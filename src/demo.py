"""Offline sample companies for demo mode.

The pages are HTML files in ``fixtures/demo``. Notes and drafts are JSON
saved next to those pages. Nothing in this module opens a socket, calls a
model, or sends mail. The pipeline uses it when ``AgentConfig.demo_mode``
is set, which is what ``make demo`` turns on.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.gmail_sender import _log_outreach
from src.models import (
    EmailDraft,
    NeedAnalysis,
    OutreachRecord,
    ProgressCallback,
    ScrapedPage,
    ScrapedWebsite,
    resolve_sender_name,
)
from src.prompts import SAVED_SAMPLE_VERSION
from src.scraper import _extract_company_name, _extract_emails, _extract_text, _extract_title

logger = logging.getLogger(__name__)

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "demo"

_PAGE_FILES: tuple[tuple[str, str], ...] = (
    ("home.html", "homepage"),
    ("about.html", "about"),
    ("services.html", "services"),
    ("contact.html", "contact"),
)


class DemoSampleNotFound(Exception):
    """Raised when demo mode is asked for a company that is not in the fixture set."""


@dataclass(frozen=True)
class DemoCompany:
    """One fictional company a reviewer can run without a network."""

    slug: str
    name: str
    url: str
    blurb: str

    @property
    def directory(self) -> Path:
        return FIXTURE_ROOT / self.slug


DEMO_COMPANIES: tuple[DemoCompany, ...] = (
    DemoCompany(
        slug="northwind",
        name="Northwind Analytics",
        url="https://northwind.example",
        blurb="12-person analytics consultancy. Monday reports still come out of spreadsheets.",
    ),
    DemoCompany(
        slug="harbor",
        name="Harbor & Pine Goods",
        url="https://harborpine.example",
        blurb="Small home-goods studio. Wholesale orders still live in a spreadsheet.",
    ),
)


def _host_key(url: str) -> str:
    text = url.strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    host = urlparse(text).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host.startswith("www."):
        host = host[4:]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host


def match_demo_company(url: str) -> DemoCompany | None:
    """Return the sample whose host matches ``url``, ignoring a leading www."""
    host = _host_key(url)
    if not host:
        return None
    for company in DEMO_COMPANIES:
        if host == _host_key(company.url):
            return company
    return None


def _sample_list() -> str:
    return ", ".join(company.url for company in DEMO_COMPANIES)


def _require_company(url: str) -> DemoCompany:
    company = match_demo_company(url)
    if company is None:
        raise DemoSampleNotFound(
            f"Demo mode only serves the built-in sample companies ({_sample_list()}). "
            f"It does not fetch {url.strip() or 'an empty URL'}. "
            "Turn off Demo mode to read a live site."
        )
    return company


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path.name}.")
    return data


def _company_for_analysis(analysis: NeedAnalysis) -> DemoCompany:
    for company in DEMO_COMPANIES:
        if company.name == analysis.company_name:
            return company
    raise DemoSampleNotFound(
        "Demo mode has no saved draft for " f"{analysis.company_name}. Samples: {_sample_list()}."
    )


def _log(message: str, progress_callback: ProgressCallback | None) -> None:
    logger.info(message)
    if progress_callback is not None:
        progress_callback(message)


def demo_scrape(url: str, progress_callback: ProgressCallback | None = None) -> ScrapedWebsite:
    """Build a scraped site from the saved HTML. Does not touch the network."""
    company = _require_company(url)
    _log(
        f"Demo mode: loading saved pages for {company.name}. No network request.",
        progress_callback,
    )

    pages: list[ScrapedPage] = []
    emails: dict[str, None] = {}
    company_name = company.name
    for filename, page_type in _PAGE_FILES:
        html = (company.directory / filename).read_text(encoding="utf-8")
        text = _extract_text(html)
        if page_type == "homepage":
            company_name = _extract_company_name(html, company.url) or company.name
        page_url = company.url if page_type == "homepage" else f"{company.url}/{page_type}"
        pages.append(
            ScrapedPage(
                url=page_url,
                title=_extract_title(html),
                content=text,
                page_type=page_type,
            )
        )
        for address in _extract_emails(html):
            emails[address] = None
        _log(f"Loaded {page_type} fixture ({len(text)} chars).", progress_callback)

    summary = "\n\n".join(
        f"=== {page.page_type.upper()}: {page.title} ===\n{page.content}" for page in pages
    )
    _log(f"Demo scrape complete: {len(pages)} saved pages.", progress_callback)
    return ScrapedWebsite(
        base_url=company.url,
        company_name=company_name,
        pages=pages,
        raw_text_summary=summary,
        contact_emails=list(emails),
    )


def demo_analysis(scraped: ScrapedWebsite) -> NeedAnalysis:
    """Return the saved notes for this sample. Does not call a model."""
    company = _require_company(scraped.base_url)
    logger.info("Demo mode: using saved notes for %s.", company.name)
    notes = NeedAnalysis(**_load_json(company.directory / "analysis.json"))
    return notes.model_copy(update={"prompt_version": SAVED_SAMPLE_VERSION, "model": ""})


def demo_draft(analysis: NeedAnalysis, sender_name: str | None, tone: str) -> EmailDraft:
    """Return the saved draft for this tone, with the sender name filled in."""
    company = _company_for_analysis(analysis)
    drafts = _load_json(company.directory / "drafts.json")
    chosen = drafts.get(tone)
    if not isinstance(chosen, dict):
        logger.warning("Demo mode has no %s draft for %s; using professional.", tone, company.name)
        chosen = drafts["professional"]
    subject = str(chosen["subject"]).strip()
    body = str(chosen["body"]).replace("{{sender_name}}", resolve_sender_name(sender_name))
    logger.info("Demo mode: using saved %s draft for %s.", tone, company.name)
    return EmailDraft(
        subject=subject,
        body=body,
        tone=tone if tone in drafts else "professional",
        prompt_version=SAVED_SAMPLE_VERSION,
        model="",
    )


def demo_send(
    draft: EmailDraft,
    to_address: str,
    sender_name: str | None = None,
    prospect_url: str = "",
    prospect_name: str = "",
) -> OutreachRecord:
    """Record a practice send in the local log. Does not open an SMTP connection.

    ``sender_name`` is accepted so the call matches ``send_email``. The saved
    draft already contains the name, and no message is handed to a mail server.
    """
    del sender_name  # The draft is already signed. Nothing is transmitted.
    record = OutreachRecord(
        prospect_url=prospect_url,
        prospect_name=prospect_name,
        recipient_email=to_address,
        email_subject=draft.subject,
        email_body=draft.body,
        status="demo_sent",
        notes="Demo mode: saved on this machine. No email was sent.",
        prompt_version=draft.prompt_version,
    )
    _log_outreach(record)
    logger.info("Demo send recorded locally for %s. No email was sent.", to_address)
    return record
