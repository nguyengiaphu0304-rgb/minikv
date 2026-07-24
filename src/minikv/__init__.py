"""Public MiniKV API."""

from minikv.errors import (
    ClosedError,
    ConcurrencyError,
    CorruptionError,
    LimitError,
    MiniKVError,
    PersistenceError,
)
from minikv.store import (
    BACKUP_MAGIC,
    BACKUP_VERSION,
    DEFAULT_MAX_DATABASE_BYTES,
    FORMAT_VERSION,
    HARD_MAX_DATABASE_BYTES,
    MAX_KEY_BYTES,
    MAX_VALUE_BYTES,
    BackupStats,
    CompactionStats,
    MiniKV,
    RestoreStats,
    StoreStats,
)

__all__ = [
    "BACKUP_MAGIC",
    "BACKUP_VERSION",
    "DEFAULT_MAX_DATABASE_BYTES",
    "FORMAT_VERSION",
    "HARD_MAX_DATABASE_BYTES",
    "MAX_KEY_BYTES",
    "MAX_VALUE_BYTES",
    "BackupStats",
    "ClosedError",
    "CompactionStats",
    "ConcurrencyError",
    "CorruptionError",
    "LimitError",
    "MiniKV",
    "MiniKVError",
    "PersistenceError",
    "RestoreStats",
    "StoreStats",
]
