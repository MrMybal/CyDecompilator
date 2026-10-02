from .core import ConnectorError, descriptors
from .cli import CliTransport
from .codex import CodexAppServer


def create_transport(connector_id, config=None, sink=None):
    descriptor = descriptors()[connector_id]
    config = config or {}
    name = config.get("transport") or descriptor["preferred_transport"]
    implemented = [t["id"] for t in descriptor["transports"] if t["implemented"]]
    if name not in implemented:
        raise ConnectorError("Unsupported", f"Transport {name} non implémenté pour {connector_id}")
    cls = CodexAppServer if name == "app-server" else CliTransport
    instance = cls(descriptor, config, sink)
    instance.name = name
    return instance
