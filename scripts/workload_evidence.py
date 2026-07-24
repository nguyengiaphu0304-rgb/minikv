"""Generate and verify MiniKV deterministic workload evidence."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from minikv.evidence import run_workload, stable_from_dict, verify_evidence


def main() -> None:
    """Run the workload, compare stable fields, and write observed evidence."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    baseline_document = json.loads(arguments.baseline.read_text(encoding="utf-8"))
    if not isinstance(baseline_document, dict):
        msg = "baseline must be a JSON object"
        raise TypeError(msg)
    expected = stable_from_dict(baseline_document)
    with tempfile.TemporaryDirectory(prefix="minikv-evidence-") as temporary:
        evidence = run_workload(Path(temporary) / "workload")
    verify_evidence(evidence, expected=expected)
    arguments.output.write_text(
        json.dumps(evidence.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
