"""Run scrape, analysis, and draft as one pipeline.

The default stop is a draft. auto_send exists for a scripted caller. The
Streamlit UI does not set it: a person confirms on the page, then calls send.
Batch mode always stops at the draft so a list of URLs cannot mail itself.
"""

import logging
from dataclasses import dataclass, field

from src.analyzer import analyze_prospect
from src.demo import demo_analysis, demo_draft, demo_scrape, demo_send
from src.email_drafter import draft_email
from src.gmail_sender import send_email
from src.models import (
    DEFAULT_MODEL,
    EmailDraft,
    NeedAnalysis,
    OutreachRecord,
    ProgressCallback,
    ScrapedWebsite,
    resolve_sender_name,
)
from src.scraper import scrape_website

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for the outreach agent."""

    anthropic_api_key: str
    gmail_address: str = ""
    gmail_app_password: str = ""
    sender_name: str = field(default_factory=resolve_sender_name)
    tone: str = "professional"
    llm_model: str = DEFAULT_MODEL
    use_playwright: bool = True
    demo_mode: bool = False


@dataclass
class PipelineResult:
    """Everything one URL produced, including the stage it stopped at.

    stage is a string because the UI and the tests match on a handful of
    values. An enum would not add a check they do not already have.
    """

    url: str
    scraped: ScrapedWebsite | None = None
    analysis: NeedAnalysis | None = None
    draft: EmailDraft | None = None
    send_result: OutreachRecord | None = None
    error: str | None = None
    stage: str = "not_started"


class OutreachAgent:
    """One configured pass over the four stages. The stages are also public so the UI can drive them."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def scrape(self, url: str, progress_callback: ProgressCallback | None = None) -> ScrapedWebsite:
        """Phase 1: Scrape the prospect's website, or load a saved sample in demo mode."""
        if self.config.demo_mode:
            return demo_scrape(url, progress_callback=progress_callback)
        return scrape_website(
            url=url,
            use_playwright_fallback=self.config.use_playwright,
            progress_callback=progress_callback,
        )

    def analyze(self, scraped: ScrapedWebsite) -> NeedAnalysis:
        """Phase 2: Analyze the prospect's needs via LLM, or load the saved notes."""
        if self.config.demo_mode:
            return demo_analysis(scraped)
        return analyze_prospect(
            scraped=scraped,
            api_key=self.config.anthropic_api_key,
            model=self.config.llm_model,
        )

    def draft(self, analysis: NeedAnalysis) -> EmailDraft:
        """Phase 3: Draft a personalized outreach email, or load the saved draft."""
        if self.config.demo_mode:
            return demo_draft(
                analysis=analysis,
                sender_name=self.config.sender_name,
                tone=self.config.tone,
            )
        return draft_email(
            analysis=analysis,
            api_key=self.config.anthropic_api_key,
            sender_name=self.config.sender_name,
            tone=self.config.tone,
            model=self.config.llm_model,
        )

    def send(
        self,
        draft: EmailDraft,
        to_address: str,
        prospect_url: str = "",
        prospect_name: str = "",
    ) -> OutreachRecord:
        """Phase 4: Send the email via Gmail, or record a local practice send in demo mode."""
        if self.config.demo_mode:
            return demo_send(
                draft=draft,
                to_address=to_address,
                sender_name=self.config.sender_name,
                prospect_url=prospect_url,
                prospect_name=prospect_name,
            )
        return send_email(
            draft=draft,
            to_address=to_address,
            gmail_address=self.config.gmail_address,
            gmail_app_password=self.config.gmail_app_password,
            sender_name=self.config.sender_name,
            prospect_url=prospect_url,
            prospect_name=prospect_name,
        )

    def run_pipeline(
        self,
        url: str,
        to_address: str = "",
        auto_send: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> PipelineResult:
        """Run one URL. Stops at the draft unless auto_send is set and a recipient is present."""
        result = PipelineResult(url=url)

        def _log(msg: str) -> None:
            logger.info(msg)
            if progress_callback:
                progress_callback(msg)

        try:
            # Phase 1: Scrape
            result.stage = "scraping"
            _log(f"Phase 1: Scraping {url}...")
            result.scraped = self.scrape(url, progress_callback=progress_callback)

            if not result.scraped.pages:
                result.error = (
                    result.scraped.scrape_note or "Failed to scrape any content from the website."
                )
                result.stage = "failed"
                return result

            # Phase 2: Analyze
            result.stage = "analyzing"
            _log("Phase 2: Analyzing prospect needs...")
            result.analysis = self.analyze(result.scraped)
            _log(f"Analysis complete: {result.analysis.company_name}")

            # Phase 3: Draft
            result.stage = "drafting"
            _log("Phase 3: Drafting outreach email...")
            result.draft = self.draft(result.analysis)
            _log(f'Draft ready: "{result.draft.subject}"')

            # Phase 4: Send (only if auto_send)
            if auto_send and to_address:
                result.stage = "sending"
                _log(f"Phase 4: Sending to {to_address}...")
                result.send_result = self.send(
                    draft=result.draft,
                    to_address=to_address,
                    prospect_url=url,
                    prospect_name=result.analysis.company_name,
                )
                if result.send_result.status == "sent":
                    result.stage = "complete"
                    _log("Email sent successfully!")
                else:
                    result.stage = "failed"
                    result.error = result.send_result.error_message
                    _log(f"Send failed: {result.error}")
            else:
                result.stage = "reviewing"
                _log("Pipeline paused for review. Approve to send.")

        except Exception as e:
            result.error = str(e)
            result.stage = "failed"
            logger.error(f"Pipeline error: {e}", exc_info=True)
            _log(f"Error: {e}")

        return result

    def run_batch(
        self,
        urls: list[str],
        progress_callback: ProgressCallback | None = None,
    ) -> list[PipelineResult]:
        """Draft every URL. One failure is recorded and the next URL still runs."""
        results = []
        for i, url in enumerate(urls, 1):
            if progress_callback:
                progress_callback(f"\n--- Processing {i}/{len(urls)}: {url} ---")
            result = self.run_pipeline(url=url, progress_callback=progress_callback)
            results.append(result)
        return results
