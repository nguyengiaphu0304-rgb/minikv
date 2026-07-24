from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from minikv import ConcurrencyError, CorruptionError, MiniKV, __version__
from minikv.evidence import run_workload, verify_evidence

SCHEMA = "minikv.demo.v1"
FILES = {"manifest.json", "summary.md"}


class DemoError(ValueError):
    """Raised when release demo evidence violates its contract."""


def _exercise_boundaries(root: Path) -> dict[str, bool | int]:
    root.mkdir(parents=True)
    database = root / "demo.mkv"
    backup = root / "demo.mkvb"
    restored = root / "restored.mkv"
    events_dropped = 0

    def fail_event(_event: object) -> None:
        raise RuntimeError("synthetic event sink failure")

    with MiniKV.open(database, event_hook=fail_event) as store:
        store.put("Cafe\u0301", b"first")
        store.put("empty", b"")
        store.put("binary", bytes(range(32)))
        store.put("temporary", b"delete-me")
        store.delete("temporary")
        store.put("Caf\u00e9", b"overwritten")
        store.compact()
        events_dropped = store.stats().events_dropped
        try:
            MiniKV.open(database)
        except ConcurrencyError:
            concurrent_open_rejected = True
        else:
            concurrent_open_rejected = False
        store.backup(backup)

    result = MiniKV.restore(backup, restored)
    with MiniKV.open(restored) as reopened:
        recovery_equal = (
            reopened.get("Caf\u00e9") == b"overwritten"
            and reopened.get("empty") == b""
            and reopened.get("binary") == bytes(range(32))
            and reopened.get("temporary") is None
        )

    corrupted = root / "corrupted.mkvb"
    content = bytearray(backup.read_bytes())
    content[-1] ^= 0x01
    corrupted.write_bytes(content)
    try:
        MiniKV.restore(corrupted, root / "must-not-exist.mkv")
    except CorruptionError:
        corrupted_backup_rejected = True
    else:
        corrupted_backup_rejected = False

    return {
        "concurrent_open_rejected": concurrent_open_rejected,
        "corrupted_backup_rejected": corrupted_backup_rejected,
        "events_dropped": events_dropped,
        "recovery_equal": recovery_equal,
        "restored_entries": result.entries,
    }


def _manifest(root: Path) -> dict[str, Any]:
    evidence = run_workload(root / "workload")
    verify_evidence(evidence)
    boundaries = _exercise_boundaries(root / "boundaries")
    if not all(
        (
            boundaries["concurrent_open_rejected"],
            boundaries["corrupted_backup_rejected"],
            boundaries["recovery_equal"],
        )
    ):
        raise DemoError("a required release boundary was not demonstrated")
    stable = asdict(evidence.stable)
    return {
        "boundaries": boundaries,
        "counts": {
            "deletes": stable["deletes"],
            "events": stable["event_count"],
            "live_entries": stable["live_entries"],
            "puts": stable["puts"],
        },
        "lineage": {
            "backup_payload_sha256": stable["backup_payload_sha256"],
            "event_sha256": stable["event_sha256"],
            "fixture_sha256": stable["fixture_sha256"],
            "logical_state_sha256": stable["logical_state_sha256"],
        },
        "package_version": __version__,
        "schema_version": SCHEMA,
        "supported_contract": (
            "CPython 3.11-3.13; local POSIX filesystem with flock and atomic replace"
        ),
        "synthetic": True,
    }


def _summary(manifest: dict[str, Any]) -> bytes:
    counts = manifest["counts"]
    return (
        "# MiniKV v1.0 reproducible demo\n\n"
        "This offline demonstration uses only synthetic data. It verifies the bounded "
        "storage lifecycle, logical recovery, corruption rejection, cooperative process "
        "locking, and privacy-safe event failure handling. It is not a production "
        "benchmark or physical power-loss test.\n\n"
        f"- Puts: {counts['puts']}\n"
        f"- Deletes: {counts['deletes']}\n"
        f"- Live entries: {counts['live_entries']}\n"
        f"- Events: {counts['events']}\n"
        "- Backup recovery equal: true\n"
        "- Concurrent open rejected: true\n"
        "- Corrupted backup rejected: true\n"
    ).encode()


def generate_demo(output: Path) -> dict[str, Any]:
    if output.is_symlink():
        raise DemoError("demo output cannot be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise DemoError("demo output directory must be empty")
    with TemporaryDirectory(prefix="minikv-demo-") as directory:
        manifest = _manifest(Path(directory))
    summary = _summary(manifest)
    manifest["summary_sha256"] = sha256(summary).hexdigest()
    (output / "summary.md").write_bytes(summary)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verify_demo(output)
    return manifest


def verify_demo(output: Path) -> None:
    if output.is_symlink() or not output.is_dir():
        raise DemoError("demo output must be a regular directory")
    paths = tuple(output.iterdir())
    if {path.name for path in paths} != FILES:
        raise DemoError("demo output file set is invalid")
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise DemoError("demo outputs must be regular files")
    try:
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DemoError("manifest is not valid UTF-8 JSON") from error
    expected_fields = {
        "boundaries",
        "counts",
        "lineage",
        "package_version",
        "schema_version",
        "summary_sha256",
        "supported_contract",
        "synthetic",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_fields:
        raise DemoError("manifest fields do not match the schema")
    if manifest["schema_version"] != SCHEMA or manifest["package_version"] != __version__:
        raise DemoError("demo schema or package version is invalid")
    if manifest["synthetic"] is not True:
        raise DemoError("demo must be explicitly synthetic")
    summary = (output / "summary.md").read_bytes()
    if sha256(summary).hexdigest() != manifest["summary_sha256"]:
        raise DemoError("summary checksum mismatch")
    with TemporaryDirectory(prefix="minikv-demo-verify-") as directory:
        expected = _manifest(Path(directory))
    if {key: manifest[key] for key in expected} != expected:
        raise DemoError("demo manifest does not reproduce")
    if summary != _summary(expected):
        raise DemoError("demo summary does not reproduce")
