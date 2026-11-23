"""Tests for the Gmail sending module."""

import json
import smtplib
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from src.gmail_sender import (
    DAILY_SEND_CAP,
    _log_outreach,
    get_outreach_log,
    send_email,
    sends_today,
    update_outreach_record,
    update_outreach_record_by_id,
)
from src.models import EmailDraft, OutreachRecord


def _make_draft() -> EmailDraft:
    return EmailDraft(subject="Test Subject", body="Test body content", tone="professional")


class TestSendEmail:
    @pytest.fixture(autouse=True)
    def _isolated_log(self, monkeypatch, tmp_path):
        """Keep the daily cap from reading a developer's real outreach log."""
        monkeypatch.setattr("src.gmail_sender.LOG_DIR", tmp_path)

    @patch("src.gmail_sender._log_outreach")
    @patch("src.gmail_sender.smtplib.SMTP")
    def test_successful_send(self, mock_smtp_cls, mock_log):
        server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email(
            draft=_make_draft(),
            to_address="recipient@example.com",
            gmail_address="sender@gmail.com",
            gmail_app_password="abcdefghijklmnop",
            sender_name="Test Sender",
            prospect_url="https://example.com",
            prospect_name="Example",
        )

        assert result.status == "sent"
        assert result.recipient_email == "recipient@example.com"
        assert result.email_subject == "Test Subject"
        mock_log.assert_called_once()

    @patch("src.gmail_sender._log_outreach")
    @patch("src.gmail_sender.smtplib.SMTP")
    def test_sender_name_from_env(self, mock_smtp_cls, mock_log, monkeypatch):
        monkeypatch.setenv("SENDER_NAME", "Casey Lee")
        server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        send_email(
            draft=_make_draft(),
            to_address="recipient@example.com",
            gmail_address="sender@gmail.com",
            gmail_app_password="abcdefghijklmnop",
        )

        sent = server.send_message.call_args[0][0]
        assert sent["From"] == "Casey Lee <sender@gmail.com>"

    @patch("src.gmail_sender._log_outreach")
    @patch("src.gmail_sender.smtplib.SMTP")
    def test_auth_failure_no_retry(self, mock_smtp_cls, mock_log):
        server = MagicMock()
        server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email(
            draft=_make_draft(),
            to_address="recipient@example.com",
            gmail_address="sender@gmail.com",
            gmail_app_password="wrongpassword",
        )

        assert result.status == "failed"
        assert "Authentication" in result.error_message
        # Auth failures should NOT retry — only 1 SMTP connection
        assert mock_smtp_cls.call_count == 1

    @patch("src.gmail_sender._log_outreach")
    @patch("src.gmail_sender.smtplib.SMTP")
    def test_recipient_refused_no_retry(self, mock_smtp_cls, mock_log):
        server = MagicMock()
        server.send_message.side_effect = smtplib.SMTPRecipientsRefused(
            {"bad@x.com": (550, b"No such user")}
        )
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email(
            draft=_make_draft(),
            to_address="bad@x.com",
            gmail_address="sender@gmail.com",
            gmail_app_password="abcdefghijklmnop",
        )

        assert result.status == "failed"
        assert "refused" in result.error_message.lower()
        assert mock_smtp_cls.call_count == 1

    @patch("src.gmail_sender._log_outreach")
    @patch("src.gmail_sender.smtplib.SMTP")
    def test_transient_error_retries(self, mock_smtp_cls, mock_log):
        server = MagicMock()
        server.send_message.side_effect = [
            smtplib.SMTPException("Temporary failure"),
            smtplib.SMTPException("Temporary failure"),
            None,  # succeeds on 3rd try
        ]
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email(
            draft=_make_draft(),
            to_address="recipient@example.com",
            gmail_address="sender@gmail.com",
            gmail_app_password="abcdefghijklmnop",
        )

        assert result.status == "sent"
        assert mock_smtp_cls.call_count == 3  # retried

    @patch("src.gmail_sender._log_outreach")
    @patch("src.gmail_sender.smtplib.SMTP")
    def test_missing_gmail_does_not_open_a_connection(self, mock_smtp_cls, mock_log):
        result = send_email(
            draft=_make_draft(),
            to_address="recipient@example.com",
            gmail_address="",
            gmail_app_password="",
        )

        assert result.status == "failed"
        assert result.error_message is not None
        assert "GMAIL_ADDRESS" in result.error_message
        mock_smtp_cls.assert_not_called()
        mock_log.assert_called_once()

    @patch("src.gmail_sender._log_outreach")
    @patch("src.gmail_sender.smtplib.SMTP")
    def test_placeholder_gmail_does_not_open_a_connection(self, mock_smtp_cls, mock_log):
        result = send_email(
            draft=_make_draft(),
            to_address="recipient@example.com",
            gmail_address="you@gmail.com",
            gmail_app_password="your-16-character-app-password",
        )

        assert result.status == "failed"
        assert result.error_message is not None
        assert "not credentials" in result.error_message
        mock_smtp_cls.assert_not_called()

    @patch("src.gmail_sender._log_outreach")
    @patch("src.gmail_sender.smtplib.SMTP")
    def test_subject_newline_stays_in_one_header(self, mock_smtp_cls, mock_log):
        server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=server)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = send_email(
            draft=EmailDraft(subject="Hello\nBcc: evil@example.com", body="Body"),
            to_address="recipient@example.com",
            gmail_address="sender@gmail.com",
            gmail_app_password="abcdefghijklmnop",
        )

        assert result.status == "sent"
        sent = server.send_message.call_args[0][0]
        assert "\n" not in sent["Subject"]
        assert sent["Bcc"] is None
        assert "Hello" in sent["Subject"]

    @patch("src.gmail_sender._log_outreach")
    @patch("src.gmail_sender.smtplib.SMTP")
    @pytest.mark.parametrize(
        "recipient",
        ["", "not-an-email", "a@b.com, c@d.com", "a@b.com\nBcc: evil@example.com"],
    )
    def test_bad_recipient_does_not_open_a_connection(self, mock_smtp_cls, mock_log, recipient):
        result = send_email(
            draft=_make_draft(),
            to_address=recipient,
            gmail_address="sender@gmail.com",
            gmail_app_password="abcdefghijklmnop",
        )

        assert result.status == "failed"
        assert result.error_message is not None
        assert "one email address" in result.error_message
        mock_smtp_cls.assert_not_called()


