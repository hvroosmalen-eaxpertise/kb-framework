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
from dotenv import load_dotenv

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


def clean_docs(kb_root: Path) -> int:
    """Delete all markdown and json under docs/ (keeps directories and mkdocs.yml)."""
    docs = kb_root / "docs"
    removed = 0
    for pattern in ("*.md", "*.json"):
        for page in docs.rglob(pattern):
            page.unlink()
            removed += 1
    return removed


def _new_domain_frontmatter(rel: str, tag: str, label: str, pdf_name: str) -> dict:
    today = datetime.date.today().isoformat()
    ctype = "standard" if rel.startswith("standards/") else "framework"
    return {
        "title": label or tag, "content_type": ctype, "domain": [tag],
        "status": "draft", "date_added": today, "date_updated": today,
        "source_file": pdf_name, "sources": [pdf_name],
    }


def _write(out_path: Path, frontmatter: dict, body: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fm = "---\n" + yaml.dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n"
    out_path.write_text(fm + body, encoding="utf-8")


def _bootstrap_one(pdf, paths, framework_path, kb_config,
                   domain_map, nav_paths, label_by_path) -> bool:
    """Process one PDF. Returns True if it merged into >=1 domain page, else False (report)."""
    ingest_log = paths["logs"] / "ingestion.log"
    enrich_log = paths["logs"] / "enrichment.log"
    raw = extract_markdown(pdf)
    source_meta = (f"Source file: {pdf.name}\n"
                   f"Source body: {kb_config.get('default_source_body', 'Unknown')}\n"
                   f"Date: {datetime.date.today().isoformat()}")
    article = call_claude(load_agent_prompt(framework_path, "wikipedia-style"),
                          f"{source_meta}\n\n---\n\n{raw[:12000]}")

    split = call_claude(load_agent_prompt(framework_path, "splitter"),
                        f"KNOWN DOMAINS: {', '.join(domain_map) or '(none)'}\n\n---\n\n{article[:12000]}")
    blocks = parse_splitter_output(split, domain_map.keys())

    merged_any = False
    written = []  # (out_path, frontmatter) per page actually written, for the changelog
    for tag, prose in blocks.items():
        rel = domain_map[tag]
        if rel not in nav_paths:
            log(enrich_log, "WARN", f"BOOTSTRAP {pdf.name}: domain '{tag}' path '{rel}' not in nav; skipping")
            continue
        target = paths["docs"] / rel
        if target.exists():
            efm, ebody = split_frontmatter(target.read_text(encoding="utf-8"))
            body = merge_into_domain(framework_path, ebody, prose, source_meta)
            fm = merge_frontmatter(efm, {"domain": [tag]}, pdf.name)
        else:
            body = prose
            fm = _new_domain_frontmatter(rel, tag, label_by_path.get(rel, tag), pdf.name)
        _write(target, fm, body)
        log(ingest_log, "INFO", f"BOOTSTRAP_MERGED {pdf.name} -> {rel}")
        written.append((target, fm))
        merged_any = True

    if not merged_any:
        # Standalone report: tag, then write to determine_output_path.
        tag_yaml = call_claude(load_agent_prompt(framework_path, "tagger"),
                               f"{source_meta}\n\n---\n\n{article[:6000]}").strip().lstrip("-").strip()
        try:
            frontmatter = yaml.safe_load(tag_yaml) or {}
        except yaml.YAMLError:
            frontmatter = {}
        frontmatter.setdefault("content_type", "report")
        frontmatter["date_added"] = frontmatter["date_updated"] = datetime.date.today().isoformat()
        frontmatter["source_file"] = pdf.name
        source_name = pdf.stem.lower().replace(" ", "-")
        out_path = determine_output_path(paths["docs"], frontmatter, source_name)
        _write(out_path, frontmatter, article)
        written.append((out_path, frontmatter))
        mkdocs_yml = paths["docs"].parent / "mkdocs.yml"
        if mkdocs_yml.exists():
            _update_nav(mkdocs_yml, out_path, paths["docs"],
                        frontmatter.get("title", source_name), frontmatter)
        log(ingest_log, "INFO", f"BOOTSTRAP_REPORT {pdf.name} -> {out_path.relative_to(paths['docs'])}")

    try:
        enrich_glossary(paths, framework_path, article, source_meta, enrich_log)
    except Exception as exc:
        log(enrich_log, "WARN", f"GLOSSARY_SKIP {pdf.name}: {exc}")

    shutil.move(str(pdf), str(paths["processed"] / pdf.name))
    changelog = paths["logs"].parent / "CHANGELOG.md"
    for out_path, fm in written:
        _append_changelog(changelog=changelog, pdf_name=pdf.name, out_path=out_path,
                          docs_root=paths["docs"], frontmatter=fm)
    return merged_any


def _regenerate(kb_root: Path, framework_path: Path) -> None:
    """Regenerate models (3), cross-ref, synthesis, catalog via query.py subprocesses."""
    query = framework_path / "pipeline" / "query.py"
    for model in ("semantic-model", "concept-map", "ontology"):
        subprocess.run([sys.executable, str(query), "--kb", str(kb_root), "--model", model])
    subprocess.run([sys.executable, str(query), "--kb", str(kb_root),
                    "--cross-ref", "--synthesis", "--catalog"])


def _rebuild(kb_root: Path, framework_path: Path) -> None:
    rebuild = framework_path / "pipeline" / "rebuild.py"
    if rebuild.exists():
        subprocess.run([sys.executable, str(rebuild), "--kb", str(kb_root)])


def run_bootstrap(kb_root: Path, framework_path: Path, kb_config: dict, clean: bool = False):
    paths = resolve_paths(kb_root)
    ingest_log = paths["logs"] / "ingestion.log"
    paths["logs"].mkdir(parents=True, exist_ok=True)
    if clean:
        removed = clean_docs(kb_root)
        log(ingest_log, "INFO", f"BOOTSTRAP_CLEAN removed {removed} files")

    nav_pairs = parse_nav(kb_root / "mkdocs.yml")
    nav_paths = {rel for _, rel in nav_pairs}
    label_by_path = {rel: label for label, rel in nav_pairs}
    domain_map = {k.upper(): v for k, v in (kb_config.get("domains") or {}).items()}

    pdfs = sorted(paths["inbox"].glob("*.pdf"))
    for pdf in pdfs:
        try:
            _bootstrap_one(pdf, paths, framework_path, kb_config,
                           domain_map, nav_paths, label_by_path)
        except Exception as exc:
            log(ingest_log, "ERROR", f"BOOTSTRAP_FAILED {pdf.name}: {exc}")
            try:
                shutil.move(str(pdf), str(paths["failed"] / pdf.name))
            except Exception:
                pass

    _regenerate(kb_root, framework_path)
    created = scaffold_missing(kb_root)
    if created:
        log(ingest_log, "INFO", f"BOOTSTRAP_SCAFFOLD {len(created)} stub pages")
    _rebuild(kb_root, framework_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", required=True)
    parser.add_argument("--clean", action="store_true",
                        help="Delete docs/**/*.md and *.json before building (true from-scratch)")
    args = parser.parse_args()
    kb_root = Path(args.kb).resolve()
    load_dotenv(kb_root / ".env")  # so ANTHROPIC_API_KEY is available to call_claude
    cfg_file = kb_root / "config" / "kb.yaml"
    kb_config = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    fw_raw = (kb_config or {}).get("framework_path", "../kb-framework")
    framework_path = (kb_root / fw_raw).resolve()
    run_bootstrap(kb_root, framework_path, kb_config or {}, clean=args.clean)


if __name__ == "__main__":
    main()
