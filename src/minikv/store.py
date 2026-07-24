"""Crash-aware append-only MiniKV storage engine."""

from __future__ import annotations

import os
import stat
import struct
import unicodedata
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final, Self

from minikv.errors import ClosedError, CorruptionError, LimitError, PersistenceError

MAGIC: Final = b"MKV1"
FORMAT_VERSION: Final = 1
PUT: Final = 1
DELETE: Final = 2
HEADER: Final = struct.Struct(">4sBBQII")
CHECKSUM: Final = struct.Struct(">I")
MAX_KEY_BYTES: Final = 1_024
MAX_VALUE_BYTES: Final = 1_048_576
DEFAULT_MAX_DATABASE_BYTES: Final = 64 * 1_048_576
HARD_MAX_DATABASE_BYTES: Final = 1_073_741_824
FaultHook = Callable[[str], None]
BytesLike = bytes | bytearray | memoryview


@dataclass(frozen=True, slots=True)
class StoreStats:
    """Non-sensitive operational state for the current handle."""

    entries: int
    sequence: int
    log_bytes: int
    recovered_bytes: int


@dataclass(frozen=True, slots=True)
class CompactionStats:
    """Non-sensitive outcome of a successful compaction."""

    entries: int
    old_log_bytes: int
    new_log_bytes: int
    reclaimed_bytes: int
    parent_directory_fsynced: bool


@dataclass(frozen=True, slots=True)
class _FrameHeader:
    magic: bytes
    version: int
    operation: int
    sequence: int
    key_length: int
    value_length: int


