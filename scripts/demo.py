from __future__ import annotations

import argparse
from pathlib import Path

from minikv.demo import generate_demo, verify_demo


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or verify MiniKV release demo")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify", type=Path)
    arguments = parser.parse_args()
    if arguments.output is not None:
        generate_demo(arguments.output)
    else:
        verify_demo(arguments.verify)


if __name__ == "__main__":
    main()
