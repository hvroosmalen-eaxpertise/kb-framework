import json
from pathlib import Path

from catalog import build_catalog


def test_catalog_json_has_one_entry_per_page(tiny_kb: Path):
    build_catalog(tiny_kb)
    data = json.loads((tiny_kb / "docs" / "catalog.json").read_text(encoding="utf-8"))
    urls = {e["url"] for e in data}
    # catalog.md/json themselves are excluded; 4 source pages remain.
    assert urls == {"standards/esrs/", "frameworks/tcfd/", "glossary/", "insights/climate/"}


def test_catalog_entry_fields_and_wikilinks(tiny_kb: Path):
    build_catalog(tiny_kb)
    data = json.loads((tiny_kb / "docs" / "catalog.json").read_text(encoding="utf-8"))
    esrs = next(e for e in data if e["url"] == "standards/esrs/")
    assert esrs["title"] == "ESRS"
    assert esrs["summary"] == "EU reporting standards."
    assert esrs["content_type"] == "standard"
    assert esrs["domain"] == ["ESRS"]
    assert esrs["status"] == "published"
    assert esrs["generated"] is False
    assert esrs["wikilinks"] == ["Double Materiality"]
    climate = next(e for e in data if e["url"] == "insights/climate/")
    assert climate["generated"] is True
