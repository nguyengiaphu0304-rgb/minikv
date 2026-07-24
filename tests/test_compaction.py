from __future__ import annotations

import os
from pathlib import Path

import pytest

from minikv import ClosedError, LimitError, MiniKV, PersistenceError


def build_history(path: Path) -> bytes:
    with MiniKV.open(path) as store:
        store.put("zulu", b"old")
        store.put("alpha", b"\x00\xff")
        store.put("zulu", b"new")
        store.put("deleted", b"gone")
        store.delete("deleted")
        store.put("empty", b"")
    return path.read_bytes()


def test_compaction_preserves_live_state_and_reclaims_history(tmp_path: Path) -> None:
    path = tmp_path / "store.mkv"
    original = build_history(path)
    with MiniKV.open(path) as store:
        result = store.compact()
        assert result.entries == 3
        assert result.old_log_bytes == len(original)
        assert result.new_log_bytes == path.stat().st_size
        assert result.reclaimed_bytes == len(original) - path.stat().st_size
        assert result.parent_directory_fsynced is (os.name == "posix")
        assert store.keys() == ("alpha", "empty", "zulu")
        assert store.get("alpha") == b"\x00\xff"
        assert store.get("empty") == b""
        assert store.get("zulu") == b"new"
        store.put("after", b"rebound")

    with MiniKV.open(path) as reopened:
        assert reopened.keys() == ("after", "alpha", "empty", "zulu")
        assert reopened.get("after") == b"rebound"


def test_compaction_is_deterministic_across_history_and_repetition(tmp_path: Path) -> None:
    first = tmp_path / "first.mkv"
    second = tmp_path / "second.mkv"
    with MiniKV.open(first) as store:
        store.put("zulu", b"new")
        store.put("alpha", b"\x00\xff")
        store.put("empty", b"")
        store.compact()
    with MiniKV.open(second) as store:
        store.put("empty", b"")
        store.put("zulu", b"old")
        store.put("alpha", b"\x00\xff")
        store.put("zulu", b"new")
        store.compact()
    assert first.read_bytes() == second.read_bytes()

    before = first.read_bytes()
    with MiniKV.open(first) as store:
        first_result = store.compact()
        second_result = store.compact()
    assert first.read_bytes() == before
    assert first_result.new_log_bytes == second_result.new_log_bytes
    assert second_result.reclaimed_bytes == 0


def test_empty_database_compacts_to_empty_database(tmp_path: Path) -> None:
    path = tmp_path / "empty.mkv"
    with MiniKV.open(path) as store:
        result = store.compact()
        assert result.entries == 0
        assert result.old_log_bytes == 0
        assert result.new_log_bytes == 0
        assert store.keys() == ()
    assert path.read_bytes() == b""


@pytest.mark.parametrize(
    "stage",
    [
        "compact_after_partial_write",
        "compact_after_write",
        "compact_after_flush",
        "compact_before_validation",
        "compact_before_replace",
    ],
)
def test_pre_replace_failures_preserve_source_and_clean_temporary(
    tmp_path: Path,
    stage: str,
) -> None:
    path = tmp_path / "store.mkv"
    original = build_history(path)

    def fail(current: str) -> None:
        if current == stage:
            raise OSError("synthetic compaction failure")

    with MiniKV.open(path, fault_hook=fail) as store:
        with pytest.raises(PersistenceError, match="original database preserved"):
            store.compact()
        assert store.get("zulu") == b"new"
    assert path.read_bytes() == original
    assert not (tmp_path / ".store.mkv.compact.tmp").exists()


def test_replace_failure_preserves_source_and_cleans_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "store.mkv"
    original = build_history(path)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with (
        MiniKV.open(path) as store,
        pytest.raises(PersistenceError, match="original database preserved"),
    ):
        store.compact()
    assert path.read_bytes() == original
    assert not (tmp_path / ".store.mkv.compact.tmp").exists()


@pytest.mark.parametrize(
    "stage",
    ["compact_after_replace", "compact_before_directory_fsync"],
)
def test_post_replace_failure_closes_handle_but_compacted_state_reopens(
    tmp_path: Path,
    stage: str,
) -> None:
    path = tmp_path / "store.mkv"
    original = build_history(path)

    def fail(current: str) -> None:
        if current == stage:
            raise OSError("synthetic post-replace failure")

    store = MiniKV.open(path, fault_hook=fail)
    with pytest.raises(PersistenceError, match="reopen required"):
        store.compact()
    with pytest.raises(ClosedError):
        store.keys()
    assert path.stat().st_size < len(original)
    with MiniKV.open(path) as reopened:
        assert reopened.keys() == ("alpha", "empty", "zulu")
        assert reopened.get("zulu") == b"new"


def test_unowned_temporary_collision_is_rejected_without_modification(tmp_path: Path) -> None:
    path = tmp_path / "store.mkv"
    original = build_history(path)
    target = tmp_path / "target"
    target.write_bytes(b"unowned")
    temporary = tmp_path / ".store.mkv.compact.tmp"
    temporary.symlink_to(target)
    with (
        MiniKV.open(path) as store,
        pytest.raises(PersistenceError, match="already exists"),
    ):
        store.compact()
    assert path.read_bytes() == original
    assert temporary.is_symlink()
    assert target.read_bytes() == b"unowned"


def test_replaced_source_path_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "store.mkv"
    moved = tmp_path / "moved.mkv"
    with MiniKV.open(path) as store:
        store.put("safe", b"value")
        path.replace(moved)
        path.write_bytes(b"replacement")
        with pytest.raises(PersistenceError, match="replaced"):
            store.compact()
    assert path.read_bytes() == b"replacement"
    with MiniKV.open(moved) as reopened:
        assert reopened.get("safe") == b"value"


def test_replaced_parent_directory_is_rejected(tmp_path: Path) -> None:
    parent = tmp_path / "database"
    parent.mkdir()
    path = parent / "store.mkv"
    moved_parent = tmp_path / "moved"
    with MiniKV.open(path) as store:
        store.put("safe", b"value")
        parent.replace(moved_parent)
        parent.mkdir()
        os.link(moved_parent / "store.mkv", path)
        with pytest.raises(PersistenceError, match="parent directory was replaced"):
            store.compact()
    with MiniKV.open(moved_parent / "store.mkv") as reopened:
        assert reopened.get("safe") == b"value"


def test_compacted_size_guard_preserves_source(tmp_path: Path) -> None:
    path = tmp_path / "store.mkv"
    original = build_history(path)
    with MiniKV.open(path) as store:
        store._max_database_bytes = 1  # noqa: SLF001 - exercise invariant guard
        with pytest.raises(LimitError, match="compacted state would exceed"):
            store.compact()
    assert path.read_bytes() == original


def test_compaction_after_close_is_rejected(tmp_path: Path) -> None:
    store = MiniKV.open(tmp_path / "store.mkv")
    store.close()
    with pytest.raises(ClosedError):
        store.compact()
