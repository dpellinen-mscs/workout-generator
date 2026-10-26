"""Observe isolated library faults without changing the source library."""

from copy import deepcopy
import re
from unittest.mock import patch


REQUIRED_KEYS = ("name", "pattern", "muscle_mass", "unilateral", "id", "movement_family", "equipment")


def _entry(library, category, exercise_id):
    matches = [item for item in library[category] if item.get("id") == exercise_id]
    if len(matches) != 1:
        raise ValueError(f"Fixture must select one {category} entry with id {exercise_id!r}")
    return matches[0]


def _mutate(library, mutation):
    """Return fixture evidence and its expected problem, independently of output."""
    action = mutation["action"]
    category = mutation.get("category")
    summary = {"action": action}
    if action == "control":
        return summary, []
    summary["category"] = category
    if action == "empty_category":
        summary["before_count"] = len(library[category])
        library[category] = []
        summary["after_count"] = 0
        return summary, [{"kind": "empty", "category": category}]
    target = _entry(library, category, mutation["exercise_id"])
    summary["before"] = deepcopy(target)
    if action == "remove_key":
        key = mutation["key"]
        del target[key]
        problem = {"kind": "missing_key", "category": category, "key": key,
                   "exercise_id": mutation["exercise_id"]}
    elif action == "duplicate_id":
        source = _entry(library, mutation["source_category"], mutation["source_id"])
        target["id"] = source["id"]
        summary["source"] = {"category": mutation["source_category"], **deepcopy(source)}
        problem = {"kind": "duplicate_id", "category": category,
                   "source_category": mutation["source_category"], "id": source["id"]}
    else:
        raise ValueError(f"Unknown library fixture action: {action!r}")
    summary["after"] = deepcopy(target)
    return summary, [problem]


def observe_library(case, generate):
    """Call the supplied generator with a temporary deep copy of the library.

    The caller must supply explicit synthetic history through its callback.
    Only actionable ValueError and the confirmed missing-name lookup are recorded.
    All other generator errors propagate and fail the eval runner.
    """
    import work_gen

    library = deepcopy(work_gen.EXERCISE_LIBRARY)
    summary, problems = _mutate(library, case["scenario"]["library"])
    observation = {"library_mutation": summary, "library_problems": problems,
                   "category_sizes": {key: len(value) for key, value in library.items()},
                   "workout": None, "rejection": None}
    if case["scenario"]["library"]["action"] == "control":
        observation["catalog_entries"] = [
            {"category": category, "exercise": deepcopy(exercise)}
            for category, entries in library.items() if category != "warmup"
            for exercise in entries
        ]
    with patch.object(work_gen, "EXERCISE_LIBRARY", library):
        try:
            observation["workout"] = generate(case["day_index"])
        except (ValueError, KeyError) as exc:
            clear = isinstance(exc, ValueError) and bool(problems) and all(
                _message_identifies_problem(str(exc), problem) for problem in problems
            )
            trace = exc.__traceback__
            while trace.tb_next:
                trace = trace.tb_next
            selected = trace.tb_frame.f_locals.get("ex")
            mutation = case["scenario"]["library"]
            known_name = (isinstance(exc, KeyError) and exc.args == ("name",)
                          and mutation["action"] == "remove_key" and mutation["key"] == "name"
                          and isinstance(selected, dict) and "name" not in selected
                          and selected.get("id") == mutation["exercise_id"])
            if not clear and not known_name:
                raise
            observation["rejection"] = {"type": type(exc).__name__, "message": str(exc)}
    return observation


def _message_identifies_problem(message, problem):
    value = message.lower()
    if not re.search(r"(?<!\w)" + re.escape(problem["category"].lower()) + r"(?!\w)", value):
        return False
    if problem["kind"] == "empty":
        return any(word in value for word in ("empty", "no available", "no exercises"))
    if problem["kind"] == "missing_key":
        return problem["key"].lower() in value and any(
            word in value for word in ("missing", "required", "absent")
        )
    if problem["kind"] == "duplicate_id":
        return problem["id"].lower() in value and any(
            word in value for word in ("duplicate", "collision", "not unique")
        )
    return False


def _usable_fallback(workout, problem):
    if not isinstance(workout, dict):
        return False
    slots = {"lower": "main_lift_lower", "upper_push": "main_lift_upper_push",
             "upper_pull": "main_lift_upper_pull", "core": "core"}
    category = problem["category"].removesuffix("_power")
    if category in slots and not workout.get(slots[category]):
        return False
    blocks = [workout[key] for key in slots.values() if workout.get(key)] + workout.get("accessories", [])
    if not blocks:
        return False
    ids = []
    for block in blocks:
        exercise = block.get("exercise", {})
        if any(key not in exercise for key in REQUIRED_KEYS) or not exercise["name"] or exercise["name"].startswith("["):
            return False
        if not exercise["equipment"] or "sets" not in block or "reps" not in block:
            return False
        ids.append(exercise["id"])
    return len(ids) == len(set(ids))


def library_problem_reported(observation, expected):
    """Require an actionable rejection or an explicit output warning.

    Placeholder exercise names and evaluator metadata do not report a
    generator problem. A bare KeyError does not identify a repair location.
    """
    if not expected:
        return []
    if not observation["library_problems"]:
        return ["No library problem was supplied"]
    rejection = observation.get("rejection")
    workout = observation.get("workout")
    warnings = workout.get("warnings", []) if isinstance(workout, dict) else []
    if isinstance(warnings, str):
        warnings = [warnings]
    violations = []
    for problem in observation["library_problems"]:
        rejected = (rejection is not None and rejection["type"] == "ValueError"
                    and _message_identifies_problem(rejection["message"], problem))
        warned = _usable_fallback(workout, problem) and any(
            isinstance(message, str) and _message_identifies_problem(message, problem)
            for message in warnings)
        if not rejected and not warned:
            detail = problem.get("key") or problem.get("id") or "empty category"
            violations.append(f"{problem['category']}: {detail} has no actionable generator report")
    return violations


def library_metadata_complete(observation, expected):
    """Check the intact control's catalog metadata and global id uniqueness."""
    if not expected:
        return []
    violations = []
    seen = {}
    for row in observation["catalog_entries"]:
        category, exercise = row["category"], row["exercise"]
        location = f"{category}/{exercise.get('name', '<unnamed>')}"
        for key in REQUIRED_KEYS:
            if key not in exercise:
                violations.append(f"{location}: missing {key}")
        exercise_id = exercise.get("id")
        if exercise_id is not None:
            if exercise_id in seen:
                violations.append(f"{location}: duplicate id {exercise_id!r}; first at {seen[exercise_id]}")
            seen[exercise_id] = location
    return violations


CHECKS = {
    "library_problem_reported": library_problem_reported,
    "library_metadata_complete": library_metadata_complete,
}
