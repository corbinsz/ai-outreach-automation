# Changelog

This project is not published as a package. The log records changes that matter to someone running it locally. There are no usage numbers, because there is no launched product.

## Unreleased

### Added

- Demo mode: two saved companies, saved notes, and saved drafts. `make demo` runs the full review flow with no API key and no network. A practice confirm is stored locally and is not emailed.
- `make setup` for a virtualenv, dev tools, and a `.env` copied from the example file.
- Dockerfile and docker-compose for running that demo on your own machine. Nothing in this repo is deployed.
- mypy, pre-commit, a coverage report in CI, MIT license, contributing guide, issue templates, product write-up, and short architecture decision records.

### Fixed

- A missing or placeholder Anthropic key or Gmail setting fails with setup instructions and does not open a client or an SMTP connection.
- The follow-up button after a send updates that send's id, not whatever row is last in the log. An invalid update no longer rewrites the file.
- A subject or sender name with a line break cannot become a second email header. A recipient that is blank, a list, or split across lines is rejected before any connection.
- Links on `www` and the bare host are treated as the same site. A different subdomain is not.
- Regenerating a draft refreshes the subject and body fields. The success animation plays once per real send.
- Live mode no longer puts the first scraped address into the To field.

## Earlier

The first version scraped a site, asked Claude for notes, drafted one email, and sent it from the operator's Gmail only after confirmation. Tests mocked Claude and SMTP. That behavior is what the commits before this log describe.
