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

The design needs an explicit lock and lifetime rules, stale-handle behavior, and
tests across independent processes. Merely relying on append mode would not make
sequence allocation or index state safe.

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

Concurrent-open handling needs a clear lock lifetime, stale-handle behavior, and
independent-process tests. A lock around individual writes would be insufficient
because each process also maintains a derived in-memory index and sequence.
