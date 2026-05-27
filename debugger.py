"""
debugger.py – Structured logging & debug utilities for eThute Lenna.
"""

import logging
import sys
from datetime import datetime


class DebugLogger:
    LOG_FORMAT  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    DATE_FORMAT = "%H:%M:%S"

    def __init__(self, level: int = logging.INFO):
        self.level = level
        self._configure_root()

    def _configure_root(self):
        root = logging.getLogger()
        root.setLevel(self.level)
        root.handlers.clear()
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(self.level)
        handler.setFormatter(logging.Formatter(self.LOG_FORMAT, datefmt=self.DATE_FORMAT))
        root.addHandler(handler)

    def get_logger(self, name: str) -> logging.Logger:
        return logging.getLogger(name)


class EventTracker:
    def __init__(self, max_events: int = 100):
        self.max_events = max_events
        self._events: list[str] = []

    def log(self, category: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] [{category}] {message}"
        self._events.append(entry)
        if len(self._events) > self.max_events:
            self._events.pop(0)

    def recent(self, n: int = 20) -> list[str]:
        return self._events[-n:]

    def clear(self):
        self._events.clear()

    def all(self) -> list[str]:
        return list(self._events)
