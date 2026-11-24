"""OIDC bearer-token verification and authenticated user identity."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from jwt import (
    PyJWKClient,
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWTError,
    decode,
    encode,
)
from pydantic import BaseModel, ConfigDict

SESSION_TOKEN_PREFIX = "cs1."
SESSION_TOKEN_ISSUER = "cortexstone"
SESSION_TOKEN_AUDIENCE = "cortexstone-api"
SESSION_TOKEN_TTL = timedelta(hours=1)


class AuthenticatedUser(BaseModel):
    """User identity derived from a verified access-token subject."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str
    display_name: str


class InvalidBearerToken(Exception):
    """Raised when a bearer token is invalid or does not identify a user."""


class AuthenticationProviderUnavailable(Exception):
    """Raised when the configured OIDC signing keys cannot be reached."""


class OIDCAuthenticator:
    """Verify RS256 access tokens against a configured OIDC JWKS endpoint."""

    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_url: str,
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks_client = jwks_client or PyJWKClient(jwks_url, timeout=5)

    def authenticate(self, token: str) -> AuthenticatedUser:
        """Verify token signature and required OIDC claims, returning its subject."""
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        except PyJWKClientConnectionError as exc:
            raise AuthenticationProviderUnavailable from exc
        except PyJWKClientError as exc:
            raise InvalidBearerToken from exc

        try:
            claims = decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "sub"]},
            )
        except PyJWTError as exc:
            raise InvalidBearerToken from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise InvalidBearerToken
        display_name = claims.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = subject
        return AuthenticatedUser(subject=subject, display_name=display_name)


class SessionTokenAuthenticator:
    """Issue and verify short-lived API sessions created by a completed OAuth login."""

    def __init__(self, signing_key: str) -> None:
        self._signing_key = signing_key

    def issue(self, user: AuthenticatedUser) -> str:
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "iss": SESSION_TOKEN_ISSUER,
            "aud": SESSION_TOKEN_AUDIENCE,
            "sub": user.subject,
            "name": user.display_name,
            "iat": now,
            "exp": now + SESSION_TOKEN_TTL,
            "jti": uuid4().hex,
        }
        return SESSION_TOKEN_PREFIX + encode(claims, self._signing_key, algorithm="HS256")

    def authenticate(self, token: str) -> AuthenticatedUser:
        if not token.startswith(SESSION_TOKEN_PREFIX):
            raise InvalidBearerToken
        try:
            claims = decode(
                token[len(SESSION_TOKEN_PREFIX) :],
                self._signing_key,
                algorithms=["HS256"],
                audience=SESSION_TOKEN_AUDIENCE,
                issuer=SESSION_TOKEN_ISSUER,
                options={"require": ["exp", "iat", "sub"]},
            )
        except PyJWTError as exc:
            raise InvalidBearerToken from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise InvalidBearerToken
        display_name = claims.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = subject
        return AuthenticatedUser(subject=subject, display_name=display_name)
