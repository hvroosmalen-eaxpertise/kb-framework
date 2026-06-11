"""
Sync a Visual Studio solution's `docs` subtree with the docs/ filesystem.

Each directory under docs/ becomes a solution folder, each `*.md` a Solution
Item, mirroring the tree. Folder GUIDs are derived from the path so the output
is idempotent (an unchanged tree regenerates byte-identical). The framework-side
projects (and any non-docs project) pass through verbatim.

Usage:
    python sln_sync.py --kb <path-to-kb>     # resync <kb>/<name>.sln from docs/
"""

import re
import sys
import uuid
import argparse
from pathlib import Path
from dataclasses import dataclass, field

# Project type GUID Visual Studio uses for solution folders.
FOLDER_TYPE = "{2150E333-8FDC-42A3-9474-1A3956D46DE8}"

# Fixed namespace so folder_guid() is stable across machines and runs.
NAMESPACE = uuid.UUID("9f2b7c4e-3a51-4d8e-bf06-1c2d3e4f5a6b")

_PROJECT_RE = re.compile(
    r'^Project\("(?P<type>\{[^}]+\})"\) = '
    r'"(?P<name>[^"]*)", "(?P<path>[^"]*)", "(?P<guid>\{[^}]+\})"'
)


@dataclass
class Project:
    type: str
    name: str
    path: str
    guid: str
    items: list = field(default_factory=list)   # left-hand SolutionItems paths


def folder_guid(relpath_posix: str) -> str:
    """Deterministic, path-keyed GUID for a solution folder."""
    return "{" + str(uuid.uuid5(NAMESPACE, relpath_posix)).upper() + "}"


# ── parse ─────────────────────────────────────────────────────────────────────

def parse_sln(text: str):
    """Return (projects, nesting) where nesting maps child GUID → parent GUID."""
    lines = text.splitlines()
    projects, nesting = [], {}
    i, n = 0, len(lines)
    in_nested = False
    while i < n:
        line = lines[i]
        m = _PROJECT_RE.match(line)
        if m:
            items = []
            i += 1
            while i < n and lines[i].strip() != "EndProject":
                s = lines[i].strip()
                if " = " in s and not s.startswith(("ProjectSection", "EndProjectSection")):
                    items.append(s.split(" = ", 1)[0])
                i += 1
            projects.append(Project(m["type"], m["name"], m["path"], m["guid"], items))
            i += 1
            continue
        if line.strip().startswith("GlobalSection(NestedProjects)"):
            in_nested = True
            i += 1
            continue
        if in_nested:
            s = line.strip()
            if s == "EndGlobalSection":
                in_nested = False
            elif " = " in s:
                child, parent = (t.strip() for t in s.split(" = ", 1))
                nesting[child] = parent
        i += 1
    return projects, nesting


def _descendants(root_guid: str, nesting: dict) -> set:
    children = {}
    for child, parent in nesting.items():
        children.setdefault(parent, []).append(child)
    out, stack = set(), list(children.get(root_guid, []))
    while stack:
        g = stack.pop()
        if g in out:
            continue
        out.add(g)
        stack.extend(children.get(g, []))
    return out


# ── filesystem → solution subtree ─────────────────────────────────────────────

def _md_first(name: str):
    return (name.lower() != "index.md", name.lower())


def _has_md(d: Path) -> bool:
    return any(f.suffix == ".md" for f in d.rglob("*.md"))


def build_docs_projects(kb_root: Path, parent_guid):
    """Mirror docs/ into solution folder projects + their nesting."""
    kb_root = Path(kb_root)
    docs = kb_root / "docs"
    projects, nesting = [], {}

    def walk(d: Path, parent):
        relp = d.relative_to(kb_root).as_posix()
        guid = folder_guid(relp)
        mds = sorted((f for f in d.iterdir() if f.is_file() and f.suffix == ".md"),
                     key=lambda f: _md_first(f.name))
        items = [f.relative_to(kb_root).as_posix().replace("/", "\\") for f in mds]
        projects.append(Project(FOLDER_TYPE, d.name, d.name, guid, items))
        nesting[guid] = parent
        for sub in sorted((x for x in d.iterdir() if x.is_dir()), key=lambda x: x.name.lower()):
            if _has_md(sub):
                walk(sub, guid)

    if docs.exists():
        walk(docs, parent_guid)
    return projects, nesting


