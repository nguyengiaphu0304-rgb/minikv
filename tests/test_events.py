from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from minikv import EVENT_SCHEMA_VERSION, MiniKV, OperationalEvent, PersistenceError
from minikv.events import operational_event


def test_events_cover_success_boundaries_without_sensitive_content(tmp_path: Path) -> None:
    database = tmp_path / "private-database-name.mkv"
    backup = tmp_path / "private-backup-name.mkvb"
    restored = tmp_path / "private-restore-name.mkv"
    fixture_key = "customer-sensitive-key"
    fixture_value = b"customer-sensitive-value"
    events: list[OperationalEvent] = []

    with MiniKV.open(database, event_hook=events.append) as store:
        store.put(fixture_key, fixture_value)
        store.put("deleted-secret", b"deleted-value")
        store.delete("deleted-secret")
        store.compact()
        store.backup(backup)

    restore_events: list[OperationalEvent] = []
    result = MiniKV.restore(backup, restored, event_hook=restore_events.append)

    assert result.events_dropped == 0
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert [event.name for event in events] == [
        "store.opened",
        "mutation.put_committed",
        "mutation.put_committed",
        "mutation.delete_committed",
        "store.compacted",
        "backup.published",
        "store.closed",
    ]
    assert [event.name for event in restore_events] == ["restore.completed"]
    serialized = json.dumps(
        [event.to_dict() for event in [*events, *restore_events]],
        sort_keys=True,
    )
    for sensitive in (
        database.name,
        backup.name,
        restored.name,
        fixture_key,
        fixture_value.decode(),
        "deleted-secret",
        "deleted-value",
    ):
        assert sensitive not in serialized


def test_event_is_immutable_sorted_and_strictly_validated() -> None:
    event = operational_event(
        1,
        "store.opened",
        recovered_bytes=0,
        entries=2,
        log_bytes=100,
    )
    assert event.schema_version == EVENT_SCHEMA_VERSION
    assert tuple(name for name, _ in event.metrics) == (
        "entries",
        "log_bytes",
        "recovered_bytes",
    )
    with pytest.raises(FrozenInstanceError):
        event.sequence = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="event contract"):
        OperationalEvent(
            EVENT_SCHEMA_VERSION,
            1,
            "store.opened",
            (("entries", 1),),
        )
    with pytest.raises(ValueError, match="unknown"):
        OperationalEvent(
            EVENT_SCHEMA_VERSION,
            1,
            cast("Any", "unknown.event"),
            (),
        )
    with pytest.raises(ValueError, match="non-negative"):
        operational_event(
            1,
            "store.opened",
            entries=-1,
            log_bytes=0,
            recovered_bytes=0,
        )


def test_hook_failures_do_not_reverse_durable_operations(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    calls = 0

    def fail(_event: OperationalEvent) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic telemetry failure")

    store = MiniKV.open(database, event_hook=fail)
    assert store.stats().events_dropped == 1
    store.put("durable", b"value")
    assert store.get("durable") == b"value"
    assert store.stats().events_dropped == 2
    store.close()
    assert calls == 3
    with MiniKV.open(database) as reopened:
        assert reopened.get("durable") == b"value"


def test_failed_mutation_does_not_emit_committed_event(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    events: list[OperationalEvent] = []
    writes = 0

    def fail_second_write(stage: str) -> None:
        nonlocal writes
        if stage == "after_write":
            writes += 1
        if stage == "after_write" and writes == 2:
            raise OSError("synthetic failure")

    with MiniKV.open(database, fault_hook=fail_second_write, event_hook=events.append) as store:
        store.put("safe", b"value")
        with pytest.raises(PersistenceError):
            store.put("rejected", b"value")

    assert [event.name for event in events].count("mutation.put_committed") == 1


def test_restore_hook_failure_is_reported_without_reversing_restore(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    backup = tmp_path / "store.mkvb"
    restored = tmp_path / "restored.mkv"
    with MiniKV.open(database) as store:
        store.put("safe", b"value")
        store.backup(backup)

    def fail(_event: OperationalEvent) -> None:
        raise RuntimeError("synthetic telemetry failure")

    result = MiniKV.restore(backup, restored, event_hook=fail)
    assert result.events_dropped == 1
    with MiniKV.open(restored) as reopened:
        assert reopened.get("safe") == b"value"
