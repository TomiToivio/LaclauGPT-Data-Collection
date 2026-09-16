# Multi-collection Firefox capture

The Firefox collector can run several study/campaign configurations through one localhost backend. Dataset separation is metadata-based, not port-based.

Use private ignored study configurations whose `study` values are the desired collection IDs, for example `ai26` and `brazil26`.

```bash
laclaugpt-multi-capture \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/ai26.yaml" \
  --study-config "$LACLAUGPT_PRIVATE_CONFIG_DIR/brazil26.yaml" \
  --data-root ./data/browser \
  --host 127.0.0.1 \
  --port 8765
```

The existing Firefox extension continues to post captures to `http://127.0.0.1:8765`. The backend attributes a capture from its configured account/page URL. `/tour` returns account rows with `collection_id`, and `/status` lists the active collection IDs.

Each normalized record contains a top-level `collection_id` plus the same value in collection provenance/source metadata. `arena` is preserved where the configured target supplies one. The local deduplication identity is effectively `(collection_id, source_url)`, so the same public source can belong to AI26 and Brazil26 without one study erasing the other.

When more than one collection is active, unattributed captures are not guessed. A caller may explicitly include `collection_id` in the `/capture` JSON envelope when attribution cannot be inferred from the page URL.

The generic media downloader already uses `collection_id` in its media key. Distributed sync now also scopes its Redis lease by `collection_id + source_url`, and MongoDB stores `project_id`, `collection_id`, and `arena` as queryable routing metadata.

For the first distributed AI26 test it is still simplest to use:

```text
project_id = ai26
collection_id = ai26
```

A later multi-campaign shared runtime may use a broader runtime `project_id` while retaining `collection_id=ai26` / `collection_id=brazil26` on each record. Private source/account lists and credentials remain outside this public repository.
