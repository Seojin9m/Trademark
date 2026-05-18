"""Supabase JWT verification for FastAPI.

Every request that hits a per-user endpoint should depend on ``get_current_user``.
The frontend obtains a JWT by calling Supabase Auth (signUp / signInWithPassword
/ verifyOtp) and then sends ``Authorization: Bearer <token>`` on every API call.
We verify the signature, expiry, and audience, then expose a lightweight
``AuthUser`` dataclass to the route function.

Supabase now signs JWTs with an **asymmetric ECC P-256 key (ES256)**. We verify
locally against the project's JWKS (JSON Web Key Set), which is a small public
document fetched once and cached by pyjwt's ``PyJWKClient``. No shared secret
or per-request network call is needed in steady state.

``service_role`` tokens (admin-only) are explicitly rejected: those shouldn't
arrive over an authenticated user route.

Required env var:
    SUPABASE_URL    e.g. https://abcdefgh.supabase.co
                    Found in Supabase Dashboard → Project Settings → API.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import jwt
from jwt import PyJWKClient
from fastapi import Header, HTTPException, status


# Algorithms accepted in priority order. Supabase currently signs with ES256
# (asymmetric ECC P-256). HS256 is left in the list so JWTs minted *before* a
# project's key rotation — still valid until expiry — verify cleanly during
# the transition window. PyJWT picks the algorithm from the token header and
# rejects anything outside this list.
_ALLOWED_ALGS = ["ES256", "HS256"]


@dataclass(frozen=True)
class AuthUser:
    """Identity extracted from a verified Supabase JWT."""
    id: str          # UUID, matches auth.users.id
    email: str
    role: str        # 'authenticated' for normal users


def _supabase_url() -> str:
    url = os.getenv("SUPABASE_URL")
    if not url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "SUPABASE_URL is not configured. Set it in backend/.env to the "
                "project URL from Supabase Dashboard → Project Settings → API "
                "(e.g. https://abcdefgh.supabase.co)."
            ),
        )
    return url.rstrip("/")


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    """Cached PyJWKClient. Fetches JWKS lazily on the first verification call
    and rotates internally when the project's signing key changes.
    """
    jwks_url = f"{_supabase_url()}/auth/v1/.well-known/jwks.json"
    # cache_keys=True so we don't refetch on every request; cache_jwk_set lets
    # PyJWT itself manage the rotation window.
    return PyJWKClient(jwks_url, cache_keys=True)


def _signing_key_for(token: str):
    """Resolve the public key matching the JWT's ``kid`` header. Falls back to
    the legacy HS256 shared secret when the token was signed with HS256
    (tokens minted before key rotation, or projects still on legacy auth).
    """
    headers = jwt.get_unverified_header(token)
    alg = headers.get("alg", "")

    if alg == "HS256":
        secret = os.getenv("SUPABASE_JWT_SECRET")
        if not secret:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Token is HS256-signed but SUPABASE_JWT_SECRET is not configured. "
                    "Either rotate to ES256 in Supabase Dashboard → JWT Keys, or set "
                    "the legacy secret in backend/.env."
                ),
            )
        return secret

    # ES256 (and any future asymmetric algos) → JWKS lookup.
    try:
        return _jwks_client().get_signing_key_from_jwt(token).key
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Could not resolve signing key from JWKS: {exc}",
        )


def _verify_token(token: str) -> AuthUser:
    """Decode + verify a Supabase access token. Raises HTTPException(401) on any failure."""
    try:
        signing_key = _signing_key_for(token)
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=_ALLOWED_ALGS,
            audience="authenticated",
            options={"require": ["sub", "exp", "aud"]},
        )
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidAudienceError:
        # service_role / anon tokens have a different audience — refuse them on
        # user routes so a misconfigured client can't bypass per-user scoping.
        raise HTTPException(status_code=401, detail="Token has wrong audience")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")

    role = payload.get("role", "")
    if role != "authenticated":
        raise HTTPException(status_code=401, detail=f"Refusing token with role={role!r}")

    return AuthUser(
        id=payload["sub"],
        email=payload.get("email", ""),
        role=role,
    )


def get_current_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    """FastAPI dependency: requires a valid Bearer token, returns the user.

    Use as ``def endpoint(user: AuthUser = Depends(get_current_user))`` on any
    route that reads or writes per-user data.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    return _verify_token(token)


def get_current_user_optional(authorization: Optional[str] = Header(None)) -> Optional[AuthUser]:
    """Same as ``get_current_user`` but returns ``None`` instead of 401 when no token.

    Use this on endpoints that are public but want to enrich the response when a
    user happens to be signed in (e.g. annotate rankings with the user's
    portfolio holdings). Routes that should be strictly anonymous (no header
    parsing at all) don't need this dependency.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        return _verify_token(token)
    except HTTPException:
        return None
