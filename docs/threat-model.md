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
- A persistent owner-only sidecar and non-blocking exclusive POSIX `flock`
  prevent concurrent opens and restores by cooperating MiniKV processes.
- Database and lock-sidecar identities are rechecked before mutation and
  replacement boundaries. Kernel lock release is exercised after abrupt process
  exit.
- Operational events use exact name/metric allowlists and contain no key, value,
  path, timestamp, process, host, or exception fields.
- Synthetic evidence uses generated fixtures and records only counts, byte
  sizes, durability booleans, and SHA-256 lineage.

## Out of scope and residual risks

- CRC32 is forgeable; a malicious writer can alter data and recompute it.
- Source and parent replacement are detected at explicit boundaries, but
  platform-specific time-of-check/time-of-use races are not fully eliminated.
- Advisory locking cannot stop malicious or non-cooperating writers, and is not
  a distributed consensus or lease protocol.
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
- Reliable operation requires local POSIX `flock` semantics. Windows, inherited
  post-`fork()` handles, and filesystems with unreliable or host-local advisory
  locks are unsupported.
- Event hooks run application code synchronously. Their ordinary exceptions are
  suppressed after being counted so they cannot reverse a durable operation;
  hooks can still add latency or deliberately terminate the process.
- Events are not authenticated, durable, ordered across handles, or sufficient
  for security auditing. Consumers control any external sink and its privacy.
- Synthetic workload timings can vary with runners, filesystems, contention,
  caches, and virtualization. They are not evidence of production performance.

Applications needing adversarial integrity, confidentiality, multiple
simultaneous writers, distributed coordination, or durable remote recovery
should use a production database and appropriate platform controls.
