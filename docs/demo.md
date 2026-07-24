# Reproducible v1.0 demo

The release demo is offline and contains only generated synthetic values. It
exercises durable mutation, Unicode NFC normalization, empty and binary values,
delete and overwrite behavior, compaction, backup, restore, reopen verification,
corrupted-backup rejection, cooperative concurrent-open rejection, and
best-effort event-hook failure handling.

```bash
python scripts/demo.py --output demo-output
python scripts/demo.py --verify demo-output
```

The output is limited to `manifest.json` and `summary.md`. The manifest records
only version, counts, booleans, supported-platform text, and SHA-256 lineage. It
contains no generated keys or values, paths, timestamps, process or host
identifiers, and no timing measurements.

Generating the demo twice must produce byte-identical files. Verification
re-executes the complete workload independently and rejects field drift, file-set
drift, checksum mismatch, incorrect version, missing synthetic marker, logical
recovery mismatch, accepted corruption, or failed concurrency rejection.

This demonstrates reproducible software behavior on a cooperating local POSIX
filesystem. It is not physical power-loss evidence, a production benchmark, a
distributed-filesystem guarantee, or a security audit.
