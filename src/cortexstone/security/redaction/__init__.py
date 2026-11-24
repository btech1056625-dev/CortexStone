"""Secret redaction for data crossing model, persistence, audit, and logging boundaries."""

import logging
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

_SECRET_NAMES = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "clientsecret",
    "apikey",
    "token",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "authorization",
    "credential",
    "privatekey",
    "connectionstring",
    "databaseurl",
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>\b(?:password|passwd|pwd|secret|client[_-]?secret|"
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|"
    r"authorization|credential|private[_-]?key|connection[_-]?string|database[_-]?url)"
    r"\b\s*[:=]\s*)(?P<quote>[\"'])(?P<quoted>[^\r\n]*?)(?P=quote)"
    r"|(?P<plain_prefix>\b(?:password|passwd|pwd|secret|client[_-]?secret|"
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|"
    r"authorization|credential|private[_-]?key|connection[_-]?string|database[_-]?url)"
    r"\b\s*[:=]\s*)(?P<plain>[^\s,;]+)"
)
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_URL_CREDENTIALS = re.compile(r"(?i)(?P<prefix>\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)(?P<secret>[^@\s]+)@")
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_AUTH_HEADER = re.compile(
    r"(?i)(?P<prefix>\b(?:authorization|proxy-authorization)\s*[:=]\s*)"
    r"(?:Bearer|Basic)\s+[A-Za-z0-9._~+/-]+=*"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
_KNOWN_TOKEN = re.compile(
    r"\b(?:"
    r"AKIA[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|glpat-[A-Za-z0-9_-]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AIza[0-9A-Za-z_-]{30,}"
    r"|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{12,}"
    r"|sk-(?:proj-)?[A-Za-z0-9_-]{20,}"
    r")\b"
)


def _is_secret_name(name: object) -> bool:
    if not isinstance(name, str):
        return False
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return any(
        normalized == secret_name or normalized.endswith(secret_name)
        for secret_name in _SECRET_NAMES
    )


def redact_secrets(text: str) -> str:
    """Redact supported credential patterns in text; unmatched secret formats may remain."""
    redacted = _PEM_PRIVATE_KEY.sub(REDACTED, text)
    redacted = _AUTH_HEADER.sub(lambda match: f"{match.group('prefix')}{REDACTED}", redacted)
    redacted = _BEARER_TOKEN.sub(f"Bearer {REDACTED}", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}{REDACTED}{match.group('quote')}"
            if match.group("prefix") is not None
            else f"{match.group('plain_prefix')}{REDACTED}"
        ),
        redacted,
    )
    redacted = _URL_CREDENTIALS.sub(lambda match: f"{match.group('prefix')}{REDACTED}@", redacted)
    redacted = _JWT.sub(REDACTED, redacted)
    return _KNOWN_TOKEN.sub(REDACTED, redacted)


def redact_value(value: Any, *, key: object = None) -> Any:
    """Recursively redact strings and values held under credential-like mapping keys."""
    if _is_secret_name(key):
        return REDACTED
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, Mapping):
        return {name: redact_value(item, key=name) for name, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


class RedactingLogFilter(logging.Filter):
    """Redact credential patterns from log messages, exception traces, and extra fields."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact_secrets(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact_secrets(record.stack_info)
        for name, value in vars(record).items():
            if name not in {"msg", "args", "exc_info", "exc_text", "stack_info"}:
                setattr(record, name, redact_value(value, key=name))
        return True


def configure_redacting_logging() -> None:
    """Install redaction on all logging handlers already configured in this process."""
    loggers = [logging.getLogger()]
    loggers.extend(
        logger
        for logger in logging.root.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    )
    for logger in loggers:
        for handler in logger.handlers:
            if not any(isinstance(item, RedactingLogFilter) for item in handler.filters):
                handler.addFilter(RedactingLogFilter())
