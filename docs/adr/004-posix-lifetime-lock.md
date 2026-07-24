# ADR-004: POSIX lifetime lock

## Status

Accepted for v0.4.

## Context

Every MiniKV handle rebuilds an in-memory index and sequence counter from the
log. Two writers cannot safely coordinate by locking only individual appends:
either process could act on stale derived state. Restore and compaction also
replace directory entries, which can detach an already-open process from the
authoritative inode.

## Decision

Before opening, creating, scanning, or repairing a database, MiniKV opens a
persistent owner-only `.DATABASE_NAME.lock` sibling without following symlinks
and acquires `LOCK_EX | LOCK_NB` through POSIX `flock`.

The lock is held for the complete handle lifetime, including compaction and
backup. Restore holds the destination lock from before inspection through
replacement and directory `fsync`. A second cooperating process receives
`ConcurrencyError`. The database and sidecar inode identities are rechecked
before mutation and replacement boundaries.

The sidecar is never unlinked during normal close. Closing the descriptor or
process exit releases the kernel lock, while preserving the stable inode used by
future openers. Internal validation of exclusively created temporary files does
not acquire public sidecar locks.

## Consequences

- Independent processes cannot concurrently open or restore the same database
  through MiniKV.
- Abrupt process exit does not strand a user-space lock record.
- Lock-sidecar symlinks, non-regular paths, replacement, and backup aliases are
  rejected.
- Empty lock sidecars intentionally remain on disk.
- This release supports POSIX only. Advisory locks do not constrain
  non-cooperating software and may not be reliable on network or distributed
  filesystems.
- Multiple simultaneous writers, inherited handles after `fork()`, leases,
  lock recovery across hosts, and Windows coordination remain out of scope.
