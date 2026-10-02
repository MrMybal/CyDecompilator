"""Bounded process IO and shell-free Windows npm resolution."""
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
from pathlib import Path

from .core import ConnectorError

NPM = {"codex": "@openai/codex/bin/codex.js", "claude": "@anthropic-ai/claude-code/cli.js",
       "opencode": "opencode-ai/bin/opencode"}


def resolve(names, configured="", paths=()):
    candidates = [configured] if configured else [*names, *paths]
    for candidate in candidates:
        if not candidate:
            continue
        candidate = os.path.expandvars(os.path.expanduser(candidate))
        found = shutil.which(candidate)
        if not found and Path(candidate).is_file():
            found = str(Path(candidate).resolve())
        if not found:
            continue
        path = Path(found)
        if path.suffix.lower() in {".cmd", ".ps1", ".bat"}:
            native = path.parent / "node_modules/@anthropic-ai/claude-code/bin/claude.exe"
            if path.stem == "claude" and native.is_file():
                return [str(native)]
            script = path.parent / "node_modules" / NPM.get(path.stem, "__unsupported__")
            if script.is_file() and shutil.which("node"):
                return [shutil.which("node"), str(script)]
            continue
        return [str(path)]
    raise ConnectorError("ExecutableMissing", "Exécutable CLI absent ou shim non reconnu ; configurez un chemin natif.")


class Process:
    def __init__(self, argv, owner, input_text=None, env=None):
        owner.check()
        self.owner = owner
        self.queue = queue.Queue()
        self.closed_streams = 0
        self.errors = []
        process_env = os.environ.copy()
        process_env.update(env or {})
        root = Path(owner.config.get("cwd", ".lab/workspace")).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(argv, cwd=root, env=process_env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     encoding="utf-8", errors="replace", bufsize=1,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                     start_new_session=os.name != "nt")
        self.readers = []
        for channel, stream in (("stdout", self.proc.stdout), ("stderr", self.proc.stderr)):
            thread = threading.Thread(target=self._read, args=(channel, stream), daemon=True)
            thread.start()
            self.readers.append(thread)
        if input_text is not None:
            if input_text:
                self.proc.stdin.write(input_text)
                self.proc.stdin.flush()
            self.proc.stdin.close()

    def _read(self, channel, stream):
        try:
            for line in stream:
                self.queue.put((channel, line.rstrip("\r\n")))
        finally:
            self.queue.put((channel, None))

    def next_line(self):
        while self.closed_streams < 2:
            self.owner.check()
            try:
                channel, line = self.queue.get(timeout=.05)
            except queue.Empty:
                continue
            if line is None:
                self.closed_streams += 1
                continue
            if channel == "stderr":
                self.errors.append(line)
            return channel, line
        return None

    def send(self, value):
        self.owner.check()
        self.owner.capture("stdin", value)
        try:
            self.proc.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ConnectorError("ProcessCrash", str(exc)) from exc

    def next_json(self):
        while True:
            line = self.next_line()
            if line is None:
                raise ConnectorError("UnexpectedEOF", "Processus terminé sans résultat : " + "\n".join(self.errors[-4:]))
            channel, value = line
            if channel == "stderr":
                self.owner.capture(channel, value)
                continue
            try:
                data = json.loads(value)
            except ValueError as exc:
                self.owner.capture(channel, value)
                raise ConnectorError("MalformedJSON", "Sortie non JSON : " + value[:200]) from exc
            self.owner.capture(channel, data)
            if not isinstance(data, dict):
                raise ConnectorError("MalformedJSON", "Un événement doit être un objet JSON")
            return data

    def close(self):
        if self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                               capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        for reader in self.readers:
            reader.join(timeout=1)
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if not stream.closed:
                stream.close()


def probe(argv, owner):
    process = Process(argv, owner, input_text="")
    stdout, stderr = [], []
    try:
        while (line := process.next_line()) is not None:
            (stdout if line[0] == "stdout" else stderr).append(line[1])
        process.proc.wait(timeout=2)
        return process.proc.returncode, "\n".join(stdout), "\n".join(stderr)
    finally:
        process.close()
