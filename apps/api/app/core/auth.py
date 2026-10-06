"""JWT authentication and role-based authorization (PLAN.md §27).

Roles and permissions:

    developer       create/view shipments, view events/logs, upload artifacts,
                    analyze incidents
    release_manager everything a developer can do + retry + publish
    admin           everything

Passwords are hashed with bcrypt (never stored or logged in plaintext).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

import bcrypt
import jwt
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.db.session import get_db

Role = Literal["developer", "release_manager", "admin"]

# Role hierarchy: each role includes the permissions of the one above it.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "developer": frozenset(
        {"shipment:read", "shipment:create", "artifact:write", "incident:analyze"}
    ),
    "release_manager": frozenset(
        {
            "shipment:read",
            "shipment:create",
            "artifact:write",
            "incident:analyze",
            "shipment:retry",
            "shipment:publish",
        }
    ),
    "admin": frozenset(
        {
            "shipment:read",
            "shipment:create",
            "artifact:write",
            "incident:analyze",
            "shipment:retry",
            "shipment:publish",
            "user:manage",
        }
    ),
}

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password with bcrypt (salted, never reversible)."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time password verification."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: uuid.UUID, username: str, role: str) -> str:
    """Create a signed JWT with a short expiry."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class AuthenticatedUser:
    """The authenticated principal attached to a request."""

    def __init__(self, user_id: uuid.UUID, username: str, role: str) -> None:
        self.id = user_id
        self.username = username
        self.role = role

    def has(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    """Validate the bearer token and return the authenticated user."""
    if credentials is None:
        raise AppError(
            "UNAUTHORIZED",
            "Authentication required",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    settings = get_settings()
    if not settings.jwt_secret:
        # Never fall back to an unsigned/empty secret.
        raise AppError(
            "INTERNAL_ERROR",
            "Authentication is not configured",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise AppError(
            "UNAUTHORIZED", "Token has expired", status_code=status.HTTP_401_UNAUTHORIZED
        ) from None
    except jwt.InvalidTokenError:
        raise AppError(
            "UNAUTHORIZED", "Invalid token", status_code=status.HTTP_401_UNAUTHORIZED
        ) from None

    from app.models.user import User

    user = db.scalars(select(User).where(User.id == uuid.UUID(payload["sub"]))).first()
    if user is None or not user.is_active:
        raise AppError(
            "UNAUTHORIZED", "Unknown or disabled user", status_code=status.HTTP_401_UNAUTHORIZED
        )
    return AuthenticatedUser(user_id=user.id, username=user.username, role=user.role)


def require(permission: str) -> Callable[..., AuthenticatedUser]:
    """Dependency factory enforcing a single permission."""

    def _checker(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not user.has(permission):
            raise AppError(
                "FORBIDDEN",
                f"Missing permission: {permission}",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return user

    return _checker
