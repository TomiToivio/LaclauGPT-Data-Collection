# AI26 arena and source coverage: what is fixed, what is a decision

Four issues opened on 2026-10-23/24 describe the same shape of problem at different layers: a
**collection-side gap that the analysis layer then reports as a corpus property**. This document
records the root-cause trace for each, what this change fixes, and what is left for the study owner
because it is a *sampling* decision rather than a bug.

The measured counts below are the ones recorded in the issues (Laskin, read-only queries); this
document does not restate them as new measurements.

## #336 — 40% of analysis-grade records have no arena

**Root cause, traced in code.** Arena is never produced by the capture path for X:

- `capture_server._records_for()` builds the canonical record from the extension's payload and sets
  no `arena`; nothing in `ai26_browser.py` or `capture_server.py` mentions the field at all
  (`grep -rn arena src/laclaugpt_data_collection/{ai26_browser,capture_server}.py` → one hit, the
  child-inheritance line below).
- `capture_server._fetch_web_children()` reads the child's arena from
  `parent.source.raw_metadata.get("arena")` (`capture_server.py:390`), so an X parent without an
  arena produces external-link children without one. The `fetch_external_links_as_web_sources`
  setting therefore propagates the blank instead of surfacing it.
- The actor→arena relation the study publishes **does** exist, but only in configuration:
  `groups[<group>].accounts.x` in the study config. It is consumed when the browser tour URL list is
  built, and never applied to the records the capture returns.

**This change.** Nothing yet, deliberately: the fix is one function and one migration, and the
migration is a bulk write over live records.

**The fix, ready to be taken:**

1. *Forward.* When the capture server builds records for `platform == "x"`, resolve the posting
   handle against the study config's `groups[].accounts.x` and write
   `source.raw_metadata["arena"]` and `source.name` (the configured source label). Two lines of
   plumbing: the study config is already loaded in the server process for the tour; the handle is in
   the payload the extension posts. The child-inheritance line then works unchanged.
2. *Backfill.* The 1,334 existing blank-arena records can be filled from the same mapping, keyed by
   handle, but that is a bulk write over the production collection and needs approval (see the
   runbook's "what to ask before doing" list). Until it runs, the paper-facing denominator keeps the
   gap, and the corpus audit keeps reporting it — which is the honest state.
3. *Guard.* A record whose platform is `x` and whose handle is in no group should be **refused at
   capture** or quarantined with a reason, not stored with a blank arena: a blank arena silently
   removes the record from the stratified sample the paper computes.

## #337 — the `pause_ai` web source has produced zero records

The issue's own diagnosis is decisive: `pauseai.info` is a SvelteKit SPA whose homepage anchors are
evergreen routes, so the child-fetch path derives no date inside the study window, and its own feed
(`/rss.xml`, 121 items) is entirely older than the 2026-09-01 floor. Verified against the live site in
the issue; the mitigation already deployed is the `pauseai.bsky.social` Bluesky account (arena
`grassroots`, P1), which the repo's own collector returns records for.

**Decision (Tomi, 2026-10-25): keep it and document it as a recorded zero-yield attempt.**

The non-destructive option, chosen over retiring the row. A source that yields nothing inside the
window is evidence about the grassroots stratum's web reachability rather than a configuration
mistake to scrub, and the exclusion is worth more as a stated fact than as a tidier source list.

The documentation this decision requires **already exists**, which is why nothing new is asserted
here — it was written when the Bluesky mitigation landed:

- `configs/studies/ai26.sources.example.toml` (the `pause_ai` `[[web_source]]` row and the
  `pauseai.bsky.social` block that follows it): 5 candidates per cycle, **30 of 30 discarded before
  the 2026-09-01 publication floor** in the 24 h to 2026-10-23; `pauseai.info` is an undated
  SvelteKit site whose anchors are evergreen pages (`/about`, `/action`, `/ai-takeover`) rather
  than dated posts; its own feed is outside the window (`/rss.xml`, 121 items, newest 2026-07-06).
- `configs/studies/ai26.example.yaml`, the `grassroots_pause_resistance_x` group notes: the same
  fact stated where the group is declared, with the Bluesky verification (440 posts, newest
  2026-10-23T12:08Z).

Two consequences that follow from *keeping* it, recorded so the row is not silently counted as
expected work:

- its rotation slot is a **permanent zero, not a backlog** — a cycle that returns nothing from it
  is working as configured, not falling behind;
- the `grassroots` stratum must not be described as having web-platform evidence until a source
  actually produces records inside the window. The stratum's first-party evidence is the Bluesky
  account.

Retiring remains available and would mean deleting the row from the tracked plan and the deployed
manifest; that option is no longer the default.

## #340 — the Finnish party stratum

Unchanged by this change. PR #339 added the one verified party feed (`vihreat_press_releases`), which
is exactly the situation the issue asks the owner to rule on: one party in a stratum whose purpose is
to show how claims attach to *established cleavages* is a partisan skew, and the party feeds that
would complete the set currently yield no in-window AI material.

The four options in the issue (full major-party set; verified-AI-only; add Eduskunta via its open-data
API; how to price such sources if added) are sampling decisions, and `AGENTS.md` reserves those for
the author. Nothing here picks one.

## #342 — the frontier-lab stratum

Unchanged by this change. PR #341's sibling commit added the one verified feed
(`mistral_blog`). The rest of the labs expose no feed and the Laskin stage is feed/page-only by
design, so the arena's first declared `sampling_focus` ("frontier-lab and industry discourse") is
covered by ≈7% first-party material.

Two options, again the owner's: (a) a page-level article-list collector with datable items, run as a
non-browser job, or (b) an explicit statement in §4.1 and in the arena's `platforms` /
`stage_reachability` declaration that this stratum is browser-only and therefore out of Phase 1
scope. The important part is that **a corpus-level claim about lab discourse must not be readable as
coverage of the labs**, and that is a documentation fix only if the author decides it is.

## What the four have in common

In every case the corpus audit already reports the gap, and the pipeline does not invent data to hide
it: blank arenas stay blank, a zero-yield source stays zero, a missing stratum stays missing. The
work is to (i) stop *creating* the blank where the mapping is already known (#336 forward fix), (ii)
make a permanent zero visible as a decision rather than as a backlog (#337), and (iii) decide the two
sampling strata (#340, #342) — which is the author's call, not an implementation detail.
