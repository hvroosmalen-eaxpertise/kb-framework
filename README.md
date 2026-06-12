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

Each agent is a markdown file containing a system prompt used by `pipeline/ingest.py` during ingestion.

| Agent | Purpose |
|---|---|
| [`wikipedia-style.md`](agents/wikipedia-style.md) | Rewrites raw extracted text into a neutral encyclopaedic article |
| [`tagger.md`](agents/tagger.md) | Generates YAML frontmatter (title, domain, content_type, status) |
| [`summarizer.md`](agents/summarizer.md) | Produces a one-paragraph summary for the frontmatter `summary` field |
| [`term-enricher.md`](agents/term-enricher.md) | Extracts domain terms and proposes glossary entries |
| [`cross-ref-finder.md`](agents/cross-ref-finder.md) | Identifies cross-references to other articles in the knowledge base |
| [`model-builder.md`](agents/model-builder.md) | Derives semantic model fragments from article content |
| [`linter.md`](agents/linter.md) | Flags factual contradictions between canonical pages (`lint.py --deep`) |
| [`splitter.md`](agents/splitter.md) | Fans one source across the domains it substantively covers (`bootstrap.py`) |

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
| [`ingest.py`](pipeline/ingest.py) | Process sources (`.pdf` or `.md`) from `pipeline/inbox/` → enriched Markdown in `docs/` |
| [`orchestrate.py`](pipeline/orchestrate.py) | Everyday loop: ingest the inbox, then finalise (regenerate → scaffold → reconcile links → lint → strict build → commit → push) |
| [`finalize.py`](pipeline/finalize.py) | The finalise sequence on its own (no ingest); shared by `orchestrate.py` and `bootstrap.py`. Use `--no-push` to commit for review |
| [`rebuild.py`](pipeline/rebuild.py) | Run `mkdocs build` and optionally commit + push the result |
| [`query.py`](pipeline/query.py) | Regenerate derived artefacts: `--synthesis`, `--cross-ref`, `--model`, `--catalog` |
| [`lint.py`](pipeline/lint.py) | Health-check the KB: orphans, stale/dangling sources, missing cross-refs; `--deep` adds contradiction detection |
| [`bootstrap.py`](pipeline/bootstrap.py) | Build a structured wiki from scratch toward the `mkdocs.yml` nav blueprint (`--clean` for a true reset) |
| [`usage.py`](pipeline/usage.py) | Token-usage accounting for every Claude call; tally a run with `--kb <path>` |
| [`sln_sync.py`](pipeline/sln_sync.py) | Mirror `docs/` into a Visual Studio solution's folders; idempotent, opt-in (no-op without a `.sln`). Runs at the end of `ingest.py` and standalone via `--kb <path>` |

### Ingesting a document

```bash
python pipeline/ingest.py --kb <path-to-kb>             # all .pdf/.md in inbox/
python pipeline/ingest.py --kb <path-to-kb> --file <source>  # one .pdf or .md
```

Requires `ANTHROPIC_API_KEY` in the KB root `.env` file.

Sources can be PDFs or Markdown. **Markdown with its own leading frontmatter is
treated as authored content**: the body is preserved verbatim (no Wikipedia-style
rewrite) and the tagger only fills missing required fields (`content_type`,
`domain`, `status`) — the author wins on every conflict. PDFs, and Markdown
*without* frontmatter, are treated as raw and go through the full rewrite + tag path.

On success the pipeline:
1. Extracts content (PDF → `marker-pdf`/`pypdf`; MD → read verbatim)
2. For raw sources, calls Claude to rewrite the content in Wikipedia style
3. Generates YAML frontmatter via Claude (raw), or fills gaps in authored frontmatter
4. Writes the enriched Markdown to `docs/` in the knowledge base
5. Merges new facts into the canonical domain `index.md` (not a parallel page)
6. Upserts extracted terms into `glossary.md`, kept in alphabetical order (case-insensitive)
7. Regenerates synthesis pages, the cross-reference matrix, and the catalog
8. Runs a warn-only deterministic lint, then commits locally (no push)
9. Moves the source to `pipeline/processed/`

Failed sources move to `pipeline/failed/` with a log entry in `logs/ingestion.log`.

### Rebuilding the site

```bash
python pipeline/rebuild.py --kb <path-to-kb>          # build + git commit + push
python pipeline/rebuild.py --kb <path-to-kb> --no-git  # build only
```

### Token-usage accounting

Every Claude call (`ingest.py`, `query.py`, `bootstrap.py`) records its token usage to
`<kb>/logs/token_usage.jsonl` — one JSON line per call, labelled by stage
(`wikipedia-style`, `splitter`, `domain-merge`, `tagger`, `glossary`, `model:*`,
`synthesis`). Accounting spans subprocesses (`bootstrap.py` spawns `query.py`), so a full
`--clean` run yields one exact, per-stage tally. `bootstrap.py` prints it on completion;
read any log on demand with:

```bash
python pipeline/usage.py --kb <path-to-kb>
```

## Requirements

```bash
pip install anthropic pypdf pyyaml python-dotenv mkdocs mkdocs-material
```

## Using This Framework for a New Knowledge Base

1. Create a new KB directory with the structure expected by `ingest.py`:
   ```
   my-kb/
   ├── config/kb.yaml        # name, framework_path, default_source_body, domains
   ├── docs/                 # MkDocs content root
   ├── pipeline/inbox/       # drop .pdf or .md sources here
   ├── pipeline/processed/
   ├── pipeline/failed/
   ├── logs/
   ├── mkdocs.yml
   └── .env                  # ANTHROPIC_API_KEY=...
   ```
2. Set `framework_path: ../kb-framework` in `config/kb.yaml`.
3. Declare a `domains:` map in `config/kb.yaml` (domain tag → canonical page path), e.g.
   `ESRS: standards/esrs/index.md`. Both `ingest.py` (Layer-1 merge) and `bootstrap.py`
   read it; without it, sources are filed only as standalone reports.
4. Run `python ../kb-framework/pipeline/ingest.py --kb .` to grow the KB one source at a time,
   or `python ../kb-framework/pipeline/bootstrap.py --kb . --clean` to build it from scratch
   toward the `mkdocs.yml` nav blueprint.

## Related

- [EurSuRA-kb](https://github.com/hvroosmalen-eaxpertise/EurSuRA-kb) — the EurSuRA knowledge base built on this framework
