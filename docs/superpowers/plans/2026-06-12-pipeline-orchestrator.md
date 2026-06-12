# Pipeline Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command that runs the whole KB pipeline — ingest the inbox, then finalise (regenerate → scaffold → reconcile links → lint → strict build → commit → push) — with fail-fast gates, sharing a single `finalize` module across `orchestrate`, standalone `finalize`, and `bootstrap`.

**Architecture:** Extract the finalising tail currently inlined in `bootstrap.py` into a new `finalize.py` (the single source of truth). Add `orchestrate.py` (ingest + finalise, auto-push) and run `finalize.py` standalone (finalise-only). Refactor `bootstrap.py` to import and call `finalize()`. Gates (lint, `mkdocs --strict`) run before any commit, so a failure leaves nothing committed.

**Tech Stack:** Python 3.11, MkDocs (+ Material), pytest, PyYAML, python-dotenv. All new code lives in `kb-framework/pipeline/`; tests in `kb-framework/tests/`.

---

## File Structure

- **Create** `pipeline/finalize.py` — owns `parse_nav`, `scaffold_missing`, `reconcile_links`, `_regenerate` (moved from `bootstrap.py`), plus new `_run_lint`, `_strict_build`, `_commit`, `_push`, the public `finalize(...)`, and a standalone `main()`.
- **Create** `pipeline/orchestrate.py` — everyday loop: subprocess-ingest the inbox, then call `finalize(...)`.
- **Create** `tests/test_finalize.py` — API-free unit tests for `scaffold_missing`, `reconcile_links`, and `finalize()` gate/abort logic.
- **Modify** `pipeline/bootstrap.py` — remove the moved functions; import them and `finalize` from `finalize`; replace the `run_bootstrap` tail with one `finalize(...)` call.
- **Modify** `EurSuRA-kb/CLAUDE.md` (and `kb-framework/README.md` if it documents the scripts) — add the two new commands.

`rebuild.py` is left in place (other callers may use it) but is no longer invoked by `bootstrap`; `finalize` supersedes its commit/push role.

> **Import direction (no cycles):** `finalize` imports from `ingest` + `usage`; `orchestrate` imports from `finalize`; `bootstrap` imports from `finalize` + `ingest`. `finalize` never imports `bootstrap`.

> **Run all commands from `kb-framework/pipeline/`** (the scripts import sibling modules like `ingest`, `usage` by bare name). `<KB>` below means an absolute path to a KB root, e.g. `M:/KnowledgeBase/EurSuRA-kb`.

---

## Task 1: `finalize.py` — `parse_nav` + `scaffold_missing` (moved)

**Files:**
- Create: `pipeline/finalize.py`
- Test: `tests/test_finalize.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_finalize.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_finalize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finalize'`.

- [ ] **Step 3: Create `finalize.py` with the moved functions**

Create `pipeline/finalize.py`:

```python
"""Finalise a KB: regenerate derived layers, scaffold missing pages, reconcile
external wikilinks, lint, strict-build, commit, and push.

This is the single source of truth for the post-ingest sequence. ``bootstrap.py``
and ``orchestrate.py`` both call :func:`finalize`. Runnable standalone for a
finalise-only pass (no ingest):

    python finalize.py --kb <path> [--no-lint] [--deep] [--no-strict]
                       [--no-commit] [--no-push]
"""

import re
import sys
import datetime
import argparse
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv

import usage
from ingest import resolve_paths, log


def parse_nav(mkdocs_yml: Path) -> list:
    """[(label, rel_path)] for every page in the nav; label is the nearest dict key."""
    cfg = yaml.safe_load(mkdocs_yml.read_text(encoding="utf-8")) or {}
    pairs = []

    def walk(node, label=None):
        if isinstance(node, str):
            pairs.append((label or node, node))
        elif isinstance(node, list):
            for item in node:
                walk(item, label)
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(value, key)

    walk(cfg.get("nav", []))
    return pairs


def scaffold_missing(kb_root: Path) -> list:
    """Write a minimal valid stub for any nav page with no file. Never overwrites."""
    docs = kb_root / "docs"
    created = []
    for label, rel in parse_nav(kb_root / "mkdocs.yml"):
        page = docs / rel
        if page.exists():
            continue
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            f"---\ntitle: {label}\nstatus: draft\n---\n\n# {label}\n\n"
            "*Placeholder page scaffolded by bootstrap. Ingest sources to fill it.*\n",
            encoding="utf-8")
        created.append(rel)
    return created
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_finalize.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/finalize.py tests/test_finalize.py
git commit -m "feat(finalize): add finalize module with parse_nav + scaffold_missing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `finalize.py` — `reconcile_links` (moved)

**Files:**
- Modify: `pipeline/finalize.py`
- Test: `tests/test_finalize.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_finalize.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_finalize.py::test_reconcile_links_records_unresolved_terms -v`
Expected: FAIL — `AttributeError: module 'finalize' has no attribute 'reconcile_links'`.

- [ ] **Step 3: Add `reconcile_links` to `finalize.py`**

Append after `scaffold_missing` in `pipeline/finalize.py`:

```python
def reconcile_links(kb_root: Path) -> int:
    """Make a from-scratch build strict-clean.

    Runs a non-strict mkdocs build, harvests the ``unresolved [[wikilink]]`` warnings
    the link hook emits, and records the (normalised) targets in
    ``config/known_external.txt`` so a subsequent ``--strict`` build does not fail on
    them. Returns the number of newly recorded terms.
    """
    build = subprocess.run([sys.executable, "-m", "mkdocs", "build",
                            "--config-file", str(kb_root / "mkdocs.yml")],
                           cwd=str(kb_root), capture_output=True, text=True)
    found = re.findall(r"unresolved \[\[([^\]]+)\]\]", build.stdout + build.stderr)
    norm = {re.sub(r"\s+", " ", t.split("|")[0]).strip().lower() for t in found}
    norm = {t for t in norm if t}
    if not norm:
        return 0
    kx = kb_root / "config" / "known_external.txt"
    existing = set()
    if kx.exists():
        existing = {re.sub(r"\s+", " ", line).strip().lower()
                    for line in kx.read_text(encoding="utf-8").splitlines()}
    new = sorted(norm - existing)
    if not new:
        return 0
    kx.parent.mkdir(parents=True, exist_ok=True)
    with open(kx, "a", encoding="utf-8") as fh:
        if not existing:
            fh.write("# Auto-recorded by bootstrap: external concepts referenced by "
                     "[[wikilinks]]\n# but not (yet) pages or glossary terms. Promote one "
                     "by adding a page/glossary\n# entry and removing it here.\n")
        for term in new:
            fh.write(term + "\n")
    return len(new)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_finalize.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline/finalize.py tests/test_finalize.py
git commit -m "feat(finalize): move reconcile_links into finalize module

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `finalize.py` — regenerate, gates, commit/push, and `finalize()`

**Files:**
- Modify: `pipeline/finalize.py`
- Test: `tests/test_finalize.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_finalize.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_finalize.py -k finalize_ -v`
Expected: FAIL — `AttributeError: module 'finalize' has no attribute '_run_lint'` (and `finalize`).

- [ ] **Step 3: Add the regenerate step, gate/commit helpers, and `finalize()`**

Append to `pipeline/finalize.py`:

