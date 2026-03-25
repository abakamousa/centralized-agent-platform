import os
from functools import lru_cache
from typing import Any

import httpx
import jwt
from fastapi import HTTPException
from jwt import PyJWKClient

from auth.context import RequestIdentity


class Auth0TokenValidator:
    def __init__(self, auth0_config: dict[str, Any] | None = None) -> None:
        config = auth0_config or {}
        self.issuer = str(config.get("issuer") or os.getenv("AUTH0_ISSUER", "")).rstrip("/")
        self.audience = str(config.get("audience") or os.getenv("AUTH0_AUDIENCE", ""))

    def validate(
        self, authorization: str, session_id: str | None = None
    ) -> RequestIdentity:
        if not self.issuer or not self.audience:
            raise HTTPException(
                status_code=500,
                detail="AUTH0_ISSUER and AUTH0_AUDIENCE must be configured",
            )

        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Invalid Authorization header")

        try:
            signing_key = self._get_jwk_client(self.issuer).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid Auth0 access token") from exc

        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience] if audience else []

        return RequestIdentity(
            authorization=authorization,
            user_id=str(claims.get("sub", "unknown-user")),
            session_id=self._resolve_session_id(claims, session_id),
            issuer=str(claims.get("iss", self.issuer)),
            audience=[str(item) for item in audiences],
            subject=str(claims.get("sub", "unknown-subject")),
            entra_tenant_id=self._extract_entra_tenant_id(claims),
            claims=claims,
        )

    @staticmethod
    @lru_cache(maxsize=8)
    def _get_jwk_client(issuer: str) -> PyJWKClient:
        openid_config_url = f"{issuer}/.well-known/openid-configuration"
        with httpx.Client(timeout=10.0) as client:
            response = client.get(openid_config_url)
            response.raise_for_status()
            jwks_uri = response.json()["jwks_uri"]
        return PyJWKClient(jwks_uri)

    @staticmethod
    def _extract_entra_tenant_id(claims: dict[str, Any]) -> str | None:
        candidate_keys = ("tid", "tenant_id", "http://schemas.microsoft.com/identity/claims/tenantid")
        for key in candidate_keys:
            value = claims.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _resolve_session_id(
        claims: dict[str, Any], session_id: str | None
    ) -> str:
        if session_id:
            return session_id

        candidate_keys = ("sid", "session_id")
        for key in candidate_keys:
            value = claims.get(key)
            if value:
                return str(value)

        return str(claims.get("sub", "unknown-session"))
