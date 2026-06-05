# M:/KnowledgeBase/kb-framework/tests/conftest.py
import sys
from pathlib import Path

import pytest

# Make pipeline/ importable as top-level modules (query, catalog, lint).
PIPELINE = Path(__file__).resolve().parents[1] / "pipeline"
sys.path.insert(0, str(PIPELINE))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def tiny_kb(tmp_path: Path) -> Path:
    """A minimal KB: two domain pages, a glossary, an insight with sources."""
    docs = tmp_path / "docs"
    _write(docs / "standards" / "esrs" / "index.md",
           "---\ntitle: ESRS\nsummary: EU reporting standards.\n"
           "content_type: standard\ndomain: [ESRS]\nstatus: published\n"
           "date_updated: 2026-06-01\n---\n\n# ESRS\n\nSee [[Double Materiality]].\n")
    _write(docs / "frameworks" / "tcfd" / "index.md",
           "---\ntitle: TCFD\nsummary: Climate disclosure framework.\n"
           "content_type: framework\ndomain: [TCFD]\nstatus: published\n"
           "date_updated: 2026-06-01\n---\n\n# TCFD\n\nClimate governance and risk.\n")
    _write(docs / "glossary.md",
           "---\ntitle: Glossary\n---\n\n# Glossary\n\n"
           "## Double Materiality\n\nImpact and financial materiality.\n")
    _write(docs / "insights" / "climate.md",
           "---\ntitle: Climate Disclosure\ncontent_type: synthesis\ngenerated: true\n"
           "sources: [esrs, tcfd]\ndate_updated: 2026-06-02\n---\n\n# Climate Disclosure\n\nBody.\n")
    _write(tmp_path / "mkdocs.yml",
           "site_name: Tiny\nnav:\n"
           "  - ESRS: standards/esrs/index.md\n"
           "  - TCFD: frameworks/tcfd/index.md\n"
           "  - Glossary: glossary.md\n"
           "  - Climate: insights/climate.md\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "logs").mkdir()
    return tmp_path
