"""Bootstrap: build a structured wiki from a folder of PDFs.

Uses the existing mkdocs.yml nav as the blueprint and the config `domains:` map.
Reuses ingest.py helpers and query.py regeneration. Everyday ingest is unchanged.

Usage:
    python bootstrap.py --kb <path> [--clean]
"""

import re
import sys
import shutil
import datetime
import argparse
import subprocess
from pathlib import Path

import yaml

from ingest import (
    resolve_paths, log, extract_markdown, load_agent_prompt, call_claude,
    split_frontmatter, merge_into_domain, merge_frontmatter, determine_output_path,
    enrich_glossary, _update_nav, _append_changelog,
)

SECTION_RE = re.compile(r"^##\s*DOMAIN:\s*(.+?)\s*$", re.MULTILINE)


def parse_splitter_output(text: str, known_tags) -> dict:
    """{TAG: prose} for each `## DOMAIN: TAG` section whose tag is known and body non-empty."""
    known = {str(t).upper() for t in known_tags}
    matches = list(SECTION_RE.finditer(text))
    blocks = {}
    for i, m in enumerate(matches):
        tag = m.group(1).strip().upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if tag in known and body:
            blocks[tag] = body
    return blocks


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
