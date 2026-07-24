# Synthetic workload evidence

## Purpose

The workload provides reproducible correctness, lineage, data-quality, and
bounded-growth evidence. It is not a production database benchmark.

## Fixed workload

`minikv-synthetic-v1` uses only generated local fixtures:

1. Insert 64 records with deterministic 32-byte values.
2. Overwrite 16 records.
3. Delete 8 records.
4. Add a decomposed Unicode key, an empty value, and binary bytes.
5. Verify the 59-entry logical state.
6. Compact, back up, restore, reopen, and verify again.
7. Serialize the privacy-safe events and compute their SHA-256 lineage.

The checked [stable baseline](../evidence/workload-v1.json) contains 83 puts,
8 deletes, 91 pre-compaction frames, byte sizes, and SHA-256 digests for the
fixture specification, logical state, backup payload, and 98-event stream.
There is no live, personal, customer, financial, or proprietary data.

## Reproduction

```bash
python scripts/workload_evidence.py \
  --baseline evidence/workload-v1.json \
  --output workload-observation.json
```

The command fails if stable evidence differs, a data-quality invariant fails, a
digest is malformed, a privacy/schema test fails, storage grows beyond 1 MiB,
any phase exceeds 30 seconds, or the complete workload exceeds 60 seconds.

## Timing interpretation

`workload-observation.json` includes nanosecond durations for mutation,
compaction, backup, restore, reopen verification, and the total run. CI uploads
one observation per Python version for 14 days.

These durations depend on CPU scheduling, filesystem, storage cache,
virtualization, runner load, Python build, and operating-system behavior. The
budgets are intentionally broad hang detectors. The project does not publish
operations per second, latency percentiles, cross-machine comparisons, or
claims of production capacity from this evidence.

## Known gaps

- No physical power-loss or storage-device fault test.
- No Windows, network-filesystem, or distributed-lock measurement.
- No long-duration soak, high-cardinality, multi-process throughput, memory
  profile, or tail-latency study.
- Synthetic state does not model a specific application's key/value
  distribution.
