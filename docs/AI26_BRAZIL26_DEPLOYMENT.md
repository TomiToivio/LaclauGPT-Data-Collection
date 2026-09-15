# AI26 and Brazil26 collection deployment

This document defines the public, reusable deployment contract for two concurrent studies without publishing operational targets, credentials, hostnames, machine paths, or research data.

## Shared collector, isolated studies

AI26 and Brazil26 use the same `LaclauGPT-Data-Collection` codebase and canonical schema. They must use separate private runtime state:

- separate study YAML files;
- separate data roots and SQLite state;
- separate raw-capture directories and manifests;
- separate Firefox profiles when browser-assisted collection is used;
- separate capture ports/tunnels when both are active at once.

Never deduplicate across studies by a shared runtime database. `source_url` remains the canonical record identity inside each study and at module handoff.

Public templates live at:

- `configs/studies/ai26.example.yaml`
- `configs/studies/brazil26.example.yaml`

They contain fictional targets only. Real sampling frames belong in ignored/private runtime configuration.

## Real-time research-server pattern

A Linux research server may run Collection continuously with local SQLite/filesystem storage or the distributed MongoDB/Redis/S3 adapters. Machine addresses, credentials and concrete paths stay private.

For browser-assisted capture, keep the capture backend loopback-only even when it runs on the research server. Start it with the generic wrapper:

```bash
scripts/run_firefox_study.sh \
  /private/config/ai26.yaml \
  /private/runtime/ai26 \
  18765
```

From the researcher workstation, use an authenticated SSH local-forward (or an equivalent private tunnel) so the Firefox extension still talks to `127.0.0.1`:

```bash
ssh -N -L 18765:127.0.0.1:18765 RESEARCH_SERVER
```

Configure the AI26 Firefox profile to use `http://127.0.0.1:18765` in extension local storage. Use a different local/server port and a different Firefox profile for Brazil26, for example `18766`. The numbers are examples only, not deployment assignments.

This preserves the capture server's loopback-only security invariant instead of publishing an unauthenticated HTTP ingestion endpoint.

## AI26 flow

```text
Firefox / feeds / platform collectors
        -> LaclauGPT-Data-Collection
        -> canonical records in private runtime storage
        -> LaclauGPT-Data-Analysis real-time worker
        -> canonical analysis results
        -> LaclauGPT-Data-Visualization Monitor / Review / Explore
```

Collection does not perform ideological or discourse-theoretical classification. Sampling group metadata is provenance only and must not become an automatic label for a captured document.

## Brazil26 flow

Brazil26 currently needs the collection side prepared first. Use the same Firefox extension and capture backend with a Brazil26 private study file and an independent runtime root. The public example intentionally contains fictional candidates and parties; the real election sampling frame must be researcher-maintained outside Git.

Once Brazil26 analysis is activated, its canonical records can enter the same Analysis and Visualization module contracts without a Brazil-specific schema fork.

## Operational checks

Before starting either study:

1. `laclaugpt-collect doctor` the server deployment profile.
2. Validate the private study YAML by starting the backend and checking `/status` through the private tunnel.
3. Confirm that AI26 and Brazil26 resolve to different data roots and ports.
4. Confirm the Firefox profile points only at loopback.
5. Confirm collected data is ignored/untracked before any `git push`.
6. Confirm Analysis consumes canonical records rather than scraping Collection internals.

The public repository should contain reusable code and synthetic examples only. Live target lists, schedules, machine endpoints and collected material remain private.
