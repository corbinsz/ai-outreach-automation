"""Read a few public pages and turn them into text for the model.

Requests is the default because it has no browser to install. Playwright runs
only when the HTML is too thin to be a real page, which usually means the
site painted its content with JavaScript. This is not a crawler: one site,
a page cap, a pause between requests, and a robots.txt check.

The client identifies itself. It does not pretend to be a browser. Private
and non-web addresses are refused before a socket opens, including a hostname
that resolves to one. Redirects are followed only when they stay on the same
public host.
"""

import ipaddress
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from src.models import ProgressCallback, ScrapedPage, ScrapedWebsite

logger = logging.getLogger(__name__)

# Keywords that indicate important pages to scrape
PAGE_KEYWORDS = {
    "about": "about",
    "services": "services",
    "solutions": "services",
    "products": "services",
    "offerings": "services",
    "what-we-do": "services",
    "blog": "blog",
    "news": "blog",
    "insights": "blog",
    "contact": "contact",
    "team": "about",
    "careers": "about",
    "case-studies": "services",
    "portfolio": "services",
    "pricing": "services",
    "faq": "services",
}

# Elements to strip from HTML before text extraction
STRIP_ELEMENTS = [
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "noscript",
    "iframe",
    "svg",
    "form",
    "button",
]

# Identifies this tool. A Chrome string fetches more pages and misrepresents
# the client. Sites that block unknown agents will return less text, and
# that is the accepted tradeoff. See docs/adr/0004-honest-scrape.md.
USER_AGENT = (
    "AIOutreach/1.0 (+https://github.com/corbinsz/ai-outreach-automation; "
    "personal research; one site, a few pages)"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_TIMEOUT = 15
# Pause between pages after the homepage. robots.txt Crawl-delay can raise
# it, and it is capped so a huge delay cannot stall a run.
RATE_LIMIT_DELAY = 1.0
MAX_CRAWL_DELAY = 10.0
# A cap so one prospect cannot turn into a crawl.
MAX_PAGES = 8
MAX_CONTENT_LENGTH = 5000
# Bound a single response before BeautifulSoup sees it.
MAX_HTML_CHARS = 1_500_000
_MAX_REDIRECTS = 5

_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
}


def _hostname(netloc: str) -> str:
    """Return the host without userinfo or a port. IPv6 stays inside the brackets."""
    host = netloc.lower().strip()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host
    return host.split(":", 1)[0]


def classify_public_url(url: str) -> tuple[str, str]:
    """Return a normalized public http(s) URL, or an empty URL and the reason.

    Literal private, loopback, and link-local addresses are refused here.
    Hostnames are resolved separately by ``resolution_block`` before a request.
    """
    text = url.strip()
    if not text:
        return "", "The URL is empty, so nothing was fetched."
    # A scheme is already present when "://" is. Prepending https would turn
    # ftp://... into a nonsense URL that still looks fetchable.
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return "", "Only http and https pages are fetched."
    if parsed.username or parsed.password:
        return "", "The URL includes a username or password, so nothing was fetched."
    host = _hostname(parsed.netloc)
    if not host:
        return "", "The URL has no host, so nothing was fetched."
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
        return "", f"{host} is not a public website, so nothing was fetched."
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return "", f"{host} is not a public website, so nothing was fetched."
    path = parsed.path or ""
    normalized = f"{parsed.scheme}://{parsed.netloc}{path}".rstrip("/")
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    return normalized, ""


def _blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for addresses that are not a public website."""
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _addresses_for_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve one hostname. Tests replace ``socket.getaddrinfo`` so DNS stays fake.

    A zone index such as ``fe80::1%eth0`` is stripped before the address is parsed.
    """
    found: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in socket.getaddrinfo(host, None):
        raw = info[4][0]
        if not isinstance(raw, str) or not raw:
            continue
        found.append(ipaddress.ip_address(raw.split("%", 1)[0]))
    return found


def resolution_block(url: str) -> str:
    """Return a refusal note, or an empty string when the host is public.

    A hostname is refused when lookup fails or any answer is private, loopback,
    or link-local. The check runs before the request. It cannot see an address
    that changes after the lookup returns.
    """
    host = _hostname(urlparse(url).netloc)
    if not host:
        return "The URL has no host, so nothing was fetched."
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_address(literal):
            return f"{host} is not a public website, so nothing was fetched."
        return ""
    try:
        addresses = _addresses_for_host(host)
    except socket.gaierror:
        return f"Could not look up {host}, so nothing was fetched."
    if not addresses:
        return f"Could not look up {host}, so nothing was fetched."
    for address in addresses:
        if _blocked_address(address):
            return (
                f"{host} resolves to {address}, which is not a public address, "
                "so nothing was fetched."
            )
    return ""


