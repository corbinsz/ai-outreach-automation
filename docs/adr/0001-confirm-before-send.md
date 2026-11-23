# ADR 0001: Send only after an explicit confirm

- Status: Accepted
- Date: 2026-02

## Context

The useful part of this tool is the draft. The harmful part is mail the operator did not read. Cold email already has spam, legal, and "this person did not ask" problems. An automatic send would make those the default.

The operator is one person with a short list. A sequence tool that sends on a timer solves a different job, for a team I am not building for.

## Decision

The pipeline stops at a draft. The Streamlit screen shows a quality checklist, then sends only after a checkbox that the draft was read and Confirm, to one address. The checklist does not block Confirm. A local daily cap can refuse the send. That cap is [ADR 0005](0005-daily-send-cap.md). Batch mode never calls send. There is no scheduler. `auto_send` exists on the agent for a scripted caller and the screen does not set it.

Demo mode keeps the same button, and the button writes a local log row instead of opening SMTP. That is [ADR 0003](0003-offline-demo-mode.md).

## Consequences

A person can close the tab and nothing goes out. The cost is an extra click, and a list of URLs cannot be "finished" by the app. That cost is the product.

Confirm is not a legal review. It does not add an unsubscribe link, and it does not know whether the recipient wants the mail. It only makes sure a person saw the draft and chose one address.

The screen and the agent used to reach the draft through two different call paths. The screen now calls `run_pipeline` and `run_batch`, so a change to the stop-at-draft rule is in one place.
