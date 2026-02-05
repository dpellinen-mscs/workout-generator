"""
Workout Generator v1
- No APIs
- No database
- Just: athlete profile -> simple logic -> printed workout
"""

import json
import hashlib
import random
from datetime import datetime, timedelta
from pathlib import Path


# -----------------------------
# 1) Athlete profile (defaults)
# -----------------------------
DEFAULT_ATHLETE = {
    "age": 24,
    "position": "outfielder",
    "injuries": [],   # examples: ["shoulder"], ["knee"], [], ["back"]
    "goal": "power",  # examples: "power", "speed", "hypertrophy", "general"
    "phase": "offseason",  # examples: "offseason", "inseason"
}


# -----------------------------
# 2) Tiny exercise library (v1)
# -----------------------------
EXERCISE_LIBRARY_PATH = Path(__file__).parent / "exercise_library.json"
EXERCISE_LIBRARY = json.loads(EXERCISE_LIBRARY_PATH.read_text())


STYLE_PATH = Path(__file__).parent / "coaching_style.json"
STYLE = json.loads(STYLE_PATH.read_text())
PRESCRIPTIONS = STYLE["prescriptions"]
CORE_PRESCRIPTION = STYLE["core_prescription"]
ACCESSORY_PRESCRIPTION = STYLE["accessory_prescription"]
MUSCLE_MASS_SCALE = STYLE["muscle_mass_scale"]
INTENSITY_SCALE = STYLE["intensity_scale"]
PHASE_INTENSITY = STYLE["phase_intensity"]
PROGRESSION = STYLE["progression"]
ROTATION = STYLE["rotation"]
ACCESSORY_PAIRS = STYLE["accessory_pairs"]
WEEKLY_LOAD_CAPS = STYLE["weekly_load_caps"]
PATTERN_CAPS = STYLE["pattern_caps"]
TIME_BASED_KEYWORDS = [
    "plank",
    "side bridge",
    "farmer carry",
    "farmers carry",
    "farmer's carry",
]

# -----------------------------
# 3) Simple “filters” (v1 logic)
# -----------------------------
def filter_exercises_for_injuries(options: list[dict], injuries: list[str]) -> list[dict]:
    """
    V1: super simple safety rule.
    If shoulder injury: avoid overhead-ish press and heavy vertical pulling.
    This is not perfect, it's just a starter logic example.
    """
    if not injuries:
        return options

    filtered = options[:]

    if "shoulder" in injuries:
        # remove anything that might aggravate shoulder in this tiny list
        banned_keywords = ["overhead", "landmine press", "incline dumbbell press", "lat pulldown"]
        filtered = [
            ex for ex in filtered
            if not any(bad.lower() in ex["name"].lower() for bad in banned_keywords)
        ]

    return filtered


def get_prescription(goal: str) -> dict:
    return PRESCRIPTIONS.get(goal, PRESCRIPTIONS["general"])

def get_phase_intensity(phase: str) -> str:
    return PHASE_INTENSITY.get(phase, "moderate")


def compute_load_score(intensity: str, exercise: dict) -> int:
    intensity_score = INTENSITY_SCALE.get(intensity, 2)
    muscle_score = MUSCLE_MASS_SCALE.get(exercise.get("muscle_mass", "medium"), 3)
    return intensity_score * muscle_score


def is_time_based_exercise(name: str | None) -> bool:
    if not name:
        return False
    value = name.lower()
    return any(keyword in value for keyword in TIME_BASED_KEYWORDS)

