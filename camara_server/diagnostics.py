"""Allowlisted JSON diagnostics; never log request/response bodies or credentials."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from uuid import uuid4

call_id = ContextVar("diagnostic_call_id", default=None)
logger = logging.getLogger('camara_server')
logger.addHandler(logging.NullHandler())
_FIELDS = {"tool", "method", "duration_ms", "lock_wait_ms", "status", "attempt", "correlator", "code", "exception_type", "cache_hit", "outcome", "count", "protocol", "stage"}

def clean(value):
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if not isinstance(value, str):
        return "<non-scalar>"
    if "PRIVATE KEY" in value:
        return "<private-key-redacted>"
    value = re.sub(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}", "<jwt-redacted>", value)
    value = re.sub(r"(?i)Bearer\s+\S+", "Bearer <redacted>", value)
    value = re.sub(r"\+[1-9][0-9]{4,14}", "<phone-redacted>", value)
    return value[:200]

class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {"time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "service": 'server', "level": record.levelname,
                "event": clean(record.msg)}
        data.update(getattr(record, "diagnostic_fields", {}))
        return json.dumps(data, ensure_ascii=False)

def event(name, level=logging.INFO, **fields):
    data = {key: clean(value) for key, value in fields.items() if key in _FIELDS}
    if call_id.get():
        data["call_id"] = call_id.get()
    logger.log(level, name, extra={"diagnostic_fields": data})

def configure(root):
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logger.setLevel(level if isinstance(level, int) else logging.INFO)
    logger.propagate = False
    formatter = JsonFormatter()
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(formatter)
    logger.addHandler(stderr)
    if os.getenv("LOG_TO_FILE", "true").lower() in {"true", "1", "yes"}:
        path = Path(os.getenv("LOG_FILE", str(Path(root) / "logs" / 'server.log')))
        if not path.is_absolute():
            path = Path(root) / path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        except OSError as error:
            event("log.file_unavailable", logging.WARNING, exception_type=type(error).__name__)
    event("process.start")

@asynccontextmanager
async def operation(name, **fields):
    token = None
    if call_id.get() is None:
        token = call_id.set(uuid4().hex)
    details = dict(fields)
    started = perf_counter()
    event(name + ".start", **details)
    try:
        yield details
    except BaseException as error:
        details.update(outcome="cancelled" if type(error).__name__ == "CancelledError" else "error",
                       exception_type=type(error).__name__)
        response = getattr(error, "response", None)
        if response is not None:
            details["status"] = response.status_code
        # Exception strings, tracebacks and locals may contain credentials.
        raise
    finally:
        details["duration_ms"] = round((perf_counter()-started)*1000, 2)
        details.setdefault("outcome", "ok")
        event(name + ".end", logging.WARNING if details["outcome"] != "ok" else logging.INFO, **details)
        if token is not None:
            call_id.reset(token)


def result_fields(result):
    payload = result.structured_content
    if not isinstance(payload, dict):
        payload = {}
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    return {"outcome": "error" if result.is_error else "ok", "code": code,
            "correlator": payload.get("correlator")}
