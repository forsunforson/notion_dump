"""
Local, durable, structured debug logging.

This module provides a lightweight logger that writes NDJSON events to the local
filesystem with log levels and rotation. Debug enablement is controlled via a
persisted state file so the setting survives process restarts.

Environment variables:
- LOCAL_DEBUG_LOG_PATH: Override log file path (default: ./logs/debug.log)
- LOCAL_DEBUG_STATE_PATH: Override persisted state file path (default: ./logs/debug_state.json)
- LOCAL_DEBUG_MAX_BYTES: Override rotation size in bytes (default: 10485760)
- LOCAL_DEBUG_BACKUP_COUNT: Override rotation backup count (default: 5)
- LOCAL_DEBUG_ENABLED: Optional override ("1/0", "true/false") taking precedence over state file
- LOCAL_DEBUG_SESSION_ID: Optional default session id (default: "local-debug")
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping

_CACHE_LOCK = threading.Lock()
_LOGGER_BY_PATH: dict[str, logging.Logger] = {}


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        n = int(raw)
    except Exception:
        return default
    return n if n > 0 else default


def _get_or_create_logger(log_path: Path, *, max_bytes: int, backup_count: int) -> logging.Logger:
    key = str(log_path.resolve())
    with _CACHE_LOCK:
        existing = _LOGGER_BY_PATH.get(key)
        if existing is not None:
            return existing

        logger = logging.getLogger(f"local_debug_logger:{key}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

        _LOGGER_BY_PATH[key] = logger
        return logger


def _load_enabled_from_state(state_path: Path) -> bool:
    try:
        raw = state_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return False
    except Exception:
        return False

    if not raw:
        return False

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            enabled = obj.get("enabled")
            if isinstance(enabled, bool):
                return enabled
            if isinstance(enabled, str):
                parsed = _parse_bool(enabled)
                return bool(parsed) if parsed is not None else False
        if isinstance(obj, bool):
            return obj
    except Exception:
        parsed = _parse_bool(raw)
        return bool(parsed) if parsed is not None else False

    return False


def _normalize_level(level: int | str) -> int:
    if isinstance(level, int):
        return level
    name = level.strip().upper()
    if name == "WARN":
        name = "WARNING"
    return logging._nameToLevel.get(name, logging.DEBUG)


class LocalDebugLogger:
    def __init__(
        self,
        *,
        session_id: str | None = None,
        log_path: str | Path | None = None,
        state_path: str | Path | None = None,
        max_bytes: int | None = None,
        backup_count: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._session_id = (
            (session_id or os.getenv("LOCAL_DEBUG_SESSION_ID") or "local-debug").strip() or "local-debug"
        )
        self._log_path = Path(
            log_path
            or os.getenv("LOCAL_DEBUG_LOG_PATH")
            or os.path.join(".", "logs", "debug.log")
        )
        self._state_path = Path(
            state_path
            or os.getenv("LOCAL_DEBUG_STATE_PATH")
            or os.path.join(".", "logs", "debug_state.json")
        )
        self._max_bytes = max_bytes if max_bytes is not None else _env_int("LOCAL_DEBUG_MAX_BYTES", 10 * 1024 * 1024)
        self._backup_count = backup_count if backup_count is not None else _env_int("LOCAL_DEBUG_BACKUP_COUNT", 5)
        self._enabled_override = enabled

        self._seq_lock = threading.Lock()
        self._seq = 0
        self._logger = _get_or_create_logger(
            self._log_path,
            max_bytes=self._max_bytes,
            backup_count=self._backup_count,
        )

    def is_enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        env_override = _parse_bool(os.getenv("LOCAL_DEBUG_ENABLED"))
        if env_override is not None:
            return env_override
        return _load_enabled_from_state(self._state_path)

    def emit(self, name: str, payload: Mapping[str, Any], *, level: int | str = "DEBUG") -> None:
        if not self.is_enabled():
            return
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        level_no = _normalize_level(level)
        event = {
            "sessionId": self._session_id,
            "name": name,
            "seq": seq,
            "ts": int(time.time() * 1000),
            "level": logging.getLevelName(level_no),
            "payload": payload,
        }
        try:
            self._logger.log(level_no, json.dumps(event, ensure_ascii=False))
        except Exception:
            return

    def debug(self, name: str, payload: Mapping[str, Any]) -> None:
        self.emit(name, payload, level="DEBUG")

    def info(self, name: str, payload: Mapping[str, Any]) -> None:
        self.emit(name, payload, level="INFO")

    def warning(self, name: str, payload: Mapping[str, Any]) -> None:
        self.emit(name, payload, level="WARNING")

    def error(self, name: str, payload: Mapping[str, Any]) -> None:
        self.emit(name, payload, level="ERROR")
