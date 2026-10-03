"""Shared exceptions, friendly messages and a bounded retry helper."""
import time
from typing import Callable, Tuple, Type, TypeVar

from utils.logger import get_logger, redact

T = TypeVar("T")
log = get_logger()


class MythCodeError(Exception):
    """Base class for expected application errors."""


class ConfigError(MythCodeError):
    """Missing or invalid configuration (never retried)."""


class StateValidationError(MythCodeError):
    """A proposed world change or saved state is invalid."""

    def __init__(self, issues):
        self.issues = list(issues) if not isinstance(issues, str) else [issues]
        super().__init__("; ".join(self.issues))


class StorageError(MythCodeError):
    """Saved data could not be read or written."""


class AIResponseError(MythCodeError):
    """The AI returned empty, malformed or unexpected output."""


def user_message(exc: BaseException) -> str:
    """A safe, non-technical message for the player. Never includes secrets."""
    if isinstance(exc, ConfigError):
        return f"Setup problem: {redact(str(exc))}"
    if isinstance(exc, StateValidationError):
        return "That action couldn't be applied, so your adventure was left unchanged."
    if isinstance(exc, StorageError):
        return f"This save file couldn't be loaded: {redact(str(exc))}"
    if isinstance(exc, AIResponseError):
        return "The storyteller stumbled, so a prepared scene was used instead."
    return "Something unexpected happened. Your progress was kept."


def call_with_retries(
    func: Callable[[], T],
    *,
    max_attempts: int = 2,
    retry_on: Tuple[Type[BaseException], ...] = (TimeoutError, ConnectionError),
    delay_seconds: float = 0.5,
) -> T:
    """Call func up to max_attempts times, retrying only on the listed exception types.

    ConfigError and anything not in retry_on is raised immediately.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return func()
        except ConfigError:
            raise
        except retry_on as exc:
            if attempt >= max_attempts:
                raise
            log.warning("Retrying after %s (attempt %d/%d)", type(exc).__name__, attempt, max_attempts)
            time.sleep(delay_seconds)
