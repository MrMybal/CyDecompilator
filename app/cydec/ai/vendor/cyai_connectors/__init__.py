"""Portable connector library. No dependency on the desktop application."""
from .core import ConnectorError, Event, Session, Transport, descriptors
from .registry import create_transport

__all__ = ["ConnectorError", "Event", "Session", "Transport", "descriptors", "create_transport"]
