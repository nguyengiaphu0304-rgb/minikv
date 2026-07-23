from __future__ import annotations

import os
import struct
import unicodedata
import zlib
from pathlib import Path

import pytest

from minikv import ClosedError, CorruptionError, LimitError, MiniKV, PersistenceError
from minikv.store import CHECKSUM, DELETE, FORMAT_VERSION, HEADER, MAGIC, PUT


def frame(
    sequence: int,
    key: bytes,
    value: bytes,
    *,
    operation: int = PUT,
    magic: bytes = MAGIC,
    version: int = FORMAT_VERSION,
) -> bytes:
    header = HEADER.pack(magic, version, operation, sequence, len(key), len(value))
    content = header + key + value
    return content + CHECKSUM.pack(zlib.crc32(content))


def test_round_trip_overwrite_delete_reopen_and_stats(tmp_path: Path) -> None:
    path = tmp_path / "store.mkv"
    with MiniKV.open(path) as store:
        assert store.get("missing") is None
        assert store.delete("missing") is False
        store.put("alpha", b"one")
        store.put("binary", b"\x00\xff")
        store.put("alpha", b"two")
        assert store.get("alpha") == b"two"
        assert store.get("binary") == b"\x00\xff"
        assert store.keys() == ("alpha", "binary")
        assert store.delete("alpha") is True
        assert store.keys() == ("binary",)
        assert store.stats().sequence == 4
        assert store.stats().entries == 1

    with MiniKV.open(path) as reopened:
        assert reopened.get("alpha") is None
        assert reopened.get("binary") == b"\x00\xff"
        assert reopened.stats().sequence == 4
        assert reopened.stats().recovered_bytes == 0


def test_unicode_keys_are_normalized_and_values_are_copied(tmp_path: Path) -> None:
    decomposed = "Cafe\u0301"
    canonical = unicodedata.normalize("NFC", decomposed)
    source = bytearray(b"before")
    with MiniKV.open(tmp_path / "store.mkv") as store:
        store.put(decomposed, source)
        source[:] = b"mutate"
        assert store.get(canonical) == b"before"
        assert store.keys() == (canonical,)
        store.put("empty", b"")
        assert store.get("empty") == b""


@pytest.mark.parametrize("stage", ["after_write", "after_flush"])
def test_failed_persistence_rolls_back_frame_and_visible_state(tmp_path: Path, stage: str) -> None:
    path = tmp_path / "store.mkv"
    matching_calls = 0

    def fail_once(current: str) -> None:
        nonlocal matching_calls
        if current == stage:
            matching_calls += 1
        if current == stage and matching_calls == 2:
            raise OSError("synthetic persistence failure")

    with MiniKV.open(path, fault_hook=fail_once) as store:
        store.put("stable", b"yes")
        before = store.stats()
        with pytest.raises(PersistenceError, match="not acknowledged"):
            store.put("unstable", b"no")
        assert store.get("unstable") is None
        assert store.stats() == before

    with MiniKV.open(path) as reopened:
        assert reopened.get("stable") == b"yes"
        assert reopened.get("unstable") is None
        assert reopened.stats().recovered_bytes == 0


@pytest.mark.parametrize(
    "tail",
    [
        b"M",
        HEADER.pack(MAGIC, FORMAT_VERSION, PUT, 2, 3, 5) + b"key",
        HEADER.pack(MAGIC, FORMAT_VERSION, PUT, 2, 3, 5) + b"keyvalue",
    ],
)
def test_only_incomplete_final_frame_is_recovered(tmp_path: Path, tail: bytes) -> None:
    path = tmp_path / "store.mkv"
    valid = frame(1, b"safe", b"value")
    path.write_bytes(valid + tail)
    with MiniKV.open(path) as store:
        assert store.get("safe") == b"value"
        assert store.stats().recovered_bytes == len(tail)
        assert store.stats().log_bytes == len(valid)
    assert path.read_bytes() == valid


