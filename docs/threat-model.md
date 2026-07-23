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

## Out of scope and residual risks

- CRC32 is forgeable; a malicious writer can alter data and recompute it.
- Parent-directory replacement and platform-specific path races are not fully
  eliminated.
- No inter-process lock prevents simultaneous writers.
- No encryption at rest, key management, secure deletion, or access-control
  layer is provided.
- Deleted and overwritten values remain recoverable from the append-only file.
- Denial of service remains possible within configured size limits.
- No protection exists against disk rollback, media failure, or a dishonest OS.
- Fault injection does not prove behavior under physical power loss.

Applications needing adversarial integrity, confidentiality, multi-writer
coordination, or durable remote recovery should use a production database and
appropriate platform controls.
