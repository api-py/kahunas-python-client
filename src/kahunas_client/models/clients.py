"""Client/user models for the web app routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Client(BaseModel):
    """A coaching client."""

    model_config = ConfigDict(extra="allow")

    uuid: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    birthdate: str = ""
    package_name: str = ""
    check_in_day: str = ""
    status: str = ""
    created_at: str = ""
    updated_at: str = ""


class ClientCreateParams(BaseModel):
    """Parameters for creating a new client."""

    first_name: str
    last_name: str
    email: str
    phone: str = ""
    package_uuid: str = ""
    plan_start_date: str = ""
    payment_start_date: str = ""
    needs_payment: bool = False
    check_in_days: list[str] = Field(default_factory=list)
    check_in_form: str = ""
    welcome_qa: str = ""
    allow_goal: bool = False


class Package(BaseModel):
    """A coaching package."""

    model_config = ConfigDict(extra="allow")

    uuid: str = ""
    title: str = ""
    description: str = ""
    price: float = 0.0
    currency: str = ""
    duration: str = ""
    status: str = ""
    created_at: str = ""


class CheckIn(BaseModel):
    """A client check-in."""

    model_config = ConfigDict(extra="allow")

    uuid: str = ""
    client_uuid: str = ""
    client_name: str = ""
    check_in_number: int = 0
    submitted_at: str = ""
    data: Any = None


class Habit(BaseModel):
    """A client habit."""

    model_config = ConfigDict(extra="allow")

    uuid: str = ""
    client_uuid: str = ""
    title: str = ""
    completed: bool = False
    date: str = ""


class ChatMessage(BaseModel):
    """A chat message."""

    model_config = ConfigDict(extra="allow")

    id: int = 0
    sender_uuid: str = ""
    receiver_uuid: str = ""
    message: str = ""
    created_at: str = ""
    read: bool = False
