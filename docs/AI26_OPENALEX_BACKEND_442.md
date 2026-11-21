# AI26 scholarly strata: the OpenAlex backend (#442)

**Decision, 2026-11-21.** Three declared scholarly strata had no executable backend and
had collected zero records: `left_techno_optimism`, `critical_ai_political_economy` and
`ai_creative_labour` all declare `services = ["openalex", "semantic_scholar", "socArXiv"]`
and the runner answered every attempt with `unsupported_scholarly_backend`.

This records option (a) from #442: give the query a backend it declares. OpenAlex needs no
API key and no new dependency, so the adapter is stdlib HTTP plus the same canonical record
mapping the arXiv adapter uses (`src/laclaugpt_data_collection/collectors/openalex.py`).

## Why the config carries a second query

OpenAlex search is relevance-ranked full text and **does not implement `AND`/`OR`**. Fed the
declared boolean directly, it matches on words alone:

| query | OpenAlex `count` 2026-11-21 |
| --- | ---: |
| `(AI OR automation) AND (post-work OR postcapitalism OR …)` | **1 992 536** |
| `postcapitalism post-work public ownership technological emancipation` | **109** |

The first number is not a sample of a formation; it is most of the literature. So each
stratum now carries `openalex_query` — the executable form — and keeps the original boolean
in `query` as the declared intent. The translation is a sampling decision and therefore lives
in the study config, not in a heuristic inside the code.

| stratum | `openalex_query` | OpenAlex count | first page (measured live) |
| --- | --- | ---: | --- |
| `left_techno_optimism` | postcapitalism post-work public ownership technological emancipation | 109 | 5 records, 1 205–2 491 chars of text |
| `critical_ai_political_economy` | artificial intelligence labour inequality discrimination surveillance ownership | 2 319 | 5 records, 1 361–1 604 chars |
| `ai_creative_labour` | generative AI copyright automation labour artists | 651 | 5 records, 265–1 756 chars |

Every returned record carries a title and a reconstructed abstract
(`abstract_inverted_index` → text), so the AI26 evidence gate has source text to work with. A
work with neither title nor abstract is dropped rather than stored as an uncodeable record.

## What also changed

`preflight_optional_dependencies` used to require the `documents` extra (the `arxiv` package)
for **any** `scholarly_query` job. A manifest that declares only `openalex` must not be
blocked by a missing arXiv package, so the preflight now checks the extra only when a
configured job actually names `arxiv`.

## Verifying

```bash
PYTHONPATH=src python3 -m pytest tests/test_issue442_openalex_backend.py   # 6 passed
PYTHONPATH=src python3 - <<'PY'
import tomllib
from laclaugpt_data_collection.collectors.openalex import OpenAlexCollector
row = next(r for r in tomllib.load(open("data/config/ai26.sources.toml","rb"))["scholarly_query"]
           if r["name"] == "left_techno_optimism")
print(row["openalex_query"])
print(OpenAlexCollector(row["openalex_query"], max_results=5).collect().records[0].source_url)
PY
```

The runtime manifests are untracked per host (`data/config/ai26.sources.toml`); the same patch
was applied on the local station and on Laskin.
