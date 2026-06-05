# M:/KnowledgeBase/kb-framework/tests/test_bootstrap.py
from pathlib import Path

import yaml

import ingest


def test_domain_index_path_uses_config_map(tmp_path: Path):
    docs = tmp_path / "docs"
    dmap = {"ESRS": "standards/esrs/index.md", "GRI": "frameworks/gri/index.md"}
    fm = {"content_type": "standard", "domain": ["ESRS"]}
    assert ingest.domain_index_path(docs, fm, dmap) == docs / "standards/esrs/index.md"
    # Non-mergeable type -> None
    assert ingest.domain_index_path(docs, {"content_type": "report", "domain": ["ESRS"]}, dmap) is None
    # Unknown domain -> None
    assert ingest.domain_index_path(docs, {"content_type": "framework", "domain": ["XYZ"]}, dmap) is None
