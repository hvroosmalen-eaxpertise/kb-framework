# M:/KnowledgeBase/kb-framework/tests/test_ingest_md.py
"""Markdown source ingestion (EurSuRA-kb #7).

Frontmatter presence is the raw-vs-authored signal. Authored MD is preserved
(no wikipedia-style rewrite); raw MD goes through the full PDF-style path.
"""
from pathlib import Path

import pytest

import ingest


# ── discovery ────────────────────────────────────────────────────────────────

def test_discover_sources_picks_up_pdf_and_md(tmp_path: Path):
    inbox = tmp_path / "inbox"; inbox.mkdir()
    (inbox / "a.pdf").write_bytes(b"%PDF")
    (inbox / "b.md").write_text("x", encoding="utf-8")
    (inbox / "ignore.txt").write_text("x", encoding="utf-8")
    found = [p.name for p in ingest.discover_sources(inbox, None)]
    assert found == ["a.pdf", "b.md"]


def test_discover_sources_file_arg_overrides_glob(tmp_path: Path):
    inbox = tmp_path / "inbox"; inbox.mkdir()
    (inbox / "a.pdf").write_bytes(b"%PDF")
    found = ingest.discover_sources(inbox, str(tmp_path / "one.md"))
    assert found == [Path(str(tmp_path / "one.md"))]


# ── extraction dispatch ──────────────────────────────────────────────────────

def test_extract_content_reads_md_verbatim(tmp_path: Path):
    md = tmp_path / "src.md"
    md.write_text("# Hello\n\nBody text.\n", encoding="utf-8")
    assert ingest.extract_content(md) == "# Hello\n\nBody text.\n"


def test_extract_content_dispatches_pdf_to_extract_markdown(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "src.pdf"; pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(ingest, "extract_markdown", lambda p: "EXTRACTED")
    assert ingest.extract_content(pdf) == "EXTRACTED"


def test_extract_content_rejects_unknown_extension(tmp_path: Path):
    other = tmp_path / "src.txt"; other.write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError):
        ingest.extract_content(other)


# ── frontmatter parsing ──────────────────────────────────────────────────────

def test_parse_source_frontmatter_valid():
    fm, body, malformed = ingest.parse_source_frontmatter(
        "---\ntitle: T\ncontent_type: report\n---\n\nBody.\n")
    assert fm == {"title": "T", "content_type": "report"}
    assert body == "Body."
    assert malformed is False


def test_parse_source_frontmatter_none():
    fm, body, malformed = ingest.parse_source_frontmatter("# Just a heading\n\nBody.\n")
    assert fm == {}
    assert "Just a heading" in body
    assert malformed is False


def test_parse_source_frontmatter_malformed_is_treated_as_raw():
    raw = "---\ntitle: [unclosed\ncontent_type: report\n---\n\nBody.\n"
    fm, body, malformed = ingest.parse_source_frontmatter(raw)
    assert fm == {}
    assert malformed is True
    assert "Body." in body          # original content preserved for the raw path


def test_has_required_fm():
    assert ingest.has_required_fm({"content_type": "report", "domain": ["ESRS"], "status": "draft"})
    assert not ingest.has_required_fm({"content_type": "report", "domain": ["ESRS"]})
    assert not ingest.has_required_fm({"content_type": "report", "domain": [], "status": "draft"})


# ── build_article: the raw-vs-authored fork ──────────────────────────────────

def _no_claude(*a, **k):
    raise AssertionError("call_claude must not be invoked")


def test_build_article_authored_complete_skips_claude(monkeypatch):
    monkeypatch.setattr(ingest, "call_claude", _no_claude)
    existing = {"content_type": "report", "domain": ["ESRS"], "status": "draft", "title": "T"}
    body = "# Authored\n\nProse kept verbatim.\n"
    article_md, fm = ingest.build_article(existing, body, "ignored-raw", Path("/fw"), "meta",
                                           ingest.resolve_enrich({}))
    assert article_md == body                 # preserved verbatim, no rewrite
    assert fm == existing                      # author frontmatter untouched


def test_build_article_authored_gapfill_author_wins(monkeypatch):
    calls = []

    def fake_claude(system_prompt, user_content, **k):
        calls.append(system_prompt)
        return "content_type: standard\ndomain: [GRI]\nstatus: draft\ntitle: Tagged\n"

    monkeypatch.setattr(ingest, "load_agent_prompt", lambda fw, name: name)
    monkeypatch.setattr(ingest, "call_claude", fake_claude)
    existing = {"content_type": "report", "title": "Author Title"}   # missing domain + status
    article_md, fm = ingest.build_article(existing, "Body.", "raw", Path("/fw"), "meta",
                                           ingest.resolve_enrich({}))
    assert calls == ["tagger"]                 # only the tagger ran, no rewrite
    assert article_md == "Body."
    assert fm["content_type"] == "report"      # author wins on conflict
    assert fm["title"] == "Author Title"       # author wins
    assert fm["domain"] == ["GRI"]             # gap filled by tagger
    assert fm["status"] == "draft"             # gap filled by tagger


def test_build_article_raw_rewrites_and_tags(monkeypatch):
    calls = []

    def fake_claude(system_prompt, user_content, **k):
        calls.append(system_prompt)
        return {
            "wikipedia-style": "Rewritten encyclopaedic body.",
            "tagger": "content_type: report\ndomain: [ESRS]\nstatus: draft\n",
        }[system_prompt]

    monkeypatch.setattr(ingest, "load_agent_prompt", lambda fw, name: name)
    monkeypatch.setattr(ingest, "call_claude", fake_claude)
    article_md, fm = ingest.build_article({}, "raw body", "raw body", Path("/fw"), "meta",
                                           ingest.resolve_enrich({}))
    assert calls == ["wikipedia-style", "tagger"]
    assert article_md == "Rewritten encyclopaedic body."
    assert fm["content_type"] == "report"


# ── integration: authored .md through ingest_source (no live Claude) ──────────

def test_ingest_source_authored_md_preserves_body(tmp_path: Path, monkeypatch):
    fw = Path(__file__).resolve().parents[1]
    docs = tmp_path / "docs"; docs.mkdir()
    (tmp_path / "logs").mkdir()
    for sub in ("inbox", "processed", "failed"):
        (tmp_path / "pipeline" / sub).mkdir(parents=True)
    (tmp_path / "mkdocs.yml").write_text("site_name: T\nnav: []\n", encoding="utf-8")

    body = "# Green Software\n\nAuthored prose that must survive verbatim.\n"
    src = tmp_path / "pipeline" / "inbox" / "green-software.md"
    src.write_text(
        "---\ntitle: Green Software\ncontent_type: report\ndomain: [ESRS]\n"
        "status: draft\nsource_year: 2026\n---\n\n" + body, encoding="utf-8")

    paths = ingest.resolve_paths(tmp_path)
    seen = []

    def fake_claude(system_prompt, user_content, **k):
        seen.append(system_prompt)
        return "### Green Software\nA term.\n"     # only the glossary step may call this

    monkeypatch.setattr(ingest, "load_agent_prompt", lambda fw, name: name)
    monkeypatch.setattr(ingest, "call_claude", fake_claude)

    out = ingest.ingest_source(src, paths, fw, {"domains": {}})

    assert "wikipedia-style" not in seen        # body was NOT rewritten
    assert "tagger" not in seen                 # frontmatter was complete
    written = out.read_text(encoding="utf-8")
    assert body.strip() in written              # body preserved verbatim
    assert out == docs / "reports" / "2026" / "green-software.md"
    assert (tmp_path / "pipeline" / "processed" / "green-software.md").exists()
