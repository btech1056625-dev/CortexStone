"""Provider-facing tests for bounded primary-calendar operations."""

import asyncio
import json

import httpx
import pytest

from cortexstone.agent.schemas.actions import ProposedAction
from cortexstone.tools.connectors.google_calendar import (
    GOOGLE_CALENDAR_EVENT_CREATE_TOOL,
    GOOGLE_CALENDAR_EVENT_READ_TOOL,
    GOOGLE_CALENDAR_SCOPE,
    GoogleCalendarConnector,
    GoogleCalendarProviderError,
)
from cortexstone.tools.connectors.google_calendar.events import MAX_CALENDAR_RESPONSE_BYTES


def event_payload(event_id: str = "event123") -> dict:
    return {
        "id": event_id,
        "summary": "Calendar review",
        "start": {"dateTime": "2026-10-30T09:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2026-10-30T10:00:00+05:30", "timeZone": "Asia/Kolkata"},
    }


def action(tool_name: str, arguments: dict, *, idempotency_key: str | None = None):
    return ProposedAction(
        tool_name=tool_name,
        target_ref="primary",
        arguments=arguments,
        purpose="Test a Calendar connector operation.",
        idempotency_key=idempotency_key,
    )


def test_list_events_uses_fixed_primary_calendar_and_bounds_response():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"items": [event_payload()]})

    async def exercise():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = GoogleCalendarConnector("google-test-token", client)
        try:
            result = await connector(
                action(
                    GOOGLE_CALENDAR_EVENT_READ_TOOL,
                    {
                        "time_min": "2026-10-30T00:00:00+05:30",
                        "time_max": "2026-10-31T00:00:00+05:30",
                        "time_zone": "Asia/Kolkata",
                        "limit": 10,
                    },
                )
            )
        finally:
            await client.aclose()
        return result

    result = asyncio.run(exercise())

    assert result[0].summary == "Calendar review"
    assert result[0].timezone == "Asia/Kolkata"
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.host == "www.googleapis.com"
    assert requests[0].url.path == "/calendar/v3/calendars/primary/events"
    assert requests[0].url.params["maxResults"] == "10"
    assert requests[0].headers["authorization"] == "Bearer google-test-token"
    assert GOOGLE_CALENDAR_SCOPE == "https://www.googleapis.com/auth/calendar.events.owned"


def test_create_event_reuses_deterministic_provider_id_after_conflict():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(409, json={"error": {"message": "already exists"}})
        return httpx.Response(200, json=event_payload(request.url.path.rsplit("/", 1)[-1]))

    async def exercise():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        connector = GoogleCalendarConnector("google-test-token", client)
        try:
            result = await connector(
                action(
                    GOOGLE_CALENDAR_EVENT_CREATE_TOOL,
                    {
                        "summary": "Calendar review",
                        "start": "2026-10-30T09:00:00+05:30",
                        "end": "2026-10-30T10:00:00+05:30",
                        "time_zone": "Asia/Kolkata",
                    },
                    idempotency_key="request-1",
                )
            )
        finally:
            await client.aclose()
        return result

    result = asyncio.run(exercise())

    assert result.summary == "Calendar review"
    assert [request.method for request in requests] == ["POST", "GET"]
    assert requests[0].url.host == "www.googleapis.com"
    created = json.loads(requests[0].content)
    assert requests[1].url.path.endswith(created["id"])
    assert created["start"]["timeZone"] == "Asia/Kolkata"


def test_calendar_connector_rejects_invalid_range_without_provider_request():
    async def exercise():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"items": []}))
        )
        connector = GoogleCalendarConnector("google-test-token", client)
        try:
            with pytest.raises(GoogleCalendarProviderError, match="time range"):
                await connector(
                    action(
                        GOOGLE_CALENDAR_EVENT_READ_TOOL,
                        {
                            "time_min": "2026-10-31T00:00:00+00:00",
                            "time_max": "2026-10-30T00:00:00+00:00",
                            "time_zone": "Asia/Kolkata",
                        },
                    )
                )
        finally:
            await client.aclose()

    asyncio.run(exercise())


def test_calendar_connector_rejects_oversized_provider_response():
    async def exercise():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    content=b"x" * (MAX_CALENDAR_RESPONSE_BYTES + 1),
                )
            )
        )
        connector = GoogleCalendarConnector("google-test-token", client)
        try:
            with pytest.raises(GoogleCalendarProviderError, match="oversized"):
                await connector(
                    action(
                        GOOGLE_CALENDAR_EVENT_READ_TOOL,
                        {
                            "time_min": "2026-10-30T00:00:00+00:00",
                            "time_max": "2026-10-31T00:00:00+00:00",
                            "time_zone": "UTC",
                        },
                    )
                )
        finally:
            await client.aclose()

    asyncio.run(exercise())
