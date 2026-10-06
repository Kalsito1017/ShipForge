"""Tests for Prometheus metrics and structured logging."""

import json
import logging
import re

from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from app.core.metrics import REGISTRY, render_metrics
from tests.conftest import requires_db


def _sample(name: str) -> float:
    """Read a counter/gauge value from the registry (0.0 when never updated)."""
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == name:
                return float(sample.value)
    return 0.0


class TestMetricsEndpoint:
    def test_metrics_exposed(self, client: TestClient) -> None:
        response = client.get("/metrics")
        assert response.status_code == 200
        body = response.text
        assert "api_requests_total" in body
        assert "shipments_created_total" in body
        assert "shipments_failed_total" in body
        assert "shipments_published_total" in body
        assert "shipment_processing_duration_seconds" in body
        assert "shipment_queue_size" in body

    def test_request_instrumentation_counts(self, client: TestClient) -> None:
        client.get("/health")
        body = client.get("/metrics").text
        # The middleware recorded at least the /health request.
        assert re.search(r'api_requests_total\{[^}]*path="/health"[^}]*\}', body)

    def test_render_metrics_content_type(self) -> None:
        payload, content_type = render_metrics()
        assert b"shipments_created_total" in payload
        assert "text/plain" in content_type


@requires_db
class TestShipmentMetrics:
    def test_create_increments_counter(self, client: TestClient) -> None:
        before = _sample("shipments_created_total")
        response = client.post(
            "/api/v1/shipments",
            json={"product": "metrics-service", "version": "1.0.0"},
        )
        assert response.status_code == 202
        assert _sample("shipments_created_total") == before + 1


class TestStructuredLogging:
    def test_json_formatter_required_fields(self) -> None:
        formatter = JsonFormatter(service="shipforge-api")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Dependency installation failed",
            args=(),
            exc_info=None,
        )
        payload = json.loads(formatter.format(record))

        assert payload["level"] == "INFO"
        assert payload["service"] == "shipforge-api"
        assert payload["message"] == "Dependency installation failed"
        assert re.match(r"^\d{4}-\d{2}-\d{2}T.*Z$", payload["timestamp"])

    def test_json_formatter_context_fields(self) -> None:
        formatter = JsonFormatter(service="shipforge-worker")
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Dependency installation failed",
            args=(),
            exc_info=None,
        )
        record.shipment_id = "123"
        record.stage = "BUILDING"
        record.error_code = "DEPENDENCY_ERROR"
        payload = json.loads(formatter.format(record))

        assert payload["shipment_id"] == "123"
        assert payload["stage"] == "BUILDING"
        assert payload["error_code"] == "DEPENDENCY_ERROR"

    def test_exception_rendered(self) -> None:
        formatter = JsonFormatter(service="shipforge-api")
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="unhandled",
                args=(),
                exc_info=sys.exc_info(),
            )
        payload = json.loads(formatter.format(record))
        assert "ValueError: boom" in payload["exception"]
