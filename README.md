# MiniKV

MiniKV is a small, bounded, crash-aware key-value storage engine for learning
and portfolio review. It demonstrates how an append-only log can acknowledge
mutations only after durability, rebuild deterministic state after restart, and
distinguish a torn final write from complete corrupt data.

The current `v0.4` engine is intentionally single-writer and local. It is
not a replacement for SQLite, RocksDB, Redis, or a production database.

## What it does

- Provides `open`, `get`, `put`, `delete`, `keys`, `stats`, and `close`.
- Stores immutable byte values behind Unicode NFC-normalized string keys.
- Uses a versioned, big-endian binary frame with a monotonic sequence number and
  CRC32 integrity check.
- Flushes and `fsync`s every acknowledged mutation.
- Rolls back the current frame when an injected write or flush failure occurs.
- Recovers only an incomplete final frame; complete malformed or checksum-invalid
  frames fail closed without modifying the file.
- Enforces key, value, database, and declared-frame limits before allocation.
- Rejects symbolic links and non-regular database paths.
- Acquires a non-blocking POSIX lifetime lock before opening a database and
  rejects concurrent cooperating processes with `ConcurrencyError`.
- Compacts live state into deterministic sorted frames using a private sibling
  file, independent validation, atomic replacement, and parent-directory
  `fsync` where supported.
- Publishes versioned SHA-256 backup artifacts from canonical live state and
  restores them only after envelope, digest, log, count, and canonical-form
  validation.
- Requires explicit overwrite consent for restore and preserves the prior
  destination on every handled failure before atomic replacement.
- Has no production dependencies.

## Install and verify

Python 3.11 or newer is required.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

Run the same core checks used by CI:

```bash
ruff check .
ruff format --check .
mypy
pytest
python -m build
python -m pip check
python -m pip_audit --skip-editable
```

## Example

```python
from pathlib import Path

from minikv import MiniKV

with MiniKV.open(Path("example.mkv")) as store:
    store.put("language", b"Python")
    assert store.get("language") == b"Python"
    assert store.keys() == ("language",)
    result = store.compact()
    assert result.entries == 1
    backup = store.backup(Path("example.mkvb"))
    assert backup.entries == 1
    store.delete("language")

MiniKV.restore("example.mkvb", "restored.mkv")
```

Keys are normalized to Unicode NFC. Values are copied on input and returned as
immutable `bytes`. A missing key returns `None`, while a zero-byte value returns
`b""`.

## Recovery and integrity contract

On open, MiniKV scans every frame in sequence and reconstructs the live index.
An incomplete final header, body, or checksum is treated as a torn tail and
truncated after `fsync`. Any complete frame with invalid magic, version,
operation, sequence, key encoding, declared length, or checksum raises
`CorruptionError`; the original bytes are preserved.

CRC32 detects accidental corruption but does **not** authenticate a writer.
Anyone able to rewrite the database can recompute checksums.

## Compaction contract

`compact()` writes one canonical put frame per live key in sorted key order,
with sequences restarting at one. It writes to a private sibling path with
owner-only permissions, flushes and `fsync`s it, reopens it for independent
validation, rechecks the source and parent identities, then performs an atomic
replacement. On POSIX, it also `fsync`s the parent directory.

Every handled failure before replacement preserves the original source bytes and
cleans the owned temporary file. If replacement succeeds but a later durability
or rebind step fails, the handle closes and raises `PersistenceError`; the caller
must reopen and inspect the path because the compacted file may already be
authoritative. MiniKV never reports such a case as a clean rollback.

## Backup and restore contract

`backup()` wraps the canonical live-state log in a versioned `MKB1` envelope
containing the log format, entry count, payload length, and SHA-256 digest. It
writes an owner-only sibling temporary file, flushes and `fsync`s it, reopens
and verifies the artifact, rechecks path identities, atomically publishes it,
and requests parent-directory durability.

`MiniKV.restore()` validates the entire artifact before creating a destination
temporary file. The extracted payload must pass the ordinary MiniKV scanner and
reconstruct a complete canonical log. Existing destinations require
`overwrite=True`. Every handled pre-replacement failure preserves the previous
destination; a post-replacement failure reports uncertainty and requires reopen.
Restore owns the destination's lifetime lock from before inspection through the
replacement and directory-durability boundary.

SHA-256 detects accidental modification but is not a publisher signature.
Retention, access control, encryption, and remote durability remain deployment
responsibilities.

## Concurrency contract

`MiniKV.open()` creates or reuses a persistent owner-only
`.DATABASE_NAME.lock` sibling and acquires a non-blocking exclusive POSIX
`flock` before it opens, creates, scans, or repairs the database. The lock is
held across mutations, compaction, and backup until `close()`. Restore acquires
the same destination lock for its full operation. A clean close or process exit,
including abrupt exit, releases the kernel lock.

The sidecar is deliberately not unlinked on close: unlinking could let a second
process lock a new inode while an existing process still owns the old one.
MiniKV rechecks both database and lock-file identities before mutations and
replacement boundaries. This is an advisory protocol for cooperating MiniKV
processes, not protection from software that ignores the lock.

## Design documentation

- [Architecture](docs/architecture.md)
- [Binary format](docs/format.md)
- [Threat model](docs/threat-model.md)
- [Roadmap](docs/roadmap.md)
- [Interview guide](docs/interview-guide.md)
- [ADR-001: append-only verified log](docs/adr/001-append-only-verified-log.md)
- [ADR-002: validated atomic compaction](docs/adr/002-validated-atomic-compaction.md)
- [ADR-003: canonical backup and atomic restore](docs/adr/003-canonical-backup-restore.md)
- [ADR-004: POSIX lifetime lock](docs/adr/004-posix-lifetime-lock.md)

## Current limitations

- One open writer per database is enforced only for cooperating processes on
  POSIX filesystems with reliable `flock` semantics. Windows is not supported
  by this milestone.
- No transactions across multiple keys, compare-and-swap, snapshots, or
  isolation levels.
- No encryption, authenticated writer, artifact signing, remote retention
  policy, or secure deletion.
- Compaction removes obsolete values from the active path but does not guarantee
  secure erasure from storage media, snapshots, or backups.
- Recovery tests use deterministic fault injection, not physical
  power-loss or filesystem-failure testing.
- `fsync` semantics still depend on the operating system, filesystem, and
  storage device.
- Advisory locks do not stop malicious or non-cooperating writers. Network and
  distributed filesystems may not provide the local lock semantics MiniKV
  assumes; inherited handles after `fork()` are unsupported.

The next milestone adds repeatable performance/data-quality evidence and
privacy-safe operational events before a `v1.0` release is considered.
