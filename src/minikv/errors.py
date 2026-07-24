"""Public MiniKV exception hierarchy."""


class MiniKVError(Exception):
    """Base class for MiniKV failures."""


class CorruptionError(MiniKVError):
    """The log contains a complete frame that violates the storage contract."""


class LimitError(MiniKVError):
    """An input or database would exceed an explicit resource limit."""


class ClosedError(MiniKVError):
    """An operation was attempted after the database was closed."""


class ConcurrencyError(MiniKVError):
    """Another cooperating process owns the database lifetime lock."""


class PersistenceError(MiniKVError):
    """A mutation could not be durably persisted and was rolled back."""
