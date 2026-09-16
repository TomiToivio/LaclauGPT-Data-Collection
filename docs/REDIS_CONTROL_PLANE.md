# Redis control plane

Redis is optional operational infrastructure for distributed LaclauGPT Collection. It has three independent roles:

1. **Distributed project configuration**
2. **Operational messaging/events**
3. **Distributed task leases/coordination**

Redis is not the canonical research datastore. Canonical records, media and durable outputs remain in MongoDB/CSV/SQLite/files/S3-compatible storage as configured.

## Current AI26 policy

For the current AI26 Data Collection deployment, enable **only distributed configuration**.

```text
LACLAUGPT_PROJECT_ID=ai26
LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=redis
LACLAUGPT_REDIS_URL=<private-runtime-value>

LACLAUGPT_MESSAGING_BACKEND=none
LACLAUGPT_TASK_QUEUE_BACKEND=direct
```

This lets the Linux/server collector and the researcher-laptop/browser collector share one validated project configuration revision without turning AI26 into a queue-driven collection system yet.

The messaging/event bus and Redis lease/task primitives are implemented for later use but remain disabled unless their backend flags are explicitly changed.

Merely defining `LACLAUGPT_REDIS_URL` does not activate messaging or task coordination.

## Configuration import/export

Install the distributed extra:

```bash
pip install -e '.[distributed]'
```

Push a validated local layered config to Redis:

```bash
export LACLAUGPT_PROJECT_ID=ai26
export LACLAUGPT_DISTRIBUTED_CONFIG_BACKEND=redis
export LACLAUGPT_REDIS_URL='redis://...'

laclaugpt-redis-config push \
  --project configs/studies/ai26.example.yaml \
  --private-override /path/to/private/ai26.runtime.yaml \
  --actor researcher \
  --source cli
```

The effective configuration is validated through the normal Collection configuration resolver before publication. Secret-like keys such as passwords, tokens, cookies, API keys and access keys are rejected rather than copied into Redis.

Each published config receives a content-derived revision and metadata describing the actor, source and publication time. The current revision is stored through the shared project namespace, for example conceptually:

```text
laclaugpt:ai26:settings:collection:current
laclaugpt:ai26:settings:collection:<revision>
```

A durable local JSON snapshot is written under:

```text
data/config/redis-snapshots/ai26/<revision>.json
```

This keeps reproducibility from depending on Redis persistence.

Export the current remote revision:

```bash
laclaugpt-redis-config pull \
  --output data/config/ai26.current.json
```

Inspect it:

```bash
laclaugpt-redis-config show
```

## Worker semantics

A collection worker using Redis-backed configuration should load/pin a known revision at a safe boundary, normally startup or the start of a scheduled collection run. It should record the config revision/hash in run/record provenance.

Do not silently change configuration halfway through one logical collection run. A dashboard or CLI may publish a new `current` revision, but already-running work should continue using its pinned revision until the next safe refresh boundary.

## Messaging/events

`RedisEventBus` defines a small reference-oriented envelope on the shared project event stream. It is intended for later events such as:

- collection run started/completed/failed
- canonical record stored
- browser collector connected/disconnected
- config revision changed
- human/agent command notifications

Large source payloads and media do not belong in Redis messages. Use canonical record IDs/URLs and durable object references.

For AI26 this remains disabled:

```text
LACLAUGPT_MESSAGING_BACKEND=none
```

## Task coordination

`RedisLeaseCoordinator` provides atomic claim, renew and release semantics for idempotency keys. This is sufficient groundwork for preventing two future distributed collection workers from processing the same task concurrently.

For AI26 this remains disabled and ordinary direct/scheduled collection continues:

```text
LACLAUGPT_TASK_QUEUE_BACKEND=direct
```

Enable a Redis task/queue layer only when AI26 actually has multiple collection workers competing for the same units of work.

## Separation of responsibilities

```text
Redis configuration
  -> centralized, versioned operational settings

Redis streams/messages
  -> small operational requests/events

Redis leases/tasks
  -> ephemeral coordination and duplicate-work prevention

MongoDB / CSV / SQLite / files / Allas
  -> durable research data and artifacts
```

The three Redis roles are deliberately independent so a project can use centralized configuration without also adopting messaging or distributed queue semantics.
