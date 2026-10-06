"""Artifact validation helpers and storage-path rules."""

import hashlib
import re
import tarfile
import uuid
from typing import BinaryIO

from app.core.exceptions import (
    ARTIFACT_INVALID_TYPE,
    ARTIFACT_TOO_LARGE,
    VALIDATION_ERROR,
    AppError,
)

# Safe artifact filenames: no path separators, no leading dot.
FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,250}$")

ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/gzip",
        "application/x-gzip",
        "application/x-tar",
        "application/zip",
        "application/octet-stream",
    }
)

ALLOWED_EXTENSIONS = (".tar.gz", ".tgz", ".zip")


def validate_artifact_name(filename: str) -> None:
    """Reject unsafe or unsupported artifact filenames."""
    if not filename or not FILENAME_RE.match(filename):
        raise AppError(
            ARTIFACT_INVALID_TYPE,
            "Artifact filename contains invalid characters",
        )
    if any(sep in filename for sep in ("/", "\\", "..")):
        raise AppError(ARTIFACT_INVALID_TYPE, "Artifact filename must not contain path parts")
    if not filename.endswith(ALLOWED_EXTENSIONS):
        raise AppError(
            ARTIFACT_INVALID_TYPE,
            f"Artifact must be one of: {', '.join(ALLOWED_EXTENSIONS)}",
        )


def validate_content_type(content_type: str) -> None:
    """Reject content types outside the artifact allowlist."""
    base = content_type.split(";")[0].strip().lower()
    if base not in ALLOWED_CONTENT_TYPES:
        raise AppError(ARTIFACT_INVALID_TYPE, f"Unsupported artifact content type: {base}")


def validate_size(size: int, max_size_mb: int) -> None:
    """Reject artifacts over the configured size limit."""
    max_bytes = max_size_mb * 1024 * 1024
    if size <= 0:
        raise AppError(VALIDATION_ERROR, "Artifact is empty")
    if size > max_bytes:
        raise AppError(
            ARTIFACT_TOO_LARGE,
            f"Artifact exceeds the {max_size_mb} MB limit",
        )


def build_artifact_path(product: str, version: str, filename: str) -> str:
    """Return the canonical storage path: artifacts/{product}/{version}/{filename}."""
    validate_artifact_name(filename)
    return f"artifacts/{product}/{version}/{filename}"


def sha256_of(data: bytes) -> str:
    """Return the hex sha256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def archive_integrity_error(data: bytes, filename: str) -> str | None:
    """Return an error message when the archive is corrupt or empty, else None.

    ``.zip`` support is intentionally shallow (magic-byte check) for now; tar.gz
    archives are opened and listed fully.
    """
    if filename.endswith(".zip"):
        if not data.startswith(b"PK"):
            return "Archive is not a valid zip file"
        return None
    try:
        with tarfile.open(fileobj=_reader(data), mode="r:*") as archive:
            members = archive.getmembers()
    except tarfile.TarError as exc:
        return f"Archive is not a valid tarball: {exc}"
    if not members:
        return "Archive contains no files"
    return None


def _reader(data: bytes) -> BinaryIO:
    import io

    return io.BytesIO(data)


def new_artifact_id() -> uuid.UUID:
    """Return a fresh artifact identifier (used in event metadata)."""
    return uuid.uuid4()
