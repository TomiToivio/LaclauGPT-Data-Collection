# Issue #392: AI26 three-host rollout verification

This is an **operator runbook**, not proof that credentials or access are available.
Never commit local study manifests, env files, AWS credentials, or complete effective
configuration dumps. Existing blocked steps remain blocked until each operator
runs the commands on that host.

## 1. Shared MongoDB and worker (Ubuntu desktop and WSL laptop)

Provision the **shared** URI in `data/config/ai26-localhost.env`, not
`mongodb://127.0.0.1:27017` unless that address is deliberately tunneled to
the shared service. Provision required Redis/S3 credentials separately.
Install the non-browser extras and supply the private AI26 sources manifest.
Then run:

```bash
set -a; source data/config/ai26-localhost.env; set +a
LACLAUGPT_AI26_DISTRIBUTED_JOBS=1 bash scripts/run_ai26_localhost_collect.sh
python -m laclaugpt_data_collection.ai26_localhost_collect --status
```

The status command checks the shared queue; it does not prove that a worker is
actively running, so inspect job leases and the cron/systemd logs too.
Do not change cron scheduling or sampling targets without an operator decision.

## 2. S3 and archival

Obtain CSC credentials through the approved private workflow. Check quota and
write permission before running `scripts/run_ai26_localhost_media.sh`.
Validate object manifests and downloads as in #373. Never report an upload
until the S3 backend confirms it. An Allas quota refusal remains blocking.

## 3. Three-host effective-config comparison

On **each** of Laskin, Ubuntu desktop, and the WSL laptop, in its AI26 checkout:

```bash
python scripts/ai26_config_fingerprint.py \
  --sources data/config/ai26.sources.toml \
  --study data/config/ai26.yaml > /tmp/ai26-fingerprint.json
```

Transfer **only** the output JSON reports (not the private YAML/TOML)
to one trusted machine, naming them `laskin.json`, `desktop.json`,
`wsl.json`, then run:

```bash
python scripts/ai26_config_fingerprint.py --compare \
  laskin.json desktop.json wsl.json
```

Exit 0 / `match` means normalized source and study configurations have
identical hashes on all three hosts. Exit 1 means missing/incompatible or
mismatched reports. Exit 2 is a read/parse error. This is a parity gate,
not a runtime connectivity or credential validity check. Canonicalization
ignores TOML/YAML formatting, but preserves actual configuration values.
Hashes can reveal equality of a guessed sensitive value, so share reports
only with the authorized project team.

## 4. WSL capture and hygiene

On WSL, verify the `ai26-capture.service` and Firefox extension separately
and inspect `/status`, newly written canonical records, and mirror errors.
Capture timestamps are **not** publication timestamps. Keep out-of-window
records in the audit trail and exclude them from analysis with the existing
`publication_date_floor` policy until retention policy is explicitly changed.
Do not delete or rewrite historical captures by default.

Investigate truncated raw JSONL writes with a concurrency-safe append design
and regression tests before altering the writer. Do not imply the malformed
historical lines have been repaired by this runbook.

## Completion gate

Mark #392 complete only after operator evidence exists for shared queue
leases, source manifest deployment, Allas write/read validation, WSL capture
and mirror, three matching fingerprint reports, and a documented decision
on capture hygiene. These are **not** verified by this repository change.
