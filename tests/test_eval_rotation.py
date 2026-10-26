from copy import deepcopy

from eval.tools import rotation as score
from eval.tools import score as runner


def _block(name):
    return {"exercise": {"name": name}}


def test_main_lifts_avoid_history():
    data = {"workout": {"main_lift_lower": _block("Synthetic squat")},
            "prior_main_names": {"lower": ["Synthetic hinge"]}}
    before = deepcopy(data)
    assert score.main_lifts_avoid_history(data, ["lower"]) == []
    assert data == before
    data["prior_main_names"]["lower"].append("Synthetic squat")
    assert score.main_lifts_avoid_history(data, ["lower"])
    data["workout"]["main_lift_lower"] = None
    assert score.main_lifts_avoid_history(data, ["lower"])


def test_accessory_pair_differs_from_previous():
    data = {"workout": {"accessories": [_block("Synthetic A"), _block("Synthetic B")]},
            "prior_accessory_pair": ["Synthetic C", "Synthetic D"]}
    before = deepcopy(data)
    assert score.accessory_pair_differs_from_previous(data, True) == []
    assert data == before
    data["prior_accessory_pair"] = ["Synthetic B", "Synthetic A"]
    assert score.accessory_pair_differs_from_previous(data, True)
    data["workout"]["accessories"] = []
    assert score.accessory_pair_differs_from_previous(data, True)
    data["prior_accessory_pair"] = []
    assert score.accessory_pair_differs_from_previous(data, True)


def test_repeated_run_equals():
    data = {"workout": {"accessories": [_block("Synthetic A")]},
            "repeated_workout": {"accessories": [_block("Synthetic A")]}}
    before = deepcopy(data)
    assert score.repeated_run_equals(data, True) == []
    assert data == before
    data["repeated_workout"]["accessories"][0]["exercise"]["name"] = "Synthetic B"
    assert score.repeated_run_equals(data, True)


def test_main_lift_names():
    data = {"workout": {"main_lift_lower": _block("Synthetic squat")}}
    before = deepcopy(data)
    assert score.main_lift_names(data, {"lower": "Synthetic squat"}) == []
    assert data == before
    assert score.main_lift_names(data, {"lower": "Synthetic hinge"})


def test_rotation_observation_uses_final_session_for_same_date():
    case = {"history": [
        {"date": "2026-10-25", "session_id": "synthetic-001", "category": "accessory", "exercise_name": "A"},
        {"date": "2026-10-25", "session_id": "synthetic-002", "category": "accessory", "exercise_name": "B"},
        {"date": "2026-10-25", "session_id": "synthetic-002", "category": "accessory", "exercise_name": "C"},
    ], "expect": {"accessory_pair_differs_from_previous": True}}
    data = score.observe_rotation(case, lambda _: {"accessories": []})
    assert data["prior_accessory_pair"] == ["B", "C"]


def test_rotation_replay_resets_seed_and_restores_random_state():
    import random
    case = next(case for case in runner.load_cases() if case["id"] == "rotation-005")
    before = random.getstate()
    first = runner.observe(case)
    assert first["workout"] == first["repeated_workout"]
    assert runner.observe(case) == first
    assert random.getstate() == before
