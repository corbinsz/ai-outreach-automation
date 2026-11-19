# Contributing

This is a personal spare-time project by Corbin Szenegeto. It is not a commercial product and it is not hosted. Issues and small fixes are welcome. Please do not send pull requests that add a public deployment, a tracking pixel, or unsupervised sending.

## Setup

Python 3.10 or newer.

```bash
make setup
make demo
```

`make setup` creates `.venv`, installs the runtime and dev tools, and copies `.env.example` to `.env` when `.env` is missing. `make demo` starts Streamlit in demo mode at `http://127.0.0.1:8501`.

Without make:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
DEMO_MODE=1 streamlit run app.py
```

On Windows, activate with `.venv\Scripts\activate`. The pre-commit config calls `.venv/bin`, which is the Unix layout. On Windows, run `python -m ruff`, `python -m black`, and `python -m mypy` yourself.

Do not commit `.env`. The values in `.env.example` are placeholders.

## Checks

```bash
make check
```

That runs Ruff, Black, mypy, and pytest with a coverage report for `src`. GitHub Actions runs the same tools.

Install the git hooks after `make setup`:

```bash
.venv/bin/pre-commit install
```

## Tests

The suite does not call the network and does not need API keys. Demo-mode tests fail if a sample run touches HTTP, the Anthropic client, or SMTP.

Add a test when you fix a bug. `make eval` scores the saved drafts. The Success metrics section of `docs/PRODUCT.md` has to match that script; a test fails if they drift. If you change a saved draft, run `make eval` and replace that section with the script's output. Do not type a new pass rate by hand.

## Secrets and mail

Do not put keys in issues, commits, or fixtures. Do not point the live sender at a real inbox from CI. Demo companies use the reserved `.example` domain.

## Docs

[docs/PRODUCT.md](docs/PRODUCT.md) is the product write-up. [docs/PRODUCT_NOTES.md](docs/PRODUCT_NOTES.md) is the engineering account. [docs/adr](docs/adr/0001-confirm-before-send.md) holds decisions that should not be relitigated in a drive-by change. If you change a decision, add an ADR rather than quietly rewriting history. Do not invent usage numbers. There are no users to count.
