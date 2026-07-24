from __future__ import annotations

import os
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

import pytest

from minikv import CorruptionError, LimitError, MiniKV, PersistenceError
from minikv.store import BACKUP_HEADER, BACKUP_MAGIC, BACKUP_VERSION, FORMAT_VERSION


def build_backup(tmp_path: Path) -> tuple[Path, bytes]:
    database = tmp_path / "source.mkv"
    backup = tmp_path / "source.mkvb"
    with MiniKV.open(database) as store:
        store.put("zulu", b"old")
        store.put("Cafe\u0301", b"\x00\xff")
        store.put("zulu", b"current")
        store.put("deleted", b"gone")
        store.delete("deleted")
        store.put("empty", b"")
        result = store.backup(backup)
        assert result.entries == 3
        assert result.payload_bytes > 0
        assert result.artifact_bytes == backup.stat().st_size
        assert len(result.payload_sha256) == 64
        assert result.replaced_existing is False
        assert result.parent_directory_fsynced is (os.name == "posix")
    if os.name == "posix":
        assert backup.stat().st_mode & 0o777 == 0o600
    return backup, backup.read_bytes()


def replace_header(
    artifact: bytes,
    *,
    magic: bytes = BACKUP_MAGIC,
    version: int = BACKUP_VERSION,
    log_version: int = FORMAT_VERSION,
    reserved: int = 0,
    entries: int | None = None,
    payload_bytes: int | None = None,
    digest: bytes | None = None,
) -> bytes:
    unpacked = BACKUP_HEADER.unpack(artifact[: BACKUP_HEADER.size])
    header = BACKUP_HEADER.pack(
        magic,
        version,
        log_version,
        reserved,
        unpacked[4] if entries is None else entries,
        unpacked[5] if payload_bytes is None else payload_bytes,
        unpacked[6] if digest is None else digest,
    )
    return header + artifact[BACKUP_HEADER.size :]


def test_backup_restore_round_trip_and_continued_writes(tmp_path: Path) -> None:
    backup, artifact = build_backup(tmp_path)
    restored = tmp_path / "restored.mkv"
    result = MiniKV.restore(backup, restored)
    assert result.entries == 3
    assert result.payload_bytes == len(artifact) - BACKUP_HEADER.size
    assert result.replaced_existing is False
    assert result.parent_directory_fsynced is (os.name == "posix")

    with MiniKV.open(restored) as store:
        assert store.keys() == ("Café", "empty", "zulu")
        assert store.get("Café") == b"\x00\xff"
        assert store.get("empty") == b""
        assert store.get("zulu") == b"current"
        assert store.stats().sequence == 3
        store.put("after", b"restore")
    with MiniKV.open(restored) as reopened:
        assert reopened.get("after") == b"restore"


def test_backup_is_deterministic_and_can_atomically_replace_previous(tmp_path: Path) -> None:
    database = tmp_path / "source.mkv"
    backup = tmp_path / "source.mkvb"
    with MiniKV.open(database) as store:
        store.put("b", b"2")
        store.put("a", b"1")
        first = store.backup(backup)
        first_bytes = backup.read_bytes()
        second = store.backup(backup)
    assert backup.read_bytes() == first_bytes
    assert first.payload_sha256 == second.payload_sha256
    assert second.replaced_existing is True


