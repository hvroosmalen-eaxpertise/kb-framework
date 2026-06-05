# M:/KnowledgeBase/kb-framework/tests/test_bootstrap.py
from pathlib import Path

import yaml

import ingest


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
