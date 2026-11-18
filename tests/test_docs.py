"""Guards for the portfolio docs.

These fail if a relative link rots or if the docs start advertising a hosted app.
They do not fetch the network.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "docs" / "PRODUCT_NOTES.md"]

# Hosted-app markers. The GitHub clone URL and Google's own help pages are allowed.
_BANNED = (
    "streamlit.app",
    "share.streamlit.io",
    "herokuapp.com",
    "onrender.com",
    "vercel.app",
    "fly.dev",
    "railway.app",
)


def test_docs_exist_and_state_this_is_a_personal_project():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.lstrip().startswith("# AI Outreach")
    opening = "\n".join(readme.splitlines()[:8]).lower()
    assert "personal project" in opening
    assert "not a commercial product" in opening
    assert "corbin szenegeto" in opening


def test_relative_markdown_links_resolve():
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        for target in link_re.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            assert (path.parent / relative).resolve().exists(), f"{path.name} -> {target}"


def test_docs_do_not_advertise_a_hosted_app():
    blob = "\n".join(path.read_text(encoding="utf-8").lower() for path in DOCS)
    for banned in _BANNED:
        assert banned not in blob
    assert "127.0.0.1:8501" in blob
