"""Reproducible synthetic workload and environment-specific timing evidence."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from time import perf_counter_ns
from typing import TYPE_CHECKING, Final

from minikv.store import BACKUP_HEADER, MiniKV

if TYPE_CHECKING:
    from pathlib import Path

    from minikv.events import OperationalEvent

EVIDENCE_SCHEMA_VERSION: Final = 1
WORKLOAD_ID: Final = "minikv-synthetic-v1"
FIXTURE_RECORDS: Final = 64
OVERWRITES: Final = 16
DELETES: Final = 8
EXTRA_RECORDS: Final = 3
MAX_TOTAL_NS: Final = 60_000_000_000
MAX_PHASE_NS: Final = 30_000_000_000
MAX_DATABASE_BYTES: Final = 1_048_576
MAX_BACKUP_BYTES: Final = 1_048_576
EXPECTED_PUTS: Final = FIXTURE_RECORDS + OVERWRITES + EXTRA_RECORDS
EXPECTED_FRAMES: Final = EXPECTED_PUTS + DELETES
EXPECTED_LIVE_ENTRIES: Final = FIXTURE_RECORDS - DELETES + EXTRA_RECORDS
SHA256_HEX_LENGTH: Final = 64
EXPECTED_EVENTS: Final = EXPECTED_FRAMES + 7


@dataclass(frozen=True, slots=True)
class StableEvidence:
    """Environment-independent workload facts compared byte-for-byte in CI."""

    schema_version: int
    workload_id: str
    fixture_sha256: str
    puts: int
    deletes: int
    frames_before_compaction: int
    live_entries: int
    pre_compaction_bytes: int
    compacted_bytes: int
    backup_artifact_bytes: int
    backup_payload_sha256: str
    logical_state_sha256: str
    event_count: int
    event_sha256: str
    events_dropped: int


@dataclass(frozen=True, slots=True)
class TimingObservation:
    """Observed durations that are never treated as reproducible output."""

    mutation_ns: int
    compaction_ns: int
    backup_ns: int
    restore_ns: int
    reopen_verify_ns: int
    total_ns: int


@dataclass(frozen=True, slots=True)
class EvidenceBudgets:
    """Broad smoke budgets intended to catch hangs and explosive growth."""

    max_total_ns: int = MAX_TOTAL_NS
    max_phase_ns: int = MAX_PHASE_NS
    max_database_bytes: int = MAX_DATABASE_BYTES
    max_backup_bytes: int = MAX_BACKUP_BYTES


@dataclass(frozen=True, slots=True)
class WorkloadEvidence:
    """Stable evidence plus explicitly environment-specific observations."""

    stable: StableEvidence
    observation: TimingObservation
    budgets: EvidenceBudgets

    def to_dict(self) -> dict[str, object]:
        """Return deterministic JSON-compatible field ordering."""
        return {
            "stable": asdict(self.stable),
            "observation": asdict(self.observation),
            "budgets": asdict(self.budgets),
        }


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _fixture_value(index: int, generation: int) -> bytes:
    return sha256(f"{WORKLOAD_ID}:{generation}:{index}".encode()).digest()


def _fixture_manifest() -> dict[str, object]:
    return {
        "workload_id": WORKLOAD_ID,
        "fixture_records": FIXTURE_RECORDS,
        "overwrites": OVERWRITES,
        "deletes": DELETES,
        "extra_records": EXTRA_RECORDS,
        "value_bytes": 32,
        "unicode_normalization": "NFC",
    }


def _expected_state() -> dict[str, bytes]:
    state = {f"record-{index:03d}": _fixture_value(index, 0) for index in range(FIXTURE_RECORDS)}
    for index in range(OVERWRITES):
        state[f"record-{index:03d}"] = _fixture_value(index, 1)
    for index in range(FIXTURE_RECORDS - OVERWRITES, FIXTURE_RECORDS - OVERWRITES + DELETES):
        del state[f"record-{index:03d}"]
    state["Café"] = b"normalized"
    state["binary"] = bytes(range(32))
    state["empty"] = b""
    return state


def _logical_state_digest(state: dict[str, bytes]) -> str:
    digest = sha256()
    for key in sorted(state):
        encoded = key.encode("utf-8")
        value = state[key]
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def _assert_store_state(store: MiniKV, expected: dict[str, bytes]) -> None:
    if store.keys() != tuple(sorted(expected)):
        msg = "workload key set does not match the deterministic fixture"
        raise ValueError(msg)
    if any(store.get(key) != value for key, value in expected.items()):
        msg = "workload values do not match the deterministic fixture"
        raise ValueError(msg)


def _event_digest(events: list[OperationalEvent]) -> str:
    return sha256(_canonical_json([event.to_dict() for event in events])).hexdigest()


def run_workload(directory: Path) -> WorkloadEvidence:
    """Run the fixed offline workload and return stable and observed evidence."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    database = directory / "workload.mkv"
    backup_path = directory / "workload.mkvb"
    restored_path = directory / "restored.mkv"
    expected = _expected_state()
    events: list[OperationalEvent] = []
    total_start = perf_counter_ns()

    mutation_start = perf_counter_ns()
    with MiniKV.open(database, event_hook=events.append) as store:
        for index in range(FIXTURE_RECORDS):
            store.put(f"record-{index:03d}", _fixture_value(index, 0))
        for index in range(OVERWRITES):
            store.put(f"record-{index:03d}", _fixture_value(index, 1))
        for index in range(
            FIXTURE_RECORDS - OVERWRITES,
            FIXTURE_RECORDS - OVERWRITES + DELETES,
        ):
            if not store.delete(f"record-{index:03d}"):
                msg = "deterministic delete fixture was unexpectedly absent"
                raise ValueError(msg)
        store.put("Cafe\u0301", b"normalized")
        store.put("binary", bytes(range(32)))
        store.put("empty", b"")
        mutation_ns = perf_counter_ns() - mutation_start
        before = store.stats()
        _assert_store_state(store, expected)

        compaction_start = perf_counter_ns()
        compaction = store.compact()
        compaction_ns = perf_counter_ns() - compaction_start
        _assert_store_state(store, expected)

        backup_start = perf_counter_ns()
        backup = store.backup(backup_path)
        backup_ns = perf_counter_ns() - backup_start
        events_dropped = store.stats().events_dropped

    restore_start = perf_counter_ns()
    restore = MiniKV.restore(
        backup_path,
        restored_path,
        event_hook=events.append,
    )
    restore_ns = perf_counter_ns() - restore_start

    reopen_start = perf_counter_ns()
    with MiniKV.open(restored_path, event_hook=events.append) as reopened:
        _assert_store_state(reopened, expected)
        restored_stats = reopened.stats()
    reopen_verify_ns = perf_counter_ns() - reopen_start
    total_ns = perf_counter_ns() - total_start

    if restored_stats.log_bytes != compaction.new_log_bytes:
        msg = "restored log size differs from compacted source"
        raise ValueError(msg)
    if restore.payload_sha256 != backup.payload_sha256:
        msg = "restored payload lineage differs from the backup"
        raise ValueError(msg)

    stable = StableEvidence(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        workload_id=WORKLOAD_ID,
        fixture_sha256=sha256(_canonical_json(_fixture_manifest())).hexdigest(),
        puts=FIXTURE_RECORDS + OVERWRITES + EXTRA_RECORDS,
        deletes=DELETES,
        frames_before_compaction=before.sequence,
        live_entries=len(expected),
        pre_compaction_bytes=before.log_bytes,
        compacted_bytes=compaction.new_log_bytes,
        backup_artifact_bytes=backup.artifact_bytes,
        backup_payload_sha256=backup.payload_sha256,
        logical_state_sha256=_logical_state_digest(expected),
        event_count=len(events),
        event_sha256=_event_digest(events),
        events_dropped=events_dropped + restore.events_dropped + restored_stats.events_dropped,
    )
    observation = TimingObservation(
        mutation_ns=mutation_ns,
        compaction_ns=compaction_ns,
        backup_ns=backup_ns,
        restore_ns=restore_ns,
        reopen_verify_ns=reopen_verify_ns,
        total_ns=total_ns,
    )
    evidence = WorkloadEvidence(stable, observation, EvidenceBudgets())
    verify_evidence(evidence)
    return evidence


