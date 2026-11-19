"""Direct checks for model-response parsing."""

import pytest
from src.llm_client import message_text
from src.llm_json import parse_llm_json


def test_array_is_not_an_analysis_object():
    with pytest.raises(ValueError, match="valid JSON"):
        parse_llm_json("[1, 2, 3]")


def test_empty_model_message_is_rejected():
    class Empty:
        content: list[object] = []

    with pytest.raises(ValueError, match="empty response"):
        message_text(Empty())  # type: ignore[arg-type]
