from copy import deepcopy
import json
from pathlib import Path

import pytest
import work_gen

from eval.tools.tag_equipment import EQUIPMENT, equipment_for_name, tag_library

ROOT = Path(__file__).resolve().parents[1]


def test_all_entries_have_reviewed_equipment():
    library = json.loads((ROOT / "exercise_library.json").read_text())
    before = deepcopy(library)
    assert tag_library(library) == library
    assert library == before
    assert sum(map(len, library.values())) == 80
    for entries in library.values():
        for entry in entries:
            assert entry["equipment"]
            assert set(entry["equipment"]) <= set(EQUIPMENT)
    reviewed = json.loads((ROOT / "eval/catalog/equipment_manual_review.json").read_text())["entries"]
    assert len(reviewed) == 20
    by_name = {entry["name"]: entry for entries in library.values() for entry in entries}
    for entry in reviewed:
        assert by_name[entry["name"]]["equipment"] == entry["equipment"]
        assert entry["rationale"]


def test_warmup_text_survives_metadata_conversion():
    athlete = {"position": "RHP", "goal": "power", "phase": "offseason", "injuries": []}
    workout = work_gen.generate_workout(athlete, history=[], day_index=0)
    assert workout["warmup"] == [entry["name"] for entry in work_gen.EXERCISE_LIBRARY["warmup"]]
    assert all(isinstance(entry, str) for entry in workout["warmup"])


def test_tagger_wraps_strings_without_mutation():
    library = {"warmup": ["Plank"], "lower": [{"name": "Trap bar deadlift"}]}
    before = deepcopy(library)
    tagged = tag_library(library)
    assert library == before
    assert tagged["warmup"][0] == {"name": "Plank", "equipment": ["bodyweight"]}
    assert tagged["lower"][0]["equipment"] == ["other"]


def test_tagger_requires_review_for_unknown_name():
    with pytest.raises(ValueError, match="No equipment rule"):
        equipment_for_name("Synthetic unknown exercise")
