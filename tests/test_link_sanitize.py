"""Wikilink sanitization for generated pages (query.py).

Generated pages (models, synthesis) are produced through the KB's enrichment
backends; a local model invents [[links]] more freely than Claude. `_sanitize_links`
demotes any link that would not resolve at build time to plain text, using the same
index the KB's own hooks.py builds. All tests offline — no API calls.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import query  # noqa: E402


HOOKS_PY = '''\
import re
from pathlib import Path
from markdown.extensions.toc import slugify

WIKILINK_RE = re.compile(r"\\[\\[([^\\]|]+?)(?:\\|([^\\]]+))?\\]\\]")
HEADING_RE = re.compile(r"^#{2,3}\\s+(.+?)\\s*#*$", re.MULTILINE)
MANUAL_ALIASES = {"sme": "standards/vsme/index.md"}
KNOWN_EXTERNAL = {"greenwashing"}
RUNTIME_EXTERNAL = set(KNOWN_EXTERNAL)
LINK_INDEX = {}


def _norm(text):
    return re.sub(r"\\s+", " ", text).strip().lower()


def _register(index, key, target):
    index.setdefault(_norm(key), target)


def _read_title(md_text):
    if not md_text.startswith("---"):
        return None
    end = md_text.find("\\n---", 3)
    if end == -1:
        return None
    for line in md_text[3:end].splitlines():
        if line.strip().lower().startswith("title:"):
            return line.split(":", 1)[1].strip().strip("\\"'")
    return None


def _index_titles(index, docs_dir):
    for md in sorted(Path(docs_dir).rglob("*.md")):
        rel = md.relative_to(docs_dir).as_posix()
        title = _read_title(md.read_text(encoding="utf-8"))
        if title:
            _register(index, title, rel)


def _index_glossary(index, docs_dir):
    glossary = Path(docs_dir) / "glossary.md"
    if not glossary.exists():
        return
    for heading in HEADING_RE.findall(glossary.read_text(encoding="utf-8")):
        if heading.strip().lower() != "glossary":
            _register(index, heading, "glossary.md#" + slugify(heading, "-"))


def _index_slugs(index, docs_dir):
    for md in sorted(Path(docs_dir).rglob("*.md")):
        rel = md.relative_to(docs_dir).as_posix()
        slug = md.parent.name if md.name == "index.md" else md.stem
        if slug:
            _register(index, slug, rel)


def _load_known_external(docs_dir):
    return set(KNOWN_EXTERNAL)
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def kb_with_hooks(tmp_path: Path) -> Path:
    _write(tmp_path / "docs" / "standards" / "esrs" / "index.md",
           "---\ntitle: ESRS\n---\n\n# ESRS\n")
    _write(tmp_path / "docs" / "glossary.md",
           "---\ntitle: Glossary\n---\n\n# Glossary\n\n## Double Materiality\n\nImpact.\n")
    _write(tmp_path / "hooks.py", HOOKS_PY)
    return tmp_path


# ── _enrich: loads the KB's enrich config, defaults to all-Claude ─────────────

def test_enrich_absent_config_defaults_all_claude(tmp_path: Path):
    cfg = query._enrich(tmp_path)
    assert all(v == "claude" for v in cfg["tasks"].values())


def test_enrich_reads_kb_config(tmp_path: Path):
    _write(tmp_path / "config" / "kb.yaml",
           "enrich:\n  backends:\n"
           "    ollama: { model: qwen3:8b }\n"
           "  tasks:\n    model: ollama\n")
    cfg = query._enrich(tmp_path)
    assert cfg["tasks"]["model"] == "ollama"
    assert cfg["tasks"].get("synthesis", "claude") == "claude"  # unspecified → default


# ── _link_resolver: loads hooks.py index, None when absent ───────────────────

def test_link_resolver_none_without_hooks(tmp_path: Path):
    assert query._link_resolver(tmp_path) is None


def test_link_resolver_builds_index(kb_with_hooks: Path):
    hooks, index, external = query._link_resolver(kb_with_hooks)
    assert hooks is not None
    assert "esrs" in index          # slug from docs/standards/esrs/index.md
    assert "double materiality" in index  # glossary heading
    assert "sme" in index           # manual alias
    assert "greenwashing" in external


# ── _sanitize_links: keep resolvable, demote invented, no-op without hooks ───

def test_sanitize_keeps_resolvable_and_known_external(kb_with_hooks: Path):
    text = ("See [[ESRS]] and [[Double Materiality]] and [[greenwashing]] "
            "and [[SME|small firms]].")
    out = query._sanitize_links(text, query._link_resolver(kb_with_hooks))
    assert "[[ESRS]]" in out
    assert "[[Double Materiality]]" in out
    assert "[[greenwashing]]" in out
    assert "[[SME|small firms]]" in out


def test_sanitize_demotes_unresolvable(kb_with_hooks: Path):
    text = "Compare [[ESRS]] with [[Made Up Concept]] and [[bogus|alias]]."
    out = query._sanitize_links(text, query._link_resolver(kb_with_hooks))
    assert "[[ESRS]]" in out
    assert "[[Made Up Concept]]" not in out
    assert "Made Up Concept" in out            # plain text, no brackets
    assert "[[bogus|alias]]" not in out
    assert "alias" in out                      # display text kept


def test_sanitize_noop_without_hooks(tmp_path: Path):
    text = "[[Anything]] stays [[Exactly|as-is]]."
    assert query._sanitize_links(text, None) == text
