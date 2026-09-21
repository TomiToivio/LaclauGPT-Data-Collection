# Hermes handoff: AI26 Phase 1 Collection on Laskin

This is the host-execution handoff for issue #151. The repository-side implementation is already present. Hermes should **verify and operate the existing Phase 1 path on Laskin**, not design a second collection architecture.

## Already prepared in Git

- `scripts/run_ai26_laskin_collect.sh`: bounded, cron-safe, `flock`-protected non-browser cycle.
- `scripts/run_ai26_laskin_media.sh`: bounded shared pending-media worker.
- `src/laclaugpt_data_collection/ai26_laskin_runner.py`: RSS/web plus supported non-browser source orchestration, browser/X exclusion, shared `collection_id=ai26`.
- Shared MongoDB pending-media discovery so laptop browser captures can be processed on Laskin.
- Canonical AI26 Collection -> Analysis contract fixture and `python tools/verify_contracts.py`.
- Public runbooks: `docs/AI26_LASKIN_COLLECTION.md`, `docs/AI26_TWO_MACHINE_COLLECTION.md`.

Do not create machine-specific MongoDB collections, Redis namespaces, S3 prefixes, schemas or study IDs. Machine identity is execution provenance only.

## Hermes mission on Laskin

1. Inspect `AGENTS.md`, `HERMES.md`, `docs/AI26_LASKIN_COLLECTION.md`, and issue #151 before changing anything.
2. Verify the checkout is current and clean enough to operate. Do not discard unrelated local work.
3. Use the authorized private AI26 runtime configuration. Never copy credentials, endpoints, cookies, private targets or raw research rows into this public repository or issue comments.
4. Confirm `LACLAUGPT_PROJECT_ID=ai26` and `LACLAUGPT_BROWSER=none`.
5. Install/update the existing environment:

```bash
cd /mnt/workspace/LaclauGPT-Data-Collection
git pull --ff-only origin main
python -m venv .venv
source .venv/bin/activate
pip install -e '.[distributed,phase1-non-browser,dev]'
```

The aggregate extra above must remain aligned with the checked-in source manifest. A missing optional dependency is a setup failure, not a routine partial collection tick.\n\n6. Run repository/offline gates first:

```bash
python tools/verify_contracts.py
pytest -q
```

7. Run sanitized profile and live backend checks:

```bash
set -a; . ./.env; set +a
.venv/bin/laclaugpt-collect doctor --profile configs/ai26.laskin-remote.example.toml
.venv/bin/laclaugpt-collect distributed-check --study-config data/config/ai26.yaml
```

8. Execute one bounded collection tick and one media tick:

```bash
bash scripts/run_ai26_laskin_collect.sh
bash scripts/run_ai26_laskin_media.sh
```

9. Repeat collection once to prove idempotence, then reproduce a cron-like minimal environment where the wrapper supports it. Verify a forced overlap exits cleanly through `flock`.
10. Verify in the shared canonical plane, using sanitized counts/metadata only:
   - at least one public-safe item was written or safely deduplicated;
   - `project_id=ai26` / `collection_id=ai26`;
   - machine/worker identity is provenance only;
   - no browser/X collector started;
   - pending media created from a localhost/browser record is discoverable from shared MongoDB and can be processed on Laskin;
   - media remains a reference in the canonical record and durable bytes live in the shared Allas/S3 project prefix.
11. Install/verify the documented hourly cron entries only after the manual cycles pass.
12. Inspect logs for bounded status and absence of secrets.

## Cross-repo exit check

The Collection result must leave this repository in the canonical Analysis-ready shape. Use the pinned contract:

- schema contract: canonical Collection record
- AI26 handoff contract: `ai26-phase1-handoff-v1`
- verifier: `python tools/verify_contracts.py`

Then confirm the Analysis Laskin worker can ingest the new/public-safe record unchanged. Do not add a study-specific conversion layer.

## When to change code

Only change public code if the live host exposes a reproducible repository defect. Prefer the smallest general fix, add a synthetic regression test, run public CI-equivalent checks, and keep Phase 0 isolated.

## Completion evidence for issue #151

Post only sanitized evidence: commit SHA, pass/fail for contract/tests, bounded record counts, cron presence, overlap/idempotence result, whether shared pending media was discovered, and whether Analysis consumed the canonical item unchanged. Never post private endpoints, credentials, source lists, research rows or sensitive paths.
