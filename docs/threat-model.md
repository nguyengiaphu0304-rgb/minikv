# Threat model

## Assets

- Integrity and ordering of acknowledged mutations.
- Availability of the local store after a torn final write.
- Confidentiality of application keys and values from logs and diagnostics.

## Trusted boundary

The caller, current process, operating system, filesystem, and storage device are
trusted to enforce local file permissions and implement `fsync` as documented.
Input keys, values, existing database bytes, and the final path component are
untrusted.

## Defenses in v0.1

- Strict type, Unicode, length, operation, version, sequence, and checksum
  validation.
- Bounds checked before body reads or mutation writes.
- Final-component symlink and non-regular path rejection.
- Owner-only mode requested when creating a database.
- State becomes visible only after flush and `fsync`.
- Complete corruption fails closed and leaves bytes untouched.
- Statistics contain counts and sizes, not application payloads.
- Zero production dependencies reduce supply-chain surface.
- Compaction uses an exclusive owner-only sibling file, validates reconstructed
  state before replacement, rechecks source/parent identities, and never deletes
  a colliding path it did not create.
- Backup/restore use strict versioned envelopes, bounded lengths, SHA-256,
  ordinary log replay, canonical equality, exclusive temporary files, explicit
  overwrite consent, identity rechecks, and atomic replacement.

## Out of scope and residual risks

- CRC32 is forgeable; a malicious writer can alter data and recompute it.
- Source and parent replacement are detected at explicit boundaries, but
  platform-specific time-of-check/time-of-use races are not fully eliminated.
- No inter-process lock prevents simultaneous writers.
- No encryption at rest, key management, secure deletion, or access-control
  layer is provided.
- Backup SHA-256 is not a signature or MAC. Anyone able to rewrite an artifact
  can replace both its payload and digest.
- Local backup publication does not provide remote replication, retention,
  media independence, rollback protection, or disaster-recovery policy.
- Compaction removes deleted and overwritten values from the active file, but
  storage media, snapshots, backups, or forensic recovery may retain them.
- Denial of service remains possible within configured size limits.
- No protection exists against disk rollback, media failure, or a dishonest OS.
- Fault injection does not prove behavior under physical power loss.
- After atomic replacement but before directory `fsync`, a crash can leave the
  old or new directory entry depending on filesystem semantics. An observed
  failure in that boundary closes the handle and requires reopen.
- Restoring into a path that another process has open is unsupported. Atomic
  replacement can leave that process attached to the previous inode.

Applications needing adversarial integrity, confidentiality, multi-writer
coordination, or durable remote recovery should use a production database and
appropriate platform controls.
