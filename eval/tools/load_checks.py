"""Pure checks and raw observations for the configured load constraints."""

from collections import Counter
import json
from pathlib import Path


def prescribed_load_scores(workouts, style):
    loads = []
    for workout in workouts:
        blocks = [workout[key] for key in (
            "main_lift_lower", "main_lift_upper_push", "main_lift_upper_pull", "core"
        ) if workout.get(key)] + workout.get("accessories", [])
        loads.append(sum(style["intensity_scale"][block["intensity"]]
                         * style["muscle_mass_scale"][block["exercise"]["muscle_mass"]]
                         for block in blocks))
    return loads


def history_load_equals(observation, expected):
    actual = observation["history_caps"]["total_load"]
    return [] if actual == expected else [f"Expected history load {expected}; observed {actual}"]


def session_load_scores_match(observation, expected):
    return [f"Session {index}: reported load {reported} differs from block sum {computed}"
            for index, (reported, computed) in enumerate(zip(
                observation["reported_session_loads"], observation["session_loads"]))
            if reported != computed]


def weekly_load_within_cap(observation, cap):
    total = observation["weekly_load"]
    return [f"Weekly load {total} exceeds configured cap {cap}"] if total > cap else []


def pattern_counts_within_caps(observation, caps):
    counts = observation["pattern_counts"]
    return [f"{pattern}: {counts.get(pattern, 0)} exceeds configured cap {cap}"
            for pattern, cap in sorted(caps.items()) if counts.get(pattern, 0) > cap]


def warnings_include(observation, expected):
    return [f"Missing warning: {message}" for message in expected
            if message not in observation["warnings"]]


def no_warnings(observation, expected):
    return [f"Unexpected warnings: {observation['warnings']}"
            ] if expected and observation["warnings"] else []


LOAD_CHECKS = {
    "session_load_scores_match": session_load_scores_match,
    "weekly_load_within_cap": weekly_load_within_cap,
    "history_load_equals": history_load_equals,
    "pattern_counts_within_caps": pattern_counts_within_caps,
    "warnings_include": warnings_include,
    "no_warnings": no_warnings,
}


def prescribed_pattern_counts(workouts):
    """Count literal prescribed exercises, independent of engine cap aggregates."""
    counts = Counter()
    for workout in workouts:
        blocks = [workout[key] for key in (
            "main_lift_lower", "main_lift_upper_push", "main_lift_upper_pull", "core"
        ) if workout.get(key)] + workout.get("accessories", [])
        for block in blocks:
            pattern = block["exercise"].get("pattern", "unknown")
            counts["core" if pattern == "carry" else pattern] += 1
    return dict(counts)


def observe_caps(case, work_gen, generate):
    """Accept a generate(day_index) callback with the case seed/date reset per call.

    Run this helper while work_gen.datetime is patched to the audit date. The
    callback must always supply case['history']; it must not read a history file.
    """
    scenario = case["scenario"]
    kind = scenario["kind"]
    if kind == "caps_week":
        workouts = [generate(index) for index in range(case["athlete"]["days_per_week"])]
        reported = [workout["total_load_score"] for workout in workouts]
        style = json.loads((Path(__file__).resolve().parents[2] / "coaching_style.json").read_text())
        loads = prescribed_load_scores(workouts, style)
        return {"workout": workouts[case["day_index"]], "workouts": workouts,
                "reported_session_loads": reported,
                "session_loads": loads, "weekly_load": sum(loads),
                "pattern_counts": prescribed_pattern_counts(workouts)}
    if kind == "caps_warning":
        total = scenario["total_load"]
        counts = scenario["pattern_counts"]
        return {"weekly_load": total, "pattern_counts": counts,
                "warnings": work_gen._weekly_warnings(case["athlete"]["phase"], total, counts)}
    if kind == "caps_history":
        # A zero-load synthetic current workout isolates history warning behavior.
        workout = scenario["workout"]
        result = work_gen.compute_history_caps_from_history(
            case["history"], case["athlete"]["phase"], workout, days=7,
        )
        return {"workout": workout, "history_caps": result,
                "weekly_load": result["total_load"],
                "pattern_counts": result["pattern_counts"], "warnings": result["warnings"]}
    raise ValueError(f"Unknown load scenario: {kind}")
