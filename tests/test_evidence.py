from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from minikv.evidence import (
    MAX_TOTAL_NS,
    StableEvidence,
    run_workload,
    stable_from_dict,
    verify_evidence,
)


def baseline() -> StableEvidence:
    document = json.loads(Path("evidence/workload-v1.json").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return stable_from_dict(document)


def test_workload_regenerates_checked_stable_evidence(tmp_path: Path) -> None:
    evidence = run_workload(tmp_path / "workload")
    verify_evidence(evidence, expected=baseline())
    serialized = json.dumps(evidence.to_dict(), sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "record-000" not in serialized
    assert "Café" not in serialized
    assert "normalized" not in serialized


def test_tampered_stable_evidence_is_rejected(tmp_path: Path) -> None:
    evidence = run_workload(tmp_path / "workload")
    tampered = replace(
        evidence,
        stable=replace(evidence.stable, compacted_bytes=evidence.stable.compacted_bytes + 1),
    )
    with pytest.raises(ValueError, match="checked baseline"):
        verify_evidence(tampered, expected=baseline())


def test_exceeded_timing_budget_is_rejected(tmp_path: Path) -> None:
    evidence = run_workload(tmp_path / "workload")
    too_slow = replace(
        evidence,
        observation=replace(evidence.observation, total_ns=MAX_TOTAL_NS + 1),
    )
    with pytest.raises(ValueError, match="total smoke budget"):
        verify_evidence(too_slow)


def test_baseline_parser_rejects_unknown_fields() -> None:
    document = json.loads(Path("evidence/workload-v1.json").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    document["database_path"] = "must-not-be-accepted"
    with pytest.raises(ValueError, match="fields"):
        stable_from_dict(document)


def test_baseline_parser_rejects_type_confusion() -> None:
    document = json.loads(Path("evidence/workload-v1.json").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    document["event_count"] = "98"
    with pytest.raises(TypeError, match="event_count"):
        stable_from_dict(document)
