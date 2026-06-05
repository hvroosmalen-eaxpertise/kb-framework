"""Lint the knowledge base: a checker, not a generator.

Automated enforcement of kb-framework/rules/quality-checklist.md. Deterministic
checks (orphans, stale/dangling sources, missing cross-references) form the CI
gate; the opt-in --deep tier adds an LLM contradiction check.

Exit code: 0 if no hard failures, 1 otherwise (hard set comes from config).
"""

import re
from pathlib import Path

from query import load_articles, call_claude, load_agent_prompt, _strip_frontmatter

Finding = tuple[str, str, str]  # (kind, path, detail)

WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")
HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*#*$", re.MULTILINE)
CONTRA_RE = re.compile(r"^CONTRADICTION\s+(.+?)\s+vs\s+(.+?):\s*(.+)$", re.MULTILINE)
DEFAULT_HARD_FAIL = ["ORPHAN", "STALE"]


def load(kb_root: Path) -> list[dict]:
    return load_articles(kb_root / "docs")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _domain_slug_exists(docs_path: Path, slug: str) -> bool:
    return any((docs_path / sub / slug / "index.md").exists()
               for sub in ("standards", "frameworks"))


def check_dangling_sources(articles: list[dict]) -> list[Finding]:
    if not articles:
        return []
    docs_path = articles[0]["path"].parents[len(articles[0]["rel_path"].parts) - 1]
    findings: list[Finding] = []
    for a in articles:
        rel = a["rel_path"].as_posix()
        for slug in (a["frontmatter"] or {}).get("sources", []) or []:
            if not _domain_slug_exists(docs_path, slug):
                findings.append(("STALE", rel, f"source '{slug}' not found"))
    return findings


def _date(fm: dict) -> str:
    return str(fm.get("date_updated", "")) if fm else ""


def check_stale(articles: list[dict]) -> list[Finding]:
    by_slug: dict[str, str] = {}
    for a in articles:
        parts = a["rel_path"].parts
        if len(parts) == 3 and parts[0] in ("standards", "frameworks") and parts[2] == "index.md":
            by_slug[parts[1]] = _date(a["frontmatter"])
    findings: list[Finding] = []
    for a in articles:
        fm = a["frontmatter"] or {}
        own = _date(fm)
        if not own:
            continue
        for slug in fm.get("sources", []) or []:
            src = by_slug.get(slug, "")
            if src and src > own:
                findings.append(("STALE", a["rel_path"].as_posix(),
                                 f"source '{slug}' ({src}) is newer than this page ({own})"))
    return findings


def _referenced_pages(articles: list[dict]) -> set[str]:
    """rel_paths reachable as the target of some [[wikilink]] (title or glossary term)."""
    title_to_path: dict[str, str] = {}
    glossary_rel: str | None = None
    glossary_terms: set[str] = set()
    for a in articles:
        rel = a["rel_path"].as_posix()
        title = _norm(str((a["frontmatter"] or {}).get("title", "")))
        if title:
            title_to_path.setdefault(title, rel)
        if rel == "glossary.md":
            glossary_rel = rel
            for h in HEADING_RE.findall(a["text"]):
                if _norm(h) != "glossary":
                    glossary_terms.add(_norm(h))

    referenced: set[str] = set()
    for a in articles:
        for m in WIKILINK_RE.finditer(a["text"]):
            key = _norm(m.group(1))
            if key in title_to_path:
                referenced.add(title_to_path[key])
            elif glossary_rel and key in glossary_terms:
                referenced.add(glossary_rel)
    return referenced


def check_orphans(articles: list[dict], nav_paths: set[str]) -> list[Finding]:
    referenced = _referenced_pages(articles)
    findings: list[Finding] = []
    for a in articles:
        fm = a["frontmatter"] or {}
        rel = a["rel_path"].as_posix()
        if rel == "index.md" or fm.get("orphan_ok"):
            continue
        if rel in nav_paths or rel in referenced:
            continue
        findings.append(("ORPHAN", rel, "not in nav and not referenced by any wikilink"))
    return findings


