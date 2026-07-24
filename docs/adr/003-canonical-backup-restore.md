# ADR-003: Canonical backup artifacts and atomic inactive-path restore

- Status: accepted
- Date: 2026-07-24

## Context

Copying an active append-only file can capture more history than needed and
provides no explicit artifact boundary, lineage digest, or restore contract.
Treating SHA-256 alone as validation would also accept structurally invalid
database bytes. Replacing a live destination too early could destroy the only
usable copy when parsing, writing, or validation fails.

## Decision

Backup derives the same deterministic canonical log used by compaction and wraps
it in a fixed `MKB1` v1 envelope with log version, entry count, payload length,
and SHA-256. Publication uses an exclusive owner-only sibling file, flush,
`fsync`, independent envelope verification, path-identity rechecks, atomic
replacement, and parent-directory `fsync` where supported.

Restore targets an inactive path. It validates the complete envelope before
writing, extracts into an exclusive temporary file, flushes and `fsync`s, opens
that file through the ordinary MiniKV scanner, verifies entry count,
completeness, and canonical equality, then rechecks identities and atomically
replaces the destination. Existing destinations require explicit overwrite
consent.

MiniKV deletes a temporary only when its inode matches the file created by the
current operation. Pre-replacement failure preserves the previous destination.
Post-replacement failure reports durability uncertainty and never claims a
rollback that cannot be proven.

## Consequences

- Identical live state produces identical backup bytes.
- Restore rejects transport corruption and validly hashed but invalid database
  payloads.
- Backups expose equality through their deterministic digest and are not
  confidential or authenticated.
- Memory use is bounded by the configured database ceiling but currently
  includes the canonical payload and envelope.
- Atomic replacement and directory durability retain operating-system and
  filesystem dependencies.
- Remote retention, signatures, encryption, concurrent-open coordination, and
  physical power-loss proof remain out of scope.
