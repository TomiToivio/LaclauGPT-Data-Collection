# Optional collection messaging/task adapter

Data Collection supports the umbrella LaclauGPT messaging/task contract in two modes:

- **direct**: default, no Redis package or service required;
- **redis**: optional Redis Streams publication for distributed handoff.

Redis is coordination only. Canonical records and large artifacts must be committed to MongoDB, SQLite, S3/Allas or the filesystem **before** the collection worker publishes a downstream event/task. Queue messages contain durable references, not corpora, media, transcripts, codebooks or other large/private payloads.

## Configuration

Direct mode requires nothing:

```text
LACLAUGPT_MESSAGING_BACKEND=none
LACLAUGPT_TASK_QUEUE_BACKEND=direct
```

For Redis mode install the optional dependency and configure the private runtime environment:

```bash
pip install 'laclaugpt-data-collection[distributed]'
export LACLAUGPT_REDIS_URL='<private-runtime-value>'
```

Then select Redis explicitly in the relevant runtime settings:

```text
LACLAUGPT_MESSAGING_BACKEND=redis
LACLAUGPT_TASK_QUEUE_BACKEND=redis
```

Never commit the Redis URL, credentials or private endpoint.

## Publishing after durable commit

```python
from laclaugpt_data_collection.messaging import (
    DurableRef,
    TaskEnvelope,
    idempotency_key,
    publisher_from_environment,
)

# 1. Persist/upsert the canonical record first.
# record_store.upsert(record)

publisher = publisher_from_environment(
    project_id="ai26",
    backend="redis",  # use "direct" for the no-Redis path
)

identity = "https://example.invalid/synthetic/1"
envelope = TaskEnvelope(
    project_id="ai26",
    run_id="run-synthetic",
    task_type="collection.complete",
    source_url=identity,
    idempotency_key=idempotency_key(
        project_id="ai26",
        operation="collection.complete",
        identity=identity,
        revision="collector-v1",
    ),
    schema_revision="research-record-1.0",
    config_revision="synthetic-config-v1",
    refs=(
        DurableRef(
            kind="mongodb",
            uri="mongodb-ref://ai26/records/synthetic-1",
        ),
    ),
)
publisher.publish("collected", envelope)
```

The same adapter can request downstream analysis after the durable collection record exists:

```python
envelope = TaskEnvelope(
    project_id="ai26",
    run_id="run-synthetic",
    task_type="analysis.requested",
    source_url=identity,
    idempotency_key=idempotency_key(
        project_id="ai26",
        operation="analysis.requested",
        identity=identity,
        revision="analysis-contract-v1",
    ),
    refs=(DurableRef(kind="mongodb", uri="mongodb-ref://ai26/records/synthetic-1"),),
)
publisher.publish("analysis-requested", envelope)
```

Publication is idempotent in Redis mode. The adapter atomically checks the project-scoped idempotency key and appends to the stream in one Lua script, so equivalent work is not published twice.

A failed Redis publication does not roll back or mutate the already committed durable record. Callers may retry publication safely with the same idempotency key.

## Streams and heartbeats

Project-scoped names use the shared namespace helpers:

```text
laclaugpt:<project_id>:stream:collected
laclaugpt:<project_id>:stream:analysis-requested
laclaugpt:<project_id>:worker:collection:<worker_id>
```

Long-running collectors may publish an expiring heartbeat:

```python
publisher.heartbeat(
    run_id="run-synthetic",
    worker_id="server-collector-1",
    status="busy",
    current_task_id="task-1",
    metadata={"source": "rss"},
)
```

Heartbeats are transient operational state, not audit history.

## Privacy boundary

`TaskEnvelope` deliberately exposes only scalar metadata and durable references. Full text/media and nested arbitrary payloads do not belong in Redis. Public tests/examples must remain synthetic and no log or safe settings summary should contain Redis connection values.
