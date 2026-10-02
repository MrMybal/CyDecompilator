import time
from collections import deque
from pathlib import Path

from .cli import CliTransport
from .core import ConnectorError
from .process import Process


class CodexAppServer(CliTransport):
    name = "app-server"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.process = None
        self.pending = deque()
        self.counter = 0

    def request(self, method, params):
        self.counter += 1
        request_id = self.counter
        self.process.send({"id": request_id, "method": method, "params": params})
        while True:
            data = self.process.next_json()
            if data.get("id") == request_id and "method" not in data:
                if "error" in data:
                    raise ConnectorError("ProtocolError", str(data["error"]))
                return data.get("result", {})
            if "method" in data and "id" in data:
                self.reject_request(data)
            else:
                self.pending.append(data)

    def reject_request(self, data):
        method = data["method"]
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            reply = {"result": {"decision": "decline"}}
        elif method == "item/permissions/requestApproval":
            reply = {"result": {"permissions": {}, "scope": "turn"}}
        else:
            reply = {"error": {"code": -32601, "message": "Unsupported by Connector Lab"}}
        self.process.send({"id": data["id"], **reply})
        self.emit("ApprovalDenied", raw=data)

    def connect(self):
        self.begin()
        started = time.monotonic()
        if self.process:
            self.disconnect()
        self.pending.clear()
        self.process = Process(self.command() + ["app-server", "--listen", "stdio://"], self)
        try:
            info = self.request("initialize", {"clientInfo": {"name": "cyai_connector_lab", "version": "0.1.0"}, "capabilities": {}})
            self.process.send({"method": "initialized", "params": {}})
            account = self.request("account/read", {"refreshToken": False})
            authenticated = bool(account.get("account"))
            self.status = "Connected"
            self.emit("Connected", raw=info)
            return {"authenticated": authenticated, "server": info, "transport": self.name}
        except Exception:
            self.disconnect()
            raise
        finally:
            self.metrics["connect_ms"] = round((time.monotonic() - started) * 1000, 2)

    def list_models(self):
        self.begin()
        if not self.process:
            self.connect()
        models, cursor, seen = [], None, set()
        while True:
            data = self.request("model/list", {"cursor": cursor} if cursor else {})
            models.extend(data.get("data", []))
            cursor = data.get("nextCursor")
            if not cursor:
                return models
            if cursor in seen:
                raise ConnectorError("ProtocolError", "Pagination de modèles cyclique")
            seen.add(cursor)

    def start_session(self, model="", native_id=None):
        self.begin()
        if not self.process:
            self.connect()
        started = time.monotonic()
        session = super().start_session(model, native_id)
        params = {"cwd": str(Path(self.config.get("cwd", ".lab/workspace")).resolve()),
                  "approvalPolicy": "never", "sandbox": "read-only"}
        if model:
            params["model"] = model
        if native_id:
            params["threadId"] = native_id
        data = self.request("thread/resume" if native_id else "thread/start", params)
        session.native_id = data["thread"]["id"]
        session.model = data.get("model", model)
        self.metrics["session_start_ms"] = round((time.monotonic() - started) * 1000, 2)
        self.emit("SessionStarted", raw=data, native_id=session.native_id, resumed=bool(native_id))
        return session

    def send(self, prompt):
        if not self.session or not self.process:
            raise ConnectorError("SessionInvalid", "Démarrez une session avant l’envoi")
        self.begin()
        self.metrics.pop("first_token_ms", None)
        self.turn_started = time.monotonic()
        self.session.status = "running"
        result = ""
        turn_id = None
        try:
            response = self.request("turn/start", {"threadId": self.session.native_id,
                                    "input": [{"type": "text", "text": prompt}],
                                    "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly"}})
            turn_id = response["turn"]["id"]
            self.emit("TurnStarted", raw=response)
            while True:
                self.check()
                data = self.pending.popleft() if self.pending else self.process.next_json()
                method, params = data.get("method", ""), data.get("params", {})
                if "method" in data and "id" in data:
                    self.reject_request(data)
                    continue
                if params.get("threadId") and params["threadId"] != self.session.native_id:
                    continue
                if method == "item/agentMessage/delta":
                    self.emit("TextDelta", params.get("delta", ""), data)
                elif method in {"item/reasoning/textDelta", "item/reasoning/summaryTextDelta"}:
                    self.emit("ThinkingDelta", params.get("delta", ""), data)
                elif method in {"item/started", "item/completed"}:
                    item = params.get("item", {})
                    done = method.endswith("completed")
                    kind = item.get("type")
                    if done and kind == "agentMessage":
                        result += item.get("text", "")
                    event = {"commandExecution": "CommandCompleted" if done else "CommandStarted",
                             "fileChange": "FileChanged" if done else "ToolStarted",
                             "mcpToolCall": "ToolCompleted" if done else "ToolStarted"}.get(kind, "ProviderEvent")
                    self.emit(event, raw=data, item=item)
                elif method == "thread/tokenUsage/updated":
                    self.emit("UsageUpdated", raw=data, usage=params.get("tokenUsage", {}))
                elif method == "turn/completed" and params.get("turn", {}).get("id") == turn_id:
                    turn = params["turn"]
                    if turn.get("status") != "completed":
                        raise ConnectorError("ProviderError", str(turn.get("error") or turn.get("status")))
                    self.session.status = "completed"
                    self.emit("TurnCompleted", result, data)
                    return result
                elif method == "error":
                    self.emit("ProviderError", raw=data)
                else:
                    self.emit("ProviderEvent", raw=data, provider_type=method)
        except Exception:
            self.session.status = "cancelled" if self.cancelled.is_set() else "error"
            # Closing the owned server also cleans up an unresponsive/cancelled turn.
            self.disconnect()
            raise
        finally:
            self.metrics["total_ms"] = round((time.monotonic() - self.turn_started) * 1000, 2)
