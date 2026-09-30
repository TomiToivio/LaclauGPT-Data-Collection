# Phase branch workflow

This repository keeps persistent `phase-0` through `phase-4` branches.

As of 2026-09-30, **Phase 2 is active**. Phase 2 development goes directly to `main`. The `phase-2` branch is a passive compatibility/mirror ref and must match the validated `main` tree; it is not the development or pull-request target. The `phase-1` branch is the preserved Phase 1 baseline, and `phase-0` is the preserved Phase 0 baseline. Later Phase 3 and Phase 4 branches may advance independently.

## Rules

1. Determine an issue's phase from its title/body, labels, milestone, linked roadmap, or explicit instruction.
2. For Phase 2, start from `main`; Phase 2 changes may be made directly on `main` when explicitly authorized, or through a short-lived branch targeting `main`.
3. Do not start new Phase 2 work from `phase-2` and do not target Phase 2 PRs at `phase-2`.
4. Keep `phase-2` synchronized as a passive mirror of the validated `main` tree.
5. Do not target `main` with Phase 3/4 work while Phase 2 is active; use the matching `phase-N` branch instead.
6. Phase 1 maintenance stays on `phase-1`; Phase 0 maintenance stays on `phase-0`. Neither moves `main` backward.
7. Unphased issues default to the active phase, currently Phase 2 on `main`.
8. For cross-repository Phase 2 work, use `main` in every affected LaclauGPT repository unless explicitly documented otherwise.
9. Backport minimal fixes between phases when required; never merge an entire later phase into the current stable phase just to obtain one fix.

`main` means the current active Phase 2 line.

Current invariant:

```text
main = Phase 2 active development/stable branch
phase-2 = passive mirror of main
phase-1 = preserved Phase 1 baseline
phase-0 = preserved Phase 0 baseline
phase-3..phase-4 = isolated future work
```


When the project advances to a later phase, promotion into `main` requires explicit human approval.

Repository: `TomiToivio/LaclauGPT-Data-Collection`.

Agents must read `AGENTS.md` and this file before issue-driven changes. Working on the wrong phase branch is an incorrect implementation.
