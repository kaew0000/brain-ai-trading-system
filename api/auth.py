"""
api/auth.py — P1-A Dashboard Authentication
============================================================
Two credential types, one role model.

  API Key    (X-API-Key header)       long-lived, operator-issued, meant
                                       for server-to-server / scripted
                                       clients.
  Bearer JWT (Authorization: Bearer)  short-lived, minted from an API key
                                       via POST /api/auth/token, meant for
                                       the browser dashboard session.
                                       Supports expiration + rotation.

Roles (ascending privilege): VIEWER < OPERATOR < ADMIN.
  VIEWER   read-only access to every GET /api/* route and every read-only
           /ws/* stream.
  OPERATOR VIEWER + may issue commands that change live trading state
           (POST /api/command, /ws/command — pause/resume, paper mode).
  ADMIN    reserved for future privileged actions (key management, config
           writes). Nothing in the current API needs it yet — not
           invented here, just reserved so the role ordering is stable.

Enforcement only runs when settings.API_AUTH_ENABLED is true. See
config/settings.py for why that defaults to False.
"""
from __future__ import annotations

import hmac
import secrets as _secrets
import time
import uuid
from dataclasses import dataclass
from enum import IntEnum

import jwt  # PyJWT
from fastapi import Request, WebSocket

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("api.auth")


class Role(IntEnum):
    VIEWER = 1
    OPERATOR = 2
    ADMIN = 3

    @classmethod
    def from_str(cls, name: str) -> Role:
        try:
            return cls[name.strip().upper()]
        except (KeyError, AttributeError):
            raise ValueError(f"unknown role: {name!r}")


@dataclass
class AuthContext:
    principal: str            # masked API key, or JWT subject
    role: Role
    method: str                # "api_key" | "bearer" | "disabled"
    jti: str | None = None  # bearer tokens only


class AuthError(Exception):
    """Raised on any authentication/authorization failure. Carries the
    HTTP status the caller should respond with (401 vs 403)."""

    def __init__(self, status_code: int, reason: str):
        self.status_code = status_code
        self.reason = reason
        super().__init__(reason)


# ── Startup safety check ────────────────────────────────────────────────
# An empty JWT_SECRET with auth enabled would let anyone forge an ADMIN
# token. Don't silently sign with "" and don't hard-crash the process
# (that would violate "never remove working features" for anyone who
# flips the flag without reading the docs first) — generate a random
# ephemeral secret and make it impossible to miss in the logs instead.
if settings.API_AUTH_ENABLED and not settings.JWT_SECRET:
    settings.JWT_SECRET = _secrets.token_hex(32)
    logger.critical(
        "API_AUTH_ENABLED=true but JWT_SECRET is not set — generated a "
        "random ephemeral secret for THIS PROCESS ONLY. Bearer tokens "
        "will not survive a restart and won't validate against any other "
        "replica. Set JWT_SECRET in .env before running this in production."
    )
if settings.API_AUTH_ENABLED and not settings.API_KEYS:
    logger.critical(
        "API_AUTH_ENABLED=true but API_KEYS is empty — nobody, including "
        "an operator, can authenticate (bearer tokens are minted from an "
        "API key via /api/auth/token, so there is no other way in). "
        "Configure API_KEYS in .env."
    )


# ── API key lookup ──────────────────────────────────────────────────────

def _lookup_api_key(raw_key: str) -> Role | None:
    if not raw_key:
        return None
    for configured_key, role_name in settings.API_KEYS.items():
        # Constant-time compare to avoid leaking key material via timing.
        if hmac.compare_digest(configured_key, raw_key):
            try:
                return Role.from_str(role_name)
            except ValueError:
                logger.error(f"API_KEYS entry has an unknown role {role_name!r} — ignoring this key")
                return None
    return None


def _mask(raw_key: str) -> str:
    if len(raw_key) <= 8:
        return "***"
    return f"{raw_key[:4]}…{raw_key[-4:]}"


# ── Bearer JWTs ──────────────────────────────────────────────────────────

# jti -> expiry epoch. In-memory by design (same single-process assumption
# already used everywhere else in this file, e.g. _state / ConnectionManager
# in api/app.py) — doesn't survive a restart, which is fine since restart
# also invalidates every in-flight token's usefulness for a live dashboard
# session; the browser just re-authenticates.
_revoked_jti: dict[str, float] = {}


def _cleanup_revoked() -> None:
    now = time.time()
    for j in [j for j, exp in _revoked_jti.items() if exp < now]:
        _revoked_jti.pop(j, None)


