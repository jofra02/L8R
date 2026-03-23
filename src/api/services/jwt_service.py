import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt

from src.config import settings


def create_access_token(
    user_id: str,
    customer_id: str,
    permissions: list[str],
    is_platform_admin: bool = False,
    must_change_password: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "cid": customer_id,
        "perms": permissions,
        "ipa": is_platform_admin,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    if must_change_password:
        payload["mcp"] = True
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def create_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token, token_hash, expires_at)."""
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return raw, token_hash, expires_at


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
