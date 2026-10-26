"""Observe a weekly schedule and check its stated day constraints."""

import json


MAIN_SLOTS = ("main_lift_lower", "main_lift_upper_push", "main_lift_upper_pull")
PRESCRIBED_SLOTS = ("warmup", *MAIN_SLOTS, "core", "accessories")


def observe_days(case, generate):
    """Call ``generate(index)`` with the caller's fixed clock and seed.

    Errors inside the requested schedule must propagate. At an index past
    the limit, ValueError and IndexError are accepted input rejections.
    Keep these rejections in the recording so that a baseline can be read.
    """
    import work_gen

    count = case["athlete"]["days_per_week"]
    sessions = [generate(index) for index in range(count)]
    after_limit = []
    for index in (count, count + 1):
        try:
            workout = generate(index)
        except (ValueError, IndexError) as exc:
            after_limit.append({"day_index": index, "workout": None,
                                "rejection": f"{type(exc).__name__}: {exc}"})
        else:
            after_limit.append({"day_index": index,
                                "workout": None if workout is None or workout == {} else workout,
                                "rejection": None})
    phase = case["athlete"]["phase"]
    plans = [work_gen._offseason_day_plan(count, index)
             if phase == "offseason" else None for index in range(count)]
    return {"sessions": sessions, "after_limit": after_limit, "day_plans": plans}


def day_count_equals(observation, expected):
    """Count nonempty workouts at the requested in-range indices."""
    actual = sum(isinstance(workout, dict) and bool(workout)
                 for workout in observation["sessions"])
    return [] if actual == expected else [f"expected {expected} sessions; observed {actual}"]


def sessions_distinct(observation, expected):
    """Compare the prescribed blocks, without scores or suggested weights."""
    signatures = {
        json.dumps({key: workout.get(key) for key in PRESCRIBED_SLOTS}, sort_keys=True)
        for workout in observation["sessions"] if isinstance(workout, dict) and workout
    }
    actual = len(signatures)
    return [] if actual == expected else [
        f"expected {expected} distinct sessions; observed {actual}"
    ]


def no_session_after_limit(observation, expected):
    """Require both observed indices past the limit to have no workout."""
    if not expected:
        return []
    return [f"day_index {row['day_index']}: returned a workout past the day limit"
            for row in observation["after_limit"]
            if row["workout"] is not None and row["workout"] != {}]


def fallback_full_body(observation, expected):
    """Record the three-day off-season fallback without calling it an error."""
    if not expected:
        return []
    violations = []
    if any(plan is not None for plan in observation["day_plans"]):
        violations.append("expected no off-season day plan for the fallback")
    for index, workout in enumerate(observation["sessions"]):
        for slot in MAIN_SLOTS:
            if not isinstance(workout, dict) or not workout.get(slot):
                violations.append(f"day_index {index}: fallback is missing {slot}")
    return violations


CHECKS = {
    "day_count_equals": day_count_equals,
    "sessions_distinct": sessions_distinct,
    "no_session_after_limit": no_session_after_limit,
    "fallback_full_body": fallback_full_body,
}
