"""Tests for the first-party client event collector."""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api import main  # noqa: E402
from api.analytics import EVENT_BY_ROUTE, route_key  # noqa: E402
from api.config import get_settings  # noqa: E402
from api.main import app  # noqa: E402
from api.routers import events as events_router  # noqa: E402

SESSION = "0f8fad5b-d9cb-469f-a165-70867728950e"


@pytest.fixture
def client():
    # Reset the module-level limiter so tests do not leak buckets into each other.
    events_router._limiter = None
    return TestClient(app)


@pytest.fixture
def captured(monkeypatch):
    records: list[logging.LogRecord] = []

    class Collector(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("analytics")
    handler = Collector()
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)


def post(client, payload, **kwargs):
    return client.post("/api/events", content=payload, **kwargs)


def test_accepts_an_allowlisted_event(client, captured):
    response = post(
        client,
        '{"events":[{"name":"tour_completed","props":{"steps":7}}]}',
        headers={"X-Client-Session": SESSION},
    )
    assert response.status_code == 204
    assert response.content == b""

    record = captured[-1]
    assert record.event == "tour_completed"
    assert record.steps == 7
    assert record.session_id == SESSION
    assert record.event_source == "client"


def test_rejects_unknown_event_names(client, captured):
    assert post(client, '{"events":[{"name":"exfiltrate"}]}').status_code == 422
    assert captured == []


def test_rejects_malformed_json(client):
    assert post(client, "not json").status_code == 422


def test_rejects_empty_batches(client):
    assert post(client, '{"events":[]}').status_code == 422


def test_rejects_oversized_batches(client):
    events = ",".join(['{"name":"print_clicked"}'] * 21)
    assert post(client, f'{{"events":[{events}]}}').status_code == 422


def test_rejects_too_many_properties(client):
    props = ",".join(f'"k{i}":1' for i in range(11))
    assert post(client, f'{{"events":[{{"name":"print_clicked","props":{{{props}}}}}]}}').status_code == 422


def test_rejects_non_scalar_property_values(client):
    assert post(
        client, '{"events":[{"name":"print_clicked","props":{"a":{"b":1}}}]}'
    ).status_code == 422


def test_truncates_long_property_values(client, captured):
    value = "x" * 500
    assert post(client, f'{{"events":[{{"name":"print_clicked","props":{{"v":"{value}"}}}}]}}').status_code == 204
    assert len(captured[-1].v) == 64


def test_rate_limits_a_noisy_client(client):
    statuses = {post(client, '{"events":[{"name":"print_clicked"}]}').status_code for _ in range(130)}
    assert statuses == {204, 429}


def test_missing_session_header_falls_back_to_a_hash(client, captured):
    assert post(client, '{"events":[{"name":"print_clicked"}]}').status_code == 204
    session = captured[-1].session_id
    assert len(session) == 32
    assert "testclient" not in session


def _api_routes(routes):
    """Every (method, router-local path) pair the app actually serves."""
    for route in routes:
        yield from _api_routes(getattr(getattr(route, "original_router", None), "routes", []))
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                yield route_key(method, route.path)


def test_every_tracked_route_still_exists():
    registered = set(_api_routes(app.routes))
    assert set(EVENT_BY_ROUTE) <= registered, sorted(registered)


def test_middleware_resolves_route_templates_at_runtime(client, captured, monkeypatch):
    monkeypatch.setitem(main.EVENT_BY_ROUTE, ("POST", "/events"), "probe")
    assert post(client, '{"events":[{"name":"print_clicked"}]}').status_code == 204

    probe = next(r for r in captured if r.event == "probe")
    assert probe.event_source == "server"
    assert probe.status_code == 204
    assert probe.duration_ms >= 0


def test_detail_events_carry_the_record_id(captured):
    """The id lives in the path, not the query string, so it needs its own branch."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/colas/26208001000457",
        "query_string": b"",
        "headers": [(b"x-client-session", SESSION.encode())],
        "path_params": {"cola_id": 26208001000457},
        "route": type("R", (), {"path": "/colas/{cola_id}"})(),
    }
    main._record_event(Request(scope), 200, time.perf_counter(), get_settings())

    record = next(r for r in captured if r.event == "detail_viewed")
    assert record.cola_id == "26208001000457"
