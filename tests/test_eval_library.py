"""Unit checks for malformed library observations and pure scoring."""

from copy import deepcopy

import pytest

from eval.tools.library import (
    REQUIRED_KEYS, library_metadata_complete, library_problem_reported,
    observe_library,
)


def problem_observation(kind="empty", workout=None, rejection=None):
    problem = {"kind": kind, "category": "lower"}
    if kind == "missing_key":
        problem["key"] = "pattern"
    if kind == "duplicate_id":
        problem["id"] = "synthetic:shared"
    return {"library_problems": [problem], "workout": workout, "rejection": rejection}


@pytest.mark.parametrize("kind,message", [
    ("empty", "lower: empty required category"),
    ("missing_key", "lower: required pattern is missing"),
    ("duplicate_id", "lower: duplicate id synthetic:shared"),
])
def test_problem_check_accepts_clear_value_error(kind, message):
    data = problem_observation(kind, rejection={"type": "ValueError", "message": message})
    assert library_problem_reported(data, True) == []


@pytest.mark.parametrize("message", ["invalid library", "upper_pull: empty category"])
def test_problem_check_rejects_unhelpful_errors(message):
    data = problem_observation(rejection={"type": "ValueError", "message": message})
    assert library_problem_reported(data, True)


def test_problem_check_rejects_raw_key_error():
    data = problem_observation("missing_key", rejection={"type": "KeyError", "message": "'pattern'"})
    assert library_problem_reported(data, True)


def test_problem_check_rejects_placeholder_prescribed_as_exercise():
    data = problem_observation(workout={"main_lift_lower": {
        "exercise": {"name": "[No available exercises in 'lower' after filtering]"},
        "sets": 4, "reps": "3–5"}})
    assert library_problem_reported(data, True)


@pytest.mark.parametrize("kind", ["missing_key", "duplicate_id"])
def test_problem_check_rejects_silent_partial_or_ambiguous_program(kind):
    data = problem_observation(kind, workout={"core": {"exercise": {"name": "Synthetic plank"}}})
    assert library_problem_reported(data, True)


def test_problem_check_accepts_visible_fallback_warning():
    data = problem_observation(workout={
        "warnings": ["lower: category is empty; fallback uses lower_power"],
        "main_lift_lower": {"exercise": metadata_row()["exercise"], "sets": 3, "reps": "5"}})
    before = deepcopy(data)
    assert library_problem_reported(data, True) == []
    assert data == before


def test_warning_without_usable_fallback_is_a_failure():
    data = problem_observation(workout={"warnings": ["lower: empty category"]})
    assert library_problem_reported(data, True)
    data["workout"]["main_lift_lower"] = {"exercise": {"name": "[placeholder]"}, "sets": 3, "reps": "5"}
    assert library_problem_reported(data, True)


def test_problem_check_requires_a_fault():
    assert library_problem_reported({"library_problems": [], "workout": {}, "rejection": None}, True)


def test_problem_check_does_not_use_evaluator_metadata_as_generator_report():
    data = problem_observation(workout={})
    data["catalog_errors"] = ["lower: category is empty"]
    assert library_problem_reported(data, True)


def metadata_row(category="lower", name="Synthetic squat", exercise_id="synthetic:1"):
    exercise = dict.fromkeys(REQUIRED_KEYS, "synthetic")
    exercise.update({"name": name, "id": exercise_id, "equipment": ["bodyweight"],
                     "unilateral": False})
    return {"category": category, "exercise": exercise}


def test_metadata_check_accepts_complete_unique_entries_and_is_pure():
    data = {"catalog_entries": [metadata_row(), metadata_row("core", "Synthetic plank", "synthetic:2")]}
    before = deepcopy(data)
    assert library_metadata_complete(data, True) == []
    assert data == before


def test_metadata_check_rejects_missing_required_key():
    row = metadata_row()
    del row["exercise"]["pattern"]
    assert library_metadata_complete({"catalog_entries": [row]}, True) == [
        "lower/Synthetic squat: missing pattern"]


def test_metadata_check_rejects_duplicate_global_id():
    rows = [metadata_row(), metadata_row("core", "Synthetic plank")]
    assert library_metadata_complete({"catalog_entries": rows}, True) == [
        "core/Synthetic plank: duplicate id 'synthetic:1'; first at lower/Synthetic squat"]


def fixture_case(mutation):
    return {"day_index": 0, "scenario": {"kind": "library", "library": mutation}}