def _same_site(left: str, right: str) -> bool:
    return _host_key(urlparse(left).netloc) == _host_key(urlparse(right).netloc)


def _html_body(text: str) -> str | None:
    """Keep HTML, including a response that forgot its Content-Type, and cap the size."""
    if not isinstance(text, str):
        return None
    body = text
    if len(body) > MAX_HTML_CHARS:
        body = body[:MAX_HTML_CHARS]
    return body


def _looks_like_html(body: str, content_type: str) -> bool:
    ctype = content_type.lower()
    if "text/html" in ctype or "application/xhtml" in ctype:
        return True
    if ctype.strip():
        return False
    start = body.lstrip().lower()
    return start.startswith(("<!doctype", "<html", "<head", "<body"))


def _fetch_page(url: str, session: requests.Session, hops: int = 0) -> str | None:
    """Fetch one page. Redirects stay on the same public host, up to a few hops."""
    if hops > _MAX_REDIRECTS:
        logger.warning(f"Too many redirects for {url}")
        return None
    blocked = resolution_block(url)
    if blocked:
        logger.warning(blocked)
        return None
    try:
        response = session.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout fetching {url}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.warning(f"HTTP error fetching {url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Error fetching {url}: {e}")
        return None

    status = response.status_code if isinstance(response.status_code, int) else 200
    if status in {301, 302, 303, 307, 308}:
        location = response.headers.get("Location", "")
        if not isinstance(location, str) or not location.strip():
            logger.warning(f"Redirect from {url} had no location")
            return None
        nxt = urljoin(url, location.strip())
        allowed, note = classify_public_url(nxt)
        if not allowed:
            logger.warning(f"Refusing redirect from {url}: {note}")
            return None
        if not _same_site(url, allowed):
            logger.warning(f"Refusing cross-host redirect from {url} to {allowed}")
            return None
        return _fetch_page(allowed, session, hops + 1)

    content_type = response.headers.get("Content-Type", "")
    if not isinstance(content_type, str):
        content_type = ""
    body = _html_body(response.text)
    if body is None or not _looks_like_html(body, content_type):
        logger.warning(f"Skipping non-HTML content at {url}: {content_type}")
        return None
    return body


def _fetch_robots(session: requests.Session, base_url: str) -> RobotFileParser | None:
    """Load robots.txt for this host. A missing file means nothing is disallowed.

    A network error is treated the same way: the scrape continues, and the
    log says the file could not be read. That is a best-effort check, not a
    guarantee the site wanted the visit.
    """
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = session.get(robots_url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        logger.info(f"Could not read robots.txt for {base_url}: {exc}")
        return None
    status = response.status_code if isinstance(response.status_code, int) else 0
    if status >= 400 or status == 0:
        logger.info(f"No robots.txt at {robots_url} (status {status}). Continuing.")
        return None
    parser = RobotFileParser()
    parser.parse(response.text.splitlines() if isinstance(response.text, str) else [])
    return parser


def _robots_allow(parser: RobotFileParser | None, url: str) -> bool:
    if parser is None:
        return True
    return bool(parser.can_fetch(USER_AGENT, url))


def _pause_seconds(parser: RobotFileParser | None) -> float:
    """Use Crawl-delay when the file sets one, and never wait more than the cap."""
    if parser is None:
        return RATE_LIMIT_DELAY
    delay = parser.crawl_delay(USER_AGENT)
    if delay is None:
        delay = parser.crawl_delay("*")
    if delay is None:
        return RATE_LIMIT_DELAY
    try:
        seconds = float(delay)
    except (TypeError, ValueError):
        return RATE_LIMIT_DELAY
    return min(max(seconds, RATE_LIMIT_DELAY), MAX_CRAWL_DELAY)


def _extract_text(html: str) -> str:
    """Clean HTML and extract readable text content."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove unwanted elements
    for tag_name in STRIP_ELEMENTS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Get text with spacing
    text = soup.get_text(separator="\n", strip=True)

    # Clean up excessive whitespace / blank lines
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    # Collapse runs of very short lines (likely nav remnants)
    cleaned = []
    for line in lines:
        if len(line) > 2:
            cleaned.append(line)

    text = "\n".join(cleaned)

    # Truncate if too long
    if len(text) > MAX_CONTENT_LENGTH:
        text = text[:MAX_CONTENT_LENGTH] + "\n... [content truncated]"

    return text


def _extract_title(html: str) -> str:
    """Extract the page title from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()

    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    return ""


def _extract_company_name(html: str, url: str) -> str:
    """Try to extract the company name from the homepage."""
    soup = BeautifulSoup(html, "html.parser")

    # Check meta tags
    og_site = soup.find("meta", property="og:site_name")
    if og_site is not None:
        content = og_site.get("content") if hasattr(og_site, "get") else None
        if isinstance(content, str) and content.strip():
            return content.strip()

    # Check title tag (often "Company Name - tagline")
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        title = title_tag.string.strip()
        # Split on common separators
        for sep in [" | ", " - ", " — ", " – ", " :: "]:
            if sep in title:
                return title.split(sep)[0].strip()
        return title

    # Fallback to domain name
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    return domain.split(".")[0].capitalize()


# Junk email patterns to filter out
_JUNK_EMAIL_PATTERNS = {
    "noreply@",
    "no-reply@",
    "donotreply@",
    "mailer-daemon@",
    "postmaster@",
    "webmaster@",
    "hostmaster@",
}
_JUNK_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "test.com", "sentry.io"}
_JUNK_EMAIL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js"}

