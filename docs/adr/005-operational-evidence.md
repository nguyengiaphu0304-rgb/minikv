# ADR-005: privacy-safe events and deterministic evidence

## Status

Accepted for v0.5.

## Context

Operational visibility can leak keys, values, paths, host identity, or exception
content. Performance numbers can also mislead when nondeterministic CI timing is
presented as a reproducible or production claim. MiniKV needs evidence useful
for review without weakening its data boundary or honesty.

## Decision

MiniKV exposes immutable schema-v1 events with exact names and per-event metric
allowlists. Only counts, byte sizes, sequence values, operation categories, and
durability booleans are representable. Events are emitted after successful
boundaries. Ordinary hook exceptions increment a drop counter and cannot reverse
or falsely fail an acknowledged operation.

A fixed offline workload records environment-independent operation counts, byte
sizes, and SHA-256 lineage in a checked baseline. CI regenerates those fields
exactly. Timing is stored separately as a per-run observation and checked only
against broad smoke budgets.

## Consequences

- Core storage remains dependency-free and application payloads do not enter the
  event model.
- Consumers receive explicit delivery and privacy limits rather than an implied
  durable audit-log guarantee.
- Stable evidence detects format, behavior, or fixture drift across supported
  Python versions.
- Timing artifacts support investigation but cannot substantiate throughput,
  latency-percentile, or production-readiness claims.
- Synchronous hooks can add latency, and external sinks remain responsible for
  durability, retries, access control, and any additional context they attach.
