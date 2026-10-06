"""AI incident analysis endpoint (PLAN.md §26)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, require
from app.db.session import get_db
from app.schemas.ai import AnalyzeResponse
from app.services.ai import IncidentAnalyzer

router = APIRouter()


def _analyzer(db: Session = Depends(get_db)) -> IncidentAnalyzer:
    return IncidentAnalyzer(db)


@router.post(
    "/{shipment_id}/analyze",
    response_model=AnalyzeResponse,
)
def analyze_shipment(
    shipment_id: uuid.UUID,
    analyzer: IncidentAnalyzer = Depends(_analyzer),
    user: AuthenticatedUser = Depends(require("incident:analyze")),
) -> AnalyzeResponse:
    """Analyze a shipment failure and suggest remediation.

    Advisory only: the response is a diagnosis for a human operator. The
    service never executes commands or changes infrastructure.
    """
    return analyzer.analyze(shipment_id)
