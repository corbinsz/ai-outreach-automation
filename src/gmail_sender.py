"""Send one message through the operator's own Gmail account.

SMTP with an app password is enough for a single person and a short list.
It is the wrong design for a shared inbox: there is no per-user OAuth, and
a revoked password fails the same way as a typo. The UI is what asks for
confirmation. This function sends when it is called.

Demo mode does not call this module's send function. It writes a practice
row through ``_log_outreach`` instead.
"""

import json
import logging
import smtplib
import uuid
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.config import GMAIL_MISSING_MESSAGE, gmail_is_unset
from src.models import EmailDraft, OutreachRecord, resolve_sender_name

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
MAX_RETRIES = 3
LOG_DIR = Path("logs")
# Well under the Gmail help-page figure of 500 messages a day. This counts
# rows on this machine with status "sent" and today's local date. It does
# not ask Gmail how many messages the account has already sent, and demo
# practice rows do not count. See docs/adr/0005-daily-send-cap.md.
DAILY_SEND_CAP = 20

RECIPIENT_MESSAGE = (
    "The recipient must be one email address on a single line. "
    "Nothing was sent. The app will not mail a blank address, a list of "
    "addresses, or a value that contains a line break."
)


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(exist_ok=True)


def _log_path() -> Path:
    return LOG_DIR / "outreach_log.json"


def _read_raw_records() -> list[dict[str, Any]]:
    """Return the log as dicts. A missing or unreadable file is an empty list."""
    log_file = _log_path()
    if not log_file.exists():
        return []
    try:
        data = json.loads(log_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _write_raw_records(records: list[dict[str, Any]]) -> None:
    """Replace the log file. The temp file keeps a crash from leaving a half write."""
    _ensure_log_dir()
    log_file = _log_path()
    temporary = log_file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(records, indent=2), encoding="utf-8")
    temporary.replace(log_file)


def _log_outreach(record: OutreachRecord) -> None:
    """Append one row to a JSON file.

    A file is easier to inspect than a database for a personal tool. Two
    processes can still overwrite each other. This app assumes one local user.
    """
    records = _read_raw_records()
    records.append(record.model_dump())
    _write_raw_records(records)
    logger.info("Outreach logged: %s -> %s", record.status, record.recipient_email)


def get_outreach_log() -> list[OutreachRecord]:
    """Read outreach records from the log file.

    A row that fails validation is skipped so one bad line does not hide the
    rest. A row that has no id is given one and, when every row is readable,
    the id is written back so later edits can find it.
    """
    raw = _read_raw_records()
    records: list[OutreachRecord] = []
    changed = False
    skipped = 0
    for row in raw:
        stored = dict(row)
        if not isinstance(stored.get("id"), str) or not stored["id"].strip():
            stored["id"] = str(uuid.uuid4())
            changed = True
        try:
            records.append(OutreachRecord.model_validate(stored))
        except ValidationError:
            skipped += 1
    if skipped:
        logger.warning("Skipped %s outreach log row(s) that failed validation.", skipped)
    elif changed:
        _write_raw_records([record.model_dump() for record in records])
    return records


def sends_today(day: str | None = None) -> int:
    """Count real sends logged on this machine for a local calendar day.

    ``day`` is ``YYYY-MM-DD``. The default is today. Failed rows and demo
    practice rows are not counted.
    """
    prefix = day or datetime.now().date().isoformat()
    return sum(
        1
        for record in get_outreach_log()
        if record.status == "sent" and record.timestamp.startswith(prefix)
    )


def daily_cap_message(used: int) -> str:
    """Explain a refused send. The count is from the local log, not from Gmail."""
    return (
        f"Daily send cap is {DAILY_SEND_CAP} real emails. "
        f"{used} are already logged today on this machine. Nothing was sent. "
        "Demo practice rows do not count. The cap is local and does not ask Gmail."
    )


def _validate_updates(fields: dict[str, object]) -> None:
    valid_fields = set(OutreachRecord.model_fields.keys())
    for key in fields:
        if key not in valid_fields:
            raise ValueError(f"Invalid field '{key}' — valid fields: {sorted(valid_fields)}")


