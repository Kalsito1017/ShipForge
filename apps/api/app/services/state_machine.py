"""Shipment state machine — the only way a shipment's status may change.

Allowed transitions (PLAN.md §12 / AGENTS.md):

    CREATED    -> VALIDATING
    VALIDATING -> BUILDING | FAILED
    BUILDING   -> SCANNING | FAILED
    SCANNING   -> READY    | FAILED
    READY      -> PUBLISHED | FAILED
    FAILED     -> VALIDATING
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTransitionError
from app.models.shipment import Shipment, ShipmentEvent

CREATED = "CREATED"
VALIDATING = "VALIDATING"
BUILDING = "BUILDING"
SCANNING = "SCANNING"
READY = "READY"
PUBLISHED = "PUBLISHED"
FAILED = "FAILED"

ALL_STATUSES: frozenset[str] = frozenset(
    {CREATED, VALIDATING, BUILDING, SCANNING, READY, PUBLISHED, FAILED}
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    CREATED: frozenset({VALIDATING}),
    VALIDATING: frozenset({BUILDING, FAILED}),
    BUILDING: frozenset({SCANNING, FAILED}),
    SCANNING: frozenset({READY, FAILED}),
    READY: frozenset({PUBLISHED, FAILED}),
    PUBLISHED: frozenset(),
    FAILED: frozenset({VALIDATING}),
}


def validate_transition(current: str, new: str) -> None:
    """Raise InvalidTransitionError unless current -> new is allowed."""
    if current not in ALL_STATUSES:
        raise InvalidTransitionError(
            f"Unknown shipment status: {current}", current=current, new=new
        )
    if new not in ALL_STATUSES:
        raise InvalidTransitionError(f"Unknown shipment status: {new}", current=current, new=new)
    if new not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(
            f"Invalid transition: {current} -> {new}", current=current, new=new
        )


def transition(
    session: Session,
    shipment: Shipment,
    new_status: str,
    *,
    event_type: str | None = None,
    message: str = "",
    error_code: str | None = None,
    error_message: str | None = None,
    context: dict[str, Any] | None = None,
) -> Shipment:
    """Validate and apply a status change, recording a shipment_event.

    This is the single sanctioned mutation path for shipment status.
    """
    old_status = shipment.status
    validate_transition(old_status, new_status)

    shipment.status = new_status
    if new_status == FAILED:
        shipment.error_code = error_code
        shipment.error_message = error_message
    elif new_status == PUBLISHED:
        shipment.published_at = datetime.now(UTC)
        shipment.error_code = None
        shipment.error_message = None

    event_meta: dict[str, Any] = {"from": old_status, "to": new_status}
    if context:
        event_meta.update(context)

    session.add(
        ShipmentEvent(
            id=uuid.uuid4(),
            shipment_id=shipment.id,
            event_type=event_type or new_status,
            message=message or f"{old_status} -> {new_status}",
            meta=event_meta,
        )
    )
    session.flush()
    return shipment
