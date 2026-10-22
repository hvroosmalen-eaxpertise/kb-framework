"""
Query the knowledge base content and generate derived artefacts.

Usage:
    python query.py --kb <path> --model semantic-model
    python query.py --kb <path> --model concept-map
    python query.py --kb <path> --model ontology
    python query.py --kb <path> --cross-ref     # regenerate cross-reference matrix
    python query.py --kb <path> --synthesis      # regenerate cross-domain insight pages
"""

import re
import argparse
import datetime
from pathlib import Path

import anthropic
import yaml

import usage
import mkdocs_yaml
from ingest import resolve_enrich, enrich_call


def _enrich(kb_root: Path) -> dict:
    """Resolve the KB's enrichment backend config (Claude/Ollama per task)."""
    cfg_file = kb_root / "config" / "kb.yaml"
    kb_cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    return resolve_enrich(kb_cfg or {})


def _link_resolver(kb_root: Path):
    """Load the KB's hooks.py wikilink index (titles + glossary + slugs + aliases +
    known-external). Used to strip [[links]] a generator invented that would not
    resolve under `mkdocs build --strict` — backend-agnostic, but essential now
    that local models (which invent links more freely) can drive generation."""
    hooks_path = kb_root / "hooks.py"
    if not hooks_path.exists():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("_kb_hooks", hooks_path)
    hooks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hooks)
    docs_dir = str(kb_root / "docs")
    index: dict = {}
    for key, target in getattr(hooks, "MANUAL_ALIASES", {}).items():
        hooks._register(index, key, target)
    hooks._index_titles(index, docs_dir)
    hooks._index_glossary(index, docs_dir)
    hooks._index_slugs(index, docs_dir)
    return hooks, index, hooks._load_known_external(docs_dir)


def _sanitize_links(text: str, resolver) -> str:
    """Demote any [[wikilink]] that would not resolve at build time to plain text,
    keeping the ones that do. No-op if the KB ships no hooks.py."""
    if not resolver:
        return text
    hooks, index, external = resolver

    def repl(m):
        key = m.group(1).strip().rstrip("\\")
        display = (m.group(2) or key).strip()
        nk = hooks._norm(key)
        return m.group(0) if (nk in index or nk in external) else display

    return hooks.WIKILINK_RE.sub(repl, text)


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s-]+", "-", text)


def load_articles(docs_path: Path) -> list[dict]:
    articles = []
    for md_file in docs_path.rglob("*.md"):
        text = md_file.read_text(encoding="utf-8")
        frontmatter = {}
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    text = parts[2].strip()
                except yaml.YAMLError:
                    pass
        articles.append({
            "path": md_file,
            "rel_path": md_file.relative_to(docs_path),
            "frontmatter": frontmatter,
            "text": text,
        })
    return articles


def load_agent_prompt(framework_path: Path, agent_name: str) -> str:
    agent_file = framework_path / "agents" / f"{agent_name}.md"
    text = agent_file.read_text(encoding="utf-8")
    match = re.search(r"```\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text


def call_claude(system_prompt: str, user_content: str, model="claude-sonnet-4-6",
                label: str = "") -> str:
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}]
    )
    usage.record(model, message.usage, label)
    return message.content[0].text


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text


def build_model(kb_root: Path, framework_path: Path, model_type: str):
    docs_path = kb_root / "docs"
    articles  = load_articles(docs_path)

    # Build context from published articles only (skip models/ and index)
    content_articles = [
        a for a in articles
        if "models" not in str(a["rel_path"])
        and a["frontmatter"].get("status") in ("published", "review", None)
    ]

    titles_list = "\n".join(
        f"- {a['frontmatter'].get('title', a['rel_path'])} [{', '.join(a['frontmatter'].get('domain', []))}]"
        for a in content_articles
    )

    # Combine article texts (truncated to stay within context)
    combined = "\n\n---\n\n".join(
        f"# {a['frontmatter'].get('title', str(a['rel_path']))}\n{a['text'][:3000]}"
        for a in content_articles[:20]
    )

    prompt = load_agent_prompt(framework_path, "model-builder")
    user_input = (
        f"Model type requested: {model_type}\n\n"
        f"Available articles:\n{titles_list}\n\n"
        f"Article content:\n{combined}"
    )

    result = enrich_call("model", prompt, user_input, _enrich(kb_root), label=f"model:{model_type}")
    result = _sanitize_links(result, _link_resolver(kb_root))

    out_path = kb_root / "docs" / "models" / f"{model_type}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fm = (
        f"---\ntitle: {model_type.replace('-', ' ').title()}\n"
        f"content_type: model\ngenerated: true\n"
        f"date_updated: {datetime.date.today().isoformat()}\n---\n\n"
    )
    out_path.write_text(fm + result, encoding="utf-8")
    print(f"Model written to {out_path}")


