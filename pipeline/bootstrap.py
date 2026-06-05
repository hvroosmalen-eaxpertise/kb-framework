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
