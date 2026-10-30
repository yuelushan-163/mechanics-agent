from __future__ import annotations

import re
import threading
import traceback
import asyncio
import inspect
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable


_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|password|passwd|secret|access[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)
_TEXT_REDACTIONS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*(?:bearer|apikey)\s+)[^\s,;]+"),
    re.compile(
        r"(?i)((?:api[_-]?key|password|passwd|secret|access[_-]?token|"
        r"refresh[_-]?token)\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    ),
    re.compile(r"(?i)\bsk-[a-z0-9_-]{8,}\b"),
    re.compile(
        r'(?i)("(?:api[_-]?key|password|secret|token|authorization)"\s*:\s*)"[^"]*"'
    ),
)


def redact_text(value: str) -> str:
    result = value
    result = _TEXT_REDACTIONS[0].sub(r"\1[REDACTED]", result)
    result = _TEXT_REDACTIONS[1].sub(r"\1[REDACTED]", result)
    result = _TEXT_REDACTIONS[2].sub("[REDACTED]", result)
    result = _TEXT_REDACTIONS[3].sub(r'\1"[REDACTED]"', result)
    return result


def redact_value(value: Any, key: str | None = None) -> Any:
    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): redact_value(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


@dataclass(frozen=True, slots=True)
class DebugLogEntry:
    sequence: int
    timestamp: str
    level: str
    source: str
    message: str
    request_id: str | None = None
    method: str | None = None
    path: str | None = None
    status_code: int | None = None
    duration_ms: float | None = None
    details: Any = None
    traceback: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DebugLogStore:
    def __init__(
        self,
        capacity: int = 500,
        *,
        on_add: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._entries: deque[DebugLogEntry] = deque(maxlen=capacity)
        self._sequence = 0
        self._lock = threading.Lock()
        self._on_add = on_add

    def set_on_add(self, callback: Callable[[dict[str, Any]], Any] | None) -> None:
        self._on_add = callback

    def add(
        self,
        *,
        level: str,
        message: str,
        request_id: str | None = None,
        method: str | None = None,
        path: str | None = None,
        status_code: int | None = None,
        duration_ms: float | None = None,
        details: Any = None,
        traceback_text: str | None = None,
    ) -> DebugLogEntry:
        with self._lock:
            self._sequence += 1
            entry = DebugLogEntry(
                sequence=self._sequence,
                timestamp=datetime.now(timezone.utc).isoformat(),
                level=level.upper(),
                source="server",
                message=redact_text(message),
                request_id=request_id,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=round(duration_ms, 2) if duration_ms is not None else None,
                details=redact_value(details),
                traceback=redact_text(traceback_text) if traceback_text else None,
            )
            self._entries.append(entry)
        self._notify(entry)
        return entry

    def add_exception(
        self,
        exc: BaseException,
        *,
        request_id: str | None,
        method: str,
        path: str,
        duration_ms: float | None = None,
        status_code: int | None = 500,
        details: Any = None,
    ) -> DebugLogEntry:
        exception_details = {
            "exception_type": type(exc).__name__,
            **(redact_value(details) if isinstance(details, dict) else {}),
        }
        return self.add(
            level="ERROR",
            message=f"{type(exc).__name__}: {exc}",
            request_id=request_id,
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            details=exception_details,
            traceback_text="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
        )

    def list(
        self,
        *,
        after: int = 0,
        level: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        normalized_level = level.upper() if level else None
        with self._lock:
            matches = [
                item
                for item in self._entries
                if item.sequence > after
                and (normalized_level is None or item.level == normalized_level)
            ]
        return [item.to_dict() for item in matches[-limit:]]

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    @property
    def latest_sequence(self) -> int:
        with self._lock:
            return self._sequence

    def _notify(self, entry: DebugLogEntry) -> None:
        if self._on_add is None:
            return
        try:
            result = self._on_add(entry.to_dict())
            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    close = getattr(result, "close", None)
                    if close:
                        close()
                    return
                task = loop.create_task(result)
                task.add_done_callback(_consume_background_exception)
        except Exception:
            # Logging must never make the original API request fail.
            return


def _consume_background_exception(task: asyncio.Task[Any]) -> None:
    try:
        task.exception()
    except (asyncio.CancelledError, Exception):
        return
