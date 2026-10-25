"""OIDC bearer-token verification and authenticated user identity."""

from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWKClientError, PyJWTError, decode
from pydantic import BaseModel, ConfigDict


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
