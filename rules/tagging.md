# Tagging Rules

Every article must include YAML frontmatter with the following tags.

## Required Frontmatter

```yaml
---
title: ""
summary: ""           # 2-4 sentence lead, Wikipedia style
source_file: ""       # original PDF filename
source_body: ""       # issuing organisation (e.g. EFRAG, EC, UN)
source_year: 2024
date_added: YYYY-MM-DD
date_updated: YYYY-MM-DD
content_type: ""      # standard | directive | framework | report | term | model
domain: []            # one or more: ESRS | CSRD | EU-Taxonomy | SDG | GRI | TCFD | ISSB
sdg: []               # e.g. [SDG-13, SDG-15] — omit if not applicable
topics: []            # free keywords, lowercase, hyphenated
status: draft         # draft | review | published
---
```

## Content Type Definitions

| Value | Use for |
|---|---|
| `standard` | ESRS topical and cross-cutting standards |
| `directive` | EU directives (CSRD, NFRD, Taxonomy Regulation) |
| `framework` | Voluntary frameworks (GRI, TCFD, ISSB) |
| `report` | Company or sector sustainability reports |
| `term` | Glossary entries |
| `model` | Derived artefacts (semantic model, ontology, concept map) |

## Topic Keywords (starter list — extend as needed)

`climate-change`, `biodiversity`, `water`, `pollution`, `circular-economy`,
`own-workforce`, `value-chain-workers`, `affected-communities`, `consumers`,
`governance`, `double-materiality`, `due-diligence`, `transition-plan`,
`scope-1`, `scope-2`, `scope-3`, `ghg-emissions`, `net-zero`
