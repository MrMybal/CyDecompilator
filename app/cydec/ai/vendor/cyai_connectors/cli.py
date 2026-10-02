import json
import time

from .core import ConnectorError, Transport
from .process import Process, probe, resolve


class CliTransport(Transport):
    name = "cli-jsonl"

    def command(self):
        discovery = self.descriptor["discovery"]
        return resolve(discovery["executables"], self.config.get("executable", ""), discovery.get("paths", []))

    def detect(self):
        self.begin()
        started = time.monotonic()
        try:
            command = self.command()
            code, out, err = probe(command + ["--version"], self)
            self.status = "Installed" if code == 0 else "Error"
            return {"status": self.status, "command": command, "version": out.strip() or err.strip(),
                    "authenticated": "unknown", "exit_code": code}
        except ConnectorError as exc:
            self.status = "Executable Missing" if exc.code == "ExecutableMissing" else "Error"
            return {"status": self.status, "error": str(exc), "code": exc.code, "authenticated": "unknown"}
        finally:
            self.metrics["detection_ms"] = round((time.monotonic() - started) * 1000, 2)

    def connect(self):
        self.begin()
        command = self.command()
        auth = {"claude-code": ["auth", "status"], "codex": ["login", "status"]}.get(self.id)
        if not auth:
            self.status = "Installed"
            return {"authenticated": "unknown", "detail": "Vérification par un envoi réel nécessaire"}
        code, out, err = probe(command + auth, self)
        if self.id == "claude-code":
            try:
                authenticated = code == 0 and json.loads(out).get("loggedIn") is True
            except ValueError:
                raise ConnectorError("MalformedJSON", "Statut d’authentification illisible")
        else:
            authenticated = code == 0
        self.status = "Connected" if authenticated else "Authentication Required"
        # Auth outputs contain account identity. Keep only the diagnostic conclusion.
        result = {"authenticated": authenticated, "exit_code": code}
        if not authenticated:
            result["detail"] = self.redactor.clean(err[-1500:] or "Connexion au compte requise via le CLI")
        return result

    def list_models(self):
        self.begin()
        args = {"opencode": ["models"], "antigravity": ["models"]}.get(self.id)
        if not args:
            raise ConnectorError("Unsupported", "Ce transport n’expose pas de catalogue ; saisissez un ID de modèle.")
        code, out, err = probe(self.command() + args, self)
        self.capture("models", out)
        if code:
            raise ConnectorError("ModelDiscoveryFailed", err or out)
        if self.id == "opencode":
            return [{"id": s.strip()} for s in out.splitlines() if "/" in s and " " not in s.strip()]
        try:
            data = json.loads(out)
            rows = data if isinstance(data, list) else data.get("models", data.get("data", []))
            return [{"id": row} if isinstance(row, str) else row for row in rows]
        except ValueError:
            return [{"id": s.split("\t")[0], "name": s.split("\t")[-1]} for s in out.splitlines() if "\t" in s]

    def arguments(self, prompt):
        model, native = self.session.model, self.session.native_id
        env = {}
        if self.id == "claude-code":
            args = ["-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                    "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                    "--permission-mode", "dontAsk", "--disable-slash-commands", "--setting-sources", ""]
            if native:
                args += ["--resume", native]
            input_text = prompt
        elif self.id == "opencode":
            args = ["run", "--format", "json"]
            if native:
                args += ["--session", native]
            args += ["--", prompt]
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"permission": {"*": "deny"}})
            input_text = ""
        elif self.id == "antigravity":
            args = ["--input-format", "stream-json", "--output-format", "stream-json"]
            if native:
                args += ["--conversation", native]
            input_text = json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
        elif self.id == "codex":
            args = ["exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only"]
            if native:
                # Resume has its own argument parser; global policy precedes the subcommand.
                args = ["--sandbox", "read-only", "exec", "resume", "--json", "--skip-git-repo-check", native]
            args += ["-"]
            input_text = prompt
        else:
            raise ConnectorError("Unsupported", "Adaptateur non implémenté")
        if model:
            if "--" in args:
                index = args.index("--")
                args[index:index] = ["--model", model]
            elif self.id == "codex":
                args[-1:-1] = ["--model", model]
            else:
                args += ["--model", model]
        return self.command() + args, input_text, env

    def send(self, prompt):
        if self.session is None:
            raise ConnectorError("SessionInvalid", "Démarrez une session avant l’envoi")
        self.begin()
        self.metrics.pop("first_token_ms", None)
        self.turn_started = time.monotonic()
        self.session.status = "running"
        self.emit("TurnStarted")
        args, input_text, env = self.arguments(prompt)
        process = Process(args, self, input_text, env)
        self.process = process
        self.metrics["startup_ms"] = round((time.monotonic() - self.turn_started) * 1000, 2)
        result = ""
        partial = ""
        completed = False
        try:
            while True:
                line = process.next_line()
                if line is None:
                    break
                channel, line_text = line
                if channel == "stderr":
                    self.capture(channel, line_text)
                    continue
                try:
                    data = json.loads(line_text)
                except ValueError as exc:
                    self.capture(channel, line_text)
                    raise ConnectorError("MalformedJSON", line_text[:500]) from exc
                self.capture(channel, data)
                if not isinstance(data, dict):
                    raise ConnectorError("MalformedJSON", "Objet événement attendu")
                kind = data.get("type", data.get("event", ""))
                payload = data.get("result", {}) if self.id == "antigravity" and kind == "result" else data
                if not isinstance(payload, dict):
                    payload = data
                sid = payload.get("session_id") or payload.get("sessionID") or payload.get("conversation_id") or payload.get("thread_id")
                if sid and sid != self.session.native_id:
                    self.session.native_id = sid
                    self.emit("SessionStarted", raw=data, native_id=sid)
                text = ""
                if kind == "stream_event":
                    event = data.get("event", {})
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                    elif delta.get("type") == "thinking_delta":
                        self.emit("ThinkingDelta", delta.get("thinking", ""), data)
                elif kind == "step_update":
                    step = data.get("step_update", {})
                    text = step.get("text_delta", "")
                    if step.get("tool_info"):
                        self.emit("ToolCompleted" if step.get("state") == "DONE" else "ToolStarted", raw=data, tool=step["tool_info"])
                elif kind == "text":
                    text = data.get("part", {}).get("text", "")
                elif kind == "item.completed":
                    item = data.get("item", {})
                    if item.get("type") == "agent_message":
                        result += item.get("text", "")
                        self.emit("TextSnapshot", item.get("text", ""), data)
                    elif item.get("type") == "command_execution":
                        self.emit("CommandCompleted", raw=data, command=item)
                    elif item.get("type") == "file_change":
                        self.emit("FileChanged", raw=data, file=item)
                elif kind == "result":
                    if payload.get("is_error") or payload.get("status", payload.get("subtype", "success")) not in {"success", "SUCCESS"}:
                        raise ConnectorError("ProviderError", str(payload.get("error") or payload.get("errors") or payload))
                    result = payload.get("response", payload.get("result", ""))
                    completed = True
                    if payload.get("usage"):
                        self.emit("UsageUpdated", raw=data, usage=payload["usage"])
                elif kind == "turn.completed":
                    completed = True
                    self.emit("UsageUpdated", raw=data, usage=data.get("usage", {}))
                elif kind == "step_finish":
                    reason = data.get("part", {}).get("reason")
                    if reason == "stop":
                        completed = True
                        result = partial
                    self.emit("UsageUpdated", raw=data, usage=data.get("part", {}).get("tokens", {}))
                elif kind in {"error", "turn.failed"}:
                    raise ConnectorError("ProviderError", str(data))
                else:
                    self.emit("ProviderEvent", raw=data, provider_type=kind)
                if text:
                    partial += text
                    self.emit("TextDelta", text, data)
            process.proc.wait(timeout=2)
            if process.proc.returncode:
                raise ConnectorError("ProcessCrash", "\n".join(process.errors[-6:]) or f"Code de sortie {process.proc.returncode}")
            if not completed:
                raise ConnectorError("UnexpectedEOF", "Flux fermé sans confirmation finale du fournisseur")
            self.check()
            self.session.status = "completed"
            self.status = "Connected"
            self.emit("TurnCompleted", text=result)
            return result
        except Exception:
            self.session.status = "cancelled" if self.cancelled.is_set() else "error"
            raise
        finally:
            self.metrics["total_ms"] = round((time.monotonic() - self.turn_started) * 1000, 2)
            process.close()
            self.process = None

    def disconnect(self):
        process = getattr(self, "process", None)
        if process:
            process.close()
            self.process = None
        self.status = "Disconnected"
        self.emit("Disconnected")
