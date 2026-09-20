# Phase 1 AI26 + Brazil26 end-to-end integration gate

Issue #143 is the cross-study integration gate for the Phase 1 pipeline:

```text
Collection -> Analysis -> Visualization
```

The public repository carries a synthetic, public-safe fixture at
`tests/fixtures/phase1_e2e_ai26_brazil26_v1.json`. It represents the four
required producer roles without requiring credentials, private target overlays,
MongoDB, Redis, CSC Allas, or collected research data.

## What the automated gate proves

Run:

```bash
pytest -q tests/test_phase1_e2e_ai26_brazil26.py
python tools/verify_contracts.py
```

The fixture and test verify:

- one canonical `CanonicalRecord` schema, currently `1.1.0`;
- AI26 compatibility with `ai26-phase1-handoff-v1`;
- AI26 localhost browser and Laskin non-browser records;
- Brazil26 localhost browser and Laskin non-browser records;
- the same public URL can exist in both studies because identity includes
  `project_id + collection_id + source_url`;
- machine/source provenance does not alter study identity;
- Analysis can enrich either study by adding to the same canonical record rather
  than translating to a Brazil-specific transport;
- deterministic analytical identity is study-scoped and idempotent;
- Visualization can select AI26, Brazil26, or an explicit combined view without
  collapsing cross-study identities;
- Laskin fixtures never use browser-only platforms;
- media/object references remain project-scoped; and
- study config, collection codebook, and source-manifest revisions are visible
  in provenance as public-safe revision placeholders.

The fixture is intentionally synthetic. The `sha256:...` provenance values are
not hashes of private operational overlays. Live deployments should record the
real revision/hash values at runtime without printing private configuration or
secrets into public logs.

## Final Phase 1 topology and ownership

| Host/module | AI26 | Brazil26 | Ownership boundary |
|---|---|---|---|
| Localhost Collection | browser + bounded non-browser | browser + bounded non-browser | interactive browser capture stays local |
| Laskin Collection | bounded non-browser + shared media | bounded non-browser + shared media | no Firefox/browser collectors |
| MongoDB | canonical records | canonical records | durable canonical state, study-scoped routing |
| Redis | config/coordination/reference events | config/coordination/reference events | never canonical payload storage |
| CSC Allas/S3 | raw/media objects | raw/media objects | `projects/<project_id>/...` |
| Data Analysis | consumes canonical handoff | consumes same canonical handoff | adds analysis to canonical identity |
| Data Visualization | AI26 filter or combined | Brazil26 filter or combined | combined views must retain study identity |

Machine identity belongs only in execution provenance. It must not create a
localhost/Laskin research namespace.

## Live smoke run prerequisites

The automated gate is self-contained, but the live two-host smoke run depends on
all four deployment profiles being present:

- #139 AI26 localhost
- #140 AI26 Laskin
- #141 Brazil26 localhost
- #142 Brazil26 Laskin

At the time this gate was added, #140 and #141 were already integrated while
#139 and #142 were still deployment work items. The live run should therefore
be executed only after those profiles are available on the target Phase 1
branch.

## Reproducible live smoke procedure

Use only synthetic or public-safe records.

1. Start localhost browser backends through the shared Firefox study runner for
   AI26 and Brazil26. Both must bind to `127.0.0.1`.
2. Capture one browser record per study, using the same public-safe URL for one
   pair to exercise cross-study identity.
3. Run one bounded localhost non-browser cycle per study.
4. Run one bounded Laskin non-browser cycle per study. Laskin must have no
   browser backend or browser-only source scheduled.
5. Run the shared media workers. Confirm a pending object originating on
   localhost can be discovered from canonical shared state and processed on
   Laskin.
6. Query MongoDB by `project_id` and `collection_id`. Re-run all bounded
   cycles and confirm the number of canonical identity tuples does not grow.
7. Run Data Analysis against AI26 and Brazil26 using the canonical handoff.
   Confirm no study-specific transport translation is used.
8. Query Visualization in three modes: AI26 only, Brazil26 only, explicit
   combined. The combined result must preserve `project_id`,
   `collection_id`, and `source_url`.
9. Record the public study config, collection codebook, and source-manifest
   revisions in run provenance. Keep private overlays, cookies, credentials,
   account targets, and raw research data out of logs and Git.

A successful live smoke run completes the operational acceptance gate for
#143; the committed synthetic test remains the CI-safe regression guard.
