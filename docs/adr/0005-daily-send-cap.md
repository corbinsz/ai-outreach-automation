# ADR 0005: Cap real sends at 20 a day

- Status: Accepted
- Date: 2026-11

## Context

Gmail's help page describes a block after more than 500 messages in a day, or one message to more than 500 people. That number is Google's, it can change, and looking like a blast can limit an account sooner. This app had no cap of its own. A person confirming one email at a time can still click through more mail than they meant to send.

The operator is one person. The log already records every real send.

## Decision

`send_email` refuses to open SMTP once 20 rows with status `sent` are logged for the local calendar day. The refusal is written to the log as a failed row, with the reason. Demo practice rows and failed rows do not count. The review screen shows the count and disables Confirm when the cap is reached. The server-side check remains, so a caller that skips the screen still cannot send past the cap.

The cap does not ask Gmail how many messages the account has already sent. It counts this machine's log.

## Consequences

Twenty is a choice, well under the published Gmail figure, and it is a constant in `src/gmail_sender.py`. It is not a compliance limit and it is not a deliverability system. Mail sent from another client the same day is invisible to the cap. Two processes can still race on the JSON file.

OAuth is still the wrong next step while only one person sends. The cap is not a reason to add unsupervised sending.
