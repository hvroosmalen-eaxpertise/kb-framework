# Design: Visual Studio solution sync

- **Status:** approved, pending implementation
- **Date:** 2026-06-11
- **Scope:** new `kb-framework/pipeline/sln_sync.py`; one wiring line in `ingest.py`
- **Tracks:** EurSuRA-kb — keep `EurSuRA-kb.sln` in step with `docs/` as sources are ingested

## Problem

The VS solution lists `docs/` content as Solution Items grouped into solution
folders. As sources are ingested (or files are added by hand), new pages under
`docs/` do not appear in the solution until someone edits the `.sln` manually.
The solution's docs view should be regenerated from the filesystem so it never
drifts.

Lands in **kb-framework** (the shared engine) but is **opt-in**: it runs only when
a `.sln` exists in the KB root, so KBs that don't use Visual Studio are unaffected.

## Decisions (from brainstorming)

- **Full mirror:** every `docs/**/*.md` is represented.
- **Both triggers:** a step at the end of `ingest.py`, and a standalone command.
- **Approach A:** regenerate the docs subtree, preserve everything else.

## Design

### Two regions of the `.sln`

- **docs side** — the `docs` solution folder and every folder nested under it
  (`standards`, `frameworks`, `models`, `reports/<year>`, …). This is regenerated.
- **framework side** — the top-level `EurSuRA-kb` items folder (`.gitignore`,
  `CHANGELOG.md`, `hooks.py`, `config/kb.yaml`, `mkdocs.yml`, `README.md`) and the
  `kb-framework` folder with `pipeline`/`agents`/`rules`/`schemas`. Passed through
  **verbatim**, including hand-curation (e.g. only 3 of 6 pipeline scripts listed).

### Module

`kb-framework/pipeline/sln_sync.py`, primary entry `sync_solution(kb_root: Path) -> bool`.
Returns True if a solution was written, False if no `.sln` was found (no-op).

`find_solution(kb_root)` globs `kb_root/*.sln`: exactly one → use it; none → return
None (no-op); more than one → raise (ambiguous).

### Recursive filesystem → solution mapping

Walk `docs/`:
- **each directory → a solution folder** (project type `{2150E333-8FDC-42A3-9474-1A3956D46DE8}`),
- **each `*.md` file → a SolutionItem** (`docs\rel\path.md = docs\rel\path.md`, backslashes),
- **each subdirectory → a nested solution folder** (child in `NestedProjects`).

So `docs/standards/esrs/index.md` becomes `docs ▸ standards ▸ esrs ▸ index.md`.
Per-domain folders that are currently flattened become nested (faithful to the
tree). Generated pages (`insights/`, `catalog.md`, `cross-reference-matrix.md`,
`models/`) are included; non-`.md` files (e.g. `catalog.json`) are not.

Within a folder, `index.md` is emitted first, then the rest sorted; subfolders
sorted by name. Empty directories (no `.md` anywhere beneath) are skipped.

### Deterministic GUIDs

Each solution folder's GUID = `uuid5(NAMESPACE, relpath_posix)` where `relpath_posix`
is the folder path relative to the KB root using forward slashes (e.g.
`docs/standards/esrs`), and `NAMESPACE` is a fixed module-level UUID constant.
Formatted uppercase, brace-wrapped. Consequence: **idempotent** — an unchanged tree
regenerates byte-identical output, so re-running yields a clean git diff. One-time
cost: existing docs-folder GUIDs change on the first run, so VS forgets their
expand/collapse state once (all folders and files are preserved, just re-keyed).

### Parse / regenerate / emit

1. Read `.sln` text.
2. Parse `Project(...) = ... EndProject` blocks → `(type, name, path, guid, items)`.
3. Parse the `GlobalSection(NestedProjects)` map child→parent.
4. Identify the docs root: the solution folder named `docs`. Record its current
   parent GUID (the `EurSuRA-kb` folder) to preserve nesting. If absent, create
   `docs` as a top-level folder (no parent).
5. Compute the docs subtree = docs root + all transitive descendants; drop those
   projects and their `NestedProjects` entries.
6. Build the fresh docs subtree from the filesystem (deterministic GUIDs); docs
   root re-uses the recorded parent.
7. Re-emit: non-docs projects unchanged, then the regenerated docs projects;
   `NestedProjects` = preserved non-docs entries + regenerated docs entries. All
   other global sections pass through unchanged. Header/`Global` framing preserved.

### Triggers

- **Ingest step:** in `ingest.py main()`, after `rebuild.py`, call
  `sync_solution(kb_root)` guarded so a missing `.sln` (or any error) only warns —
  never fails an ingest. Newly written pages appear in the solution automatically.
- **Standalone:** `python ../kb-framework/pipeline/sln_sync.py --kb .`, with a
  `main()` that prints the solution written or "no .sln found".

### Edge cases

| Case | Handling |
|------|----------|
| No `.sln` in KB root | `sync_solution` returns False; ingest step is a silent no-op. |
| Multiple `.sln` | `find_solution` raises (ambiguous); caller in ingest logs a warning and skips. |
| `.sln` has no `docs` folder | Create `docs` as a top-level solution folder, then populate. |
| `docs/` empty / missing | Emit an empty `docs` folder (no items); preserve the rest. |
| Backslash vs forward slash | Solution paths use backslashes; GUID input uses forward slashes (stable across OSes). |

### Testing (TDD, no live calls)

- **parse**: a sample `.sln` → expected projects + nesting map.
- **build subtree**: a temp `docs/` tree → expected folder/item blocks with the
  deterministic GUIDs; `index.md` ordered first.
- **idempotency**: `sync_solution` twice → identical file bytes.
- **preservation**: framework-side projects and top-level items unchanged after sync.
- **integration**: sync a fixture `.sln` against a fixture `docs/` and assert the
  new tree (incl. a freshly added report) is present and correctly nested.

## Scope boundary

- **In:** `pipeline/sln_sync.py`, one guarded call in `ingest.py main()`.
- **Out:** non-`.md` files, the framework-side folders, `.sln` build configurations
  or any global section other than `NestedProjects`, and `.csproj`/MSBuild concerns.
