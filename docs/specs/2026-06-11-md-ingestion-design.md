# Design: Markdown source ingestion

- **Status:** approved, pending implementation
- **Date:** 2026-06-11
- **Scope:** `kb-framework/pipeline/ingest.py`
- **Tracks:** EurSuRA-kb issue #7 ("Ingesting of MD files")

## Problem

Some sources that belong in a KB wiki arrive as Markdown rather than PDF. The
ingestion pipeline (`pipeline/ingest.py`) is entirely PDF-centric: the inbox glob
and `--file` are hardcoded to `*.pdf`, and `extract_markdown()` shells out to
`marker_single`/`pypdf`. MD sources must be ingestible through the same pipeline.

This lands in **kb-framework**, not EurSuRA-kb: `ingest.py` is the shared engine,
and MD ingestion is a generic capability every KB on the framework benefits from.

## Key insight

MD sources are a mix: some are raw, unstructured material (treat like a PDF), and
some are already authored, wiki-quality pages (possibly carrying their own
frontmatter). The signal that distinguishes them is **the presence of leading YAML
frontmatter**. No new config key or directive is introduced.

Crucially, *whether a page merges into a canonical domain page or lands standalone
is already decided by `content_type`*, not by source format. So "raw vs authored"
collapses to a single, narrow fork around the extraction + frontmatter step; the
entire downstream (domain-merge, glossary, nav, changelog, move-to-processed) is
shared and untouched.

## Design

### 1. Format dispatch (extraction layer)

New `extract_content(path: Path) -> str` replaces the direct `extract_markdown()`
call inside ingestion:

| Extension | Behavior |
|-----------|----------|
| `.pdf` | `extract_markdown(path)` — existing marker_single / pypdf path, unchanged |
| `.md` | `path.read_text(encoding="utf-8")` — the bytes *are* the content |
| other | `raise RuntimeError(...)` → routed to `failed/` |

`extract_markdown()` stays PDF-only.

### 2. Source discovery (entry point)

- Inbox glob picks up both: `sorted([*inbox.glob("*.pdf"), *inbox.glob("*.md")])`.
- `--file` already accepts an arbitrary path; extension-based dispatch makes it
  work for `.md` with no further change.
- `ingest_pdf()` → renamed `ingest_source()`; internal `pdf_path`/`pdf_name`
  locals → `src_path`/`src_name`. Pure rename, signature otherwise unchanged.

### 3. The raw-vs-authored fork

Immediately after extraction, split frontmatter using the existing
`split_frontmatter()`:

```python
existing_fm, body = split_frontmatter(raw_content)
authored = bool(existing_fm)   # leading --- block present and non-empty
```

**Raw path (`authored == False`)** — unchanged from today:
- `article_md = call_claude(wikipedia-style, ...)`
- `frontmatter = call_claude(tagger, ...)` — full generation.

**Authored path (`authored == True`)** — new:
- `article_md = body` — no wikipedia-style rewrite call (the body is already
  wiki-quality; this also saves one Claude call).
- Frontmatter = author's fields with gaps filled. Required fields =
  `{content_type, domain, status}` (the minimum downstream routing + lint need).
  - All present → **skip the tagger call** (zero Claude cost).
  - Any missing → call tagger, then `frontmatter = {**tagger_out, **existing_fm}`
    so the **author always wins** on conflicts.

### 4. Shared overrides (both paths)

After frontmatter is set:

```python
frontmatter.setdefault("date_added", today)   # preserve author's if supplied (edge e)
frontmatter["date_updated"] = today
frontmatter["source_file"]  = src_path.name
```

### 5. Downstream — untouched

`determine_output_path`, `domain_index_path`, `merge_into_domain`,
`merge_frontmatter`, `enrich_glossary`, `_update_nav`, `_append_changelog`, and the
move-to-`processed/` step all operate on `(article_md, frontmatter)` and are
origin-agnostic. An authored ESRS page folds into `standards/esrs/index.md` exactly
like a PDF-derived one; an authored report lands standalone. This is why the fork
is ~15 lines.

### 6. Edge cases

| # | Case | Handling |
|---|------|----------|
| a | `.md` with malformed YAML frontmatter | `split_frontmatter` uses `yaml.safe_load`; wrap so a YAML error → treat as **raw** (no frontmatter) and log `WARN MALFORMED_FM`. Do not crash to `failed/`. |
| b | `.md` with frontmatter but empty body | Authored path, `article_md = ""`. Glossary/merge on empty is harmless; log `WARN EMPTY_BODY`. |
| c | Authored frontmatter missing all required fields | Tagger fills them; author wins on whatever it did supply. |
| d | Frontmatter present, `content_type` not mergeable (e.g. `report`) | Standalone write via `determine_output_path` — existing logic. |
| e | Author supplied `date_added` | Preserve it; only default when absent. `date_updated` always today. |
| f | `.md` filename collides with an existing page | Same as PDF today (merge or overwrite per `content_type`) — out of scope. |

### 7. Scope boundary

- **In:** `pipeline/ingest.py` only. No schema changes, no new agents, no config keys.
- **Out:** EurSuRA-kb issue #4 (manually-changed-page protection), bulk re-ingest,
  MD with embedded images/assets. The explicit `ingest:` directive idea is
  deliberately not built — frontmatter presence is the sole signal.

### 8. Testing

- **Unit:** `extract_content` dispatch (3 extensions); `authored` detection on
  no-fm / valid-fm / malformed-fm fixtures; gap-fill precedence (author wins).
- **Integration (no live Claude):** a frontmatter-complete authored `.md` through
  `ingest_source` with `call_claude` monkeypatched — assert **zero** Claude calls,
  body preserved verbatim, correct target path.

## Decisions beyond the raw selections

- **(e)** Preserve an author-supplied `date_added` rather than stomping it.
- **Skip-tagger-when-complete:** no Claude call when authored frontmatter already
  has the required fields. Reduces cost and surprise for authored pages.
