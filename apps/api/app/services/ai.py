"""AI incident assistant (PLAN.md §26).

Collects shipment context and asks an OpenAI-compatible LLM for a structured
diagnosis. The response is validated with Pydantic before it is returned.

SAFETY: advisory only. This module never executes commands, modifies
infrastructure, deletes artifacts, or deploys anything. It produces text
recommendations for a human operator.

Without an LLM_API_KEY a deterministic offline mock is used so the feature
works without credentials and in tests.
"""

import json
import logging
import uuid
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.shipment import Shipment, ShipmentLog
from app.repositories.shipment_repository import ShipmentRepository
from app.schemas.ai import AnalyzeResponse, IncidentAnalysis

logger = logging.getLogger(__name__)

# Deterministic mock heuristics keyed by error code (used when no LLM key).
_MOCK_RULES: tuple[tuple[str, str, str, float], ...] = (
    (
        "DEPENDENCY_ERROR",
        "DEPENDENCY",
        "A required dependency could not be installed or resolved. Registry "
        "availability or an invalid version constraint is the likely cause.",
        0.9,
    ),
    (
        "ARTIFACT_MISSING",
        "ARTIFACT",
        "The artifact referenced by the shipment is not present in storage. "
        "It may not have been uploaded or was removed before processing.",
        0.92,
    ),
    (
        "ARTIFACT_TOO_LARGE",
        "ARTIFACT",
        "The uploaded artifact exceeds the configured size limit.",
        0.95,
    ),
    (
        "ARTIFACT_INVALID_TYPE",
        "ARTIFACT",
        "The artifact filename or content type is not on the allowed list.",
        0.95,
    ),
    (
        "VALIDATION_ERROR",
        "VALIDATION",
        "Artifact validation failed: the archive is corrupt, empty, or does "
        "not match the expected manifest.",
        0.85,
    ),
    (
        "BUILD_FAILED",
        "BUILD",
        "The build stage failed while compiling or assembling the artifact. "
        "Inspect the build logs for the first failing step.",
        0.8,
    ),
    (
        "SCAN_FAILED",
        "SCAN",
        "The security scan reported findings that block publication. Review "
        "the scan report and remediate before retrying.",
        0.8,
    ),
    (
        "TIMEOUT",
        "TIMEOUT",
        "A pipeline stage exceeded its time budget and was aborted.",
        0.85,
    ),
)


