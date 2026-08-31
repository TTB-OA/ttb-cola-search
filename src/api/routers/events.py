"""First-party collector for interactions that never reach the API.

Facet, sort and paging changes are already visible server-side because the SPA
drives them through the URL; this endpoint exists only for the things that are
not, such as the onboarding tour and outbound download clicks.

The event name allowlist is deliberate: without it this is an open, unauthenticated
log sink.
"""
from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..analytics import emit, session_id_from
from ..config import get_settings
from ..ratelimit import SlidingWindowLimiter, client_key

router = APIRouter(tags=["analytics"])

ALLOWED_EVENTS = frozenset(
    {
        "tour_started",
        "tour_step_viewed",
        "tour_completed",
        "tour_dismissed",
        "advanced_panel_toggled",
        "view_mode_changed",
        "result_clicked",
        "label_face_switched",
        "lightbox_opened",
        "ocr_chip_clicked",
        "cola_form_downloaded",
        "form_viewed",
        "print_clicked",
        "describe_search_submitted",
        "image_search_abandoned",
        "image_search_state_lost",
        # Map mode and role are chosen client-side and never reach the URL the
        # viewport query carries, so the server cannot infer them.
        "map_mode_changed",
        "map_role_changed",
        "map_marker_clicked",
        "map_area_opened",
        # Basemap tiles are fetched by MapLibre, not by our code, so a failed
        # tile is invisible to the server unless the client says so.
        "map_tile_error",
        "client_api_error",
    }
)

MAX_EVENTS_PER_BATCH = 20
MAX_PROPS = 10
MAX_VALUE_LENGTH = 64
MAX_BODY_BYTES = 16 * 1024

_limiter: SlidingWindowLimiter | None = None


def _events_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowLimiter(120, 60)
    return _limiter


class ClientEvent(BaseModel):
    name: str
    props: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _known_event(cls, value: str) -> str:
        if value not in ALLOWED_EVENTS:
            raise ValueError("unknown event name")
        return value

    @field_validator("props")
    @classmethod
    def _bounded_props(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > MAX_PROPS:
            raise ValueError("too many properties")
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(item, (str, int, float, bool)) and item is not None:
                raise ValueError("property values must be scalars")
            cleaned[str(key)[:40]] = item[:MAX_VALUE_LENGTH] if isinstance(item, str) else item
        return cleaned


class EventBatch(BaseModel):
    events: Annotated[list[ClientEvent], Field(min_length=1, max_length=MAX_EVENTS_PER_BATCH)]


@router.post("/events", status_code=204, response_class=Response)
async def collect_events(request: Request) -> Response:
    settings = get_settings()

    key = client_key(request, settings.trust_forwarded_for)
    if _events_limiter().check(key) is not None:
        raise HTTPException(status_code=429, detail="Too many events.")

    # Parsed by hand so validation failures return 422 with a bare body, and so
    # text/plain beacons are accepted alongside application/json.
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large.")
    try:
        batch = EventBatch.model_validate(json.loads(raw or b"{}"))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="Malformed event payload.") from exc

    session_id = session_id_from(
        request,
        trust_forwarded_for=settings.trust_forwarded_for,
        salt=settings.analytics_salt,
    )
    for event in batch.events:
        # `event_source`, not `origin`: the search filter of that name would
        # otherwise overwrite it on the server side.
        emit(event.name, {**event.props, "session_id": session_id, "event_source": "client"})

    return Response(status_code=204)
