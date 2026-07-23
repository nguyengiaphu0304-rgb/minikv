# Roadmap

## v0.1 — verified append-only foundation

- [x] Strict public API and bounded binary format.
- [x] Put, get, delete, deterministic key listing, and non-sensitive stats.
- [x] Flush/`fsync` acknowledgement boundary and injected rollback tests.
- [x] Torn-tail recovery and fail-closed corruption handling.
- [x] Package, typed API, documentation, and Python 3.11–3.13 CI.

## v0.2 — lifecycle and operational evidence

- [ ] Atomic compaction with crash-boundary tests and source-log preservation.
- [ ] Validated backup/restore with logical-content equality evidence.
- [ ] Explicit concurrent-open rejection or inter-process locking contract.
- [ ] Deterministic performance and data-quality report with budgets.
- [ ] Structured operational events that do not expose keys or values.

## v1.0 — portfolio release

- [ ] Reproducible demo and verified wheel/sdist contents.
- [ ] Release notes, publication checklist, and residual-risk review.
- [ ] Recovery verification on supported operating-system/filesystem combinations.
- [ ] Annotated tag and non-prerelease GitHub Release at the verified commit.

Potential work after v1.0 includes batch transactions and snapshots. Encryption,
distributed consensus, and network service concerns are intentionally excluded
unless a future design can add them without weakening the local storage contract.
