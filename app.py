"""Local Streamlit UI for a personal outreach project.

The page is a review desk. Scraping and drafting happen here, and mail
leaves only after you press confirm. Demo mode loads saved pages and a
saved draft so the same desk works with no API key and no network.
Styles live in assets/styles.css so this file stays the interaction logic.
"""

import html as html_module
from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from src.agent import AgentConfig, OutreachAgent, PipelineResult
from src.config import (
    ANTHROPIC_KEY_MESSAGE,
    GMAIL_ADDRESS_PLACEHOLDERS,
    GMAIL_MISSING_MESSAGE,
    GMAIL_PASSWORD_PLACEHOLDERS,
    anthropic_key_is_unset,
    configure_logging,
    gmail_is_unset,
    is_unset,
    load_settings,
)
from src.demo import DEMO_COMPANIES
from src.gmail_sender import get_outreach_log, update_outreach_record, update_outreach_record_by_id
from src.models import DEFAULT_MODEL, EmailDraft, OutreachRecord, resolve_sender_name
from src.recipients import suggested_recipient

load_dotenv()

_logging_ready = False


def esc(text: str) -> str:
    """Escape text before it is placed in HTML.

    Analysis and drafts come from a model and from pages it read. Those
    strings are data, not markup we control.
    """
    return html_module.escape(str(text)) if text else ""


st.set_page_config(
    page_title="AI Outreach",
    page_icon="✉️",
    layout="wide",
    initial_sidebar_state="expanded",
)

_STYLES_PATH = Path(__file__).resolve().parent / "assets" / "styles.css"


def _page_styles() -> str:
    """Load the local stylesheet. It lives beside the app so this file stays the UI logic."""
    return _STYLES_PATH.read_text(encoding="utf-8")


st.markdown(f"<style>{_page_styles()}</style>", unsafe_allow_html=True)

SVG_TARGET = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>'
SVG_BOOK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>'
SVG_ENVELOPE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>'
SVG_SEND = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="m22 2-11 11"/></svg>'
SVG_GRID = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>'
SVG_DOC = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>'
SVG_CALENDAR = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>'


def section_header(title: str, subtitle: str, svg: str, color: str) -> str:
    """Section title with an icon. Titles are escaped because some include model text."""
    return (
        f'<div class="section-header">'
        f'<div class="section-icon section-icon-{color}">{svg}</div>'
        f'<div><p class="section-title">{esc(title)}</p>'
        f'<p class="section-subtitle">{esc(subtitle)}</p></div>'
        f"</div>"
    )


def _state_str(key: str, default: str = "") -> str:
    value = st.session_state.get(key, default)
    return value if isinstance(value, str) else default


def _state_bool(key: str, default: bool = False) -> bool:
    value = st.session_state.get(key, default)
    return bool(value) if isinstance(value, bool) else default


def _state_int(key: str, default: int = 0) -> int:
    value = st.session_state.get(key, default)
    return value if isinstance(value, int) else default


