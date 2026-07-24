"""Versioned privacy-safe operational events."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, TypeAlias

EVENT_SCHEMA_VERSION: Final = 1
EventName: TypeAlias = Literal[
    "backup.published",
    "mutation.delete_committed",
    "mutation.put_committed",
    "restore.completed",
    "store.closed",
    "store.compacted",
    "store.opened",
]
MetricValue: TypeAlias = int | bool
EventHook: TypeAlias = Callable[["OperationalEvent"], None]

EVENT_METRICS: Final[Mapping[EventName, frozenset[str]]] = MappingProxyType(
    {
        "backup.published": frozenset(
            {
                "artifact_bytes",
                "entries",
                "parent_directory_fsynced",
                "payload_bytes",
                "replaced_existing",
            }
        ),
        "mutation.delete_committed": frozenset({"entries", "log_bytes", "sequence"}),
        "mutation.put_committed": frozenset({"entries", "log_bytes", "sequence"}),
        "restore.completed": frozenset(
            {
                "entries",
                "parent_directory_fsynced",
                "payload_bytes",
                "replaced_existing",
            }
        ),
        "store.closed": frozenset({"entries", "events_dropped", "log_bytes", "sequence"}),
        "store.compacted": frozenset(
            {
                "entries",
                "new_log_bytes",
                "old_log_bytes",
                "parent_directory_fsynced",
                "reclaimed_bytes",
            }
        ),
        "store.opened": frozenset({"entries", "log_bytes", "recovered_bytes"}),
    }
)


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    """Immutable event containing only allowlisted non-sensitive metrics."""

    schema_version: int
    sequence: int
    name: EventName
    metrics: tuple[tuple[str, MetricValue], ...]

    def __post_init__(self) -> None:
        """Reject schema drift, reordered metrics, and unexpected value types."""
        if self.schema_version != EVENT_SCHEMA_VERSION:
            msg = "unsupported operational event schema version"
            raise ValueError(msg)
        if not isinstance(self.sequence, int) or isinstance(self.sequence, bool):
            msg = "operational event sequence must be an integer"
            raise TypeError(msg)
        if self.sequence < 1:
            msg = "operational event sequence must be positive"
            raise ValueError(msg)
        if self.name not in EVENT_METRICS:
            msg = "unknown operational event name"
            raise ValueError(msg)
        names = tuple(name for name, _ in self.metrics)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            msg = "operational event metrics must be unique and sorted"
            raise ValueError(msg)
        if frozenset(names) != EVENT_METRICS[self.name]:
            msg = "operational event metrics do not match the event contract"
            raise ValueError(msg)
        for _, metric_value in self.metrics:
            value: object = metric_value
            if not isinstance(value, int):
                msg = "operational event metric must be an integer or boolean"
                raise TypeError(msg)
            if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                msg = "operational event integer metrics must be non-negative"
                raise ValueError(msg)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable copy with deterministic metric ordering."""
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "name": self.name,
            "metrics": dict(self.metrics),
        }


def operational_event(
    event_sequence: int,
    name: EventName,
    **metrics: MetricValue,
) -> OperationalEvent:
    """Create one validated event from allowlisted metrics."""
    return OperationalEvent(
        schema_version=EVENT_SCHEMA_VERSION,
        sequence=event_sequence,
        name=name,
        metrics=tuple(sorted(metrics.items())),
    )
