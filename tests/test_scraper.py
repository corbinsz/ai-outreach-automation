"""Tests for the web scraping module."""

import ipaddress
import socket
from unittest.mock import MagicMock, patch
from urllib.robotparser import RobotFileParser

import pytest
from src.scraper import (
    DEFAULT_HEADERS,
    MAX_CONTENT_LENGTH,
    MAX_CRAWL_DELAY,
    RATE_LIMIT_DELAY,
    USER_AGENT,
    _discover_links,
    _extract_company_name,
    _extract_emails,
    _extract_text,
    _extract_title,
    _fetch_page,
    _fetch_robots,
    _pause_seconds,
    classify_public_url,
    resolution_block,
    scrape_website,
)


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hostnames resolve to a public address. Tests that need a private answer replace this."""

    def _public(host: str, port: int | None, *args: object, **kwargs: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr("src.scraper.socket.getaddrinfo", _public)


# --- Sample HTML fixtures ---

SAMPLE_HTML = """
<html>
<head><title>Acme Corp - Building the Future</title>
<meta property="og:site_name" content="Acme Corp"/>
</head>
<body>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<main>
<h1>Welcome to Acme Corp</h1>
<p>We build innovative solutions for modern businesses.</p>
<p>Our team of experts delivers world-class engineering.</p>
</main>
<footer>Copyright 2024</footer>
<script>var x = 1;</script>
</body>
</html>
"""

LINKS_HTML = """
<html><body>
<a href="/about">About Us</a>
<a href="/services">Our Services</a>
<a href="/blog">Blog</a>
<a href="/contact">Contact</a>
<a href="https://external.com/page">External Link</a>
<a href="mailto:info@acme.com">Email</a>
<a href="#section">Anchor</a>
</body></html>
"""


class TestExtractText:
    def test_strips_scripts_and_nav(self):
        text = _extract_text(SAMPLE_HTML)
        assert "var x = 1" not in text
        assert "Copyright 2024" not in text  # footer stripped
        assert "Welcome to Acme Corp" in text

    def test_preserves_content(self):
        text = _extract_text(SAMPLE_HTML)
        assert "innovative solutions" in text
        assert "world-class engineering" in text

    def test_strips_short_lines(self):
        html = "<html><body><p>OK</p><p>A</p><p>This is real content here</p></body></html>"
        text = _extract_text(html)
        # Lines with len <= 2 are removed
        assert "This is real content here" in text

    def test_truncates_long_content(self):
        long_html = f"<html><body><p>{'x' * (MAX_CONTENT_LENGTH + 1000)}</p></body></html>"
        text = _extract_text(long_html)
        assert len(text) <= MAX_CONTENT_LENGTH + 50  # allow for truncation message
        assert "truncated" in text


class TestExtractTitle:
    def test_from_title_tag(self):
        title = _extract_title(SAMPLE_HTML)
        assert title == "Acme Corp - Building the Future"

    def test_fallback_to_h1(self):
        html = "<html><body><h1>My Page</h1></body></html>"
        title = _extract_title(html)
        assert title == "My Page"

    def test_empty_when_nothing(self):
        html = "<html><body><p>Just text</p></body></html>"
        title = _extract_title(html)
        assert title == ""


class TestExtractCompanyName:
    def test_from_og_site_name(self):
        name = _extract_company_name(SAMPLE_HTML, "https://acme.com")
        assert name == "Acme Corp"

    def test_from_title_with_separator(self):
        html = "<html><head><title>BigCo | Enterprise Solutions</title></head></html>"
        name = _extract_company_name(html, "https://bigco.com")
        assert name == "BigCo"

    def test_fallback_to_domain(self):
        html = "<html><body></body></html>"
        name = _extract_company_name(html, "https://www.coolstartup.io")
        assert name == "Coolstartup"


class TestDiscoverLinks:
    def test_finds_internal_links(self):
        links = _discover_links(LINKS_HTML, "https://acme.com")
        urls = [url for url, _ in links]
        assert "https://acme.com/about" in urls
        assert "https://acme.com/services" in urls
        assert "https://acme.com/blog" in urls
        assert "https://acme.com/contact" in urls

    def test_excludes_external(self):
        links = _discover_links(LINKS_HTML, "https://acme.com")
        urls = [url for url, _ in links]
        assert not any("external.com" in u for u in urls)

    def test_excludes_mailto_and_anchors(self):
        links = _discover_links(LINKS_HTML, "https://acme.com")
        urls = [url for url, _ in links]
        assert not any("mailto:" in u for u in urls)
        assert not any(u == "#section" for u in urls)

    def test_assigns_page_types(self):
        links = _discover_links(LINKS_HTML, "https://acme.com")
        types = {url: ptype for url, ptype in links}
        assert types.get("https://acme.com/about") == "about"
        assert types.get("https://acme.com/services") == "services"
        assert types.get("https://acme.com/blog") == "blog"

    def test_www_host_is_the_same_site_and_other_subdomains_are_not(self):
        html = """
        <html><body>
        <a href="https://www.acme.com/about">About Us</a>
        <a href="https://acme.com/services">Services</a>
        <a href="https://blog.acme.com/news">News</a>
        </body></html>
        """
        urls = [url for url, _page_type in _discover_links(html, "https://acme.com")]
        assert "https://www.acme.com/about" in urls
        assert "https://acme.com/services" in urls
        assert not any("blog.acme.com" in url for url in urls)


class TestFetchPage:
    def test_success(self):
        session = MagicMock()
        response = MagicMock()
        response.text = "<html>OK</html>"
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.raise_for_status = MagicMock()
        session.get.return_value = response

        result = _fetch_page("https://example.com", session)
        assert result == "<html>OK</html>"

    def test_non_html_returns_none(self):
        session = MagicMock()
        response = MagicMock()
        response.headers = {"Content-Type": "application/pdf"}
        response.raise_for_status = MagicMock()
        session.get.return_value = response

        result = _fetch_page("https://example.com/file.pdf", session)
        assert result is None

    def test_timeout_returns_none(self):
        import requests

        session = MagicMock()
        session.get.side_effect = requests.exceptions.Timeout("timed out")

        result = _fetch_page("https://slow.com", session)
        assert result is None

    def test_http_error_returns_none(self):
        import requests

        session = MagicMock()
        session.get.side_effect = requests.exceptions.HTTPError("404")

        result = _fetch_page("https://example.com/404", session)
        assert result is None


class TestScrapeWebsite:
    @patch("src.scraper._fetch_page")
    @patch("src.scraper._try_playwright_fetch")
    @patch("src.scraper.time.sleep")
    @patch("src.scraper._fetch_robots", return_value=None)
    def test_basic_scrape(self, _robots, mock_sleep, mock_pw, mock_fetch):
        mock_pw.return_value = None
        mock_fetch.return_value = SAMPLE_HTML

        result = scrape_website("https://acme.com", use_playwright_fallback=False)

        assert result.base_url == "https://acme.com"
        assert result.company_name == "Acme Corp"
        assert len(result.pages) >= 1
        assert result.pages[0].page_type == "homepage"

    @patch("src.scraper._fetch_page")
    @patch("src.scraper.time.sleep")
    @patch("src.scraper._fetch_robots", return_value=None)
    def test_url_normalization(self, _robots, mock_sleep, mock_fetch):
        mock_fetch.return_value = SAMPLE_HTML

        result = scrape_website("acme.com/", use_playwright_fallback=False)
        assert result.base_url == "https://acme.com"

    @patch("src.scraper._fetch_page")
    @patch("src.scraper.time.sleep")
    @patch("src.scraper._fetch_robots", return_value=None)
    def test_empty_when_fetch_fails(self, _robots, mock_sleep, mock_fetch):
        mock_fetch.return_value = None

        result = scrape_website("https://down.com", use_playwright_fallback=False)
        assert result.pages == []

    @patch("src.scraper._fetch_page")
    @patch("src.scraper.time.sleep")
    @patch("src.scraper._fetch_robots", return_value=None)
    def test_progress_callback(self, _robots, mock_sleep, mock_fetch):
        mock_fetch.return_value = SAMPLE_HTML
        messages = []

        scrape_website(
            "https://acme.com",
            use_playwright_fallback=False,
            progress_callback=messages.append,
        )
        assert any("Starting scrape" in m for m in messages)
        assert any("Homepage scraped" in m for m in messages)


class TestExtractEmails:
    def test_finds_mailto_links(self):
        html = """
        <html><body>
        <a href="mailto:sales@acme.com">Email us</a>
        <a href="mailto:support@acme.com?subject=Hello">Support</a>
        <p>Contact us today!</p>
        </body></html>
        """
        emails = _extract_emails(html)
        assert "sales@acme.com" in emails
        assert "support@acme.com" in emails

    def test_finds_text_emails(self):
        html = """
        <html><body>
        <p>Reach out at info@company.org or call us.</p>
        <p>Our CEO is at ceo@company.org</p>
        </body></html>
        """
        emails = _extract_emails(html)
        assert "info@company.org" in emails
        assert "ceo@company.org" in emails

    def test_deduplicates(self):
        html = """
        <html><body>
        <a href="mailto:hello@firm.com">Email</a>
        <p>Write to hello@firm.com for info.</p>
        </body></html>
        """
        emails = _extract_emails(html)
        assert emails.count("hello@firm.com") == 1

    def test_filters_junk_emails(self):
        html = """
        <html><body>
        <a href="mailto:noreply@acme.com">Don't reply</a>
        <a href="mailto:no-reply@acme.com">No reply</a>
        <p>test@example.com user@test.com icon@2x.png</p>
        <a href="mailto:real@acme.com">Contact</a>
        </body></html>
        """
        emails = _extract_emails(html)
        assert "real@acme.com" in emails
        assert "noreply@acme.com" not in emails
        assert "no-reply@acme.com" not in emails
        assert "test@example.com" not in emails
        assert "user@test.com" not in emails
        assert "icon@2x.png" not in emails

    def test_empty_when_no_emails(self):
        html = "<html><body><p>No contact info here.</p></body></html>"
        emails = _extract_emails(html)
        assert emails == []


def _html_response(
    *,
    text: str = "<html><body><p>Hello from the public page.</p></body></html>",
    content_type: str = "text/html",
    status: int = 200,
    location: str | None = None,
) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.status_code = status
    response.headers = {"Content-Type": content_type}
    if location is not None:
        response.headers["Location"] = location
    response.raise_for_status = MagicMock()
    return response


def _robots(lines: list[str]) -> RobotFileParser:
    parser = RobotFileParser()
    parser.parse(lines)
    return parser


class TestPublicUrl:
    def test_user_agent_names_the_tool(self):
        assert USER_AGENT.startswith("AIOutreach/")
        assert "Chrome/" not in USER_AGENT
        assert DEFAULT_HEADERS["User-Agent"] == USER_AGENT

    def test_missing_scheme_becomes_https_and_a_trailing_slash_is_removed(self):
        assert classify_public_url("acme.com/about/")[0] == "https://acme.com/about"

    def test_private_and_non_web_urls_are_refused(self):
        refused = [
            "http://127.0.0.1/latest",
            "http://169.254.169.254/computeMetadata/v1/",
            "http://10.1.2.3/",
            "http://192.168.0.8/admin",
            "http://[::1]/",
            "http://localhost/secret",
            "http://metadata.google.internal/computeMetadata/v1/",
            "ftp://files.example/readme",
            "https://user:pass@acme.com/private",
        ]
        for url in refused:
            normalized, reason = classify_public_url(url)
            assert normalized == "", url
            assert reason

    def test_private_address_does_not_open_a_connection(self):
        def _forbid(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a private address was fetched")

        with patch("requests.sessions.Session.request", _forbid):
            result = scrape_website("http://127.0.0.1/latest", use_playwright_fallback=True)
        assert result.pages == []
        assert "not a public website" in result.scrape_note

    def test_literal_public_address_skips_dns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(host: str, port: int | None, *_args: object, **_kwargs: object) -> list[tuple]:
            raise AssertionError(f"DNS was called for literal {host}")

        monkeypatch.setattr("src.scraper.socket.getaddrinfo", _boom)
        assert resolution_block("https://1.1.1.1/page") == ""

    def test_name_that_resolves_private_is_not_fetched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _private(host: str, port: int | None, *_args: object, **_kwargs: object) -> list[tuple]:
            assert host == "rebind.example"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

        monkeypatch.setattr("src.scraper.socket.getaddrinfo", _private)

        def _forbid(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a private resolution was fetched")

        with patch("requests.sessions.Session.request", _forbid):
            result = scrape_website("https://rebind.example/admin", use_playwright_fallback=True)
        assert result.pages == []
        assert "169.254.169.254" in result.scrape_note

    def test_one_private_answer_among_public_ones_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _mixed(host: str, port: int | None, *_args: object, **_kwargs: object) -> list[tuple]:
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 0)),
            ]

        monkeypatch.setattr("src.scraper.socket.getaddrinfo", _mixed)
        note = resolution_block("https://mixed.example")
        assert "10.0.0.8" in note

    def test_lookup_failure_is_not_fetched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _missing(host: str, port: int | None, *_args: object, **_kwargs: object) -> list[tuple]:
            raise socket.gaierror(8, "nodename nor servname provided")

        monkeypatch.setattr("src.scraper.socket.getaddrinfo", _missing)

        def _forbid(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a failed lookup was fetched")

        with patch("requests.sessions.Session.request", _forbid):
            result = scrape_website("https://missing.example", use_playwright_fallback=True)
        assert result.pages == []
        assert "Could not look up missing.example" in result.scrape_note

    def test_link_local_ipv6_answer_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _local(host: str, port: int | None, *_args: object, **_kwargs: object) -> list[tuple]:
            return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%eth0", 0, 0, 0))]

        monkeypatch.setattr("src.scraper.socket.getaddrinfo", _local)
        note = resolution_block("https://lan.example")
        assert "fe80::1" in note
        assert ipaddress.ip_address("fe80::1").is_link_local

    def test_empty_lookup_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.scraper.socket.getaddrinfo", lambda *_args, **_kwargs: [])
        assert "Could not look up" in resolution_block("https://empty.example")


class TestFetchGuards:
    def test_missing_content_type_still_accepts_html(self):
        session = MagicMock()
        session.get.return_value = _html_response(
            content_type="",
            text="<!doctype html><html><body><p>Visible page</p></body></html>",
        )
        result = _fetch_page("https://acme.com", session)
        assert result is not None
        assert "Visible page" in result

    def test_huge_body_is_cut_before_parsing(self):
        session = MagicMock()
        session.get.return_value = _html_response(text="<html>" + ("x" * 100))
        with patch("src.scraper.MAX_HTML_CHARS", 12):
            result = _fetch_page("https://acme.com", session)
        assert result == "<html>" + ("x" * 6)

    def test_same_host_redirect_is_followed(self):
        session = MagicMock()
        session.get.side_effect = [
            _html_response(status=302, location="/about"),
            _html_response(text="<html><body><p>About the team</p></body></html>"),
        ]
        result = _fetch_page("https://acme.com", session)
        assert result is not None
        assert "About the team" in result
        assert session.get.call_count == 2

    def test_cross_host_redirect_is_not_followed(self):
        session = MagicMock()
        session.get.return_value = _html_response(status=302, location="https://evil.example/phish")
        result = _fetch_page("https://acme.com", session)
        assert result is None
        session.get.assert_called_once()

    def test_redirect_to_a_private_address_is_not_followed(self):
        session = MagicMock()
        session.get.return_value = _html_response(
            status=302, location="http://169.254.169.254/latest"
        )
        result = _fetch_page("https://acme.com", session)
        assert result is None
        session.get.assert_called_once()

    def test_redirect_to_a_name_that_resolves_private_is_not_followed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _lookup(host: str, port: int | None, *_args: object, **_kwargs: object) -> list[tuple]:
            if host == "www.acme.com":
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

        monkeypatch.setattr("src.scraper.socket.getaddrinfo", _lookup)
        session = MagicMock()
        session.get.return_value = _html_response(status=302, location="https://www.acme.com/about")
        result = _fetch_page("https://acme.com", session)
        assert result is None
        session.get.assert_called_once()


class TestRobots:
    def test_missing_robots_does_not_block(self):
        session = MagicMock()
        session.get.return_value = _html_response(status=404, content_type="text/plain", text="")
        assert _fetch_robots(session, "https://acme.com") is None

    def test_robots_network_error_does_not_block(self):
        import requests

        session = MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("offline")
        assert _fetch_robots(session, "https://acme.com") is None

    def test_robots_rules_are_applied_to_this_user_agent(self):
        session = MagicMock()
        session.get.return_value = _html_response(
            status=200,
            content_type="text/plain",
            text="User-agent: *\nDisallow: /private\n",
        )
        parser = _fetch_robots(session, "https://acme.com")
        assert parser is not None
        assert parser.can_fetch(USER_AGENT, "https://acme.com/private") is False
        assert parser.can_fetch(USER_AGENT, "https://acme.com/about") is True

    def test_crawl_delay_is_capped(self):
        assert _pause_seconds(None) == RATE_LIMIT_DELAY
        assert _pause_seconds(_robots(["User-agent: *", "Crawl-delay: 2"])) == 2.0
        assert _pause_seconds(_robots(["User-agent: *", "Crawl-delay: 90"])) == MAX_CRAWL_DELAY

    @patch("src.scraper.time.sleep")
    @patch("src.scraper._fetch_page")
    @patch("src.scraper._fetch_robots")
    def test_disallowed_homepage_is_not_fetched(self, mock_robots, mock_fetch, _sleep):
        mock_robots.return_value = _robots(["User-agent: *", "Disallow: /"])
        result = scrape_website("https://acme.com", use_playwright_fallback=True)
        assert result.pages == []
        assert "robots.txt disallows" in result.scrape_note
        mock_fetch.assert_not_called()

    @patch("src.scraper.time.sleep")
    @patch("src.scraper._fetch_page")
    @patch("src.scraper._fetch_robots")
    def test_disallowed_path_is_skipped(self, mock_robots, mock_fetch, mock_sleep):
        mock_robots.return_value = _robots(["User-agent: *", "Disallow: /blog", "Crawl-delay: 30"])
        mock_fetch.return_value = (
            "<html><head><title>Acme</title></head><body>"
            '<a href="/about">About Us</a><a href="/blog">Blog</a>'
            "<p>Acme publishes a long enough homepage to keep.</p>"
            "</body></html>"
        )
        result = scrape_website("https://acme.com", use_playwright_fallback=False)
        urls = [page.url for page in result.pages]
        assert "https://acme.com" in urls
        assert "https://acme.com/about" in urls
        assert "https://acme.com/blog" not in urls
        assert mock_sleep.call_args[0][0] == MAX_CRAWL_DELAY


class TestPlaywrightIdentity:
    def test_browser_context_uses_the_tool_user_agent(self):
        page = MagicMock()
        page.content.return_value = "<html><body><p>Rendered in the browser.</p></body></html>"
        context = MagicMock()
        context.new_page.return_value = page
        browser = MagicMock()
        browser.new_context.return_value = context
        playwright = MagicMock()
        playwright.chromium.launch.return_value = browser
        manager = MagicMock()
        manager.__enter__.return_value = playwright
        manager.__exit__.return_value = False
        fake_sync = MagicMock()
        fake_sync.sync_playwright.return_value = manager
        with patch.dict("sys.modules", {"playwright.sync_api": fake_sync}):
            from src.scraper import _try_playwright_fetch

            result = _try_playwright_fetch("https://acme.com")
        browser.new_context.assert_called_once_with(user_agent=USER_AGENT)
        assert result is not None
        assert "Rendered" in result
