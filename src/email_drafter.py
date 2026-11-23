"""Draft one cold email from the analysis notes.

Tone is a closed set so the UI and the prompt cannot drift apart. The
sign-off uses the configured sender name and does not invent a company.
"""

import logging

import anthropic

from src.config import require_anthropic_api_key
from src.llm_client import create_message, message_text
from src.llm_json import parse_llm_json
from src.models import DEFAULT_MODEL, EmailDraft, NeedAnalysis, resolve_sender_name
from src.prompts import EMAIL_SYSTEM_PROMPT, EMAIL_USER_PROMPT, PROMPT_VERSION, TONE_DESCRIPTIONS

logger = logging.getLogger(__name__)


def draft_email(
    analysis: NeedAnalysis,
    api_key: str,
    sender_name: str | None = None,
    tone: str = "professional",
    model: str = DEFAULT_MODEL,
) -> EmailDraft:
    """Write one draft. An unknown tone falls back to professional rather than failing closed."""
    api_key = require_anthropic_api_key(api_key)
    sender_name = resolve_sender_name(sender_name)
    client = anthropic.Anthropic(api_key=api_key)
    tone_desc = TONE_DESCRIPTIONS.get(tone, TONE_DESCRIPTIONS["professional"])

    user_prompt = EMAIL_USER_PROMPT.format(
        analysis_json=analysis.model_dump_json(indent=2),
        tone=tone,
        tone_description=tone_desc,
        sender_name=sender_name,
    )

    logger.info("Generating email draft (tone: %s, prompt %s)...", tone, PROMPT_VERSION)
    message = create_message(client, model, EMAIL_SYSTEM_PROMPT, user_prompt, max_tokens=1000)
    data = parse_llm_json(message_text(message))

    draft = EmailDraft(
        subject=data["subject"],
        body=data["body"],
        tone=tone,
        prompt_version=PROMPT_VERSION,
        model=model,
    )
    logger.info('Email draft generated: "%s"', draft.subject)
    return draft
