"""Policy-dispatched Google Calendar event operations for a linked user account."""

import hashlib
import json
import re
from base64 import b32hexencode
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from pydantic import BaseModel, ConfigDict, Field

from cortexstone.agent.schemas.actions import ProposedAction

GOOGLE_CALENDAR_EVENT_READ_TOOL = "google_calendar.events.read"
GOOGLE_CALENDAR_EVENT_CREATE_TOOL = "google_calendar.events.create"
GOOGLE_CALENDAR_EVENT_UPDATE_TOOL = "google_calendar.events.update"
GOOGLE_CALENDAR_EVENT_DELETE_TOOL = "google_calendar.events.delete"
GOOGLE_CALENDAR_API_BASE_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
MAX_CALENDAR_RESPONSE_BYTES = 512 * 1024
MAX_EVENTS_PER_RESPONSE = 100
EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class GoogleCalendarProviderError(RuntimeError):
    """Raised when Google Calendar cannot safely complete an event operation."""


class GoogleCalendarEventNotFoundError(GoogleCalendarProviderError):
    """Raised when the requested Calendar event does not exist."""


class GoogleCalendarConflictError(GoogleCalendarProviderError):
    """Raised when a retry conflicts with a different provider-side event."""


class GoogleCalendarEvent(BaseModel):
    """Minimal Calendar event fields returned to the caller."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    summary: str | None = Field(default=None, max_length=500)
    start: str = Field(max_length=64)
    end: str = Field(max_length=64)
    timezone: str | None = Field(default=None, max_length=64)


class GoogleCalendarConnector:
    """Read or mutate the authenticated user's primary calendar only."""

    def __init__(self, access_token: str, client: httpx.AsyncClient) -> None:
        if not access_token or any(ord(char) < 33 or ord(char) > 126 for char in access_token):
            raise ValueError("Google Calendar access token is invalid.")
        self._access_token = access_token
        self._client = client

    async def __call__(self, action: ProposedAction) -> Any:
        if action.target_ref != "primary":
            raise GoogleCalendarProviderError("Only the primary calendar is supported.")
        handlers = {
            GOOGLE_CALENDAR_EVENT_READ_TOOL: self._list_events,
            GOOGLE_CALENDAR_EVENT_CREATE_TOOL: self._create_event,
            GOOGLE_CALENDAR_EVENT_UPDATE_TOOL: self._update_event,
            GOOGLE_CALENDAR_EVENT_DELETE_TOOL: self._delete_event,
        }
        handler = handlers.get(action.tool_name)
        if handler is None:
            raise GoogleCalendarProviderError("The Calendar action is not supported.")
        return await handler(action.arguments, action.idempotency_key)

    async def _list_events(
        self,
        arguments: dict[str, Any],
        _idempotency_key: str | None,
    ) -> tuple[GoogleCalendarEvent, ...]:
        time_min = _aware_datetime(arguments.get("time_min"))
        time_max = _aware_datetime(arguments.get("time_max"))
        timezone = _time_zone(arguments.get("time_zone"))
        limit = arguments.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= MAX_EVENTS_PER_RESPONSE:
            raise GoogleCalendarProviderError("The Calendar event limit is invalid.")
        if time_min >= time_max or time_max - time_min > timedelta(days=366):
            raise GoogleCalendarProviderError("The Calendar time range is invalid.")

        payload = await self._request_json(
            "GET",
            GOOGLE_CALENDAR_API_BASE_URL,
            params={
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "timeZone": timezone,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": str(limit),
            },
        )
        items = payload.get("items")
        if not isinstance(items, list) or len(items) > limit:
            raise GoogleCalendarProviderError("Google returned an invalid event list.")
        return tuple(_parse_event(item) for item in items)

    async def _create_event(
        self,
        arguments: dict[str, Any],
        idempotency_key: str | None,
    ) -> GoogleCalendarEvent:
        if not isinstance(idempotency_key, str) or not IDEMPOTENCY_PATTERN.fullmatch(
            idempotency_key
        ):
            raise GoogleCalendarProviderError("An event idempotency key is required.")
        summary = _summary(arguments.get("summary"))
        start = _aware_datetime(arguments.get("start"))
        end = _aware_datetime(arguments.get("end"))
        timezone = _time_zone(arguments.get("time_zone"))
        if end <= start or end - start > timedelta(days=366):
            raise GoogleCalendarProviderError("The Calendar event duration is invalid.")

        event_id = _provider_event_id(idempotency_key)
        event_body = {
            "id": event_id,
            "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        }
        try:
            payload = await self._request_json(
                "POST",
                GOOGLE_CALENDAR_API_BASE_URL,
                json_body=event_body,
            )
        except GoogleCalendarProviderError as exc:
            if "already exists" not in str(exc):
                raise
            payload = await self._request_json(
                "GET",
                f"{GOOGLE_CALENDAR_API_BASE_URL}/{quote(event_id, safe='')}",
            )
            existing = _parse_event(payload)
            if (
                existing.summary != summary
                or _aware_datetime(existing.start) != start
                or _aware_datetime(existing.end) != end
            ):
                raise GoogleCalendarConflictError(
                    "The idempotent Calendar event conflicts with an existing event."
                ) from None
            return existing
        return _parse_event(payload, expected_id=event_id)

    async def _update_event(
        self,
        arguments: dict[str, Any],
        _idempotency_key: str | None,
    ) -> GoogleCalendarEvent:
        event_id = _event_id(arguments.get("event_id"))
        event_body: dict[str, Any] = {}
        if "summary" in arguments:
            event_body["summary"] = _summary(arguments["summary"])
        if "start" in arguments or "end" in arguments:
            if "start" not in arguments or "end" not in arguments:
                raise GoogleCalendarProviderError(
                    "Both start and end are required when changing event times."
                )
            timezone = _time_zone(arguments.get("time_zone"))
            start = _aware_datetime(arguments["start"])
            end = _aware_datetime(arguments["end"])
            if end <= start or end - start > timedelta(days=366):
                raise GoogleCalendarProviderError("The Calendar event duration is invalid.")
            event_body["start"] = {"dateTime": start.isoformat(), "timeZone": timezone}
            event_body["end"] = {"dateTime": end.isoformat(), "timeZone": timezone}
        if not event_body:
            raise GoogleCalendarProviderError("At least one Calendar event field is required.")
        payload = await self._request_json(
            "PATCH",
            f"{GOOGLE_CALENDAR_API_BASE_URL}/{quote(event_id, safe='')}",
            json_body=event_body,
        )
        return _parse_event(payload, expected_id=event_id)

    async def _delete_event(
        self,
        arguments: dict[str, Any],
        _idempotency_key: str | None,
    ) -> dict[str, bool]:
        event_id = _event_id(arguments.get("event_id"))
        await self._request_no_content(
            "DELETE",
            f"{GOOGLE_CALENDAR_API_BASE_URL}/{quote(event_id, safe='')}",
        )
        return {"deleted": True}

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        body = await self._request_bytes(method, url, params=params, json_body=json_body)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise GoogleCalendarProviderError(
                "Google Calendar returned an invalid response."
            ) from None
        if not isinstance(payload, Mapping):
            raise GoogleCalendarProviderError("Google Calendar returned an invalid response.")
        return payload

    async def _request_no_content(self, method: str, url: str) -> None:
        try:
            async with self._client.stream(
                method,
                url,
                headers=self._headers(),
            ) as response:
                if response.status_code == 404 and method == "DELETE":
                    raise GoogleCalendarEventNotFoundError("The Calendar event was not found.")
                if response.status_code != 204:
                    raise GoogleCalendarProviderError(
                        "Google Calendar could not complete the event operation."
                    )
        except httpx.TimeoutException:
            raise GoogleCalendarProviderError("The Calendar request timed out.") from None
        except httpx.RequestError:
            raise GoogleCalendarProviderError("The Calendar request failed.") from None

    async def _request_bytes(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> bytes:
        try:
            async with self._client.stream(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
            ) as response:
                if response.status_code == 409:
                    raise GoogleCalendarConflictError("The Calendar event already exists.")
                if response.status_code == 404:
                    raise GoogleCalendarEventNotFoundError("The Calendar event was not found.")
                if response.status_code in {401, 403}:
                    raise GoogleCalendarProviderError(
                        "Google rejected the Calendar credentials or permission."
                    )
                if response.status_code not in {200, 201}:
                    raise GoogleCalendarProviderError(
                        "Google Calendar could not complete the event operation."
                    )
                chunks: list[bytes] = []
                total_bytes = 0
                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > MAX_CALENDAR_RESPONSE_BYTES:
                        raise GoogleCalendarProviderError(
                            "Google Calendar returned an oversized response."
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.TimeoutException:
            raise GoogleCalendarProviderError("The Calendar request timed out.") from None
        except httpx.RequestError:
            raise GoogleCalendarProviderError("The Calendar request failed.") from None

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": "Cortexstone",
        }


def _parse_event(payload: Any, *, expected_id: str | None = None) -> GoogleCalendarEvent:
    if not isinstance(payload, Mapping):
        raise GoogleCalendarProviderError("Google Calendar returned an invalid event.")
    event_id = payload.get("id")
    start_data = payload.get("start")
    end_data = payload.get("end")
    if not isinstance(event_id, str) or not EVENT_ID_PATTERN.fullmatch(event_id):
        raise GoogleCalendarProviderError("Google Calendar returned an invalid event ID.")
    if expected_id is not None and event_id != expected_id:
        raise GoogleCalendarProviderError("Google Calendar returned a mismatched event.")
    start = _event_time(start_data)
    end = _event_time(end_data)
    summary = payload.get("summary")
    if summary is not None and not isinstance(summary, str):
        raise GoogleCalendarProviderError("Google Calendar returned an invalid event title.")
    timezone = None
    if isinstance(start_data, Mapping) and isinstance(start_data.get("timeZone"), str):
        timezone = start_data["timeZone"]
    try:
        return GoogleCalendarEvent(
            id=event_id,
            summary=summary,
            start=start,
            end=end,
            timezone=timezone,
        )
    except ValueError:
        raise GoogleCalendarProviderError("Google Calendar returned an invalid event.") from None


def _event_time(value: Any) -> str:
    if not isinstance(value, Mapping):
        raise GoogleCalendarProviderError("Google Calendar returned an invalid event time.")
    time_value = value.get("dateTime", value.get("date"))
    if not isinstance(time_value, str) or not time_value:
        raise GoogleCalendarProviderError("Google Calendar returned an invalid event time.")
    return time_value


def _aware_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise GoogleCalendarProviderError("Calendar times must be ISO-8601 strings.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GoogleCalendarProviderError("Calendar times must be valid ISO-8601 values.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GoogleCalendarProviderError("Calendar times must include a UTC offset.")
    return parsed


def _time_zone(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 64:
        raise GoogleCalendarProviderError("A valid IANA time zone is required.")
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise GoogleCalendarProviderError("A valid IANA time zone is required.") from None
    return value


def _summary(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise GoogleCalendarProviderError("Event title must contain 1 to 500 characters.")
    return value.strip()


def _event_id(value: Any) -> str:
    if not isinstance(value, str) or not EVENT_ID_PATTERN.fullmatch(value):
        raise GoogleCalendarProviderError("The Calendar event ID is invalid.")
    return value


def _provider_event_id(idempotency_key: str) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).digest()
    return b32hexencode(digest).decode("ascii").lower().rstrip("=")
