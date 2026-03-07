"""Functional tests against the live Kahunas API.

Run with: uv run python tests/functional_test.py
Requires a valid auth token in /tmp/kahunas_token.txt

NOTE: Web app endpoints (clients, chat, habits, packages, charts) require
session cookies from the email/password login flow. Token-only auth can
only access the REST API endpoints at api.kahunas.io/api.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kahunas_client.client import KahunasClient
from kahunas_client.config import KahunasConfig


def load_token() -> str:
    token_file = Path("/tmp/kahunas_token.txt")
    if token_file.exists():
        return token_file.read_text().strip()
    raise FileNotFoundError("No token file at /tmp/kahunas_token.txt")


PASS = 0
FAIL = 0
SKIP = 0
ERRORS: list[str] = []

# Throttle between API calls to avoid rate limiting
THROTTLE_DELAY = 0.5


def report(name: str, success: bool, detail: str = "") -> None:
    global PASS, FAIL
    status = "PASS" if success else "FAIL"
    if success:
        PASS += 1
    else:
        FAIL += 1
        ERRORS.append(f"{name}: {detail}")
    print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))


def skip(name: str, reason: str) -> None:
    global SKIP
    SKIP += 1
    print(f"  [SKIP] {name} - {reason}")


async def throttled() -> None:
    """Small delay between API calls to avoid rate limiting."""
    await asyncio.sleep(THROTTLE_DELAY)


async def run_all_tests() -> int:
    token = load_token()
    config = KahunasConfig(
        api_base_url="https://api.kahunas.io/api",
        web_base_url="https://kahunas.io",
        auth_token=token,
    )

    async with KahunasClient(config) as client:
        # ── 1. Authentication ──
        print("\n=== Authentication ===")
        report("Token auth", client.is_authenticated)

        # ── 2. List Workout Programs ──
        print("\n=== Workout Programs ===")
        first_program_uuid = None
        try:
            programs = await client.list_workout_programs()

            # Validate payload structure
            report(
                "Programs payload has pagination",
                hasattr(programs, "pagination"),
                f"page={programs.pagination.current_page}",
            )
            report(
                "Programs payload has total_records",
                programs.total_records >= 0,
                f"total={programs.total_records}",
            )
            report(
                "List workout programs",
                programs.total_records > 0,
                f"Found {programs.total_records} programs",
            )

            if programs.workout_plan:
                prog = programs.workout_plan[0]
                first_program_uuid = prog.uuid

                # Validate program summary fields
                report("Program has title", bool(prog.title), f"'{prog.title}'")
                report("Program has uuid", bool(prog.uuid))
                report(
                    "Program has days count",
                    prog.days >= 0,
                    f"days={prog.days}",
                )
                report(
                    "Program has type",
                    prog.type is not None,
                    f"type={prog.type.name}",
                )
        except Exception as e:
            report("List workout programs", False, str(e))

        await throttled()

        # ── 3. Get single program detail ──
        if first_program_uuid:
            try:
                detail = await client.get_workout_program(first_program_uuid)
                days = detail.workout_plan.workout_days
                report(
                    "Get workout program detail",
                    bool(detail.workout_plan.title),
                    f"'{detail.workout_plan.title}' with {len(days)} days",
                )

                if days:
                    day = days[0]
                    report(
                        "Workout day has title",
                        bool(day.title),
                        f"'{day.title}'",
                    )

                    el = day.exercise_list
                    detail_msg = (
                        f"warmup={len(el.warmup)}, "
                        f"workout={len(el.workout)}, "
                        f"cooldown={len(el.cooldown)}"
                    )
                    report("Exercise list parsed", el is not None, detail_msg)

                    # Validate exercises
                    total_exercises = 0
                    for section in (el.warmup, el.workout, el.cooldown):
                        for group in section:
                            assert hasattr(group, "type"), "Group missing type"
                            assert hasattr(group, "exercises"), "Group missing exercises"
                            total_exercises += len(group.exercises)
                            for ex in group.exercises:
                                assert ex.exercise_name, f"Missing exercise_name in {ex.uuid}"

                    report(
                        "Exercises in workout day",
                        total_exercises > 0,
                        f"{total_exercises} exercises",
                    )

                    # Validate exercise fields (sets is a string, not a list)
                    if el.workout and el.workout[0].exercises:
                        sample = el.workout[0].exercises[0]
                        report(
                            "Exercise sets is string",
                            isinstance(sample.sets, str | None),
                            f"sets='{sample.sets}' (type={type(sample.sets).__name__})",
                        )
                        report(
                            "Exercise reps field exists",
                            hasattr(sample, "reps"),
                            f"reps='{sample.reps}'",
                        )
                        report(
                            "Exercise has rest_period",
                            hasattr(sample, "rest_period"),
                            f"rest_period={sample.rest_period}",
                        )
            except Exception as e:
                report("Get workout program detail", False, str(e))

        await throttled()

        # ── 4. List Exercises ──
        print("\n=== Exercises ===")
        try:
            exercises = await client.list_exercises()

            report(
                "Exercises payload has pagination",
                hasattr(exercises, "pagination"),
            )
            report(
                "List exercises",
                exercises.total_records > 0,
                f"Found {exercises.total_records} exercises",
            )

            if exercises.exercises:
                ex = exercises.exercises[0]

                report(
                    "Exercise has name",
                    bool(ex.exercise_name),
                    f"'{ex.exercise_name}'",
                )
                report("Exercise has uuid", bool(ex.uuid))
                report(
                    "Exercise has exercise_type",
                    ex.exercise_type in (1, 2),
                    f"type={ex.exercise_type}",
                )

                if ex.media:
                    m = ex.media[0]
                    report(
                        "Media has file_url",
                        bool(m.file_url),
                        f"type={m.file_type}",
                    )
                    report(
                        "Media parent_type is nullable",
                        m.parent_type is None or isinstance(m.parent_type, int),
                        f"parent_type={m.parent_type}",
                    )
        except Exception as e:
            report("List exercises", False, str(e))

        await throttled()

        # ── 5. Search Exercises ──
        try:
            results = await client.search_exercises("bench")
            report(
                "Search exercises",
                len(results) >= 0,
                f"Found {len(results)} results for 'bench'",
            )
            if results:
                report(
                    "Search result has name",
                    bool(results[0].exercise_name),
                    f"'{results[0].exercise_name}'",
                )
        except Exception as e:
            report("Search exercises", False, str(e))

        await throttled()

        # ── 6. Pagination ──
        print("\n=== Pagination ===")
        try:
            page2 = await client.list_exercises(page=2, per_page=5)
            report(
                "Exercises page 2",
                True,
                f"Got {len(page2.exercises)} exercises",
            )
            report(
                "Pagination per_page respected",
                len(page2.exercises) <= 5,
                f"requested 5, got {len(page2.exercises)}",
            )
        except Exception as e:
            report("Exercises page 2", False, str(e))

        await throttled()

        # ── 7. Generic API ──
        print("\n=== Generic API ===")
        try:
            raw = await client.api_get(
                "v1/workoutprogram",
                params={"per_page": 1},
            )
            report("Generic API GET", raw.get("success", False))
            report(
                "Generic response has standard keys",
                all(k in raw for k in ("success", "message", "data")),
                f"keys={list(raw.keys())[:6]}",
            )
        except Exception as e:
            report("Generic API GET", False, str(e))

        # ── 8. Web Endpoints (require session cookies) ──
        print("\n=== Web Endpoints (token-only auth) ===")
        print("  NOTE: Web endpoints require session cookies from login.")
        skip("List clients", "Requires session cookies (email/password login)")
        skip("Chat messages", "Requires session cookies")
        skip("Chart data", "Requires session cookies")
        skip("Habits", "Requires session cookies")
        skip("Packages", "Requires session cookies")

    # ── Summary ──
    total = PASS + FAIL
    print(f"\n{'=' * 50}")
    print(f"RESULTS: {PASS} passed, {FAIL} failed, {SKIP} skipped (out of {total} tests)")
    if ERRORS:
        print("\nFailures:")
        for err in ERRORS:
            print(f"  - {err}")
    else:
        print("\nAll tests passed!")
    print(f"{'=' * 50}")
    return FAIL


if __name__ == "__main__":
    failures = asyncio.run(run_all_tests())
    sys.exit(1 if failures else 0)
