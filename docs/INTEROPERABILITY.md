# LaclauGPT Collection interoperability contract

`LaclauGPT-Data-Collection` is a producer module. It must not require Analysis, Visualization or external research applications in order to collect data. External tools are **sources, acquisition backends or interchange partners**, not alternate canonical schemas.

Imported material is normalized into the current nested `CanonicalRecord`. Source-specific fields remain in `raw_capture`, `source.raw_metadata`, `source_native_ids` and provenance so downstream modules can audit or re-map them later.

The project-wide interoperability contract lives in `TomiToivio/LaclauGPT#35`. This document covers the Collection boundary only: acquisition, capture, normalization, provenance, scheduling, durable source identity, raw/media preservation, and export.

## Canonical boundary

The stable Collection-side envelope is:

```text
CanonicalRecord
├── schema_version
├── source_url                 # cross-module identity / dedup key
├── source_native_ids          # external/platform IDs
├── raw_capture                # lossless payload or durable raw ref
├── source                     # source metadata + collection metadata
├── content                    # normalized text/title/media/file refs
├── intermediate              # preprocessing outputs when applicable
├── evidence
├── analysis                   # populated downstream, not by Collection
├── human_readable
├── provenance
├── review
└── legacy
```

The canonical schema remains authoritative inside LaclauGPT. External formats are adapters/projections. Backend-specific IDs never replace `source_url`.

## Status registry

| Tool/library | Import | Export | Native/library integration | Collection role |
|---|---|---|---|---|
| 4CAT | JSON/JSONL/NDJSON/CSV adapter | safe flat 4CAT-style projection | format-level | dataset interchange |
| Zeeschuimer | JSON/JSONL/NDJSON/CSV adapter | canonical or 4CAT-style projection | browser-capture compatibility | browser research capture |
| DATS | source/document JSON/JSONL/CSV adapter | canonical record | format-level | source documents only; annotations/codes belong to Analysis |
| minet | tabular/JSON output can feed adapters | canonical/tabular exports | optional `web-mining` extra | web mining/retrieval |
| Scrapy | n/a | canonical | optional `web-mining` extra | crawler backend |
| BeautifulSoup | n/a | canonical | optional `web-mining` extra | HTML parsing |
| Trafilatura | n/a | canonical | optional `web-mining` extra | main-text extraction |
| atproto | n/a | canonical | optional `bluesky-native` extra | native Bluesky/AT Protocol work |
| Mastodon.py | n/a | canonical | existing `mastodon` extra | native Mastodon access |
| PRAW | n/a | canonical | optional `reddit` extra | Reddit API access where research/API conditions permit |
| yt-dlp | n/a | files + canonical media refs | existing `youtube` extra | media acquisition |
| ffmpeg | n/a | files + canonical media refs | external executable | transcoding/probing |
| PyArrow/Parquet | typed tabular interchange | typed tabular interchange | optional `interop` extra | Python/R exchange |

The registry distinguishes **format compatibility** from **native integration**. An import adapter does not imply that LaclauGPT embeds or reimplements the external application.

## Python API

The interoperability API lives in:

```python
from laclaugpt_data_collection.integrations.interoperability import (
    export_4cat_projection,
    import_4cat_record,
    import_dats_document,
    import_zeeschuimer_record,
    read_external_records,
    write_records,
)
```

Example:

```python
records = read_external_records("data/import/capture.ndjson", tool="zeeschuimer")
write_records(records, "data/exports/capture.jsonl")
write_records(records, "data/exports/fourcat.csv", projection="4cat")
```

Parquet output is optional:

```bash
pip install -e '.[interop]'
```

Then:

```python
write_records(records, "data/exports/capture.parquet")
```

## 4CAT mapping

4CAT datasource schemas are source-specific. The adapter therefore uses a conservative alias set and retains the entire input row in `raw_capture.payload`.

Typical mapping:

```text
4CAT id/post_id/item_id     -> source_native_ids["4cat_id"]
url/link/source_url         -> source_url
author/username/user        -> source.author
timestamp/created_at/date   -> source.created_at
collected_at/retrieved_at   -> source.collected_at
text/body/content/message   -> content.text
media/attachments/images    -> content.media_references
sampling/query metadata     -> provenance.metadata.sampling
complete source row         -> raw_capture.payload
```

If a record has no URL but has a stable external ID, the adapter uses a URI-like canonical identity such as `4cat:<platform>:<id>`. A row without either form of stable identity is rejected rather than being assigned a random ID.

`export_4cat_projection()` creates a deliberately flat, portable representation. It is an interchange projection, not a second canonical schema.

## Zeeschuimer mapping

Zeeschuimer imports preserve the browser-capture envelope as raw material and distinguish:

- **source-created time** (`source.created_at`)
- **browser capture time** (`source.collected_at` and `raw_capture.captured_at`)

Typical mapping:

```text
id/post_id/pk/rest_id       -> source_native_ids["zeeschuimer_id"]
url/permalink/web_url       -> source_url
created_at/timestamp        -> source.created_at
timestamp_collected/...     -> source.collected_at
username/user/handle        -> source.author
text/body/content/caption   -> content.text
query/seed/tab_url/...      -> provenance.metadata.sampling
complete envelope           -> raw_capture.payload
```

The LaclauGPT Firefox extension remains isolated under `browser/`. JavaScript capture code must not become a dependency of the Python package. Canonical or 4CAT-style exports can be used to move browser-captured material into other research workflows.

## DATS document mapping

Collection imports only the **source/document layer** of DATS. Analytical codes, annotations, AI classifications, researcher corrections, concept-over-time results, and whiteboard relations belong in `LaclauGPT-Data-Analysis` and `LaclauGPT-Data-Visualization`.

