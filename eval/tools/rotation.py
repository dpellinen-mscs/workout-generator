"""Rotation checks and observation helpers for integration into score.py."""

MAIN_LIFT_SLOTS = {
    "lower": "main_lift_lower",
    "upper_push": "main_lift_upper_push",
    "upper_pull": "main_lift_upper_pull",
}


def main_lifts_avoid_history(observation, categories):
    """Reject a selected main lift used earlier in the supplied block."""
    violations = []
    for category in categories:
        block = observation["workout"].get(MAIN_LIFT_SLOTS[category])
        if not block:
            violations.append(f"{category}: main lift is absent")
        elif block["exercise"]["name"] in observation["prior_main_names"][category]:
            violations.append(f"{category}: repeated {block['exercise']['name']}")
    return violations


def accessory_pair_differs_from_previous(observation, required):
    """Compare the selected pair with the latest synthetic session pair."""
    if not required:
        return []
    names = [block["exercise"]["name"] for block in observation["workout"]["accessories"][:2]]
    previous = observation["prior_accessory_pair"]
    if not previous:
        return ["previous accessory pair is absent"]
    if len(names) != 2:
        return ["selected accessory pair must contain two exercises"]
    return [f"repeated accessory pair: {', '.join(names)}"] if sorted(names) == sorted(previous) else []


def repeated_run_equals(observation, required):
    """Require equal output when the same input and seed are replayed."""
    return ["same input and seed produced different output"] if required and observation["workout"] != observation["repeated_workout"] else []


def main_lift_names(observation, expected):
    """Require named main lifts at a configured rotation boundary."""
    violations = []
    for category, name in expected.items():
        block = observation["workout"].get(MAIN_LIFT_SLOTS[category])
        actual = block["exercise"]["name"] if block else None
        if actual != name:
            violations.append(f"{category}: expected {name}, got {actual}")
    return violations


def observe_rotation(case, generate):
    """Generate twice with the existing seed/date wrapper and preserve history evidence.

    The callable must reset the case seed on every call and pass case['history'].
    Each fixture history is the supplied rotation block. The final accessory
    session_id identifies the previous pair; row order resolves same-date ties.
    """
    history = case["history"]
    prior_main_names = {
        category: sorted({row["exercise_name"] for row in history
                          if row.get("category") == category})
        for category in MAIN_LIFT_SLOTS
    }
    accessory_rows = [row for row in history if row.get("category") == "accessory"]
    previous_session = accessory_rows[-1]["session_id"] if accessory_rows else None
    prior_accessory_pair = [row["exercise_name"] for row in accessory_rows
                            if row["session_id"] == previous_session]
    workout = generate(case)
    repeated = generate(case) if "repeated_run_equals" in case["expect"] else None
    return {"workout": workout, "prior_main_names": prior_main_names,
            "prior_accessory_pair": prior_accessory_pair, "repeated_workout": repeated}


ROTATION_CHECKS = {
    "main_lifts_avoid_history": main_lifts_avoid_history,
    "accessory_pair_differs_from_previous": accessory_pair_differs_from_previous,
    "repeated_run_equals": repeated_run_equals,
    "main_lift_names": main_lift_names,
}