def test_complete_checksum_corruption_fails_closed_without_truncation(tmp_path: Path) -> None:
    path = tmp_path / "store.mkv"
    original = frame(1, b"first", b"value") + frame(2, b"second", b"value")
    corrupted = bytearray(original)
    corrupted[HEADER.size + len(b"first")] ^= 0x01
    path.write_bytes(corrupted)
    with pytest.raises(CorruptionError, match="checksum"):
        MiniKV.open(path)
    assert path.read_bytes() == corrupted


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (frame(1, b"key", b"value", magic=b"BAD!"), "magic"),
        (frame(1, b"key", b"value", version=2), "version"),
        (frame(2, b"key", b"value"), "sequence"),
        (frame(1, b"key", b"value", operation=DELETE), "delete"),
        (frame(1, b"\xff", b"value"), "UTF-8"),
        (frame(1, "Cafe\u0301".encode(), b"value"), "canonical"),
    ],
)
def test_complete_malformed_frames_fail_closed(
    tmp_path: Path,
    content: bytes,
    message: str,
) -> None:
    path = tmp_path / "store.mkv"
    path.write_bytes(content)
    with pytest.raises(CorruptionError, match=message):
        MiniKV.open(path)
    assert path.read_bytes() == content


def test_declared_resource_limits_fail_before_body_allocation(tmp_path: Path) -> None:
    path = tmp_path / "store.mkv"
    oversized = HEADER.pack(MAGIC, FORMAT_VERSION, PUT, 1, 1_025, 0)
    path.write_bytes(oversized)
    with pytest.raises(CorruptionError, match="key length"):
        MiniKV.open(path)

    with (
        MiniKV.open(tmp_path / "small.mkv", max_database_bytes=60) as store,
        pytest.raises(LimitError, match="database limit"),
    ):
        store.put("key", b"x" * 40)


def test_key_and_value_validation(tmp_path: Path) -> None:
    with MiniKV.open(tmp_path / "store.mkv") as store:
        with pytest.raises(ValueError, match="empty"):
            store.put("", b"value")
        with pytest.raises(ValueError, match="NUL"):
            store.put("bad\x00key", b"value")
        with pytest.raises(LimitError, match="key exceeds"):
            store.put("x" * 1_025, b"value")
        with pytest.raises(LimitError, match="value exceeds"):
            store.put("key", b"x" * 1_048_577)
        with pytest.raises(TypeError, match="bytes-like"):
            store.put("key", "text")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="string"):
            store.get(1)  # type: ignore[arg-type]


def test_symlink_and_non_regular_paths_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.mkv"
    target.touch()
    link = tmp_path / "link.mkv"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        MiniKV.open(link)
    with pytest.raises(ValueError, match="regular file"):
        MiniKV.open(tmp_path)


def test_closed_handle_rejects_operations(tmp_path: Path) -> None:
    store = MiniKV.open(tmp_path / "store.mkv")
    store.close()
    store.close()
    with pytest.raises(ClosedError):
        store.get("key")


def test_database_size_is_checked_before_scan(tmp_path: Path) -> None:
    path = tmp_path / "store.mkv"
    path.write_bytes(b"x" * 101)
    with pytest.raises(LimitError, match="configured limit"):
        MiniKV.open(path, max_database_bytes=100)


def test_frame_encoding_is_big_endian_and_checksum_covers_header_and_body() -> None:
    encoded = frame(0x0102030405060708, b"k", b"v")
    assert encoded[:4] == MAGIC
    assert encoded[6:14] == bytes.fromhex("0102030405060708")
    checksum = struct.unpack(">I", encoded[-4:])[0]
    assert checksum == zlib.crc32(encoded[:-4])


def test_created_file_uses_owner_only_permissions_on_posix(tmp_path: Path) -> None:
    path = tmp_path / "store.mkv"
    MiniKV.open(path).close()
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
