from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from minikv import __version__
from minikv.release import verify_release_artifacts, write_checksums


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify MiniKV release artifacts")
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--write-checksums", action="store_true")
    arguments = parser.parse_args()
    if arguments.write_checksums:
        write_checksums(arguments.dist)
    artifacts = verify_release_artifacts(arguments.dist, expected_version=__version__)
    with tempfile.TemporaryDirectory(prefix="minikv-wheel-smoke-") as directory:
        environment = Path(directory)
        subprocess.run([sys.executable, "-m", "venv", environment], check=True)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-index",
                str(artifacts.wheel),
            ],
            check=True,
        )
        smoke = (
            "from pathlib import Path; from tempfile import TemporaryDirectory; "
            "import minikv; assert minikv.__version__ == '1.0.0'; "
            "d=TemporaryDirectory(); p=Path(d.name); "
            "s=minikv.MiniKV.open(p/'x.mkv'); s.put('k',b'v'); "
            "assert s.get('k')==b'v'; s.backup(p/'x.mkvb'); s.close(); "
            "minikv.MiniKV.restore(p/'x.mkvb',p/'y.mkv'); "
            "r=minikv.MiniKV.open(p/'y.mkv'); assert r.get('k')==b'v'; r.close()"
        )
        subprocess.run([str(python), "-I", "-c", smoke], check=True)


if __name__ == "__main__":
    main()
