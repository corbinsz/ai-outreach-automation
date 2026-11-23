"""Demo mode must finish with no network, no model call, and no SMTP."""

from pathlib import Path
from unittest.mock import patch

import pytest
from src.agent import AgentConfig, OutreachAgent
from src.demo import (
    DEMO_COMPANIES,
    DemoSampleNotFound,
    demo_analysis,
    demo_draft,
    demo_scrape,
    match_demo_company,
)
from src.email_drafter import TONE_DESCRIPTIONS

ROOT = Path(__file__).resolve().parents[1]

_GROUNDED = {
    "northwind": "assembled in spreadsheets",
    "harbor": "shops still reorder by email",
}


def _forbid_network(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("demo mode tried to use the network")


def test_sample_urls_resolve_with_or_without_a_scheme():
    assert match_demo_company("northwind.example") is not None
    assert match_demo_company("https://www.northwind.example/about") is not None
    assert match_demo_company("https://harborpine.example/") is not None
    assert match_demo_company("https://example.com") is None
    assert match_demo_company("") is None


def test_saved_pages_include_the_phrase_the_draft_uses():
    for company in DEMO_COMPANIES:
        phrase = _GROUNDED[company.slug]
        html = "\n".join(
            (company.directory / name).read_text(encoding="utf-8").lower()
            for name in ("home.html", "about.html", "services.html", "contact.html")
        )
        assert phrase in html
        scraped = demo_scrape(company.url)
        assert phrase in scraped.raw_text_summary.lower()
        assert scraped.contact_emails
        assert all(address.endswith(".example") for address in scraped.contact_emails)
        assert "noreply@" not in " ".join(scraped.contact_emails)


def test_every_saved_draft_stays_specific_and_short():
    seen: dict[str, set[str]] = {}
    for company in DEMO_COMPANIES:
        phrase = _GROUNDED[company.slug]
        bodies: set[str] = set()
        scraped = demo_scrape(company.url)
        analysis = demo_analysis(scraped)
        assert analysis.company_name == company.name
        assert analysis.prompt_version == "saved-demo"
        assert analysis.evidence
        assert analysis.inferences
        for tone in TONE_DESCRIPTIONS:
            draft = demo_draft(analysis, sender_name="Corbin Szenegeto", tone=tone)
            assert len(draft.subject) <= 60
            assert len(draft.body.split()) <= 200
            assert phrase in draft.body.lower()
            assert "Corbin Szenegeto" in draft.body
            assert draft.prompt_version == "saved-demo"
            lowered = draft.body.lower()
            assert "i hope this email finds you well" not in lowered
            assert not lowered.lstrip().startswith("i noticed your company")
            bodies.add(draft.body)
        assert len(bodies) == len(TONE_DESCRIPTIONS)
        seen[company.slug] = bodies
    assert seen["northwind"].isdisjoint(seen["harbor"])


def test_unknown_tone_uses_the_professional_draft():
    scraped = demo_scrape("https://northwind.example")
    analysis = demo_analysis(scraped)
    fallback = demo_draft(analysis, sender_name="Ada", tone="not-a-tone")
    professional = demo_draft(analysis, sender_name="Ada", tone="professional")
    assert fallback.tone == "professional"
    assert fallback.body == professional.body
    assert fallback.body.endswith("Ada")


@patch("smtplib.SMTP", _forbid_network)
@patch("requests.sessions.Session.request", _forbid_network)
@patch("anthropic.Anthropic", _forbid_network)
def test_pipeline_and_send_stay_offline(tmp_path: Path):
    agent = OutreachAgent(
        AgentConfig(anthropic_api_key="", demo_mode=True, sender_name="Corbin Szenegeto")
    )
    result = agent.run_pipeline("https://www.northwind.example/services")

    assert result.stage == "reviewing"
    assert result.error is None
    assert result.analysis is not None
    assert result.draft is not None
    assert "assembled in spreadsheets" in result.draft.body.lower()
    assert "Corbin Szenegeto" in result.draft.body

    with patch("src.gmail_sender.LOG_DIR", tmp_path):
        sent = agent.send(
            result.draft,
            "hello@northwind.example",
            prospect_url=result.url,
            prospect_name=result.analysis.company_name,
        )
        rows = list(tmp_path.glob("*.json"))

    assert sent.status == "demo_sent"
    assert "No email was sent" in (sent.notes or "")
    assert rows
    assert "hello@northwind.example" in rows[0].read_text(encoding="utf-8")


@patch("requests.sessions.Session.request", _forbid_network)
def test_live_url_in_demo_mode_is_refused_without_a_fetch():
    agent = OutreachAgent(AgentConfig(anthropic_api_key="", demo_mode=True))
    result = agent.run_pipeline("https://example.com")

    assert result.stage == "failed"
    assert result.error is not None
    assert "northwind.example" in result.error
    assert "harborpine.example" in result.error


def test_direct_lookup_of_an_unknown_sample_raises():
    with pytest.raises(DemoSampleNotFound):
        demo_scrape("https://example.com")


def test_batch_keeps_going_when_one_sample_is_not_in_the_set():
    agent = OutreachAgent(AgentConfig(anthropic_api_key="", demo_mode=True))
    with patch("requests.sessions.Session.request", _forbid_network):
        results = agent.run_batch(["https://example.com", "harborpine.example"])

    assert results[0].stage == "failed"
    assert results[1].stage == "reviewing"
    assert results[1].analysis is not None
    assert results[1].analysis.company_name == "Harbor & Pine Goods"


def test_fixture_directory_is_inside_the_repo():
    for company in DEMO_COMPANIES:
        assert company.directory.is_relative_to(ROOT / "fixtures" / "demo")
        assert (company.directory / "analysis.json").is_file()
        assert (company.directory / "drafts.json").is_file()