def test_restore_requires_explicit_overwrite_and_preserves_old_bytes(tmp_path: Path) -> None:
    backup, _ = build_backup(tmp_path)
    destination = tmp_path / "existing.mkv"
    destination.write_bytes(b"existing")
    with pytest.raises(FileExistsError, match="overwrite=True"):
        MiniKV.restore(backup, destination)
    with pytest.raises(TypeError, match="boolean"):
        MiniKV.restore(backup, destination, overwrite=1)  # type: ignore[arg-type]
    assert destination.read_bytes() == b"existing"

    result = MiniKV.restore(backup, destination, overwrite=True)
    assert result.replaced_existing is True
    with MiniKV.open(destination) as restored:
        assert restored.get("zulu") == b"current"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda content: content[:8], "truncated"),
        (lambda content: replace_header(content, magic=b"BAD!"), "magic"),
        (lambda content: replace_header(content, version=2), "version"),
        (lambda content: replace_header(content, log_version=2), "log format"),
        (lambda content: replace_header(content, reserved=1), "reserved"),
        (lambda content: replace_header(content, payload_bytes=1), "length"),
        (lambda content: content + b"trailing", "length"),
        (
            lambda content: replace_header(content, digest=b"\x00" * 32),
            "SHA-256",
        ),
        (
            lambda content: content[:-1] + bytes([content[-1] ^ 1]),
            "SHA-256",
        ),
        (lambda content: replace_header(content, entries=99), "entry count"),
    ],
)
def test_malformed_backups_fail_before_destination_mutation(
    tmp_path: Path,
    mutator: Callable[[bytes], bytes],
    message: str,
) -> None:
    backup, artifact = build_backup(tmp_path)
    destination = tmp_path / "existing.mkv"
    destination.write_bytes(b"preserve")
    backup.write_bytes(mutator(artifact))
    with pytest.raises((CorruptionError, LimitError), match=message):
        MiniKV.restore(backup, destination, overwrite=True)
    assert destination.read_bytes() == b"preserve"


def test_forged_outer_digest_does_not_hide_payload_corruption(tmp_path: Path) -> None:
    backup, artifact = build_backup(tmp_path)
    payload = bytearray(artifact[BACKUP_HEADER.size :])
    payload[-1] ^= 1
    forged = replace_header(artifact, digest=sha256(payload).digest())
    backup.write_bytes(forged[: BACKUP_HEADER.size] + payload)
    with pytest.raises(CorruptionError, match="checksum"):
        MiniKV.restore(backup, tmp_path / "restored.mkv")


def test_valid_noncanonical_log_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "history.mkv"
    backup = tmp_path / "history.mkvb"
    with MiniKV.open(database) as store:
        store.put("key", b"old")
        store.put("key", b"current")
    payload = database.read_bytes()
    header = BACKUP_HEADER.pack(
        BACKUP_MAGIC,
        BACKUP_VERSION,
        FORMAT_VERSION,
        0,
        1,
        len(payload),
        sha256(payload).digest(),
    )
    backup.write_bytes(header + payload)
    with pytest.raises(CorruptionError, match="entry count"):
        MiniKV.restore(backup, tmp_path / "restored.mkv")


@pytest.mark.parametrize(
    "stage",
    [
        "backup_after_partial_write",
        "backup_after_write",
        "backup_after_flush",
        "backup_before_validation",
        "backup_before_replace",
    ],
)
def test_backup_prepublication_failures_preserve_existing_artifact(
    tmp_path: Path,
    stage: str,
) -> None:
    database = tmp_path / "source.mkv"
    destination = tmp_path / "backup.mkvb"
    destination.write_bytes(b"previous backup")

    def fail(current: str) -> None:
        if current == stage:
            raise OSError("synthetic backup failure")

    with MiniKV.open(database, fault_hook=fail) as store:
        store.put("safe", b"value")
        with pytest.raises(PersistenceError):
            store.backup(destination)
    assert destination.read_bytes() == b"previous backup"
    assert not (tmp_path / ".backup.mkvb.backup.tmp").exists()


@pytest.mark.parametrize(
    "stage",
    [
        "restore_after_partial_write",
        "restore_after_write",
        "restore_after_flush",
        "restore_before_validation",
        "restore_before_replace",
    ],
)
def test_restore_prereplacement_failures_preserve_destination(
    tmp_path: Path,
    stage: str,
) -> None:
    backup, _ = build_backup(tmp_path)
    destination = tmp_path / "existing.mkv"
    destination.write_bytes(b"preserve")

    def fail(current: str) -> None:
        if current == stage:
            raise OSError("synthetic restore failure")

    with pytest.raises(PersistenceError, match="preserved"):
        MiniKV.restore(backup, destination, overwrite=True, fault_hook=fail)
    assert destination.read_bytes() == b"preserve"
    assert not (tmp_path / ".existing.mkv.restore.tmp").exists()


