from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from minikv.release import (
    ReleaseVerificationError,
    verify_release_artifacts,
    write_checksums,
)


def _dist(root: Path, *, unsafe: bool = False, duplicate: bool = False) -> Path:
    dist = root / "dist"
    dist.mkdir(parents=True)
    wheel = dist / "minikv_store-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "minikv_store-1.0.0.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: minikv-store\nVersion: 1.0.0\n",
        )
        member = "../escape.py" if unsafe else "minikv/__init__.py"
        archive.writestr(member, "")
        if duplicate:
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(member, "")
    sdist = dist / "minikv_store-1.0.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        content = b"[project]\nname='minikv-store'\nversion='1.0.0'\n"
        info = tarfile.TarInfo("minikv_store-1.0.0/pyproject.toml")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return dist


def test_release_verifies_names_metadata_members_and_checksums(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    write_checksums(dist)
    result = verify_release_artifacts(dist, expected_version="1.0.0")
    assert result.version == "1.0.0"


@pytest.mark.parametrize(("unsafe", "duplicate"), [(True, False), (False, True)])
def test_release_rejects_unsafe_or_duplicate_members(
    tmp_path: Path, *, unsafe: bool, duplicate: bool
) -> None:
    dist = _dist(tmp_path, unsafe=unsafe, duplicate=duplicate)
    write_checksums(dist)
    with pytest.raises(ReleaseVerificationError):
        verify_release_artifacts(dist, expected_version="1.0.0")


def test_release_rejects_checksum_version_and_extra_artifact(tmp_path: Path) -> None:
    dist = _dist(tmp_path)
    write_checksums(dist)
    (dist / "SHA256SUMS").write_text("forged\n", encoding="ascii")
    with pytest.raises(ReleaseVerificationError, match="checksum"):
        verify_release_artifacts(dist, expected_version="1.0.0")

    dist = _dist(tmp_path / "version")
    write_checksums(dist)
    with pytest.raises(ReleaseVerificationError, match="version"):
        verify_release_artifacts(dist, expected_version="2.0.0")

    dist = _dist(tmp_path / "extra")
    write_checksums(dist)
    (dist / "unexpected.whl").write_bytes(b"x")
    with pytest.raises(ReleaseVerificationError, match="only"):
        verify_release_artifacts(dist, expected_version="1.0.0")
