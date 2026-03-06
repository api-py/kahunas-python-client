"""Tests for Pydantic models."""

from __future__ import annotations

from kahunas_client.models import (
    ApiResponse,
    AuthSession,
    CheckIn,
    Client,
    Exercise,
    ExerciseListData,
    ExerciseSet,
    MediaItem,
    Pagination,
    WorkoutDay,
    WorkoutExercise,
    WorkoutProgramDetail,
    WorkoutProgramDetailData,
    WorkoutProgramListData,
    WorkoutProgramSummary,
)


class TestApiResponse:
    def test_success(self) -> None:
        r = ApiResponse(success=True, message="ok", code=200, data={"key": "val"})
        assert r.success is True
        assert r.data == {"key": "val"}

    def test_with_token_fields(self) -> None:
        r = ApiResponse(success=True, token_expired=1, updated_token="new-tok")
        assert r.token_expired == 1
        assert r.updated_token == "new-tok"


class TestAuthSession:
    def test_basic(self) -> None:
        s = AuthSession(auth_token="abc123")
        assert s.auth_token == "abc123"
        assert s.user_id == ""

    def test_full(self) -> None:
        s = AuthSession(
            auth_token="tok",
            csrf_token="csrf",
            user_id="uid",
            user_type="coach",
            user_name="Test User",
            user_email="test@test.com",
        )
        assert s.user_type == "coach"
        assert s.user_name == "Test User"


class TestExercise:
    def test_minimal(self) -> None:
        e = Exercise()
        assert e.title == ""
        assert e.exercise_type == 1
        assert e.tags == []
        assert e.media == []

    def test_full(self) -> None:
        e = Exercise(
            uuid="ex-1",
            title="Bench Press",
            exercise_name="Bench Press",
            sets=None,
            reps=None,
            rir=None,
            rpe_rating=8.0,
            exercise_type=1,
            tags=["chest", "push"],
            media=[
                MediaItem(
                    uuid="m1",
                    file_url="https://example.com/video.mp4",
                    parent_type=None,
                    created_at=None,
                )
            ],
        )
        assert e.exercise_name == "Bench Press"
        assert e.tags == ["chest", "push"]
        assert len(e.media) == 1

    def test_realistic_api_response(self) -> None:
        """Test with data matching real Kahunas API response structure."""
        e = Exercise.model_validate(
            {
                "id": 327947,
                "uuid": "0448d4aa-6494-4ccf-a602-7deedc61323f",
                "user_uuid": "admin_5f158ca32635a",
                "title": "3-4 Sit-up",
                "exercise_name": "3-4 Sit-up",
                "sets": None,
                "reps": None,
                "rir": None,
                "rpe_rating": None,
                "intensity": None,
                "rest_period": None,
                "notes": None,
                "exercise_type": 1,
                "tempo": None,
                "kcal": None,
                "heart_rate": None,
                "distance": None,
                "distance_unit": None,
                "time_period": None,
                "created_at": "2023-09-28T02:34:31.000000Z",
                "updated_at": "2 year Ago",
                "created_at_utc": 1695868471,
                "updated_at_utc": 1695868471,
                "is_admin": 1,
                "tags": ["Female", "abs"],
                "media": [
                    {
                        "uuid": "c03b4ea6-f23e-4b4e-b04a-90f3c2c0787a",
                        "parent_uuid": "",
                        "parent_type": 0,
                        "file_name": "a2ae25e2-2f7e-49dc-bed9-4fd058a06a49",
                        "file_url": "https://iframe.mediadelivery.net/embed/25461/test",
                        "mobile_file_url": "https://vz-test.b-cdn.net/test/playlist.m3u8",
                        "file_type": 1,
                        "user_uuid": None,
                        "source": "bunny",
                        "created_at": "28th Sep 2023 03:34",
                        "created_at_utc": 1695868471,
                    },
                    {
                        "uuid": "",
                        "parent_uuid": "",
                        "parent_type": 4,
                        "file_name": "test",
                        "file_url": "https://vz-test.b-cdn.net/test/thumbnail.jpg",
                        "mobile_file_url": "https://vz-test.b-cdn.net/test/thumbnail.jpg",
                        "file_type": 2,
                        "user_uuid": None,
                        "source": "bunny",
                        "created_at": None,
                        "created_at_utc": None,
                    },
                ],
                "bodypart": [{"id": 1, "body_part_name": "Abs"}],
                "is_editable": 1,
            }
        )
        assert e.exercise_name == "3-4 Sit-up"
        assert e.sets is None
        assert len(e.media) == 2
        assert e.media[1].created_at is None
        assert e.media[1].parent_type == 4