class MiniKV:
    """A single-process append-only key-value store.

    Mutations are acknowledged only after the frame has been flushed and fsynced.
    Opening a log rebuilds the in-memory index and may truncate one incomplete final
    frame. Complete corrupt frames fail closed.
    """

    def __init__(
        self,
        path: Path,
        file: BinaryIO,
        *,
        max_database_bytes: int,
        fault_hook: FaultHook | None,
    ) -> None:
        """Build an index from an already validated and opened file."""
        self._path = path
        self._file = file
        self._file_identity = self._identity(os.fstat(file.fileno()))
        self._parent_identity = self._identity(path.parent.stat())
        self._max_database_bytes = max_database_bytes
        self._fault_hook = fault_hook
        self._index: dict[str, bytes] = {}
        self._sequence = 0
        self._log_bytes = 0
        self._recovered_bytes = 0
        self._closed = False
        self._load()

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        max_database_bytes: int = DEFAULT_MAX_DATABASE_BYTES,
        fault_hook: FaultHook | None = None,
    ) -> MiniKV:
        """Open or create a database without following a final-component symlink."""
        database = Path(path).absolute()
        if not isinstance(max_database_bytes, int) or isinstance(max_database_bytes, bool):
            msg = "max_database_bytes must be an integer"
            raise TypeError(msg)
        if not 1 <= max_database_bytes <= HARD_MAX_DATABASE_BYTES:
            msg = f"max_database_bytes must be between 1 and {HARD_MAX_DATABASE_BYTES}"
            raise LimitError(msg)
        try:
            mode = database.lstat().st_mode
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(mode):
                msg = "database path must not be a symbolic link"
                raise ValueError(msg)
            if not stat.S_ISREG(mode):
                msg = "database path must be a regular file"
                raise ValueError(msg)

        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(database, flags, 0o600)
        file = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            return cls(
                database,
                file,
                max_database_bytes=max_database_bytes,
                fault_hook=fault_hook,
            )
        except Exception:
            file.close()
            raise

    def __enter__(self) -> Self:
        """Return this open handle for context-manager use."""
        self._ensure_open()
        return self

    def __exit__(self, *_exc: object) -> None:
        """Close this handle when leaving a context manager."""
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClosedError

    @staticmethod
    def _identity(metadata: os.stat_result) -> tuple[int, int]:
        return metadata.st_dev, metadata.st_ino

    def _assert_path_identity(self) -> None:
        try:
            path_metadata = self._path.stat(follow_symlinks=False)
            parent_metadata = self._path.parent.stat()
        except OSError as error:
            msg = "database path or parent is no longer available"
            raise PersistenceError(msg) from error
        if not stat.S_ISREG(path_metadata.st_mode):
            msg = "database path no longer names a regular file"
            raise PersistenceError(msg)
        if self._identity(path_metadata) != self._file_identity:
            msg = "database path was replaced while the handle was open"
            raise PersistenceError(msg)
        if self._identity(parent_metadata) != self._parent_identity:
            msg = "database parent directory was replaced while the handle was open"
            raise PersistenceError(msg)

    @staticmethod
    def _key_bytes(key: object) -> tuple[str, bytes]:
        if not isinstance(key, str):
            msg = "key must be a string"
            raise TypeError(msg)
        normalized = unicodedata.normalize("NFC", key)
        encoded = normalized.encode("utf-8")
        if not encoded:
            msg = "key must not be empty"
            raise ValueError(msg)
        if "\x00" in normalized:
            msg = "key must not contain NUL"
            raise ValueError(msg)
        if len(encoded) > MAX_KEY_BYTES:
            msg = f"key exceeds {MAX_KEY_BYTES} UTF-8 bytes"
            raise LimitError(msg)
        return normalized, encoded

    @staticmethod
    def _value_bytes(value: object) -> bytes:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            msg = "value must be bytes-like"
            raise TypeError(msg)
        copied = bytes(value)
        if len(copied) > MAX_VALUE_BYTES:
            msg = f"value exceeds {MAX_VALUE_BYTES} bytes"
            raise LimitError(msg)
        return copied

    @staticmethod
    def _frame(operation: int, sequence: int, key: bytes, value: bytes) -> bytes:
        header = HEADER.pack(MAGIC, FORMAT_VERSION, operation, sequence, len(key), len(value))
        content = header + key + value
        return content + CHECKSUM.pack(zlib.crc32(content))

    def _load(self) -> None:
        size = os.fstat(self._file.fileno()).st_size
        if size > self._max_database_bytes:
            msg = f"database exceeds configured limit of {self._max_database_bytes} bytes"
            raise LimitError(msg)
        offset = 0
        expected_sequence = 1
        while offset < size:
            record = self._read_frame(offset, size, expected_sequence)
            if record is None:
                self._recover_tail(offset, size)
                size = offset
                break
            frame_length, operation, key, value = record
            if operation == PUT:
                self._index[key] = value
            else:
                self._index.pop(key, None)
            offset += frame_length
            expected_sequence += 1
        self._sequence = expected_sequence - 1
        self._log_bytes = size
        self._file.seek(size)

    def _read_frame(
        self,
        offset: int,
        size: int,
        expected_sequence: int,
    ) -> tuple[int, int, str, bytes] | None:
        remaining = size - offset
        if remaining < HEADER.size:
            return None
        self._file.seek(offset)
        header_bytes = self._file.read(HEADER.size)
        if len(header_bytes) != HEADER.size:
            return None
        header = _FrameHeader(*HEADER.unpack(header_bytes))
        self._validate_header(header, expected_sequence)
        frame_length = HEADER.size + header.key_length + header.value_length + CHECKSUM.size
        if remaining < frame_length:
            return None
        body = self._file.read(header.key_length + header.value_length)
        checksum_bytes = self._file.read(CHECKSUM.size)
        if (
            len(body) != header.key_length + header.value_length
            or len(checksum_bytes) != CHECKSUM.size
        ):
            return None
        expected_checksum = CHECKSUM.unpack(checksum_bytes)[0]
        if zlib.crc32(header_bytes + body) != expected_checksum:
            msg = f"checksum mismatch at byte {offset}"
            raise CorruptionError(msg)
        key_bytes = body[: header.key_length]
        try:
            key = key_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            msg = f"invalid UTF-8 key at byte {offset}"
            raise CorruptionError(msg) from error
        if not key or "\x00" in key or unicodedata.normalize("NFC", key) != key:
            msg = f"non-canonical key at byte {offset}"
            raise CorruptionError(msg)
        return frame_length, header.operation, key, bytes(body[header.key_length :])

    @staticmethod
    def _validate_header(
        header: _FrameHeader,
        expected_sequence: int,
    ) -> None:
        if header.magic != MAGIC:
            msg = "invalid frame magic"
            raise CorruptionError(msg)
        if header.version != FORMAT_VERSION:
            msg = "unsupported format version"
            raise CorruptionError(msg)
        if header.operation not in {PUT, DELETE}:
            msg = "unsupported operation"
            raise CorruptionError(msg)
        if header.sequence != expected_sequence:
            msg = "frame sequence is not contiguous"
            raise CorruptionError(msg)
        if not 1 <= header.key_length <= MAX_KEY_BYTES:
            msg = "declared key length exceeds format limits"
            raise CorruptionError(msg)
        if header.value_length > MAX_VALUE_BYTES:
            msg = "declared value length exceeds format limits"
            raise CorruptionError(msg)
        if header.operation == DELETE and header.value_length != 0:
            msg = "delete frame contains a value"
            raise CorruptionError(msg)

    def _recover_tail(self, valid_bytes: int, original_bytes: int) -> None:
        self._file.truncate(valid_bytes)
        self._file.flush()
        os.fsync(self._file.fileno())
        self._recovered_bytes += original_bytes - valid_bytes

    @staticmethod
    def _write_all_to(file: BinaryIO, content: bytes) -> None:
        pending = memoryview(content)
        while pending:
            written = file.write(pending)
            if written is None or written <= 0:
                msg = "storage write made no forward progress"
                raise OSError(msg)
            pending = pending[written:]

    def _write_all(self, content: bytes) -> None:
        self._write_all_to(self._file, content)

    def _append(self, operation: int, key: str, key_bytes: bytes, value: bytes) -> None:
        sequence = self._sequence + 1
        frame = self._frame(operation, sequence, key_bytes, value)
        if self._log_bytes + len(frame) > self._max_database_bytes:
            msg = f"mutation would exceed database limit of {self._max_database_bytes} bytes"
            raise LimitError(msg)
        start = self._log_bytes
        self._file.seek(start)
        try:
            self._write_all(frame)
            if self._fault_hook is not None:
                self._fault_hook("after_write")
            self._file.flush()
            if self._fault_hook is not None:
                self._fault_hook("after_flush")
            os.fsync(self._file.fileno())
        except Exception as error:
            try:
                self._file.truncate(start)
                self._file.flush()
                os.fsync(self._file.fileno())
                self._file.seek(start)
            except OSError as rollback_error:
                self.close()
                msg = "persistence failed and rollback could not be confirmed"
                raise PersistenceError(msg) from rollback_error
            msg = "mutation was not acknowledged and its partial frame was rolled back"
            raise PersistenceError(msg) from error
        self._sequence = sequence
        self._log_bytes += len(frame)
        if operation == PUT:
            self._index[key] = value
        else:
            self._index.pop(key, None)

    def get(self, key: str) -> bytes | None:
        """Return immutable value bytes or ``None`` when the key is absent."""
        self._ensure_open()
        normalized, _ = self._key_bytes(key)
        return self._index.get(normalized)

    def put(self, key: str, value: BytesLike) -> None:
        """Durably append a value before updating the visible index."""
        self._ensure_open()
        normalized, encoded_key = self._key_bytes(key)
        copied_value = self._value_bytes(value)
        self._append(PUT, normalized, encoded_key, copied_value)

    def delete(self, key: str) -> bool:
        """Durably delete an existing key, returning whether it existed."""
        self._ensure_open()
        normalized, encoded_key = self._key_bytes(key)
        if normalized not in self._index:
            return False
        self._append(DELETE, normalized, encoded_key, b"")
        return True

    def keys(self) -> tuple[str, ...]:
        """Return a deterministic immutable snapshot of live keys."""
        self._ensure_open()
        return tuple(sorted(self._index))

    def stats(self) -> StoreStats:
        """Return counts and byte sizes without exposing keys or values."""
        self._ensure_open()
        return StoreStats(
            entries=len(self._index),
            sequence=self._sequence,
            log_bytes=self._log_bytes,
            recovered_bytes=self._recovered_bytes,
        )

    def _canonical_log(self) -> bytes:
        frames: list[bytes] = []
        total = 0
        for sequence, key in enumerate(sorted(self._index), start=1):
            frame = self._frame(PUT, sequence, key.encode("utf-8"), self._index[key])
            total += len(frame)
            if total > self._max_database_bytes:
                msg = "compacted state would exceed the configured database limit"
                raise LimitError(msg)
            frames.append(frame)
        return b"".join(frames)

    def _invoke_fault_hook(self, stage: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def _temporary_path(self) -> Path:
        return self._path.with_name(f".{self._path.name}.compact.tmp")

    @staticmethod
    def _cleanup_owned_temporary(path: Path, identity: tuple[int, int]) -> None:
        try:
            metadata = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            return
        if MiniKV._identity(metadata) == identity:
            path.unlink()

    def _validate_compacted_file(self, path: Path, expected_bytes: int) -> None:
        with MiniKV.open(path, max_database_bytes=self._max_database_bytes) as candidate:
            if candidate.keys() != tuple(sorted(self._index)) or any(
                candidate.get(key) != value for key, value in self._index.items()
            ):
                msg = "compacted file does not reconstruct the expected logical state"
                raise CorruptionError(msg)
            candidate_stats = candidate.stats()
            if (
                candidate_stats.sequence != len(self._index)
                or candidate_stats.log_bytes != expected_bytes
            ):
                msg = "compacted file metadata does not match the canonical state"
                raise CorruptionError(msg)

    def _fsync_parent_directory(self) -> bool:
        if os.name != "posix" or not hasattr(os, "O_DIRECTORY"):
            return False
        descriptor = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True

    def _rebind_after_compaction(self, new_log_bytes: int) -> None:
        self._file.close()
        flags = os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._path, flags)
        self._file = os.fdopen(descriptor, "r+b", buffering=0)
        self._file_identity = self._identity(os.fstat(self._file.fileno()))
        self._parent_identity = self._identity(self._path.parent.stat())
        self._sequence = len(self._index)
        self._log_bytes = new_log_bytes
        self._file.seek(new_log_bytes)

    def _write_compaction_temporary(self, path: Path, content: bytes) -> tuple[int, int]:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        identity = self._identity(os.fstat(descriptor))
        temporary_file = os.fdopen(descriptor, "w+b", buffering=0)
        try:
            split = len(content) // 2
            self._write_all_to(temporary_file, content[:split])
            self._invoke_fault_hook("compact_after_partial_write")
            self._write_all_to(temporary_file, content[split:])
            self._invoke_fault_hook("compact_after_write")
            temporary_file.flush()
            self._invoke_fault_hook("compact_after_flush")
            os.fsync(temporary_file.fileno())
        except Exception:
            temporary_file.close()
            self._cleanup_owned_temporary(path, identity)
            raise
        temporary_file.close()
        return identity

    def compact(self) -> CompactionStats:
        """Atomically replace mutation history with canonical live-state frames.

        Failures before replacement preserve the original database. A failure after
        replacement closes this handle because directory durability or rebinding
        could not be confirmed; callers must reopen the path and inspect the raised
        error.
        """
        self._ensure_open()
        self._assert_path_identity()
        content = self._canonical_log()
        old_log_bytes = self._log_bytes
        temporary_path = self._temporary_path()
        try:
            temporary_path.lstat()
        except FileNotFoundError:
            pass
        else:
            msg = "compaction temporary path already exists"
            raise PersistenceError(msg)

        temporary_identity: tuple[int, int] | None = None
        replaced = False
        try:
            temporary_identity = self._write_compaction_temporary(temporary_path, content)
            self._invoke_fault_hook("compact_before_validation")
            self._validate_compacted_file(temporary_path, len(content))
            self._assert_path_identity()
            self._invoke_fault_hook("compact_before_replace")
            temporary_path.replace(self._path)
            replaced = True
            self._invoke_fault_hook("compact_after_replace")
            self._invoke_fault_hook("compact_before_directory_fsync")
            parent_directory_fsynced = self._fsync_parent_directory()
            self._rebind_after_compaction(len(content))
        except Exception as error:
            if not replaced:
                if temporary_identity is not None:
                    self._cleanup_owned_temporary(temporary_path, temporary_identity)
                if isinstance(error, (LimitError, PersistenceError)):
                    raise
                msg = "compaction failed before replacement; original database preserved"
                raise PersistenceError(msg) from error
            self.close()
            msg = (
                "compaction replaced the database but post-replacement durability "
                "was not confirmed; reopen required"
            )
            raise PersistenceError(msg) from error

        return CompactionStats(
            entries=len(self._index),
            old_log_bytes=old_log_bytes,
            new_log_bytes=len(content),
            reclaimed_bytes=max(0, old_log_bytes - len(content)),
            parent_directory_fsynced=parent_directory_fsynced,
        )

    def close(self) -> None:
        """Close the handle. Calling close repeatedly is safe."""
        if self._closed:
            return
        self._closed = True
        self._file.close()