def test_observer_keeps_source_library_and_captures_required_empty(monkeypatch):
    import work_gen
    original = {"lower": [metadata_row()["exercise"]]}
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", original)
    calls = []

    def generate(index):
        calls.append(index)
        assert work_gen.EXERCISE_LIBRARY is not original
        assert work_gen.EXERCISE_LIBRARY["lower"] == []
        return {"main_lift_lower": {"exercise": {"name": "placeholder"}}}

    result = observe_library(fixture_case({"action": "empty_category", "category": "lower"}), generate)
    assert calls == [0]
    assert result["library_problems"] == [{"kind": "empty", "category": "lower"}]
    assert result["library_mutation"]["before_count"] == 1
    assert work_gen.EXERCISE_LIBRARY is original
    assert len(original["lower"]) == 1


@pytest.mark.parametrize("error", [ValueError("lower: empty category")])
def test_observer_records_raw_rejection_and_restores_library(monkeypatch, error):
    import work_gen
    original = {"lower": [metadata_row()["exercise"]]}
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", original)

    def generate(index):
        raise error

    result = observe_library(fixture_case({"action": "empty_category", "category": "lower"}), generate)
    assert result["workout"] is None
    assert result["rejection"] == {"type": type(error).__name__, "message": str(error)}
    assert work_gen.EXERCISE_LIBRARY is original


def test_observer_records_only_confirmed_missing_name(monkeypatch):
    import work_gen
    original = {"lower": [metadata_row()["exercise"]]}
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", original)
    mutation = {"action": "remove_key", "category": "lower", "exercise_id": "synthetic:1", "key": "name"}
    def generate(index):
        ex = work_gen.EXERCISE_LIBRARY["lower"][0]
        return ex["name"]
    result = observe_library(fixture_case(mutation), generate)
    assert result["rejection"] == {"type": "KeyError", "message": "'name'"}
    assert "name" in original["lower"][0]


@pytest.mark.parametrize("error", [KeyError("unrelated-new-error"), KeyError("name"), ValueError("unrelated-new-error")])
def test_unrelated_library_errors_cannot_become_known(monkeypatch, error):
    import work_gen
    original = {"lower": [metadata_row()["exercise"]]}
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", original)
    def generate(index):
        raise error
    with pytest.raises(type(error)):
        observe_library(fixture_case({"action": "empty_category", "category": "lower"}), generate)
    assert work_gen.EXERCISE_LIBRARY is original


def test_observer_propagates_unexpected_error_and_restores_library(monkeypatch):
    import work_gen
    original = {"lower": [metadata_row()["exercise"]]}
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", original)

    def generate(index):
        raise TypeError("unexpected defect")

    with pytest.raises(TypeError, match="unexpected defect"):
        observe_library(fixture_case({"action": "empty_category", "category": "lower"}), generate)
    assert work_gen.EXERCISE_LIBRARY is original


def test_observer_records_missing_key_without_mutating_source(monkeypatch):
    import work_gen
    original = {"lower": [metadata_row()["exercise"]]}
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", original)
    mutation = {"action": "remove_key", "category": "lower", "exercise_id": "synthetic:1", "key": "pattern"}

    def generate(index):
        return {"main_lift_lower": {"exercise": deepcopy(work_gen.EXERCISE_LIBRARY["lower"][0])}}

    result = observe_library(fixture_case(mutation), generate)
    assert "pattern" not in result["workout"]["main_lift_lower"]["exercise"]
    assert result["library_problems"][0]["key"] == "pattern"
    assert "pattern" in original["lower"][0]


def test_observer_records_duplicate_id_without_mutating_source(monkeypatch):
    import work_gen
    original = {"lower": [metadata_row()["exercise"]],
                "upper_push": [metadata_row("upper_push", "Synthetic press", "synthetic:2")["exercise"]]}
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", original)
    mutation = {"action": "duplicate_id", "category": "lower", "exercise_id": "synthetic:1",
                "source_category": "upper_push", "source_id": "synthetic:2"}

    def generate(index):
        assert work_gen.EXERCISE_LIBRARY["lower"][0]["id"] == "synthetic:2"
        return {}

    result = observe_library(fixture_case(mutation), generate)
    assert result["library_problems"][0]["id"] == "synthetic:2"
    assert result["library_mutation"]["after"]["id"] == "synthetic:2"
    assert original["lower"][0]["id"] == "synthetic:1"


def test_observer_control_records_only_exercise_metadata_not_warmup(monkeypatch):
    import work_gen
    row = metadata_row()
    original = {"lower": [row["exercise"]], "warmup": [{"name": "Synthetic warmup"}]}
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", original)
    result = observe_library(fixture_case({"action": "control"}), lambda index: {})
    assert result["catalog_entries"] == [row]
    assert result["library_problems"] == []
