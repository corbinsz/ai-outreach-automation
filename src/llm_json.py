"""Turn a model reply into a dict.

The prompts ask for raw JSON. Models still wrap the object in a markdown
fence or a sentence. Failing the whole run on that formatting is worse than
extracting the object, so analysis and drafting share this parser.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_llm_json(response_text: str) -> dict[str, Any]:
    """Return the JSON object inside a model response.

    Raises ValueError when no object can be recovered. The message is stable
    so tests can match it.
    """
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop the opening fence and the closing fence when both are present.
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text.strip("`").strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            logger.warning(
                "Model response was not raw JSON; recovered the object from surrounding text."
            )
            data = json.loads(text[start:end])
        else:
            raise ValueError(f"LLM did not return valid JSON: {response_text[:200]}") from None

    if not isinstance(data, dict):
        raise ValueError(f"LLM did not return valid JSON: {response_text[:200]}")
    return data
