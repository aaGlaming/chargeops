"""Password hashing and signed access token primitives."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from uuid import uuid4

from app.config import Settings


TOKEN_ALGORITHM = "HS256"
PASSWORD_ALGORITHM = "pbkdf2_sha256"


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, iterations: int = 310_000) -> str:
    if len(password) < 10:
        raise ValueError("password must contain at least 10 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PASSWORD_ALGORITHM}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iteration_text, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        iterations = int(iteration_text)
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def _sign(signing_input: str, secret: str) -> str:
    return _b64encode(hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest())


def create_access_token(*, user_id: int, username: str, token_version: int, roles: list[str], settings: Settings) -> tuple[str, int]:
    if not settings.auth_secret or settings.auth_secret == "replace-with-a-random-long-secret":
        raise ValueError("AUTH_SECRET must be configured before issuing tokens")
    now = int(time.time())
    expires_in = settings.access_token_expire_minutes * 60
    header = {"alg": TOKEN_ALGORITHM, "typ": "JWT"}
    payload = {
        "iss": settings.auth_token_issuer,
        "sub": str(user_id),
        "username": username,
        "tv": token_version,
        "roles": roles,
        "iat": now,
        "exp": now + expires_in,
        "jti": str(uuid4()),
    }
    encoded_header = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}"
    return f"{signing_input}.{_sign(signing_input, settings.auth_secret)}", expires_in


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
        header = json.loads(_b64decode(encoded_header))
        payload = json.loads(_b64decode(encoded_payload))
        if header.get("alg") != TOKEN_ALGORITHM or header.get("typ") != "JWT":
            raise ValueError("unsupported token header")
        signing_input = f"{encoded_header}.{encoded_payload}"
        secrets_to_try = [settings.auth_secret]
        if settings.auth_secret_previous:
            secrets_to_try.append(settings.auth_secret_previous)
        if not any(secret and hmac.compare_digest(_sign(signing_input, secret), encoded_signature) for secret in secrets_to_try):
            raise ValueError("invalid token signature")
        if payload.get("iss") != settings.auth_token_issuer:
            raise ValueError("invalid token issuer")
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise ValueError("token expired")
        if not payload.get("sub") or not isinstance(payload.get("tv"), int):
            raise ValueError("invalid token claims")
        return payload
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("invalid access token") from exc
