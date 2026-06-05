# KB Schema Overview

The "schema layer" for every knowledge base built on this framework. It is the
one place that names the structure all KBs share; instances point here rather
than copying it.

## The three layers
1. **Domain layer** - canonical `standards/<slug>/index.md` and
   `frameworks/<slug>/index.md`. New facts are *merged* into these pages, not
   added as parallel summaries.
2. **Shared graph** - the single `glossary.md`. Terms are upserted; domain pages
   reference them via `[[wikilinks]]` and never redefine them.
3. **Synthesis layer** - regenerated artefacts (`insights/*`,
   `cross-reference-matrix.md`, `models/*`, `catalog.*`). All carry
   `generated: true` and must not be hand-edited.

## Frontmatter
Required: `title`. Common: `summary`, `content_type`
(`standard|directive|framework|term|model|report|synthesis`), `domain` (list),
`status` (`draft|review|published`). Generated pages add `generated: true` and
`date_updated`. See per-type schemas: `standard.yaml`, `report.yaml`, `term.yaml`.

## Operations
- **ingest** (`pipeline/ingest.py`) - PDF -> enriched page -> merge -> regenerate
  synthesis, cross-ref, catalog -> warn-only lint -> local commit.
- **query** (`pipeline/query.py`) - `--synthesis`, `--cross-ref`, `--model`,
  `--catalog`.
- **lint** (`pipeline/lint.py`) - deterministic checks (CI gate) + `--deep`
  contradiction check. Enforces `rules/quality-checklist.md`.

## Rules
Editorial rules in `rules/` are authoritative: `writing-style.md`, `tagging.md`,
`term-definition.md`, `cross-referencing.md`, `quality-checklist.md`.
