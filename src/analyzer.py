"""Ask Claude for structured notes on a scraped site.

The call is one shot. Temporary API errors are retried in llm_client. A bad
JSON reply is not retried: the parser either recovers the object or the run
stops before a draft is written from garbage.
"""

import logging

import anthropic

from src.config import require_anthropic_api_key
from src.llm_client import create_message, message_text
from src.llm_json import parse_llm_json
from src.models import DEFAULT_MODEL, NeedAnalysis, ScrapedWebsite
from src.prompts import ANALYSIS_SYSTEM_PROMPT, ANALYSIS_USER_PROMPT, PROMPT_VERSION

logger = logging.getLogger(__name__)

# Character cap, not a token cap. It keeps one prospect from dominating the
# prompt and the bill. The cut can land mid-sentence.
_MAX_CONTENT_CHARS = 15000


def analyze_prospect(
    scraped: ScrapedWebsite,
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> NeedAnalysis:
    """Return structured notes for one scraped site."""
    api_key = require_anthropic_api_key(api_key)
    client = anthropic.Anthropic(api_key=api_key)

    content = scraped.raw_text_summary
    if len(content) > _MAX_CONTENT_CHARS:
        content = content[:_MAX_CONTENT_CHARS] + "\n\n... [content truncated for analysis]"

    user_prompt = ANALYSIS_USER_PROMPT.format(
        url=scraped.base_url,
        company_name=scraped.company_name,
        content=content,
    )

    logger.info("Sending analysis request to Claude (%s, prompt %s)...", model, PROMPT_VERSION)
    message = create_message(client, model, ANALYSIS_SYSTEM_PROMPT, user_prompt, max_tokens=2000)
    data = parse_llm_json(message_text(message))
    # The version and model are facts about this call, not fields the model fills in.
    data.pop("prompt_version", None)
    data.pop("model", None)
    analysis = NeedAnalysis(**data)
    analysis = analysis.model_copy(update={"prompt_version": PROMPT_VERSION, "model": model})
    logger.info("Analysis complete for %s", analysis.company_name)
    return analysis
