# Residual risks for v1.0.0

- Durability depends on the local operating system, filesystem, storage device,
  and correct `fsync`/atomic-replace semantics. CI does not simulate physical
  power loss or controller write-cache failure.
- `flock` is advisory and POSIX-only. Non-cooperating writers, Windows,
  inherited post-`fork()` handles, and network/distributed filesystems are
  unsupported.
- CRC32 detects accidental frame corruption but is not authenticated integrity.
  Backup SHA-256 detects changes but does not authenticate the publisher.
- Values are not encrypted. File permissions, device encryption, access control,
  backups, and retention remain operator responsibilities.
- There are no multi-key transactions, snapshots, readers during destructive
  restore, multi-writer isolation, replication, remote retention, or telemetry
  durability.
- Event callbacks are synchronous best-effort notifications. They can add
  latency, and dropped counts cannot reconstruct missing events.
- Synthetic evidence checks correctness and broad growth/hang budgets. It does
  not establish production throughput, tail latency, workload fitness, or
  long-duration reliability.
- Reproducible sdist publication depends on the documented `gzip -n`
  normalization step; raw build-backend gzip headers are not treated as stable.
