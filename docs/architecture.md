# Architecture

MiniKV separates an immutable public API contract from an append-only
persistence mechanism.

## Components

1. `MiniKV.open` acquires a non-blocking exclusive POSIX lifetime lock, validates
   the target, opens it without following a final-component symlink, and bounds
   the file before scanning.
2. The scanner validates each binary frame and rebuilds an in-memory dictionary.
3. The mutation path serializes one complete frame, appends it, flushes and
   `fsync`s it, and only then changes visible state.
4. The recovery path truncates only an incomplete final frame. Complete invalid
   frames stop startup without altering the file.
5. `StoreStats` exposes only counts and byte sizes, never keys or values.
6. Compaction derives a canonical log from sorted live keys, writes and validates
   a private sibling file, atomically replaces the source, requests directory
   durability, and rebinds the active handle.
7. Backup wraps the same canonical log in a strict `MKB1` envelope, then
   independently verifies and atomically publishes the artifact.
8. Restore locks the destination, validates the envelope and SHA-256 before writing, runs the extracted
   payload through the ordinary startup scanner, checks canonical equality, and
   atomically replaces only a destination it exclusively coordinates.
9. The event boundary constructs immutable allowlisted metrics only after each
   successful state transition. Callback failures increment a dropped count
   without changing persistence outcomes.
10. The evidence runner executes a fixed synthetic lifecycle, separates stable
    lineage from observed durations, and compares stable facts with a checked
    baseline.

```text
caller
  |
  v
lifetime lock -> public validation -> frame encoder -> append / flush / fsync
  |                                      |
  |                                      v
  +------------------------------> append-only file
                                           |
                                           v
                                  verified startup scan
                                           |
                                           v
                                  in-memory live index
```

## Correctness boundaries

- The file is the source of truth. The index is derived and never serialized.
- Sequence numbers must be contiguous from one, preventing silent frame
  reordering or omission within the scanned log.
- Index state changes only after durability has been requested successfully.
- Failure before acknowledgement attempts to truncate back to the last durable
  offset. If rollback cannot be confirmed, the handle closes and fails loudly.
- String keys have exactly one stored representation: strict UTF-8 in NFC.
- Compaction rechecks the open file and parent-directory identities before
  replacement, so path substitution is rejected rather than overwriting an
  unrelated file.
- A pre-replacement failure preserves the source. A post-replacement durability
  failure closes the handle and requires explicit reopen because rolling back
  safely can no longer be guaranteed.
- Backup and restore capture source, destination, and parent identities and
  recheck them at the final replacement boundary. Temporary collisions are
  never deleted unless MiniKV created and still owns the same inode.
- Restore never treats an envelope digest as sufficient validation. The payload
  must satisfy the binary log, entry-count, completeness, and canonical-order
  contracts before the destination can change.
- The lock is acquired before database inspection and held until close. The
  persistent sidecar preserves a stable lock inode across clean close and crash.
  Database and lock identities are checked before every mutation and destructive
  replacement boundary.
- Event construction accepts only fixed names and exact per-name metric sets.
  Application payloads and environment identifiers never enter the event model.
- Timing observations are not part of the reproducibility contract. CI compares
  operation counts, byte sizes, logical-state, backup, fixture, and event
  digests while applying only broad timing smoke budgets.

## Deliberate scope

The engine optimizes for a readable storage contract, deterministic tests, and
explicit failure behavior. It coordinates one writer among cooperating POSIX
processes, but does not claim malicious-writer exclusion, distributed locking,
remote backup durability, or database-grade transactional guarantees. Backup
artifacts provide portable recovery evidence, not retention policy, encryption,
or authenticated provenance. Operational events are observability hints rather
than a durable audit log, and the synthetic workload is correctness evidence
rather than a production benchmark.
