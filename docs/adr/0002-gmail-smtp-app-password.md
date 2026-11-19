# ADR 0002: Send through the operator's Gmail with an app password

- Status: Accepted
- Date: 2026-02

## Context

The mail has to come from a real inbox the operator already has. A new sending domain, warmup, and OAuth consent screen are the right design for a product other people log into. They are a lot of setup for a spare-time script with one user.

Gmail lets an SMTP client log in with an app password when 2-Step Verification is on. That password is not the normal login password. Google can disable app passwords. There is no per-user consent screen.

## Decision

Live sends use `smtp.gmail.com` on port 587 with the address and app password the operator types into the sidebar or `.env`. The app does not store those values in the repo. Missing or example values fail with a setup message and do not open a connection.

Authentication failures and rejected recipients are not retried. Other SMTP errors are tried up to three times.

This choice is revoked if anyone besides the operator sends. At that point the app password should be replaced with Gmail OAuth, or the project should stop sending.

## Consequences

One person can send without a Google Cloud project. The cost is real: a revoked app password looks like a typo, a personal Gmail account is a poor bulk sender, and Google's published daily limit is not enforced here. Spam filters will treat unexpected mail as spam.

The log keeps the subject and body on disk, unencrypted, because that is how a single operator inspects what went out. It is the wrong store for someone else's mail.

A recipient must be one address on one line. That blocks an accidental list in the To field. It does not decide whether that one person should hear from you.