def update_outreach_record(index: int, **fields: object) -> OutreachRecord:
    """Update one log row by position.

    The index is the position in the file, not a stable id. The send screen
    should prefer ``update_outreach_record_by_id``. Unknown field names are
    rejected. The file is left untouched when the new row would not validate.
    """
    records = _read_raw_records()
    if index < 0 or index >= len(records):
        raise IndexError(f"Record index {index} out of range (0-{len(records) - 1})")

    _validate_updates(fields)
    updated = dict(records[index])
    updated.update(fields)
    # Validate before writing so a bad value cannot land in the file.
    validated = OutreachRecord.model_validate(updated)
    records[index] = validated.model_dump()
    _write_raw_records(records)
    logger.info("Updated record %s: %s", index, list(fields.keys()))
    return validated


def update_outreach_record_by_id(record_id: str, **fields: object) -> OutreachRecord:
    """Update the row with this id.

    Follow-up edits use the id captured when the row was written. Updating
    "the last row" targets the wrong prospect if another send was appended.
    """
    records = _read_raw_records()
    for index, row in enumerate(records):
        if row.get("id") == record_id:
            return update_outreach_record(index, **fields)
    raise KeyError(f"No outreach record with id {record_id}")


def _single_line(value: str) -> str:
    """Collapse characters that would break an email header into a new header."""
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def _recipient_is_one_address(value: str) -> bool:
    cleaned = value.strip()
    if not cleaned or any(character.isspace() for character in cleaned):
        return False
    if "," in cleaned or cleaned.count("@") != 1:
        return False
    local, domain = cleaned.split("@", 1)
    return bool(local) and "." in domain and "\n" not in value and "\r" not in value


def _fail(record: OutreachRecord, message: str) -> OutreachRecord:
    record.status = "failed"
    record.error_message = message
    record.timestamp = datetime.now().isoformat()
    _log_outreach(record)
    logger.error(message)
    return record


def send_email(
    draft: EmailDraft,
    to_address: str,
    gmail_address: str,
    gmail_app_password: str,
    sender_name: str | None = None,
    prospect_url: str = "",
    prospect_name: str = "",
) -> OutreachRecord:
    """Send the draft and append a log row for both success and failure.

    Auth errors and rejected recipients are permanent, so they are not
    retried. Other SMTP errors are tried up to MAX_RETRIES times, with no
    delay between tries. Missing Gmail settings and a recipient that is not
    one address return a failed row without opening a connection.
    """
    sender_name = resolve_sender_name(sender_name)
    safe_subject = _single_line(draft.subject)
    safe_sender = _single_line(sender_name)
    record = OutreachRecord(
        prospect_url=prospect_url,
        prospect_name=prospect_name,
        recipient_email=to_address.strip(),
        email_subject=safe_subject,
        email_body=draft.body,
        status="pending",
        prompt_version=draft.prompt_version,
    )

    if not _recipient_is_one_address(to_address):
        return _fail(record, RECIPIENT_MESSAGE)

    if gmail_is_unset(gmail_address, gmail_app_password):
        return _fail(record, GMAIL_MISSING_MESSAGE)

    used = sends_today()
    if used >= DAILY_SEND_CAP:
        return _fail(record, daily_cap_message(used))

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{safe_sender} <{gmail_address.strip()}>"
    msg["To"] = to_address.strip()
    msg["Subject"] = safe_subject
    msg.attach(MIMEText(draft.body, "plain"))

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("Send attempt %s/%s to %s", attempt, MAX_RETRIES, to_address)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(gmail_address.strip(), gmail_app_password)
                server.send_message(msg)

            record.status = "sent"
            record.timestamp = datetime.now().isoformat()
            logger.info("Email sent successfully to %s", to_address)
            _log_outreach(record)
            return record

        except smtplib.SMTPAuthenticationError as exc:
            last_error = f"Authentication failed: {exc}. Check your Gmail address and App Password."
            logger.error(last_error)
            break
        except smtplib.SMTPRecipientsRefused as exc:
            last_error = f"Recipient refused: {exc}"
            logger.error(last_error)
            break
        except (smtplib.SMTPException, OSError) as exc:
            last_error = f"SMTP error (attempt {attempt}): {exc}"
            logger.warning(last_error)
            if attempt == MAX_RETRIES:
                break

    record.status = "failed"
    record.error_message = last_error
    record.timestamp = datetime.now().isoformat()
    _log_outreach(record)
    return record
