"""Artifact storage backends: MinIO in production, in-memory for tests."""

import io
from collections.abc import Iterator
from functools import lru_cache
from typing import BinaryIO, Protocol

from app.core.config import get_settings


class ArtifactStorage(Protocol):
    """Minimal object-storage interface used by API and worker."""

    def put(self, path: str, data: BinaryIO, size: int, content_type: str) -> None:
        """Store an object at ``path``."""

    def get(self, path: str) -> bytes:
        """Return object bytes; raise ``KeyError`` if missing."""

    def exists(self, path: str) -> bool:
        """Return True when the object exists."""


class InMemoryStorage:
    """Dict-backed storage for unit/API tests."""

    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    def put(self, path: str, data: BinaryIO, size: int, content_type: str) -> None:
        self._objects[path] = (data.read(), content_type)

    def get(self, path: str) -> bytes:
        if path not in self._objects:
            raise KeyError(path)
        return self._objects[path][0]

    def exists(self, path: str) -> bool:
        return path in self._objects


class MinioStorage:
    """S3-compatible artifact storage backed by MinIO."""

    def __init__(self) -> None:
        # Import lazily so the API can boot without the SDK in unit tests.
        from minio import Minio
        from minio.error import S3Error

        self._s3error = S3Error
        settings = get_settings()
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def put(self, path: str, data: BinaryIO, size: int, content_type: str) -> None:
        self._ensure_bucket()
        self._client.put_object(self._bucket, path, data, size, content_type=content_type)

    def get(self, path: str) -> bytes:
        self._ensure_bucket()
        try:
            response = self._client.get_object(self._bucket, path)
        except self._s3error as exc:
            if exc.code in ("NoSuchKey", "NoSuchBucket"):
                raise KeyError(path) from exc
            raise
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, path: str) -> bool:
        self._ensure_bucket()
        try:
            self._client.stat_object(self._bucket, path)
            return True
        except self._s3error as exc:
            if exc.code in ("NoSuchKey", "NoSuchBucket"):
                return False
            raise


@lru_cache(maxsize=1)
def get_storage() -> ArtifactStorage:
    """Return the configured storage backend."""
    return MinioStorage()


def open_bytes(data: bytes) -> Iterator[bytes]:
    """Helper for tests that need a file-like object over bytes."""
    return iter((data,))


def bytes_reader(data: bytes) -> BinaryIO:
    """Return a binary file-like object over ``data``."""
    return io.BytesIO(data)
