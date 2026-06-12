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


def reconcile_links(kb_root: Path) -> int:
    """Make a from-scratch build strict-clean.

    Runs a non-strict mkdocs build, harvests the ``unresolved [[wikilink]]`` warnings
    the link hook emits, and records the (normalised) targets in
    ``config/known_external.txt`` so a subsequent ``--strict`` build does not fail on
    them. These are external concepts the LLM referenced that are not (yet) pages or
    glossary terms. Returns the number of newly recorded terms.
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
            print("ABORT: lint - hard failures (run lint.py --kb <kb> for detail)",
                  file=sys.stderr)
            return rc

    if strict:
        rc = _strict_build(Path(kb_root))
        if rc != 0:
            log(log_file, "ERROR", "FINALIZE_ABORT strict build failed")
            print("ABORT: build - mkdocs --strict failed", file=sys.stderr)
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
