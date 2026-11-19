"""The offline draft rubric and the confirm-gate count."""

import json
from pathlib import Path

import pytest
from src.agent import PipelineResult
from src.confirm_gate import GateReport, GateRow, _classify, measure_confirm_gate
from src.draft_eval import (
    CHECK_ORDER,
    DraftEvalError,
    EvalCase,
    build_case,
    invented_numbers,
    load_demo_cases,
    load_eval_cases,
    main,
    miss_line,
    name_token,
    score_case,
    score_cases,
    success_metrics_markdown,
)
from src.models import EmailDraft, OutreachRecord

ROOT = Path(__file__).resolve().parents[1]


def _case(
    *,
    company: str = "Lumen Freight",
    tone: str = "saved",
    page: str = "Night dispatch still lives in a shared inbox.",
    subject: str = "Night dispatch",
    body: str = (
        "Hi,\n\nLumen Freight's site says night dispatch still lives in a shared inbox. "
        "The morning handoff is a forwarded thread, which is a fragile way to start a route. "
        "A short conversation could decide what to change.\n\nWorth a 15-minute chat?\n\nAlex Example"
    ),
    facts: tuple[str, ...] = ("night dispatch still lives in a shared inbox",),
) -> EvalCase:
    return build_case(
        source="fixture",
        company=company,
        tone=tone,
        page_text=page,
        subject=subject,
        body=body,
        facts=facts,
    )


def test_saved_demo_drafts_cite_the_page_and_two_do_not_name_the_company():
    scores = {(item.company, item.tone): item for item in score_cases(load_demo_cases())}
    assert len(scores) == 8
    for company in ("Northwind Analytics", "Harbor & Pine Goods"):
        professional = scores[(company, "professional")]
        assert professional.failed_labels == ("Names the company",)
        assert professional.passed("fact_citation")
        assert professional.passed("clear_ask")
    named = [
        scores[("Northwind Analytics", "bold")],
        scores[("Harbor & Pine Goods", "consultative")],
    ]
    assert all(item.passed_all for item in named)


def test_fixture_set_has_twelve_pages_and_every_check_can_fail():
    cases = load_eval_cases()
    assert len(cases) == 12
    pages = list((ROOT / "fixtures" / "eval").glob("*/page.html"))
    assert len(pages) == 12
    scores = score_cases(cases)
    for key in CHECK_ORDER:
        assert any(not item.passed(key) for item in scores), key
    assert sum(1 for item in scores if item.passed_all) == 5
    assert miss_line([item for item in scores if item.passed_all]).startswith("Every draft")


def test_product_note_matches_the_eval_output():
    block = success_metrics_markdown()
    text = (ROOT / "docs" / "PRODUCT.md").read_text(encoding="utf-8")
    assert block in text
    assert "8 of 9" in block
    assert "6/8" in block
    assert "5/12" in block


def test_confirm_gate_stops_eight_of_nine_drafts_and_the_screen_cannot_bypass():
    gate = measure_confirm_gate()
    outcomes = {row.name: row.outcome for row in gate.rows}
    assert outcomes == {
        "Single URL, no auto-send": "blocked",
        "Recipient filled in, no auto-send": "blocked",
        "Auto-send on, no recipient": "blocked",
        "Auto-send on, with a recipient": "not_blocked",
        "Batch, first URL": "blocked",
        "Batch, second URL": "blocked",
        "Batch, failed scrape": "no_draft",
        "Batch URL after a failed scrape": "blocked",
        "Empty scrape": "no_draft",
        "Analysis raises": "no_draft",
        "Missing API key": "no_draft",
        "Demo mode, Northwind": "blocked",
        "Demo batch, unknown URL": "no_draft",
        "Demo batch, Harbor & Pine": "blocked",
    }
    assert gate.blocked == 8
    assert gate.reached_draft == 9
    assert gate.no_draft == 5
    assert gate.screen_sets_auto_send is False
    assert "auto_send" not in (ROOT / "app.py").read_text(encoding="utf-8")


def test_gate_prose_for_zero_and_several_bypasses():
    demo = score_cases(load_demo_cases())
    fixtures = score_cases(load_eval_cases())
    none = success_metrics_markdown(demo, fixtures, GateReport((), True))
    assert "Every counted run stopped before send." in none
    assert "The review screen source mentions auto-send." in none
    several = GateReport(
        (GateRow("one", "not_blocked"), GateRow("two", "not_blocked")),
        False,
    )
    text = success_metrics_markdown(demo, fixtures, several)
    assert "2 counted runs did not stop." in text
    assert "| one | no |" in several.markdown()


def test_classify_counts_a_send_even_when_the_stage_says_reviewing():
    draft = EmailDraft(subject="Hi", body="Hello there, worth a chat?")
    record = OutreachRecord(
        prospect_url="https://acme.example",
        prospect_name="Acme",
        recipient_email="a@acme.example",
        email_subject="Hi",
        email_body="Hello",
        status="sent",
    )
    sent_anyway = PipelineResult(
        url="https://acme.example",
        draft=draft,
        stage="reviewing",
        send_result=record,
    )
    assert _classify(sent_anyway) == "not_blocked"
    failed_send = PipelineResult(
        url="https://acme.example",
        draft=draft,
        stage="failed",
        send_result=record,
    )
    assert _classify(failed_send) == "not_blocked"