class TestOutreachLog:
    def test_log_and_read(self, tmp_path):
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            record = OutreachRecord(
                prospect_url="https://example.com",
                prospect_name="Example",
                recipient_email="test@example.com",
                email_subject="Hi",
                email_body="Hello",
                status="sent",
            )
            _log_outreach(record)

            records = get_outreach_log()

        assert len(records) == 1
        assert records[0].status == "sent"
        assert records[0].prospect_name == "Example"

    def test_empty_log_returns_empty(self, tmp_path):
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            records = get_outreach_log()
        assert records == []

    def test_corrupt_log_returns_empty(self, tmp_path):
        log_file = tmp_path / "outreach_log.json"
        log_file.write_text("not valid json{{{")

        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            records = get_outreach_log()
        assert records == []


def _seed_log(tmp_path, count=2):
    """Helper: create a log file with `count` records, return records list."""
    records = []
    for i in range(count):
        records.append(
            OutreachRecord(
                prospect_url=f"https://example{i}.com",
                prospect_name=f"Company {i}",
                recipient_email=f"contact{i}@example.com",
                email_subject=f"Subject {i}",
                email_body=f"Body {i}",
                status="sent",
            ).model_dump()
        )
    log_file = tmp_path / "outreach_log.json"
    log_file.write_text(json.dumps(records, indent=2))
    return records


class TestUpdateOutreachRecord:
    def test_update_single_field(self, tmp_path):
        _seed_log(tmp_path)
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            updated = update_outreach_record(0, opened_at="2025-01-15T10:30:00")
        assert updated.opened_at == "2025-01-15T10:30:00"
        assert updated.prospect_name == "Company 0"

    def test_update_multiple_fields(self, tmp_path):
        _seed_log(tmp_path)
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            updated = update_outreach_record(
                1,
                follow_up_date="2025-01-20",
                notes="Call scheduled",
            )
        assert updated.follow_up_date == "2025-01-20"
        assert updated.notes == "Call scheduled"

    def test_index_out_of_range(self, tmp_path):
        _seed_log(tmp_path, count=2)
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            with pytest.raises(IndexError):
                update_outreach_record(5, opened_at="2025-01-15T10:30:00")

    def test_invalid_field_name(self, tmp_path):
        _seed_log(tmp_path)
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            with pytest.raises(ValueError, match="Invalid field"):
                update_outreach_record(0, nonexistent_field="value")

    def test_preserves_other_records(self, tmp_path):
        _seed_log(tmp_path, count=3)
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            update_outreach_record(1, notes="Updated")
            records = get_outreach_log()
        assert len(records) == 3
        assert records[0].notes is None
        assert records[1].notes == "Updated"
        assert records[2].notes is None

    def test_invalid_value_does_not_rewrite_the_file(self, tmp_path):
        _seed_log(tmp_path)
        original = (tmp_path / "outreach_log.json").read_text(encoding="utf-8")
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            with pytest.raises(ValidationError):
                update_outreach_record(0, email_body={"not": "text"})
        assert (tmp_path / "outreach_log.json").read_text(encoding="utf-8") == original

    def test_update_by_id_does_not_touch_a_later_row(self, tmp_path):
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            first = OutreachRecord(
                prospect_url="https://first.example",
                prospect_name="First",
                recipient_email="first@example.com",
                email_subject="Hello first",
                email_body="Body",
                status="sent",
            )
            second = OutreachRecord(
                prospect_url="https://second.example",
                prospect_name="Second",
                recipient_email="second@example.com",
                email_subject="Hello second",
                email_body="Body",
                status="sent",
            )
            _log_outreach(first)
            _log_outreach(second)
            update_outreach_record_by_id(first.id, notes="follow up with the first company")
            rows = get_outreach_log()

        assert rows[0].id == first.id
        assert rows[0].notes == "follow up with the first company"
        assert rows[1].id == second.id
        assert rows[1].notes is None

    def test_unknown_id_does_not_update_the_last_row(self, tmp_path):
        _seed_log(tmp_path, count=2)
        original = (tmp_path / "outreach_log.json").read_text(encoding="utf-8")
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            with pytest.raises(KeyError):
                update_outreach_record_by_id("missing-id", notes="should not land")
        assert (tmp_path / "outreach_log.json").read_text(encoding="utf-8") == original


