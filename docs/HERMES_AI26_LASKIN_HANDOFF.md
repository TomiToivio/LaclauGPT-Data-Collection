# Hermes handoff: AI26 Phase 1 Collection on Laskin

This is the host-execution handoff for issue #169. The repository-side implementation is already present. Hermes should **verify and operate the existing Phase 1 path on Laskin**, not design a second collection architecture.

## Already prepared in Git

- `scripts/run_ai26_laskin_collect.sh`: bounded, cron-safe, `flock`-protected non-browser cycle.
- `scripts/run_ai26_laskin_media.sh`: bounded shared pending-media worker.
- `src/laclaugpt_data_collection/ai26_laskin_runner.py`: RSS/web plus supported non-browser source orchestration, browser/X exclusion, shared `collection_id=ai26`.
- Shared MongoDB pending-media discovery so laptop browser captures can be processed on Laskin.
- Canonical AI26 Collection -> Analysis contract fixture and `python tools/verify_contracts.py`.
- Public runbooks: `docs/AI26_LASKIN_COLLECTION.md`, `docs/AI26_TWO_MACHINE_COLLECTION.md`.
- Synthetic/offline tests covering browser exclusion, rotating source windows, shared project-scoped backends, shared MongoDB media discovery, publication-date filtering, and the optional dependency contract.

Do not create machine-specific MongoDB collections, Redis namespaces, S3 prefixes, schemas or study IDs. Machine identity is execution provenance only.

## Hermes mission on Laskin

1. Inspect `AGENTS.md`, `HERMES.md`, `skills/laclaugpt-data-collection/SKILL.md`, `docs/AI26_LASKIN_COLLECTION.md`, and issue #169 before changing anything.
2. Verify the checkout is current and clean enough to operate. Do not discard unrelated local work.

```bash
cd <absolute-repo-path>
git status --short
git pull --ff-only origin main
git rev-parse HEAD
```

3. Use the authorized private AI26 runtime configuration. Never copy credentials, endpoints, cookies, private targets or raw research rows into this public repository or issue comments.
4. Confirm `LACLAUGPT_PROJECT_ID=ai26`, server/unattended execution, and `LACLAUGPT_BROWSER=none`.
5. Install/update the existing environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[distributed,phase1-non-browser,dev]'
```

The aggregate extra above must remain aligned with the checked-in source manifest. A missing optional dependency is a setup failure, not a routine partial collection tick.

6. Run the repository/offline gates first:

```bash
python scripts/check_public_tree.py
ruff check .
mypy src/laclaugpt_data_collection/config.py \
  src/laclaugpt_data_collection/models.py \
  src/laclaugpt_data_collection/normalize.py \
  src/laclaugpt_data_collection/storage/base.py \
  src/laclaugpt_data_collection/storage/local.py
python tools/verify_contracts.py
pytest -q
```

If one of these fails before any host-specific operation, report it separately as a repository/offline gate failure.

7. Run sanitized profile and live backend checks:

```bash
set -a; . ./.env; set +a
.venv/bin/laclaugpt-collect doctor --profile configs/ai26.laskin-remote.example.toml
.venv/bin/laclaugpt-collect distributed-check --study-config data/config/ai26.yaml
```

Confirm only redacted/safe facts: project, execution/browser modes, schema/config revision identifiers, backend capability status and namespace consistency. Do not print private values.

8. Execute one bounded collection tick and one media tick:

```bash
bash scripts/run_ai26_laskin_collect.sh
bash scripts/run_ai26_laskin_media.sh
```

9. Repeat collection once to prove idempotence, then reproduce a cron-like minimal environment where the wrapper supports it. Verify a forced overlap exits cleanly through `flock`.
10. Verify in the shared canonical plane, using sanitized counts/metadata only:
   - at least one newly collected public-safe item exists, or a bounded run safely deduplicated already-present items;
   - `project_id=ai26` / `collection_id=ai26`;
   - stable `source_url` identity is preserved across runs;
   - machine/worker identity is provenance only;
   - no browser/X collector started;
   - source-native IDs and collection timestamps are preserved where available;
   - pending media created from a localhost/browser record is discoverable from shared MongoDB and can be processed on Laskin;
   - media remains a reference in the canonical record and durable bytes live in the shared Allas/S3 project prefix;
   - source-specific failures do not corrupt successful records or leak private values.

11. Inspect logs for bounded status and absence of secrets. Do not install/change scheduled jobs merely to satisfy #169 unless runtime verification shows the existing deployment is missing or broken.

## Source coverage audit

For each source/plugin enabled by the authorized private AI26 configuration, record only sanitized status:

```text
source/plugin:
configured: yes|no
preflight: pass|fail
attempted: yes|no
records: <aggregate count or empty>
canonical_validation: pass|fail|n/a
media: success|pending|failed|n/a
status: working|empty|auth-blocked|platform-blocked|config-defect|collector-defect|canonicalization-defect|storage-defect|media-defect|browser-only|disabled
notes: <sanitized>
```

A zero-record result is not automatically success; classify why it is empty.

## Cross-repo exit check

The Collection result must leave this repository in the canonical Analysis-ready shape. Use the pinned contract:

- schema contract: canonical Collection record
- AI26 handoff contract: `ai26-phase1-handoff-v1`
- verifier: `python tools/verify_contracts.py`

Then confirm the Analysis-side Phase 1 handoff/worker can see and ingest a newly collected canonical AI26 record unchanged, without a Phase 0 flat-record adapter or study-specific conversion layer. Do not run discourse analysis in this repository.

## Defect handling

Only change public code if the live host exposes a concrete, reproducible repository defect. Before filing anything, search open and recently closed issues for the same problem. Add sanitized evidence to an existing issue when it already covers the defect; otherwise create one narrowly scoped issue in the owning repository.

For a new defect record: observed behavior, expected behavior, sanitized reproduction, affected Git SHA, source/plugin/backend, severity, whether it blocks the Collection -> Analysis gate, sanitized error, owning component, next diagnostic step and acceptance criteria.

Stop the Step 1 handoff if canonical identity/schema, namespace isolation, privacy, durable storage or the Analysis handoff cannot be trusted.

## Completion evidence for issue #169

Post only sanitized evidence using this template:

```text
Laskin execution time:
Collection Git SHA:
project / schema:
offline quality gates:
doctor / preflight:
enabled source/plugin count:
source/plugin totals: working= empty= failed= browser-only/disabled=
records: attempted= new= updated= duplicate-skipped=
media: success= pending= failed=
second-run idempotency:
MongoDB capability:
Redis capability:
S3/Allas capability:
canonical validation:
Collection -> Analysis handoff:
defect issues:
STEP 1 PASS | STEP 1 BLOCKED
```

Never post private endpoints, credentials, source/account lists, research rows, raw captures, media contents or sensitive paths. This issue certifies Collection Step 1 only, not the overall Phase 1 pipeline.
