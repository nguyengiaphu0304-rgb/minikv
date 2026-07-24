# Operational event schema v1

Operational events are immutable values delivered synchronously to an optional
callback. Every event contains:

- `schema_version`: currently `1`
- `sequence`: positive and monotonic within one open handle
- `name`: one fixed allowlisted event name
- `metrics`: an exact sorted metric set for that name

## Events and metrics

| Event | Metrics |
| --- | --- |
| `store.opened` | `entries`, `log_bytes`, `recovered_bytes` |
| `mutation.put_committed` | `entries`, `log_bytes`, `sequence` |
| `mutation.delete_committed` | `entries`, `log_bytes`, `sequence` |
| `store.compacted` | `entries`, `old_log_bytes`, `new_log_bytes`, `reclaimed_bytes`, `parent_directory_fsynced` |
| `backup.published` | `entries`, `payload_bytes`, `artifact_bytes`, `replaced_existing`, `parent_directory_fsynced` |
| `restore.completed` | `entries`, `payload_bytes`, `replaced_existing`, `parent_directory_fsynced` |
| `store.closed` | `entries`, `sequence`, `log_bytes`, `events_dropped` |

Metrics are non-negative integers or booleans. Unknown names, missing/extra
metrics, duplicate or unsorted metrics, negative counts, and unsupported schema
versions are rejected.

## Privacy boundary

The schema has no field for keys, values, database paths, backup paths,
timestamps, process IDs, host identifiers, user identifiers, or exception text.
`to_dict()` copies only the four schema fields above, so event serialization
cannot accidentally inspect the store.

The callback itself is application code and can collect unrelated context.
MiniKV cannot enforce the privacy behavior of an external sink.

## Delivery semantics

Events describe completed boundaries; there are no speculative "committed"
events before durability. Delivery is synchronous and best effort. An ordinary
callback exception increments `events_dropped` but does not reverse the
operation, alter the database, or convert success into a false storage failure.

Sequences are local to a handle. `restore.completed` is a standalone sequence
starting at one. The API does not promise global ordering, durable delivery,
retry, authentication, or exactly-once external ingestion.
