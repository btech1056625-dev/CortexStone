"""Tests for OAuth state, PKCE, and dashboard-origin boundaries."""

import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet

from cortexstone.api.auth import SessionTokenAuthenticator
from cortexstone.api.config import Settings
from cortexstone.security.oauth import OAuthFlowError, OAuthService

DASHBOARD_ORIGIN = "https://dashboard.example.test"


class FakeSession:
    def __init__(self) -> None:
        self.flow = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False

    def begin(self):
        return self

    async def execute(self, _statement):
        return None

    def add(self, flow) -> None:
        self.flow = flow

    async def scalar(self, _statement):
        return self.flow

    async def delete(self, flow) -> None:
        if self.flow is flow:
            self.flow = None


def make_oauth_service():
    settings = Settings(
        google_oauth_client_id="google-client",
        google_oauth_client_secret="google-secret",
        oauth_public_api_base_url="https://api.example.test",
        oauth_dashboard_origins=(DASHBOARD_ORIGIN,),
        oauth_session_signing_key="s" * 32,
        oauth_token_encryption_key=Fernet.generate_key().decode("ascii"),
    )
    session = FakeSession()
    client = httpx.AsyncClient()
    service = OAuthService(
        settings,
        lambda: session,
        client,
        SessionTokenAuthenticator("s" * 32),
        google_identity_verifier=lambda _token, _nonce: ("google-user", "Google User"),
    )
    return service, session, client


def test_authorization_url_uses_pkce_nonce_and_exact_callback_origin():
    async def exercise():
        service, session, client = make_oauth_service()
        try:
            url = await service.create_authorization_url(
                "google",
                mode="login",
                return_origin=DASHBOARD_ORIGIN,
            )
            return url, session.flow
        finally:
            await client.aclose()

    url, flow = asyncio.run(exercise())
    parsed = urlparse(url)
    parameters = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parameters["code_challenge_method"] == ["S256"]
    assert parameters["code_challenge"][0]
    assert parameters["nonce"] == [flow.nonce]
    assert parameters["redirect_uri"] == ["https://api.example.test/api/v1/oauth/google/callback"]
    assert flow.return_origin == DASHBOARD_ORIGIN
    assert flow.principal_id is None
    assert len(flow.state_hash) == 64
    assert flow.state_hash != parameters["state"][0]
    assert flow.encrypted_code_verifier != ""
    assert "calendar.events.owned" in parameters["scope"][0]


def test_oauth_state_is_single_use_and_rejects_unallowlisted_return_origin():
    async def exercise():
        service, session, client = make_oauth_service()
        try:
            with pytest.raises(OAuthFlowError, match="origin"):
                await service.create_authorization_url(
                    "google",
                    mode="login",
                    return_origin="https://attacker.example.test",
                )
            url = await service.create_authorization_url(
                "google",
                mode="login",
                return_origin=DASHBOARD_ORIGIN,
            )
            state = parse_qs(urlparse(url).query)["state"][0]
            assert session.flow is not None
            assert await service.cancel_flow("google", state) == DASHBOARD_ORIGIN
            with pytest.raises(OAuthFlowError, match="state"):
                await service.cancel_flow("google", state)
        finally:
            await client.aclose()

    asyncio.run(exercise())
