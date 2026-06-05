from pathlib import Path

import lint


def test_dangling_source_flagged(tiny_kb: Path):
    p = tiny_kb / "docs" / "insights" / "climate.md"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "sources: [esrs, tcfd]", "sources: [esrs, nonexistent]"), encoding="utf-8")
    findings = lint.check_dangling_sources(lint.load(tiny_kb))
    assert any(k == "STALE" and "nonexistent" in d for k, _, d in findings)


def test_no_dangling_when_all_sources_exist(tiny_kb: Path):
    findings = lint.check_dangling_sources(lint.load(tiny_kb))
    assert findings == []


def test_stale_when_source_newer_than_generated(tiny_kb: Path):
    e = tiny_kb / "docs" / "standards" / "esrs" / "index.md"
    e.write_text(e.read_text(encoding="utf-8").replace(
        "date_updated: 2026-06-01", "date_updated: 2026-06-10"), encoding="utf-8")
    findings = lint.check_stale(lint.load(tiny_kb))
    assert any(k == "STALE" and "insights/climate.md" in p for k, p, _ in findings)


def test_orphan_detected_and_orphan_ok_skips(tiny_kb: Path):
    orphan = tiny_kb / "docs" / "reports" / "lonely.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("---\ntitle: Lonely\ncontent_type: report\n---\n\n# Lonely\n",
                      encoding="utf-8")
    findings = lint.check_orphans(lint.load(tiny_kb), nav_paths=set())
    assert any(k == "ORPHAN" and "reports/lonely.md" in p for k, p, _ in findings)

    orphan.write_text("---\ntitle: Lonely\ncontent_type: report\norphan_ok: true\n"
                      "---\n\n# Lonely\n", encoding="utf-8")
    findings = lint.check_orphans(lint.load(tiny_kb), nav_paths=set())
    assert not any("reports/lonely.md" in p for _, p, _ in findings)


def test_wikilinked_page_is_not_orphan(tiny_kb: Path):
    findings = lint.check_orphans(lint.load(tiny_kb), nav_paths=set())
    assert not any("glossary.md" in p for _, p, _ in findings)


def test_missing_xref_flagged_and_ignored(tiny_kb: Path):
    t = tiny_kb / "docs" / "frameworks" / "tcfd" / "index.md"
    t.write_text(t.read_text(encoding="utf-8").replace(
        "Climate governance and risk.",
        "Climate governance and double materiality."), encoding="utf-8")
    arts = lint.load(tiny_kb)
    findings = lint.check_missing_xrefs(arts, ignore=set())
    assert any(k == "XREF" and "tcfd" in p and "double materiality" in d.lower()
               for k, p, d in findings)
    findings = lint.check_missing_xrefs(arts, ignore={"double materiality"})
    assert not any(k == "XREF" for k, _, _ in findings)


def test_run_deterministic_writes_log_and_sets_hard_fail(tiny_kb: Path):
    orphan = tiny_kb / "docs" / "reports" / "lonely.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("---\ntitle: Lonely\ncontent_type: report\n---\n\n# Lonely\n",
                      encoding="utf-8")
    findings, hard = lint.run_deterministic(tiny_kb, {"lint": {"hard_fail": ["ORPHAN"]}})
    assert hard is True
    assert (tiny_kb / "logs" / "lint.log").exists()
    log = (tiny_kb / "logs" / "lint.log").read_text(encoding="utf-8")
    assert "ORPHAN" in log and "reports/lonely.md" in log


def test_run_deterministic_clean_kb_passes(tiny_kb: Path):
    findings, hard = lint.run_deterministic(tiny_kb, {})
    assert hard is False


def test_deep_parses_contradiction_lines(tiny_kb: Path, monkeypatch):
    monkeypatch.setattr(lint, "load_agent_prompt", lambda *a, **k: "PROMPT", raising=False)
    monkeypatch.setattr(lint, "call_claude",
                        lambda *a, **k: "CONTRADICTION esrs vs tcfd: scope differs",
                        raising=False)
    findings = lint.run_deep(tiny_kb, {})
    assert findings and findings[0][0] == "CONTRADICTION"


def test_deep_none_yields_no_findings(tiny_kb: Path, monkeypatch):
    monkeypatch.setattr(lint, "load_agent_prompt", lambda *a, **k: "PROMPT", raising=False)
    monkeypatch.setattr(lint, "call_claude", lambda *a, **k: "NONE", raising=False)
    assert lint.run_deep(tiny_kb, {}) == []
