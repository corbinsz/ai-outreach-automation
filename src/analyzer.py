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

logger = logging.getLogger(__name__)

# The prompt refuses a made-up sender company. It still allows industry
# inferences when the page is thin, which is a known quality limit.
ANALYSIS_SYSTEM_PROMPT = """You are a senior business development analyst preparing notes for a personalized outreach email.

Read the prospect's website and identify how the business actually works: what they sell, who they serve, and where the work looks manual, slow, or hard to measure. Look for concrete openings where data, automation, or operations support could help. Do not assume a product catalog, and do not invent a company or product name for the sender.

Be specific. Reference actual details from the website and avoid generic observations. Think like a consultant identifying real opportunities, not a salesperson pushing features."""

ANALYSIS_USER_PROMPT = """Analyze the following website content for a prospective client. \
Produce a detailed JSON analysis.

**Website URL:** {url}
**Company Name (detected):** {company_name}

**Scraped Content:**
{content}

---

Return a JSON object with exactly these fields:

{{
  "company_name": "The company's actual name",
  "company_summary": "2-3 sentence summary of what the company does, their market, and their scale",
  "industry": "Their primary industry/vertical",
  "services_offered": ["List of their main products/services based on website content"],
  "pain_points": [
    "Specific pain point 1 - explain why this is likely a challenge for them based on what you see",
    "Specific pain point 2 - be concrete, reference what you observed on their site",
    "Specific pain point 3 - connect to their industry context"
  ],
  "ai_opportunities": [
    "Specific opportunity 1 - how data, automation, or operations work could help, tied to their actual business",
    "Specific opportunity 2 - a practical use case with a plausible impact",
    "Specific opportunity 3 - a concrete advantage they could gain"
  ],
  "value_proposition": "A tailored 2-3 sentence note on why a conversation could be useful for this specific company. Reference their actual situation. Do not invent a company or product name for the sender.",
  "recommended_angle": "The single best angle of approach for the outreach email. What topic will resonate most? What pain point is most urgent? What's the hook?"
}}

Important guidelines:
- Every pain point and opportunity must be grounded in evidence from the scraped content.
- If the website content is limited, acknowledge that and make reasonable inferences based on the industry.
- Be specific about HOW AI/automation would help—don't just say "AI could improve efficiency."
- The recommended_angle should be the most compelling single hook for the outreach email.
- Return ONLY the JSON object, no markdown formatting or code blocks."""

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

    logger.info("Sending analysis request to Claude (%s)...", model)
    message = create_message(client, model, ANALYSIS_SYSTEM_PROMPT, user_prompt, max_tokens=2000)
    data = parse_llm_json(message_text(message))
    analysis = NeedAnalysis(**data)
    logger.info("Analysis complete for %s", analysis.company_name)
    return analysis
