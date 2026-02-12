import work_gen


def test_time_based_detection():
    assert work_gen.is_time_based_exercise("Plank")
    assert work_gen.is_time_based_exercise("Farmer carry x 40 yards")
    assert not work_gen.is_time_based_exercise("Barbell bench press")


def test_trunk_prescription_modes():
    time_based = work_gen._trunk_prescription("Side plank", "heavy")
    assert time_based["reps"] == ""
    assert time_based["rest"] == "2–3 min"

    rotation = work_gen._trunk_prescription("High-to-low cable chop", "heavy")
    assert rotation["reps"] == "6–10"
    assert rotation["rest"] == "2–3 min"

    anti_rotation = work_gen._trunk_prescription("Pallof press", "heavy")
    assert anti_rotation["reps"] == "6–10"
    assert anti_rotation["rest"] == "2–3 min"

    loaded = work_gen._trunk_prescription("Cable crunch", "heavy")
    assert loaded["reps"] == "8–12"
    assert loaded["rest"] == "2–3 min"


def test_primary_exercise_filtering():
    assert not work_gen.is_primary_exercise({"name": "Hammer curl", "pattern": "pull", "muscle_mass": "small"})
    assert not work_gen.is_primary_exercise({"name": "Leg curl", "pattern": "knee_flexion", "muscle_mass": "medium"})
    assert not work_gen.is_primary_exercise({"name": "Lateral raise", "pattern": "push", "muscle_mass": "small"})
    assert work_gen.is_primary_exercise({"name": "Barbell bench press", "pattern": "push", "muscle_mass": "large"})
