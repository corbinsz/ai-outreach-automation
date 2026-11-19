"""Records passed between scrape, analysis, draft, and send.

Pydantic is the boundary on purpose. A malformed model response should fail
when it is parsed, not halfway through an SMTP send.
"""

import os
import uuid
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel, Field

# Neutral fallback when SENDER_NAME is unset and the caller passes no name.
DEFAULT_SENDER_NAME = "Your Name"

# Pinned so a library default cannot change the draft without a diff in this repo.
# Replace the snapshot when Anthropic retires it. There is no fallback model.
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

ProgressCallback = Callable[[str], None]


def resolve_sender_name(sender_name: str | None = None) -> str:
    """Prefer an explicit name, then SENDER_NAME, then a neutral default.

    The sign-off used to be a hard-coded brand. A personal project should
    send as the person running it, and should still run if they have not
    chosen a name yet.
    """
    if sender_name and sender_name.strip():
        return sender_name.strip()
    configured = os.getenv("SENDER_NAME", "").strip()
    return configured or DEFAULT_SENDER_NAME


class ScrapedPage(BaseModel):
    """One fetched page, already reduced to text."""

    url: str
    title: str = ""
    content: str = ""
    page_type: str = "unknown"


class ScrapedWebsite(BaseModel):
    """What the scraper managed to read. An empty pages list means the fetch failed."""

    base_url: str
    company_name: str = ""
    pages: list[ScrapedPage] = Field(default_factory=list)
    raw_text_summary: str = ""
    contact_emails: list[str] = Field(default_factory=list)


class NeedAnalysis(BaseModel):
    """Structured notes from Claude. Fields can be inferred, not observed. See the product notes."""

    company_name: str
    company_summary: str
    industry: str
    services_offered: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    ai_opportunities: list[str] = Field(default_factory=list)
    value_proposition: str = ""
    recommended_angle: str = ""


class EmailDraft(BaseModel):
    """A draft waiting for a person. to_address stays empty until send time."""

    to_address: str = ""
    subject: str
    body: str
    tone: str = "professional"


class OutreachRecord(BaseModel):
    """One row in the local JSON log.

    opened_at and replied_at are filled by the UI, not by a tracking pixel.
    Streamlit on a laptop is not a public endpoint, and a pixel would record
    someone opening mail they did not ask for.

    ``id`` is stable for the life of the row. Follow-up edits use it so they
    do not depend on "the last line in the file."
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    prospect_url: str
    prospect_name: str
    recipient_email: str
    email_subject: str
    email_body: str
    status: str = "drafted"
    error_message: str | None = None
    opened_at: str | None = None
    replied_at: str | None = None
    follow_up_date: str | None = None
    notes: str | None = None
