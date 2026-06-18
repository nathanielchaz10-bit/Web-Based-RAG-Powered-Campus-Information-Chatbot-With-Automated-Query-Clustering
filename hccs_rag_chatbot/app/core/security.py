"""JWT helpers implemented with the Python standard library only.

The original version depended on python-jose, which is not in requirements.txt
and never installed cleanly. These functions produce/verify standard HS256 JWTs
using hmac + hashlib, so there is no third-party dependency to install. The
public API (create_access_token / decode_access_token) is unchanged.
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta

from app.core.config import settings


class TokenError(Exception):
    """Raised when a token is malformed, tampered with, or expired."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _sign(signing_input: bytes) -> str:
    signature = hmac.new(
        settings.JWT_SECRET_KEY.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    return _b64url_encode(signature)


def create_access_token(data: dict) -> str:
    """Encode `data` as a signed HS256 JWT with an expiry claim."""
    header = {"alg": "HS256", "typ": "JWT"}
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)

    payload = data.copy()
    payload["exp"] = int(expire.timestamp())

    header_segment = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature_segment = _sign(signing_input)

    return f"{header_segment}.{payload_segment}.{signature_segment}"


def decode_access_token(token: str) -> dict:
    """Verify signature + expiry and return the payload. Raises TokenError."""
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError:
        raise TokenError("Malformed token")

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_signature = _sign(signing_input)
    if not hmac.compare_digest(expected_signature, signature_segment):
        raise TokenError("Invalid signature")

    try:
        payload = json.loads(_b64url_decode(payload_segment))
    except (ValueError, json.JSONDecodeError):
        raise TokenError("Malformed payload")

    exp = payload.get("exp")
    if exp is not None and datetime.utcnow().timestamp() > exp:
        raise TokenError("Token expired")

    return payload
