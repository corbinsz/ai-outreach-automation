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

logger = logging.getLogger(__name__)

TONE_DESCRIPTIONS = {
    "professional": "Professional and polished. Business-appropriate language, clear and direct.",
    "conversational": "Friendly and conversational. Warm but still professional. Like talking to a smart colleague.",
    "bold": "Confident and bold. Direct, slightly provocative, pattern-interrupting. Stands out in an inbox.",
    "consultative": "Thoughtful and consultative. Lead with insights and questions. Position as a strategic advisor.",
}

EMAIL_SYSTEM_PROMPT = """You are an expert cold email copywriter. You write one outreach email for the sender named in the request.

You write outreach emails that:
- Feel personally written, not templated or mass-produced
- Reference specific details from the prospect's website to show the research
- Lead with an observation or insight, not a sales pitch
- Stay concise (under 200 words for the body)
- Have a single, clear call to action
- Use a subject line that is specific but not clickbait (under 60 characters)

Sign off with the sender name you are given. Do not invent a company, product, or team name."""

EMAIL_USER_PROMPT = """Write a personalized cold outreach email based on this prospect analysis.

**Prospect Analysis:**
{analysis_json}

**Tone/Style:** {tone}
{tone_description}

**Sender Name:** {sender_name}

---

Return a JSON object with exactly these fields:

{{
  "subject": "Email subject line (under 60 chars, no quotes)",
  "body": "The full email body. Use \\n for line breaks. Start with a personalized opener that references something specific from their website. Include the value proposition. End with a clear CTA (suggest a brief call/meeting). Sign off with the sender name."
}}

Guidelines:
- NEVER start with "I hope this email finds you well" or similar cliches.
- NEVER start with "I noticed your company..." — be more creative.
- DO reference a specific detail from their website (a service, a recent post, their mission, etc.).
- DO tie the note to a specific detail on their site so the offer feels like a natural next step.
- Keep paragraphs short (2-3 sentences max).
- The CTA should be low-friction (e.g., "Worth a 15-minute chat?" not "Schedule a demo").
- Return ONLY the JSON object, no markdown formatting or code blocks."""


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

    logger.info("Generating email draft (tone: %s)...", tone)
    message = create_message(client, model, EMAIL_SYSTEM_PROMPT, user_prompt, max_tokens=1000)
    data = parse_llm_json(message_text(message))

    draft = EmailDraft(
        subject=data["subject"],
        body=data["body"],
        tone=tone,
    )
    logger.info('Email draft generated: "%s"', draft.subject)
    return draft