```python
def _regenerate(kb_root: Path, framework_path: Path) -> None:
    """Regenerate models (3), cross-ref, synthesis, catalog via query.py subprocesses."""
    query = framework_path / "pipeline" / "query.py"
    for model in ("semantic-model", "concept-map", "ontology"):
        subprocess.run([sys.executable, str(query), "--kb", str(kb_root), "--model", model])
    subprocess.run([sys.executable, str(query), "--kb", str(kb_root),
                    "--cross-ref", "--synthesis", "--catalog"])


def _run_lint(kb_root: Path, framework_path: Path, deep: bool) -> int:
    """Run lint.py; return its exit code (non-zero when a hard rule fails)."""
    lint_script = framework_path / "pipeline" / "lint.py"
    cmd = [sys.executable, str(lint_script), "--kb", str(kb_root)]
    if deep:
        cmd.append("--deep")
    return subprocess.run(cmd, cwd=str(kb_root)).returncode


def _strict_build(kb_root: Path) -> int:
    """Run a strict mkdocs build; return its exit code."""
    return subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict",
         "--config-file", str(kb_root / "mkdocs.yml")],
        cwd=str(kb_root)).returncode


def _commit(kb_root: Path, log_file: Path) -> bool:
    """Stage derived changes and commit. Returns True if a commit was made."""
    subprocess.run(["git", "add", "docs", "logs", "config", "mkdocs.yml"], cwd=str(kb_root))
    status = subprocess.run(["git", "status", "--porcelain"],
                            cwd=str(kb_root), capture_output=True, text=True)
    if not status.stdout.strip():
        log(log_file, "INFO", "FINALIZE_NO_CHANGES nothing to commit")
        print("No changes to commit.")
        return False
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"ingest: pipeline run {timestamp}"
    subprocess.run(["git", "commit", "-m", msg], cwd=str(kb_root))
    log(log_file, "INFO", f"FINALIZE_COMMIT {msg}")
    return True


def _push(kb_root: Path, log_file: Path) -> None:
    rc = subprocess.run(["git", "push"], cwd=str(kb_root)).returncode
    log(log_file, "INFO", "FINALIZE_PUSH pushed" if rc == 0 else "FINALIZE_PUSH_FAILED")


def finalize(kb_root, framework_path, kb_config, *,
             lint=True, deep=False, strict=True,
             commit=True, push=True) -> int:
    """Run the finalising sequence with fail-fast gates. Returns a process exit code.

    Order: regenerate -> scaffold -> reconcile-links -> lint gate -> strict-build
    gate -> commit -> push. Gates run before any commit, so a failure leaves the
    working tree uncommitted.
    """
    paths = resolve_paths(Path(kb_root))
    log_file = paths["logs"] / "ingestion.log"
    paths["logs"].mkdir(parents=True, exist_ok=True)

    _regenerate(Path(kb_root), Path(framework_path))

    created = scaffold_missing(Path(kb_root))
    if created:
        log(log_file, "INFO", f"FINALIZE_SCAFFOLD {len(created)} stub pages")

    recorded = reconcile_links(Path(kb_root))
    if recorded:
        log(log_file, "INFO", f"FINALIZE_RECONCILE {recorded} external links recorded")

    if lint:
        rc = _run_lint(Path(kb_root), Path(framework_path), deep)
        if rc != 0:
            log(log_file, "ERROR", "FINALIZE_ABORT lint hard-failed")
            print("ABORT: lint — hard failures (run lint.py --kb <kb> for detail)",
                  file=sys.stderr)
            return rc

    if strict:
        rc = _strict_build(Path(kb_root))
        if rc != 0:
            log(log_file, "ERROR", "FINALIZE_ABORT strict build failed")
            print("ABORT: build — mkdocs --strict failed", file=sys.stderr)
            return rc

    if commit:
        made = _commit(Path(kb_root), log_file)
        if made and push:
            _push(Path(kb_root), log_file)

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Finalise a KB: regenerate, scaffold, reconcile, lint, strict build, commit, push.")
    parser.add_argument("--kb", required=True)
    parser.add_argument("--no-lint", action="store_true")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--no-strict", action="store_true")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    kb_root = Path(args.kb).resolve()
    load_dotenv(kb_root / ".env")
    cfg_file = kb_root / "config" / "kb.yaml"
    kb_config = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    fw_raw = (kb_config or {}).get("framework_path", "../kb-framework")
    framework_path = (kb_root / fw_raw).resolve()
    usage.configure(kb_root / "logs")

    rc = finalize(kb_root, framework_path, kb_config or {},
                  lint=not args.no_lint, deep=args.deep,
                  strict=not args.no_strict,
                  commit=not args.no_commit, push=not args.no_push)
    sys.exit(rc)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the full test file to verify it passes**

Run: `python -m pytest tests/test_finalize.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Verify the standalone CLI parses**

Run: `python pipeline/finalize.py --help`
Expected: usage text listing `--kb --no-lint --deep --no-strict --no-commit --no-push`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/finalize.py tests/test_finalize.py
git commit -m "feat(finalize): add regenerate, gates, commit/push, finalize() and CLI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `orchestrate.py` — everyday loop (ingest + finalise)

**Files:**
- Create: `pipeline/orchestrate.py`
- Test: `tests/test_finalize.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_finalize.py`:

```python
def test_orchestrate_aborts_when_ingest_fails(tmp_path, monkeypatch):
    import orchestrate
    monkeypatch.setattr(orchestrate, "_ingest", lambda *a, **k: 2)
    called = {"finalize": 0}
    monkeypatch.setattr(orchestrate, "finalize",
                        lambda *a, **k: called.__setitem__("finalize", 1) or 0)
    monkeypatch.setattr(sys, "argv", ["orchestrate.py", "--kb", str(tmp_path)])

    with pytest.raises(SystemExit) as exc:
        orchestrate.main()

    assert exc.value.code == 2
    assert called["finalize"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_finalize.py::test_orchestrate_aborts_when_ingest_fails -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrate'`.

- [ ] **Step 3: Create `orchestrate.py`**

