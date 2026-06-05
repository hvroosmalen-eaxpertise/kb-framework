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


def test_catalog_md_groups_by_type_and_has_banner(tiny_kb: Path):
    build_catalog(tiny_kb)
    md = (tiny_kb / "docs" / "catalog.md").read_text(encoding="utf-8")
    assert "generated: true" in md           # frontmatter triggers the banner
    assert "## standard" in md and "## framework" in md
    assert "[ESRS](standards/esrs/index.md)" in md   # md uses repo-relative path
    assert "*(generated)*" in md             # the insight page is flagged


import subprocess, sys, json as _json
from pathlib import Path as _Path

def test_query_catalog_flag_runs(tiny_kb: _Path):
    pipeline = _Path(__file__).resolve().parents[1] / "pipeline"
    (tiny_kb / "config" / "kb.yaml").write_text(
        "name: tiny\nframework_path: ..\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(pipeline / "query.py"),
                        "--kb", str(tiny_kb), "--catalog"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tiny_kb / "docs" / "catalog.json").exists()