def issue_token(role: Role, subject: str = "dashboard") -> dict:
    now = int(time.time())
    exp = now + settings.JWT_EXPIRY_MINUTES * 60
    jti = uuid.uuid4().hex
    payload = {"sub": subject, "role": role.name, "iat": now, "exp": exp, "jti": jti}
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
    return {"token": token, "role": role.name, "expires_at": exp, "jti": jti}


def issue_token_for_api_key(raw_key: str) -> dict | None:
    """POST /api/auth/token — exchange an API key for a short-lived bearer token."""
    role = _lookup_api_key(raw_key)
    if role is None:
        return None
    return issue_token(role)


def revoke_token(jti: str, exp: float) -> None:
    _revoked_jti[jti] = exp


def _decode_bearer(token: str) -> AuthContext:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError(401, "token expired")
    except jwt.InvalidTokenError:
        raise AuthError(401, "invalid token")

    _cleanup_revoked()
    jti = payload.get("jti")
    if jti and jti in _revoked_jti:
        raise AuthError(401, "token revoked")

    try:
        role = Role.from_str(payload.get("role", ""))
    except ValueError:
        raise AuthError(401, "token has an invalid role claim")

    return AuthContext(principal=payload.get("sub", "unknown"), role=role, method="bearer", jti=jti)


def rotate_token(bearer_token: str) -> dict:
    """POST /api/auth/rotate — revoke the presented token, issue a fresh one
    with the same role. Raises AuthError if the presented token isn't
    currently valid (expired/revoked/malformed tokens can't be rotated —
    get a new one from /api/auth/token instead)."""
    ctx = _decode_bearer(bearer_token)  # raises AuthError on any problem
    if ctx.jti:
        try:
            payload = jwt.decode(bearer_token, settings.JWT_SECRET, algorithms=["HS256"])
            revoke_token(ctx.jti, payload.get("exp", time.time() + 1))
        except jwt.InvalidTokenError:
            pass
    return issue_token(ctx.role, subject=ctx.principal)


# ── Shared resolution (HTTP + WS) ────────────────────────────────────────

def _extract_bearer(header_value: str | None) -> str | None:
    if not header_value:
        return None
    parts = header_value.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _resolve(api_key: str | None, bearer: str | None) -> AuthContext:
    if api_key:
        role = _lookup_api_key(api_key)
        if role is None:
            raise AuthError(401, "invalid API key")
        return AuthContext(principal=_mask(api_key), role=role, method="api_key")
    if bearer:
        return _decode_bearer(bearer)
    raise AuthError(401, "missing credentials (X-API-Key or Authorization: Bearer)")


def authenticate_request(request: Request) -> AuthContext:
    """Used by the HTTP auth middleware in api/app.py."""
    api_key = request.headers.get("x-api-key")
    bearer = _extract_bearer(request.headers.get("authorization"))
    return _resolve(api_key, bearer)


def _ws_credentials(ws: WebSocket) -> tuple[str | None, str | None]:
    api_key = ws.headers.get("x-api-key")
    # Browsers can't set custom headers on the native WebSocket handshake,
    # so a bearer token may also arrive as ?token=... on the connect URL.
    # Only bearer tokens fall back to the query string (short-lived) —
    # never API keys (long-lived, shouldn't end up in proxy/access logs).
    bearer = _extract_bearer(ws.headers.get("authorization")) or ws.query_params.get("token")
    return api_key, bearer


async def enforce_ws_role(ws: WebSocket, min_role: Role) -> AuthContext | None:
    """Call BEFORE accepting the connection (i.e. before manager.connect()).
    Returns the AuthContext on success. On failure, closes the handshake
    and returns None — the caller must return immediately without
    registering the connection with its ConnectionManager."""
    if not settings.API_AUTH_ENABLED:
        return AuthContext(principal="auth-disabled", role=Role.ADMIN, method="disabled")

    client = ws.client.host if ws.client else "?"
    path = ws.url.path
    try:
        api_key, bearer = _ws_credentials(ws)
        ctx = _resolve(api_key, bearer)
    except AuthError as exc:
        log_unauthorized(path, "WS", client, exc.reason)
        await ws.close(code=4401)
        return None

    if ctx.role < min_role:
        log_unauthorized(path, "WS", client, f"role {ctx.role.name} < required {min_role.name}")
        await ws.close(code=4403)
        return None
    return ctx


def log_unauthorized(path: str, method: str, client: str, reason: str) -> None:
    """Every rejected request is logged — never the credential value itself."""
    logger.warning(f"UNAUTHORIZED {method} {path} from {client}: {reason}")
