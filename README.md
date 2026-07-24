# MiniKV

MiniKV is a small, bounded, crash-aware key-value storage engine for learning
and portfolio review. It demonstrates how an append-only log can acknowledge
mutations only after durability, rebuild deterministic state after restart, and
distinguish a torn final write from complete corrupt data.

The current `v0.2` engine is intentionally single-process and local. It is
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
- Compacts live state into deterministic sorted frames using a private sibling
  file, independent validation, atomic replacement, and parent-directory
  `fsync` where supported.
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
    store.delete("language")
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

## Design documentation

- [Architecture](docs/architecture.md)
- [Binary format](docs/format.md)
- [Threat model](docs/threat-model.md)
- [Roadmap](docs/roadmap.md)
- [Interview guide](docs/interview-guide.md)
- [ADR-001: append-only verified log](docs/adr/001-append-only-verified-log.md)
- [ADR-002: validated atomic compaction](docs/adr/002-validated-atomic-compaction.md)

## Current limitations

- One process and one open writer only; there is no file locking.
- No transactions across multiple keys, compare-and-swap, snapshots, or
  isolation levels.
- No encryption, authenticated writer, artifact signing, backup policy, or
  secure deletion.
- Compaction removes obsolete values from the active path but does not guarantee
  secure erasure from storage media, snapshots, or backups.
- Recovery tests use deterministic fault injection, not physical
  power-loss or filesystem-failure testing.
- `fsync` semantics still depend on the operating system, filesystem, and
  storage device.

The next milestone adds validated backup/restore and explicit concurrent-open
handling, followed by repeatable performance/data-quality evidence before a
`v1.0` release is considered.