@pytest.mark.parametrize(
    ("operation", "stage"),
    [
        ("backup", "backup_after_replace"),
        ("restore", "restore_after_replace"),
    ],
)
def test_postreplacement_failure_reports_uncertainty(
    tmp_path: Path,
    operation: str,
    stage: str,
) -> None:
    database = tmp_path / "source.mkv"
    backup = tmp_path / "backup.mkvb"

    def fail(current: str) -> None:
        if current == stage:
            raise OSError("synthetic post-replacement failure")

    with MiniKV.open(database, fault_hook=fail if operation == "backup" else None) as store:
        store.put("safe", b"value")
        if operation == "backup":
            with pytest.raises(PersistenceError, match="published"):
                store.backup(backup)
            assert backup.exists()
            return
        store.backup(backup)

    destination = tmp_path / "restored.mkv"
    with pytest.raises(PersistenceError, match="replaced"):
        MiniKV.restore(backup, destination, fault_hook=fail)
    with MiniKV.open(destination) as restored:
        assert restored.get("safe") == b"value"


def test_aliases_symlinks_and_unowned_temporaries_are_rejected(tmp_path: Path) -> None:
    database = tmp_path / "source.mkv"
    backup = tmp_path / "backup.mkvb"
    with MiniKV.open(database) as store:
        store.put("safe", b"value")
        with pytest.raises(ValueError, match="differ"):
            store.backup(database)
        alias = tmp_path / "database-alias"
        os.link(database, alias)
        with pytest.raises(ValueError, match="alias"):
            store.backup(alias)
        store.backup(backup)

    backup_link = tmp_path / "backup-link"
    backup_link.symlink_to(backup)
    with pytest.raises(ValueError, match="symbolic"):
        MiniKV.restore(backup_link, tmp_path / "restored.mkv")
    with pytest.raises(ValueError, match="differ"):
        MiniKV.restore(backup, backup)

    temporary = tmp_path / ".restored.mkv.restore.tmp"
    temporary.symlink_to(database)
    with pytest.raises(PersistenceError, match="temporary path"):
        MiniKV.restore(backup, tmp_path / "restored.mkv")
    assert temporary.is_symlink()


def test_restore_detects_source_replacement_and_destination_appearance(tmp_path: Path) -> None:
    backup, original = build_backup(tmp_path)
    destination = tmp_path / "restored.mkv"

    def replace_source(stage: str) -> None:
        if stage == "restore_before_replace":
            moved = tmp_path / "moved.mkvb"
            backup.replace(moved)
            backup.write_bytes(original)

    with pytest.raises(PersistenceError, match="source was replaced"):
        MiniKV.restore(backup, destination, fault_hook=replace_source)
    assert not destination.exists()

    moved = tmp_path / "moved.mkvb"

    def create_destination(stage: str) -> None:
        if stage == "restore_before_replace":
            destination.write_bytes(b"appeared")

    with pytest.raises(PersistenceError, match="appeared"):
        MiniKV.restore(moved, destination, fault_hook=create_destination)
    assert destination.read_bytes() == b"appeared"


def test_artifact_size_limit_and_empty_backup(tmp_path: Path) -> None:
    database = tmp_path / "empty.mkv"
    backup = tmp_path / "empty.mkvb"
    with MiniKV.open(database) as store:
        result = store.backup(backup)
    assert result.entries == 0
    assert result.payload_bytes == 0
    restored = tmp_path / "restored.mkv"
    MiniKV.restore(backup, restored, max_database_bytes=1)
    assert restored.read_bytes() == b""

    oversized = tmp_path / "oversized.mkvb"
    oversized.write_bytes(b"x" * (BACKUP_HEADER.size + 2))
    with pytest.raises(LimitError, match="limit"):
        MiniKV.restore(oversized, tmp_path / "blocked.mkv", max_database_bytes=1)