Create `pipeline/orchestrate.py`:

```python
"""Everyday pipeline loop: ingest the inbox, then finalise.

Usage:
    python orchestrate.py --kb <path> [--file SRC] [--no-lint] [--deep]
                          [--no-strict] [--no-commit] [--no-push]

Ingest is best-effort per source (failures isolate to pipeline/failed/). The
hard gates are lint and the strict build, enforced by finalize(); a gate failure
aborts before any commit. On a clean run this commits and pushes by default
(use --no-push to hold the commit for review).
"""

import sys
import argparse
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv

import usage
from finalize import finalize


def _ingest(kb_root: Path, framework_path: Path, file_arg) -> int:
    """Run ingest.py over the inbox (or a single --file). Returns its exit code."""
    ingest_script = framework_path / "pipeline" / "ingest.py"
    cmd = [sys.executable, str(ingest_script), "--kb", str(kb_root)]
    if file_arg:
        cmd += ["--file", file_arg]
    return subprocess.run(cmd, cwd=str(kb_root)).returncode


def main():
    parser = argparse.ArgumentParser(description="Ingest the inbox then finalise the KB.")
    parser.add_argument("--kb", required=True)
    parser.add_argument("--file", help="Ingest a single source file (.pdf or .md)")
    parser.add_argument("--no-lint", action="store_true")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--no-strict", action="store_true")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    kb_root = Path(args.kb).resolve()
    load_dotenv(kb_root / ".env")
    cfg_file = kb_root / "config" / "kb.yaml"
    kb_config = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    fw_raw = (kb_config or {}).get("framework_path", "../kb-framework")
    framework_path = (kb_root / fw_raw).resolve()
    usage.configure(kb_root / "logs")

    rc = _ingest(kb_root, framework_path, args.file)
    if rc != 0:
        print("ABORT: ingest — ingest.py exited non-zero", file=sys.stderr)
        sys.exit(rc)

    rc = finalize(kb_root, framework_path, kb_config or {},
                  lint=not args.no_lint, deep=args.deep,
                  strict=not args.no_strict,
                  commit=not args.no_commit, push=not args.no_push)
    sys.exit(rc)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_finalize.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Verify the CLI parses**

Run: `python pipeline/orchestrate.py --help`
Expected: usage text listing `--kb --file --no-lint --deep --no-strict --no-commit --no-push`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/orchestrate.py tests/test_finalize.py
git commit -m "feat(orchestrate): add everyday ingest+finalise loop

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Refactor `bootstrap.py` to reuse `finalize`

**Files:**
- Modify: `pipeline/bootstrap.py`

Context: `bootstrap.py` currently defines `parse_nav` (≈ lines 46-62), `scaffold_missing` (≈ 65-79), `_regenerate` (≈ 181-187), `_rebuild` (≈ 190-193), and `reconcile_links` (≈ 196-229), and its `run_bootstrap` tail (≈ 259-266) calls them. We remove the duplicates, import from `finalize`, and replace the tail with one `finalize(...)` call.

- [ ] **Step 1: Update the imports**

In `pipeline/bootstrap.py`, just below the existing `from ingest import (...)` block, add:

```python
from finalize import finalize, parse_nav, scaffold_missing, reconcile_links
```

- [ ] **Step 2: Delete the now-duplicated function definitions**

Remove these definitions from `bootstrap.py` (they now live in `finalize.py`):
`parse_nav`, `scaffold_missing`, `_regenerate`, `_rebuild`, `reconcile_links`.
Leave `parse_splitter_output`, `clean_docs`, `_new_domain_frontmatter`, `_write`, `_bootstrap_one`, `run_bootstrap`, and `main` in place.

- [ ] **Step 3: Replace the `run_bootstrap` tail**

In `run_bootstrap`, replace this block:

```python
    _regenerate(kb_root, framework_path)
    created = scaffold_missing(kb_root)
    if created:
        log(ingest_log, "INFO", f"BOOTSTRAP_SCAFFOLD {len(created)} stub pages")
    recorded = reconcile_links(kb_root)
    if recorded:
        log(ingest_log, "INFO", f"BOOTSTRAP_RECONCILE {recorded} external links recorded")
    _rebuild(kb_root, framework_path)
```

with:

```python
    # From-scratch rebuilds finalise like everyday runs, but commit locally for
    # review (no auto-push).
    finalize(kb_root, framework_path, kb_config, strict=True, push=False)