class TestExerciseListData:
    def test_empty(self) -> None:
        d = ExerciseListData()
        assert d.exercises == []
        assert d.total_records == 0

    def test_with_data(self) -> None:
        d = ExerciseListData(
            exercises=[Exercise(title="Squat")],
            total_records=1,
            pagination=Pagination(total=1),
        )
        assert len(d.exercises) == 1
        assert d.total_records == 1


class TestWorkoutModels:
    def test_exercise_set(self) -> None:
        s = ExerciseSet(set_order=1, reps="10", weight="60kg", rir="2")
        assert s.reps == "10"
        assert s.weight == "60kg"

    def test_workout_exercise(self) -> None:
        e = WorkoutExercise(
            exercise_name="Deadlift",
            sets="4",
            reps="8-12",
            rest_period=120,
        )
        assert e.sets == "4"
        assert e.reps == "8-12"
        assert e.rest_period == 120

    def test_workout_exercise_from_api(self) -> None:
        """Test with data matching real workout program detail API response."""
        e = WorkoutExercise.model_validate(
            {
                "id": 53090725,
                "uuid": "a13d0acd-b952-4dec-bc19-cba5f81ebfe0",
                "workout_uuid": "a13d0acd-b780-4cdb-8db5-53e2a1aed33c",
                "exercise_uuid": "8f7bf54d-1557-4f19-8d97-a3ef66acfed0",
                "exercise_name": "Barbell Bench Press",
                "exercise_type": 1,
                "plan_uuid": "a13d0acd-b4a9-4b54-8664-7e787d1c08bf",
                "circuit_uuid": None,
                "name": None,
                "type": 1,
                "exercise_order": 1,
                "group_order": 0,
                "sets": "4",
                "reps": "8-12",
                "rir": None,
                "rpe_rating": None,
                "intensity": None,
                "rest_period": 120,
                "notes": None,
                "tempo": None,
                "media": [
                    {
                        "uuid": "7ce1d9e7-test",
                        "parent_uuid": "",
                        "parent_type": None,
                        "file_name": "test",
                        "file_url": "https://iframe.mediadelivery.net/embed/test",
                        "mobile_file_url": "https://vz-test.b-cdn.net/test/playlist.m3u8",
                        "file_type": 1,
                        "user_uuid": None,
                        "source": "bunny",
                        "created_at": "28th Sep 2023 03:34",
                        "created_at_utc": 1695868488,
                    },
                ],
                "tags": ["upper", "push"],
            }
        )
        assert e.exercise_name == "Barbell Bench Press"
        assert e.sets == "4"
        assert e.reps == "8-12"
        assert e.rest_period == 120
        assert e.media[0].parent_type is None

    def test_workout_day(self) -> None:
        d = WorkoutDay(title="Day 1 - Push", is_restday=0)
        assert d.title == "Day 1 - Push"
        assert d.is_restday == 0

    def test_program_summary(self) -> None:
        s = WorkoutProgramSummary(uuid="prog-1", title="PPL", days=6)
        assert s.title == "PPL"
        assert s.days == 6

    def test_program_detail(self) -> None:
        p = WorkoutProgramDetail(
            uuid="prog-1",
            title="Test Program",
            workout_days=[WorkoutDay(title="Day 1")],
        )
        assert len(p.workout_days) == 1

    def test_list_data(self) -> None:
        d = WorkoutProgramListData(
            workout_plan=[WorkoutProgramSummary(uuid="p1", title="Plan A")],
            total_records=1,
        )
        assert len(d.workout_plan) == 1

    def test_detail_data(self) -> None:
        d = WorkoutProgramDetailData(
            workout_plan=WorkoutProgramDetail(uuid="p1", title="Full Plan")
        )
        assert d.workout_plan.title == "Full Plan"


class TestClientModels:
    def test_client(self) -> None:
        c = Client(first_name="John", last_name="Doe", email="john@test.com")
        assert c.first_name == "John"

    def test_checkin(self) -> None:
        ci = CheckIn(uuid="ci-1", check_in_number=3, client_uuid="c-1")
        assert ci.check_in_number == 3


class TestPagination:
    def test_defaults(self) -> None:
        p = Pagination()
        assert p.total == 0
        assert p.current_page == 1
        assert p.per_page == 12

    def test_custom(self) -> None:
        p = Pagination(total=100, current_page=2, next_page=3, per_page=24)
        assert p.next_page == 3
