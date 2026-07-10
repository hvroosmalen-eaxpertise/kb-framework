"""Extraction-readability guard (issue #14).

Catches unusable PDF extraction (broken-font mojibake or image-only PDFs) before
any enrichment spend. Offline: extract_content is monkeypatched.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import ingest  # noqa: E402


_READABLE = (
    "How do environmental management and corporate social responsibility "
    "strategies become relevant for the core business strategies of firms? "
    "This paper provides some preliminary answers to these questions."
)
# Real sample of the broken-font extraction seen on Corporate_Sustainability_...pdf
_MOJIBAKE = "%-)&#%!& &'.% /'% *01$+'02*0,#3% 2#0#4*2*0,% #0/% ('+5'+#,*% -'($#3 " * 40


def test_readable_prose_passes():
    assert ingest.extraction_looks_readable(_READABLE)


def test_mojibake_fails():
    assert not ingest.extraction_looks_readable(_MOJIBAKE)


def test_empty_fails():
    assert not ingest.extraction_looks_readable("   \n\t ")


def _kb(tmp_path: Path) -> dict:
    (tmp_path / "docs").mkdir()
    (tmp_path / "logs").mkdir()
    for sub in ("inbox", "processed", "failed"):
        (tmp_path / "pipeline" / sub).mkdir(parents=True)
    return ingest.resolve_paths(tmp_path)


def test_ingest_source_routes_mojibake_pdf_to_failed(tmp_path, monkeypatch):
    paths = _kb(tmp_path)
    src = tmp_path / "pipeline" / "inbox" / "broken.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(ingest, "extract_content", lambda p: _MOJIBAKE)
    monkeypatch.setattr(ingest, "call_claude",
                        lambda *a, **k: pytest.fail("must not enrich mojibake"))

    with pytest.raises(RuntimeError, match="unreadable extraction"):
        ingest.ingest_source(src, paths, tmp_path, {"domains": {}})

    assert (paths["failed"] / "broken.pdf").exists()      # fail-loud, routed aside
    assert not src.exists()


def test_ingest_source_does_not_guard_authored_md(tmp_path, monkeypatch):
    """A short authored .md is trusted verbatim and must not trip the guard."""
    paths = _kb(tmp_path)
    (tmp_path / "mkdocs.yml").write_text("site_name: T\nnav: []\n", encoding="utf-8")
    src = tmp_path / "pipeline" / "inbox" / "note.md"
    src.write_text(
        "---\ntitle: Note\ncontent_type: report\ndomain: [ESRS]\nstatus: draft\n"
        "source_year: 2026\n---\n\n# Note\n\nx y z.\n", encoding="utf-8")
    monkeypatch.setattr(ingest, "load_agent_prompt", lambda fw, name: name)
    monkeypatch.setattr(ingest, "call_claude", lambda *a, **k: "### Note\nA term.\n")

    out = ingest.ingest_source(src, paths, tmp_path, {"domains": {}})
    assert out.exists()                                    # processed, not failed
