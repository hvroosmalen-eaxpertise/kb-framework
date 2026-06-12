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
