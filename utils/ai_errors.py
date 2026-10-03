"""Error classification, bounded retries and secret redaction for AI calls.

New file for Phase 3. It does not replace any existing utils module.
"""
from __future__ import annotations

import logging
import re
import time
from enum import Enum
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
logger = logging.getLogger("mythcode.ai")


class ErrorKind(str, Enum):
    CONFIG = "config"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    CONTEXT = "context"
    BAD_RESPONSE = "bad_response"
    UNKNOWN = "unknown"


# Only these are worth retrying. Auth, config, context and bad-response
# problems will not fix themselves, so they are never retried here.
RETRYABLE_KINDS = frozenset(
    {ErrorKind.RATE_LIMIT, ErrorKind.TIMEOUT, ErrorKind.NETWORK, ErrorKind.SERVER}
)


class MythCodeError(Exception):
    kind: ErrorKind = ErrorKind.UNKNOWN


class ConfigError(MythCodeError):
    kind = ErrorKind.CONFIG


class AIResponseError(MythCodeError):
    kind = ErrorKind.BAD_RESPONSE


_PATTERNS: list[tuple[ErrorKind, re.Pattern[str]]] = [
    (ErrorKind.CONTEXT, re.compile(
        r"context length|context window|maximum context|too many tokens|token limit|input is too long", re.I)),
    (ErrorKind.AUTH, re.compile(
        r"api key|api_key|apikey|unauthori[sz]ed|unauthenticated|permission[ _]denied|forbidden|\b401\b|\b403\b", re.I)),
    (ErrorKind.RATE_LIMIT, re.compile(
        r"rate limit|ratelimit|quota|resource[ _]exhausted|too many requests|\b429\b", re.I)),
    (ErrorKind.TIMEOUT, re.compile(r"timeout|timed out|deadline exceeded", re.I)),
    (ErrorKind.NETWORK, re.compile(r"connection|network|name resolution|unreachable|\bdns\b", re.I)),
    (ErrorKind.SERVER, re.compile(
        r"internal server error|service unavailable|overloaded|bad gateway|\b50[0234]\b", re.I)),
]

USER_MESSAGES = {
    ErrorKind.CONFIG: "The storyteller is not set up yet (missing AI settings), so a prepared scene is being used.",
    ErrorKind.AUTH: "The storyteller could not sign in with the saved key, so a prepared scene is being used.",
    ErrorKind.RATE_LIMIT: "The storyteller is busy right now (usage limit reached). A prepared scene is being used.",
    ErrorKind.TIMEOUT: "The storyteller took too long to answer, so a prepared scene is being used.",
    ErrorKind.NETWORK: "The storyteller could not be reached (connection problem). A prepared scene is being used.",
    ErrorKind.SERVER: "The storyteller's service had a problem. A prepared scene is being used.",
    ErrorKind.CONTEXT: "The story request was too long, so a prepared scene is being used.",
    ErrorKind.BAD_RESPONSE: "The storyteller's answer could not be understood, so a prepared scene is being used.",
    ErrorKind.UNKNOWN: "Something unexpected happened with the storyteller. A prepared scene is being used.",
}

_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")


def classify_exception(exc: BaseException) -> ErrorKind:
    if isinstance(exc, MythCodeError):
        return exc.kind
    text = f"{type(exc).__name__} {exc}"
    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            return kind
    return ErrorKind.UNKNOWN


def user_message(kind: ErrorKind) -> str:
    return USER_MESSAGES.get(kind, USER_MESSAGES[ErrorKind.UNKNOWN])


def redact(text: object, secrets: Iterable[str] = ()) -> str:
    out = _KEY_RE.sub("[redacted-key]", str(text))
    for secret in secrets:
        if secret and len(secret) >= 6:
            out = out.replace(secret, "[redacted]")
    return out


def log_error(exc: BaseException, context: str = "", secrets: Iterable[str] = ()) -> ErrorKind:
    """Log a technical, redacted message and return the error kind."""
    kind = classify_exception(exc)
    logger.warning("%s [%s] %s: %s", context or "AI call", kind.value,
                   type(exc).__name__, redact(exc, secrets))
    return kind


def call_with_retries(
    fn: Callable[[], T],
    max_retries: int = 2,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    secrets: Iterable[str] = (),
) -> T:
    """Call fn(); retry only retryable failures, at most max_retries times (0-3)."""
    max_retries = max(0, min(int(max_retries), 3))
    secrets = tuple(secrets)
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classified below, never swallowed
            kind = log_error(exc, f"attempt {attempt + 1}", secrets)
            if kind in RETRYABLE_KINDS and attempt < max_retries:
                sleep(base_delay * (2 ** attempt))
                attempt += 1
                continue
            raise
