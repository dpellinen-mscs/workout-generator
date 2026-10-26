"""Observe explicit injury scenarios without making clinical injury rules."""

import json
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalog" / "injury_exclusions.json"


def resolve_exclusions(library, profile):
    """Resolve metadata selectors and the catalog's reviewed ID exceptions."""
    entries = {exercise["id"]: exercise for group in library.values()
               for exercise in group if isinstance(exercise, dict) and exercise.get("id")}
    excluded = {exercise_id for exercise_id, exercise in entries.items()
                if exercise.get("pattern") in profile["patterns"]
                or exercise.get("movement_family") in profile["movement_families"]}
    for reviewed in profile["reviewed_ids"]:
        exercise = entries.get(reviewed["id"])
        if exercise is None:
            raise ValueError(f"Reviewed injury exclusion is absent: {reviewed['id']}")
        for key in ("pattern", "movement_family"):
            if exercise.get(key) != reviewed[key]:
                raise ValueError(f"Reviewed injury exclusion metadata changed: {reviewed['id']} {key}")
        excluded.add(reviewed["id"])
    if not excluded:
        raise ValueError("Injury profile resolves to no exercise IDs")
    return sorted(excluded)


def observe_injury(case, workout, library, injury_filter):
    """Attach the declared restriction and raw selected exercise metadata."""
    profile_name = case["expect"]["no_excluded_exercises"]
    catalog = json.loads(CATALOG_PATH.read_text())
    profile = catalog["profiles"][profile_name]
    excluded = resolve_exclusions(library, profile)
    scenario = case.get("scenario", {})
    if scenario.get("kind") == "injury_filter":
        options = [exercise for category in scenario["categories"]
                   for exercise in library[category]]
        if not set(excluded).intersection(exercise.get("id") for exercise in options):
            raise ValueError("Direct injury filter input contains no excluded exercise ID")
        selected = injury_filter(options, case["athlete"]["injuries"])
        scope = "direct injury filter"
    else:
        blocks = [workout[key] for key in (
            "main_lift_lower", "main_lift_upper_push", "main_lift_upper_pull", "core"
        ) if workout.get(key)] + workout.get("accessories", [])
        selected = [block["exercise"] for block in blocks]
        scope = "prescribed exercise blocks; warmup text has no movement metadata"
    return {"injury_profile": profile_name, "injury_scope": scope,
            "excluded_exercise_ids": excluded, "injury_exercises": selected}


def no_excluded_exercises(observation, profile_name):
    """Compare selected IDs with an already resolved explicit restriction."""
    if observation.get("injury_profile") != profile_name:
        return [f"Expected injury profile {profile_name!r} is absent"]
    excluded = set(observation.get("excluded_exercise_ids", []))
    if not excluded:
        return ["The injury exclusion list is empty"]
    exercises = observation.get("injury_exercises", [])
    if not exercises:
        return ["No exercises were observed for the injury check"]
    violations = []
    for exercise in exercises:
        exercise_id = exercise.get("id")
        if not exercise_id:
            violations.append(f"{exercise.get('name', 'Unnamed exercise')}: exercise ID absent")
        elif exercise_id in excluded:
            violations.append(f"{exercise_id}: {exercise.get('name', 'Unnamed exercise')} is excluded")
    return violations
