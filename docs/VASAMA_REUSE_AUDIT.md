# VASAMA collection reuse audit

Issue: #19

This audit treats historical `TomiToivio/vasama-osint` code as archaeology, not as a dependency. Only generic Collection infrastructure is reusable. OSINT prompts, geopolitical semantics, private source lists, credentials, generated datasets and analysis logic are excluded.

## Findings

The old `rag` branch contains a simple cron pipeline (`cron.sh`, `cron_collect.py`, wrapper scripts) that demonstrates the useful operational pattern: one Linux machine can run collection non-interactively on a schedule. The historical implementation itself is not suitable for direct reuse because it hard-codes a machine path and source list and mixes collection with downstream processing stages.

The current LaclauGPT Data Collection repository already has a cleaner implementation of the reusable pattern:

- `DeploymentProfile.linux_server_local()` selects cron + SQLite + filesystem + in-process cache.
- `configs/server-local.example.toml` requires no MongoDB, Redis or S3.
- `render_cron()` emits a `flock`-guarded invocation using `data/runs/collection.lock` and appends to `data/logs/collection.log`.
- `render_systemd_units()` emits oneshot service/timer templates with `Persistent=true`.
- tests cover local/distributed profile separation, cron locking and systemd persistence.

VASAMA's old geocoding path also shows why Collection needs to retain factual source location fields while keeping inferred geocoding downstream. The historical code geocoded analysis-derived `event_location` values and wrote latitude/longitude into dashboard structures. That inference pattern is intentionally **not** imported into Collection. Instead, Collection now has an optional `SourceLocation` structure for locations and coordinates supplied directly by the source, including a `source_field` and metadata for provenance. Geocoder/LLM/researcher-derived locations remain Analysis-side claims.

## Audit table

| VASAMA path | branch/commit | capability | decision | target path | reason |
|---|---|---|---|---|---|
| `cron.sh` | `rag` @ `94ec36d` | sequential one-machine scheduled pipeline | ADAPT | `src/laclaugpt_data_collection/deployment.py`, `docs/DEPLOYMENT_AND_HERMES.md` | Keep external scheduler model, remove hard-coded path and mixed analysis stages. |
| `cron_collect.py` | `rag` @ `94ec36d`; evolved through Jan 2026 | scheduled collector entry point | REIMPLEMENT CLEANLY | CLI + collector registry + private study config | Historical file hard-codes operational source lists; source lists belong outside public code. |
| `cron_*.sh` wrappers | `rag` | small cron wrappers | REPLACE | `render_cron()` / `render_systemd_units()` | Generated scheduler commands are more portable and testable. |
| rotating cron logs | 2025-12 commits including `e0a4315` | persistent operational logs | ADAPT | `data/logs/collection.log` + external log rotation/systemd | Keep logs under private runtime root; avoid embedding machine assumptions. |
| `osint_geocode.py` | `rag` blob lineage | map/timeline geocoding | REJECT as Collection logic | downstream Analysis/Visualization | Geocoder results are inferred/enriched data, not source truth; historical file also contained an embedded API token. |
| source-provided place/coordinate fields | generic pattern inferred from geospatial pipeline need | preserve location-bearing evidence | ADOPT | `SourceSection.locations: list[SourceLocation]` | Enables later NER/geocoding without laundering inferred coordinates into source metadata. |
| Chroma/Mongo shared-context/RAG hooks | Jan 2026 shared-context work | downstream indexing after collection | OPTIONAL HANDOFF ONLY | future integration hook, not core Collection dependency | Collection must run with no Neo4j/Chroma/Ollama/Mongo requirement. |
| `.session`, credentials, target lists, dataframes | historical repo | runtime/auth/data | REJECT | none | Private/sensitive operational material; never copy. |

## March 2026 audit note

The repository history visible around the requested early-2026 window does not show a distinct March 2026 cron architecture replacing the older pattern. The relevant local-orchestration lineage is the `rag` branch plus late-2025/January-2026 cron and shared-context commits. Later 2026 Vasama work is intentionally not used as Collection domain semantics.

## Acceptance status

- [x] historical early-2026 commit window checked
- [x] `rag` branch checked for cron/local patterns
- [x] local cron/systemd collection profile documented/tested
- [x] local mode requires no MongoDB/Redis/S3
- [x] canonical schema remains identical to distributed mode
- [x] location-bearing source metadata is preserved for downstream analysis
- [x] no OSINT-specific prompts/domain assumptions imported
- [x] no private runtime/auth material copied

## Design boundary

Collection may preserve what the source actually says about location. It may not promote a geocoder, model or analyst guess into source truth. A downstream enrichment can cite the source location as evidence and add its own inferred/geocoded representation with separate provenance.
