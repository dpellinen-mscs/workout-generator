from copy import deepcopy
import random

from eval.tools import score


def observation(equipment):
    return {"workout": {"warmup": [], "core": {"exercise": {
        "name": "Synthetic exercise", "equipment": equipment
    }}, "accessories": []}}


def test_equipment_check():
    assert score.all_exercises_use_only(observation(["dumbbell"]), ["dumbbell"]) == []
    assert score.all_exercises_use_only(observation(["barbell"]), ["dumbbell"])
    assert score.all_exercises_use_only(observation([]), ["dumbbell"])
    assert score.all_exercises_use_only(observation(None), ["dumbbell"])


def test_empty_category_check():
    data = {"category_sizes": {"upper_pull_power": 0, "lower": 2}}
    assert score.library_categories_nonempty(data, ["upper_pull_power"])
    assert score.library_categories_nonempty(data, ["lower"]) == []


def test_check_is_pure():
    data = observation(["barbell"])
    before = deepcopy(data)
    score.all_exercises_use_only(data, ["dumbbell"])
    assert data == before
    data = {"category_sizes": {"upper_pull_power": 0}}
    before = deepcopy(data)
    score.library_categories_nonempty(data, ["upper_pull_power"])
    assert data == before


def test_known_failure_and_regression_classification():
    case = {"id": "unit-001", "expect": {"all_exercises_use_only": ["dumbbell"]}}
    assert score.score_observation(case, observation(["barbell"]))["status"] == "fail"
    case["finding"] = "F-001"
    assert score.score_observation(case, observation(["barbell"]))["status"] == "known"
    assert score.score_observation(case, observation(["dumbbell"]))["status"] == "pass"


def test_seed_restores_random_state():
    before = random.getstate()
    with score.seeded(3):
        random.random()
    assert random.getstate() == before


def test_regression_on_passing_check_in_known_case():
    old = {"id": "unit-001", "checks": {"a": [], "b": ["known"]}, "error": None}
    new = {"id": "unit-001", "checks": {"a": ["drop"], "b": ["known"]}, "error": None}
    assert score.score_drops([new], [old]) == ["unit-001: a"]


def test_replay_requires_matching_inputs():
    import pytest
    cases = score.load_cases()
    record = score.make_record(cases)
    assert score.replay(cases, record)
    cases = deepcopy(cases)
    cases[0]["seed"] += 1
    with pytest.raises(ValueError, match="input hash"):
        score.replay(cases, record)
    record["source_sha256"] = {}
    with pytest.raises(ValueError, match="source hashes"):
        score.replay(cases, record)


def test_source_change_does_not_disable_regression_gate(monkeypatch, tmp_path):
    import json
    case = {"id": "unit-001", "expect": {"all_exercises_use_only": ["dumbbell"]}}
    old = score.score_observation(case, observation(["dumbbell"]))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"source_sha256": {"old": "source"}, "cases": [{"result": old}]}))
    monkeypatch.setattr(score, "BASELINE", baseline)
    monkeypatch.setattr(score, "load_cases", lambda: [case])
    monkeypatch.setattr(score, "observe", lambda case: observation(["barbell"]))
    assert score.main([]) == 1
    assert score.main(["--record", str(baseline)]) == 1
    assert json.loads(baseline.read_text())["cases"][0]["result"] == old
