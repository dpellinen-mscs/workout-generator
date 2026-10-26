from copy import deepcopy
import json

import pytest

from eval.tools.injury import CATALOG_PATH, no_excluded_exercises, observe_injury, resolve_exclusions


def observation(exercise_id="allowed"):
    return {"injury_profile": "knee", "excluded_exercise_ids": ["forbidden"],
            "injury_exercises": [{"id": exercise_id, "name": "Synthetic exercise"}]}


def test_no_excluded_exercises_passes_and_fails_by_id():
    assert no_excluded_exercises(observation(), "knee") == []
    assert no_excluded_exercises(observation("forbidden"), "knee")
    assert no_excluded_exercises(observation(), "back")
    assert no_excluded_exercises(observation(None), "knee")
    missing = observation()
    missing["excluded_exercise_ids"] = []
    assert no_excluded_exercises(missing, "knee")
    missing = observation()
    missing["injury_exercises"] = []
    assert no_excluded_exercises(missing, "knee")


def test_no_excluded_exercises_is_pure():
    data = observation("forbidden")
    before = deepcopy(data)
    no_excluded_exercises(data, "knee")
    assert data == before


def test_resolve_exclusions_uses_metadata_and_reviewed_ids():
    library = {"synthetic": [
        {"id": "a", "name": "Arbitrary A", "pattern": "squat", "movement_family": "general"},
        {"id": "b", "name": "Arbitrary B", "pattern": "hinge", "movement_family": "deadlift"},
        {"id": "c", "name": "Arbitrary C", "pattern": "push", "movement_family": "general"},
        {"id": "d", "name": "overhead", "pattern": "pull", "movement_family": "general"},
    ]}
    profile = {"patterns": ["squat"], "movement_families": ["deadlift"],
               "reviewed_ids": [{"id": "c", "pattern": "push", "movement_family": "general"}]}
    original = deepcopy((library, profile))
    assert resolve_exclusions(library, profile) == ["a", "b", "c"]
    assert (library, profile) == original
    for exercise in library["synthetic"]:
        exercise["name"] = "Another arbitrary label"
    assert resolve_exclusions(library, profile) == ["a", "b", "c"]


def test_resolve_exclusions_rejects_stale_or_empty_catalog():
    profile = {"patterns": [], "movement_families": [], "reviewed_ids": []}
    with pytest.raises(ValueError, match="no exercise IDs"):
        resolve_exclusions({}, profile)
    profile["reviewed_ids"] = [{"id": "missing", "pattern": "push", "movement_family": "general"}]
    with pytest.raises(ValueError, match="absent"):
        resolve_exclusions({}, profile)
    library = {"synthetic": [{"id": "missing", "pattern": "pull", "movement_family": "general"}]}
    with pytest.raises(ValueError, match="metadata changed"):
        resolve_exclusions(library, profile)


def test_catalog_has_five_explicit_profiles():
    catalog = json.loads(CATALOG_PATH.read_text())
    assert set(catalog["profiles"]) == {"shoulder", "elbow", "knee", "back", "hip"}
    for profile in catalog["profiles"].values():
        assert profile["constraint"]
        assert profile["patterns"] or profile["movement_families"] or profile["reviewed_ids"]


def test_direct_filter_observation_records_actual_survivors(monkeypatch, tmp_path):
    from eval.tools import injury
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"profiles": {"knee": {
        "patterns": ["squat"], "movement_families": [], "reviewed_ids": []}}}))
    monkeypatch.setattr(injury, "CATALOG_PATH", catalog)
    forbidden = {"id": "forbidden", "pattern": "squat", "name": "Synthetic excluded"}
    allowed = {"id": "allowed", "pattern": "hinge", "name": "Synthetic allowed"}
    case = {"athlete": {"injuries": ["knee"]}, "expect": {"no_excluded_exercises": "knee"},
            "scenario": {"kind": "injury_filter", "categories": ["synthetic"]}}
    calls = []
    def synthetic_filter(options, injuries):
        calls.append((options, injuries))
        return [allowed]
    observed = observe_injury(case, {}, {"synthetic": [forbidden, allowed]}, synthetic_filter)
    assert calls == [([forbidden, allowed], ["knee"])]
    assert observed["injury_exercises"] == [allowed]
    assert no_excluded_exercises(observed, "knee") == []
    case["scenario"]["categories"] = ["unrelated"]
    with pytest.raises(ValueError, match="contains no excluded"):
        observe_injury(case, {}, {"synthetic": [forbidden], "unrelated": [allowed]}, synthetic_filter)
