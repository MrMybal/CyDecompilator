from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def now():
    return datetime.now(timezone.utc).isoformat()


def descriptors():
    result = {}
    for path in sorted((Path(__file__).parent / "descriptors").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema_version"] != "1.0":
            raise ValueError(f"Unsupported descriptor version: {path}")
        if data["id"] in result:
            raise ValueError(f"Duplicate connector: {data['id']}")
        result[data["id"]] = data
    return result


class ConnectorError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class Redactor:
    """Preserve provider structure, replacing credentials before display or storage."""
    sensitive = re.compile(r"authorization|api[_-]?key|password|secret|(?:access|refresh|id)[_-]?token|cookie", re.I)

    def __init__(self):
        self.values = [v for k, v in os.environ.items() if self.sensitive.search(k) and len(v) >= 8]

    def clean(self, value):
        if isinstance(value, dict):
            return {k: "[REDACTED]" if self.sensitive.search(k) else self.clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for secret in self.values:
                value = value.replace(secret, "[REDACTED]")
            value = re.sub(r"\bsk-[A-Za-z0-9_-]{10,}", "[REDACTED]", value)
            value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", value)
            value = re.sub(r'(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)[\"\s]*[:=]\s*[\"]?)[^\s\",}]+', r'\1[REDACTED]', value)
        return value


@dataclass
class Event:
    type: str
    connector_id: str
    session_id: str | None = None
    timestamp: str = field(default_factory=now)
    text: str = ""
    raw_payload: Any = None
    metadata: dict = field(default_factory=dict)
    schema_version: str = "1.0"


@dataclass
class Session:
    connector_id: str
    transport: str
    model: str = ""
    local_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    native_id: str | None = None
    created: str = field(default_factory=now)
    status: str = "created"


class Transport(ABC):
    def __init__(self, descriptor, config=None, sink: Callable | None = None):
        self.descriptor = descriptor
        self.id = descriptor["id"]
        self.config = config or {}
        self.sink = sink or (lambda channel, value: None)
        self.redactor = Redactor()
        self.events = []
        self.raw = []
        self.session = None
        self.cancelled = threading.Event()
        self.deadline = float("inf")
        self.status = "Not Configured"
        self.metrics = {}
        self.turn_started = None

    def begin(self):
        self.cancelled.clear()
        self.deadline = time.monotonic() + float(self.config.get("timeout", 90))

    def check(self):
        if self.cancelled.is_set():
            raise ConnectorError("Cancelled", "Opération annulée")
        if time.monotonic() >= self.deadline:
            raise ConnectorError("Timeout", "Délai de réponse dépassé")

    def capture(self, channel, payload):
        record = {"timestamp": now(), "channel": channel, "payload": self.redactor.clean(payload)}
        self.raw.append(record)
        self.sink("raw", record)

    def emit(self, kind, text="", raw=None, **metadata):
        if kind == "TextDelta" and text and self.turn_started is not None:
            self.metrics.setdefault("first_token_ms", round((time.monotonic() - self.turn_started) * 1000, 2))
        event = Event(kind, self.id, self.session.local_id if self.session else None,
                      text=text, raw_payload=raw, metadata=metadata)
        value = self.redactor.clean(asdict(event))
        self.events.append(value)
        self.sink("event", value)
        return value

    def start_session(self, model="", native_id=None):
        if native_id and self.descriptor["capabilities"].get("resume") != "declared":
            raise ConnectorError("Unsupported", "Reprise native non disponible")
        self.session = Session(self.id, self.name, model, native_id=native_id)
        return self.session

    def resume_session(self, native_id, model=""):
        if not native_id:
            raise ConnectorError("SessionInvalid", "Identifiant natif explicite requis")
        return self.start_session(model, native_id)

    def cancel(self):
        self.cancelled.set()

    def get_status(self):
        return self.status

    def get_capabilities(self):
        return self.descriptor["capabilities"]

    @abstractmethod
    def detect(self): ...

    @abstractmethod
    def connect(self): ...

    @abstractmethod
    def list_models(self): ...

    @abstractmethod
    def send(self, prompt): ...

    @abstractmethod
    def disconnect(self): ...
