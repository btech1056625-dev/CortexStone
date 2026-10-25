"""Tests for verified OIDC identities at the API boundary."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from cortexstone.api.auth import (
    AuthenticationProviderUnavailable,
    InvalidBearerToken,
    OIDCAuthenticator,
)
from cortexstone.api.config import Settings
from cortexstone.api.main import create_app

ISSUER = "https://identity.example.test/"
AUDIENCE = "cortexstone-api"
JWKS_URL = "https://identity.example.test/.well-known/jwks.json"


@pytest.fixture
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


class StubJwksClient:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, token: str):
        return SimpleNamespace(key=self.public_key)


def issue_token(private_key, **overrides: object) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "oidc|user-123",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_oidc_authenticator_returns_verified_subject(key_pair):
    private_key, public_key = key_pair
    authenticator = OIDCAuthenticator(
        ISSUER,
        AUDIENCE,
        JWKS_URL,
        jwks_client=StubJwksClient(public_key),
    )

    user = authenticator.authenticate(issue_token(private_key))

    assert user.subject == "oidc|user-123"


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.example.test/"},
        {"aud": "another-api"},
        {"sub": ""},
        {"exp": datetime.now(UTC) - timedelta(minutes=1)},
    ],
)
def test_oidc_authenticator_rejects_invalid_claims(key_pair, claims):
    private_key, public_key = key_pair
    authenticator = OIDCAuthenticator(
        ISSUER,
        AUDIENCE,
        JWKS_URL,
        jwks_client=StubJwksClient(public_key),
    )

    with pytest.raises(InvalidBearerToken):
        authenticator.authenticate(issue_token(private_key, **claims))


def test_oidc_authenticator_rejects_signature_from_another_key(key_pair):
    private_key, public_key = key_pair
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    authenticator = OIDCAuthenticator(
        ISSUER,
        AUDIENCE,
        JWKS_URL,
        jwks_client=StubJwksClient(public_key),
    )

    with pytest.raises(InvalidBearerToken):
        authenticator.authenticate(issue_token(other_private_key))


def test_oidc_authenticator_rejects_unapproved_algorithm(key_pair):
    _, public_key = key_pair
    authenticator = OIDCAuthenticator(
        ISSUER,
        AUDIENCE,
        JWKS_URL,
        jwks_client=StubJwksClient(public_key),
    )
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "oidc|user-123",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "untrusted-secret-long-enough-for-hmac",
        algorithm="HS256",
    )

    with pytest.raises(InvalidBearerToken):
        authenticator.authenticate(token)


def test_oidc_authenticator_reports_jwks_connection_failure(key_pair):
    class OfflineJwksClient:
        def get_signing_key_from_jwt(self, token: str):
            raise jwt.PyJWKClientConnectionError("offline")

    authenticator = OIDCAuthenticator(
        ISSUER,
        AUDIENCE,
        JWKS_URL,
        jwks_client=OfflineJwksClient(),
    )

    with pytest.raises(AuthenticationProviderUnavailable):
        authenticator.authenticate("token")


def test_oidc_authentication_protects_current_user_endpoint(key_pair):
    private_key, public_key = key_pair
    application = create_app(
        Settings(auth_issuer=ISSUER, auth_audience=AUDIENCE, auth_jwks_url=JWKS_URL)
    )
    application.state.authenticator = OIDCAuthenticator(
        ISSUER,
        AUDIENCE,
        JWKS_URL,
        jwks_client=StubJwksClient(public_key),
    )

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.get(
                "/api/v1/me",
                headers={"Authorization": f"Bearer {issue_token(private_key)}"},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == {
        "id": "oidc|user-123",
        "display_name": "oidc|user-123",
        "authenticated": True,
    }


def test_user_id_header_does_not_authenticate_request():
    application = create_app(
        Settings(auth_issuer=ISSUER, auth_audience=AUDIENCE, auth_jwks_url=JWKS_URL)
    )

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.get(
                "/api/v1/me",
                headers={"X-User-ID": "attacker-selected-user"},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/api/v1/me", None),
        ("GET", "/api/v1/memories", None),
        ("POST", "/api/v1/memories", {"content": "demo", "memory_type": "fact"}),
        ("GET", "/api/v1/memories/00000000-0000-0000-0000-000000000001", None),
        ("DELETE", "/api/v1/memories/00000000-0000-0000-0000-000000000001", None),
        (
            "POST",
            "/api/v1/actions/validate",
            {
                "action": {
                    "tool_name": "notes.search",
                    "target_ref": "notes/personal",
                    "arguments": {"query": "demo"},
                    "purpose": "Check demo authentication",
                }
            },
        ),
    ],
)
def test_protected_routes_fail_closed_when_oidc_is_unconfigured(method, path, payload):
    application = create_app(Settings())

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.request(
                method,
                path,
                json=payload,
                headers={"X-User-ID": "demo-user"},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_protected_route_fails_closed_when_oidc_keys_are_unavailable():
    class OfflineAuthenticator:
        def authenticate(self, token: str):
            raise AuthenticationProviderUnavailable

    application = create_app(Settings())
    application.state.authenticator = OfflineAuthenticator()

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.get(
                "/api/v1/me",
                headers={"Authorization": "Bearer present-but-unverifiable"},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_authentication_configuration_requires_all_values():
    with pytest.raises(ValueError, match="must be configured together"):
        Settings(auth_issuer=ISSUER)


def test_authentication_configuration_requires_https_urls():
    with pytest.raises(ValueError, match="must be an HTTPS URL"):
        Settings(
            auth_issuer="http://identity.example.test",
            auth_audience=AUDIENCE,
            auth_jwks_url=JWKS_URL,
        )
