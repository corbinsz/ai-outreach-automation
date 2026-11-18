"""Pydantic models for structured data throughout the pipeline."""

import os
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# Neutral fallback when SENDER_NAME is unset and the caller passes no name.
DEFAULT_SENDER_NAME = "Your Name"


def resolve_sender_name(sender_name: Optional[str] = None) -> str:
    """Use an explicit name, then SENDER_NAME, then a neutral default."""
    if sender_name and sender_name.strip():
        return sender_name.strip()
    configured = os.getenv("SENDER_NAME", "").strip()
    return configured or DEFAULT_SENDER_NAME


class ScrapedPage(BaseModel):
    """A single scraped page from a website."""
    url: str
    title: str = ""
    content: str = ""
    page_type: str = "unknown"  # homepage, about, services, blog, contact, etc.


class ScrapedWebsite(BaseModel):
    """Complete scraped data from a prospect's website."""
    base_url: str
    company_name: str = ""
    pages: list[ScrapedPage] = Field(default_factory=list)
    raw_text_summary: str = ""
    contact_emails: list[str] = Field(default_factory=list)


class NeedAnalysis(BaseModel):
    """LLM-generated analysis of a prospect's needs."""
    company_name: str
    company_summary: str
    industry: str
    services_offered: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    ai_opportunities: list[str] = Field(default_factory=list)
    value_proposition: str = ""
    recommended_angle: str = ""


class EmailDraft(BaseModel):
    """A drafted outreach email."""
    to_address: str = ""
    subject: str
    body: str
    tone: str = "professional"


class OutreachRecord(BaseModel):
    """CRM-style log of an outreach attempt."""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    prospect_url: str
    prospect_name: str
    recipient_email: str
    email_subject: str
    email_body: str
    status: str = "drafted"  # drafted, sent, failed
    error_message: Optional[str] = None
    # --- Tracking & Follow-Up Fields ---
    opened_at: Optional[str] = None       # ISO timestamp when marked opened
    replied_at: Optional[str] = None      # ISO timestamp when marked replied
    follow_up_date: Optional[str] = None  # ISO date (YYYY-MM-DD) for scheduled follow-up
    notes: Optional[str] = None           # Free-text notes