def init_session_state() -> None:
    """Seed widget state once.

    Streamlit reruns this script on every click. Defaults live here so a
    rerun does not wipe a draft that is still being edited. Placeholder
    secrets from `.env.example` are treated as blank.
    """
    settings = load_settings()
    api_key = (
        "" if anthropic_key_is_unset(settings.anthropic_api_key) else settings.anthropic_api_key
    )
    gmail_address = settings.gmail_address
    if is_unset(gmail_address, GMAIL_ADDRESS_PLACEHOLDERS):
        gmail_address = ""
    gmail_password = settings.gmail_app_password
    if is_unset(gmail_password, GMAIL_PASSWORD_PLACEHOLDERS):
        gmail_password = ""
    defaults: dict[str, object] = {
        "pipeline_result": None,
        "scrape_logs": [],
        "email_subject": "",
        "email_body": "",
        "pipeline_run_id": 0,
        "draft_version": 0,
        "send_result": None,
        "last_send_id": None,
        "celebrated_send_id": None,
        "form_error": None,
        "batch_results": [],
        "batch_error": None,
        "prospect_url": "",
        "api_key": api_key,
        "gmail_addr": gmail_address,
        "gmail_pass": gmail_password,
        "sender_name": resolve_sender_name(settings.sender_name),
        "tone": "professional",
        "demo_mode": settings.demo_mode,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def get_agent_config() -> AgentConfig:
    """Build AgentConfig from the sidebar.

    The model id is a constant on purpose. A silent SDK default would change
    the draft without the change showing up in this repo.
    """
    return AgentConfig(
        anthropic_api_key=_state_str("api_key"),
        gmail_address=_state_str("gmail_addr"),
        gmail_app_password=_state_str("gmail_pass"),
        sender_name=resolve_sender_name(_state_str("sender_name")),
        tone=_state_str("tone", "professional") or "professional",
        llm_model=DEFAULT_MODEL,
        use_playwright=True,
        demo_mode=_state_bool("demo_mode"),
    )


def _follow_up_day(record: OutreachRecord) -> str:
    """Return the saved follow-up date, or an empty string when there is none."""
    when = record.follow_up_date
    return when if isinstance(when, str) else ""


def _status_badge(record: OutreachRecord) -> tuple[str, str]:
    """Return the short label and CSS class for one log row."""
    if record.replied_at:
        return "REPLIED", "status-replied"
    if record.opened_at:
        return "OPENED", "status-opened"
    if record.status == "sent":
        return "SENT", "status-sent"
    if record.status == "demo_sent":
        return "DEMO", "status-demo"
    if record.status == "failed":
        return "FAILED", "status-failed"
    return "DRAFT", "status-draft"


def render_sidebar() -> None:
    """Sidebar for demo mode, keys, Gmail, and tone. Nothing here is written to disk."""
    with st.sidebar:
        st.markdown(
            '<div class="sidebar-logo-block">'
            '<div class="sidebar-logo-mark">A</div>'
            "<div>"
            '<div class="sidebar-logo-text">AI Outreach</div>'
            '<div class="sidebar-logo-sub">Personal project</div>'
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown('<p class="sidebar-section-label">Configuration</p>', unsafe_allow_html=True)
        st.toggle(
            "Demo mode",
            key="demo_mode",
            help=(
                "Use the two sample companies saved in this repo. "
                "No API key, no network, and Confirm writes a local practice row instead of email."
            ),
        )
        if _state_bool("demo_mode"):
            st.caption("Demo mode is on. The Anthropic key and Gmail settings are not used.")
        else:
            st.caption("Demo mode is off. Analysis needs an Anthropic key. Sending needs Gmail.")

        key_label = (
            "Anthropic API Key (not used in demo mode)"
            if _state_bool("demo_mode")
            else "Anthropic API Key (required)"
        )
        st.text_input(
            key_label,
            type="password",
            key="api_key",
            help="Your Anthropic API key for Claude. Required for a live website, not for demo mode.",
        )

        st.markdown("---")
        st.markdown('<p class="sidebar-section-label">Gmail Settings</p>', unsafe_allow_html=True)
        st.caption(
            "Only needed when you send a real email. Demo mode never contacts Gmail. "
            "Scraping and drafting work without these."
        )

        st.text_input(
            "Gmail Address",
            key="gmail_addr",
            help="The Gmail address real emails will be sent from.",
        )
        st.text_input(
            "Gmail App Password",
            type="password",
            key="gmail_pass",
            help=(
                "16-character App Password from Google Account > Security > App Passwords. "
                "This is NOT your Gmail login password."
            ),
        )
        st.text_input(
            "Sender Name",
            key="sender_name",
            help=(
                "The name recipients see on the From line. "
                "Set SENDER_NAME in .env to prefill this."
            ),
        )

        st.markdown("---")
        st.markdown('<p class="sidebar-section-label">Email Tone</p>', unsafe_allow_html=True)

        st.selectbox(
            "Tone / Style",
            options=["professional", "conversational", "bold", "consultative"],
            index=0,
            key="tone",
            help=(
                "Controls the writing style of the generated email. "
                "In demo mode each tone has its own saved draft."
            ),
        )

        st.markdown("---")
        st.markdown(
            '<div class="sidebar-footer">'
            "Live analysis runs on Claude.<br>"
            "Sending uses your own Gmail app password."
            "</div>",
            unsafe_allow_html=True,
        )


def _show_scrape_log() -> None:
    logs = st.session_state.get("scrape_logs", [])
    with st.expander("Scraping Log — See what pages were discovered and fetched", expanded=False):
        if isinstance(logs, list):
            for log_line in logs:
                if isinstance(log_line, str):
                    st.text(log_line)


def _advance(progress: st.delta_generator.DeltaGenerator, message: str) -> None:
    """Move the bar from the pipeline's own progress lines."""
    if message.startswith("Phase 1") or message.startswith("Demo mode: loading"):
        progress.progress(15, text="Reading the site...")
    elif "Loaded " in message or "Homepage scraped" in message or "Discovered" in message:
        progress.progress(40, text="Reading the site...")
    elif message.startswith("Phase 2"):
        progress.progress(60, text="Writing notes...")
    elif message.startswith("Phase 3"):
        progress.progress(80, text="Drafting the email...")
    elif "paused for review" in message or "sent successfully" in message:
        progress.progress(100, text="Ready for review")


def render_single_mode() -> None:
    """One URL: scrape, analyze, draft, then wait for a person to send."""
    st.markdown(
        section_header(
            "Single Prospect Outreach",
            "Scrape, analyze, and draft a personalized email",
            SVG_TARGET,
            "blue",
        ),
        unsafe_allow_html=True,
    )
    demo_mode = _state_bool("demo_mode")
    if demo_mode:
        st.caption(
            "Demo mode reads two companies saved in this repo. "
            "Pick one, or paste its URL. A live URL is refused until you turn demo mode off."
        )
        columns = st.columns(len(DEMO_COMPANIES))
        for column, company in zip(columns, DEMO_COMPANIES, strict=True):
            with column:
                st.markdown(f"**{esc(company.name)}**")
                st.caption(company.blurb)
                if st.button(
                    "Run this sample",
                    key=f"demo_{company.slug}",
                    use_container_width=True,
                ):
                    st.session_state["prospect_url"] = company.url
                    st.session_state["run_requested"] = True
                    st.rerun()
    else:
        st.caption(
            "Paste a company's website URL below. The app reads a few pages, "
            "asks Claude for notes, and drafts an email you can edit."
        )

    col1, col2 = st.columns([3, 1])
    with col1:
        url = st.text_input(
            "Prospect Website URL",
            key="prospect_url",
            placeholder="https://northwind.example" if demo_mode else "https://example.com",
            help=(
                "In demo mode use https://northwind.example or https://harborpine.example. "
                "Live mode reads the homepage and a few internal pages such as About and Services."
            ),
        )
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        run_clicked = st.button(
            "Run Pipeline",
            type="primary",
            use_container_width=True,
            key="run_pipeline",
        )

    if st.session_state.pop("run_requested", False):
        run_clicked = True

    if run_clicked:
        config = get_agent_config()
        if not url.strip():
            st.session_state["form_error"] = (
                "Enter a website URL. In demo mode, run Northwind Analytics or Harbor & Pine."
            )
        elif not config.demo_mode and anthropic_key_is_unset(config.anthropic_api_key):
            st.session_state["form_error"] = ANTHROPIC_KEY_MESSAGE
        else:
            st.session_state["form_error"] = None
            st.session_state["send_result"] = None
            st.session_state["last_send_id"] = None
            logs: list[str] = []
            st.session_state["scrape_logs"] = logs
            progress_bar = st.progress(5, text="Starting...")
            status_placeholder = st.empty()

            def progress_cb(msg: str) -> None:
                logs.append(msg)
                status_placeholder.text(msg)
                _advance(progress_bar, msg)

            agent = OutreachAgent(config)
            ran = agent.run_pipeline(url=url.strip(), progress_callback=progress_cb)
            st.session_state["pipeline_result"] = ran
            st.session_state["pipeline_run_id"] = _state_int("pipeline_run_id") + 1
            if ran.draft is not None:
                st.session_state["email_subject"] = ran.draft.subject
                st.session_state["email_body"] = ran.draft.body
                # A new widget key lets the text fields pick up this draft.
                # Reusing the old key would keep the previous text.
                st.session_state["draft_version"] = _state_int("draft_version") + 1
            if ran.error:
                st.session_state["form_error"] = ran.error
            progress_bar.progress(100, text="Done" if ran.stage != "failed" else "Stopped")

    form_error = st.session_state.get("form_error")
    if isinstance(form_error, str) and form_error:
        st.error(form_error)

    stored = st.session_state.get("pipeline_result")
    result = stored if isinstance(stored, PipelineResult) else None
    if result is None:
        st.info(
            "Enter a prospect's website URL above and click **Run Pipeline** to start. "
            "Nothing is scraped until you do, and nothing is sent until you confirm."
        )
        return

    _show_scrape_log()
    if result.stage == "failed":
        return

    if result.analysis:
        st.markdown("---")
        st.markdown(
            section_header(
                "Prospect Analysis",
                "Notes from the saved sample" if demo_mode else "Notes from the scraped pages",
                SVG_BOOK,
                "purple",
            ),
            unsafe_allow_html=True,
        )
        if result.scraped is not None and len(result.scraped.raw_text_summary) < 400:
            st.warning(
                "These pages did not have much text. Treat the notes as inferences, not quotes."
            )

        analysis = result.analysis
        industry_tag = (
            f'<span class="tag-pill tag-industry">{esc(analysis.industry)}</span>'
            if analysis.industry
            else ""
        )
        overview_html = (
            f'<div class="styled-card">'
            f'<div class="overview-grid">'
            f'<div><div class="overview-label">Company</div>'
            f'<div class="overview-value">{esc(analysis.company_name)}</div></div>'
            f'<div><div class="overview-label">Industry</div>'
            f'<div class="overview-value">{industry_tag}</div></div>'
            f"</div>"
            f'<div style="margin-top:0.75rem;"><div class="overview-label">Summary</div>'
            f'<div class="overview-value">{esc(analysis.company_summary)}</div></div>'
            f"</div>"
        )
        st.markdown(overview_html, unsafe_allow_html=True)

        col_a, col_b = st.columns(2)
        with col_a:
            if analysis.services_offered:
                services_html = (
                    '<div class="styled-card"><div class="overview-label">Services</div>'
                    '<div style="margin-top:0.4rem;">'
                )
                for service in analysis.services_offered:
                    services_html += f'<span class="tag-pill">{esc(service)}</span>'
                services_html += "</div></div>"
                st.markdown(services_html, unsafe_allow_html=True)
            if analysis.pain_points:
                pain_html = (
                    '<div class="overview-label" style="margin-top:0.5rem;">Pain Points</div>'
                    '<div class="item-list">'
                )
                for pain in analysis.pain_points:
                    pain_html += f'<div class="item-pain"><div class="dot-red"></div><div>{esc(pain)}</div></div>'
                pain_html += "</div>"
                st.markdown(pain_html, unsafe_allow_html=True)
        with col_b:
            if analysis.ai_opportunities:
                opp_html = (
                    '<div class="overview-label">AI Opportunities</div><div class="item-list">'
                )
                for opportunity in analysis.ai_opportunities:
                    opp_html += (
                        f'<div class="item-opp"><div class="dot-green"></div>'
                        f"<div>{esc(opportunity)}</div></div>"
                    )
                opp_html += "</div>"
                st.markdown(opp_html, unsafe_allow_html=True)

        if analysis.value_proposition:
            vp_html = (
                f'<div class="styled-card-accent">'
                f'<div class="overview-label">Value Proposition</div>'
                f'<div class="overview-value">{esc(analysis.value_proposition)}</div>'
            )
            if analysis.recommended_angle:
                vp_html += (
                    f'<div style="margin-top:0.75rem;">'
                    f'<div class="overview-label">Recommended Angle</div>'
                    f'<div class="overview-value" style="font-style:italic;">'
                    f"{esc(analysis.recommended_angle)}</div></div>"
                )
            vp_html += "</div>"
            st.markdown(vp_html, unsafe_allow_html=True)

    if result.draft:
        st.markdown("---")
        st.markdown(
            section_header("Email Draft", "Review and edit before sending", SVG_ENVELOPE, "green"),
            unsafe_allow_html=True,
        )
        if demo_mode:
            st.caption(
                "This draft was loaded from the repo, not from a live model call. "
                "Edit it, change the tone and regenerate, or confirm a practice send. "
                "Confirm does not email anyone."
            )
        else:
            st.caption(
                "This email was generated from the notes above. "
                "Edit it before sending, or regenerate it."
            )

        version = _state_int("draft_version")
        edited_subject = st.text_input(
            "Subject",
            value=_state_str("email_subject"),
            key=f"subject_{version}",
        )
        edited_body = st.text_area(
            "Body",
            value=_state_str("email_body"),
            key=f"body_{version}",
            height=300,
        )
        st.session_state["email_subject"] = edited_subject
        st.session_state["email_body"] = edited_body

        st.markdown("---")
        st.markdown(
            section_header(
                "Send Email",
                "Practice send, saved locally" if demo_mode else "Deliver via Gmail SMTP",
                SVG_SEND,
                "orange",
            ),
            unsafe_allow_html=True,
        )
        if demo_mode:
            st.caption(
                "Confirm writes a row to the local log and stops. " "No SMTP connection is opened."
            )
        else:
            st.caption(
                "Nothing is sent until you press Confirm. Use your own Gmail account, "
                "and only email someone you have a reason to contact. You are responsible "
                "for identifying yourself and honoring opt-outs."
            )

        found = result.scraped.contact_emails if result.scraped is not None else []
        default_to = suggested_recipient(found, demo_mode=demo_mode)
        if found and demo_mode:
            st.success(
                "Sample address, not a real inbox: **"
                + ", ".join(found)
                + "**. Confirming records a practice send only."
            )
        elif found:
            st.info(
                f"Found {len(found)} address(es) on the site: **{', '.join(found)}**. "
                "The To field is blank so you choose the recipient. "
                "The first address on a page is often a shared inbox."
            )
        else:
            st.caption("No contact emails found on the website. Enter one manually.")

        run_id = _state_int("pipeline_run_id")
        to_address = st.text_input(
            "Recipient Email Address",
            value=default_to,
            key=f"to_address_{run_id}",
            placeholder="prospect@company.com",
            help="Who should receive this one email. Demo mode will not deliver it.",
        )

        col_send, col_regen = st.columns(2)
        with col_regen:
            if st.button("Regenerate Draft", use_container_width=True, key="regenerate_draft"):
                config = get_agent_config()
                if result.analysis is None:
                    st.error("There are no notes to draft from. Run the pipeline again.")
                elif not config.demo_mode and anthropic_key_is_unset(config.anthropic_api_key):
                    st.error(ANTHROPIC_KEY_MESSAGE)
                else:
                    try:
                        new_draft = OutreachAgent(config).draft(result.analysis)
                    except Exception as exc:
                        st.error(f"Could not regenerate the draft: {exc}")
                    else:
                        st.session_state["email_subject"] = new_draft.subject
                        st.session_state["email_body"] = new_draft.body
                        st.session_state["draft_version"] = version + 1
                        st.session_state["send_result"] = None
                        st.session_state["last_send_id"] = None
                        result.draft = new_draft
                        st.session_state["pipeline_result"] = result
                        st.rerun()

        with col_send:
            send_clicked = st.button(
                "Confirm & Send" if not demo_mode else "Confirm practice send",
                type="primary",
                use_container_width=True,
                disabled=not to_address.strip(),
                key="confirm_send",
            )

        if send_clicked and to_address.strip():
            config = get_agent_config()
            if not config.demo_mode and gmail_is_unset(
                config.gmail_address, config.gmail_app_password
            ):
                st.error(GMAIL_MISSING_MESSAGE)
            else:
                final_draft = EmailDraft(
                    subject=_state_str("email_subject"),
                    body=_state_str("email_body"),
                    to_address=to_address.strip(),
                    tone=config.tone,
                )
                with st.spinner("Saving..." if config.demo_mode else "Sending email..."):
                    sent = OutreachAgent(config).send(
                        draft=final_draft,
                        to_address=to_address.strip(),
                        prospect_url=result.url,
                        prospect_name=result.analysis.company_name if result.analysis else "",
                    )
                st.session_state["send_result"] = sent
                st.session_state["last_send_id"] = sent.id
                st.session_state["celebrated_send_id"] = None

    stored_send = st.session_state.get("send_result")
    if not isinstance(stored_send, OutreachRecord):
        return
    send_result = stored_send

    if send_result.status == "sent":
        if st.session_state.get("celebrated_send_id") != send_result.id:
            st.balloons()
            st.session_state["celebrated_send_id"] = send_result.id
        st.success(f"Email sent to {send_result.recipient_email}.")
    elif send_result.status == "demo_sent":
        st.success(
            "Practice send saved in the local log. "
            f"No email was sent to {send_result.recipient_email}."
        )
    elif send_result.status == "failed":
        st.error(send_result.error_message or "The send failed.")
        return

    if send_result.status not in {"sent", "demo_sent"}:
        return

    st.markdown("---")
    st.markdown(
        section_header(
            "Schedule Follow-Up",
            "Set a reminder on this send",
            SVG_CALENDAR,
            "orange",
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "The date is saved on this send's id, not on whatever row happens to be last in the file."
    )
    fu_col1, fu_col2 = st.columns([1, 2])
    with fu_col1:
        fu_date = st.date_input(
            "Follow-up date",
            value=date.today() + timedelta(days=3),
            key="post_send_fu_date",
        )
    with fu_col2:
        fu_note = st.text_input(
            "Note (optional)",
            key="post_send_fu_note",
            placeholder="e.g. Check if they wrote back",
        )

    if st.button("Save Follow-Up", key="post_send_fu_save"):
        record_id = _state_str("last_send_id")
        chosen = fu_date if isinstance(fu_date, date) else date.today()
        if not record_id:
            st.error("This send has no id, so the follow-up was not saved.")
        else:
            updates: dict[str, object] = {"follow_up_date": chosen.isoformat()}
            note = fu_note.strip()
            if note:
                current = next(
                    (row for row in get_outreach_log() if row.id == record_id),
                    None,
                )
                existing = current.notes if current is not None and current.notes else ""
                updates["notes"] = f"{existing}\n{note}".strip() if existing else note
            try:
                update_outreach_record_by_id(record_id, **updates)
            except KeyError:
                st.error("That send is no longer in the local log, so the follow-up was not saved.")
            else:
                st.success(f"Follow-up scheduled for {chosen.isoformat()}.")


def render_batch_mode() -> None:
    """Several URLs, each stopped at a draft. Batch mode never sends."""
    st.markdown(
        section_header("Batch Mode", "Process multiple prospects at once", SVG_GRID, "blue"),
        unsafe_allow_html=True,
    )
    demo_mode = _state_bool("demo_mode")
    if demo_mode:
        sample_urls = " and ".join(company.url for company in DEMO_COMPANIES)
        st.caption(
            "Batch mode drafts only. It never sends. "
            f"Demo mode accepts only the sample companies: {sample_urls}."
        )
    else:
        st.caption(
            "Each URL is scraped, analyzed, and drafted. "
            "Nothing is sent from this tab. Review each draft here, then send it from Single Outreach if you still want to."
        )

    urls_text = st.text_area(
        "Enter URLs (one per line)",
        placeholder=(
            "https://northwind.example\nhttps://harborpine.example"
            if demo_mode
            else "https://company1.com\nhttps://company2.com\nhttps://company3.com"
        ),
        height=150,
        key="batch_urls",
    )

    if st.button("Run Batch Pipeline", type="primary", key="run_batch"):
        urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
        config = get_agent_config()
        if not urls:
            st.session_state["batch_error"] = "Enter at least one URL."
        elif not config.demo_mode and anthropic_key_is_unset(config.anthropic_api_key):
            st.session_state["batch_error"] = ANTHROPIC_KEY_MESSAGE
        else:
            st.session_state["batch_error"] = None
            progress_bar = st.progress(0, text="Starting batch...")
            status = st.empty()

            def on_progress(msg: str) -> None:
                status.text(msg)
                if msg.startswith("Phase 1") or "Processing" in msg:
                    progress_bar.progress(30, text=msg[:80])
                elif msg.startswith("Phase 3") or "paused for review" in msg:
                    progress_bar.progress(80, text="Drafting...")

            batch_results = OutreachAgent(config).run_batch(urls, progress_callback=on_progress)
            progress_bar.progress(100, text="Batch complete")
            status.text(f"Processed {len(urls)} prospects. Drafts only. Nothing was sent.")
            st.session_state["batch_results"] = batch_results

    batch_error = st.session_state.get("batch_error")
    if isinstance(batch_error, str) and batch_error:
        st.error(batch_error)

    stored_batch = st.session_state.get("batch_results", [])
    batch_results = stored_batch if isinstance(stored_batch, list) else []
    if not batch_results:
        return

    st.markdown("---")
    for index, item in enumerate(batch_results):
        if not isinstance(item, PipelineResult):
            continue
        status_label = "[OK]" if item.stage == "reviewing" else "[FAILED]"
        label_name = item.analysis.company_name if item.analysis else item.url
        with st.expander(f"{status_label} {label_name}", expanded=(index == 0)):
            if item.error:
                st.error(item.error)
                continue
            if item.analysis:
                st.markdown(f"**Industry:** {item.analysis.industry}")
                st.markdown(f"**Summary:** {item.analysis.company_summary}")
                pain = item.analysis.pain_points[0] if item.analysis.pain_points else "N/A"
                st.markdown(f"**Key Pain Point:** {pain}")
            if item.draft:
                st.markdown(f"**Email Subject:** {item.draft.subject}")
                st.text_area(
                    "Email Body",
                    value=item.draft.body,
                    height=200,
                    key=f"batch_body_{index}",
                )


def render_outreach_log() -> None:
    """Local log of sends. Opened and replied are checkboxes you set, not pixel events."""
    st.markdown(
        section_header(
            "Outreach Log", "Local history of sends and practice rows", SVG_DOC, "purple"
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Real sends and demo practice rows are listed together. "
        "A DEMO row was not emailed. Opened, replied, and follow-up are marks you set yourself."
    )

    records = get_outreach_log()
    if not records:
        st.info(
            "No outreach attempts logged yet. Send an email, or confirm a demo send, to see it here."
        )
        return

    total = len(records)
    sent = sum(1 for record in records if record.status == "sent")
    demo_sent = sum(1 for record in records if record.status == "demo_sent")
    opened = sum(1 for record in records if record.opened_at)
    replied = sum(1 for record in records if record.replied_at)
    today_str = date.today().isoformat()
    due_follow_ups = sum(
        1
        for record in records
        if record.follow_up_date and record.follow_up_date <= today_str and not record.replied_at
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total", total)
    m2.metric("Sent", sent)
    m3.metric("Opened", opened)
    m4.metric("Replied", replied)
    m5.metric("Due Follow-Ups", due_follow_ups)
    if demo_sent:
        st.caption(f"{demo_sent} practice row(s) from demo mode are not counted as sent.")

    st.markdown("---")
    for idx, record in enumerate(records):
        badge, css_class = _status_badge(record)
        status_html = f'<span class="{css_class}">{badge}</span>'
        fu_label = ""
        if record.follow_up_date and not record.replied_at:
            if record.follow_up_date <= today_str:
                fu_label = " | FOLLOW-UP DUE"
            else:
                fu_label = f" | Follow-up: {record.follow_up_date}"
        expander_label = (
            f"{badge} | {record.prospect_name or record.prospect_url} "
            f"→ {record.recipient_email}{fu_label}"
        )
        with st.expander(expander_label):
            st.markdown(status_html, unsafe_allow_html=True)
            col1, col2, col3 = st.columns(3)
            col1.metric("Status", badge)
            col2.metric("Recipient", record.recipient_email)
            col3.metric("Time", record.timestamp[:19])

            if record.follow_up_date and not record.replied_at:
                if record.follow_up_date <= today_str:
                    days_overdue = (date.today() - date.fromisoformat(record.follow_up_date)).days
                    st.markdown(
                        f'<span class="follow-up-due">FOLLOW-UP OVERDUE by {days_overdue} day(s)</span>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<span class="follow-up-upcoming">Follow-up scheduled: {record.follow_up_date}</span>',
                        unsafe_allow_html=True,
                    )

            st.markdown(f"**Subject:** {record.email_subject}")
            st.text_area(
                "Body",
                value=record.email_body,
                height=150,
                key=f"log_body_{idx}",
                disabled=True,
            )
            if record.error_message:
                st.error(record.error_message)
            if record.notes:
                st.markdown(f"**Notes:** {record.notes}")

            if record.status in {"sent", "demo_sent"}:
                st.markdown("---")
                act_cols = st.columns(4)
                with act_cols[0]:
                    if not record.opened_at:
                        if st.button("Mark as Opened", key=f"open_{idx}"):
                            update_outreach_record(idx, opened_at=datetime.now().isoformat())
                            st.rerun()
                    else:
                        st.caption(f"Opened: {record.opened_at[:19]}")
                with act_cols[1]:
                    if not record.replied_at:
                        if st.button("Mark as Replied", key=f"reply_{idx}"):
                            update_outreach_record(idx, replied_at=datetime.now().isoformat())
                            st.rerun()
                    else:
                        st.caption(f"Replied: {record.replied_at[:19]}")
                with act_cols[2]:
                    if not record.follow_up_date and not record.replied_at:
                        fu_date = st.date_input(
                            "Follow-up date",
                            value=date.today() + timedelta(days=3),
                            key=f"fu_date_{idx}",
                        )
                        if st.button("Set Follow-Up", key=f"fu_set_{idx}"):
                            chosen = fu_date if isinstance(fu_date, date) else date.today()
                            update_outreach_record(idx, follow_up_date=chosen.isoformat())
                            st.rerun()
                with act_cols[3]:
                    new_note = st.text_input(
                        "Add note",
                        key=f"note_input_{idx}",
                        placeholder="e.g. Spoke with the founder",
                    )
                    if st.button("Save Note", key=f"note_save_{idx}") and new_note:
                        existing = record.notes or ""
                        combined = f"{existing}\n{new_note}".strip() if existing else new_note
                        update_outreach_record(idx, notes=combined)
                        st.rerun()


def render_follow_up_dashboard() -> None:
    """Dates you set yourself. There is no mail-server clock behind this list."""
    st.markdown(
        section_header(
            "Follow-Up Dashboard",
            "Upcoming and overdue follow-ups",
            SVG_CALENDAR,
            "orange",
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Dates you saved on a send. Overdue items appear first. "
        "Snooze and mark replied change the local log only."
    )

    records = get_outreach_log()
    today = date.today()
    today_str = today.isoformat()
    follow_ups = [
        (idx, record)
        for idx, record in enumerate(records)
        if record.follow_up_date and not record.replied_at
    ]
    if not follow_ups:
        st.info(
            "No follow-ups scheduled. Send an email, or confirm a demo send, "
            "and set a follow-up date from the Outreach Log tab."
        )
        return

    horizon = (today + timedelta(days=7)).isoformat()
    overdue = [(idx, record) for idx, record in follow_ups if _follow_up_day(record) <= today_str]
    upcoming = [
        (idx, record) for idx, record in follow_ups if today_str < _follow_up_day(record) <= horizon
    ]
    later = [(idx, record) for idx, record in follow_ups if _follow_up_day(record) > horizon]

    if overdue:
        st.markdown(f"### Overdue ({len(overdue)})")
        for idx, record in overdue:
            assert record.follow_up_date is not None
            days_overdue = (today - date.fromisoformat(record.follow_up_date)).days
            with st.expander(
                f"OVERDUE ({days_overdue}d) | {record.prospect_name or record.prospect_url} "
                f"→ {record.recipient_email}"
            ):
                st.markdown(
                    f'<span class="follow-up-due">OVERDUE by {days_overdue} day(s)</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**Subject:** {record.email_subject}")
                if record.notes:
                    st.markdown(f"**Notes:** {record.notes}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Mark as Replied", key=f"fu_reply_{idx}"):
                        update_outreach_record(idx, replied_at=datetime.now().isoformat())
                        st.rerun()
                with c2:
                    snooze_days = st.selectbox(
                        "Snooze",
                        options=[1, 2, 3, 5, 7],
                        index=0,
                        key=f"snooze_sel_{idx}",
                    )
                    if st.button("Snooze", key=f"snooze_{idx}"):
                        days = snooze_days if isinstance(snooze_days, int) else 1
                        new_date = (today + timedelta(days=days)).isoformat()
                        update_outreach_record(idx, follow_up_date=new_date)
                        st.rerun()

    if upcoming:
        st.markdown(f"### Upcoming — Next 7 Days ({len(upcoming)})")
        for idx, record in upcoming:
            assert record.follow_up_date is not None
            days_until = (date.fromisoformat(record.follow_up_date) - today).days
            with st.expander(
                f"In {days_until}d ({record.follow_up_date}) | "
                f"{record.prospect_name or record.prospect_url} → {record.recipient_email}"
            ):
                st.markdown(
                    f'<span class="follow-up-upcoming">Follow-up in {days_until} day(s)</span>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**Subject:** {record.email_subject}")
                if record.notes:
                    st.markdown(f"**Notes:** {record.notes}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Mark as Replied", key=f"fu_reply_{idx}"):
                        update_outreach_record(idx, replied_at=datetime.now().isoformat())
                        st.rerun()
                with c2:
                    snooze_days = st.selectbox(
                        "Snooze",
                        options=[1, 2, 3, 5, 7],
                        index=0,
                        key=f"snooze_sel_{idx}",
                    )
                    if st.button("Snooze", key=f"snooze_{idx}"):
                        days = snooze_days if isinstance(snooze_days, int) else 1
                        new_date = (
                            date.fromisoformat(record.follow_up_date) + timedelta(days=days)
                        ).isoformat()
                        update_outreach_record(idx, follow_up_date=new_date)
                        st.rerun()

    if later:
        st.markdown(f"### Later ({len(later)})")
        for _idx, record in later:
            assert record.follow_up_date is not None
            days_until = (date.fromisoformat(record.follow_up_date) - today).days
            st.markdown(
                f"- **{record.follow_up_date}** ({days_until}d) — "
                f"{record.prospect_name or record.prospect_url} → {record.recipient_email}"
            )


def main() -> None:
    """Draw the review desk. Logging is configured once per process."""
    global _logging_ready
    if not _logging_ready:
        configure_logging()
        _logging_ready = True

    init_session_state()
    render_sidebar()

    st.markdown(
        '<div class="branded-header">'
        '<div class="brand-logo-mark">A</div>'
        "<div>"
        '<p class="brand-title">AI Outreach</p>'
        '<p class="brand-subtitle">Personal project. Runs on your machine. Nothing sends until you confirm.</p>'
        "</div>"
        "</div>"
        '<div class="accent-divider"></div>',
        unsafe_allow_html=True,
    )

    if _state_bool("demo_mode"):
        st.markdown(
            '<div class="demo-banner"><strong>Demo mode.</strong> '
            "Sample pages and a saved draft. No API key, no network, and no email leaves this machine. "
            "Turn off Demo mode in the sidebar to read a live site.</div>",
            unsafe_allow_html=True,
        )
    elif anthropic_key_is_unset(_state_str("api_key")):
        st.warning(ANTHROPIC_KEY_MESSAGE)

    with st.expander("How It Works — Pipeline Overview", expanded=False):
        st.markdown(
            '<div class="pipeline-steps">'
            '<div class="pipeline-step-item"><span class="step-num">STEP 1</span>Web Scraping</div>'
            '<div class="pipeline-step-item"><span class="step-num">STEP 2</span>Need Analysis</div>'
            '<div class="pipeline-step-item"><span class="step-num">STEP 3</span>Email Drafting</div>'
            '<div class="pipeline-step-item"><span class="step-num">STEP 4</span>Review &amp; Send</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown("""
**This tool runs a 4-step pipeline for each prospect:**

| Step | What Happens |
|------|-------------|
| **1. Web Scraping** | Fetches the prospect's website (homepage plus a few pages such as About, Services, and Contact) and extracts text. Demo mode loads saved pages instead. |
| **2. Need Analysis** | Claude returns industry, pain points, and places where data or operations work could help. Demo mode loads saved notes. |
| **3. Email Drafting** | Claude writes one email that references the pages. Demo mode loads a saved draft for the tone you picked. |
| **4. Review & Send** | You edit the draft and confirm. Nothing is mailed until then. Demo mode records the confirm locally and does not email. |

Gmail is only used on a live confirm. Batch mode never sends.
            """)

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Single Outreach", "Batch Mode", "Outreach Log", "Follow-Ups"]
    )
    with tab1:
        render_single_mode()
    with tab2:
        render_batch_mode()
    with tab3:
        render_outreach_log()
    with tab4:
        render_follow_up_dashboard()


if __name__ == "__main__":
    main()
