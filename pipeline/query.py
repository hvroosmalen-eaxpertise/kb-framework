"""
Query the knowledge base content and generate derived artefacts.

Usage:
    python query.py --kb <path> --model semantic-model
    python query.py --kb <path> --model concept-map
    python query.py --kb <path> --model ontology
    python query.py --kb <path> --cross-ref   # regenerate cross-reference matrix
"""

import argparse
import datetime
from pathlib import Path

import anthropic
import yaml


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
    import re
    match = re.search(r"```\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text


def call_claude(system_prompt: str, user_content: str, model="claude-sonnet-4-6") -> str:
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}]
    )
    return message.content[0].text


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

    result = call_claude(prompt, user_input)

    out_path = kb_root / "docs" / "models" / f"{model_type}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fm = (
        f"---\ntitle: {model_type.replace('-', ' ').title()}\n"
        f"content_type: model\ndate_updated: {datetime.date.today().isoformat()}\n---\n\n"
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
        title   = fm.get("title", str(a["rel_path"]))
        domains = ", ".join(fm.get("domain", []))
        sdgs    = ", ".join(fm.get("sdg", []))
        topics  = ", ".join(fm.get("topics", [])[:4])
        rows.append(f"| [{title}]({a['rel_path']}) | {domains} | {sdgs} | {topics} |")

    header = (
        "---\ntitle: Cross-Reference Matrix\ncontent_type: model\n"
        f"date_updated: {datetime.date.today().isoformat()}\n---\n\n"
        "# Cross-Reference Matrix\n\n"
        "| Article | Domain | SDG | Topics |\n"
        "|---|---|---|---|\n"
    )
    out_path = kb_root / "docs" / "cross-reference-matrix.md"
    out_path.write_text(header + "\n".join(rows), encoding="utf-8")
    print(f"Cross-reference matrix written to {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb",        required=True)
    parser.add_argument("--model",     choices=["semantic-model", "concept-map", "ontology"])
    parser.add_argument("--cross-ref", action="store_true")
    args = parser.parse_args()

    kb_root = Path(args.kb).resolve()
    config  = kb_root / "config" / "kb.yaml"
    kb_cfg  = yaml.safe_load(config.read_text()) if config.exists() else {}
    fw_raw  = kb_cfg.get("framework_path", "framework")
    fw_path = (kb_root / fw_raw).resolve()

    if args.model:
        build_model(kb_root, fw_path, args.model)
    if args.cross_ref:
        build_cross_ref(kb_root)


if __name__ == "__main__":
    main()
