"""One Messages API call, with a short retry for temporary failures.

Analysis and drafting used to each carry a copy of this loop. They should
not grow different backoff rules by accident.
"""

import logging
import time

import anthropic
from anthropic.types import Message

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


def message_text(message: Message) -> str:
    """Return the text of the first block, or raise if the model sent something else."""
    if not message.content:
        raise ValueError("LLM returned an empty response.")
    text = getattr(message.content[0], "text", None)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("LLM returned a non-text response.")
    return text


def create_message(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    user_prompt: str,
    max_tokens: int,
) -> Message:
    """Retry rate limits, connection errors, and 5xx. Other errors propagate.

    A bad API key or a rejected request will not succeed on a second try,
    and sleeping on those would hide the real failure.
    """
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        ) as exc:
            if attempt == _MAX_RETRIES:
                raise
            wait = 2**attempt
            logger.warning(
                "Anthropic API error (attempt %s/%s): %s. Retrying in %ss...",
                attempt,
                _MAX_RETRIES,
                exc,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError("Anthropic retries exhausted without a response")