def test_number_allowance_is_only_the_fifteen_minute_ask():
    page = "The tasting room seats 18."
    assert invented_numbers("Worth a 15-minute chat about those 18 seats?", page) == ()
    assert invented_numbers("Open to 15 minutes?", page) == ()
    assert invented_numbers("Sales are up 40% and 40% again.", page) == ("40",)


def test_citation_can_come_from_the_subject_and_a_missing_fact_is_a_fixture_error():
    cited = _case(
        subject="Night dispatch still lives in a shared inbox",
        body="Hi.\n\n" + ("word " * 45),
    )
    score = score_case(cited)
    assert score.passed("fact_citation")
    with pytest.raises(DraftEvalError, match="not on the page"):
        _case(facts=("this phrase is not on the page",))
    with pytest.raises(DraftEvalError, match="no facts"):
        _case(facts=())


def test_length_banned_phrase_name_and_ask_failures():
    short = _case(
        subject="x" * 61,
        body="Too short to be a real note.",
        page="Too short to be a real note. night dispatch still lives in a shared inbox.",
    )
    score = score_case(short)
    assert not score.passed("length")
    assert "61 characters" in score.checks[1].detail

    sample = _case()
    banned = _case(body=sample.body.replace("Hi,", "I hope this email finds you well."))
    assert not score_case(banned).passed("banned_phrase")

    unnamed = _case(
        company="Fieldnote Survey", body=sample.body.replace("Lumen Freight", "the crew")
    )
    assert name_token("Fieldnote Survey") == "Fieldnote"
    assert name_token("A B") == ""
    assert name_token("Co") == ""
    assert not score_case(unnamed).passed("personalization")

    no_token = _case(company="A B", body=sample.body)
    assert not score_case(no_token).passed("personalization")

    split_ask = _case(
        body=(
            "Lumen Freight's site says night dispatch still lives in a shared inbox. "
            + ("The handoff is fragile. " * 8)
            + "\ncalls roll to the owner\n\nIs Tuesday open?\n\nAlex Example"
        )
    )
    assert not score_case(split_ask).passed("clear_ask")
    with pytest.raises(KeyError):
        score.passed("not-a-check")


def test_bad_fixture_files_are_refused(tmp_path: Path):
    with pytest.raises(DraftEvalError, match="Missing eval fixtures"):
        load_eval_cases(tmp_path / "missing")

    empty = tmp_path / "empty"
    empty.mkdir()
    assert load_eval_cases(empty) == []

    broken = tmp_path / "broken"
    company = broken / "acme"
    company.mkdir(parents=True)
    (company / "page.html").write_text("<p>Hi</p>", encoding="utf-8")
    with pytest.raises(DraftEvalError, match="page.html and draft.json"):
        load_eval_cases(broken)

    (company / "draft.json").write_text("[]", encoding="utf-8")
    with pytest.raises(DraftEvalError, match="must be an object"):
        load_eval_cases(broken)

    (company / "draft.json").write_text(
        json.dumps({"company_name": " ", "subject": "Hi", "body": "Hi", "facts": ["Hi"]}),
        encoding="utf-8",
    )
    with pytest.raises(DraftEvalError, match="company_name"):
        load_eval_cases(broken)

    (company / "draft.json").write_text(
        json.dumps(
            {
                "company_name": "Acme",
                "subject": "Hi",
                "body": "Hi",
                "facts": ["not on the page"],
            }
        ),
        encoding="utf-8",
    )
    (company / "page.html").write_text("<p>Acme builds widgets.</p>", encoding="utf-8")
    with pytest.raises(DraftEvalError, match="not on the page"):
        load_eval_cases(broken)

    (company / "draft.json").write_text(
        json.dumps({"company_name": "Acme", "subject": "Hi", "body": "Hi", "facts": []}),
        encoding="utf-8",
    )
    with pytest.raises(DraftEvalError, match="facts"):
        load_eval_cases(broken)

    (company / "draft.json").write_text(
        json.dumps({"company_name": "Acme", "subject": "Hi", "body": "Hi", "facts": ["", "Hi"]}),
        encoding="utf-8",
    )
    with pytest.raises(DraftEvalError, match="facts"):
        load_eval_cases(broken)


def test_demo_facts_must_be_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.draft_eval.DEMO_FACTS", {})
    with pytest.raises(DraftEvalError, match="No demo facts"):
        load_demo_cases()


def test_main_prints_the_report_and_returns_nonzero_on_a_bad_fixture(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert main() == 0
    printed = capsys.readouterr().out
    assert "## Success metrics" in printed
    assert "8 of 9" in printed

    def _boom() -> str:
        raise DraftEvalError("facts must be a non-empty list of strings.")

    monkeypatch.setattr("src.draft_eval.render_report", _boom)
    assert main() == 1
    assert "inconsistent" in capsys.readouterr().out
