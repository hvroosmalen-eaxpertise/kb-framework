import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))


def _make_kb(tmp_path, nav):
    """Minimal KB: mkdocs.yml with the given nav + a docs/ tree."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "mkdocs.yml").write_text(
        "site_name: Test\nnav:\n" + nav, encoding="utf-8")
    return tmp_path


def test_scaffold_missing_creates_stub_for_unfiled_nav_page(tmp_path):
    import finalize
    kb = _make_kb(tmp_path,
                  "  - Home: index.md\n  - Foo: standards/foo/index.md\n")
    (kb / "docs" / "index.md").write_text("# Home\n", encoding="utf-8")

    created = finalize.scaffold_missing(kb)

    assert created == ["standards/foo/index.md"]
    stub = kb / "docs" / "standards" / "foo" / "index.md"
    assert "Placeholder page scaffolded by bootstrap" in stub.read_text(encoding="utf-8")


def test_scaffold_missing_never_overwrites(tmp_path):
    import finalize
    kb = _make_kb(tmp_path, "  - Home: index.md\n")
    (kb / "docs" / "index.md").write_text("# Real content\n", encoding="utf-8")

    created = finalize.scaffold_missing(kb)

    assert created == []
    assert (kb / "docs" / "index.md").read_text(encoding="utf-8") == "# Real content\n"


def test_reconcile_links_records_unresolved_terms(tmp_path, monkeypatch):
    import finalize
    kb = _make_kb(tmp_path, "  - Home: index.md\n")
    (kb / "config").mkdir()

    class FakeBuild:
        returncode = 0
        stdout = "WARNING - wikilinks: unresolved [[Green Software Foundation]] in x.md\n"
        stderr = ""

    monkeypatch.setattr(finalize.subprocess, "run", lambda *a, **k: FakeBuild())

    recorded = finalize.reconcile_links(kb)

    assert recorded == 1
    text = (kb / "config" / "known_external.txt").read_text(encoding="utf-8")
    assert "green software foundation" in text


def _stub_finalize_steps(finalize, monkeypatch):
    """No-op the pre-gate steps so tests isolate the gate/commit logic."""
    monkeypatch.setattr(finalize, "_regenerate", lambda *a, **k: None)
    monkeypatch.setattr(finalize, "scaffold_missing", lambda *a, **k: [])
    monkeypatch.setattr(finalize, "reconcile_links", lambda *a, **k: 0)


def test_finalize_aborts_before_commit_on_lint_failure(tmp_path, monkeypatch):
    import finalize
    _stub_finalize_steps(finalize, monkeypatch)
    monkeypatch.setattr(finalize, "_run_lint", lambda *a, **k: 1)
    monkeypatch.setattr(finalize, "_strict_build", lambda *a, **k: 0)
    commits = []
    monkeypatch.setattr(finalize, "_commit", lambda *a, **k: commits.append(1) or True)

    rc = finalize.finalize(tmp_path, tmp_path, {}, lint=True, strict=True,
                           commit=True, push=False)

    assert rc == 1
    assert commits == []


def test_finalize_aborts_before_commit_on_strict_build_failure(tmp_path, monkeypatch):
    import finalize
    _stub_finalize_steps(finalize, monkeypatch)
    monkeypatch.setattr(finalize, "_run_lint", lambda *a, **k: 0)
    monkeypatch.setattr(finalize, "_strict_build", lambda *a, **k: 1)
    commits = []
    monkeypatch.setattr(finalize, "_commit", lambda *a, **k: commits.append(1) or True)

    rc = finalize.finalize(tmp_path, tmp_path, {}, lint=True, strict=True,
                           commit=True, push=False)

    assert rc == 1
    assert commits == []


def test_finalize_commits_when_gates_pass(tmp_path, monkeypatch):
    import finalize
    _stub_finalize_steps(finalize, monkeypatch)
    monkeypatch.setattr(finalize, "_run_lint", lambda *a, **k: 0)
    monkeypatch.setattr(finalize, "_strict_build", lambda *a, **k: 0)
    calls = {"commit": 0, "push": 0}
    monkeypatch.setattr(finalize, "_commit",
                        lambda *a, **k: calls.__setitem__("commit", calls["commit"] + 1) or True)
    monkeypatch.setattr(finalize, "_push",
                        lambda *a, **k: calls.__setitem__("push", calls["push"] + 1))

    rc = finalize.finalize(tmp_path, tmp_path, {}, lint=True, strict=True,
                           commit=True, push=True)

    assert rc == 0
    assert calls == {"commit": 1, "push": 1}
