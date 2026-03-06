"""Common models shared across the Kahunas API."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Pagination(BaseModel):
    """Pagination metadata from API responses."""

    total: int = 0
    current_page: int = 1
    next_page: int | None = None
    per_page: int = 12
    start: int = 0
    data_range: list[int] = Field(default_factory=lambda: [12, 24, 36, 48, 100])
    showeachside: int = 5
    eitherside: int = 60
    num: int = 5


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response wrapper."""

    success: bool
    message: str = ""
    errors: list[str] = Field(default_factory=list)
    code: int = 0
    status: int | None = None
    data: T | None = None
    token_expired: int | None = None
    updated_token: str | None = None


class MediaItem(BaseModel):
    """Media attachment (video/image) for exercises or content."""

    model_config = ConfigDict(extra="allow")

    uuid: str = ""
    parent_uuid: str = ""
    parent_type: int | None = None
    file_name: str = ""
    file_url: str = ""
    mobile_file_url: str = ""
    file_type: int = 0
    user_uuid: str | None = None
    source: str = ""
    created_at: str | None = None
    created_at_utc: int | None = None


class ProgramType(BaseModel):
    """Workout program type."""

    id: int
    name: str


class PaginatedData(BaseModel, Generic[T]):
    """Generic wrapper for paginated list data."""

    model_config = ConfigDict(extra="allow")

    pagination: Pagination = Field(default_factory=Pagination)
    total_records: int = 0
    items: list[T] = Field(default_factory=list)


class WebActionResponse(BaseModel):
    """Response from web app action endpoints."""

    success: bool = False
    message: str = ""
    data: Any = None
    status: int = 0
