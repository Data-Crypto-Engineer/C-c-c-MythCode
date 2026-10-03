from utils.config import parse_settings
from utils.error_handler import ConfigError, call_with_retries
from utils.logger import redact


def test_missing_credentials_give_clear_errors():
    for raw in ({}, {"provider": "gemini", "model": "m"}, {"provider": "gemini", "model": "m", "api_key": "YOUR_API_KEY"},
                {"provider": "gemini", "api_key": "k"}, {"provider": "other", "model": "m", "api_key": "k"}):
        try:
            parse_settings(raw)
            assert False, raw
        except ConfigError as exc:
            assert "k" != str(exc)


def test_valid_settings_hide_key_in_repr():
    s = parse_settings({"provider": "Gemini", "model": "m", "api_key": "secret-value"})
    assert s.provider == "gemini" and "secret-value" not in repr(s)


def test_retry_is_bounded_and_selective():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        raise TimeoutError("slow")

    try:
        call_with_retries(flaky, max_attempts=3, delay_seconds=0)
        assert False
    except TimeoutError:
        assert calls["n"] == 3

    calls["n"] = 0

    def bad_config():
        calls["n"] += 1
        raise ConfigError("nope")

    try:
        call_with_retries(bad_config, max_attempts=3, delay_seconds=0)
    except ConfigError:
        assert calls["n"] == 1


def test_retry_succeeds_after_transient_failure():
    seq = iter([ConnectionError("x"), "ok"])

    def f():
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v

    assert call_with_retries(f, max_attempts=2, delay_seconds=0) == "ok"


def test_logs_redact_keys():
    assert "AIza" not in redact("key AIzaSyA1234567890abcdefghijkl failed")
    assert "abc123" not in redact("api_key=abc123 failed")