class IncidentAnalyzer:
    """Builds shipment context and produces a validated incident analysis."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ShipmentRepository(session)
        self._settings = get_settings()

    def analyze(self, shipment_id: uuid.UUID) -> AnalyzeResponse:
        shipment = self._repo.get(shipment_id)
        if shipment is None:
            raise NotFoundError("Shipment not found", shipment_id=str(shipment_id))

        context = self._build_context(shipment)
        source: Literal["llm", "mock"] = "mock"
        analysis: IncidentAnalysis

        if self._settings.llm_api_key:
            try:
                analysis = self._analyze_with_llm(context)
                source = "llm"
            except Exception:
                logger.exception(
                    "LLM analysis failed, falling back to mock",
                    extra={"shipment_id": str(shipment_id), "stage": "ANALYZE"},
                )
                analysis = self._analyze_with_mock(shipment)
        else:
            analysis = self._analyze_with_mock(shipment)

        logger.info(
            "incident analysis produced",
            extra={
                "shipment_id": str(shipment_id),
                "stage": "ANALYZE",
                "error_code": shipment.error_code or "",
            },
        )
        return AnalyzeResponse(
            shipment_id=str(shipment.id),
            analysis=analysis,
            source=source,
            advisory=True,
        )

    # -- context collection -------------------------------------------------

    def _build_context(self, shipment: Shipment) -> dict[str, Any]:
        events = self._repo.list_events(shipment.id)
        logs = (
            self._session.query(ShipmentLog)
            .filter_by(shipment_id=shipment.id)
            .order_by(ShipmentLog.created_at.asc())
            .limit(200)
            .all()
        )
        return {
            "shipment": {
                "id": str(shipment.id),
                "product": shipment.product,
                "version": shipment.version,
                "status": shipment.status,
                "error_code": shipment.error_code,
                "error_message": shipment.error_message,
                "created_at": shipment.created_at.isoformat() if shipment.created_at else None,
            },
            "events": [
                {
                    "event_type": e.event_type,
                    "message": e.message,
                    "created_at": e.created_at.isoformat(),
                }
                for e in events
            ],
            "logs": [
                {
                    "level": entry.level,
                    "stage": entry.stage,
                    "message": entry.message,
                }
                for entry in logs
            ],
            "environment": {
                "app_env": self._settings.app_env,
                # No secrets: only non-sensitive operational facts.
                "artifact_max_size_mb": self._settings.artifact_max_size_mb,
            },
        }

    # -- LLM path -----------------------------------------------------------

    def _analyze_with_llm(self, context: dict[str, Any]) -> IncidentAnalysis:
        """Call an OpenAI-compatible chat completions endpoint."""
        import httpx

        system_prompt = (
            "You are a software shipment incident assistant. Analyze the "
            "provided shipment context and respond with a JSON object with "
            "exactly these keys: category (one of DEPENDENCY, ARTIFACT, "
            "VALIDATION, BUILD, SCAN, TIMEOUT, INFRASTRUCTURE, CONFIGURATION, "
            "UNKNOWN), root_cause (string), confidence (number 0-1), severity "
            "(one of LOW, MEDIUM, HIGH, CRITICAL), recommendations (array of "
            "1-10 short actionable strings). Respond with JSON only, no prose. "
            "You are advisory only: never suggest executing commands "
            "automatically, only recommend actions for a human operator."
        )
        payload = {
            "model": self._settings.llm_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(context, default=str)},
            ],
        }
        response = httpx.post(
            f"{self._settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        data = json.loads(content)
        # Pydantic validation of the LLM output — rejects malformed answers.
        return IncidentAnalysis.model_validate(data)

    # -- mock path ----------------------------------------------------------

    def _analyze_with_mock(self, shipment: Shipment) -> IncidentAnalysis:
        """Deterministic offline analysis (no credentials required)."""
        error_code = shipment.error_code or ""
        for code, category, root_cause, confidence in _MOCK_RULES:
            if error_code == code:
                return IncidentAnalysis(
                    category=category,  # type: ignore[arg-type]
                    root_cause=root_cause,
                    confidence=confidence,
                    severity="MEDIUM" if confidence < 0.9 else "HIGH",
                    recommendations=self._recommendations(category),
                )

        if shipment.status == "PUBLISHED":
            return IncidentAnalysis(
                category="UNKNOWN",
                root_cause="The shipment completed successfully; no incident to analyze.",
                confidence=0.99,
                severity="LOW",
                recommendations=["No action required."],
            )

        return IncidentAnalysis(
            category="UNKNOWN",
            root_cause=(
                f"Shipment is in state {shipment.status} without a recorded "
                "error code; insufficient evidence for a specific diagnosis."
            ),
            confidence=0.4,
            severity="LOW",
            recommendations=[
                "Inspect the shipment event trail for the last transition.",
                "Review worker logs for unreported errors.",
            ],
        )

    @staticmethod
    def _recommendations(category: str) -> list[str]:
        table = {
            "DEPENDENCY": [
                "Check package registry availability.",
                "Verify the dependency version exists.",
                "Rebuild the artifact after fixing dependencies.",
            ],
            "ARTIFACT": [
                "Verify the artifact was uploaded to storage.",
                "Check the artifact filename and content type.",
                "Re-upload the artifact and retry the shipment.",
            ],
            "VALIDATION": [
                "Inspect the archive for corruption.",
                "Verify the manifest and checksums.",
                "Repackage the artifact and retry.",
            ],
            "BUILD": [
                "Review the build stage logs for the first failing step.",
                "Reproduce the build locally.",
                "Fix the build input and retry the shipment.",
            ],
            "SCAN": [
                "Review the scan findings report.",
                "Remediate the reported issues.",
                "Retry the shipment after remediation.",
            ],
            "TIMEOUT": [
                "Check for slow external dependencies.",
                "Increase the stage timeout if justified.",
                "Retry the shipment.",
            ],
        }
        return table.get(
            category,
            ["Inspect the shipment events and logs.", "Retry the shipment if appropriate."],
        )
