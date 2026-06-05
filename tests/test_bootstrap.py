# M:/KnowledgeBase/kb-framework/tests/test_bootstrap.py
from pathlib import Path

import yaml

import ingest
import bootstrap


def test_domain_index_path_uses_config_map(tmp_path: Path):
    docs = tmp_path / "docs"
    dmap = {"ESRS": "standards/esrs/index.md", "GRI": "frameworks/gri/index.md"}
    fm = {"content_type": "standard", "domain": ["ESRS"]}
    assert ingest.domain_index_path(docs, fm, dmap) == docs / "standards/esrs/index.md"
    # Non-mergeable type -> None
    assert ingest.domain_index_path(docs, {"content_type": "report", "domain": ["ESRS"]}, dmap) is None
    # Unknown domain -> None
    assert ingest.domain_index_path(docs, {"content_type": "framework", "domain": ["XYZ"]}, dmap) is None


def test_enrich_glossary_seeds_when_absent(tmp_path: Path, monkeypatch):
    docs = tmp_path / "docs"; docs.mkdir()
    (tmp_path / "logs").mkdir()
    paths = {"docs": docs, "logs": tmp_path / "logs"}
    monkeypatch.setattr(ingest, "call_claude", lambda *a, **k: "### Double Materiality\nImpact and financial.\n")
    monkeypatch.setattr(ingest, "load_agent_prompt", lambda *a, **k: "PROMPT")
    ingest.enrich_glossary(paths, tmp_path, "article", "meta", paths["logs"] / "enrich.log")
    g = (docs / "glossary.md").read_text(encoding="utf-8")
    assert "# Glossary" in g and "Double Materiality" in g


def test_parse_splitter_output_keeps_known_domains_only():
    text = (
        "## DOMAIN: ESRS\nESRS prose here.\n\n"
        "## DOMAIN: XYZ\nUnknown domain, ignore.\n\n"
        "## DOMAIN: GRI\nGRI prose here.\n"
    )
    blocks = bootstrap.parse_splitter_output(text, ["ESRS", "GRI", "TCFD"])
    assert set(blocks) == {"ESRS", "GRI"}
    assert blocks["ESRS"].startswith("ESRS prose")
    assert "Unknown" not in "".join(blocks.values())


def test_parse_splitter_output_empty_when_no_sections():
    assert bootstrap.parse_splitter_output("nothing here", ["ESRS"]) == {}


def test_parse_nav_and_scaffold(tmp_path: Path):
    (tmp_path / "mkdocs.yml").write_text(
        "site_name: T\nnav:\n"
        "  - Home: index.md\n"
        "  - Standards:\n"
        "    - ESRS: standards/esrs/index.md\n"
        "  - Glossary: glossary.md\n", encoding="utf-8")
    docs = tmp_path / "docs"; docs.mkdir()
    (docs / "glossary.md").write_text("---\ntitle: Glossary\n---\n\n# Glossary\n", encoding="utf-8")

    pairs = bootstrap.parse_nav(tmp_path / "mkdocs.yml")
    assert ("ESRS", "standards/esrs/index.md") in pairs
    assert ("Home", "index.md") in pairs

    created = bootstrap.scaffold_missing(tmp_path)
    assert "index.md" in created and "standards/esrs/index.md" in created
    assert "glossary.md" not in created
    stub = (docs / "standards/esrs/index.md").read_text(encoding="utf-8")
    assert "title: ESRS" in stub and "# ESRS" in stub
    assert "[[" not in stub


def test_clean_docs_removes_md_and_json(tmp_path: Path):
    docs = tmp_path / "docs" / "standards" / "esrs"
    docs.mkdir(parents=True)
    (tmp_path / "docs" / "index.md").write_text("x", encoding="utf-8")
    (docs / "index.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs" / "catalog.json").write_text("[]", encoding="utf-8")
    removed = bootstrap.clean_docs(tmp_path)
    assert removed == 3
    assert list((tmp_path / "docs").rglob("*.md")) == []
    assert list((tmp_path / "docs").rglob("*.json")) == []