def verify_evidence(
    evidence: WorkloadEvidence,
    *,
    expected: StableEvidence | None = None,
) -> None:
    """Validate stable lineage, data-quality invariants, and broad smoke budgets."""
    _verify_stable_evidence(evidence.stable, evidence.budgets, expected=expected)
    _verify_timing_observation(evidence.observation, evidence.budgets)


def _verify_stable_evidence(
    stable: StableEvidence,
    budgets: EvidenceBudgets,
    *,
    expected: StableEvidence | None,
) -> None:
    if stable.schema_version != EVIDENCE_SCHEMA_VERSION or stable.workload_id != WORKLOAD_ID:
        msg = "unsupported workload evidence schema or identifier"
        raise ValueError(msg)
    if expected is not None and stable != expected:
        msg = "stable workload evidence differs from the checked baseline"
        raise ValueError(msg)
    if (
        stable.puts != EXPECTED_PUTS
        or stable.deletes != DELETES
        or stable.frames_before_compaction != EXPECTED_FRAMES
    ):
        msg = "workload operation counts do not match the fixed specification"
        raise ValueError(msg)
    if (
        stable.live_entries != EXPECTED_LIVE_ENTRIES
        or stable.event_count != EXPECTED_EVENTS
        or stable.events_dropped != 0
    ):
        msg = "workload data-quality or event-delivery invariant failed"
        raise ValueError(msg)
    if (
        stable.compacted_bytes > stable.pre_compaction_bytes
        or stable.backup_artifact_bytes != stable.compacted_bytes + BACKUP_HEADER.size
    ):
        msg = "workload compaction or backup byte relationship failed"
        raise ValueError(msg)
    for digest in (
        stable.fixture_sha256,
        stable.backup_payload_sha256,
        stable.logical_state_sha256,
        stable.event_sha256,
    ):
        if len(digest) != SHA256_HEX_LENGTH or any(
            character not in "0123456789abcdef" for character in digest
        ):
            msg = "workload evidence contains an invalid SHA-256 digest"
            raise ValueError(msg)
    if stable.pre_compaction_bytes > budgets.max_database_bytes:
        msg = "workload database exceeded its evidence budget"
        raise ValueError(msg)
    if stable.backup_artifact_bytes > budgets.max_backup_bytes:
        msg = "workload backup exceeded its evidence budget"
        raise ValueError(msg)


