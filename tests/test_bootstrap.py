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


# Shared fakes. load_agent_prompt is patched to return the agent NAME, so call_claude
# can dispatch deterministically by name (robust to agent-prompt wording changes).
def _fake_prompt(framework_path, agent_name):
    return agent_name


def _fake_claude(system_prompt, user_content, **kw):
    return {
        "splitter": "## DOMAIN: ESRS\nESRS prose from the source.\n",
        "wikipedia-style": "Wikipedia-style article body about ESRS.",
        "domain-merge": "MERGED ESRS BODY",
        "tagger": "content_type: report\ntitle: A Report\ndomain: []\n",
        "term-enricher": "### Double Materiality\nImpact and financial.\n",
    }.get(system_prompt, "")


def _patch_llm(monkeypatch):
    """Patch call_claude + load_agent_prompt in BOTH modules (ingest helpers call ingest's)."""
    import ingest
    monkeypatch.setattr(bootstrap, "call_claude", _fake_claude)
    monkeypatch.setattr(bootstrap, "load_agent_prompt", _fake_prompt)
    monkeypatch.setattr(ingest, "call_claude", _fake_claude)
    monkeypatch.setattr(ingest, "load_agent_prompt", _fake_prompt)


def test_bootstrap_one_merges_domain_block(tmp_path: Path, monkeypatch):
    fw = Path(__file__).resolve().parents[1]            # real kb-framework
    docs = tmp_path / "docs"; (tmp_path / "logs").mkdir(); (tmp_path / "config").mkdir()
    (tmp_path / "pipeline" / "processed").mkdir(parents=True); docs.mkdir()
    pdf = tmp_path / "pipeline" / "inbox" / "src.pdf"
    pdf.parent.mkdir(parents=True); pdf.write_bytes(b"%PDF-1.4 fake")
    paths = bootstrap.resolve_paths(tmp_path)

    monkeypatch.setattr(bootstrap, "extract_markdown", lambda p: "raw text")
    _patch_llm(monkeypatch)
    domain_map = {"ESRS": "standards/esrs/index.md"}
    merged = bootstrap._bootstrap_one(
        pdf, paths, fw, {"domains": domain_map},
        domain_map=domain_map, nav_paths={"standards/esrs/index.md"},
        label_by_path={"standards/esrs/index.md": "ESRS"})

    page = docs / "standards/esrs/index.md"
    assert page.exists()
    assert "content_type: standard" in page.read_text(encoding="utf-8")
    assert merged is True
    assert (tmp_path / "pipeline" / "processed" / "src.pdf").exists()  # moved


def test_bootstrap_one_report_fallback(tmp_path: Path, monkeypatch):
    fw = Path(__file__).resolve().parents[1]
    docs = tmp_path / "docs"; (tmp_path / "logs").mkdir(); (tmp_path / "config").mkdir()
    (tmp_path / "pipeline" / "processed").mkdir(parents=True); docs.mkdir()
    pdf = tmp_path / "pipeline" / "inbox" / "rep.pdf"
    pdf.parent.mkdir(parents=True); pdf.write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "mkdocs.yml").write_text("site_name: T\nnav: []\n", encoding="utf-8")
    paths = bootstrap.resolve_paths(tmp_path)

    monkeypatch.setattr(bootstrap, "extract_markdown", lambda p: "raw")
    _patch_llm(monkeypatch)
    # Empty domain_map => splitter blocks are all filtered out => report fallback.
    merged = bootstrap._bootstrap_one(
        pdf, paths, fw, {"domains": {}},
        domain_map={}, nav_paths=set(), label_by_path={})
    assert merged is False
    assert list((docs / "reports").rglob("*.md"))  # a report page was written


def test_run_bootstrap_end_to_end_strict_build(tmp_path: Path, monkeypatch):
    fw = Path(__file__).resolve().parents[1]
    (tmp_path / "config").mkdir(); (tmp_path / "logs").mkdir(); (tmp_path / "docs").mkdir()
    for sub in ("inbox", "processed", "failed"):
        (tmp_path / "pipeline" / sub).mkdir(parents=True)
    (tmp_path / "pipeline" / "inbox" / "src.pdf").write_bytes(b"%PDF-1.4 fake")
    (tmp_path / "config" / "kb.yaml").write_text(
        "name: t\nframework_path: " + fw.as_posix() + "\n"
        "domains:\n  ESRS: standards/esrs/index.md\n", encoding="utf-8")
    (tmp_path / "mkdocs.yml").write_text(
        "site_name: T\ndocs_dir: docs\nsite_dir: site\nplugins: [search]\nnav:\n"
        "  - Home: index.md\n  - ESRS: standards/esrs/index.md\n  - Glossary: glossary.md\n",
        encoding="utf-8")

    monkeypatch.setattr(bootstrap, "extract_markdown", lambda p: "raw text")
    _patch_llm(monkeypatch)
    monkeypatch.setattr(bootstrap, "_regenerate", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap, "_rebuild", lambda *a, **k: None)

    kb_cfg = yaml.safe_load((tmp_path / "config" / "kb.yaml").read_text(encoding="utf-8"))
    bootstrap.run_bootstrap(tmp_path, fw, kb_cfg, clean=True)

    assert (tmp_path / "docs" / "standards/esrs/index.md").exists()
    assert (tmp_path / "docs" / "index.md").exists()           # scaffolded stub
    assert (tmp_path / "docs" / "glossary.md").exists()         # seeded by enrich_glossary
    import subprocess, sys
    r = subprocess.run([sys.executable, "-m", "mkdocs", "build",
                        "--config-file", str(tmp_path / "mkdocs.yml"), "--strict"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr


def test_bootstrap_one_merges_into_existing_domain_page(tmp_path: Path, monkeypatch):
    fw = Path(__file__).resolve().parents[1]
    docs = tmp_path / "docs"; (tmp_path / "logs").mkdir(); (tmp_path / "config").mkdir()
    (tmp_path / "pipeline" / "processed").mkdir(parents=True); docs.mkdir()
    # Pre-existing curated ESRS page -> exercises the merge_into_domain branch.
    page = docs / "standards/esrs/index.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\ntitle: ESRS\ncontent_type: standard\ndomain: [ESRS]\n---\n\n"
                    "# ESRS\n\nCurated prose.\n", encoding="utf-8")
    pdf = tmp_path / "pipeline" / "inbox" / "src.pdf"
    pdf.parent.mkdir(parents=True); pdf.write_bytes(b"%PDF-1.4 fake")
    paths = bootstrap.resolve_paths(tmp_path)

    monkeypatch.setattr(bootstrap, "extract_markdown", lambda p: "raw text")
    _patch_llm(monkeypatch)
    domain_map = {"ESRS": "standards/esrs/index.md"}
    merged = bootstrap._bootstrap_one(
        pdf, paths, fw, {"domains": domain_map},
        domain_map=domain_map, nav_paths={"standards/esrs/index.md"},
        label_by_path={"standards/esrs/index.md": "ESRS"})

    assert merged is True
    text = page.read_text(encoding="utf-8")
    assert "MERGED ESRS BODY" in text          # body came from merge_into_domain (stubbed)
    assert "src.pdf" in text                    # merge_frontmatter recorded the source
