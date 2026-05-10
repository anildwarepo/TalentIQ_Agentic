"""Entra ID (Azure AD) JWT token validation for FastAPI.

Validates Bearer tokens against Microsoft's JWKS endpoint for the
configured tenant.  When AZURE_TENANT_ID is not set, validation is
skipped (dev mode) and a warning is logged on every request.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import jwt
from fastapi import HTTPException, Request

from talent_backend.config import AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_TOKEN_AUDIENCE

logger = logging.getLogger("talent_backend.auth")

# ── JWKS cache ───────────────────────────────────────────────

_jwks_cache: dict[str, Any] | None = None
_jwks_fetched_at: float = 0.0
_JWKS_TTL_SECONDS: float = 3600  # 1 hour


def _jwks_url() -> str:
    return f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys"


def _issuer() -> str:
    return f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/v2.0"


def _issuers() -> list[str]:
    """Accept both v1.0 and v2.0 token issuers."""
    return [
        f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/v2.0",
        f"https://sts.windows.net/{AZURE_TENANT_ID}/",
    ]


async def _get_signing_keys() -> dict[str, Any]:
    """Fetch (or return cached) JWKS from Microsoft's endpoint."""
    global _jwks_cache, _jwks_fetched_at

    now = time.monotonic()
    if _jwks_cache is not None and (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS:
        return _jwks_cache

    url = _jwks_url()
    logger.info("Fetching JWKS from %s", url)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_fetched_at = now
        logger.info("JWKS refreshed — %d keys", len(_jwks_cache.get("keys", [])))
        return _jwks_cache


def _find_rsa_key(token: str, jwks: dict[str, Any]) -> dict[str, Any] | None:
    """Match the token's ``kid`` header to a key in the JWKS."""
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if not kid:
        return None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


# ── FastAPI dependency ───────────────────────────────────────

async def get_current_user(request: Request) -> dict[str, str | None]:
    """Validate the ``Authorization: Bearer <token>`` header.

    Returns a dict with ``oid``, ``name``, and ``email`` on success.
    Raises ``HTTPException(401)`` on missing or invalid tokens.

    When ``AZURE_TENANT_ID`` is not configured the check is skipped
    (dev mode) and a synthetic anonymous user dict is returned.
    """

    # ── Dev mode: skip validation when tenant is not configured ──
    if not AZURE_TENANT_ID:
        logger.warning("AZURE_TENANT_ID not set — auth is DISABLED (dev mode)")
        return {"oid": "dev-user", "name": "Dev User", "email": "dev@localhost"}

    # ── Extract Bearer token ─────────────────────────────────
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = auth_header[7:]  # strip "Bearer "

    # ── Validate ─────────────────────────────────────────────
    try:
        jwks = await _get_signing_keys()
        rsa_key = _find_rsa_key(token, jwks)
        if rsa_key is None:
            raise HTTPException(status_code=401, detail="Token signing key not found in JWKS")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(rsa_key)

        # Accept Foundry API scope, app client ID, or configured audience
        valid_audiences = [a for a in [AZURE_TOKEN_AUDIENCE, AZURE_CLIENT_ID] if a]

        payload = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=valid_audiences or None,
            options={
                "verify_exp": True,
                "verify_iss": False,  # validate manually — v1 and v2 have different issuers
                "verify_aud": bool(valid_audiences),
            },
        )

        # Manual issuer validation (accept both v1.0 and v2.0)
        token_issuer = payload.get("iss", "")
        if token_issuer not in _issuers():
            logger.warning("Token issuer %s not in allowed issuers", token_issuer)
            raise HTTPException(status_code=401, detail="Invalid token issuer")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidAudienceError:
        raise HTTPException(status_code=401, detail="Invalid token audience")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="Invalid token issuer")
    except jwt.PyJWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch JWKS: %s", exc)
        raise HTTPException(status_code=401, detail="Unable to validate token (JWKS fetch failed)")

    user = {
        "oid": payload.get("oid"),
        "name": payload.get("name"),
        "email": payload.get("preferred_username"),
    }
    logger.info("Authenticated user: %s (%s)", user["email"], user["oid"])
    return user