def _verify_timing_observation(
    observation: TimingObservation,
    budgets: EvidenceBudgets,
) -> None:
    durations = (
        observation.mutation_ns,
        observation.compaction_ns,
        observation.backup_ns,
        observation.restore_ns,
        observation.reopen_verify_ns,
    )
    if any(duration < 0 or duration > budgets.max_phase_ns for duration in durations):
        msg = "workload phase exceeded its broad smoke budget"
        raise ValueError(msg)
    if observation.total_ns < 0 or observation.total_ns > budgets.max_total_ns:
        msg = "workload exceeded its broad total smoke budget"
        raise ValueError(msg)


def stable_from_dict(value: dict[str, object]) -> StableEvidence:
    """Parse a strict checked-in stable evidence object."""
    expected_fields = {field.name for field in StableEvidence.__dataclass_fields__.values()}
    if set(value) != expected_fields:
        msg = "stable evidence fields do not match the schema"
        raise ValueError(msg)

    def integer(name: str) -> int:
        candidate = value[name]
        if not isinstance(candidate, int) or isinstance(candidate, bool):
            msg = f"stable evidence field {name} must be an integer"
            raise TypeError(msg)
        return candidate

    def string(name: str) -> str:
        candidate = value[name]
        if not isinstance(candidate, str):
            msg = f"stable evidence field {name} must be a string"
            raise TypeError(msg)
        return candidate

    return StableEvidence(
        schema_version=integer("schema_version"),
        workload_id=string("workload_id"),
        fixture_sha256=string("fixture_sha256"),
        puts=integer("puts"),
        deletes=integer("deletes"),
        frames_before_compaction=integer("frames_before_compaction"),
        live_entries=integer("live_entries"),
        pre_compaction_bytes=integer("pre_compaction_bytes"),
        compacted_bytes=integer("compacted_bytes"),
        backup_artifact_bytes=integer("backup_artifact_bytes"),
        backup_payload_sha256=string("backup_payload_sha256"),
        logical_state_sha256=string("logical_state_sha256"),
        event_count=integer("event_count"),
        event_sha256=string("event_sha256"),
        events_dropped=integer("events_dropped"),
    )