def nav_paths_from_mkdocs(kb_root: Path) -> set[str]:
    import yaml
    mk = kb_root / "mkdocs.yml"
    if not mk.exists():
        return set()
    cfg = yaml.safe_load(mk.read_text(encoding="utf-8")) or {}
    found: set[str] = set()

    def walk(node):
        if isinstance(node, str):
            found.add(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(cfg.get("nav", []))
    return found


def _glossary_terms(articles: list[dict]) -> list[str]:
    for a in articles:
        if a["rel_path"].as_posix() == "glossary.md":
            terms = [h.strip() for h in HEADING_RE.findall(a["text"])]
            return [t for t in terms if _norm(t) != "glossary"]
    return []


def check_missing_xrefs(articles: list[dict], ignore: set[str]) -> list[Finding]:
    terms = _glossary_terms(articles)
    findings: list[Finding] = []
    for a in articles:
        rel = a["rel_path"].as_posix()
        if rel == "glossary.md":
            continue
        plain = WIKILINK_RE.sub(" ", a["text"]).lower()
        for term in terms:
            n = _norm(term)
            if n in ignore:
                continue
            if re.search(rf"\b{re.escape(n)}\b", plain):
                findings.append(("XREF", rel, f"mentions '{term}' without a [[wikilink]]"))
    return findings


def run_deterministic(kb_root: Path, config: dict) -> tuple[list[Finding], bool]:
    lint_cfg = (config or {}).get("lint", {}) or {}
    hard_kinds = set(lint_cfg.get("hard_fail", DEFAULT_HARD_FAIL))
    ignore = {_norm(t) for t in lint_cfg.get("ignore_terms", [])}

    articles = load(kb_root)
    nav = nav_paths_from_mkdocs(kb_root)
    findings: list[Finding] = []
    findings += check_orphans(articles, nav)
    findings += check_dangling_sources(articles)
    findings += check_stale(articles)
    findings += check_missing_xrefs(articles, ignore)

    lines = [f"{k}\t{p}\t{d}" for k, p, d in findings]
    log_dir = kb_root / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "lint.log").write_text("\n".join(lines) + ("\n" if lines else ""),
                                      encoding="utf-8")

    hard_failed = any(k in hard_kinds for k, _, _ in findings)
    counts: dict[str, int] = {}
    for k, _, _ in findings:
        counts[k] = counts.get(k, 0) + 1
    summary = ", ".join(f"{k}={counts[k]}" for k in sorted(counts)) or "no findings"
    print(f"lint: {summary} | hard_fail={'YES' if hard_failed else 'no'}")
    return findings, hard_failed


def run_deep(kb_root: Path, config: dict) -> list[Finding]:
    articles = load(kb_root)
    fw_raw = (config or {}).get("framework_path", "../kb-framework")
    fw_path = (kb_root / fw_raw).resolve()
    prompt = load_agent_prompt(fw_path, "linter")

    canon = [a for a in articles
             if a["rel_path"].parts[0] in ("standards", "frameworks")
             and a["rel_path"].name == "index.md"]
    blocks = "\n\n---\n\n".join(
        f"# PAGE: {a['rel_path'].as_posix()}\n{_strip_frontmatter(a['text'])[:4000]}"
        for a in canon)
    reply = call_claude(prompt, blocks)

    findings: list[Finding] = []
    for m in CONTRA_RE.finditer(reply):
        findings.append(("CONTRADICTION", f"{m.group(1)} vs {m.group(2)}", m.group(3).strip()))
    return findings


def main() -> int:
    import argparse
    import yaml
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", required=True)
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args()

    kb_root = Path(args.kb).resolve()
    cfg_file = kb_root / "config" / "kb.yaml"
    config = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}

    findings, hard_failed = run_deterministic(kb_root, config or {})
    if args.deep:
        deep = run_deep(kb_root, config or {})
        for k, p, d in deep:
            print(f"  {k}\t{p}\t{d}")
    return 1 if hard_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
