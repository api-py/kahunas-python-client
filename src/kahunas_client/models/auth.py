"""Authentication models."""

from __future__ import annotations

from pydantic import BaseModel


class AuthCredentials(BaseModel):
    """Login credentials."""

    email: str
    password: str


class AuthSession(BaseModel):
    """Authenticated session state."""

    auth_token: str
    csrf_token: str = ""
    session_cookie: str = ""
    user_id: str = ""
    user_type: str = ""
    user_name: str = ""
    user_email: str = ""
