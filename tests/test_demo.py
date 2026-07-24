from __future__ import annotations

import json
from pathlib import Path

import pytest

from minikv.demo import DemoError, generate_demo, verify_demo


def test_demo_reproduces_without_sensitive_fields(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = generate_demo(first)
    generate_demo(second)
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "summary.md").read_bytes() == (second / "summary.md").read_bytes()
    serialized = json.dumps(manifest, sort_keys=True)
    for forbidden in ("Café", "binary", "temporary", str(tmp_path)):
        assert forbidden not in serialized
    assert manifest["package_version"] == "1.0.0"
    assert manifest["boundaries"]["events_dropped"] > 0


def test_demo_rejects_tampering_and_unexpected_files(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    generate_demo(output)
    (output / "summary.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(DemoError, match="checksum"):
        verify_demo(output)

    output = tmp_path / "extra"
    generate_demo(output)
    (output / "private.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(DemoError, match="file set"):
        verify_demo(output)
