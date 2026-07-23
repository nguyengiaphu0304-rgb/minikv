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
        file: BinaryIO,
        *,
        max_database_bytes: int,
        fault_hook: FaultHook | None,
    ) -> None:
        """Build an index from an already validated and opened file."""
        self._file = file
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
        database = Path(path)
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

    def _write_all(self, content: bytes) -> None:
        pending = memoryview(content)
        while pending:
            written = self._file.write(pending)
            if written is None or written <= 0:
                msg = "storage write made no forward progress"
                raise OSError(msg)
            pending = pending[written:]

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

    def close(self) -> None:
        """Close the handle. Calling close repeatedly is safe."""
        if self._closed:
            return
        self._closed = True
        self._file.close()