# Regex for email addresses: standard addr-spec
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)


def _href(tag: object) -> str:
    """Return an anchor href as text. BeautifulSoup may hand back a list of values."""
    getter = getattr(tag, "get", None)
    if not callable(getter):
        return ""
    value = getter("href")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0].strip()
    return ""


def _extract_emails(html: str) -> list[str]:
    """
    Extract contact email addresses from HTML.
    Scans mailto: links first, then falls back to regex on raw HTML.
    Deduplicates and filters junk/image addresses.
    """
    found: dict[str, None] = {}  # ordered set via dict

    soup = BeautifulSoup(html, "html.parser")

    # 1. mailto: links (highest confidence)
    for a_tag in soup.find_all("a", href=True):
        href = _href(a_tag)
        if href.lower().startswith("mailto:"):
            email = href[7:].split("?")[0].strip().lower()
            if email and "@" in email:
                found[email] = None

    # 2. Regex scan on raw HTML
    for match in _EMAIL_RE.findall(html):
        found[match.lower()] = None

    # 3. Filter junk
    cleaned = []
    for email in found:
        # Skip junk prefixes
        if any(email.startswith(pat) for pat in _JUNK_EMAIL_PATTERNS):
            continue
        # Skip junk domains
        domain = email.split("@", 1)[1] if "@" in email else ""
        if domain in _JUNK_EMAIL_DOMAINS:
            continue
        # Skip addresses that look like file references (e.g. icon@2x.png)
        if any(email.endswith(ext) for ext in _JUNK_EMAIL_EXTENSIONS):
            continue
        cleaned.append(email)

    return cleaned


def _host_key(netloc: str) -> str:
    """Return a host for same-site checks. A leading www is not a different site."""
    host = netloc.lower().strip()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host.startswith("www."):
        host = host[4:]
    return host


def _discover_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """
    Discover important internal links from the homepage.
    Returns list of (url, page_type) tuples.
    """
    soup = BeautifulSoup(html, "html.parser")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()

    discovered = {}

    for a_tag in soup.find_all("a", href=True):
        href = _href(a_tag)

        # Skip empty, anchors, mailto, tel, javascript
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        # Resolve relative URLs
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Only follow internal links. www.example.com and example.com are one site.
        # A different subdomain, such as blog.example.com, is not.
        if _host_key(parsed.netloc) != _host_key(base_domain):
            continue

        # Check path against keywords
        path_lower = parsed.path.lower().rstrip("/")
        link_text = a_tag.get_text(strip=True).lower()

        for keyword, page_type in PAGE_KEYWORDS.items():
            if keyword in path_lower or keyword in link_text:
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                clean_url = clean_url.rstrip("/")
                if clean_url not in discovered and clean_url != base_url.rstrip("/"):
                    discovered[clean_url] = page_type
                break

    return list(discovered.items())[: MAX_PAGES - 1]  # -1 for homepage


