# ADR 0004: Identify the scraper and honor robots.txt

- Status: Accepted
- Date: 2026-11

## Context

The scraper used a Chrome user-agent so simple bot filters would still return HTML. That got more text back and it misrepresented the client. It also fetched any URL a person pasted, including loopback and link-local addresses, and it did not read `robots.txt`.

This is one person reading a few public pages to draft an email they will review. It is not a crawler, and it should not pretend to be a browser.

## Decision

The User-Agent is `AIOutreach/1.0`, with a link to this repo. Playwright, when it runs, sends the same string.

`robots.txt` is fetched first. A disallow on the homepage returns an empty result and a note, and the page is not fetched. A disallow on a later path skips that path. Crawl-delay is honored and capped at 10 seconds so a huge value cannot stall a run. A missing or unreadable `robots.txt` does not block the scrape. The log says so.

Before any request, the URL has to be http or https, with no username or password, and the host cannot be a literal private, loopback, or link-local address, or a name like `localhost`. Redirects are followed only when they stay on the same public host. A redirect to another host or to a private address is dropped.

## Consequences

Some sites will return less text, or nothing. That is the tradeoff. The page cap and the pause between requests stay.

A public hostname that later resolves to a private address is not detected. DNS is not consulted at the policy check, so the tests stay offline. Login walls and JavaScript-only pages are still fragile. Playwright remains optional.

Demo mode does not fetch, so this policy does not apply to the saved samples.
