"""Generate the KB catalog (read-API foundation).

Deterministic, no LLM. Emits two derived artefacts from page frontmatter:
  docs/catalog.json - machine array, one object per page (served at /catalog.json).
  docs/catalog.md   - human page, grouped by content_type, with a generated banner.

Modelled on query.build_cross_ref; reuses query.load_articles.
"""

import json
import re
import datetime
from pathlib import Path

from query import load_articles

WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")

# Pages this generator writes itself; never include them as catalog entries.
SELF_FILES = {"catalog.md", "catalog.json"}


def _site_url(rel: str) -> str:
    if rel == "index.md":
        return ""
    if rel.endswith("/index.md"):
        return rel[: -len("index.md")]
    return rel[:-3] + "/"


def _outbound_links(text: str) -> list[str]:
    return sorted({m.group(1).strip() for m in WIKILINK_RE.finditer(text)})


def collect_entries(kb_root: Path) -> list[dict]:
    docs_path = kb_root / "docs"
    entries = []
    for a in load_articles(docs_path):
        rel = a["rel_path"].as_posix()
        if rel in SELF_FILES:
            continue
        fm = a["frontmatter"] or {}
        domain = fm.get("domain", [])
        if isinstance(domain, str):
            domain = [domain]
        entries.append({
            "title": fm.get("title", rel),
            "summary": fm.get("summary", ""),
            "content_type": fm.get("content_type", ""),
            "domain": list(domain),
            "status": fm.get("status", ""),
            "generated": bool(fm.get("generated", False)),
            "url": _site_url(rel),
            "path": rel,
            "wikilinks": _outbound_links(a["text"]),
        })
    entries.sort(key=lambda e: (e["content_type"], e["path"]))
    return entries


def _write_markdown(docs_path: Path, entries: list[dict]) -> None:
    by_type: dict[str, list[dict]] = {}
    for e in entries:
        by_type.setdefault(e["content_type"] or "other", []).append(e)

    lines = []
    for ctype in sorted(by_type):
        lines.append(f"## {ctype}\n")
        for e in by_type[ctype]:
            dom = f" `{', '.join(e['domain'])}`" if e["domain"] else ""
            flag = " *(generated)*" if e["generated"] else ""
            summary = f" - {e['summary']}" if e["summary"] else ""
            lines.append(f"- [{e['title']}]({e['path']}){dom}{summary}{flag}")
        lines.append("")

    fm = (
        "---\ntitle: Catalog\ncontent_type: model\ngenerated: true\n"
        f"date_updated: {datetime.date.today().isoformat()}\n---\n\n"
        "# Catalog\n\n"
        "Every page in this knowledge base, grouped by type. "
        "Machine-readable version: [catalog.json](catalog.json).\n\n"
    )
    (docs_path / "catalog.md").write_text(fm + "\n".join(lines), encoding="utf-8")


def build_catalog(kb_root: Path) -> list[dict]:
    docs_path = kb_root / "docs"
    entries = collect_entries(kb_root)
    (docs_path / "catalog.json").write_text(
        json.dumps([{k: v for k, v in e.items() if k != "path"} for e in entries],
                   indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_markdown(docs_path, entries)
    print(f"Catalog written: {len(entries)} pages")
    return entries