def _try_playwright_fetch(url: str) -> str | None:
    """Render the page when requests only saw a shell.

    Import is inside the function so the app still starts if Playwright
    is not installed. The caller decides whether the fallback is worth it.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=20000)
            html = page.content()
            browser.close()
            return html
    except ImportError:
        logger.info("Playwright not installed, skipping JS rendering fallback")
        return None
    except Exception as e:
        logger.warning(f"Playwright fallback failed for {url}: {e}")
        return None


def _empty_site(url: str, note: str) -> ScrapedWebsite:
    return ScrapedWebsite(base_url=url, scrape_note=note)


def scrape_website(
    url: str,
    use_playwright_fallback: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> ScrapedWebsite:
    """Fetch the homepage and a handful of internal pages that look relevant.

    A missing scheme is treated as https. Private addresses, credentialed
    URLs, and a homepage that robots.txt disallows return an empty site and
    a note, without fetching the page. Other fetch failures also return an
    empty site so a batch can record the failure and move on.
    """
    normalized, rejected = classify_public_url(url)

    def _log(msg: str) -> None:
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    if not normalized:
        _log(rejected)
        return _empty_site(url.strip(), rejected)
    url = normalized
    blocked = resolution_block(url)
    if blocked:
        _log(blocked)
        return _empty_site(url, blocked)

    _log(f"Starting scrape of {url}")

    session = requests.Session()
    pages = []
    all_emails: dict[str, None] = {}  # ordered set for dedup across pages
    robots = _fetch_robots(session, url)
    pause = _pause_seconds(robots)
    if robots is not None and not _robots_allow(robots, url):
        note = f"robots.txt disallows {url}. Nothing was fetched."
        _log(note)
        return _empty_site(url, note)
    if robots is None:
        _log("No usable robots.txt. Continuing with the page cap.")

    # --- Scrape homepage ---
    _log("Fetching homepage...")
    homepage_html = _fetch_page(url, session)

    if not homepage_html and use_playwright_fallback:
        _log("Trying Playwright fallback for homepage...")
        homepage_html = _try_playwright_fetch(url)

    if not homepage_html:
        note = "Failed to fetch the homepage. Nothing was read."
        _log(note)
        return _empty_site(url, note)

    homepage_text = _extract_text(homepage_html)
    company_name = _extract_company_name(homepage_html, url)

    # Check if content is too thin (might be JS-rendered)
    if len(homepage_text) < 100 and use_playwright_fallback:
        _log("Homepage content is thin, trying Playwright fallback...")
        pw_html = _try_playwright_fetch(url)
        if pw_html:
            pw_text = _extract_text(pw_html)
            if len(pw_text) > len(homepage_text):
                homepage_html = pw_html
                homepage_text = pw_text
                company_name = _extract_company_name(pw_html, url)

    pages.append(
        ScrapedPage(
            url=url,
            title=_extract_title(homepage_html),
            content=homepage_text,
            page_type="homepage",
        )
    )
    for e in _extract_emails(homepage_html):
        all_emails[e] = None
    _log(f"Homepage scraped: {len(homepage_text)} chars")

    # --- Discover and scrape linked pages ---
    linked_pages = _discover_links(homepage_html, url)
    _log(f"Discovered {len(linked_pages)} internal pages to scrape")

    for page_url, page_type in linked_pages:
        allowed, rejected = classify_public_url(page_url)
        if not allowed or not _same_site(url, allowed):
            _log(f"Skipping {page_url}: {rejected or 'off-site link'}")
            continue
        if not _robots_allow(robots, allowed):
            _log(f"Skipping {allowed} because robots.txt disallows it.")
            continue
        page_url = allowed
        time.sleep(pause)
        _log(f"Fetching {page_type} page: {page_url}")

        html = _fetch_page(page_url, session)
        if not html:
            continue

        text = _extract_text(html)
        if len(text) < 30:
            _log(f"Skipping thin page: {page_url}")
            continue

        pages.append(
            ScrapedPage(
                url=page_url,
                title=_extract_title(html),
                content=text,
                page_type=page_type,
            )
        )
        for e in _extract_emails(html):
            all_emails[e] = None
        _log(f"Scraped {page_type}: {len(text)} chars")

    # --- Build combined summary ---
    summary_parts = []
    for page in pages:
        summary_parts.append(f"=== {page.page_type.upper()}: {page.title} ===\n{page.content}")

    raw_summary = "\n\n".join(summary_parts)

    contact_emails = list(all_emails)
    if contact_emails:
        _log(f"Found {len(contact_emails)} contact email(s): {', '.join(contact_emails)}")
    else:
        _log("No contact emails found on this website")

    result = ScrapedWebsite(
        base_url=url,
        company_name=company_name,
        pages=pages,
        raw_text_summary=raw_summary,
        contact_emails=contact_emails,
    )

    _log(f"Scraping complete: {len(pages)} pages, {len(raw_summary)} total chars")
    return result