```text
DATS document id      -> source_native_ids["dats_document_id"]
DATS project id       -> source_native_ids["dats_project_id"]
source URL             -> source_url
source metadata        -> source + source.raw_metadata
text/title/language    -> content
file/media references  -> content.file_references / media_references
complete document      -> raw_capture.payload
```

The raw-capture metadata explicitly records `codes_and_annotations_imported=false` so a Collection import cannot be mistaken for a full DATS analytical round trip.

## Portable formats

Preferred Collection exchange formats are:

1. **Canonical JSON/JSONL** for authoritative nested research records.
2. **CSV** for human-readable/manual interchange and flat projections.
3. **Parquet/Apache Arrow** for typed bulk Python/R exchange.
4. ZIP/tar only as containers around documented open files, never as opaque application state.

Do not use Python pickle, browser-local state, or another language-specific binary format as the only research export.

## Python/R/JavaScript placement

- **Python**: primary Collection runtime under `src/laclaugpt_data_collection/`.
- **R**: Collection normally needs no R runtime. Any future validation/conversion utility belongs under `scripts/r/` and must be independently runnable in RStudio or `Rscript`.
- **JavaScript**: browser-specific code stays in the browser extension/backend integration area. Dashboard JavaScript belongs in the Visualization repository.

## Optional collection libraries

Install only the integration needed for a deployment:

```bash
pip install -e '.[web-mining]'
pip install -e '.[bluesky-native]'
pip install -e '.[reddit]'
pip install -e '.[mastodon]'
pip install -e '.[youtube]'
```

The source-plugin contract remains above these libraries. A library is an acquisition backend; it does not define canonical identity, provenance or privacy policy.

### Web mining

`web-mining` makes minet, Scrapy, BeautifulSoup and Trafilatura available for collector plugins or researcher-side preprocessing. Prefer:

- **minet** for reproducible web-mining/retrieval workflows and CLI-oriented research pipelines;
- **Scrapy** for structured crawling and scheduling;
- **BeautifulSoup** for DOM parsing when a full extraction model is unnecessary;
- **Trafilatura** for main-text/article extraction.

When their output is imported, retain the original URL, crawl/retrieval metadata and tool version in provenance.

### Source-native APIs

Prefer source-native stable IDs/protocol identifiers where available. atproto, Mastodon.py and PRAW should sit behind Collection source plugins; backend-specific IDs must never replace `source_url` as the cross-module identity.

### Media

`yt-dlp` and ffmpeg are acquisition/transcoding backends. Collection records should contain the durable media/object reference, checksums where available, acquisition provenance and original source identity. Analysis should not need to know which downloader fetched the file.

## Sampling and collection provenance

A technically successful scrape is not automatically a representative sample. Each collection run should preserve, where applicable:

- seed/query/search terms;
- reference to the account/channel/source list without putting private targets in public Git;
- discovery mechanism;
- requested collection time window;
- pagination/cursor strategy;
- API vs browser vs crawler vs manual collection mode;
- collector/library name and version;
- retry/rate-limit behavior relevant to completeness;
- sampling mode;
- inclusion/exclusion rules;
- collection run ID;
- capture timestamp;
- source-created timestamp;
- source-native IDs;
- raw payload/object reference.

External adapters put available sampling metadata into `CollectionProvenance.metadata["sampling"]`. Native collectors should use the same vocabulary where practical.

## Methodological guardrails

Collection provenance describes **how data entered the corpus**. It does not establish population representativeness, completeness, authenticity, ideological relevance or theoretical meaning.

Keep these distinctions explicit:

- successful API/browser retrieval != complete population capture;
- a platform search result != random sample;
- high-frequency users can dominate post-level samples;
- deleted/private/unavailable material creates survivorship and access bias;
- ranking/recommendation/search interfaces can shape discovered corpora;
- collector failure and platform rate limits can create patterned missingness;
- normalization must not silently erase source-specific information needed to evaluate those biases.

## Scientific and methodological sources

The canonical project bibliography belongs in the main `LaclauGPT` repository. Collection-specific sources should include at least:

- Lazer, D. et al. (2009). **Computational Social Science.** *Science*, 323(5915), 721–723. https://doi.org/10.1126/science.1167742
- Lazer, D. M. J. et al. (2020). **Computational social science: Obstacles and opportunities.** *Science*, 369(6507), 1060–1062. https://doi.org/10.1126/science.aaz8170
- Salganik, M. J. **Bit by Bit: Social Research in the Digital Age.** Princeton University Press. Open edition: https://www.bitbybitbook.com/
- Peeters, S. & Hagen, S. (2022). **The 4CAT Capture and Analysis Toolkit: A Modular Tool for Transparent and Traceable Social Media Research.** *Computational Communication Research*. https://doi.org/10.5117/CCR2022.1.007.HAGE
- Digital Methods Initiative. **Zeeschuimer** documentation and source repository: https://github.com/digitalmethodsinitiative/zeeschuimer
- Digital Methods Initiative. **4CAT** documentation and source repository: https://github.com/digitalmethodsinitiative/4cat

For source-specific collectors, add the strongest available peer-reviewed or official methodological documentation for the source/API and describe known coverage limitations.

## Testing and public-repository safety

Interoperability tests use synthetic multilingual fixtures only. They cover stable identity, source vs capture timestamps, URL canonicalization/deduplication, external IDs, provenance, media references, malformed records and portable export.

Never commit real 4CAT/DATS/Zeeschuimer project exports, target lists, cookies, browser profiles, raw research payloads, media or credentials. Runtime imports belong below ignored `data/` paths or external/private infrastructure.

## Compatibility rule

Breaking changes to the canonical envelope require a schema-version bump and migration notes. New optional fields are backwards-compatible. External-format changes should normally be absorbed by versioned adapters, not by changing the canonical schema.
