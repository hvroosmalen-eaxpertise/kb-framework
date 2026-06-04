# Term and Definition Rules

This file specifies how to write a high-quality term entry for the glossary or an article lead.

## Structure of a Term Entry

```markdown
### [Term]

**Definition:** [One sentence, precise and complete, usable without context.]

**Domain:** [e.g. ESRS / CSRD / SDG / GRI / General]

**Synonyms:** [comma-separated, if any]

**Abbreviation:** [if applicable]

**Related terms:** [[Term A]], [[Term B]]

**Source:** [Document title, article/section, year]

> [Optional verbatim quote from source if the definition is normative]
```

## Quality Criteria for a Good Definition

A definition is good when it satisfies all of the following:

1. **Genus + differentia** — States what broader category the term belongs to, then what distinguishes it. Example: "A *double materiality assessment* is a process [genus] that evaluates both the impact of a company on sustainability topics and the financial effects of those topics on the company [differentia]."
2. **Self-contained** — Understandable without reading surrounding text.
3. **Non-circular** — Does not define a term using the term itself.
4. **Normative where possible** — Prefers definitions from official regulatory or standards sources over secondary literature.
5. **Single sense** — If a term has multiple meanings in different contexts, create a separate entry per context with a qualifier: *Materiality (ESRS)* vs *Materiality (accounting)*.
6. **Concise** — One to three sentences maximum for the definition field.

## Enrichment Steps

When processing a term from a source document:

1. Extract the verbatim definition if one is given.
2. Check whether the same term appears in other ingested documents — if so, note differences.
3. Assign domain tag(s).
4. Identify synonyms and abbreviations.
5. Link to at least one related term already in the glossary.
6. Record the source reference.
