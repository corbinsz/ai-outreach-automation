# ADR 0003: Ship an offline demo instead of a hosted app

- Status: Accepted
- Date: 2026-11

## Context

A reviewer, including a recruiter, should be able to click through the product without creating an Anthropic key, a Gmail app password, or an account on a hosted copy. Hosting it would also publish a tool that drafts cold email, which this project is not willing to run as a service.

A mocked UI that only shows a picture would not exercise the edit and confirm steps. The point of the safeguard is that confirm is a real action with a visible result, and that the result is not an email unless the operator meant it.

## Decision

Demo mode is the same pipeline with two differences:

- Pages, notes, and drafts are files under `fixtures/demo`. Two fictional companies, Northwind Analytics and Harbor & Pine Goods, use the reserved `.example` domain.
- Confirm appends a `demo_sent` row to the local log and does not open SMTP or call the model.

`make demo` turns this on. The container defaults to it. A URL that is not one of the samples fails with the sample list, and the failure does not fetch that URL. Live mode is unchanged: it needs an Anthropic key, and a real send needs Gmail.

The saved drafts are checked in tests for length, a banned opener, and a phrase that appears in the saved HTML. That is a guard on the fixtures, not a score of live model output.

## Consequences

Someone can try the product in a minute, and the repo does not need a public URL. The cost is a second source of drafts that can drift from the live prompt. The tests keep the saved drafts specific. They will not notice if the live prompt gets worse.

Demo rows are not counted as sent. A practice confirm must not look like a campaign result. There are still no usage numbers, because demo runs on a laptop are not users.
