"""
Ingestion pipeline: PDF → enriched Markdown → docs folder.

Usage:
    python ingest.py --kb <path-to-kb>          # process all PDFs in inbox/
    python ingest.py --kb <path> --file <pdf>   # process one specific PDF
"""

import os
import sys
import json
import shutil
import argparse
import datetime
import subprocess
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

# ── Paths ──────────────────────────────────────────────────────────────────────

def resolve_paths(kb_root: Path):
    return {
        "inbox":     kb_root / "pipeline" / "inbox",
        "processed": kb_root / "pipeline" / "processed",
        "failed":    kb_root / "pipeline" / "failed",
        "docs":      kb_root / "docs",
        "logs":      kb_root / "logs",
        "config":    kb_root / "config" / "kb.yaml",
    }

# ── Logging ────────────────────────────────────────────────────────────────────

def log(log_file: Path, level: str, message: str):
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    entry = f"{timestamp} [{level}] {message}\n"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(entry)
    print(entry.strip())

# ── PDF extraction ─────────────────────────────────────────────────────────────

def extract_markdown(pdf_path: Path) -> str:
    """Convert PDF to raw Markdown using marker-pdf if available, else basic text."""
    try:
        result = subprocess.run(
            ["marker_single", str(pdf_path), "--output_format", "markdown"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: pypdf plain text extraction
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    except ImportError:
        pass

    raise RuntimeError(f"No PDF extraction tool available. Install marker-pdf or pypdf.")

# ── Claude enrichment ──────────────────────────────────────────────────────────

def load_agent_prompt(framework_path: Path, agent_name: str) -> str:
    agent_file = framework_path / "agents" / f"{agent_name}.md"
    text = agent_file.read_text(encoding="utf-8")
    # Extract the content between the first ```...``` block as the system prompt
    import re
    match = re.search(r"```\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text

def call_claude(system_prompt: str, user_content: str, model="claude-sonnet-4-6") -> str:
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}]
    )
    return message.content[0].text

def determine_output_path(docs_root: Path, frontmatter: dict, source_name: str) -> Path:
    content_type = frontmatter.get("content_type", "report")
    domains = frontmatter.get("domain", [])
    year = str(frontmatter.get("source_year", datetime.datetime.now().year))

    if content_type == "standard":
        domain = domains[0].lower().replace("-", "") if domains else "standards"
        return docs_root / "standards" / domain / f"{source_name}.md"
    elif content_type == "directive":
        return docs_root / "standards" / "csrd" / f"{source_name}.md"
    elif content_type == "framework":
        domain = domains[0].lower().replace("-", "") if domains else "frameworks"
        return docs_root / "frameworks" / domain / f"{source_name}.md"
    elif content_type == "report":
        return docs_root / "reports" / year / f"{source_name}.md"
    else:
        return docs_root / f"{source_name}.md"

# ── Nav update ────────────────────────────────────────────────────────────────

