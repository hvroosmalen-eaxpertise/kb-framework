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

    kb_root      = Path(args.kb).resolve()
    paths        = resolve_paths(kb_root)
    config_file  = paths["config"]
    kb_config    = yaml.safe_load(config_file.read_text()) if config_file.exists() else {}
    framework_path = Path(kb_config.get("framework_path", kb_root / "framework")).resolve()

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
