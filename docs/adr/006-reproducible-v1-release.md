# ADR-006: reproducible v1 release evidence

## Status

Accepted for the v1.0 release candidate.

## Decision

The release uses a synthetic deterministic demo, a strict package verifier,
isolated wheel installation, SHA-256 checksums, and a support matrix that
separates verified Ubuntu CI behavior from expected, unsupported, and unverified
environments. Release artifacts have explicit path, type, count, size, metadata,
and file-set boundaries.

Hatchling's sdist tar content follows the fixed source epoch, but the outer gzip
header can record build-time metadata. CI rewrites only that compression header
with `gzip -n` before comparing and publishing the two builds. The normalized
sdists and wheels must then be byte-identical; their archive members are still
independently inspected before installation.

An annotated tag and GitHub Release are human publication gates after the
verified commit is merged. Source readiness alone does not constitute a public
release.

## Consequences

- Reviewers can reproduce the lifecycle without private or live data.
- Archive inspection treats packages as untrusted input before installation.
- CI timing and virtual filesystems cannot be presented as physical durability
  or production-performance proof.
- Artifact signing and authenticated publishing remain residual risks rather
  than implied guarantees.
