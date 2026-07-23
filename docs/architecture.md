# Architecture

MiniKV separates an immutable public API contract from an append-only
persistence mechanism.

## Components

1. `MiniKV.open` validates the target, opens it without following a
   final-component symlink, and bounds the file before scanning.
2. The scanner validates each binary frame and rebuilds an in-memory dictionary.
3. The mutation path serializes one complete frame, appends it, flushes and
   `fsync`s it, and only then changes visible state.
4. The recovery path truncates only an incomplete final frame. Complete invalid
   frames stop startup without altering the file.
5. `StoreStats` exposes only counts and byte sizes, never keys or values.

```text
caller
  |
  v
public validation -> frame encoder -> append / flush / fsync
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

## Deliberate scope

The foundation optimizes for a readable storage contract, deterministic tests,
and explicit failure behavior. It does not claim multi-process coordination or
database-grade transactional guarantees. Compaction and validated backup are
separate milestones because both require additional atomic-replacement and
recovery contracts.
