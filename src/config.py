"""Load local settings and explain a missing credential.

Environment variables win over `.env`, which is how `make demo` turns on demo
mode without editing the file. Values copied straight from `.env.example`
count as unset.
"""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from src.models import resolve_sender_name

logger = logging.getLogger(__name__)

# These strings are documentation in .env.example, not credentials.
ANTHROPIC_PLACEHOLDERS = frozenset({"your-anthropic-api-key"})
GMAIL_ADDRESS_PLACEHOLDERS = frozenset({"you@gmail.com"})
GMAIL_PASSWORD_PLACEHOLDERS = frozenset({"your-16-character-app-password"})

ANTHROPIC_KEY_MESSAGE = (
    "No Anthropic API key is set. Copy .env.example to .env and replace "
    "your-anthropic-api-key, or paste a key in the sidebar. "
    "That example value is not a key. "
    "To walk through the app with no key and no network, turn on Demo mode or run make demo."
)

GMAIL_MISSING_MESSAGE = (
    "Gmail is not configured, so nothing was sent. Add GMAIL_ADDRESS and "
    "GMAIL_APP_PASSWORD in the sidebar or in .env. "
    "Use a Gmail app password from your Google account security settings, "
    "not your normal Gmail password. "
    "The example values you@gmail.com and your-16-character-app-password are not credentials. "
    "Demo mode can record a practice send without Gmail."
)

_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class ConfigError(Exception):
    """Raised when a live run is missing a credential it cannot proceed without."""


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_unset(value: str | None, placeholders: frozenset[str]) -> bool:
    """Return True when a setting is blank or still an example placeholder."""
    text = (value or "").strip()
    return text == "" or text.lower() in placeholders


def anthropic_key_is_unset(value: str | None) -> bool:
    """Return True when the Anthropic key is missing or still the example value."""
    return is_unset(value, ANTHROPIC_PLACEHOLDERS)


def gmail_is_unset(address: str | None, password: str | None) -> bool:
    """Return True when either Gmail setting is missing or still an example value."""
    return is_unset(address, GMAIL_ADDRESS_PLACEHOLDERS) or is_unset(
        password, GMAIL_PASSWORD_PLACEHOLDERS
    )


@dataclass(frozen=True)
class Settings:
    """Process configuration. Secrets stay in the environment, not in code."""

    demo_mode: bool
    anthropic_api_key: str
    gmail_address: str
    gmail_app_password: str
    sender_name: str
    log_level: str


def load_settings() -> Settings:
    """Load `.env` if it exists, then read the process environment.

    Variables already set in the process are left alone. `make demo` relies
    on that so it can force demo mode for one run.
    """
    load_dotenv()
    level = (os.getenv("LOG_LEVEL", "INFO").strip() or "INFO").upper()
    if level not in _LOG_LEVELS:
        level = "INFO"
    return Settings(
        demo_mode=_truthy(os.getenv("DEMO_MODE")),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        gmail_address=os.getenv("GMAIL_ADDRESS", "").strip(),
        gmail_app_password=os.getenv("GMAIL_APP_PASSWORD", "").strip(),
        sender_name=resolve_sender_name(),
        log_level=level,
    )


def require_anthropic_api_key(api_key: str) -> str:
    """Return a usable key, or raise ConfigError with setup instructions."""
    if anthropic_key_is_unset(api_key):
        logger.error("Anthropic API key is missing or still the example placeholder.")
        raise ConfigError(ANTHROPIC_KEY_MESSAGE)
    return api_key.strip()


def configure_logging(level: str | None = None) -> None:
    """Send library logs to stderr. Unknown levels fall back to INFO."""
    chosen = level if level else os.getenv("LOG_LEVEL", "INFO")
    if not isinstance(chosen, str) or not chosen.strip():
        chosen = "INFO"
    resolved = chosen.strip().upper() or "INFO"
    logging.basicConfig(
        level=_LOG_LEVELS.get(resolved, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
