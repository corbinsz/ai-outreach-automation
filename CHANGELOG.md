# Changelog

This project is not published as a package. The log records changes that matter to someone running it locally. There are no usage numbers, because there is no launched product.

## Unreleased

### Added

- Research notes separate a quote copied from the page from a labeled inference. The review screen shows both, and `make eval` checks that the saved quotes are on the saved pages.
- Prompt version `2026.11.1` in `src/prompts.py`. Live notes and drafts record it. Saved samples are marked `saved-demo`. See `docs/PROMPT.md`.
- A draft checklist on the review screen. It compares the draft to the page text. It does not block Confirm, and it does not send.
- Confirm requires a checkbox that the draft was read, then the Confirm button, then one address. The pipeline still stops at a draft.
- The scraper identifies itself as `AIOutreach/1.0`, skips paths `robots.txt` disallows, caps Crawl-delay at 10 seconds, and refuses private, loopback, and non-web addresses before a request. Redirects that leave the host are dropped.
- A local cap of 20 real sends per day, counted from the log. Practice rows do not count. The cap refuses the send and does not open SMTP.
- GitHub Actions runs `make eval` after the test suite.
- `make demo` is the quickstart. The first run creates the virtualenv, then opens the app. No API key.
- Hostnames are resolved before a fetch. A private, loopback, or link-local answer is refused. The tests stub DNS.
- The two professional sample drafts name the company, so the demo checklist passes.
- `make eval`: an offline rubric for saved drafts (fact citation, length, banned phrases, invented digits, company name, clear ask) on the demo drafts and 12 fictional company pages. The measured table is in `docs/PRODUCT.md`. The confirm-gate count is from the test-suite scenarios, not from users.
- Demo mode: two saved companies, saved notes, and saved drafts. `make demo` runs the full review flow with no API key and no network. A practice confirm is stored locally and is not emailed.
- `make setup` for a virtualenv, dev tools, and a `.env` copied from the example file.
- Dockerfile and docker-compose for running that demo on your own machine. Nothing in this repo is deployed.
- mypy, pre-commit, a coverage report in CI, MIT license, contributing guide, issue templates, product write-up, and short architecture decision records.

### Fixed

- One unreadable log row no longer hides the rest of the log. A row saved without an id gets one the next time the log is read, and the log screen edits by that id.
- A page with no Content-Type is still read when the body is HTML. A very large response is cut before it is parsed.
- A missing or placeholder Anthropic key or Gmail setting fails with setup instructions and does not open a client or an SMTP connection.
- The follow-up button after a send updates that send's id, not whatever row is last in the log. An invalid update no longer rewrites the file.
- A subject or sender name with a line break cannot become a second email header. A recipient that is blank, a list, or split across lines is rejected before any connection.
- Links on `www` and the bare host are treated as the same site. A different subdomain is not.
- Regenerating a draft refreshes the subject and body fields. The success animation plays once per real send.
- Live mode no longer puts the first scraped address into the To field.

## Earlier

The first version scraped a site, asked Claude for notes, drafted one email, and sent it from the operator's Gmail only after confirmation. Tests mocked Claude and SMTP. That behavior is what the commits before this log describe.
