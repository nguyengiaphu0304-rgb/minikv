from __future__ import annotations

import email
import re
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_BYTES = 1_048_576
MAX_MEMBERS = 128
_WHEEL = re.compile(r"^minikv_store-(?P<version>\d+\.\d+\.\d+)-py3-none-any\.whl$")
_SDIST = re.compile(r"^minikv_store-(?P<version>\d+\.\d+\.\d+)\.tar\.gz$")


class ReleaseVerificationError(ValueError):
    """Raised when release artifacts violate the package contract."""


@dataclass(frozen=True, slots=True)
class VerifiedArtifacts:
    version: str
    wheel: Path
    sdist: Path
    checksums: Path


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _safe_name(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\\" in name:
        raise ReleaseVerificationError(f"unsafe archive member: {name}")


def _wheel_metadata(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if not infos or len(infos) > MAX_MEMBERS or len(set(names)) != len(names):
                raise ReleaseVerificationError("wheel member count or uniqueness is invalid")
            for info in infos:
                _safe_name(info.filename)
                kind = stat.S_IFMT(info.external_attr >> 16)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ReleaseVerificationError("wheel contains a non-regular member")
                if not (
                    info.filename.startswith("minikv/")
                    or info.filename.startswith("minikv_store-1.0.0.dist-info/")
                ):
                    raise ReleaseVerificationError("wheel contains an unexpected member")
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                raise ReleaseVerificationError("wheel must contain one METADATA file")
            metadata = email.message_from_bytes(archive.read(metadata_names[0]))
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise ReleaseVerificationError("wheel cannot be inspected") from error
    return str(metadata["Name"]), str(metadata["Version"])


def _verify_sdist(path: Path, version: str) -> None:
    root = f"minikv_store-{version}"
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if not members or len(members) > MAX_MEMBERS or len(set(names)) != len(names):
                raise ReleaseVerificationError("sdist member count or uniqueness is invalid")
            for member in members:
                _safe_name(member.name)
                if member.name.split("/", 1)[0] != root:
                    raise ReleaseVerificationError("sdist root is invalid")
                if not (member.isfile() or member.isdir()):
                    raise ReleaseVerificationError("sdist contains a non-regular member")
                relative = member.name.removeprefix(f"{root}/")
                if relative.startswith((".git/", ".venv/", "dist/", "build/")):
                    raise ReleaseVerificationError("sdist contains an excluded member")
    except (OSError, tarfile.TarError) as error:
        raise ReleaseVerificationError("sdist cannot be inspected") from error


def write_checksums(dist: Path) -> Path:
    archives = sorted(path for path in dist.iterdir() if path.name != "SHA256SUMS")
    if len(archives) != 2 or any(path.is_symlink() or not path.is_file() for path in archives):
        raise ReleaseVerificationError("dist must contain exactly two regular archives")
    target = dist / "SHA256SUMS"
    target.write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in archives),
        encoding="ascii",
    )
    return target


def verify_release_artifacts(dist: Path, *, expected_version: str) -> VerifiedArtifacts:
    if dist.is_symlink() or not dist.is_dir():
        raise ReleaseVerificationError("dist must be a regular directory")
    files = {path.name: path for path in dist.iterdir()}
    if len(files) != 3 or "SHA256SUMS" not in files:
        raise ReleaseVerificationError("dist must contain wheel, sdist, and SHA256SUMS only")
    if any(path.is_symlink() or not path.is_file() for path in files.values()):
        raise ReleaseVerificationError("release artifacts must be regular files")
    if any(path.stat().st_size > MAX_ARCHIVE_BYTES for path in files.values()):
        raise ReleaseVerificationError("release artifact exceeds the size budget")
    wheels = [path for name, path in files.items() if _WHEEL.fullmatch(name)]
    sdists = [path for name, path in files.items() if _SDIST.fullmatch(name)]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ReleaseVerificationError("release filenames are invalid")
    wheel_match = _WHEEL.fullmatch(wheels[0].name)
    sdist_match = _SDIST.fullmatch(sdists[0].name)
    if wheel_match is None or sdist_match is None:
        raise ReleaseVerificationError("release filenames could not be parsed")
    if wheel_match["version"] != expected_version or sdist_match["version"] != expected_version:
        raise ReleaseVerificationError("artifact filename version mismatch")
    name, metadata_version = _wheel_metadata(wheels[0])
    if name != "minikv-store" or metadata_version != expected_version:
        raise ReleaseVerificationError("wheel metadata name or version mismatch")
    _verify_sdist(sdists[0], expected_version)
    expected = {
        f"{digest(wheels[0])}  {wheels[0].name}",
        f"{digest(sdists[0])}  {sdists[0].name}",
    }
    try:
        actual = set(files["SHA256SUMS"].read_text(encoding="ascii").splitlines())
    except (OSError, UnicodeDecodeError) as error:
        raise ReleaseVerificationError("SHA256SUMS is not valid ASCII") from error
    if actual != expected:
        raise ReleaseVerificationError("release checksum mismatch")
    return VerifiedArtifacts(expected_version, wheels[0], sdists[0], files["SHA256SUMS"])
