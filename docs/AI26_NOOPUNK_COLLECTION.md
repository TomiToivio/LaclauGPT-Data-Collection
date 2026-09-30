# AI26 collection on NooPunk

This is the **NooPunk** profile for AI26 collection: the **always-on browser capture
node**. Firefox/browser capture runs continuously here because it needs an
interactive session, which is exactly why it is not a Laskin duty.

It is a specialisation of [`AI26_LOCALHOST_COLLECTION.md`](AI26_LOCALHOST_COLLECTION.md)
— same mechanism, same scripts, same shared sink — narrowed to this node's role.
Laskin remains the always-on **non-browser** collector and the always-on analysis
node; see [`AI26_TWO_MACHINE_COLLECTION.md`](AI26_TWO_MACHINE_COLLECTION.md) and
`TomiToivio/LaclauGPT#71`.

```text
NooPunk
  continuous: Firefox / browser capture (interactive session, localhost capture)
        │
        └─ upserts into the SHARED canonical AI26 sink
             MongoDB <project>__records · Redis namespace · CSC Allas / S3
```

NooPunk does **not** keep a parallel corpus. There is no NooPunk database, bucket,
project id, run id or codebook: machine identity is execution provenance, **never study identity**. That rule is what keeps the two machines one system rather than two
corpora, and it is the reason a browser capture made here is processable by Laskin's
media and analysis workers without copying a local tree.

## Role policy

| surface | policy on this node |
| --- | --- |
| browser capture | **always on** — the primary duty |
| non-browser collectors | supported, but Laskin is the primary always-on non-browser node |
| analysis | off by default, user activated |
| visualization | off by default, user activated |

Collection must remain active **even when analysis and visualization are stopped**.
That independence is deliberate: this node's value to the shared corpus is that it
keeps capturing while the user is doing something else.

## What is reused, not reimplemented

This runbook adds no script. It uses the existing localhost profile, which already
implements the whole browser-capture contract:

| step | existing mechanism |
| --- | --- |
| browser capture into the shared sink | `scripts/run_ai26_localhost_collect.sh` |
| persist pending media and refresh downstream readiness | `scripts/run_ai26_localhost_media.sh` |
| mirror/refresh into the shared namespace | `scripts/run_ai26_localhost_sync.sh` |
| runtime resolution (PATH, lock, command checks) | `scripts/ai26_runtime.sh` |

The only thing this document changes relative to the generic localhost profile is
*intent and scheduling*: capture here is meant to be continuous rather than an
occasional manual run.

## Install

As in the localhost profile — copy the public templates to ignored `data/config/`
and never commit endpoints, credentials, cookies, private target lists or browser
profiles:

```bash
cd <absolute-repo-path>
python -m venv .venv && source .venv/bin/activate
pip install -e '.[distributed,feeds,youtube,documents]'
mkdir -p data/config data/logs data/tmp
cp configs/studies/ai26.example.yaml data/config/ai26.yaml
cp configs/studies/ai26.sources.example.toml data/config/ai26.sources.toml
cp configs/studies/ai26.collection-codebook.yaml data/config/ai26.collection-codebook.yaml
cp .env.example data/config/ai26-noopunk.env
```

## Running capture continuously

`LACLAUGPT_ENV_FILE` selects the NooPunk runtime env rather than the generic one:

```bash
export LACLAUGPT_ENV_FILE=<absolute-repo-path>/data/config/ai26-noopunk.env
export LACLAUGPT_MACHINE=laptop          # interactive workstation
```

A capture cycle is **bounded and restart-safe** by design, so "continuous" is
achieved by repeating it, not by a long-lived process. On NooPunk the appropriate
mechanism is a **user** timer (an interactive session is required for browser
capture, so a `systemd --user` timer is the right shape here):

```bash
# ~/.config/systemd/user/ai26-noopunk-collect.service
#   ExecStart=<absolute-repo-path>/scripts/run_ai26_localhost_collect.sh
# ~/.config/systemd/user/ai26-noopunk-collect.timer
#   OnCalendar=*:0/15          # every 15 minutes, staggered against Laskin's :10/:30
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now ai26-noopunk-collect.timer
systemctl --user list-timers ai26-noopunk-collect.timer
```

If a user timer is unavailable, `cron` with the same cadence works — the wrapper
already resolves its own PATH for cron (see the note in `scripts/ai26_runtime.sh`
about cron's minimal PATH, which is why a hand-run script can fail silently under
cron). Whatever mechanism you choose, keep the lock: the wrappers take an `flock`,
so an overlapping tick exits cleanly instead of double-capturing.

### Staggering

Laskin collects at `:10` and processes media at `:30` (hourly). The existing
localhost installer (`scripts/install_cron_ai26.sh`) uses `:10` for sync, `:17` for
capture and `:27` for media — **`:10` collides with Laskin's collection tick**, so
that schedule is not suitable unchanged on this node.

Pick minutes that miss `:10` and `:30` entirely, keeping the three jobs ordered
sync → capture → media inside the hour:

```text
:05  sync      (Laskin starts at :10; finish before it)
:15  capture
:25  media
```

Any set that avoids `:10` and `:30` is fine; the ordering and the gaps are what
matter. Running sync immediately before capture means the capture tick writes into a
namespace that was just refreshed.

## Verifying capture

Confirm on the **shared** store, not locally:

1. new canonical records exist in `<project>__records` carrying the versioned
   `handoff` delivery envelope (`docs/CANONICAL_RECORD_CONTRACT.md`);
2. their provenance records this node's machine class and execution profile, and
   that provenance is separable from scientific source identity;
3. a browser-captured item that has pending media is picked up by the media worker
   *from the shared namespace*, not from a local JSONL copy;
4. re-running a cycle does not duplicate records — the upsert/dedup rule is
   idempotent, so a retry is harmless.

Existence of a Firefox window is not evidence of collection; a healthy node shows a
*recent* record in the shared store.

## Restart safety and offline behaviour

The capture cycle is restart-safe: an interrupted run leaves a reclaimable state
rather than a half-written record, and the next cycle continues. NooPunk must be able
to keep capturing while Laskin is unavailable; items simply accumulate in the shared
namespace until Laskin's workers run. Capture must not depend on Laskin being up.

If the shared backend is unreachable, the correct behaviour is to **fail loudly**
rather than silently write to a local store — a local fallback would fork the corpus
while appearing to work.

## Safety

- Credentials, session secrets, cookies and browser profiles never enter this
  repository. Keep them in the ignored runtime directory, and NooPunk-specific
  values in `TomiToivio/LaclauGPT-Private`.
- Do not commit private target lists or source manifests.
- Retaining compatibility with the project's existing Firefox-based collection
  tooling is required; this runbook does not replace it.

## Related

- [`AI26_LOCALHOST_COLLECTION.md`](AI26_LOCALHOST_COLLECTION.md) — the generic laptop profile
- [`AI26_TWO_MACHINE_COLLECTION.md`](AI26_TWO_MACHINE_COLLECTION.md) — the two-machine contract
- [`AI26_LASKIN_COLLECTION.md`](AI26_LASKIN_COLLECTION.md) — the non-browser node
- [`BROWSER_CAPTURE.md`](BROWSER_CAPTURE.md) — capture mechanics
- `TomiToivio/LaclauGPT` → `docs/AI26_EXECUTION_ARCHITECTURE.md` — the two-machine roles
