# ADR-002: validated atomic compaction

- Status: accepted
- Date: 2026-07-24

## Context

The append-only v1 log retains overwritten and deleted values and grows with
mutation history. In-place rewriting would expose the authoritative file to
partial writes. Replacing it without independent validation could atomically
publish a well-formed but logically incorrect result.

## Decision

`compact()` derives a canonical byte stream containing one sorted put frame per
live key. It creates one deterministic private sibling path with exclusive
creation and owner-only permissions. A pre-existing path of any type is treated
as unowned and blocks compaction.

The operation writes the complete stream, flushes and `fsync`s it, then opens it
through the ordinary scanner and compares reconstructed logical state, sequence,
and byte size. It rechecks the source file and parent-directory identities before
using atomic replacement. On POSIX it then `fsync`s the parent directory and
rebinds the live handle to the replacement.

Fault boundaries cover partial write, complete write, flush, validation, replace,
and post-replacement directory durability. Owned temporary files are removed
after handled pre-replacement failures.

## Consequences

Benefits:

- Identical logical state yields byte-identical compacted v1 logs.
- The authoritative source is untouched until a complete validated replacement
  is ready.
- Active-handle writes continue safely after a successful rebind.
- Results expose counts and byte sizes without keys or values.

Costs and residual risks:

- Compaction requires free space for a second bounded copy.
- A deterministic temporary name permits denial of service through an unowned
  collision, chosen instead of deleting an ambiguous file.
- Atomic replacement and directory durability remain filesystem-dependent.
- A failure after replacement cannot promise rollback; the handle closes and
  callers must reopen.
- Compaction is not secure erasure and does not add multi-process locking.
