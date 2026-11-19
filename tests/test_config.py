"""Settings, placeholder secrets, and logging setup."""

import logging

from src.config import (
    ANTHROPIC_KEY_MESSAGE,
    ConfigError,
    anthropic_key_is_unset,
    configure_logging,
    gmail_is_unset,
    load_settings,
    require_anthropic_api_key,
)


def test_demo_flag_accepts_common_true_values(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "yes")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your-anthropic-api-key")
    monkeypatch.setenv("LOG_LEVEL", "not-a-level")
    settings = load_settings()
    assert settings.demo_mode is True
    assert settings.log_level == "INFO"
    assert anthropic_key_is_unset(settings.anthropic_api_key)


def test_live_mode_keeps_a_real_key(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-value")
    monkeypatch.setenv("GMAIL_ADDRESS", "person@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcdefghijklmnop")
    settings = load_settings()
    assert settings.demo_mode is False
    assert settings.anthropic_api_key == "sk-test-value"
    assert gmail_is_unset(settings.gmail_address, settings.gmail_app_password) is False


def test_example_gmail_values_count_as_unset():
    assert gmail_is_unset("you@gmail.com", "abcdefghijklmnop") is True
    assert gmail_is_unset("person@gmail.com", "your-16-character-app-password") is True
    assert gmail_is_unset("", "") is True


def test_require_key_rejects_the_placeholder():
    try:
        require_anthropic_api_key(" your-anthropic-api-key ")
    except ConfigError as exc:
        assert str(exc) == ANTHROPIC_KEY_MESSAGE
    else:
        raise AssertionError("placeholder key was accepted")
    assert require_anthropic_api_key("  sk-test  ") == "sk-test"


def test_configure_logging_accepts_an_unknown_level():
    configure_logging("NOPE")
    assert logging.getLogger().level == logging.INFO
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
    configure_logging("INFO")
