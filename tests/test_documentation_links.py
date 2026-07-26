"""Release checks for local Markdown links and anchors."""

import re
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).parents[1]
MARKDOWN_FILES = sorted(
    [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "SECURITY.md",
        *ROOT.glob("docs/**/*.md"),
        ROOT / "apps/web/README.md",
    ]
)
LINK_PATTERN = re.compile(r"(?<!!)\[[^]]*]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


@pytest.mark.parametrize("document", MARKDOWN_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_local_documentation_links_resolve(document: Path) -> None:
    """Every relative Markdown destination exists and every fragment resolves."""
    text = document.read_text(encoding="utf-8")
    for raw_destination in LINK_PATTERN.findall(text):
        destination = raw_destination.strip().split(maxsplit=1)[0].strip("<>")
        if destination.startswith(("http://", "https://", "mailto:")):
            continue
        path_text, separator, fragment = destination.partition("#")
        target = (document.parent / unquote(path_text)).resolve() if path_text else document
        assert target.is_relative_to(ROOT), f"{document}: link escapes repository: {destination}"
        assert target.exists(), f"{document}: missing link target: {destination}"
        if separator and target.suffix.casefold() == ".md":
            anchors = _anchors(target.read_text(encoding="utf-8"))
            assert unquote(fragment).casefold() in anchors, (
                f"{document}: missing anchor in {target}: #{fragment}"
            )


def _anchors(markdown: str) -> set[str]:
    """Approximate GitHub's deterministic heading slug generation."""
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for heading in HEADING_PATTERN.findall(markdown):
        plain = re.sub(r"[`*_~]", "", heading).strip().casefold()
        slug = re.sub(r"[^\w\- ]", "", plain, flags=re.UNICODE).replace(" ", "-")
        suffix = counts.get(slug, 0)
        counts[slug] = suffix + 1
        anchors.add(f"{slug}-{suffix}" if suffix else slug)
    return anchors