# ── render ─────────────────────────────────────────────────────────────────────

def render_project(p: Project) -> str:
    out = [f'Project("{p.type}") = "{p.name}", "{p.path}", "{p.guid}"']
    if p.items:
        out.append("\tProjectSection(SolutionItems) = preProject")
        out += [f"\t\t{it} = {it}" for it in p.items]
        out.append("\tEndProjectSection")
    out.append("EndProject")
    return "\n".join(out)


def _render_global(global_lines, nesting: dict) -> str:
    out, i, n = [], 0, len(global_lines)
    seen_nested = False
    while i < n:
        line = global_lines[i]
        if line.strip().startswith("GlobalSection(NestedProjects)"):
            seen_nested = True
            out.append(line)
            out += [f"\t\t{c} = {p}" for c, p in nesting.items()]
            i += 1
            while i < n and global_lines[i].strip() != "EndGlobalSection":
                i += 1
            out.append(global_lines[i])      # the EndGlobalSection
            i += 1
            continue
        if line.strip() == "EndGlobal" and not seen_nested and nesting:
            out.append("\tGlobalSection(NestedProjects) = preSolution")
            out += [f"\t\t{c} = {p}" for c, p in nesting.items()]
            out.append("\tEndGlobalSection")
            seen_nested = True
        out.append(line)
        i += 1
    return "\n".join(out)


def render_sln(original: str, projects, nesting: dict) -> str:
    lines = original.splitlines()
    first_proj = next(i for i, l in enumerate(lines) if l.startswith("Project("))
    global_idx = next(i for i, l in enumerate(lines) if l.strip() == "Global")
    preamble = "\n".join(lines[:first_proj])
    proj_text = "\n".join(render_project(p) for p in projects)
    global_text = _render_global(lines[global_idx:], nesting)
    return f"{preamble}\n{proj_text}\n{global_text}\n"


# ── sync ───────────────────────────────────────────────────────────────────────

def find_solution(kb_root: Path):
    slns = sorted(Path(kb_root).glob("*.sln"))
    if not slns:
        return None
    if len(slns) > 1:
        raise RuntimeError(f"Multiple .sln files in {kb_root}: {[p.name for p in slns]}")
    return slns[0]


def sync_solution(kb_root) -> bool:
    """Regenerate the docs subtree of the KB's solution. False if no .sln."""
    kb_root = Path(kb_root)
    sln = find_solution(kb_root)
    if sln is None:
        return False

    text = sln.read_text(encoding="utf-8")
    projects, nesting = parse_sln(text)

    docs_proj = next((p for p in projects if p.name == "docs" and p.type == FOLDER_TYPE), None)
    docs_parent = nesting.get(docs_proj.guid) if docs_proj else None
    subtree = (_descendants(docs_proj.guid, nesting) | {docs_proj.guid}) if docs_proj else set()

    kept = [p for p in projects if p.guid not in subtree]
    kept_nesting = {c: p for c, p in nesting.items() if c not in subtree and p not in subtree}

    docs_projects, docs_nesting = build_docs_projects(kb_root, docs_parent)

    out = render_sln(text, kept + docs_projects, {**kept_nesting, **docs_nesting})
    sln.write_text(out, encoding="utf-8")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", required=True, help="Path to KB root folder")
    args = parser.parse_args()
    kb_root = Path(args.kb).resolve()
    if sync_solution(kb_root):
        print(f"Solution synced: {find_solution(kb_root).name}")
    else:
        print("No .sln found in KB root — nothing to sync.")


if __name__ == "__main__":
    main()
