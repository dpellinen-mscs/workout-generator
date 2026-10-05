import json
import re
import hashlib
from datetime import datetime
from pathlib import Path


def _latest_workout_json() -> Path | None:
    workouts_dir = Path(__file__).parent / "workouts"
    if not workouts_dir.exists():
        return None
    files = sorted(workouts_dir.glob("workout_*.json"))
    return files[-1] if files else None


def _input_with_default(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else default


def _parse_weight(raw: str) -> float | None:
    cleaned = raw.strip().lower().replace("lbs", "").replace("lb", "")
    cleaned = cleaned.replace(",", "")
    # Handle formats like 2x75 or 75x2
    if "x" in cleaned:
        parts = [p for p in cleaned.split("x") if p]
        if len(parts) == 2:
            try:
                a = float(re.sub(r"[^0-9.]", "", parts[0]))
                b = float(re.sub(r"[^0-9.]", "", parts[1]))
                return a * b
            except ValueError:
                return None
    # Default: extract first number (e.g., "75s" -> 75)
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _prompt_float(prompt: str) -> float:
    while True:
        raw = input(prompt).strip()
        parsed = _parse_weight(raw)
        if parsed is None:
            print("Please enter a number (examples: 75, 75s, 2x75).")
            continue
        return parsed


def _prompt_int(prompt: str) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            return int(raw)
        except ValueError:
            print("Please enter an integer.")


def load_workout(path: Path) -> dict:
    return json.loads(path.read_text())


def _workout_id_from_file(path: Path) -> str:
    content = path.read_text()
    data = json.loads(content)
    # Older files used content hashes in history; their top-level ID was a
    # different hash. Only the new nested session identity supersedes that.
    workout_id = data.get("workout", {}).get("workout_id")
    if workout_id:
        return workout_id
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _history_contains_workout_id(history_path: Path, workout_id: str) -> bool:
    if not history_path.exists():
        return False
    for line in history_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("workout_id") == workout_id:
            return True
    return False


def append_history(entries: list[dict]) -> Path:
    history_path = Path(__file__).parent / "workouts" / "history.jsonl"
    history_path.parent.mkdir(exist_ok=True)
    with history_path.open("a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return history_path


def main() -> None:
    latest = _latest_workout_json()
    default_path = str(latest) if latest else ""
    path_str = _input_with_default("Workout JSON path", default_path) if default_path else input("Workout JSON path: ").strip()
    if not path_str:
        print("No path provided.")
        return

    workout_path = Path(path_str)
    if not workout_path.exists():
        print("File not found.")
        return

    history_path = Path(__file__).parent / "workouts" / "history.jsonl"
    workout_id = _workout_id_from_file(workout_path)
    if _history_contains_workout_id(history_path, workout_id):
        print("This workout has already been logged.")
        return

    data = load_workout(workout_path)
    workout = data.get("workout", {})
    athlete = data.get("athlete", {})

    date_str = _input_with_default("Workout date (YYYY-MM-DD)", datetime.now().strftime("%Y-%m-%d"))

    entries = []
    for key, label in [
        ("main_lift_lower", "Lower"),
        ("main_lift_upper_push", "Upper Push"),
        ("main_lift_upper_pull", "Upper Pull"),
        ("core", "Core"),
    ]:
        block = workout.get(key)
        if not block:
            continue
        name = block.get("exercise", {}).get("name", "Unknown")
        print(f"\nLogging: {label} - {name}")
        weight = _prompt_float("Weight used (lbs): ")
        reps = _prompt_int("Reps completed: ")

        entries.append({
            "date": date_str,
            "exercise_name": name,
            "category": label.lower().replace(" ", "_"),
            "weight": weight,
            "reps": reps,
            "goal": athlete.get("goal"),
            "phase": athlete.get("phase"),
            "position": athlete.get("position"),
            "workout_id": workout_id,
            "exercise": block.get("exercise", {}),
            "intensity": block.get("intensity"),
        })

    for block in workout.get("accessories", []):
        name = block.get("exercise", {}).get("name", "Unknown")
        print(f"\nLogging: Accessory - {name}")
        weight = _prompt_float("Weight used (lbs): ")
        reps = _prompt_int("Reps completed: ")
        entries.append({
            "date": date_str,
            "exercise_name": name,
            "category": "accessory",
            "weight": weight,
            "reps": reps,
            "goal": athlete.get("goal"),
            "phase": athlete.get("phase"),
            "position": athlete.get("position"),
            "workout_id": workout_id,
            "exercise": block.get("exercise", {}),
            "intensity": block.get("intensity"),
        })

    history_path = append_history(entries)
    print(f"\nSaved {len(entries)} entries to: {history_path}")


if __name__ == "__main__":
    main()
