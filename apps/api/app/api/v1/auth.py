"""Authentication endpoints (PLAN.md §27)."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, create_access_token, get_current_user, verify_password
from app.core.exceptions import AppError
from app.db.session import get_db
from app.models.user import User

router = APIRouter()


class LoginRequest(BaseModel):
    """Credentials for POST /api/v1/auth/login."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """JWT bearer token."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds")


class UserResponse(BaseModel):
    """The authenticated user's profile."""

    id: str
    username: str
    role: str


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Exchange credentials for a JWT bearer token."""
    user = db.scalars(select(User).where(User.username == payload.username)).first()
    # Same error for unknown user and wrong password — no user enumeration.
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise AppError(
            "UNAUTHORIZED",
            "Invalid username or password",
            status_code=401,
        )
    token = create_access_token(user.id, user.username, user.role)
    from app.core.config import get_settings

    return TokenResponse(
        access_token=token,
        expires_in=get_settings().jwt_expires_minutes * 60,
    )


@router.get("/me", response_model=UserResponse)
def me(user: AuthenticatedUser = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse(id=str(user.id), username=user.username, role=user.role)
