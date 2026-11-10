# X stratum: closed for Phase 1, and monitored (#401)

**Decision status: recorded 2026-11-04.** This is a decision record, not a design proposal. It can be
reversed by a human with a browser session; it cannot be reversed by an agent.

## What is actually true

- The AI26 corpus holds **5,097 X records**, captured up to **2026-10-26T14:54Z**.
- The only scheduled X path is `ai26_x_bridge.py`, a **consumer**: it replays `*.ndjson` captures from
  `/home/tomi/laclaugpt-ai26-data/raw/x` into `vasama_ai.events`. Its newest capture directory is
  `20260915`. It prints `inserted 0, skipped 36584` on every run and always will, because the capture
  set is static and fully ingested.
- The bridge writes to `vasama_ai.events`, **not** to the AI26 record store.
- Nothing in the AI26 crontab produces those captures.
- Producing them needs a **logged-in browser session** — a human action. That is why this is a
  decision and not a bug fix.

## The decision

**The X stratum is closed for Phase 1.** No agent will invent a producer, bypass authentication, or
substitute a public mirror for an authenticated capture. The 5,097 records already collected remain
in the corpus with their provenance intact.

This is option (b) in #401, taken deliberately rather than by drift. Option (a) — a scheduled
authenticated producer — remains open and is a human decision.

## Why silence was the real defect

The corpus can lose half of one platform and still report `status: ok` for fourteen consecutive
cycles, because "no jobs to run" and "collection is broken" looked identical. The fix is a monitor
that answers a different question: *when did we last capture from this platform?*

`scripts/check_ai26_capture_freshness.py` now:

1. reads capture timestamps directly from MongoDB (`provenance.captured_at`), so it needs no
   hand-maintained private file — the previous version required a `--captures-json` that did not
   exist on this host, which is why it was never scheduled;
2. checks a declared platform list (default `x`) and reports, per platform, the newest capture and
   its age;
3. exits **2** on `no_capture`, `stale_capture` or `future_capture_timestamp`;
4. is scheduled, rather than existing as an unused script.

Observed at the time of writing, which is the evidence that it works:

```
{
  "ok": false,
  "failures": {"x": "stale_capture"},
  "observed": {"x": {"latest_capture": "2026-10-26T14:54:37.075000+00:00", "age_hours": 223.7}},
  "max_age_hours": 24
}
STALE STRATUM: x=stale_capture
exit=2
```

## How to reopen the stratum

1. A human runs the authenticated X capture session on the laptop.
2. Captures land under `/home/tomi/laclaugpt-ai26-data/raw/x/<YYYYMMDD>/`.
3. `ai26_x_bridge.py` ingests them on its ten-minute schedule.
4. `check_ai26_capture_freshness.py --platforms x` goes green within a cycle.

Until step 1 happens, the monitor will keep saying so, every day, in the log.
