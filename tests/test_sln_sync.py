# M:/KnowledgeBase/kb-framework/tests/test_sln_sync.py
"""Visual Studio solution sync from the docs/ filesystem.

Regenerates the `docs` subtree of a .sln from disk (deterministic GUIDs,
idempotent) while passing the framework-side projects through verbatim.
"""
from pathlib import Path

import pytest

import sln_sync


FOLDER_TYPE = "{2150E333-8FDC-42A3-9474-1A3956D46DE8}"

# A minimal but representative solution: a top-level items folder, a docs folder
# nested under it with one (flattened) child, and a framework-side folder that
# must survive untouched.
SAMPLE_SLN = """Microsoft Visual Studio Solution File, Format Version 12.00
# Visual Studio Version 18
Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "EurSuRA-kb", "EurSuRA-kb", "{AAAA0000-0000-0000-0000-000000000001}"
	ProjectSection(SolutionItems) = preProject
		README.md = README.md
	EndProjectSection
EndProject
Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "docs", "docs", "{BBBB0000-0000-0000-0000-000000000002}"
	ProjectSection(SolutionItems) = preProject
		docs\\index.md = docs\\index.md
	EndProjectSection
EndProject
Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "standards", "standards", "{CCCC0000-0000-0000-0000-000000000003}"
	ProjectSection(SolutionItems) = preProject
		docs\\standards\\esrs\\index.md = docs\\standards\\esrs\\index.md
	EndProjectSection
EndProject
Project("{2150E333-8FDC-42A3-9474-1A3956D46DE8}") = "kb-framework", "kb-framework", "{DDDD0000-0000-0000-0000-000000000004}"
	ProjectSection(SolutionItems) = preProject
		..\\kb-framework\\README.md = ..\\kb-framework\\README.md
	EndProjectSection
EndProject
Global
	GlobalSection(SolutionProperties) = preSolution
		HideSolutionNode = FALSE
	EndGlobalSection
	GlobalSection(NestedProjects) = preSolution
		{BBBB0000-0000-0000-0000-000000000002} = {AAAA0000-0000-0000-0000-000000000001}
		{CCCC0000-0000-0000-0000-000000000003} = {BBBB0000-0000-0000-0000-000000000002}
	EndGlobalSection
EndGlobal
"""


def _docs_tree(root: Path):
    """A small docs/ tree: loose file + two nested domains + a report year."""
    def w(rel: str):
        p = root / "docs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    w("index.md")
    w("glossary.md")
    w("standards/esrs/index.md")
    w("standards/csrd/index.md")
    w("reports/2026/index.md")
    w("reports/2026/a-new-report.md")
    w("catalog.json")          # non-.md, must be ignored


# ── parsing ──────────────────────────────────────────────────────────────────

def test_parse_projects_and_nesting():
    projects, nesting = sln_sync.parse_sln(SAMPLE_SLN)
    by_name = {p.name: p for p in projects}
    assert set(by_name) == {"EurSuRA-kb", "docs", "standards", "kb-framework"}
    assert by_name["docs"].items == ["docs\\index.md"]
    # nesting maps child GUID -> parent GUID
    assert nesting["{CCCC0000-0000-0000-0000-000000000003}"] == "{BBBB0000-0000-0000-0000-000000000002}"


# ── deterministic GUIDs ──────────────────────────────────────────────────────

def test_folder_guid_is_deterministic_and_path_keyed():
    g1 = sln_sync.folder_guid("docs/standards/esrs")
    g2 = sln_sync.folder_guid("docs/standards/esrs")
    g3 = sln_sync.folder_guid("docs/standards/csrd")
    assert g1 == g2                      # stable across calls
    assert g1 != g3                      # path-keyed
    assert g1.startswith("{") and g1.endswith("}") and g1.upper() == g1


# ── filesystem → solution subtree ────────────────────────────────────────────

def test_build_docs_projects_mirrors_tree(tmp_path: Path):
    _docs_tree(tmp_path)
    parent = "{AAAA0000-0000-0000-0000-000000000001}"
    projects, nesting = sln_sync.build_docs_projects(tmp_path, parent_guid=parent)
    names = {p.name for p in projects}
    assert {"docs", "standards", "esrs", "csrd", "reports", "2026"} <= names

    by_name = {p.name: p for p in projects}
    # index.md is emitted first within a folder
    assert by_name["docs"].items[0] == "docs\\index.md"
    assert "docs\\glossary.md" in by_name["docs"].items
    assert "docs\\catalog.json" not in " ".join(by_name["docs"].items)   # non-.md ignored
    assert by_name["2026"].items[0] == "docs\\reports\\2026\\index.md"
    assert "docs\\reports\\2026\\a-new-report.md" in by_name["2026"].items

    # docs root nested under the supplied parent; esrs nested under standards
    assert nesting[sln_sync.folder_guid("docs")] == parent
    assert nesting[sln_sync.folder_guid("docs/standards/esrs")] == sln_sync.folder_guid("docs/standards")


# ── full sync: idempotency + preservation + new content ──────────────────────

def _setup_kb(tmp_path: Path) -> Path:
    (tmp_path / "EurSuRA-kb.sln").write_text(SAMPLE_SLN, encoding="utf-8")
    _docs_tree(tmp_path)
    return tmp_path / "EurSuRA-kb.sln"


def test_sync_solution_is_idempotent(tmp_path: Path):
    sln = _setup_kb(tmp_path)
    assert sln_sync.sync_solution(tmp_path) is True
    first = sln.read_text(encoding="utf-8")
    assert sln_sync.sync_solution(tmp_path) is True
    assert sln.read_text(encoding="utf-8") == first      # byte-identical second run


def test_sync_solution_preserves_framework_side(tmp_path: Path):
    sln = _setup_kb(tmp_path)
    sln_sync.sync_solution(tmp_path)
    text = sln.read_text(encoding="utf-8")
    # framework-side project + its GUID survive verbatim
    assert '"kb-framework", "kb-framework", "{DDDD0000-0000-0000-0000-000000000004}"' in text
    assert "..\\kb-framework\\README.md = ..\\kb-framework\\README.md" in text
    # top-level items folder survives
    assert '"EurSuRA-kb", "EurSuRA-kb", "{AAAA0000-0000-0000-0000-000000000001}"' in text


def test_sync_solution_adds_new_pages_and_nests_domains(tmp_path: Path):
    sln = _setup_kb(tmp_path)
    sln_sync.sync_solution(tmp_path)
    text = sln.read_text(encoding="utf-8")
    # the new report page that was never in the .sln is now present
    assert "docs\\reports\\2026\\a-new-report.md" in text
    # per-domain folders are now nested (esrs + csrd both exist as their own folders)
    assert '"esrs", "esrs"' in text
    assert '"csrd", "csrd"' in text
    # docs root still nested under the preserved top-level folder
    assert (sln_sync.folder_guid("docs") + " = {AAAA0000-0000-0000-0000-000000000001}") in text


def test_sync_solution_no_sln_is_noop(tmp_path: Path):
    _docs_tree(tmp_path)
    assert sln_sync.sync_solution(tmp_path) is False


def test_find_solution_raises_on_ambiguous(tmp_path: Path):
    (tmp_path / "a.sln").write_text(SAMPLE_SLN, encoding="utf-8")
    (tmp_path / "b.sln").write_text(SAMPLE_SLN, encoding="utf-8")
    with pytest.raises(Exception):
        sln_sync.find_solution(tmp_path)
