"""Unit tests for artifact validation helpers."""


import pytest

from app.core.artifacts import (
    archive_integrity_error,
    build_artifact_path,
    sha256_of,
    validate_artifact_name,
    validate_content_type,
    validate_size,
)
from app.core.exceptions import AppError


class TestFilenameValidation:
    @pytest.mark.parametrize(
        "name",
        ["payment-service-2.4.1.tar.gz", "a.tgz", "release_1.0.zip", "x.tar.gz"],
    )
    def test_valid(self, name: str) -> None:
        validate_artifact_name(name)

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "../evil.tar.gz",
            "dir/file.tar.gz",
            "back\\slash.tar.gz",
            "no-extension",
            "bad.tar.gz.sh",
            ".hidden.tar.gz",
            "space name.tar.gz",
        ],
    )
    def test_invalid(self, name: str) -> None:
        with pytest.raises(AppError):
            validate_artifact_name(name)


class TestContentTypeValidation:
    @pytest.mark.parametrize(
        "content_type",
        ["application/gzip", "application/x-gzip", "application/zip", "application/octet-stream"],
    )
    def test_valid(self, content_type: str) -> None:
        validate_content_type(content_type)

    @pytest.mark.parametrize("content_type", ["text/html", "application/x-executable", ""])
    def test_invalid(self, content_type: str) -> None:
        with pytest.raises(AppError):
            validate_content_type(content_type)


class TestSizeValidation:
    def test_valid(self) -> None:
        validate_size(1024, max_size_mb=1)

    def test_empty_rejected(self) -> None:
        with pytest.raises(AppError) as exc:
            validate_size(0, max_size_mb=1)
        assert exc.value.error_code == "VALIDATION_ERROR"

    def test_too_large_rejected(self) -> None:
        with pytest.raises(AppError) as exc:
            validate_size(2 * 1024 * 1024, max_size_mb=1)
        assert exc.value.error_code == "ARTIFACT_TOO_LARGE"


class TestStoragePath:
    def test_layout(self) -> None:
        path = build_artifact_path("payment-service", "2.4.1", "payment-service-2.4.1.tar.gz")
        assert path == "artifacts/payment-service/2.4.1/payment-service-2.4.1.tar.gz"

    def test_rejects_traversal_via_filename(self) -> None:
        with pytest.raises(AppError):
            build_artifact_path("product", "1.0.0", "../escape.tar.gz")


class TestArchiveIntegrity:
    def test_garbage_gz_is_reported(self) -> None:
        assert archive_integrity_error(b"not a tarball", "x.tar.gz") is not None

    def test_zip_magic_missing_is_reported(self) -> None:
        assert archive_integrity_error(b"nope", "x.zip") is not None

    def test_sha256(self) -> None:
        assert sha256_of(b"abc") == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )
