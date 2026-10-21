# AI26 sampling decision — bounded and fair RSS feed rotation (#293)

**Status: decided 2026-10-21.** The study owner authorised this sampling decision
("do these and close them"); it is recorded here with its inclusion criteria and
the measurement that produced it. Sampling provenance is not an ideology label:
no actor is classified ideologically, and `source_family` explains *why material
is sampled*, never what an actor "is".

The checked-in example manifest (`configs/studies/ai26.sources.example.toml`) is
**not** the deployed private `data/config/ai26.sources.toml`. Reconciling the
deployed file is a separate deployment step for the owner. Nothing here deletes
or relabels records already in the store.

Index of this round's decisions: `docs/ai26-sampling-decisions-2026-10-21.md`.

---

## The decision: bounded **and fair**, not bigger

**Decision.** Keep throughput exactly where it is. `limit` (40), `rss_allocation`
(20), `max_feeds` (8) and `per_source_limit` (5) are **unchanged**; no tick is
raised to buy per-feed frequency. What changes is *which* feeds the bounded window
touches: the window rotates through the priority-ordered manifest by its own size
on every cycle, and the cycle log names both the window and the feeds actually
polled.

**The cadence, computed from the code** (`ai26_laskin_runner.run_phase1_laskin`,
`server_runner.select_feed_window`), not asserted:

| quantity | value | where it comes from |
|---|---|---|
| `non_browser_reserve` | 20 | `min(limit // 2, max_jobs * per_source_limit)` = `min(20, 30)` |
| `rss_allocation` | 20 | `limit - non_browser_reserve` |
| feed window per cycle | **4 feeds** | `_rss_window(max_feeds=8, rss_limit=20, per_source_limit=5)` = `(4, 5)` |
| items fetched per feed | 5 | the declared `per_source_limit`, not a reduced depth |
| window advance per cycle | **4 positions** | `rotation * rss_feeds`, `rotation` = hours since epoch |
| full pass, 32-feed manifest | **8 cycles = 8 hours** | `ceil(32 / 4)` |
| worst-case per-feed cadence | **8 hours** | measured 8–31 h before the change |
| first record for a tail-of-manifest feed | **≤ 8 hours** | one pass; it was ~a day |
| full pass, current 36 enabled feeds | 9 cycles = 9 hours | `ceil(36 / 4)` |
| records per day | 480 | 20 × 24, unchanged |

The worst case is a *bound*, not an average: each pass polls each feed exactly
once and no feed twice, and `tests/test_issue_293_feed_rotation.py` simulates 8
consecutive cycles over a 32-feed manifest to assert it.

**Visibility.** `tick_budget.rss_feed_window` now carries `rotation` (the window's
position), `window_size`, `window` (feed names selected), `polled` (feed names
actually fetched — the fetch stops at the store budget), `feeds_in_manifest` and
`cycles_per_pass`. Per-feed cadence can be read off the cycle log instead of
inferred from `captured_at` timestamps.

**Why the window shrinks by feed count and not by depth.** The allocation can be
made to fit either way: 4 feeds at 5 candidates, or 8 feeds at 2. Reducing the
depth was tried (PR #308) and is rejected here because it silently changes *which*
records a cycle can store: only a feed's two newest items are ever fetched, so the
third newest is never collected once two newer ones exist, and the stored set stops
being the prefix of an unbounded fetch that #301 pinned. The feed count is what
shrinks; the rotation, not a shallower fetch, is what covers the manifest. The
window-size invariant (`feeds * depth <= rss_allocation`) is kept either way, and
`_rss_window` still exposes it.

**What this is not.** Not hourly per-feed polling. If the study needs hourly
per-feed coverage, the tick budget has to rise — that is a different sampling
decision and is not taken here.

---

## Verification (owner's deployment step)

1. Reconcile `configs/studies/ai26.sources.example.toml` into the deployed
   `data/config/ai26.sources.toml` and confirm `manifest-drift.in_sync`.
2. In one cycle, `tick_budget.rss_feed_window` must show `window_size: 4`,
   `cycles_per_pass: 9` at 36 enabled feeds, and a `window`/`polled` list that
   differs from the previous cycle's.
3. `rss_records_synced` must stay at 20 per cycle — the fix changes *which* feeds
   are polled, never how much is stored.
4. After a full pass, every configured feed must appear in the `polled` lists of
   the log, and each feed's gap must be at most `cycles_per_pass`.

---
