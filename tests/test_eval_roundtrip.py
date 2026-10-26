"""Verify pure round-trip scorers and file/database isolation."""

from copy import deepcopy
import pytest

from eval.tools import roundtrip
import work_gen


@pytest.fixture
def case():
    return {"id": "roundtrip-unit", "athlete": {
        "position": "RHP", "goal": "power", "phase": "offseason",
        "days_per_week": 3, "injuries": [],
    }, "history": [], "day_index": 0, "scenario": {"kind": "roundtrip"}}


@pytest.fixture
def workout(case):
    return work_gen.generate_workout(case["athlete"], history=[], day_index=0)


def test_json_roundtrip_preserves_complete_payload(case, workout):
    observation = roundtrip.observe_roundtrip(case, workout)
    assert roundtrip.json_roundtrip_preserved(observation, True) == []
    observation["loaded"]["workout"]["core"]["reps"] = "999"
    assert roundtrip.json_roundtrip_preserved(observation, True)
    observation["loaded"]["workout"] = deepcopy(workout)
    observation["loaded"]["athlete"]["position"] = "synthetic-other-position"
    assert roundtrip.json_roundtrip_preserved(observation, True)


def test_text_check_passes_generated_export(case, workout):
    observation = roundtrip.observe_roundtrip(case, workout)
    assert roundtrip.text_prescriptions_preserved(observation, True) == []


@pytest.mark.parametrize("change", ["rep", "set", "remove", "reorder", "warmup"])
def test_text_check_detects_changed_prescription(case, workout, change):
    observation = roundtrip.observe_roundtrip(case, workout)
    text = observation["text"]
    if change == "rep":
        text = text.replace("| Reps: ", "| Reps: 999", 1)
    elif change == "set":
        text = text.replace("Sets: ", "Sets: 999", 1)
    elif change == "remove":
        lines = text.splitlines()
        start = next(index for index, line in enumerate(lines) if line.startswith("- Lower:"))
        del lines[start:start + 3]
        text = "\n".join(lines)
    elif change == "reorder":
        lines = text.splitlines()
        start = next(index for index, line in enumerate(lines) if line.startswith("- Lower:"))
        lines[start:start + 6] = lines[start + 3:start + 6] + lines[start:start + 3]
        text = "\n".join(lines)
    else:
        text = text.replace("- " + workout["warmup"][0] + "\n", "", 1)
    observation["text"] = text
    assert roundtrip.text_prescriptions_preserved(observation, True)


def test_split_day_export_records_typeerror(case):
    case["athlete"]["days_per_week"] = 4
    workout = work_gen.generate_workout(case["athlete"], history=[], day_index=0)
    observation = roundtrip.observe_roundtrip(case, workout)
    assert roundtrip.json_roundtrip_preserved(observation, True) == []
    assert observation["format_error"] == "TypeError: 'NoneType' object is not subscriptable"
    assert roundtrip.text_prescriptions_preserved(observation, True)


def test_unexpected_formatter_exception_is_not_known(monkeypatch, case, workout):
    def fail(*args):
        raise KeyError("unexpected-field")
    monkeypatch.setattr(work_gen, "format_workout_text", fail)
    with pytest.raises(KeyError, match="unexpected-field"):
        roundtrip.observe_roundtrip(case, workout)


def test_unrelated_typeerror_is_not_known(monkeypatch, case, workout):
    def fail(*args):
        raise TypeError("unexpected-type")
    monkeypatch.setattr(work_gen, "format_workout_text", fail)
    with pytest.raises(TypeError, match="unexpected-type"):
        roundtrip.observe_roundtrip(case, workout)


def test_same_typeerror_outside_null_main_block_is_not_known(monkeypatch, case, workout):
    workout["main_lift_lower"] = None
    def fail(*args):
        raise TypeError("'NoneType' object is not subscriptable")
    monkeypatch.setattr(work_gen, "format_workout_text", fail)
    with pytest.raises(TypeError):
        roundtrip.observe_roundtrip(case, workout)


def test_json_output_directory_is_temporary(monkeypatch, case, workout):
    source_path = work_gen.__file__
    saved = []
    real_save = work_gen.save_workout_to_json
    def observe_path(*args):
        saved.append(real_save(*args))
        return saved[-1]
    monkeypatch.setattr(work_gen, "save_workout_to_json", observe_path)
    roundtrip.observe_roundtrip(case, workout)
    assert work_gen.__file__ == source_path
    assert saved[0].parent.name == "workouts"
    assert saved[0].parent.parent.name.startswith("workout-eval-json-")
    assert not saved[0].parent.exists()


def test_flask_save_and_log_edit_are_isolated(monkeypatch, capsys, case, workout):
    import os
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic.invalid/must-not-connect")
    monkeypatch.setenv("WORKOUT_GENERATOR_DB_URL", "postgresql://synthetic.invalid/must-not-connect")
    case["scenario"] = {"kind": "flask_roundtrip", "edit": {
        "date": "2026-10-27", "weight": 55.0, "reps": 7,
    }}
    library = work_gen.EXERCISE_LIBRARY
    observation = roundtrip.observe_flask_roundtrip(case, workout)
    assert roundtrip.flask_workout_preserved(observation, True) == []
    assert roundtrip.completed_log_edit_preserved(observation, True) == []
    assert roundtrip.text_prescriptions_preserved(observation, True) == []
    assert observation["completed_log"] == case["scenario"]["edit"]
    assert work_gen.EXERCISE_LIBRARY is library
    assert os.environ["DATABASE_URL"] == "postgresql://synthetic.invalid/must-not-connect"
    assert os.environ["WORKOUT_GENERATOR_DB_URL"] == "postgresql://synthetic.invalid/must-not-connect"
    assert capsys.readouterr().out == ""
    observation["after_edit_workout"]["core"]["sets"] = 999
    assert roundtrip.flask_workout_preserved(observation, True)
    observation["completed_log"]["reps"] = 999
    assert roundtrip.completed_log_edit_preserved(observation, True)


def test_failed_log_edit_is_a_violation():
    observation = {"edit_status": 500, "edit_location": None,
                   "completed_log": {}, "expected_completed_log": {"reps": 7}}
    assert len(roundtrip.completed_log_edit_preserved(observation, True)) == 2


def test_checks_are_pure(case, workout):
    observation = roundtrip.observe_roundtrip(case, workout)
    original = deepcopy(observation)
    roundtrip.json_roundtrip_preserved(observation, True)
    roundtrip.text_prescriptions_preserved(observation, True)
    assert observation == original
    observation = {"original": {"workout": workout}, "stored_workout": workout,
                   "after_edit_workout": workout, "edit_status": 302,
                   "edit_location": "/history", "completed_log": {"reps": 7},
                   "expected_completed_log": {"reps": 7}}
    original = deepcopy(observation)
    roundtrip.flask_workout_preserved(observation, True)
    roundtrip.completed_log_edit_preserved(observation, True)
    assert observation == original