def build_cross_ref(kb_root: Path):
    docs_path = kb_root / "docs"
    articles  = load_articles(docs_path)

    rows = []
    for a in articles:
        fm = a["frontmatter"]
        if not fm:
            continue
        title   = fm.get("title", a["rel_path"].as_posix())
        domains = ", ".join(fm.get("domain", []))
        sdgs    = ", ".join(fm.get("sdg", []))
        topics  = ", ".join(fm.get("topics", [])[:4])
        rows.append(f"| [{title}]({a['rel_path'].as_posix()}) | {domains} | {sdgs} | {topics} |")

    header = (
        "---\ntitle: Cross-Reference Matrix\ncontent_type: model\ngenerated: true\n"
        f"date_updated: {datetime.date.today().isoformat()}\n---\n\n"
        "# Cross-Reference Matrix\n\n"
        "| Article | Domain | SDG | Topics |\n"
        "|---|---|---|---|\n"
    )
    out_path = kb_root / "docs" / "cross-reference-matrix.md"
    out_path.write_text(header + "\n".join(rows), encoding="utf-8")
    print(f"Cross-reference matrix written to {out_path}")


def build_sdg_summary(kb_root: Path):
    """Build a page showing a table with SDGs and their related report pages."""
    docs_path = kb_root / "docs"
    articles  = load_articles(docs_path)

    # Collect articles by SDG
    sdg_to_articles: dict[str, list[tuple[str, str]]] = {}  # sdg -> [(title, rel_path), ...]
    for a in articles:
        fm = a["frontmatter"]
        if not fm:
            continue
        # Only include reports (content_type == "report")
        if fm.get("content_type") != "report":
            continue
        title = fm.get("title", a["rel_path"].as_posix())
        rel_path = a["rel_path"].as_posix()
        sdgs = fm.get("sdg", [])
        if not sdgs:
            sdgs = ["Generic"]
        for sdg in sdgs:
            sdg_to_articles.setdefault(sdg, []).append((title, rel_path))

    # Sort SDGs: Generic last, others by number
    def sdg_sort_key(sdg: str):
        if sdg == "Generic":
            return (1, 0)
        try:
            num = int(sdg.replace("SDG-", "").replace("sdg-", ""))
            return (0, num)
        except ValueError:
            return (0, 999)

    sorted_sdgs = sorted(sdg_to_articles.keys(), key=sdg_sort_key)

    # Render one section per SDG (goal name + bulleted list of related reports).
    # A single mega-row table makes 50+ links unreadable; a section per goal keeps
    # the page scannable and lets each report link render on its own line.
    sections = []
    for sdg in sorted_sdgs:
        articles_list = sorted(sdg_to_articles[sdg], key=lambda x: x[0].lower())
        name = SDG_NAMES.get(sdg, sdg)
        heading = f"## {sdg} — {name}" if name != sdg else f"## {sdg}"
        bullets = "\n".join(
            f"- [{title}]({path})" for title, path in articles_list
        )
        sections.append(
            f"{heading} ({len(articles_list)})\n\n{bullets}\n"
        )

    header = (
        "---\ntitle: SDG Summary\ncontent_type: model\ngenerated: true\n"
        f"date_updated: {datetime.date.today().isoformat()}\n---\n\n"
        "# SDG Summary\n\n"
        "Report pages grouped by the UN Sustainable Development Goals they "
        "touch on. Reports with no SDG tag land under **Generic**.\n\n"
    )
    out_path = kb_root / "docs" / "sdg-summary.md"
    out_path.write_text(header + "\n".join(sections), encoding="utf-8")
    print(f"SDG summary written to {out_path}")


SDG_NAMES = {
    "SDG-1":  "No Poverty",
    "SDG-2":  "Zero Hunger",
    "SDG-3":  "Good Health and Well-being",
    "SDG-4":  "Quality Education",
    "SDG-5":  "Gender Equality",
    "SDG-6":  "Clean Water and Sanitation",
    "SDG-7":  "Affordable and Clean Energy",
    "SDG-8":  "Decent Work and Economic Growth",
    "SDG-9":  "Industry, Innovation and Infrastructure",
    "SDG-10": "Reduced Inequalities",
    "SDG-11": "Sustainable Cities and Communities",
    "SDG-12": "Responsible Consumption and Production",
    "SDG-13": "Climate Action",
    "SDG-14": "Life Below Water",
    "SDG-15": "Life on Land",
    "SDG-16": "Peace, Justice and Strong Institutions",
    "SDG-17": "Partnerships for the Goals",
}


# ── Layer 3: cross-domain synthesis pages ───────────────────────────────────────

def _find_source_article(docs_path: Path, slug: str) -> Path | None:
    """Resolve a synthesis source slug to its domain index.md."""
    for sub in ("standards", "frameworks"):
        candidate = docs_path / sub / slug / "index.md"
        if candidate.exists():
            return candidate
    return None


