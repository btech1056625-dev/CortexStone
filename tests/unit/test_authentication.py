"""Tests for verified OIDC identities at the API boundary."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient

from cortexstone.api.auth import (
    AuthenticatedUser,
    AuthenticationProviderUnavailable,
    InvalidBearerToken,
    OIDCAuthenticator,
    SessionTokenAuthenticator,
)
from cortexstone.api.config import Settings
from cortexstone.api.dependencies import get_chat_service, get_memory_service
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


def test_oidc_authenticator_refreshes_jwks_after_signing_key_rotation():
    class RotatingJwksHandler(BaseHTTPRequestHandler):
        jwks: dict[str, list[dict[str, str]]] = {"keys": []}

        def do_GET(self):
            payload = json.dumps(self.jwks).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    def public_jwk(public_key, kid: str) -> dict[str, str]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
        jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
        return jwk

    old_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    RotatingJwksHandler.jwks = {"keys": [public_jwk(old_private_key.public_key(), "old-key")]}
    server = ThreadingHTTPServer(("127.0.0.1", 0), RotatingJwksHandler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    jwks_url = f"http://127.0.0.1:{server.server_port}/jwks"
    authenticator = OIDCAuthenticator(
        ISSUER,
        AUDIENCE,
        jwks_url,
        jwks_client=PyJWKClient(jwks_url, cooldown_duration=0),
    )

    def token_for(private_key, kid: str, subject: str) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})

    try:
        old_user = authenticator.authenticate(token_for(old_private_key, "old-key", "old-user"))
        RotatingJwksHandler.jwks = {"keys": [public_jwk(new_private_key.public_key(), "new-key")]}
        new_user = authenticator.authenticate(token_for(new_private_key, "new-key", "new-user"))
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()

    assert old_user.subject == "old-user"
    assert new_user.subject == "new-user"


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


def test_oauth_session_token_authenticates_the_issued_principal():
    authenticator = SessionTokenAuthenticator("a" * 32)
    user = AuthenticatedUser(subject="google:account-1", display_name="Calendar User")

    token = authenticator.issue(user)

    assert token.startswith("cs1.")
    assert authenticator.authenticate(token) == user


def test_oauth_session_token_rejects_another_signing_key():
    token = SessionTokenAuthenticator("a" * 32).issue(
        AuthenticatedUser(subject="github:account-1", display_name="GitHub User")
    )

    with pytest.raises(InvalidBearerToken):
        SessionTokenAuthenticator("b" * 32).authenticate(token)


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


def test_oidc_bearer_acceptance_protects_memory_list_endpoint(key_pair):
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
    memory_service = AsyncMock()
    memory_service.list_memories.return_value = []
    memory_service.count_memories.return_value = 0
    application.dependency_overrides[get_memory_service] = lambda: memory_service

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.get(
                "/api/v1/memories",
                headers={"Authorization": f"Bearer {issue_token(private_key)}"},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}
    memory_service.list_memories.assert_awaited_once()
    memory_service.count_memories.assert_awaited_once()
    assert memory_service.list_memories.await_args.kwargs["owner_id"] == "oidc|user-123"
    assert memory_service.count_memories.await_args.kwargs["owner_id"] == "oidc|user-123"


def test_oidc_bearer_acceptance_protects_chat_endpoint(key_pair):
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
    chat_service = AsyncMock()
    chat_service.respond.return_value = SimpleNamespace(
        model_dump=lambda: {
            "conversation_id": "conversation-1",
            "answer": "Authenticated chat response.",
            "proposed_actions": [],
        }
    )
    application.dependency_overrides[get_chat_service] = lambda: chat_service

    async def send_request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/v1/chat",
                headers={"Authorization": f"Bearer {issue_token(private_key)}"},
                json={
                    "message": "Hello",
                    "conversation_id": "conversation-1",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": "conversation-1",
        "answer": "Authenticated chat response.",
        "proposed_actions": [],
    }
    chat_service.respond.assert_awaited_once()
    assert chat_service.respond.await_args.kwargs["principal"].principal_id == "oidc|user-123"


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
        ("POST", "/api/v1/chat", {"message": "demo"}),
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
