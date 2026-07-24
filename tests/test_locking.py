from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from minikv import ConcurrencyError, CorruptionError, MiniKV, PersistenceError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX flock contract")


def lock_path(database: Path) -> Path:
    return database.with_name(f".{database.name}.lock")


def start_owner(database: Path, *, abrupt: bool = False) -> subprocess.Popen[str]:
    exit_statement = "os._exit(17)" if abrupt else "store.close()"
    code = (
        "import os, sys\n"
        "from minikv import MiniKV\n"
        "store = MiniKV.open(sys.argv[1])\n"
        "print('ready', flush=True)\n"
        "sys.stdin.readline()\n"
        f"{exit_statement}\n"
    )
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter and fixture code
        [sys.executable, "-c", code, str(database)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    return process


def release_owner(process: subprocess.Popen[str], *, expected: int = 0) -> None:
    assert process.stdin is not None
    process.stdin.write("\n")
    process.stdin.flush()
    _, stderr = process.communicate(timeout=10)
    assert process.returncode == expected, stderr


def test_same_process_concurrent_open_is_rejected_and_lock_persists(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    owner = MiniKV.open(database)
    sidecar = lock_path(database)
    assert sidecar.is_file()
    assert sidecar.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ConcurrencyError, match="already open"):
        MiniKV.open(database)
    owner.close()
    assert sidecar.is_file()
    with MiniKV.open(database) as reopened:
        reopened.put("safe", b"value")


def test_independent_process_contention_and_clean_release(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    owner = start_owner(database)
    with pytest.raises(ConcurrencyError, match="another cooperating process"):
        MiniKV.open(database)
    release_owner(owner)
    with MiniKV.open(database) as reopened:
        assert reopened.keys() == ()


def test_abrupt_process_exit_releases_kernel_lock(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    owner = start_owner(database, abrupt=True)
    release_owner(owner, expected=17)
    with MiniKV.open(database) as reopened:
        reopened.put("after-crash", b"safe")


def test_lock_is_held_across_compaction_and_backup(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    backup = tmp_path / "store.mkvb"
    with MiniKV.open(database) as owner:
        owner.put("key", b"old")
        owner.put("key", b"current")
        owner.compact()
        with pytest.raises(ConcurrencyError):
            MiniKV.open(database)
        owner.backup(backup)
        with pytest.raises(ConcurrencyError):
            MiniKV.open(database)


def test_restore_rejects_open_destination_without_mutation(tmp_path: Path) -> None:
    source = tmp_path / "source.mkv"
    backup = tmp_path / "source.mkvb"
    with MiniKV.open(source) as store:
        store.put("source", b"value")
        store.backup(backup)

    destination = tmp_path / "destination.mkv"
    with MiniKV.open(destination) as owner:
        owner.put("preserve", b"bytes")
        before = destination.read_bytes()
        with pytest.raises(ConcurrencyError):
            MiniKV.restore(backup, destination, overwrite=True)
        assert destination.read_bytes() == before
        assert owner.get("preserve") == b"bytes"


def test_symlink_lock_path_is_rejected_without_touching_target(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    target = tmp_path / "target"
    target.write_bytes(b"preserve")
    sidecar = lock_path(database)
    sidecar.symlink_to(target)
    with pytest.raises(ValueError, match="lock path must not be a symbolic link"):
        MiniKV.open(database)
    assert target.read_bytes() == b"preserve"
    assert not database.exists()


def test_lock_replacement_is_detected_before_mutation(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    moved_lock = tmp_path / "moved.lock"
    with MiniKV.open(database) as store:
        store.put("safe", b"value")
        sidecar = lock_path(database)
        sidecar.replace(moved_lock)
        sidecar.touch()
        before = database.read_bytes()
        with pytest.raises(PersistenceError, match="lock path was replaced"):
            store.put("unsafe", b"value")
        assert database.read_bytes() == before


def test_database_replacement_is_detected_before_mutation(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    moved = tmp_path / "moved.mkv"
    with MiniKV.open(database) as store:
        store.put("safe", b"value")
        database.replace(moved)
        database.write_bytes(b"replacement")
        with pytest.raises(PersistenceError, match="database path was replaced"):
            store.put("unsafe", b"value")
    assert database.read_bytes() == b"replacement"
    with MiniKV.open(moved) as original:
        assert original.get("safe") == b"value"
        assert original.get("unsafe") is None


def test_failed_corrupt_open_does_not_strand_lock(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    with MiniKV.open(database) as store:
        store.put("key", b"value")
    corrupted = bytearray(database.read_bytes())
    corrupted[-1] ^= 1
    database.write_bytes(corrupted)
    with pytest.raises(CorruptionError, match="checksum"):
        MiniKV.open(database)
    database.write_bytes(b"")
    with MiniKV.open(database) as recovered:
        assert recovered.keys() == ()


def test_backup_cannot_replace_or_alias_active_lock(tmp_path: Path) -> None:
    database = tmp_path / "store.mkv"
    with MiniKV.open(database) as store:
        sidecar = lock_path(database)
        with pytest.raises(ValueError, match="lock path"):
            store.backup(sidecar)
        alias = tmp_path / "lock-alias"
        os.link(sidecar, alias)
        with pytest.raises(ValueError, match=r"alias.*lock"):
            store.backup(alias)