```

- [ ] **Step 4: Verify bootstrap still imports and parses**

Run: `python -c "import sys; sys.path.insert(0, 'pipeline'); import bootstrap; print('ok')"`
Expected: prints `ok` (no ImportError / NameError).

Run: `python pipeline/bootstrap.py --help`
Expected: usage text with `--kb --clean`.

- [ ] **Step 5: Run the full test suite (no regressions)**

Run: `python -m pytest tests/ -v`
Expected: PASS, including the pre-existing ingest tests and the 7 finalize tests.

- [ ] **Step 6: Commit**

```bash
git add pipeline/bootstrap.py
git commit -m "refactor(bootstrap): reuse shared finalize module

Removes the inlined regenerate/scaffold/reconcile/rebuild tail in favour of a
single finalize(..., push=False) call. From-scratch runs now strict-build and
lint like everyday runs.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: API-free smoke test on EurSuRA-kb

**Files:** none (verification only)

- [ ] **Step 1: Run finalise-only against the live KB, holding the commit**

Run (from `kb-framework/pipeline/`, with `<KB>` = absolute path to `EurSuRA-kb`):
`python finalize.py --kb <KB> --no-push --no-commit`
Expected: regenerate output, then `0` exit. No ingest (no API calls). If the strict build aborts, that is a real content issue to fix before proceeding — do not weaken the gate.

- [ ] **Step 2: Confirm the working tree shows only regenerated/derived changes**

Run: `git -C <KB> status --porcelain`
Expected: only generated files (`docs/catalog.*`, `docs/insights/*`, `docs/models/*`, `docs/cross-reference-matrix.md`) and possibly `config/known_external.txt` — nothing unexpected. Discard with `git -C <KB> checkout -- .` if you don't want to keep them.

- [ ] **Step 3: No commit needed** (verification task).

---

## Task 7: Document the new commands

**Files:**
- Modify: `EurSuRA-kb/CLAUDE.md`
- Modify: `kb-framework/README.md` (only if it documents the pipeline scripts)

- [ ] **Step 1: Update `EurSuRA-kb/CLAUDE.md`**

In the `## Local mechanics` → `Pipeline (from this directory):` list, add these two bullets directly under the existing `ingest.py` bullet:

```markdown
  - `python ../kb-framework/pipeline/orchestrate.py --kb .`  (ingest inbox → finalise → commit → push)
  - `python ../kb-framework/pipeline/finalize.py --kb . --no-push`  (finalise only, hold for review)
```

- [ ] **Step 2: Update `kb-framework/README.md` if applicable**

If `kb-framework/README.md` has a pipeline/scripts section, add a short entry:

```markdown
- `orchestrate.py --kb <path>` — everyday loop: ingest the inbox, then finalise
  (regenerate → scaffold → reconcile links → lint → strict build → commit → push).
- `finalize.py --kb <path>` — the finalise sequence on its own (no ingest); shared
  by orchestrate and bootstrap. Use `--no-push` to commit for review.
```

If there is no such section, skip this step.

- [ ] **Step 3: Commit**

```bash
# In kb-framework (only if README changed):
git add README.md
git commit -m "docs(pipeline): document orchestrate and finalize commands

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
# In EurSuRA-kb:
git -C <KB> add CLAUDE.md
git -C <KB> commit -m "docs: add orchestrate/finalize to pipeline commands

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Shared `finalize.py` with the documented signature → Tasks 1-3. ✓
- `orchestrate.py` everyday loop → Task 4. ✓
- `bootstrap.py` refactored to reuse `finalize` → Task 5. ✓
- Fail-fast gates (lint + strict build before commit) → Task 3 (`finalize()`), tested in Task 3 steps. ✓
- Push defaults (orchestrate/finalize auto-push; bootstrap no-push) → Task 4 (`push` default True), Task 5 (`push=False`). ✓
- `reconcile_links` before strict build → ordering inside `finalize()` (Task 3). ✓
- Testing: scaffold, reconcile, gate-abort → Tasks 1-3; API-free smoke → Task 6. ✓
- Docs update → Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; Task 7 Step 2 is conditional (skip if no section), not a placeholder. ✓

**Type/name consistency:** `finalize(kb_root, framework_path, kb_config, *, lint, deep, strict, commit, push)` used identically in `finalize.main`, `orchestrate.main`, and `bootstrap.run_bootstrap`. Helper names `_run_lint`, `_strict_build`, `_commit`, `_push` are defined in Task 3 and monkeypatched by the same names in tests. `_ingest` defined and monkeypatched consistently in Task 4. ✓
