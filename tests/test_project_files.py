"""Guards for the files a reviewer should find, and for hosted-app URLs."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Deployment hostnames. The GitHub clone URL and Google's own help pages are not this app.
BANNED_HOSTS = (
    "streamlit.app",
    "share.streamlit.io",
    "herokuapp.com",
    "onrender.com",
    "vercel.app",
    "fly.dev",
    "railway.app",
    "netlify.app",
    "github.io",
    "pages.dev",
    "pythonanywhere.com",
    "replit.app",
    "azurewebsites.net",
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
    "logs",
    ".cursor",
}

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
    ".css",
    ".json",
    ".html",
    ".example",
}
TEXT_NAMES = {"Dockerfile", "Makefile", "LICENSE", ".dockerignore", ".env.example", ".gitignore"}


def _tracked_text_files() -> list[Path]:
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        # The denylist itself names the hosts it rejects.
        if path.name in {"test_project_files.py", "test_docs.py"}:
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            found.append(path)
    return found


def test_repo_has_no_hosted_app_urls():
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for banned in BANNED_HOSTS:
            assert banned not in text, f"{path.relative_to(ROOT)} contains {banned}"


def test_license_is_mit_and_names_the_author():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "Corbin Szenegeto" in text


def test_env_example_documents_demo_mode_and_has_no_secret():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DEMO_MODE=" in text
    assert "ANTHROPIC_API_KEY=your-anthropic-api-key" in text
    assert "sk-ant-" not in text
    assert "sk-test" not in text


def test_setup_entry_points_exist():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "setup:" in makefile
    assert "demo:" in makefile
    assert "if [ ! -x .venv/bin/python ]" in makefile
    assert "eval:" in makefile
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "DEMO_MODE=1" in dockerfile
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "127.0.0.1:8501:8501" in compose
    assert (ROOT / ".pre-commit-config.yaml").is_file()
    assert (ROOT / "CONTRIBUTING.md").is_file()
    assert (ROOT / "CHANGELOG.md").is_file()
    assert (ROOT / "docs" / "PRODUCT.md").is_file()
    assert (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").is_file()
    adr = list((ROOT / "docs" / "adr").glob("*.md"))
    assert len(adr) >= 2


def test_markdown_links_resolve_and_readme_stays_a_personal_project():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.lstrip().startswith("# AI Outreach")
    opening = "\n".join(readme.splitlines()[:8]).lower()
    assert "personal project" in opening
    assert "not a commercial product" in opening
    assert "corbin szenegeto" in opening
    assert "127.0.0.1:8501" in readme

    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    markdown_files = [path for path in _tracked_text_files() if path.suffix == ".md"]
    assert markdown_files
    for path in markdown_files:
        for target in link_re.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            assert (path.parent / relative).resolve().exists(), f"{path.name} -> {target}"
