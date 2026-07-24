"""Public MiniKV API."""

from importlib.metadata import version

from minikv.errors import (
    ClosedError,
    ConcurrencyError,
    CorruptionError,
    LimitError,
    MiniKVError,
    PersistenceError,
)
from minikv.events import EVENT_SCHEMA_VERSION, EventHook, OperationalEvent
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

__version__ = version("minikv-store")

__all__ = [
    "BACKUP_MAGIC",
    "BACKUP_VERSION",
    "DEFAULT_MAX_DATABASE_BYTES",
    "EVENT_SCHEMA_VERSION",
    "FORMAT_VERSION",
    "HARD_MAX_DATABASE_BYTES",
    "MAX_KEY_BYTES",
    "MAX_VALUE_BYTES",
    "BackupStats",
    "ClosedError",
    "CompactionStats",
    "ConcurrencyError",
    "CorruptionError",
    "EventHook",
    "LimitError",
    "MiniKV",
    "MiniKVError",
    "OperationalEvent",
    "PersistenceError",
    "RestoreStats",
    "StoreStats",
    "__version__",
]
