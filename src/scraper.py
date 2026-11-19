"""Read a few public pages and turn them into text for the model.

Requests is the default because it has no browser to install. Playwright runs
only when the HTML is too thin to be a real page, which usually means the
site painted its content with JavaScript. This is not a crawler: one site,
a page cap, and a pause between requests.
"""

import logging
import re
import time
from urllib.parse import urljoin, urlparse

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

# Pretending to be Chrome gets HTML back from simple bot filters. It also
# hides who is asking. That tradeoff is called out in docs/PRODUCT_NOTES.md.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

REQUEST_TIMEOUT = 15
# A fixed pause is a courtesy, not compliance. It does not read robots.txt.
RATE_LIMIT_DELAY = 1.0
# A cap so one prospect cannot turn into a crawl.
MAX_PAGES = 8
MAX_CONTENT_LENGTH = 5000


def _fetch_page(url: str, session: requests.Session) -> str | None:
    """Fetch a single page's HTML content with error handling."""
    try:
        response = session.get(url, headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            logger.warning(f"Skipping non-HTML content at {url}: {content_type}")
            return None

        return response.text
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout fetching {url}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.warning(f"HTTP error fetching {url}: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.warning(f"Error fetching {url}: {e}")
        return None


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
            page = browser.new_page()
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


def scrape_website(
    url: str,
    use_playwright_fallback: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> ScrapedWebsite:
    """Fetch the homepage and a handful of internal pages that look relevant.

    A missing scheme is treated as https. The function returns an empty site
    instead of raising when the homepage cannot be fetched, so a batch can
    record the failure and move on.
    """
    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    url = url.rstrip("/")

    def _log(msg: str) -> None:
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    _log(f"Starting scrape of {url}")

    session = requests.Session()
    pages = []
    all_emails: dict[str, None] = {}  # ordered set for dedup across pages

    # --- Scrape homepage ---
    _log("Fetching homepage...")
    homepage_html = _fetch_page(url, session)

    if not homepage_html and use_playwright_fallback:
        _log("Trying Playwright fallback for homepage...")
        homepage_html = _try_playwright_fetch(url)

    if not homepage_html:
        _log("Failed to fetch homepage. Returning empty result.")
        return ScrapedWebsite(base_url=url)

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
        time.sleep(RATE_LIMIT_DELAY)
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
