"""Pipeline stage implementations (PLAN.md §14, §16).

Stage semantics
---------------
Validate : real checks — artifact exists in storage, archive opens cleanly,
           manifest/checksum sanity.
Build    : deterministic simulated build (extract + fake compile) with logs.
Scan     : real checksum/manifest scan; simulated vulnerability scan.
Publish  : mark the artifact published (READY -> PUBLISHED via state machine).

Deterministic failure simulation (PLAN.md §16): products named
``failure-validation``, ``failure-build``, ``failure-scan`` and
``failure-timeout`` fail in the corresponding stage with a stable error code.
"""

import tarfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.artifacts import archive_integrity_error
from app.core.logging import get_logger
from app.core.storage import ArtifactStorage
from app.models.shipment import Shipment, ShipmentLog

logger = get_logger(__name__)

# Deterministic failure products (PLAN.md §16).
FAILURE_VALIDATION = "failure-validation"
FAILURE_BUILD = "failure-build"
FAILURE_SCAN = "failure-scan"
FAILURE_TIMEOUT = "failure-timeout"

FAILURE_PRODUCTS = {
    FAILURE_VALIDATION: ("VALIDATION_ERROR", "Simulated validation failure"),
    FAILURE_BUILD: ("BUILD_FAILED", "Simulated build failure"),
    FAILURE_SCAN: ("SCAN_FAILED", "Simulated scan failure"),
    FAILURE_TIMEOUT: ("TIMEOUT", "Simulated stage timeout"),
}


@dataclass
class StageResult:
    """Outcome of a single stage run."""

    stage: str
    ok: bool
    duration_seconds: float
    logs: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class PipelineStages:
    """Runs Validate -> Build -> Scan -> Publish against a shipment."""

    def __init__(self, session: Session, storage: ArtifactStorage) -> None:
        self._session = session
        self._storage = storage

    # -- helpers ---------------------------------------------------------

    def _log(self, shipment: Shipment, stage: str, message: str, **context: Any) -> None:
        self._session.add(
            ShipmentLog(
                id=uuid.uuid4(),
                shipment_id=shipment.id,
                stage=stage,
                level="INFO",
                message=message,
                context=context or None,
            )
        )
        logger.info(message, extra={"shipment_id": str(shipment.id), "stage": stage, **context})

    def _fail(self, shipment: Shipment, stage: str, error_code: str, message: str) -> StageResult:
        self._session.add(
            ShipmentLog(
                id=uuid.uuid4(),
                shipment_id=shipment.id,
                stage=stage,
                level="ERROR",
                message=message,
                context={"error_code": error_code},
            )
        )
        logger.error(
            message,
            extra={
                "shipment_id": str(shipment.id),
                "stage": stage,
                "error_code": error_code,
            },
        )
        return StageResult(
            stage=stage,
            ok=False,
            duration_seconds=0.0,
            error_code=error_code,
            error_message=message,
        )

    def _maybe_simulate_failure(self, shipment: Shipment, stage: str) -> StageResult | None:
        """Return a deterministic failure result for failure-* products."""
        expected_stage = {
            FAILURE_VALIDATION: "VALIDATING",
            FAILURE_BUILD: "BUILDING",
            FAILURE_SCAN: "SCANNING",
            FAILURE_TIMEOUT: "VALIDATING",
        }
        if shipment.product in FAILURE_PRODUCTS and expected_stage[shipment.product] == stage:
            code, message = FAILURE_PRODUCTS[shipment.product]
            return self._fail(shipment, stage, code, message)
        return None

    # -- stages ----------------------------------------------------------

    def validate(self, shipment: Shipment) -> StageResult:
        started = time.monotonic()
        simulated = self._maybe_simulate_failure(shipment, "VALIDATING")
        if simulated is not None:
            return simulated

        if not shipment.artifact_path:
            return self._fail(
                shipment, "VALIDATING", "ARTIFACT_MISSING", "Shipment has no artifact"
            )
        if not self._storage.exists(shipment.artifact_path):
            return self._fail(
                shipment,
                "VALIDATING",
                "ARTIFACT_MISSING",
                f"Artifact not found in storage: {shipment.artifact_path}",
            )

        try:
            data = self._storage.get(shipment.artifact_path)
        except KeyError:
            return self._fail(
                shipment,
                "VALIDATING",
                "ARTIFACT_MISSING",
                f"Artifact not readable: {shipment.artifact_path}",
            )

        integrity_error = archive_integrity_error(data, shipment.artifact_name or "")
        if integrity_error is not None:
            return self._fail(shipment, "VALIDATING", "VALIDATION_ERROR", integrity_error)

        self._log(
            shipment,
            "VALIDATING",
            "Artifact validated",
            size=len(data),
            path=shipment.artifact_path,
        )
        return StageResult(
            stage="VALIDATING",
            ok=True,
            duration_seconds=time.monotonic() - started,
            logs=["artifact integrity ok"],
        )

    def build(self, shipment: Shipment) -> StageResult:
        started = time.monotonic()
        simulated = self._maybe_simulate_failure(shipment, "BUILDING")
        if simulated is not None:
            return simulated

        if not shipment.artifact_path:
            return self._fail(shipment, "BUILDING", "ARTIFACT_MISSING", "Shipment has no artifact")

        try:
            data = self._storage.get(shipment.artifact_path)
        except KeyError:
            return self._fail(
                shipment,
                "BUILDING",
                "ARTIFACT_MISSING",
                f"Artifact not readable: {shipment.artifact_path}",
            )

        # Deterministic simulated build: list archive contents as build steps.
        steps: list[str] = []
        try:
            import io

            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                for member in archive.getmembers()[:20]:
                    steps.append(f"compiled {member.name}")
        except tarfile.TarError:
            steps.append("compiled archive (non-tar payload)")

        for step in steps:
            self._log(shipment, "BUILDING", step)

        self._log(shipment, "BUILDING", "Build completed", steps=len(steps))
        return StageResult(
            stage="BUILDING",
            ok=True,
            duration_seconds=time.monotonic() - started,
            logs=steps,
        )

    def scan(self, shipment: Shipment) -> StageResult:
        started = time.monotonic()
        simulated = self._maybe_simulate_failure(shipment, "SCANNING")
        if simulated is not None:
            return simulated

        if not shipment.artifact_path:
            return self._fail(shipment, "SCANNING", "ARTIFACT_MISSING", "Shipment has no artifact")

        try:
            data = self._storage.get(shipment.artifact_path)
        except KeyError:
            return self._fail(
                shipment,
                "SCANNING",
                "ARTIFACT_MISSING",
                f"Artifact not readable: {shipment.artifact_path}",
            )

        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        self._log(
            shipment,
            "SCANNING",
            "Scan completed",
            sha256=digest,
            findings=0,
        )
        return StageResult(
            stage="SCANNING",
            ok=True,
            duration_seconds=time.monotonic() - started,
            logs=[f"sha256={digest}", "no findings"],
        )

    def publish(self, shipment: Shipment) -> StageResult:
        started = time.monotonic()
        self._log(shipment, "PUBLISHING", "Artifact published")
        return StageResult(
            stage="PUBLISHING",
            ok=True,
            duration_seconds=time.monotonic() - started,
            logs=["published"],
        )
