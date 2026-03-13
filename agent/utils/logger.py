"""Structured logging utilities for the research agent."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional


def get_logger(name: str, config: Optional[dict] = None) -> logging.Logger:
    """Return a named logger configured according to *config*.

    Parameters
    ----------
    name:
        Logger name (usually ``__name__`` of the calling module).
    config:
        Optional dict with keys ``level``, ``file``, ``max_bytes``,
        ``backup_count``.  Falls back to sensible defaults when absent.
    """
    cfg = config or {}
    level_name: str = cfg.get("level", "INFO")
    log_file: str = cfg.get("file", "logs/agent.log")
    max_bytes: int = int(cfg.get("max_bytes", 10 * 1024 * 1024))
    backup_count: int = int(cfg.get("backup_count", 5))

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level_name.upper(), logging.INFO))

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Rotating file handler
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger
