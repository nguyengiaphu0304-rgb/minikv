# Interview guide

## Why an append-only log?

It makes acknowledgement and recovery boundaries visible. An overwrite updates
the derived index but never edits an earlier frame in place, reducing the number
of partial-write states. The cost is unbounded growth until compaction exists.

## Why rebuild the index?

The log remains the single source of truth. A serialized index would introduce
a second durability protocol and disagreement states. Rebuild is bounded by the
configured database size; later checkpoints could optimize startup with their
own verification contract.

## Why truncate only incomplete tails?

A short final frame is consistent with interruption during append. A complete
bad frame may indicate media corruption, tampering, or a software defect.
Truncating it automatically would convert detectable loss into silent loss.

## Why CRC32?

It is dependency-free and adequate for detecting common accidental corruption in
this educational milestone. It is deliberately documented as non-authenticating.
A security boundary would require a MAC or signature plus key management and
publisher identity.

## Why update the index after `fsync`?

Returning success before requesting durability can expose state that disappears
after restart. MiniKV updates visible process state only after the write, flush,
and `fsync` path succeeds. An injected failure rolls the frame back; an
unconfirmable rollback closes the handle.

## What would change for multiple writers?

MiniKV deliberately rejects multiple writers. A POSIX lifetime lock is acquired
before scanning and held until close because each process owns a derived index
and the next sequence number. Locking only individual appends would allow those
views to become stale. Supporting concurrent writers would require a different
coordination and isolation design, not a narrower lock.

## Why keep an empty lock sidecar after close?

The inode is the rendezvous point for `flock`. If a process unlinked it while
another process still had that inode open, a newcomer could create and lock a
different inode and both would believe they held the database lock. Persistence
avoids that split-brain race; the file carries no application data.

## What does the lock not guarantee?

It is advisory and protects only cooperating MiniKV processes on POSIX systems
with reliable local `flock` semantics. Code that ignores the sidecar can still
rewrite the database. It is not a distributed lease, authentication mechanism,
or substitute for transaction isolation. Windows and inherited handles after
`fork()` are outside the verified contract.

## Why are events emitted only after success?

An event named `mutation.put_committed` must correspond to a mutation that
crossed the write, flush, and `fsync` boundary. Emitting before persistence could
create a false audit trail. If the callback then fails, MiniKV counts the drop
but does not report the already-durable operation as failed.

## Why not put timestamps, paths, or exception text in events?

Those fields are common routes for application data and host identity to leak
into logs. MiniKV's fixed schema provides the operational signals it can defend:
counts, byte sizes, sequence values, operation categories, and durability
booleans. Applications can add deployment context outside the storage boundary
under their own data policy.

## Is the synthetic workload a benchmark?

No. The stable contract is the same operation counts, byte counts, logical-state
digest, backup digest, and event digest. Durations are recorded separately and
only checked against generous smoke limits that catch hangs. Claiming throughput
or latency from one virtualized CI runner would be misleading.

## How is compaction made reviewable?

Compaction rewrites all live state and replaces the authoritative file. It needs
a temporary-file allowlist, flush and `fsync` ordering, atomic replacement,
directory durability where supported, rollback/failure injection, and proof that
the original remains recoverable at every pre-replacement boundary. MiniKV also
validates the temporary file through the normal independent startup scanner and
rechecks file identities immediately before replacement.

The important honesty boundary is after replacement: if directory `fsync` or
rebinding fails, the code cannot truthfully claim rollback. It closes the handle,
reports that replacement occurred, and requires a reopen.

## Why does a backup have both SHA-256 and ordinary log validation?

SHA-256 proves that payload bytes match the envelope, but it does not prove those
bytes form a valid database. Restore also runs the ordinary scanner, checks
entry count and completeness, and regenerates the canonical log. This separates
transport integrity from storage-format correctness.

## Why is overwrite opt-in during restore?

Restore is an administrative operation with a larger blast radius than open or
put. Requiring `overwrite=True` prevents a typo from silently replacing an
existing database. Even with consent, the old destination remains untouched
until the validated temporary payload reaches the atomic replacement boundary.

## Is the backup authenticated or a full disaster-recovery system?

No. SHA-256 detects corruption but a malicious writer can replace the digest.
The project does not provide signatures, encryption, remote retention,
replication, or restore orchestration. Those limits are explicit rather than
hidden behind a "backup complete" message.

## Highest-risk next change

The release candidate must package reproducible demo evidence without confusing
archive reproducibility, synthetic workload correctness, or CI smoke timings
with physical power-loss testing or production readiness.
