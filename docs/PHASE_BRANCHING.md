# Phase branch workflow

This repository keeps persistent `phase-0` through `phase-4` branches.

As of 2026-09-21, **Phase 1 is active**. Phase 1 development goes directly to `main`. The `phase-1` branch is a passive compatibility/mirror ref and must match the validated `main` tree; it is not a development or pull-request target. The `phase-0` branch remains the preserved Phase 0 baseline. Later-phase branches may advance independently.

## Rules

1. Determine an issue's phase from its title/body, labels, milestone, linked roadmap, or explicit instruction.
2. For Phase 1, start from `main`; use a short-lived issue branch from `main` when needed and target the PR back to `main`.
3. Do not start Phase 1 work from `phase-1` and do not target Phase 1 PRs at `phase-1`.
4. Keep `phase-1` synchronized as a passive mirror of the validated `main` tree.
5. Do not target `main` with Phase 2/3/4 work while Phase 1 is active; use the matching `phase-N` branch instead.
6. Phase 0 maintenance stays on `phase-0`; it does not move `main` backward or redefine Phase 0 as Phase 1.
7. Unphased issues default to the active phase, currently Phase 1 on `main`.
8. For cross-repository Phase 1 work, use `main` in every affected LaclauGPT repository unless explicitly documented otherwise.
9. Backport minimal fixes between phases when required; never merge an entire later phase into the current stable phase just to obtain one fix.

`main` means the current active Phase 1 line.

Current invariant:

```text
main = Phase 1 active development/stable branch
phase-1 = passive mirror of main
phase-0 = preserved Phase 0 baseline
phase-2..phase-4 = isolated future work
```

When the project advances to a later phase, promotion into `main` requires explicit human approval.

Repository: `TomiToivio/LaclauGPT-Data-Collection`.

Agents must read `AGENTS.md` and this file before issue-driven changes. Working on the wrong phase branch is an incorrect implementation.
