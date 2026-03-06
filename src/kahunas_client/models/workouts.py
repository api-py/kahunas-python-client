"""Workout program models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .common import MediaItem, Pagination, ProgramType


class ExerciseSet(BaseModel):
    """A single set within a workout exercise."""

    model_config = ConfigDict(extra="allow")

    uuid: str = ""
    set_order: int = 0
    set_type: str = ""
    reps: str = ""
    weight: str = ""
    rir: str = ""
    rpe: str = ""
    tempo: str = ""
    rest: str = ""
    intensity: str = ""
    note: str = ""
    time_period: str = ""
    distance: str = ""
    distance_unit: str = ""
    kcal: str = ""
    heart_rate: str = ""


class WorkoutExercise(BaseModel):
    """An exercise within a workout day."""

    model_config = ConfigDict(extra="allow")

    id: int = 0
    uuid: str = ""
    workout_uuid: str = ""
    exercise_uuid: str = ""
    exercise_name: str = ""
    exercise_type: int = 1
    plan_uuid: str = ""
    circuit_uuid: str | None = None
    name: str | None = None
    type: int = 1
    exercise_order: int = 0
    group_order: int = 0
    sets: str | None = None
    reps: str | None = None
    rir: str | None = None
    rpe_rating: float | None = None
    intensity: str | None = None
    rest_period: int | str | None = None
    notes: str | None = None
    tempo: str | None = None
    media: list[MediaItem] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ExerciseGroup(BaseModel):
    """A group of exercises (normal, superset, circuit)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    type: str = "normal"
    exercises: list[WorkoutExercise] = Field(default_factory=list, alias="list")


class ExerciseList(BaseModel):
    """Categorized exercise lists for a workout day."""

    model_config = ConfigDict(extra="allow")

    warmup: list[ExerciseGroup] = Field(default_factory=list)
    workout: list[ExerciseGroup] = Field(default_factory=list)
    cooldown: list[ExerciseGroup] = Field(default_factory=list)


class WorkoutDay(BaseModel):
    """A single day within a workout program."""

    model_config = ConfigDict(extra="allow")

    uuid: str = ""
    title: str = ""
    additional_note: str = ""
    is_template: int = 0
    is_restday: int = 0
    exercise_list: ExerciseList = Field(default_factory=ExerciseList)


class WorkoutProgramSummary(BaseModel):
    """Workout program summary (from list endpoint)."""

    model_config = ConfigDict(extra="allow")

    uuid: str = ""
    title: str = ""
    user_uuid: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    created_at_utc: int | None = None
    updated_at_utc: int | None = None
    days: int = 0
    type: ProgramType = Field(default_factory=lambda: ProgramType(id=1, name="Detailed"))
    tags: list[str] = Field(default_factory=list)
    media: list[MediaItem] = Field(default_factory=list)
    is_editable: int = 1
    assigned_clients: int = 0


class WorkoutProgramDetail(BaseModel):
    """Full workout program detail (from single endpoint)."""

    model_config = ConfigDict(extra="allow")

    uuid: str = ""
    user_uuid: str = ""
    title: str = ""
    short_desc: str = ""
    long_desc: str = ""
    type: ProgramType = Field(default_factory=lambda: ProgramType(id=1, name="Detailed"))
    tags: list[str] = Field(default_factory=list)
    media: list[MediaItem] = Field(default_factory=list)
    updated_at: str = ""
    updated_at_utc: int = 0
    workout_days: list[WorkoutDay] = Field(default_factory=list)


class WorkoutProgramListData(BaseModel):
    """Response data for workout program list endpoint."""

    pagination: Pagination = Field(default_factory=Pagination)
    total_records: int = 0
    workout_plan: list[WorkoutProgramSummary] = Field(default_factory=list)


class WorkoutProgramDetailData(BaseModel):
    """Response data for single workout program endpoint."""

    workout_plan: WorkoutProgramDetail = Field(default_factory=WorkoutProgramDetail)
    default_weight_unit: Any = None
