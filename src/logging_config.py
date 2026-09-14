"""
Central logging configuration.

Every module should call `get_logger(__name__)` instead of using `print()`
for anything beyond simple instrumentation timing (see instrumentation.py,
which remains the dedicated latency-tracking utility).

Log level is controlled via the LOG_LEVEL env var (default INFO).
"""
import logging
import os
import sys

_CONFIGURED = False


def _configure_root():
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root = logging.getLogger("indianlawgpt")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    return logging.getLogger(f"indianlawgpt.{name}")
