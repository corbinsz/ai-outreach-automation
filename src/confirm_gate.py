"""Count how often the pipeline stops before send.

The confirm gate is the default stop in ``run_pipeline``: a draft is returned
with stage ``reviewing``, and ``send`` is not called. ``auto_send`` is a
scripted bypass. The Streamlit screen does not set it.

The scenarios below are the situations the test suite already covers. A run
counts only when it produced a draft. A failed scrape, a missing key, or an
unknown demo URL never reaches the gate, so those runs are listed and left
out of the fraction.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from src.agent import AgentConfig, OutreachAgent, PipelineResult
from src.models import EmailDraft, NeedAnalysis, OutreachRecord, ScrapedPage, ScrapedWebsite

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"

_SCRAPED = ScrapedWebsite(
    base_url="https://acme.example",
    company_name="Acme",
    pages=[
        ScrapedPage(
            url="https://acme.example",
            content="Acme builds widgets.",
            page_type="homepage",
        )
    ],
    raw_text_summary="Acme builds widgets.",
)
_EMPTY = ScrapedWebsite(base_url="https://down.example", pages=[])
_ANALYSIS = NeedAnalysis(
    company_name="Acme Corp",
    company_summary="Widgets for plants.",
    industry="Manufacturing",
    pain_points=["Manual QA"],
    ai_opportunities=["A shared checklist"],
    value_proposition="One list instead of three notebooks.",
    recommended_angle="The notebook step.",
)
_DRAFT = EmailDraft(subject="The notebook step", body="Hi there.")


def review_screen_sets_auto_send(app_source: str) -> bool:
    """True when the review screen source mentions the auto-send bypass."""
    return "auto_send" in app_source


@dataclass(frozen=True)
class GateRow:
    """One scripted run and whether the gate stopped it."""

    name: str
    outcome: str


@dataclass(frozen=True)
class GateReport:
    """The confirm-gate fraction for the scripted scenarios."""

    rows: tuple[GateRow, ...]
    screen_sets_auto_send: bool

    @property
    def blocked(self) -> int:
        return sum(1 for row in self.rows if row.outcome == "blocked")

    @property
    def not_blocked(self) -> int:
        return sum(1 for row in self.rows if row.outcome == "not_blocked")

    @property
    def reached_draft(self) -> int:
        return self.blocked + self.not_blocked

    @property
    def no_draft(self) -> int:
        return sum(1 for row in self.rows if row.outcome == "no_draft")

    def markdown(self) -> str:
        """A table a product note can paste without retyping the counts."""
        lines = [
            "| Scenario | Stopped before send |",
            "| --- | --- |",
        ]
        for row in self.rows:
            if row.outcome == "no_draft":
                stopped = "no draft, not counted"
            elif row.outcome == "blocked":
                stopped = "yes"
            else:
                stopped = "no"
            lines.append(f"| {row.name} | {stopped} |")
        return "\n".join(lines)


def _classify(result: PipelineResult) -> str:
    if result.draft is None:
        return "no_draft"
    if result.stage == "reviewing" and result.send_result is None:
        return "blocked"
    return "not_blocked"


def _sent_record() -> OutreachRecord:
    return OutreachRecord(
        prospect_url="https://acme.example",
        prospect_name="Acme Corp",
        recipient_email="ada@acme.example",
        email_subject=_DRAFT.subject,
        email_body=_DRAFT.body,
        status="sent",
    )


def _live_config(*, api_key: str = "test-key") -> AgentConfig:
    return AgentConfig(
        anthropic_api_key=api_key,
        gmail_address="sender@gmail.com",
        gmail_app_password="abcdefghijklmnop",
        use_playwright=False,
    )


def _run_live(
    name: str,
    *,
    url: str = "https://acme.example",
    scraped: ScrapedWebsite = _SCRAPED,
    api_key: str = "test-key",
    analyze_error: Exception | None = None,
    auto_send: bool = False,
    to_address: str = "",
    mock_pipeline: bool = True,
) -> GateRow:
    """Run one live pipeline.

    ``mock_pipeline`` is false for the missing-key case so the real analyzer
    rejects the key before a draft exists. Mocking that path would invent a
    draft and count a stop that never happened.
    """
    with ExitStack() as stack:
        stack.enter_context(patch("src.agent.scrape_website", return_value=scraped))
        client = stack.enter_context(patch("anthropic.Anthropic"))
        if mock_pipeline:
            analyze = stack.enter_context(
                patch("src.agent.analyze_prospect", return_value=_ANALYSIS)
            )
            if analyze_error is not None:
                analyze.side_effect = analyze_error
            stack.enter_context(patch("src.agent.draft_email", return_value=_DRAFT))
            stack.enter_context(patch("src.agent.send_email", return_value=_sent_record()))
        result = OutreachAgent(_live_config(api_key=api_key)).run_pipeline(
            url=url,
            to_address=to_address,
            auto_send=auto_send,
        )
        if api_key == "":
            client.assert_not_called()
    return GateRow(name, _classify(result))


def _run_live_batch(names: tuple[str, str], scrapes: list[ScrapedWebsite]) -> list[GateRow]:
    with (
        patch("src.agent.scrape_website", side_effect=scrapes),
        patch("src.agent.analyze_prospect", return_value=_ANALYSIS),
        patch("src.agent.draft_email", return_value=_DRAFT),
        patch("src.agent.send_email", return_value=_sent_record()),
    ):
        results = OutreachAgent(_live_config()).run_batch(
            ["https://a.example", "https://b.example"]
        )
    return [GateRow(name, _classify(result)) for name, result in zip(names, results, strict=True)]


def _run_demo(name: str, url: str) -> GateRow:
    def _forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("confirm-gate demo scenario tried to use the network")

    agent = OutreachAgent(AgentConfig(anthropic_api_key="", demo_mode=True, use_playwright=False))
    with (
        patch("smtplib.SMTP", _forbid),
        patch("requests.sessions.Session.request", _forbid),
        patch("anthropic.Anthropic", _forbid),
    ):
        result = agent.run_pipeline(url)
    return GateRow(name, _classify(result))


def _run_demo_batch() -> list[GateRow]:
    def _forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("confirm-gate demo scenario tried to use the network")

    agent = OutreachAgent(AgentConfig(anthropic_api_key="", demo_mode=True, use_playwright=False))
    with (
        patch("smtplib.SMTP", _forbid),
        patch("requests.sessions.Session.request", _forbid),
        patch("anthropic.Anthropic", _forbid),
    ):
        results = agent.run_batch(["https://example.com", "harborpine.example"])
    names = ("Demo batch, unknown URL", "Demo batch, Harbor & Pine")
    return [GateRow(name, _classify(result)) for name, result in zip(names, results, strict=True)]


def measure_confirm_gate(app_source: str | None = None) -> GateReport:
    """Replay the test-suite situations and classify each one.

    ``app_source`` defaults to ``app.py``. Tests pass a string so the screen
    check does not depend on a temporary edit of the UI.
    """
    source = APP_PATH.read_text(encoding="utf-8") if app_source is None else app_source
    # These scenarios include failures on purpose. Hide the pipeline's error
    # traceback so `make eval` prints the table and not a stack trace.
    # Set the loggers that emit, not only their parent. A child with its own
    # level ignores the parent's level, and these scenarios fail on purpose.
    quiet = tuple(
        logging.getLogger(name) for name in ("src.agent", "src.demo", "src.config", "src.analyzer")
    )
    previous = [logger.level for logger in quiet]
    for logger in quiet:
        logger.setLevel(logging.CRITICAL)
    try:
        rows = _scenario_rows()
    finally:
        for logger, level in zip(quiet, previous, strict=True):
            logger.setLevel(level)
    return GateReport(tuple(rows), review_screen_sets_auto_send(source))


def _scenario_rows() -> list[GateRow]:
    rows: list[GateRow] = [
        _run_live("Single URL, no auto-send"),
        _run_live("Recipient filled in, no auto-send", to_address="ada@acme.example"),
        _run_live("Auto-send on, no recipient", auto_send=True),
        _run_live(
            "Auto-send on, with a recipient",
            auto_send=True,
            to_address="ada@acme.example",
        ),
        *_run_live_batch(
            ("Batch, first URL", "Batch, second URL"),
            [_SCRAPED, _SCRAPED],
        ),
        *_run_live_batch(
            ("Batch, failed scrape", "Batch URL after a failed scrape"),
            [_EMPTY, _SCRAPED],
        ),
        _run_live("Empty scrape", scraped=_EMPTY),
        _run_live("Analysis raises", analyze_error=ValueError("Bad LLM response")),
        _run_live("Missing API key", api_key="", mock_pipeline=False),
        _run_demo("Demo mode, Northwind", "https://northwind.example"),
        *_run_demo_batch(),
    ]
    return rows
