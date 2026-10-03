"""Logging with API-key redaction. Console only (Community Cloud has no durable disk)."""
import logging
import re

_SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(api[_-]?key\s*[=:]\s*)[^\s,;'\"]+", re.IGNORECASE),
]


def redact(text: str) -> str:
    """Remove anything that looks like an API key from a string."""
    text = _SECRET_PATTERNS[0].sub("[REDACTED]", text)
    return _SECRET_PATTERNS[1].sub(r"\1[REDACTED]", text)


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def get_logger(name: str = "mythcode") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(_RedactFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
