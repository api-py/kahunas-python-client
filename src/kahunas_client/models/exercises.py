"""Exercise models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .common import MediaItem, Pagination


class Exercise(BaseModel):
    """An exercise in the exercise library."""

    model_config = ConfigDict(extra="allow")

    id: int = 0
    uuid: str = ""
    user_uuid: str = ""
    title: str = ""
    exercise_name: str = ""
    sets: str | int | None = None
    reps: str | int | None = None
    rir: str | int | None = None
    rpe_rating: float | None = None
    intensity: str | None = None
    rest_period: int | str | None = None
    notes: str | None = None
    exercise_type: int = 1
    tempo: str | None = None
    kcal: float | None = None
    heart_rate: int | None = None
    distance: float | None = None
    distance_unit: str | None = None
    time_period: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    created_at_utc: int | None = None
    updated_at_utc: int | None = None
    is_admin: int = 0
    tags: list[str] = Field(default_factory=list)
    media: list[MediaItem] = Field(default_factory=list)


class ExerciseListData(BaseModel):
    """Response data for exercise list endpoints."""

    exercises: list[Exercise] = Field(default_factory=list)
    total_records: int = 0
    pagination: Pagination = Field(default_factory=Pagination)
