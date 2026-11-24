"""Provider sign-in, OAuth account linking, and connection status endpoints."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse

from cortexstone.api.auth import AuthenticatedUser
from cortexstone.api.dependencies import get_authenticated_user, get_oauth_service
from cortexstone.security.oauth import (
    OAuthCallbackError,
    OAuthFlowError,
    OAuthProvider,
    OAuthProviderError,
    OAuthService,
)

router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/providers")
async def list_oauth_providers(
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service)],
) -> dict[str, list[str]]:
    """Return configured OAuth sign-in and account-linking providers."""
    return {"providers": list(oauth_service.configured_providers())}


@router.get("/{provider}/login")
async def start_login(
    provider: OAuthProvider,
    return_origin: Annotated[str, Query(min_length=1, max_length=300)],
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service)],
) -> RedirectResponse:
    """Start an OAuth login in a browser popup."""
    try:
        authorization_url = await oauth_service.create_authorization_url(
            provider,
            mode="login",
            return_origin=return_origin,
        )
    except OAuthFlowError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The OAuth sign-in request could not be started.",
        ) from None
    return RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{provider}/connect")
async def start_connection(
    provider: OAuthProvider,
    return_origin: Annotated[str, Query(min_length=1, max_length=300)],
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service)],
) -> dict[str, str]:
    """Create an authorization URL to link another provider to the signed-in user."""
    try:
        authorization_url = await oauth_service.create_authorization_url(
            provider,
            mode="connect",
            return_origin=return_origin,
            principal_id=user.subject,
        )
    except OAuthFlowError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The OAuth connection request could not be started.",
        ) from None
    return {"authorization_url": authorization_url}


@router.get("/connections")
async def list_connections(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service)],
) -> dict[str, list[dict[str, object]]]:
    """List only the caller's linked providers and non-secret connection metadata."""
    connections = await oauth_service.list_connections(user.subject)
    return {
        "connections": [
            {
                "provider": connection.provider,
                "connected": connection.connected,
                "display_name": connection.display_name,
                "scopes": list(connection.scopes),
                "expires_at": (
                    connection.expires_at.isoformat() if connection.expires_at is not None else None
                ),
            }
            for connection in connections
        ]
    }


@router.delete("/connections/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_provider(
    provider: OAuthProvider,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service)],
) -> None:
    """Remove the caller's encrypted connector credential without deleting sign-in identity."""
    removed = await oauth_service.disconnect(user.subject, provider)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider connection not found.",
        )


@router.get("/{provider}/callback", response_class=HTMLResponse)
async def oauth_callback(
    provider: OAuthProvider,
    oauth_service: Annotated[OAuthService, Depends(get_oauth_service)],
    code: str | None = Query(default=None, max_length=4096),
    state: str | None = Query(default=None, max_length=256),
    error: str | None = Query(default=None, max_length=128),
) -> HTMLResponse:
    """Complete a provider callback and message the result to the verified opener origin."""
    if state is None:
        return _popup_response(None, {"type": "cortexstone-oauth-error"})
    try:
        if error is not None:
            return_origin = await oauth_service.cancel_flow(provider, state)
            return _popup_response(
                return_origin,
                {"type": "cortexstone-oauth-error", "provider": provider},
            )
        if code is None:
            raise OAuthFlowError("The OAuth provider did not return an authorization code.")
        completion, return_origin = await oauth_service.complete_callback(
            provider,
            code=code,
            state=state,
        )
    except OAuthFlowError:
        return _popup_response(None, {"type": "cortexstone-oauth-error"})
    except OAuthCallbackError as exc:
        return _popup_response(
            exc.return_origin,
            {"type": "cortexstone-oauth-error", "provider": provider},
        )
    except OAuthProviderError:
        return _popup_response(None, {"type": "cortexstone-oauth-error"})

    message: dict[str, str] = {
        "type": "cortexstone-oauth-success",
        "provider": completion.provider,
        "mode": completion.mode,
        "principal_id": completion.user.subject,
        "display_name": completion.user.display_name,
    }
    if completion.session_token is not None:
        message["session_token"] = completion.session_token
    return _popup_response(return_origin, message)


def _popup_response(origin: str | None, message: dict[str, str]) -> HTMLResponse:
    if origin is None:
        return HTMLResponse(
            "<!doctype html><title>Sign-in failed</title>"
            "<p>OAuth could not be completed. You can close this window.</p>",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    safe_origin = json.dumps(origin).replace("<", "\\u003c")
    safe_message = json.dumps(message).replace("<", "\\u003c")
    html = (
        '<!doctype html><meta charset="utf-8"><title>OAuth complete</title>'
        "<p>You can close this window.</p><script>"
        f"if(window.opener)window.opener.postMessage({safe_message},{safe_origin});"
        "window.close();</script>"
    )
    return HTMLResponse(html)
