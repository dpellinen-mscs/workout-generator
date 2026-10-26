import json

import pytest

from eval.tools import validate_corpus as validation


@pytest.fixture(autouse=True)
def known_checks(monkeypatch):
    monkeypatch.setattr(validation, "_known_checks", lambda: {"all_exercises_use_only", "library_categories_nonempty"})


@pytest.fixture
def case():
    return {
        "id": "equip-001",
        "tags": ["equipment"],
        "athlete": {"position": "RHP", "goal": "power", "phase": "offseason", "days_per_week": 3, "injuries": [], "equipment": ["dumbbell", "bodyweight"]},
        "history": [],
        "day_index": 0,
        "expect": {"all_exercises_use_only": ["dumbbell", "bodyweight"]},
        "finding": "F-001",
    }


def write_cases(tmp_path, cases, filename="equipment.json"):
    (tmp_path / filename).write_text(json.dumps({"format_version": 1, "cases": cases}), encoding="utf-8")


def test_valid_corpus_loads_without_mutation(tmp_path, case):
    case.update(seed=7, focus={"overall_focus": "balanced_priority"}, scenario={"kind": "single"})
    write_cases(tmp_path, [case])
    assert validation.validate_corpus(tmp_path) == []
    assert validation.load_cases(tmp_path) == [case]


def test_malformed_json_reports_path(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    errors = validation.validate_corpus(tmp_path)
    assert any(str(path) in error and "cannot read JSON" in error for error in errors)


def test_history_is_required(tmp_path, case):
    del case["history"]
    write_cases(tmp_path, [case])
    assert any("missing required field 'history'" in error for error in validation.validate_corpus(tmp_path))


def test_duplicate_ids_across_files_are_rejected(tmp_path, case):
    write_cases(tmp_path, [case], "a.json")
    write_cases(tmp_path, [case], "b.json")
    assert any("duplicate case id 'equip-001'" in error for error in validation.validate_corpus(tmp_path))


def test_unknown_scorer_check_is_rejected(tmp_path, case):
    case["expect"] = {"unimplemented_check": True}
    write_cases(tmp_path, [case])
    assert any("unknown scorer check 'unimplemented_check'" in error for error in validation.validate_corpus(tmp_path))


@pytest.mark.parametrize("field,value,error_fragment", [
    ("day_index", True, "day_index: expected integer"),
    ("day_index", -1, "day_index: must be at least 0"),
    ("finding", "F-1", "finding: must match"),
    ("id", "Has spaces", "id: must match"),
    ("typo", 0, "unknown field 'typo'"),
    ("expect", {}, "expect: needs at least 1 field"),
    ("expect", {"library_categories_nonempty": True}, "library_categories_nonempty: expected array"),
    ("expect", {"all_exercises_use_only": ["teleporter"]}, "must be one of"),
])
def test_invalid_case_fields_are_rejected(tmp_path, case, field, value, error_fragment):
    case[field] = value
    write_cases(tmp_path, [case])
    assert any(error_fragment in error for error in validation.validate_corpus(tmp_path))


def test_load_rejects_invalid_corpus(tmp_path, case):
    del case["athlete"]["injuries"]
    write_cases(tmp_path, [case])
    with pytest.raises(ValueError, match="missing required field 'injuries'"):
        validation.load_cases(tmp_path)


def test_no_case_files_is_an_error(tmp_path):
    assert any("no JSON case files" in error for error in validation.validate_corpus(tmp_path))


def test_cli_returns_nonzero_for_invalid_corpus(tmp_path, capsys):
    assert validation.main(["--cases-dir", str(tmp_path)]) == 1
    assert "no JSON case files" in capsys.readouterr().err
