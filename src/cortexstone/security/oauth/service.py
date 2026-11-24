"""Secure OAuth authorization-code flows and per-principal provider credentials."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from jwt import PyJWKClient, PyJWKClientError, PyJWTError, decode
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cortexstone.api.auth import AuthenticatedUser, SessionTokenAuthenticator
from cortexstone.api.config import Settings
from cortexstone.db.models.oauth import (
    OAuthCredentialModel,
    OAuthFlowModel,
    OAuthIdentityModel,
)

OAuthProvider = Literal["google", "github"]
OAuthMode = Literal["login", "connect"]
OAUTH_FLOW_TTL = timedelta(minutes=10)
TOKEN_REFRESH_SKEW = timedelta(minutes=1)
MAX_PROVIDER_RESPONSE_BYTES = 1024 * 1024
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
GOOGLE_OIDC_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


class OAuthFlowError(RuntimeError):
    """Raised when an OAuth authorization flow is invalid, expired, or conflicting."""


class OAuthProviderError(RuntimeError):
    """Raised when a configured OAuth provider cannot complete a safe operation."""


class OAuthCallbackError(OAuthProviderError):
    """OAuth callback failure carrying its already-validated browser return origin."""

    def __init__(self, return_origin: str) -> None:
        self.return_origin = return_origin
        super().__init__("The OAuth callback could not be completed.")


@dataclass(frozen=True)
class OAuthConnection:
    """Non-secret provider connection information returned to the user."""

    provider: OAuthProvider
    connected: bool
    display_name: str | None
    scopes: tuple[str, ...]
    expires_at: datetime | None


@dataclass(frozen=True)
class OAuthCompletion:
    """Result of a successful provider callback."""

    provider: OAuthProvider
    user: AuthenticatedUser
    mode: OAuthMode
    session_token: str | None


@dataclass(frozen=True)
class _ProviderConfig:
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class _OAuthFlow:
    provider: OAuthProvider
    mode: OAuthMode
    principal_id: str | None
    return_origin: str
    encrypted_code_verifier: str
    nonce: str | None
    expires_at: datetime


class OAuthService:
    """Create one-use OAuth flows and retain provider tokens encrypted at rest."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        http_client: httpx.AsyncClient,
        session_authenticator: SessionTokenAuthenticator,
        *,
        google_identity_verifier: Callable[[str, str], tuple[str, str]] | None = None,
    ) -> None:
        if settings.oauth_token_encryption_key is None:
            raise ValueError("OAuth token encryption is not configured.")
        if settings.oauth_public_api_base_url is None:
            raise ValueError("OAuth public API URL is not configured.")
        self._settings = settings
        self._session_factory = session_factory
        self._http_client = http_client
        self._session_authenticator = session_authenticator
        self._cipher = Fernet(settings.oauth_token_encryption_key.encode("ascii"))
        self._google_identity_verifier = (
            google_identity_verifier or self._verify_google_identity_token
        )
        self._google_jwks = PyJWKClient("https://www.googleapis.com/oauth2/v3/certs", timeout=5)

    def configured_providers(self) -> tuple[OAuthProvider, ...]:
        providers: list[OAuthProvider] = []
        if self._google_config is not None:
            providers.append("google")
        if self._github_config is not None:
            providers.append("github")
        return tuple(providers)

    async def create_authorization_url(
        self,
        provider: OAuthProvider,
        *,
        mode: OAuthMode,
        return_origin: str,
        principal_id: str | None = None,
    ) -> str:
        config = self._provider_config(provider)
        if return_origin not in self._settings.oauth_dashboard_origins:
            raise OAuthFlowError("The dashboard origin is not allowed.")
        if mode == "connect" and (principal_id is None or not principal_id.strip()):
            raise OAuthFlowError("Connecting an account requires an authenticated principal.")
        if mode == "login" and principal_id is not None:
            raise OAuthFlowError("Login flows cannot be bound to an existing principal.")

        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
        nonce = secrets.token_urlsafe(32) if provider == "google" else None
        expires_at = datetime.now(UTC) + OAUTH_FLOW_TTL
        flow = OAuthFlowModel(
            state_hash=_hash_state(state),
            provider=provider,
            mode=mode,
            principal_id=principal_id,
            return_origin=return_origin,
            encrypted_code_verifier=self._encrypt(verifier),
            nonce=nonce,
            expires_at=expires_at,
        )
        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(OAuthFlowModel).where(OAuthFlowModel.expires_at <= datetime.now(UTC))
            )
            session.add(flow)

        callback_url = self._callback_url(provider)
        if provider == "google":
            parameters = {
                "client_id": config.client_id,
                "redirect_uri": callback_url,
                "response_type": "code",
                "scope": f"openid email profile {GOOGLE_CALENDAR_SCOPE}",
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
            return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(parameters)

        parameters = {
            "client_id": config.client_id,
            "redirect_uri": callback_url,
            "state": state,
            "allow_signup": "false",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return "https://github.com/login/oauth/authorize?" + urlencode(parameters)

    async def cancel_flow(self, provider: OAuthProvider, state: str) -> str:
        flow = await self._consume_flow(provider, state)
        return flow.return_origin

    async def complete_callback(
        self,
        provider: OAuthProvider,
        *,
        code: str,
        state: str,
    ) -> tuple[OAuthCompletion, str]:
        if not code or len(code) > 4096:
            raise OAuthFlowError("The OAuth authorization code is invalid.")
        flow = await self._consume_flow(provider, state)
        try:
            return await self._complete_consumed_flow(provider, code, flow)
        except (OAuthFlowError, OAuthProviderError):
            raise OAuthCallbackError(flow.return_origin) from None

    async def _complete_consumed_flow(
        self,
        provider: OAuthProvider,
        code: str,
        flow: _OAuthFlow,
    ) -> tuple[OAuthCompletion, str]:
        verifier = self._decrypt(flow.encrypted_code_verifier)
        token_data = await self._exchange_code(provider, code, verifier)

        if provider == "google":
            subject, display_name = await asyncio.to_thread(
                self._google_identity_verifier,
                _required_string(token_data, "id_token"),
                flow.nonce or "",
            )
        else:
            subject, display_name = await self._github_identity(token_data)

        access_token = _required_string(token_data, "access_token")
        refresh_token = _optional_string(token_data.get("refresh_token"))
        expires_in = token_data.get("expires_in")
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=expires_in)
            if isinstance(expires_in, int) and not isinstance(expires_in, bool) and expires_in > 0
            else None
        )
        scopes = _scopes(token_data.get("scope"))

        if provider == "google" and GOOGLE_CALENDAR_SCOPE not in scopes:
            raise OAuthProviderError("Google did not grant the required Calendar event scope.")

        try:
            user = await self._persist_identity_and_credentials(
                provider=provider,
                provider_subject=subject,
                display_name=display_name,
                mode=flow.mode,
                principal_id=flow.principal_id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                scopes=scopes,
            )
        except IntegrityError:
            raise OAuthFlowError(
                "That provider account is already linked to another Cortexstone account."
            ) from None

        session_token = self._session_authenticator.issue(user) if flow.mode == "login" else None
        return OAuthCompletion(provider, user, flow.mode, session_token), flow.return_origin

    async def get_access_token(
        self,
        principal_id: str,
        provider: OAuthProvider,
        *,
        required_scope: str | None = None,
    ) -> str:
        async with self._session_factory() as session:
            credential = await session.scalar(
                select(OAuthCredentialModel).where(
                    OAuthCredentialModel.principal_id == principal_id,
                    OAuthCredentialModel.provider == provider,
                )
            )
        if credential is None:
            raise OAuthFlowError(f"No {provider} account is connected.")
        if required_scope is not None and required_scope not in credential.scopes:
            raise OAuthFlowError(
                f"The connected {provider} account has not granted the required permission."
            )

        should_refresh = (
            credential.expires_at is not None
            and credential.expires_at <= datetime.now(UTC) + TOKEN_REFRESH_SKEW
        )
        if not should_refresh:
            return self._decrypt(credential.encrypted_access_token)
        if credential.encrypted_refresh_token is None:
            raise OAuthFlowError(f"The {provider} connection must be reauthorized.")

        refresh_token = self._decrypt(credential.encrypted_refresh_token)
        refreshed = await self._refresh_access_token(provider, refresh_token)
        access_token = _required_string(refreshed, "access_token")
        expires_in = refreshed.get("expires_in")
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=expires_in)
            if isinstance(expires_in, int) and not isinstance(expires_in, bool) and expires_in > 0
            else None
        )
        new_refresh_token = _optional_string(refreshed.get("refresh_token")) or refresh_token
        new_scopes = _scopes(refreshed.get("scope")) or tuple(credential.scopes)
        if required_scope is not None and required_scope not in new_scopes:
            raise OAuthFlowError(
                f"The refreshed {provider} account has not granted the required permission."
            )
        async with self._session_factory() as session, session.begin():
            current = await session.scalar(
                select(OAuthCredentialModel)
                .where(OAuthCredentialModel.id == credential.id)
                .with_for_update()
            )
            if current is None:
                raise OAuthFlowError(f"The {provider} connection was removed.")
            current.encrypted_access_token = self._encrypt(access_token)
            current.encrypted_refresh_token = self._encrypt(new_refresh_token)
            current.expires_at = expires_at
            current.scopes = list(new_scopes)
        return access_token

    async def list_connections(self, principal_id: str) -> tuple[OAuthConnection, ...]:
        async with self._session_factory() as session:
            identities = await session.scalars(
                select(OAuthIdentityModel).where(OAuthIdentityModel.principal_id == principal_id)
            )
            credentials = await session.scalars(
                select(OAuthCredentialModel).where(
                    OAuthCredentialModel.principal_id == principal_id
                )
            )
        identity_by_provider = {item.provider: item for item in identities}
        credential_by_provider = {item.provider: item for item in credentials}
        return tuple(
            OAuthConnection(
                provider=provider,
                connected=provider in credential_by_provider,
                display_name=(
                    identity_by_provider[provider].display_name
                    if provider in identity_by_provider
                    else None
                ),
                scopes=tuple(credential_by_provider[provider].scopes)
                if provider in credential_by_provider
                else (),
                expires_at=credential_by_provider[provider].expires_at
                if provider in credential_by_provider
                else None,
            )
            for provider in self.configured_providers()
        )

    async def disconnect(self, principal_id: str, provider: OAuthProvider) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                delete(OAuthCredentialModel).where(
                    OAuthCredentialModel.principal_id == principal_id,
                    OAuthCredentialModel.provider == provider,
                )
            )
            return result.rowcount == 1

    async def _consume_flow(self, provider: OAuthProvider, state: str) -> _OAuthFlow:
        if not state or len(state) > 256:
            raise OAuthFlowError("The OAuth state is invalid or expired.")
        async with self._session_factory() as session, session.begin():
            flow = await session.scalar(
                select(OAuthFlowModel)
                .where(OAuthFlowModel.state_hash == _hash_state(state))
                .with_for_update()
            )
            if flow is None or flow.provider != provider:
                raise OAuthFlowError("The OAuth state is invalid or expired.")
            if flow.expires_at <= datetime.now(UTC):
                await session.delete(flow)
                raise OAuthFlowError("The OAuth state is invalid or expired.")
            if flow.mode not in {"login", "connect"}:
                await session.delete(flow)
                raise OAuthFlowError("The OAuth state is invalid or expired.")
            consumed = _OAuthFlow(
                provider=provider,
                mode=flow.mode,
                principal_id=flow.principal_id,
                return_origin=flow.return_origin,
                encrypted_code_verifier=flow.encrypted_code_verifier,
                nonce=flow.nonce,
                expires_at=flow.expires_at,
            )
            await session.delete(flow)
            return consumed

    async def _exchange_code(
        self,
        provider: OAuthProvider,
        code: str,
        verifier: str,
    ) -> Mapping[str, Any]:
        config = self._provider_config(provider)
        callback_url = self._callback_url(provider)
        if provider == "google":
            url = "https://oauth2.googleapis.com/token"
            body = {
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": callback_url,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            }
            headers = {"Accept": "application/json"}
        else:
            url = "https://github.com/login/oauth/access_token"
            body = {
                "code": code,
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "redirect_uri": callback_url,
                "code_verifier": verifier,
            }
            headers = {
                "Accept": "application/json",
                "User-Agent": "Cortexstone",
            }
        return await self._request_json("POST", url, headers=headers, data=body)

    async def _github_identity(
        self,
        token_data: Mapping[str, Any],
    ) -> tuple[str, str]:
        access_token = _required_string(token_data, "access_token")
        profile = await self._request_json(
            "GET",
            "https://api.github.com/user",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "Cortexstone",
            },
        )
        subject = profile.get("id")
        if not isinstance(subject, int) or isinstance(subject, bool) or subject <= 0:
            raise OAuthProviderError("GitHub returned an invalid account identity.")
        login = profile.get("login")
        name = profile.get("name")
        display_name = name if isinstance(name, str) and name.strip() else login
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = f"GitHub user {subject}"
        return str(subject), display_name.strip()[:200]

    def _verify_google_identity_token(self, token: str, nonce: str) -> tuple[str, str]:
        try:
            signing_key = self._google_jwks.get_signing_key_from_jwt(token)
            claims = decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._provider_config("google").client_id,
                issuer=tuple(GOOGLE_OIDC_ISSUERS),
                options={"require": ["exp", "sub", "nonce"]},
            )
        except (PyJWTError, PyJWKClientError) as exc:
            raise OAuthProviderError("Google returned an invalid identity token.") from exc
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip() or claims.get("nonce") != nonce:
            raise OAuthProviderError("Google returned an invalid identity token.")
        display_name = claims.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = claims.get("email")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = subject
        return subject, display_name.strip()[:200]

    async def _refresh_access_token(
        self,
        provider: OAuthProvider,
        refresh_token: str,
    ) -> Mapping[str, Any]:
        config = self._provider_config(provider)
        if provider == "google":
            url = "https://oauth2.googleapis.com/token"
        else:
            url = "https://github.com/login/oauth/access_token"
        return await self._request_json(
            "POST",
            url,
            headers={"Accept": "application/json", "User-Agent": "Cortexstone"},
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

    async def _persist_identity_and_credentials(
        self,
        *,
        provider: OAuthProvider,
        provider_subject: str,
        display_name: str,
        mode: OAuthMode,
        principal_id: str | None,
        access_token: str,
        refresh_token: str | None,
        expires_at: datetime | None,
        scopes: tuple[str, ...],
    ) -> AuthenticatedUser:
        async with self._session_factory() as session, session.begin():
            identity = await session.scalar(
                select(OAuthIdentityModel)
                .where(
                    OAuthIdentityModel.provider == provider,
                    OAuthIdentityModel.provider_subject == provider_subject,
                )
                .with_for_update()
            )
            if mode == "login":
                resolved_principal = (
                    identity.principal_id
                    if identity is not None
                    else f"{provider}:{provider_subject}"
                )
            else:
                if principal_id is None:
                    raise OAuthFlowError("The OAuth connect flow has no principal.")
                resolved_principal = principal_id
                if identity is not None and identity.principal_id != resolved_principal:
                    raise OAuthFlowError(
                        "That provider account is already linked to another Cortexstone account."
                    )

            if identity is None:
                session.add(
                    OAuthIdentityModel(
                        provider=provider,
                        provider_subject=provider_subject,
                        principal_id=resolved_principal,
                        display_name=display_name,
                    )
                )
            else:
                identity.display_name = display_name

            credential = await session.scalar(
                select(OAuthCredentialModel)
                .where(
                    OAuthCredentialModel.principal_id == resolved_principal,
                    OAuthCredentialModel.provider == provider,
                )
                .with_for_update()
            )
            if credential is not None and credential.provider_subject != provider_subject:
                raise OAuthFlowError("A different account for this provider is already connected.")
            encrypted_refresh = self._encrypt(refresh_token) if refresh_token is not None else None
            if credential is None:
                session.add(
                    OAuthCredentialModel(
                        provider=provider,
                        provider_subject=provider_subject,
                        principal_id=resolved_principal,
                        encrypted_access_token=self._encrypt(access_token),
                        encrypted_refresh_token=encrypted_refresh,
                        expires_at=expires_at,
                        scopes=list(scopes),
                    )
                )
            else:
                credential.encrypted_access_token = self._encrypt(access_token)
                if encrypted_refresh is not None:
                    credential.encrypted_refresh_token = encrypted_refresh
                credential.expires_at = expires_at
                credential.scopes = list(scopes)
            return AuthenticatedUser(
                subject=resolved_principal,
                display_name=display_name,
            )

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        data: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        try:
            async with self._http_client.stream(
                method,
                url,
                headers=dict(headers),
                data=data,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise OAuthProviderError("The OAuth provider rejected the request.")
                chunks: list[bytes] = []
                total_bytes = 0
                async for chunk in response.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > MAX_PROVIDER_RESPONSE_BYTES:
                        raise OAuthProviderError("The OAuth provider response was oversized.")
                    chunks.append(chunk)
        except httpx.TimeoutException:
            raise OAuthProviderError("The OAuth provider request timed out.") from None
        except httpx.RequestError:
            raise OAuthProviderError("The OAuth provider request failed.") from None
        try:
            payload = json.loads(b"".join(chunks))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise OAuthProviderError("The OAuth provider returned an invalid response.") from None
        if not isinstance(payload, Mapping):
            raise OAuthProviderError("The OAuth provider returned an invalid response.")
        if "error" in payload:
            raise OAuthProviderError("The OAuth provider rejected the request.")
        return payload

    def _provider_config(self, provider: OAuthProvider) -> _ProviderConfig:
        if provider == "google" and self._google_config is not None:
            return self._google_config
        if provider == "github" and self._github_config is not None:
            return self._github_config
        raise OAuthFlowError(f"The {provider} OAuth provider is not configured.")

    @property
    def _google_config(self) -> _ProviderConfig | None:
        if self._settings.google_oauth_client_id and self._settings.google_oauth_client_secret:
            return _ProviderConfig(
                self._settings.google_oauth_client_id,
                self._settings.google_oauth_client_secret,
            )
        return None

    @property
    def _github_config(self) -> _ProviderConfig | None:
        if self._settings.github_app_client_id and self._settings.github_app_client_secret:
            return _ProviderConfig(
                self._settings.github_app_client_id,
                self._settings.github_app_client_secret,
            )
        return None

    def _callback_url(self, provider: OAuthProvider) -> str:
        assert self._settings.oauth_public_api_base_url is not None
        return (
            f"{self._settings.oauth_public_api_base_url.rstrip('/')}"
            f"/api/v1/oauth/{provider}/callback"
        )

    def _encrypt(self, value: str) -> str:
        return self._cipher.encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str) -> str:
        try:
            return self._cipher.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError):
            raise OAuthProviderError(
                "Stored provider credentials could not be decrypted."
            ) from None


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise OAuthProviderError("The OAuth provider returned an invalid token response.")
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _scopes(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(sorted(set(scope for scope in value.split() if scope)))
    if isinstance(value, list) and all(isinstance(scope, str) for scope in value):
        return tuple(sorted(set(scope for scope in value if scope)))
    return ()