def _sent_row(index: int, *, status: str = "sent", when: str | None = None) -> dict[str, object]:
    record = OutreachRecord(
        prospect_url=f"https://example{index}.com",
        prospect_name=f"Company {index}",
        recipient_email=f"person{index}@example.com",
        email_subject="Hello",
        email_body="Body",
        status=status,
        timestamp=when or datetime.now().isoformat(),
        prompt_version="2026.11.1",
    )
    return record.model_dump()


class TestDailyCap:
    def test_cap_refuses_without_opening_smtp(self, tmp_path):
        rows = [_sent_row(index) for index in range(DAILY_SEND_CAP)]
        (tmp_path / "outreach_log.json").write_text(json.dumps(rows), encoding="utf-8")
        with (
            patch("src.gmail_sender.LOG_DIR", tmp_path),
            patch("src.gmail_sender.smtplib.SMTP") as mock_smtp,
        ):
            result = send_email(
                draft=_make_draft(),
                to_address="recipient@example.com",
                gmail_address="sender@gmail.com",
                gmail_app_password="abcdefghijklmnop",
            )
        assert result.status == "failed"
        assert result.error_message is not None
        assert "Daily send cap" in result.error_message
        mock_smtp.assert_not_called()
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            assert sends_today() == DAILY_SEND_CAP

    def test_demo_rows_and_yesterday_do_not_count(self, tmp_path):
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        rows = [_sent_row(index, status="demo_sent") for index in range(DAILY_SEND_CAP)]
        rows.append(_sent_row(100, when=yesterday))
        (tmp_path / "outreach_log.json").write_text(json.dumps(rows), encoding="utf-8")
        with (
            patch("src.gmail_sender.LOG_DIR", tmp_path),
            patch("src.gmail_sender.smtplib.SMTP") as mock_smtp,
        ):
            server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = server
            mock_smtp.return_value.__exit__.return_value = False
            result = send_email(
                draft=EmailDraft(subject="Hi", body="Hello", prompt_version="2026.11.1"),
                to_address="recipient@example.com",
                gmail_address="sender@gmail.com",
                gmail_app_password="abcdefghijklmnop",
            )
        assert result.status == "sent"
        assert result.prompt_version == "2026.11.1"
        server.send_message.assert_called_once()

    def test_a_bad_row_does_not_hide_the_rest_of_the_log(self, tmp_path):
        good = _sent_row(1)
        (tmp_path / "outreach_log.json").write_text(
            json.dumps([good, {"prospect_url": "https://broken.example"}]),
            encoding="utf-8",
        )
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            records = get_outreach_log()
        assert len(records) == 1
        assert records[0].prospect_name == "Company 1"
        stored = json.loads((tmp_path / "outreach_log.json").read_text(encoding="utf-8"))
        assert len(stored) == 2

    def test_a_missing_id_is_written_back_once(self, tmp_path):
        row = _sent_row(1)
        row.pop("id")
        (tmp_path / "outreach_log.json").write_text(json.dumps([row]), encoding="utf-8")
        with patch("src.gmail_sender.LOG_DIR", tmp_path):
            first = get_outreach_log()
            second = get_outreach_log()
        assert first[0].id
        assert second[0].id == first[0].id
        stored = json.loads((tmp_path / "outreach_log.json").read_text(encoding="utf-8"))
        assert stored[0]["id"] == first[0].id
