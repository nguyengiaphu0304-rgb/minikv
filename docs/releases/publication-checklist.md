# v1.0.0 publication checklist

## Automated gates

- [x] Version metadata and public runtime version are `1.0.0`.
- [x] Ruff lint/format and strict MyPy pass.
- [x] Unit, boundary, corruption, crash, concurrency, demo, and package tests pass.
- [x] Synthetic demo regenerates byte-for-byte and independently verifies.
- [x] Wheel and sdist satisfy path, member-type, member-count, size, metadata,
  checksum, and file-set policy.
- [x] Two clean builds under the documented source epoch are byte-identical
  after deterministic normalization of the sdist's outer gzip header.
- [x] Wheel installs with `--no-index --no-deps` in an isolated environment and
  passes storage plus backup/restore smoke tests.
- [x] `pip check` and `pip-audit` report no known dependency issue.
- [x] CI passes on CPython 3.11, 3.12, and 3.13 and retains verified artifacts.

## Human publication gates

- [ ] Confirm all required GitHub checks passed at the chosen commit.
- [ ] Confirm no unresolved review concern and no secret/generated environment.
- [ ] Create annotated tag `v1.0.0` at the exact verified merge commit.
- [ ] Publish a non-prerelease GitHub Release using `docs/releases/v1.0.0.md`.
- [ ] Attach the verified wheel, sdist, and `SHA256SUMS`.
- [ ] Verify the public tag target, release metadata, and attached checksums.

The project must remain a release candidate until the human publication gates
are complete.