def build_synthesis(kb_root: Path, framework_path: Path, only_domains: set[str] | None = None):
    docs_path = kb_root / "docs"
    config_file = kb_root / "config" / "synthesis.yaml"
    if not config_file.exists():
        print("No config/synthesis.yaml — skipping synthesis.")
        return []

    topics = yaml.safe_load(config_file.read_text(encoding="utf-8")) or []
    prompt = load_agent_prompt(framework_path, "synthesizer")
    glossary = (docs_path / "glossary.md")
    glossary_text = _strip_frontmatter(glossary.read_text(encoding="utf-8")) if glossary.exists() else ""

    generated = []
    resolver = _link_resolver(kb_root)
    for topic in topics:
        title = topic["title"]
        sources = topic.get("sources", [])
        # When only_domains is set, regenerate a page only if it draws on a
        # changed domain (keeps incremental ingests cheap).
        if only_domains is not None and not (set(sources) & only_domains):
            continue

        source_blocks = []
        for slug in sources:
            art = _find_source_article(docs_path, slug)
            if art is None:
                print(f"  ! synthesis '{title}': source '{slug}' not found, skipping it")
                continue
            body = _strip_frontmatter(art.read_text(encoding="utf-8"))
            source_blocks.append(f"# SOURCE: {slug}\n{body[:6000]}")

        if not source_blocks:
            print(f"  ! synthesis '{title}': no resolvable sources, skipping page")
            continue

        user_input = (
            f"TOPIC TITLE: {title}\n"
            f"THEME: {topic.get('theme', '')}\n"
            f"SOURCE DOMAINS: {', '.join(sources)}\n\n"
            f"=== SOURCE ARTICLES ===\n\n" + "\n\n---\n\n".join(source_blocks) +
            f"\n\n=== GLOSSARY ===\n\n{glossary_text[:6000]}"
        )
        body = enrich_call("synthesis", prompt, user_input, _enrich(kb_root), label="synthesis")
        body = _sanitize_links(body, resolver)

        slug = slugify(title)
        out_path = docs_path / "insights" / f"{slug}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fm = (
            f"---\ntitle: {title}\ncontent_type: synthesis\ngenerated: true\n"
            f"sources: [{', '.join(sources)}]\n"
            f"date_updated: {datetime.date.today().isoformat()}\n---\n\n"
        )
        out_path.write_text(fm + body, encoding="utf-8")
        generated.append((title, f"insights/{slug}.md"))
        print(f"Synthesis written to {out_path}")

    _update_insights_nav(kb_root / "mkdocs.yml", generated)
    return generated


def _update_insights_nav(mkdocs_yml: Path, generated: list[tuple[str, str]]):
    """Ensure an 'Insights' nav section lists the overview plus generated pages."""
    if not mkdocs_yml.exists() or not generated:
        return
    config = mkdocs_yaml.load(mkdocs_yml)
    nav = config.get("nav", [])

    insights = next((i for i in nav if isinstance(i, dict) and "Insights" in i), None)
    if insights is None:
        insights = {"Insights": []}
        nav.append(insights)

    items = [{"Overview": "insights/index.md"}]
    existing = {list(i.values())[0] for i in insights["Insights"] if isinstance(i, dict)}
    for title, rel in generated:
        items.append({title: rel})
    # Preserve any pages already present that this run did not regenerate.
    for i in insights["Insights"]:
        if isinstance(i, dict):
            rel = list(i.values())[0]
            if rel != "insights/index.md" and rel not in {r for _, r in generated}:
                items.append(i)
    insights["Insights"] = items

    config["nav"] = nav
    mkdocs_yml.write_text(mkdocs_yaml.dump(config), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb",           required=True)
    parser.add_argument("--model",        choices=["semantic-model", "concept-map", "ontology"])
    parser.add_argument("--cross-ref",    action="store_true")
    parser.add_argument("--synthesis",    action="store_true")
    parser.add_argument("--catalog",      action="store_true")
    parser.add_argument("--sdg-summary",  action="store_true")
    args = parser.parse_args()

    kb_root = Path(args.kb).resolve()
    usage.configure(kb_root / "logs")
    config  = kb_root / "config" / "kb.yaml"
    kb_cfg  = yaml.safe_load(config.read_text()) if config.exists() else {}
    fw_raw  = kb_cfg.get("framework_path", "framework")
    fw_path = (kb_root / fw_raw).resolve()

    if args.model:
        build_model(kb_root, fw_path, args.model)
    if args.cross_ref:
        build_cross_ref(kb_root)
    if args.synthesis:
        build_synthesis(kb_root, fw_path)
    if args.catalog:
        from catalog import build_catalog
        build_catalog(kb_root)
    if args.sdg_summary:
        build_sdg_summary(kb_root)


if __name__ == "__main__":
    main()
