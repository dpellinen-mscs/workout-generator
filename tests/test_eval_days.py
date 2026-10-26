"""Unit checks for weekly schedule observations and scoring."""

from copy import deepcopy

import pytest

from eval.tools.days import (
    MAIN_SLOTS, day_count_equals, fallback_full_body, no_session_after_limit,
    observe_days, sessions_distinct,
)


def session(name="Synthetic squat"):
    block = {"exercise": {"id": "synthetic-1", "name": name}, "sets": 3,
             "reps": "5", "intensity": "heavy"}
    return {slot: deepcopy(block) for slot in MAIN_SLOTS}


def test_day_count_equals_accepts_nonempty_workouts():
    assert day_count_equals({"sessions": [session(), session()]}, 2) == []


def test_day_count_equals_rejects_missing_workouts():
    assert day_count_equals({"sessions": [session(), None, {}]}, 3)


def test_sessions_distinct_accepts_different_prescriptions():
    first = session()
    second = session()
    second["main_lift_lower"]["sets"] = 4
    assert sessions_distinct({"sessions": [first, second]}, 2) == []


def test_sessions_distinct_rejects_duplicate_programs_with_different_scores():
    first = session()
    second = session()
    first["total_load_score"] = 12
    second["total_load_score"] = 15
    second["suggested_weights"] = {"lower": 100}
    assert sessions_distinct({"sessions": [first, second]}, 2)


def test_no_session_after_limit_accepts_no_workout_and_input_rejection():
    observation = {"after_limit": [
        {"day_index": 3, "workout": None, "rejection": None},
        {"day_index": 4, "workout": None, "rejection": "ValueError: past limit"},
    ]}
    assert no_session_after_limit(observation, True) == []


def test_no_session_after_limit_rejects_returned_workout():
    observation = {"after_limit": [{"day_index": 3, "workout": session()}]}
    assert no_session_after_limit(observation, True) == [
        "day_index 3: returned a workout past the day limit"
    ]


def test_no_session_after_limit_rejects_a_malformed_falsey_output():
    observation = {"after_limit": [{"day_index": 3, "workout": []}]}
    assert no_session_after_limit(observation, True)


def test_fallback_full_body_accepts_all_main_slots_with_no_plan():
    observation = {"sessions": [session()] * 3, "day_plans": [None] * 3}
    assert fallback_full_body(observation, True) == []


def test_fallback_full_body_rejects_missing_slot_and_unexpected_plan():
    workout = session()
    workout["main_lift_upper_pull"] = None
    observation = {"sessions": [workout], "day_plans": [{"include_pull": True}]}
    assert fallback_full_body(observation, True) == [
        "expected no off-season day plan for the fallback",
        "day_index 0: fallback is missing main_lift_upper_pull",
    ]


def test_observe_days_calls_each_index_and_keeps_supported_rejections():
    calls = []

    def generate(index):
        calls.append(index)
        if index == 3:
            raise ValueError("past limit")
        if index == 4:
            return {}
        return session()

    case = {"athlete": {"days_per_week": 3, "phase": "offseason"}}
    result = observe_days(case, generate)
    assert calls == [0, 1, 2, 3, 4]
    assert len(result["sessions"]) == 3
    assert result["day_plans"] == [None, None, None]
    assert result["after_limit"] == [
        {"day_index": 3, "workout": None, "rejection": "ValueError: past limit"},
        {"day_index": 4, "workout": None, "rejection": None},
    ]


@pytest.mark.parametrize("error", [ValueError, IndexError])
def test_observe_days_propagates_in_range_errors(error):
    def generate(index):
        raise error("in-range defect")

    case = {"athlete": {"days_per_week": 3, "phase": "offseason"}}
    with pytest.raises(error, match="in-range defect"):
        observe_days(case, generate)


def test_observe_days_propagates_unexpected_out_of_range_errors():
    def generate(index):
        if index >= 3:
            raise KeyError("unexpected defect")
        return session()

    case = {"athlete": {"days_per_week": 3, "phase": "inseason"}}
    with pytest.raises(KeyError, match="unexpected defect"):
        observe_days(case, generate)
