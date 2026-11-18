# AI Outreach Automation

A Python app that turns a company URL into a researched cold email.

Paste a website. The app scrapes a handful of pages, asks Claude for a structured read of the business, and drafts an email in a tone you choose. You review and edit the draft before anything goes out. Sending is a separate step through your own Gmail account, and it only happens after you confirm.

Scraping and drafting need an Anthropic API key. Sending needs your own Gmail address and a Gmail app password — not your normal login password. The app does not send mail any other way.

---

## How it works

```
URL → scrape → Claude analysis → email draft → you review → Gmail send
```

| Piece | What it uses |
| --- | --- |
| Language | Python 3.10+ |
| Scraping | BeautifulSoup4 + Requests, with a Playwright fallback |
| Model | Anthropic Claude (`anthropic` SDK) |
| Sending | Gmail SMTP with an app password |
| Interface | Streamlit |
| Models | Pydantic v2 |
| Tests | pytest suite (mocks only — no API keys or network) |

### 1. Web scraping (`src/scraper.py`)

Fetches the homepage and follows internal links that look like About, Services, Blog, and similar pages. Scripts, nav, and footer are stripped. If the first pass comes back thin, it can retry with Playwright. Requests are spaced a second apart, and a site is capped at 8 pages.

### 2. Need analysis (`src/analyzer.py`)

Sends the scraped text to Claude and asks for JSON: company summary, industry, services, pain points, opportunities, a short value note, and one recommended angle. The prompt tells the model to stay tied to the page and not invent a company name for you. Rate limits and transient API errors retry with backoff.

### 3. Email draft (`src/email_drafter.py`)

Writes one cold email from that analysis. It is supposed to mention something specific from the site, stay under 200 words, and end with a low-friction ask. Four tones: **professional**, **conversational**, **bold**, **consultative**. The sign-off uses `SENDER_NAME` (or whatever you type in the sidebar). You can edit the draft or generate another one before sending.

### 4. Gmail send (`src/gmail_sender.py`)

Sends over Gmail SMTP with TLS. You confirm first; nothing sends on its own. Transient SMTP failures retry up to 3 times. Auth failures and rejected recipients do not retry. Each attempt is appended to `logs/outreach_log.json`.

### 5. Follow-ups (`app.py`)

After a send, you can mark a message opened or replied, attach a note, and set a follow-up date. A Follow-Ups tab lists overdue and upcoming items. Tracking is manual. Streamlit does not host a tracking-pixel endpoint, so "opened" means you marked it opened. The log fields are there if a real backend is added later.

The orchestrator in `src/agent.py` runs one URL or a batch. Batch mode stops at the draft for each URL and does not auto-send.

---

## Project structure

```
ai-outreach-automation/
├── app.py                  # Streamlit UI
├── src/
│   ├── scraper.py          # URL → page text
│   ├── analyzer.py         # page text → structured analysis
│   ├── email_drafter.py    # analysis → email draft
│   ├── gmail_sender.py     # draft → SMTP send + log
│   ├── agent.py            # pipeline (single URL and batch)
│   └── models.py           # Pydantic models, sender-name default
├── tests/                  # pytest suite
├── logs/                   # outreach log, created at runtime (gitignored)
├── .streamlit/config.toml
├── .env.example
├── requirements.txt
└── .gitignore
```

---

## Setup

### 1. Clone

```bash
git clone https://github.com/corbinsz/ai-outreach-automation.git
cd ai-outreach-automation
```

### 2. Virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install

```bash
pip install -r requirements.txt
playwright install chromium
```

Playwright is only needed for the JavaScript fallback. Scraping with `requests` works without it.

### 4. Environment variables

```bash
cp .env.example .env
```

Fill in your own keys. Placeholder values in `.env.example` are not real credentials.

```
ANTHROPIC_API_KEY=your-anthropic-api-key
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=your-16-character-app-password
SENDER_NAME=Your Name
```

You can skip the file and type the same values in the sidebar. `SENDER_NAME` is optional. If it is missing, drafts and the From line use `Your Name` until you change it.

Gmail settings are only required when you send. Analysis and drafting work with just the Anthropic key.

#### Gmail app password

Sending uses your own Gmail account. Google will not accept your normal password for SMTP here; you need an app password.

1. Open [Google Account Security](https://myaccount.google.com/security).
2. Turn on **2-Step Verification** if it is off.
3. Search account settings for **App passwords**.
4. Create one for Mail.
5. Put the 16-character password in `GMAIL_APP_PASSWORD`.

### 5. Run

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`.

### 6. Tests

```bash
pytest tests/ -v
```

The suite mocks Claude and SMTP. It does not call the network or need keys.

---

## Environment variables

| Variable | Required | Description |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `GMAIL_ADDRESS` | To send | Gmail address the message is sent from |
| `GMAIL_APP_PASSWORD` | To send | Gmail app password (16 characters), not your login password |
| `SENDER_NAME` | No | Display name on the From line |

---

## What you can do in the UI

- Run one URL or a list of URLs. Batch mode drafts only.
- Pick a tone, then edit or regenerate the draft.
- Send only after you confirm, from your own Gmail account.
- Read the outreach log, mark opened or replied, and set follow-up dates.
- Snooze follow-ups from the Follow-Ups tab.

---

## Known limitations

- **JavaScript-heavy sites**: Basic scraping uses `requests`, which does not execute JavaScript. The Playwright fallback has to be installed separately (`playwright install chromium`).
- **Rate limiting**: Some sites block automated requests. The scraper sends a User-Agent and waits 1 second between requests. It cannot get past aggressive anti-bot measures.
- **Content extraction**: The scraper looks for common page structures. Unusual layouts return less useful text.
- **Gmail sending limits**: Gmail caps how much mail a normal account can send in a day (on the order of 500). This is meant for a short list of prospects, not a blast.
- **Single language**: Website reading and email generation are English only.
- **Open tracking is manual**: There is no tracking pixel. "Opened" and "replied" are statuses you set yourself.

---

## Design notes

1. **A plain pipeline instead of LangChain or CrewAI.** Four stages with a clear handoff are easier to debug without a framework in the middle.
2. **SMTP with an app password instead of Gmail OAuth.** Faster to set up for a personal tool. OAuth is the better choice if this ever sends as more than one person.
3. **Pydantic models** between stages, so a bad model response fails at the boundary instead of halfway through a send.
4. **Separate modules.** Scrape, analyze, draft, and send can each be called on their own.
5. **Streamlit** for the review screen and the log. It is enough UI for this; it is not a mail server, which is why tracking stays manual.
