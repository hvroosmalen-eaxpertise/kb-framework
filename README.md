# kb-framework

Shared framework for EAXpertise knowledge bases. Contains the rules, schemas, agent prompts, and pipeline scripts that drive content ingestion and quality for any knowledge base built on this framework — currently used by [EurSuRA-kb](../EurSuRA-kb).

## Structure

```
kb-framework/
├── agents/       Claude agent prompts for each enrichment step
├── rules/        Editorial rules for human and agent authors
├── schemas/      YAML frontmatter schemas for each content type
└── pipeline/     Python scripts for ingestion, querying and rebuilding
```

## Agents

Each agent is a markdown file containing a system prompt used by `pipeline/ingest.py` during PDF ingestion.

| Agent | Purpose |
|---|---|
| [`wikipedia-style.md`](agents/wikipedia-style.md) | Rewrites raw extracted text into a neutral encyclopaedic article |
| [`tagger.md`](agents/tagger.md) | Generates YAML frontmatter (title, domain, content_type, status) |
| [`summarizer.md`](agents/summarizer.md) | Produces a one-paragraph summary for the frontmatter `summary` field |
| [`term-enricher.md`](agents/term-enricher.md) | Extracts domain terms and proposes glossary entries |
| [`cross-ref-finder.md`](agents/cross-ref-finder.md) | Identifies cross-references to other articles in the knowledge base |
| [`model-builder.md`](agents/model-builder.md) | Derives semantic model fragments from article content |
| [`linter.md`](agents/linter.md) | Flags factual contradictions between canonical pages (`lint.py --deep`) |

## Rules

Editorial rules enforced by agents and human authors alike.

| Rule file | Covers |
|---|---|
| [`writing-style.md`](rules/writing-style.md) | Wikipedia NPOV style, article structure, language rules |
| [`tagging.md`](rules/tagging.md) | How to assign `domain`, `content_type`, and `status` tags |
| [`term-definition.md`](rules/term-definition.md) | How to write glossary entries (definition, synonyms, related terms) |
| [`cross-referencing.md`](rules/cross-referencing.md) | When and how to add `[[wikilinks]]` to other articles |
| [`quality-checklist.md`](rules/quality-checklist.md) | Pre-publish checklist — completeness, citations, links |

## Schemas

YAML frontmatter schemas defining required and optional fields per content type.

See [`schemas/README.md`](schemas/README.md) for the schema overview (the three layers, frontmatter, operations).

| Schema | Content type |
|---|---|
| [`standard.yaml`](schemas/standard.yaml) | Mandatory standards and directives (ESRS, CSRD, EU Taxonomy) |
| [`report.yaml`](schemas/report.yaml) | Ingested source documents and sustainability reports |
| [`term.yaml`](schemas/term.yaml) | Glossary entries |

## Pipeline Scripts

| Script | Usage |
|---|---|
| [`ingest.py`](pipeline/ingest.py) | Process PDFs from `pipeline/inbox/` → enriched Markdown in `docs/` |
| [`rebuild.py`](pipeline/rebuild.py) | Run `mkdocs build` and optionally commit + push the result |
| [`query.py`](pipeline/query.py) | Regenerate derived artefacts: `--synthesis`, `--cross-ref`, `--model`, `--catalog` |
| [`lint.py`](pipeline/lint.py) | Health-check the KB: orphans, stale/dangling sources, missing cross-refs; `--deep` adds contradiction detection |

### Ingesting a document

```bash
python pipeline/ingest.py --kb <path-to-kb>          # all PDFs in inbox/
python pipeline/ingest.py --kb <path-to-kb> --file <pdf>  # one file
```

Requires `ANTHROPIC_API_KEY` in the KB root `.env` file.

On success the pipeline:
1. Extracts text from the PDF (`marker-pdf` if available, else `pypdf`)
2. Calls Claude to rewrite the content in Wikipedia style
3. Calls Claude to generate YAML frontmatter (title, domain, tags)
4. Writes the enriched Markdown to `docs/` in the knowledge base
5. Merges new facts into the canonical domain `index.md` (not a parallel page)
6. Upserts extracted terms into `glossary.md`
7. Regenerates synthesis pages, the cross-reference matrix, and the catalog
8. Runs a warn-only deterministic lint, then commits locally (no push)
9. Moves the PDF to `pipeline/processed/`

Failed PDFs move to `pipeline/failed/` with a log entry in `logs/ingestion.log`.

### Rebuilding the site

```bash
python pipeline/rebuild.py --kb <path-to-kb>          # build + git commit + push
python pipeline/rebuild.py --kb <path-to-kb> --no-git  # build only
```

## Requirements

```bash
pip install anthropic pypdf pyyaml python-dotenv mkdocs mkdocs-material
```

## Using This Framework for a New Knowledge Base

1. Create a new KB directory with the structure expected by `ingest.py`:
   ```
   my-kb/
   ├── config/kb.yaml        # name, framework_path, default_source_body
   ├── docs/                 # MkDocs content root
   ├── pipeline/inbox/       # drop PDFs here
   ├── pipeline/processed/
   ├── pipeline/failed/
   ├── logs/
   ├── mkdocs.yml
   └── .env                  # ANTHROPIC_API_KEY=...
   ```
2. Set `framework_path: ../kb-framework` in `config/kb.yaml`.
3. Run `python ../kb-framework/pipeline/ingest.py --kb .` to ingest your first documents.

## Related

- [EurSuRA-kb](https://github.com/hvroosmalen-eaxpertise/EurSuRA-kb) — the EurSuRA knowledge base built on this framework