# -----------------------------
# 3.5) Input helpers (v1.1)
# -----------------------------
def _input_with_default(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else default


def _parse_injuries(raw: str) -> list[str]:
    if not raw:
        return []
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def collect_athlete_from_input(defaults: dict) -> dict:
    print("\nEnter athlete info (press Enter to keep defaults).")

    age_raw = _input_with_default("Age", str(defaults["age"]))
    try:
        age = int(age_raw)
    except ValueError:
        age = defaults["age"]

    position = _input_with_default("Position", defaults["position"]).lower()
    goal = _input_with_default("Goal (power/speed/hypertrophy/general)", defaults["goal"]).lower()
    phase = _input_with_default("Phase (offseason/inseason)", defaults["phase"]).lower()

    injuries_raw = input("Injuries (comma-separated, or blank for none): ").strip()
    injuries = _parse_injuries(injuries_raw) if injuries_raw else defaults["injuries"]

    return {
        "age": age,
        "position": position,
        "injuries": injuries,
        "goal": goal,
        "phase": phase,
    }

# -----------------------------
# 4) Workout generator (v1)
# -----------------------------
def load_history() -> list[dict]:
    history_path = Path(__file__).parent / "workouts" / "history.jsonl"
    if not history_path.exists():
        return []
    entries = []
    for line in history_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _last_used_map(history: list[dict]) -> dict:
    last_used = {}
    for entry in history:
        name = entry.get("exercise_name")
        date = entry.get("date")
        if not name or not date:
            continue
        # Keep the most recent date string (ISO, lexicographically sortable)
        if name not in last_used or date > last_used[name]:
            last_used[name] = date
    return last_used


def _history_for_category(history: list[dict], category_name: str) -> list[dict]:
    rows = [h for h in history if h.get("category") == category_name]
    rows.sort(key=lambda r: r.get("date", ""))
    return rows


def _rotation_choice(category_name: str, options: list[dict], history: list[dict]) -> dict | None:
    order = ROTATION["order"].get(category_name, [])
    if not order:
        return None

    history_rows = _history_for_category(history, category_name)
    if not history_rows:
        target_name = order[0]
    else:
        # Count consecutive uses of the last exercise
        last_name = history_rows[-1].get("exercise_name")
        consecutive = 0
        for row in reversed(history_rows):
            if row.get("exercise_name") == last_name:
                consecutive += 1
            else:
                break

        if consecutive >= ROTATION["block_length"]:
            if last_name in order:
                idx = order.index(last_name)
                target_name = order[(idx + 1) % len(order)]
            else:
                target_name = order[0]
        else:
            target_name = last_name

    for ex in options:
        if ex["name"] == target_name:
            return ex
    return None


def pick_one(category_name: str, options: list[dict], history: list[dict]) -> dict:
    if not options:
        return {"name": f"[No available exercises in '{category_name}' after filtering]"}
    rotation_pick = _rotation_choice(category_name, options, history)
    if rotation_pick:
        return rotation_pick

    last_used = _last_used_map(history)
    scored = []
    for ex in options:
        score = last_used.get(ex["name"], "")
        scored.append((score, ex))
    scored.sort(key=lambda t: t[0])
    oldest_score = scored[0][0]
    oldest = [ex for score, ex in scored if score == oldest_score]
    return random.choice(oldest)


def pick_accessory_pair(history: list[dict]) -> list[dict]:
    if not ACCESSORY_PAIRS:
        return []
    name_to_ex = {}
    for group in ["upper_push", "upper_pull", "lower", "core"]:
        for ex in EXERCISE_LIBRARY.get(group, []):
            name_to_ex[ex["name"]] = ex
    last_used = _last_used_map(history)

    scored_pairs = []
    for pair in ACCESSORY_PAIRS:
        # Use the oldest last-used among the pair (empty string means never used)
        dates = [last_used.get(name, "") for name in pair]
        score = min(dates) if dates else ""
        scored_pairs.append((score, pair))
    scored_pairs.sort(key=lambda t: t[0])
    best_score = scored_pairs[0][0]
    candidates = [pair for score, pair in scored_pairs if score == best_score]
    chosen = random.choice(candidates)

    exercises = []
    for name in chosen:
        ex = name_to_ex.get(name, {"name": name, "pattern": "unknown", "muscle_mass": "small"})
        exercises.append(ex)
    return exercises


def _exercise_history(history: list[dict], exercise_name: str) -> list[dict]:
    rows = [h for h in history if h.get("exercise_name") == exercise_name]
    rows.sort(key=lambda r: r.get("date", ""))
    return rows


def suggest_weight(history: list[dict], exercise_name: str) -> float | None:
    rows = _exercise_history(history, exercise_name)
    if not rows:
        return None
    lookback = PROGRESSION["lookback_sessions"]
    rows = rows[-lookback:]
    weights = [r.get("weight") for r in rows if isinstance(r.get("weight"), (int, float))]
    if not weights:
        return None

    if len(weights) >= 2 and weights[-1] > weights[-2]:
        # Improved last session; check required streak
        if len(weights) >= PROGRESSION["require_improve_sessions"]:
            improved = all(
                weights[-i] > weights[-i - 1]
                for i in range(1, PROGRESSION["require_improve_sessions"])
            )
            if improved:
                return round(weights[-1] * (1 + PROGRESSION["increase_pct"] / 100), 1)

    if len(weights) >= 2 and weights[-1] < weights[-2]:
        return round(weights[-1] * (1 - PROGRESSION["decrease_pct"] / 100), 1)

    return float(weights[-1])


def _power_category_name(base_category: str) -> str:
    return f"{base_category}_power"


def _focus_for_category(focus: str | dict | None, base_category: str) -> str | None:
    if isinstance(focus, dict):
        if base_category in ["upper_push", "upper_pull"]:
            return focus.get("upper_focus")
        if base_category == "lower":
            return focus.get("lower_focus")
        if base_category == "core":
            return focus.get("core_focus") or focus.get("overall_focus")
        return focus.get("overall_focus")
    return focus


def _pick_main_exercise(
    base_category: str,
    base_options: list[dict],
    history: list[dict],
    focus: str | dict | None,
    power_options: list[dict] | None = None,
) -> dict:
    category_focus = _focus_for_category(focus, base_category)
    power_category = _power_category_name(base_category)
    power_options = power_options if power_options is not None else EXERCISE_LIBRARY.get(power_category, [])

    if category_focus == "power_speed_priority" and power_options:
        if random.random() < 0.7:
            return pick_one(power_category, power_options, history)
    elif category_focus == "balanced_priority" and power_options:
        if random.random() < 0.35:
            return pick_one(power_category, power_options, history)

    return pick_one(base_category, base_options, history)


def generate_workout(athlete: dict, history: list[dict] | None = None, focus: str | dict | None = None) -> dict:
    prescription = get_prescription(athlete.get("goal", "general"))
    injuries = athlete.get("injuries", [])
    phase_intensity = get_phase_intensity(athlete.get("phase", "offseason"))
    history = history if history is not None else load_history()

    # Filter upper options based on injuries (v1 minimal logic)
    upper_push_options = filter_exercises_for_injuries(EXERCISE_LIBRARY["upper_push"], injuries)
    upper_pull_options = filter_exercises_for_injuries(EXERCISE_LIBRARY["upper_pull"], injuries)
    upper_push_power_options = filter_exercises_for_injuries(EXERCISE_LIBRARY.get("upper_push_power", []), injuries)
    upper_pull_power_options = filter_exercises_for_injuries(EXERCISE_LIBRARY.get("upper_pull_power", []), injuries)

    lower_exercise = _pick_main_exercise(
        "lower",
        EXERCISE_LIBRARY["lower"],
        history,
        focus,
        EXERCISE_LIBRARY.get("lower_power", []),
    )
    lower_is_unilateral = lower_exercise.get("unilateral", False)

    # Maintain unilateral/bilateral balance across the session:
    # always try to include exactly one unilateral upper-body movement if possible.
    def _split_unilateral(options: list[dict]) -> tuple[list[dict], list[dict]]:
        unilateral = [ex for ex in options if ex.get("unilateral")]
        bilateral = [ex for ex in options if not ex.get("unilateral")]
        return unilateral, bilateral

    upper_push_uni, upper_push_bi = _split_unilateral(upper_push_options)
    upper_pull_uni, upper_pull_bi = _split_unilateral(upper_pull_options)
    upper_push_power_uni, upper_push_power_bi = _split_unilateral(upper_push_power_options)
    upper_pull_power_uni, upper_pull_power_bi = _split_unilateral(upper_pull_power_options)

    unilateral_slot = None
    if upper_push_uni and upper_pull_uni:
        unilateral_slot = random.choice(["push", "pull"])
    elif upper_push_uni:
        unilateral_slot = "push"
    elif upper_pull_uni:
        unilateral_slot = "pull"

    workout = {
        "warmup": EXERCISE_LIBRARY["warmup"],
        "main_lift_lower": {
            "exercise": lower_exercise,
            "intensity": phase_intensity,
            **prescription,
        },
        "main_lift_upper_push": {
            "exercise": _pick_main_exercise(
                "upper_push",
                upper_push_uni if unilateral_slot == "push" else (upper_push_bi or upper_push_options),
                history,
                focus,
                upper_push_power_uni if unilateral_slot == "push" else (upper_push_power_bi or upper_push_power_options),
            ),
            "intensity": phase_intensity,
            **prescription,
        },
        "main_lift_upper_pull": {
            "exercise": _pick_main_exercise(
                "upper_pull",
                upper_pull_uni if unilateral_slot == "pull" else (upper_pull_bi or upper_pull_options),
                history,
                focus,
                upper_pull_power_uni if unilateral_slot == "pull" else (upper_pull_power_bi or upper_pull_power_options),
            ),
            "intensity": phase_intensity,
            **prescription,
        },
        "core": {
            "exercise": _pick_main_exercise("core", EXERCISE_LIBRARY["core"], history, focus, EXERCISE_LIBRARY.get("core_power", [])),
            "intensity": "light",
            **CORE_PRESCRIPTION,
        },
        "accessories": [],
    }

    if is_time_based_exercise(workout["core"]["exercise"].get("name")):
        workout["core"]["reps"] = "20–30 sec"

    accessories = pick_accessory_pair(history)
    for ex in accessories:
        block = {
            "exercise": ex,
            "intensity": "light",
            **ACCESSORY_PRESCRIPTION,
        }
        if is_time_based_exercise(ex.get("name")):
            block["reps"] = "20–30 sec"
        workout["accessories"].append(block)

    workout["load_scores"] = {
        "lower": compute_load_score(workout["main_lift_lower"]["intensity"], workout["main_lift_lower"]["exercise"]),
        "upper_push": compute_load_score(workout["main_lift_upper_push"]["intensity"], workout["main_lift_upper_push"]["exercise"]),
        "upper_pull": compute_load_score(workout["main_lift_upper_pull"]["intensity"], workout["main_lift_upper_pull"]["exercise"]),
        "core": compute_load_score(workout["core"]["intensity"], workout["core"]["exercise"]),
    }
    for idx, block in enumerate(workout["accessories"], start=1):
        key = f"accessory_{idx}"
        workout["load_scores"][key] = compute_load_score(block["intensity"], block["exercise"])
    workout["total_load_score"] = sum(workout["load_scores"].values())
    workout["suggested_weights"] = {
        "lower": suggest_weight(history, workout["main_lift_lower"]["exercise"]["name"]),
        "upper_push": suggest_weight(history, workout["main_lift_upper_push"]["exercise"]["name"]),
        "upper_pull": suggest_weight(history, workout["main_lift_upper_pull"]["exercise"]["name"]),
        "core": None,
    }
    for idx, block in enumerate(workout["accessories"], start=1):
        key = f"accessory_{idx}"
        workout["suggested_weights"][key] = suggest_weight(history, block["exercise"]["name"])

    return workout


# -----------------------------
# 5) Print output (v1)
# -----------------------------
def print_workout(athlete: dict, workout: dict) -> None:
    print("\n==============================")
    print("WORKOUT GENERATOR v1")
    print("==============================")
    print(f"Position: {athlete['position']} | Goal: {athlete['goal']} | Phase: {athlete['phase']}")
    print(f"Injuries: {', '.join(athlete['injuries']) if athlete['injuries'] else 'None'}")
    print("------------------------------")

    print("\nWARM-UP")
    for item in workout["warmup"]:
        print(f"- {item}")

    print("\nMAIN")
    for label, block in [
        ("Lower", workout["main_lift_lower"]),
        ("Upper Push", workout["main_lift_upper_push"]),
        ("Upper Pull", workout["main_lift_upper_pull"]),
    ]:
        print(f"- {label}: {block['exercise']['name']}")
        print(f"  Sets: {block['sets']} | Reps: {block['reps']} | Rest: {block['rest']}")
        print(f"  Intensity: {block['intensity']} | Load Score: {workout['load_scores'][label.lower().replace(' ', '_')]}")
        suggested = workout["suggested_weights"][label.lower().replace(" ", "_")]
        if suggested is not None:
            print(f"  Suggested Weight: {suggested}")

    print("\nCORE / FINISHER")
    core = workout["core"]
    print(f"- {core['exercise']['name']}")
    print(f"  Sets: {core['sets']} | Reps: {core['reps']} | Rest: {core['rest']}")
    print(f"  Intensity: {core['intensity']} | Load Score: {workout['load_scores']['core']}")

    if workout["accessories"]:
        print("\nACCESSORIES")
        for idx, block in enumerate(workout["accessories"], start=1):
            key = f"accessory_{idx}"
            print(f"- {block['exercise']['name']}")
            print(f"  Sets: {block['sets']} | Reps: {block['reps']} | Rest: {block['rest']}")
            print(f"  Intensity: {block['intensity']} | Load Score: {workout['load_scores'][key]}")
            suggested = workout["suggested_weights"].get(key)
            if suggested is not None:
                print(f"  Suggested Weight: {suggested}")
    print(f"\nTOTAL LOAD SCORE: {workout['total_load_score']}")
    print("\n==============================\n")


def format_workout_text(athlete: dict, workout: dict) -> str:
    lines = []
    lines.append("==============================")
    lines.append("WORKOUT GENERATOR v1")
    lines.append("==============================")
    lines.append(f"Position: {athlete['position']} | Goal: {athlete['goal']} | Phase: {athlete['phase']}")
    lines.append(f"Injuries: {', '.join(athlete['injuries']) if athlete['injuries'] else 'None'}")
    lines.append("------------------------------")

    lines.append("")
    lines.append("WARM-UP")
    for item in workout["warmup"]:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("MAIN")
    for label, block in [
        ("Lower", workout["main_lift_lower"]),
        ("Upper Push", workout["main_lift_upper_push"]),
        ("Upper Pull", workout["main_lift_upper_pull"]),
    ]:
        lines.append(f"- {label}: {block['exercise']['name']}")
        lines.append(f"  Sets: {block['sets']} | Reps: {block['reps']} | Rest: {block['rest']}")
        lines.append(f"  Intensity: {block['intensity']} | Load Score: {workout['load_scores'][label.lower().replace(' ', '_')]}")
        suggested = workout["suggested_weights"][label.lower().replace(" ", "_")]
        if suggested is not None:
            lines.append(f"  Suggested Weight: {suggested}")

    lines.append("")
    lines.append("CORE / FINISHER")
    core = workout["core"]
    lines.append(f"- {core['exercise']['name']}")
    lines.append(f"  Sets: {core['sets']} | Reps: {core['reps']} | Rest: {core['rest']}")
    lines.append(f"  Intensity: {core['intensity']} | Load Score: {workout['load_scores']['core']}")
    if workout["accessories"]:
        lines.append("")
        lines.append("ACCESSORIES")
        for idx, block in enumerate(workout["accessories"], start=1):
            key = f"accessory_{idx}"
            lines.append(f"- {block['exercise']['name']}")
            lines.append(f"  Sets: {block['sets']} | Reps: {block['reps']} | Rest: {block['rest']}")
            lines.append(f"  Intensity: {block['intensity']} | Load Score: {workout['load_scores'][key]}")
            suggested = workout["suggested_weights"].get(key)
            if suggested is not None:
                lines.append(f"  Suggested Weight: {suggested}")
    lines.append("")
    lines.append(f"TOTAL LOAD SCORE: {workout['total_load_score']}")
    lines.append("")
    lines.append("==============================")

    return "\n".join(lines)


def _pattern_of_exercise(exercise: dict) -> str:
    pattern = exercise.get("pattern", "unknown")
    if pattern == "carry":
        return "core"
    return pattern


def _weekly_warnings(phase: str, total_load: int, pattern_counts: dict) -> list[str]:
    warnings = []
    cap = WEEKLY_LOAD_CAPS.get(phase, 60)
    if total_load > cap:
        warnings.append(f"Weekly load cap exceeded: {total_load} > {cap}")
    for pattern, count in pattern_counts.items():
        cap_val = PATTERN_CAPS.get(pattern)
        if cap_val is not None and count > cap_val:
            warnings.append(f"Pattern cap exceeded for {pattern}: {count} > {cap_val}")
    return warnings


def _recent_history_from(history: list[dict], days: int = 7) -> list[dict]:
    cutoff = datetime.now().date() - timedelta(days=days - 1)
    recent = []
    for entry in history:
        date_str = entry.get("date")
        if not date_str:
            continue
        try:
            entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if entry_date >= cutoff:
            recent.append(entry)
    return recent


def _pattern_lookup() -> dict:
    lookup = {}
    for key in ["upper_push", "upper_pull", "lower", "core"]:
        for ex in EXERCISE_LIBRARY.get(key, []):
            lookup[ex["name"]] = _pattern_of_exercise(ex)
    return lookup


def compute_history_caps_from_history(history: list[dict], phase: str, workout: dict, days: int = 7) -> dict:
    recent = _recent_history_from(history, days=days)
    pattern_counts = {p: 0 for p in PATTERN_CAPS}
    total_load = 0

    name_to_pattern = _pattern_lookup()
    name_to_ex = {}
    for group in ["upper_push", "upper_pull", "lower", "core"]:
        for ex in EXERCISE_LIBRARY.get(group, []):
            name_to_ex[ex["name"]] = ex
    for entry in recent:
        name = entry.get("exercise_name")
        if not name:
            continue
        pattern = name_to_pattern.get(name)
        if pattern in pattern_counts:
            pattern_counts[pattern] += 1
        ex = name_to_ex.get(name)
        if ex:
            entry_phase = entry.get("phase", phase)
            entry_intensity = get_phase_intensity(entry_phase)
            total_load += compute_load_score(entry_intensity, ex)

    # Add today's workout impact
    total_load += workout["total_load_score"]
    for key in ["main_lift_lower", "main_lift_upper_push", "main_lift_upper_pull", "core"]:
        ex = workout[key]["exercise"]
        pattern = _pattern_of_exercise(ex)
        if pattern in pattern_counts:
            pattern_counts[pattern] += 1
    for block in workout.get("accessories", []):
        ex = block["exercise"]
        pattern = _pattern_of_exercise(ex)
        if pattern in pattern_counts:
            pattern_counts[pattern] += 1

    warnings = _weekly_warnings(phase, total_load, pattern_counts)
    return {
        "total_load": total_load,
        "pattern_counts": pattern_counts,
        "warnings": warnings,
    }


def compute_history_caps(phase: str, workout: dict) -> dict:
    history = load_history()
    return compute_history_caps_from_history(history, phase, workout, days=7)


def save_workout_to_file(athlete: dict, workout: dict) -> Path:
    workouts_dir = Path(__file__).parent / "workouts"
    workouts_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_position = athlete["position"].replace(" ", "_")
    filename = f"workout_{safe_position}_{timestamp}.txt"
    path = workouts_dir / filename

    path.write_text(format_workout_text(athlete, workout))
    return path


def save_workout_to_json(athlete: dict, workout: dict) -> Path:
    workouts_dir = Path(__file__).parent / "workouts"
    workouts_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_position = athlete["position"].replace(" ", "_")
    filename = f"workout_{safe_position}_{timestamp}.json"
    path = workouts_dir / filename

    payload = {
        "athlete": athlete,
        "workout": workout,
    }
    workout_id = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    data = {
        **payload,
        "workout_id": workout_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    path.write_text(json.dumps(data, indent=2))
    return path


if __name__ == "__main__":
    athlete = collect_athlete_from_input(DEFAULT_ATHLETE)
    workout = generate_workout(athlete)
    print_workout(athlete, workout)
    caps = compute_history_caps(athlete.get("phase", "offseason"), workout)
    if caps["warnings"]:
        print("\nWARNINGS (LAST 7 DAYS)")
        for w in caps["warnings"]:
            print(f"- {w}")
    print(f"\n7-DAY TOTAL LOAD SCORE (including today): {caps['total_load']}")
    saved_path = save_workout_to_file(athlete, workout)
    saved_json_path = save_workout_to_json(athlete, workout)
    print(f"Saved workout to: {saved_path}")
    print(f"Saved workout JSON to: {saved_json_path}")
