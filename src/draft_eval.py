"""Score saved outreach drafts with deterministic checks.

``make eval`` runs this module. It reads HTML and JSON from the repo, then
applies the rubric in ``docs/DRAFT_RUBRIC.md``. It does not call a model, open
a socket, or send mail. A passing score is not a judgment that the email is
fair or that a person should send it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from src.confirm_gate import GateReport, measure_confirm_gate
from src.demo import DEMO_COMPANIES, demo_analysis, demo_draft, demo_scrape
from src.email_drafter import TONE_DESCRIPTIONS
from src.prompts import PROMPT_VERSION
from src.scraper import _extract_text

logger = logging.getLogger(__name__)

EVAL_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "eval"
MIN_BODY_WORDS = 40
MAX_BODY_WORDS = 200
MAX_SUBJECT_CHARS = 60

# Phrases that already appear on the saved demo pages. A demo draft passes
# the fact check when its subject or body contains at least one of these.
DEMO_FACTS: dict[str, tuple[str, ...]] = {
    "northwind": ("assembled in spreadsheets",),
    "harbor": ("shops still reorder by email",),
}

# Cold-email clichés and hype. Matched as case-insensitive substrings.
BANNED_PHRASES: tuple[str, ...] = (
    "i hope this email finds you well",
    "i hope this finds you well",
    "i noticed your company",
    "just circling back",
    "circle back",
    "touch base",
    "synergy",
    "industry-leading",
    "guaranteed results",
    "act now",
    "limited time",
    "dear sir or madam",
    "to whom it may concern",
    "as per my last email",
)

# The drafter prompt asks for a low-friction 15-minute chat. That duration is
# the ask, not a claim about the company, so those digits are not "invented".
_ASK_DURATION = re.compile(r"\b15(?:-|\s)?minutes?\b", re.IGNORECASE)
# Singular and plural. "15 minutes" is an ask. "calls" in "after-hours calls"
# is not, unless that same line also asks a question.
_ASK_PATTERNS: tuple[str, ...] = (
    r"\bchats?\b",
    r"\bcalls?\b",
    r"\bconversations?\b",
    r"\bminutes?\b",
    r"\bmeetings?\b",
    r"\bsessions?\b",
)
_NUMBER = re.compile(r"\d+")
_NAME_WORD = re.compile(r"[A-Za-z][A-Za-z']+")
_WORD = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "for",
        "in",
        "on",
        "with",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "their",
        "they",
        "them",
        "we",
        "our",
        "you",
        "your",
        "it",
        "its",
        "as",
        "at",
        "by",
        "from",
        "into",
        "over",
        "still",
        "than",
        "then",
        "not",
        "but",
        "if",
        "so",
    }
)

CHECK_ORDER: tuple[str, ...] = (
    "fact_citation",
    "length",
    "banned_phrase",
    "invented_number",
    "personalization",
    "clear_ask",
)
CHECK_LABELS: dict[str, str] = {
    "fact_citation": "Cites a fact from the page",
    "length": "Length within target",
    "banned_phrase": "No banned phrase",
    "invented_number": "No invented number",
    "personalization": "Names the company",
    "clear_ask": "Clear ask",
}


class DraftEvalError(Exception):
    """A fixture is inconsistent, so the score would not mean anything."""


@dataclass(frozen=True)
class EvalCase:
    """One draft plus the page text it is allowed to use."""

    source: str
    company: str
    tone: str
    page_text: str
    subject: str
    body: str
    facts: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    """One rubric row for one draft."""

    key: str
    passed: bool
    detail: str

    @property
    def label(self) -> str:
        return CHECK_LABELS[self.key]


@dataclass(frozen=True)
class DraftScore:
    """The six checks for one draft."""

    source: str
    company: str
    tone: str
    checks: tuple[CheckResult, ...]

    def passed(self, key: str) -> bool:
        for check in self.checks:
            if check.key == key:
                return check.passed
        raise KeyError(key)

    @property
    def passed_all(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_labels(self) -> tuple[str, ...]:
        return tuple(check.label for check in self.checks if not check.passed)


def name_token(company_name: str) -> str:
    """First word of four or more letters, used as the personalization token.

    "Northwind Analytics" counts when the draft says "Northwind". Requiring
    the full legal name would fail drafts that use the short name a person
    would actually write.
    """
    for word in _NAME_WORD.findall(company_name):
        if len(word) >= 4:
            return word
    return ""


def _require_facts(company: str, page_text: str, facts: tuple[str, ...]) -> None:
    if not facts:
        raise DraftEvalError(f"{company} has no facts to check.")
    page = page_text.lower()
    for fact in facts:
        if fact.lower() not in page:
            raise DraftEvalError(
                f"Fact {fact!r} is not on the page for {company}. "
                "The citation check would be scoring a phrase the fixture invented."
            )


def build_case(
    *,
    source: str,
    company: str,
    tone: str,
    page_text: str,
    subject: str,
    body: str,
    facts: tuple[str, ...],
) -> EvalCase:
    """Validate that every listed fact is really on the page, then keep the case."""
    _require_facts(company, page_text, facts)
    return EvalCase(
        source=source,
        company=company,
        tone=tone,
        page_text=page_text,
        subject=subject,
        body=body,
        facts=facts,
    )


def _as_str(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DraftEvalError(f"{label} must be a non-empty string.")
    return value.strip()


def _as_facts(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise DraftEvalError("facts must be a non-empty list of strings.")
    facts: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise DraftEvalError("facts must be a non-empty list of strings.")
        facts.append(item.strip())
    return tuple(facts)


def load_eval_cases(root: Path | None = None) -> list[EvalCase]:
    """Load the fictional company pages and the one saved draft beside each."""
    folder = EVAL_ROOT if root is None else root
    if not folder.is_dir():
        raise DraftEvalError(f"Missing eval fixtures at {folder}.")
    cases: list[EvalCase] = []
    for directory in sorted(path for path in folder.iterdir() if path.is_dir()):
        page_path = directory / "page.html"
        draft_path = directory / "draft.json"
        if not page_path.is_file() or not draft_path.is_file():
            raise DraftEvalError(f"{directory.name} needs page.html and draft.json.")
        raw = json.loads(draft_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise DraftEvalError(f"{directory.name}/draft.json must be an object.")
        company = _as_str(raw.get("company_name"), f"{directory.name} company_name")
        cases.append(
            build_case(
                source="fixture",
                company=company,
                tone="saved",
                page_text=_extract_text(page_path.read_text(encoding="utf-8")),
                subject=_as_str(raw.get("subject"), f"{directory.name} subject"),
                body=_as_str(raw.get("body"), f"{directory.name} body"),
                facts=_as_facts(raw.get("facts")),
            )
        )
    return cases


def load_demo_cases() -> list[EvalCase]:
    """Score the drafts ``make demo`` shows. No model call and no network."""
    cases: list[EvalCase] = []
    for company in DEMO_COMPANIES:
        facts = DEMO_FACTS.get(company.slug)
        if facts is None:
            raise DraftEvalError(f"No demo facts recorded for {company.slug}.")
        scraped = demo_scrape(company.url)
        analysis = demo_analysis(scraped)
        for tone in TONE_DESCRIPTIONS:
            draft = demo_draft(analysis, sender_name="Your Name", tone=tone)
            cases.append(
                build_case(
                    source="demo",
                    company=company.name,
                    tone=tone,
                    page_text=scraped.raw_text_summary,
                    subject=draft.subject,
                    body=draft.body,
                    facts=facts,
                )
            )
    return cases


def _combined(case: EvalCase) -> str:
    return f"{case.subject}\n{case.body}"


def _check_fact(case: EvalCase) -> CheckResult:
    haystack = _combined(case).lower()
    found = [fact for fact in case.facts if fact.lower() in haystack]
    if found:
        return CheckResult("fact_citation", True, f"cited {found[0]!r}")
    return CheckResult(
        "fact_citation",
        False,
        "none of the fixture phrases appear in the subject or body",
    )


def _check_length(case: EvalCase) -> CheckResult:
    words = len(case.body.split())
    subject_chars = len(case.subject.strip())
    problems: list[str] = []
    if words < MIN_BODY_WORDS or words > MAX_BODY_WORDS:
        problems.append(f"body has {words} words (target {MIN_BODY_WORDS} to {MAX_BODY_WORDS})")
    if subject_chars < 1 or subject_chars > MAX_SUBJECT_CHARS:
        problems.append(f"subject has {subject_chars} characters (target 1 to {MAX_SUBJECT_CHARS})")
    if problems:
        return CheckResult("length", False, "; ".join(problems))
    return CheckResult(
        "length", True, f"body has {words} words; subject has {subject_chars} characters"
    )


def _check_banned(case: EvalCase) -> CheckResult:
    haystack = _combined(case).lower()
    found = [phrase for phrase in BANNED_PHRASES if phrase in haystack]
    if found:
        return CheckResult("banned_phrase", False, f"contains {found[0]!r}")
    return CheckResult("banned_phrase", True, "no banned phrase")


def invented_numbers(draft_text: str, page_text: str) -> tuple[str, ...]:
    """Digit strings in the draft that are neither on the page nor the 15-minute ask."""
    page_numbers = set(_NUMBER.findall(page_text))
    without_ask = _ASK_DURATION.sub(" ", draft_text)
    seen: list[str] = []
    for number in _NUMBER.findall(without_ask):
        if number not in page_numbers and number not in seen:
            seen.append(number)
    return tuple(seen)


def _check_numbers(case: EvalCase) -> CheckResult:
    invented = invented_numbers(_combined(case), case.page_text)
    if invented:
        listed = ", ".join(invented)
        return CheckResult("invented_number", False, f"digits not on the page: {listed}")
    return CheckResult(
        "invented_number", True, "every digit is on the page or is the 15-minute ask"
    )


def _check_personalization(case: EvalCase) -> CheckResult:
    token = name_token(case.company)
    if not token:
        return CheckResult(
            "personalization",
            False,
            "company name has no word of four or more letters",
        )
    if token.lower() in _combined(case).lower():
        return CheckResult("personalization", True, f"contains {token!r}")
    return CheckResult("personalization", False, f"does not contain {token!r}")


def _line_has_ask(line: str) -> bool:
    if "?" not in line:
        return False
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in _ASK_PATTERNS)


def _check_ask(case: EvalCase) -> CheckResult:
    # The question and the ask have to be on the same line. A phone "call"
    # earlier in the note is not a request for a meeting.
    if any(_line_has_ask(line) for line in case.body.splitlines()):
        return CheckResult("clear_ask", True, "a line asks for a chat, call, or meeting")
    return CheckResult(
        "clear_ask",
        False,
        "no line has both a question mark and an ask (chat, call, conversation, minute, meeting, or session)",
    )


def score_case(case: EvalCase) -> DraftScore:
    """Apply the six checks. Order matches ``CHECK_ORDER``."""
    checks = (
        _check_fact(case),
        _check_length(case),
        _check_banned(case),
        _check_numbers(case),
        _check_personalization(case),
        _check_ask(case),
    )
    return DraftScore(case.source, case.company, case.tone, checks)


def score_cases(cases: list[EvalCase]) -> list[DraftScore]:
    return [score_case(case) for case in cases]


def shared_detail(page_text: str, draft_text: str, width: int = 4) -> str:
    """Return one 4-word page phrase that also appears in the draft.

    At least two of the words have to be specific (five letters or more, and
    not a stopword). "the and of a" does not count. The match is exact words
    in order, so a paraphrase fails. That is the same limitation as the
    fixture citation check, applied when nobody listed the phrases ahead of time.
    """
    words = _WORD.findall(page_text.lower())
    draft = " ".join(_WORD.findall(draft_text.lower()))
    if width < 1 or len(words) < width or not draft:
        return ""
    seen: set[str] = set()
    for index in range(len(words) - width + 1):
        window = words[index : index + width]
        contentful = [word for word in window if word not in _STOPWORDS and len(word) >= 5]
        if len(contentful) < 2:
            continue
        phrase = " ".join(window)
        if phrase in seen:
            continue
        seen.add(phrase)
        if phrase in draft:
            return phrase
    return ""


def score_review(
    *,
    company: str,
    page_text: str,
    subject: str,
    body: str,
    tone: str = "review",
) -> DraftScore:
    """Score a draft the person is about to send, against the page just read.

    The fact check looks for a shared phrase. The other five checks are the
    fixture rubric. A failing row is a warning on the review screen. It does
    not block confirm.
    """
    case = EvalCase(
        source="review",
        company=company,
        tone=tone,
        page_text=page_text,
        subject=subject,
        body=body,
        facts=("review",),
    )
    scored = score_case(case)
    phrase = shared_detail(page_text, _combined(case))
    if phrase:
        fact = CheckResult("fact_citation", True, f"cited {phrase!r}")
    else:
        fact = CheckResult(
            "fact_citation",
            False,
            "none of the page's specific 4-word phrases appear in the subject or body",
        )
    checks = (fact, *(check for check in scored.checks if check.key != "fact_citation"))
    return DraftScore("review", company, tone, checks)


@dataclass(frozen=True)
class NoteScore:
    """How a saved research note separates quotes from guesses."""

    company: str
    evidence_count: int
    quotes_on_page: int
    inference_count: int

    @property
    def quotes_match(self) -> bool:
        return self.evidence_count > 0 and self.quotes_on_page == self.evidence_count

    @property
    def enough_quotes(self) -> bool:
        return self.evidence_count >= 2

    @property
    def has_inference(self) -> bool:
        return self.inference_count >= 1

    @property
    def passed_all(self) -> bool:
        return self.quotes_match and self.enough_quotes and self.has_inference


def load_demo_notes() -> list[NoteScore]:
    """Score the saved research notes. Quotes have to appear in the saved pages."""
    scores: list[NoteScore] = []
    for company in DEMO_COMPANIES:
        scraped = demo_scrape(company.url)
        analysis = demo_analysis(scraped)
        page = scraped.raw_text_summary.lower()
        quotes = [item.quote.strip() for item in analysis.evidence if item.quote.strip()]
        on_page = sum(1 for quote in quotes if quote.lower() in page)
        scores.append(
            NoteScore(
                company=company.name,
                evidence_count=len(quotes),
                quotes_on_page=on_page,
                inference_count=len(analysis.inferences),
            )
        )
    return scores


def note_summary_table(scores: list[NoteScore]) -> str:
    """Pass counts for saved research notes."""
    total = len(scores)
    quotes_match = sum(1 for score in scores if score.quotes_match)
    enough = sum(1 for score in scores if score.enough_quotes)
    inferred = sum(1 for score in scores if score.has_inference)
    passed = sum(1 for score in scores if score.passed_all)
    return "\n".join(
        [
            "| Check | Passed |",
            "| --- | --- |",
            f"| Every quote is on the page | {quotes_match}/{total} |",
            f"| At least two quotes | {enough}/{total} |",
            f"| At least one labeled inference | {inferred}/{total} |",
            f"| All three checks | {passed}/{total} |",
        ]
    )


def note_miss_line(scores: list[NoteScore]) -> str:
    """Name saved notes that fail a research-note check."""
    parts: list[str] = []
    for score in scores:
        misses: list[str] = []
        if not score.quotes_match:
            misses.append("Every quote is on the page")
        if not score.enough_quotes:
            misses.append("At least two quotes")
        if not score.has_inference:
            misses.append("At least one labeled inference")
        if misses:
            parts.append(f"{score.company} ({', '.join(misses)})")
    if not parts:
        return "Every saved note has quotes from its page and a labeled inference."
    return "Misses: " + "; ".join(parts) + "."


def _count(scores: list[DraftScore], key: str) -> int:
    return sum(1 for score in scores if score.passed(key))


def summary_table(scores: list[DraftScore]) -> str:
    """Pass counts for one set of drafts."""
    total = len(scores)
    lines = ["| Check | Passed |", "| --- | --- |"]
    for key in CHECK_ORDER:
        lines.append(f"| {CHECK_LABELS[key]} | {_count(scores, key)}/{total} |")
    all_passed = sum(1 for score in scores if score.passed_all)
    lines.append(f"| All six checks | {all_passed}/{total} |")
    return "\n".join(lines)


def miss_line(scores: list[DraftScore]) -> str:
    """Name the drafts that failed, and which check failed."""
    parts: list[str] = []
    for score in scores:
        if score.failed_labels:
            joined = ", ".join(score.failed_labels)
            parts.append(f"{score.company} / {score.tone} ({joined})")
    if not parts:
        return "Every draft in this set passed all six checks."
    return "Misses: " + "; ".join(parts) + "."


def _gate_prose(gate: GateReport) -> str:
    if gate.not_blocked == 0:
        bypass = "Every counted run stopped before send."
    elif gate.not_blocked == 1:
        bypass = "The one counted run that did not stop had auto-send on and a recipient."
    else:
        bypass = (
            f"{gate.not_blocked} counted runs did not stop. "
            "They had auto-send on and a recipient."
        )
    if gate.screen_sets_auto_send:
        screen = "The review screen source mentions auto-send."
    else:
        screen = (
            "The review screen source does not mention auto-send, "
            "so the screen cannot take that bypass."
        )
    return (
        f"The gate stopped a send in {gate.blocked} of {gate.reached_draft} runs "
        f"that produced a draft. {gate.no_draft} runs produced no draft and are not "
        f"in that fraction. {bypass} {screen}"
    )


def success_metrics_markdown(
    demo_scores: list[DraftScore] | None = None,
    fixture_scores: list[DraftScore] | None = None,
    gate: GateReport | None = None,
    note_scores: list[NoteScore] | None = None,
) -> str:
    """The Success metrics section, computed from the fixtures.

    ``docs/PRODUCT.md`` must contain this text. The test fails if the note
    and the script disagree.
    """
    demo = score_cases(load_demo_cases()) if demo_scores is None else demo_scores
    fixtures = score_cases(load_eval_cases()) if fixture_scores is None else fixture_scores
    notes = load_demo_notes() if note_scores is None else note_scores
    measured = measure_confirm_gate() if gate is None else gate
    return "\n".join(
        [
            "## Success metrics",
            "",
            "These figures come from `make eval` on files in this repo. No model was called, no email was sent, and there are no users. Replies, minutes from a URL to a draft someone will send, and how often a person stops on a real list are still unmeasured. There is no campaign to count.",
            "",
            f"Prompt version: `{PROMPT_VERSION}`, from `src/prompts.py`. Saved drafts and notes were written by hand. Changing the live prompt does not change these scores until the saved text changes too. The review screen runs the same string checks on the draft in front of you. A failing check does not block confirm.",
            "",
            f"### Saved research notes ({len(notes)})",
            "",
            "Northwind Analytics and Harbor & Pine Goods. Each saved note keeps quotes copied from the HTML separate from labeled inferences. A quote that is not on the page fails. These notes are not model output.",
            "",
            note_summary_table(notes),
            "",
            note_miss_line(notes),
            "",
            f"### Saved demo drafts ({len(demo)})",
            "",
            "Northwind Analytics and Harbor & Pine Goods, four tones each. These are the drafts `make demo` shows. The page text is the saved HTML. The rubric is [DRAFT_RUBRIC.md](DRAFT_RUBRIC.md).",
            "",
            summary_table(demo),
            "",
            miss_line(demo),
            "",
            f"### Fixture drafts ({len(fixtures)})",
            "",
            "One hand-written draft for each fictional company page in `fixtures/eval`. Some were written to miss a single check, so a row of perfect scores would mean that check never fires. They are not model output.",
            "",
            summary_table(fixtures),
            "",
            miss_line(fixtures),
            "",
            "### Confirm gate in the test scenarios",
            "",
            "Each row is a pipeline run from the situations the test suite covers. A run counts when it produced a draft. Stopped means the stage stayed at review and send was not called.",
            "",
            measured.markdown(),
            "",
            _gate_prose(measured),
        ]
    )


def render_report() -> str:
    """Full text for ``make eval``, including the product-note section."""
    demo = score_cases(load_demo_cases())
    fixtures = score_cases(load_eval_cases())
    gate = measure_confirm_gate()
    return success_metrics_markdown(demo, fixtures, gate)


def main() -> int:
    """Print the report. Exit 0 when the fixtures are consistent.

    A draft that fails a rubric check is a result, not a script error.
    """
    logging.getLogger("src.demo").setLevel(logging.WARNING)
    logging.getLogger("src.agent").setLevel(logging.WARNING)
    try:
        print(render_report())
    except DraftEvalError as exc:
        logger.error("%s", exc)
        print(f"Eval fixtures are inconsistent: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
