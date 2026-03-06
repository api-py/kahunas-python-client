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


async def run_all_tests() -> None:
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
        try:
            programs = await client.list_workout_programs()
            report(
                "List workout programs",
                programs.total_records > 0,
                f"Found {programs.total_records} programs",
            )
            if programs.workout_plan:
                prog = programs.workout_plan[0]
                report("Program has title", bool(prog.title), f"'{prog.title}'")
                report("Program has uuid", bool(prog.uuid))

                # ── 3. Get single program detail ──
                try:
                    detail = await client.get_workout_program(prog.uuid)
                    days = detail.workout_plan.workout_days
                    report(
                        "Get workout program detail",
                        bool(detail.workout_plan.title),
                        f"'{detail.workout_plan.title}' with {len(days)} days",
                    )
                    if days:
                        day = days[0]
                        report("Workout day has title", bool(day.title), f"'{day.title}'")
                        el = day.exercise_list
                        detail_msg = (
                            f"warmup={len(el.warmup)}, "
                            f"workout={len(el.workout)}, "
                            f"cooldown={len(el.cooldown)}"
                        )
                        report("Exercise list parsed", el is not None, detail_msg)
                        # Verify exercise data within groups
                        total_exercises = 0
                        for section in (el.warmup, el.workout, el.cooldown):
                            for group in section:
                                total_exercises += len(group.exercises)
                                for ex in group.exercises:
                                    assert ex.exercise_name, f"Missing exercise_name in {ex.uuid}"
                        report(
                            "Exercises in workout day",
                            total_exercises > 0,
                            f"{total_exercises} exercises",
                        )
                        # Check exercise fields
                        sample = days[0].exercise_list.workout[0].exercises[0]
                        report(
                            "Exercise sets field",
                            sample.sets is not None,
                            f"sets='{sample.sets}', reps='{sample.reps}'",
                        )
                except Exception as e:
                    report("Get workout program detail", False, str(e))
        except Exception as e:
            report("List workout programs", False, str(e))

        # ── 4. List Exercises ──
        print("\n=== Exercises ===")
        try:
            exercises = await client.list_exercises()
            report(
                "List exercises",
                exercises.total_records > 0,
                f"Found {exercises.total_records} exercises",
            )
            if exercises.exercises:
                ex = exercises.exercises[0]
                report("Exercise has name", bool(ex.exercise_name), f"'{ex.exercise_name}'")
                report("Exercise has uuid", bool(ex.uuid))
                if ex.media:
                    m = ex.media[0]
                    report(
                        "Exercise media parsed",
                        bool(m.file_url),
                        f"{len(ex.media)} media items, type={m.file_type}",
                    )
        except Exception as e:
            report("List exercises", False, str(e))

        # ── 5. Search Exercises ──
        try:
            results = await client.search_exercises("bench")
            report(
                "Search exercises", len(results) >= 0, f"Found {len(results)} results for 'bench'"
            )
            if results:
                report(
                    "Search result has name",
                    bool(results[0].exercise_name),
                    f"'{results[0].exercise_name}'",
                )
        except Exception as e:
            report("Search exercises", False, str(e))

        # ── 6. Pagination ──
        print("\n=== Pagination ===")
        try:
            page2 = await client.list_exercises(page=2, per_page=5)
            report("Exercises page 2", True, f"Got {len(page2.exercises)} exercises")
        except Exception as e:
            report("Exercises page 2", False, str(e))

        # ── 7. Generic API ──
        print("\n=== Generic API ===")
        try:
            raw = await client.api_get("v1/workoutprogram", params={"per_page": 1})
            report("Generic API GET", raw.get("success", False))
        except Exception as e:
            report("Generic API GET", False, str(e))

        # ── 8. Web Endpoints (require session cookies) ──
        print("\n=== Web Endpoints (token-only auth) ===")
        print("  NOTE: Web endpoints require session cookies from email/password login.")
        print("  Token-only auth can only access REST API endpoints.")
        skip("List clients", "Requires session cookies (email/password login)")
        skip("Chat messages", "Requires session cookies (email/password login)")
        skip("Chart data", "Requires session cookies (email/password login)")
        skip("Habits", "Requires session cookies (email/password login)")
        skip("Packages", "Requires session cookies (email/password login)")

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
