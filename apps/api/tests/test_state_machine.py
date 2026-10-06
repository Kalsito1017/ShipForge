"""Unit tests for the shipment state machine."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTransitionError
from app.models.shipment import Shipment, ShipmentEvent
from app.services import state_machine as sm
from tests.conftest import requires_db

ALL = sorted(sm.ALL_STATUSES)
ALLOWED_PAIRS = sorted(
    (source, target) for source, targets in sm.ALLOWED_TRANSITIONS.items() for target in targets
)
FORBIDDEN_PAIRS = [
    (source, target) for source in ALL for target in ALL if (source, target) not in ALLOWED_PAIRS
]


class TestValidateTransition:
    @pytest.mark.parametrize(("source", "target"), ALLOWED_PAIRS)
    def test_allowed(self, source: str, target: str) -> None:
        sm.validate_transition(source, target)

    @pytest.mark.parametrize(("source", "target"), FORBIDDEN_PAIRS)
    def test_forbidden(self, source: str, target: str) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.validate_transition(source, target)

    def test_unknown_current_status(self) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.validate_transition("NOPE", sm.VALIDATING)

    def test_unknown_target_status(self) -> None:
        with pytest.raises(InvalidTransitionError):
            sm.validate_transition(sm.CREATED, "NOPE")


@requires_db
class TestTransition:
    def _shipment(self, session: Session, status: str = sm.CREATED) -> Shipment:
        shipment = Shipment(
            id=uuid.uuid4(),
            product="payment-service",
            version="2.4.1",
            status=status,
        )
        session.add(shipment)
        session.flush()
        return shipment

    def test_transition_updates_status_and_writes_event(self, db_session: Session) -> None:
        shipment = self._shipment(db_session)
        sm.transition(db_session, shipment, sm.VALIDATING, message="starting validation")
        db_session.commit()

        assert shipment.status == sm.VALIDATING
        events = db_session.query(ShipmentEvent).filter_by(shipment_id=shipment.id).all()
        assert len(events) == 1
        assert events[0].event_type == sm.VALIDATING
        assert events[0].message == "starting validation"
        assert events[0].meta == {"from": sm.CREATED, "to": sm.VALIDATING}

    def test_published_sets_published_at(self, db_session: Session) -> None:
        shipment = self._shipment(db_session, status=sm.READY)
        sm.transition(db_session, shipment, sm.PUBLISHED)
        db_session.commit()

        assert shipment.published_at is not None
        assert shipment.error_code is None

    def test_failed_records_error(self, db_session: Session) -> None:
        shipment = self._shipment(db_session, status=sm.BUILDING)
        sm.transition(
            db_session,
            shipment,
            sm.FAILED,
            error_code="BUILD_FAILED",
            error_message="dependency install failed",
        )
        db_session.commit()

        assert shipment.status == sm.FAILED
        assert shipment.error_code == "BUILD_FAILED"
        assert shipment.error_message == "dependency install failed"

    def test_invalid_transition_leaves_state_untouched(self, db_session: Session) -> None:
        shipment = self._shipment(db_session)
        with pytest.raises(InvalidTransitionError):
            sm.transition(db_session, shipment, sm.PUBLISHED)
        assert shipment.status == sm.CREATED

    def test_event_context_merged(self, db_session: Session) -> None:
        shipment = self._shipment(db_session, status=sm.FAILED)
        sm.transition(
            db_session,
            shipment,
            sm.VALIDATING,
            event_type="RETRY",
            context={"reason": "manual retry"},
        )
        db_session.commit()

        event = db_session.query(ShipmentEvent).filter_by(shipment_id=shipment.id).one()
        assert event.event_type == "RETRY"
        assert event.meta is not None
        assert event.meta["reason"] == "manual retry"
        assert event.meta["from"] == sm.FAILED
        assert event.meta["to"] == sm.VALIDATING
