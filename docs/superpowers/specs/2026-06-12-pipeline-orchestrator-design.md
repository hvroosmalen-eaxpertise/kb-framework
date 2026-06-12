# Pipeline Orchestrator — Design

**Date:** 2026-06-12
**Status:** approved (pending implementation)
**Repo:** `kb-framework` (shared engine; consumed by `EurSuRA-kb` and other KBs)

## Problem

The everyday `ingest.py` path stops after merging sources into pages. The
*finalising* steps that turn ingested docs into a committed, strict-clean site —
regenerate synthesis/models/catalog, scaffold remaining placeholders, reconcile
wikilinks, lint, strict build, commit — only exist **inline inside
`bootstrap.py`**, which is a from-scratch, PDF-only, destructive path
(`--clean`). Consequences:

- After a normal `.md`/`.pdf` ingest, the operator must remember to run several
  scripts by hand, and nothing enforces a strict-clean result.
- `reconcile_links` (which records external `[[wikilinks]]` so a `--strict`
  build passes) never runs on the everyday path. This is exactly how issue #8
  reached CI: the `.md` ingest of the SCI-for-AI report left unrecorded external
  links and stale glossary anchors that only a strict build would catch.
- "Placeholder page scaffolded by bootstrap" pages persist because nothing
  re-runs `scaffold_missing` / ingest outside a full bootstrap.

A placeholder exists whenever a `mkdocs.yml` nav entry has no source-derived
content. An orchestrator cannot invent content; it can ingest whatever sources
are waiting in the inbox (filling the nav pages their domains map to) and
re-stub the rest. The value is **one command that runs the whole sequence with
fail-fast gates**, shared across every path.

## Approach (chosen: A — extract a shared `finalize` module)

Pull the finalising tail out of `bootstrap.py` into a reusable module, then
expose two thin entry points and refactor bootstrap to reuse it. Rejected
alternatives: (B) a thin shell-out orchestrator that duplicates the sequence and
leaves bootstrap untouched — guarantees drift; (C) a declarative YAML/Makefile
step runner — over-engineered for ~6 fixed steps.

## Module layout (`kb-framework/pipeline/`)

### `finalize.py` (new) — owns the finalising sequence

Public function:

```python
def finalize(kb_root, framework_path, kb_config, *,
             lint=True, deep=False, strict=True,
             commit=True, push=True) -> int
```

Returns a process exit code (0 ok; non-zero on a gate failure). Bodies of
`_regenerate`, `scaffold_missing`, and `reconcile_links` **move here from
`bootstrap.py`** (already self-contained). `rebuild.py`'s commit/push logic is
absorbed here. Has its own `main()` so it is runnable standalone — the
**finalise-only** entry point (run after manual edits, no ingest).

Flags (standalone): `--kb`, `--no-lint`, `--deep`, `--no-strict`, `--no-commit`,
`--no-push`.

### `orchestrate.py` (new) — the everyday loop

Thin entry point: load `.env` + `config/kb.yaml`, init the token tally (reuse
`usage`), run ingest over the whole inbox by subprocess-calling the existing
`ingest.py` (left untouched), then call `finalize(...)`.

Flags: `--kb`, `--file` (single source passthrough), `--no-lint`, `--deep`,
`--no-strict`, `--no-commit`, `--no-push`.

### `bootstrap.py` (refactor, behaviour-preserving)

Its tail (`_regenerate → scaffold_missing → reconcile_links → _rebuild`)
collapses to a single `finalize(..., strict=True, push=False)` call. bootstrap
imports the moved helpers from `finalize`. From-scratch rebuilds stay
review-before-push; only `orchestrate` auto-pushes. The one intentional
behaviour change: bootstrap now runs a **strict** build (previously non-strict
via `rebuild.py`). `reconcile_links` already exists to make that pass; a strict
failure there is a real problem bootstrap should surface.

## Control flow & gates (fail-fast)

`orchestrate.py`:

1. Load env + `config/kb.yaml`; resolve `framework_path`; `usage.configure/reset`.
2. **Ingest** the inbox (PDF + MD) via `ingest.py`. Per-source failures already
   self-isolate to `failed/` and do not abort the batch.
3. **`finalize()`** runs in order:
   1. `_regenerate` — semantic-model, concept-map, ontology, then cross-ref +
      synthesis + catalog (via `query.py` subprocesses, as today).
   2. `scaffold_missing` — re-stub any nav page still without a file.
   3. `reconcile_links` — non-strict build, harvest `unresolved [[wikilink]]`
      warnings, append normalised terms to `config/known_external.txt`.
      **Must run before the strict build.**
   4. **lint gate** — run lint; if `hard_failed` and `lint` enabled, ABORT
      before any commit.
   5. **strict build gate** — `mkdocs build --strict --config-file mkdocs.yml`;
      ABORT on non-zero.
   6. **commit** — stage `docs/ logs/ config/ mkdocs.yml`; if nothing changed,
      report and stop; else commit with a generated message.
   7. **push** — default on for `orchestrate`; `--no-push` holds for review.

Any gate failure prints `ABORT: <step> — <reason>`, exits non-zero, and leaves
**no commit** (gates run before commit). Token usage tally printed at end.

### Defaults summary

| Caller | lint | strict | commit | push |
|---|---|---|---|---|
| `orchestrate.py` (everyday) | on | on | on | **on** (`--no-push` to hold) |
| `finalize.py` (standalone) | on | on | on | on (`--no-push` to hold) |
| `bootstrap.py` (from-scratch) | on | on | on | **off** (review first) |

## Error handling

- Each step logs to `logs/` and prints a one-line reason.
- Gates run before commit → a failed run never leaves a partial commit.
- Ingest is best-effort per source (existing behaviour); the hard gates are lint
  and the strict build.
- Token usage tally printed at the end (reuse `usage.format_tally`).

## Testing (API-free, per the KB verification approach)

No live Claude calls. Cover the finalise half:

- `scaffold_missing`: stubs missing nav pages; never overwrites an existing file.
- `reconcile_links`: tmp KB containing an unresolved `[[link]]` → assert the
  normalised term is appended to `known_external.txt` (and the dedupe/header
  behaviour holds).
- `finalize()` gate logic: monkeypatch lint and/or the strict build to fail →
  assert the run aborts **before** commit (tmp git repo; assert no new commit).
- Smoke test: `python finalize.py --kb <EurSuRA-kb> --no-push` — fully API-free
  (no ingest), exercises regenerate → scaffold → reconcile → lint → strict build
  → local commit.

The LLM/ingest half is not unit-tested here (needs API); validate it with
`--file` on a single small source when an API key is available.

## Out of scope / notes

- Does not fill placeholders that have no source — that requires adding sources
  to the inbox. Orchestrator ingests what is waiting and re-stubs the rest.
- The MD-ingest path's lack of auto-`known_external` recording (issue #8
  follow-up) is closed transitively: `reconcile_links` now runs on every path.
- Update `kb-framework` `CLAUDE.md` / README pipeline section with the two new
  commands in the same change (README-update rule).
