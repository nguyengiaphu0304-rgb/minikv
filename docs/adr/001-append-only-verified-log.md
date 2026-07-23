# ADR-001: append-only verified log

- Status: accepted
- Date: 2026-07-24

## Context

MiniKV needs a useful storage core whose correctness and recovery behavior can be
reviewed without hiding behind a database dependency. In-place mutation would
create complex partial-update cases, while JSON lines would not provide a compact
typed framing contract or an explicit checksum boundary.

## Decision

Use an append-only, versioned binary log. Every frame contains fixed-width
metadata, bounded key/value lengths, a contiguous sequence number, strict UTF-8
NFC key bytes, and CRC32 over the complete header and body.

A mutation is acknowledged only after writing the full frame, flushing the
language buffer, and calling `fsync`. Visible index state changes afterwards.
Startup reconstructs state from the log. Only an incomplete final frame is
truncated; complete invalid frames fail closed.

## Consequences

Benefits:

- Deterministic replay and a small, inspectable failure-state space.
- No production dependency.
- Corruption and torn-write behavior can be exercised with exact fixtures.

Costs:

- Startup is linear in log size.
- Old values remain until compaction.
- CRC32 does not authenticate writers.
- Single-process operation is mandatory until a locking contract exists.

Atomic compaction, backups, and concurrency control remain separate decisions.