def _update_nav(mkdocs_yml: Path, out_path: Path, docs_root: Path, title: str, frontmatter: dict):
    """Insert a newly ingested page into the mkdocs.yml nav under the correct section."""
    config = yaml.safe_load(mkdocs_yml.read_text(encoding="utf-8"))
    nav = config.get("nav", [])
    rel = str(out_path.relative_to(docs_root)).replace("\\", "/")

    content_type = frontmatter.get("content_type", "report")
    year = str(frontmatter.get("source_year", datetime.date.today().year))

    if content_type != "report":
        return  # Only auto-nav reports for now; standards/frameworks are hand-authored

    # Find or create the Reports section
    reports_entry = next((item for item in nav if isinstance(item, dict) and "Reports" in item), None)
    if reports_entry is None:
        nav.append({"Reports": []})
        reports_entry = nav[-1]

    reports_list = reports_entry["Reports"]
    if not isinstance(reports_list, list):
        reports_list = []
        reports_entry["Reports"] = reports_list

    # Find or create the year subsection
    year_entry = next((item for item in reports_list if isinstance(item, dict) and year in item), None)
    if year_entry is None:
        reports_list.append({year: [{"Overview": f"reports/{year}/index.md"}]})
        year_entry = reports_list[-1]

    year_list = year_entry[year]
    if not isinstance(year_list, list):
        year_list = []
        year_entry[year] = year_list

    # Skip if already registered
    if any(rel in item.values() for item in year_list if isinstance(item, dict)):
        return

    year_list.append({title: rel})
    config["nav"] = nav
    mkdocs_yml.write_text(
        yaml.dump(config, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


# ── Changelog ─────────────────────────────────────────────────────────────────

def _append_changelog(changelog: Path, pdf_name: str, out_path: Path, docs_root: Path, frontmatter: dict):
    today = datetime.date.today().isoformat()
    rel   = out_path.relative_to(docs_root)
    title = frontmatter.get("title", out_path.stem)
    domain = ", ".join(frontmatter.get("domain", [])) or "—"

    entry = f"- **{pdf_name}** → `{rel}` — {title} (domain: {domain})\n"

    if not changelog.exists():
        changelog.write_text(f"# Changelog\n\n## {today}\n\n### Added (ingested)\n{entry}", encoding="utf-8")
        return

    text = changelog.read_text(encoding="utf-8")

    # Insert under existing date heading if present, else prepend a new date section
    date_heading = f"## {today}"
    section_heading = "### Added (ingested)"

    if date_heading in text:
        if section_heading in text:
            # Append to the existing "Added (ingested)" block for today
            insert_after = text.index(section_heading) + len(section_heading)
            text = text[:insert_after] + "\n" + entry + text[insert_after:]
        else:
            # Add the section heading after today's date heading
            insert_after = text.index(date_heading) + len(date_heading)
            text = text[:insert_after] + f"\n\n{section_heading}\n{entry}" + text[insert_after:]
    else:
        # Prepend a new date block after the first heading line
        first_newline = text.index("\n") + 1
        new_block = f"\n## {today}\n\n{section_heading}\n{entry}\n---\n\n"
        text = text[:first_newline] + new_block + text[first_newline:]

    changelog.write_text(text, encoding="utf-8")


# ── Main ingest ────────────────────────────────────────────────────────────────

def ingest_pdf(pdf_path: Path, paths: dict, framework_path: Path, kb_config: dict):
    ingest_log  = paths["logs"] / "ingestion.log"
    enrich_log  = paths["logs"] / "enrichment.log"
    source_name = pdf_path.stem.lower().replace(" ", "-")

    log(ingest_log, "INFO", f"START {pdf_path.name}")

    try:
        # 1. Extract raw Markdown
        raw_md = extract_markdown(pdf_path)
        log(ingest_log, "INFO", f"EXTRACTED {len(raw_md)} chars from {pdf_path.name}")

        source_meta = (
            f"Source file: {pdf_path.name}\n"
            f"Source body: {kb_config.get('default_source_body', 'Unknown')}\n"
            f"Date: {datetime.date.today().isoformat()}"
        )
        user_input = f"{source_meta}\n\n---\n\n{raw_md[:12000]}"

        # 2. Rewrite to Wikipedia style
        wiki_prompt = load_agent_prompt(framework_path, "wikipedia-style")
        article_md  = call_claude(wiki_prompt, user_input)
        log(enrich_log, "INFO", f"STYLE_APPLIED {pdf_path.name}")

        # 3. Generate frontmatter
        tag_prompt    = load_agent_prompt(framework_path, "tagger")
        frontmatter_yaml = call_claude(tag_prompt, f"{source_meta}\n\n---\n\n{article_md[:6000]}")
        frontmatter_yaml = frontmatter_yaml.strip().lstrip("---").strip()
        try:
            frontmatter = yaml.safe_load(frontmatter_yaml)
        except yaml.YAMLError:
            frontmatter = {"content_type": "report", "status": "draft"}
        frontmatter["date_added"] = datetime.date.today().isoformat()
        frontmatter["date_updated"] = datetime.date.today().isoformat()
        frontmatter["source_file"] = pdf_path.name
        log(enrich_log, "INFO", f"TAGGED {pdf_path.name} → domain={frontmatter.get('domain')}")

        # 4. Assemble final file
        fm_block = "---\n" + yaml.dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n"
        final_content = fm_block + article_md

        # 5. Write to docs
        out_path = determine_output_path(paths["docs"], frontmatter, source_name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(final_content, encoding="utf-8")
        log(ingest_log, "INFO", f"WRITTEN {out_path.relative_to(paths['docs'].parent)}")

        # 6. Move PDF to processed
        dest = paths["processed"] / pdf_path.name
        shutil.move(str(pdf_path), str(dest))
        log(ingest_log, "INFO", f"DONE {pdf_path.name} → {out_path.name}")

        # 7. Append to CHANGELOG.md
        _append_changelog(
            changelog=paths["logs"].parent / "CHANGELOG.md",
            pdf_name=pdf_path.name,
            out_path=out_path,
            docs_root=paths["docs"],
            frontmatter=frontmatter,
        )

        # 8. Register page in mkdocs.yml nav
        page_title = frontmatter.get("title", out_path.stem.replace("-", " ").title())
        _update_nav(
            mkdocs_yml=paths["logs"].parent / "mkdocs.yml",
            out_path=out_path,
            docs_root=paths["docs"],
            title=page_title,
            frontmatter=frontmatter,
        )

        return out_path

    except Exception as e:
        shutil.move(str(pdf_path), str(paths["failed"] / pdf_path.name))
        log(ingest_log, "ERROR", f"FAILED {pdf_path.name}: {e}")
        raise

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", required=True, help="Path to KB root folder")
    parser.add_argument("--file", help="Process a single PDF file")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    kb_root      = Path(args.kb).resolve()
    load_dotenv(kb_root / ".env")
    paths        = resolve_paths(kb_root)
    config_file  = paths["config"]
    kb_config    = yaml.safe_load(config_file.read_text()) if config_file.exists() else {}
    fw_raw = kb_config.get("framework_path", "framework")
    framework_path = (kb_root / fw_raw).resolve()

    pdfs = [Path(args.file)] if args.file else sorted(paths["inbox"].glob("*.pdf"))
    if not pdfs:
        print("No PDFs found in inbox.")
        return

    ingested = []
    for pdf in pdfs:
        try:
            out = ingest_pdf(pdf, paths, framework_path, kb_config)
            ingested.append(out)
        except Exception:
            continue

    if ingested:
        # Trigger rebuild
        rebuild_script = framework_path / "pipeline" / "rebuild.py"
        if rebuild_script.exists():
            subprocess.run([sys.executable, str(rebuild_script), "--kb", str(kb_root)])

if __name__ == "__main__":
    main()
