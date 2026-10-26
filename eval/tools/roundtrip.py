"""Observe export and SQLite round trips without user files or databases."""

from contextlib import redirect_stdout
from copy import deepcopy
import importlib
import io
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from unittest.mock import patch

import work_gen


def observe_roundtrip(case, workout):
    """Save to a temporary directory and retain both JSON and text evidence."""
    original = {"athlete": deepcopy(case["athlete"]), "workout": deepcopy(workout)}
    with TemporaryDirectory(prefix="workout-eval-json-") as directory:
        with patch.object(work_gen, "__file__", str(Path(directory) / "work_gen.py")):
            path = work_gen.save_workout_to_json(case["athlete"], workout)
            loaded = json.loads(path.read_text())
    text, format_error = _text_export(loaded["athlete"], loaded["workout"])
    return {"original": original, "loaded": loaded, "text": text,
            "format_error": format_error}


def _text_export(athlete, workout):
    try:
        text = work_gen.format_workout_text(athlete, workout)
        format_error = None
    except TypeError as exc:
        # Record only the confirmed null-main-slot failure. Other type errors remain errors.
        null_slot = any(workout.get(key) is None for key in (
            "main_lift_lower", "main_lift_upper_push", "main_lift_upper_pull"
        ))
        trace = exc.__traceback__
        while trace.tb_next:
            trace = trace.tb_next
        null_block = "block" in trace.tb_frame.f_locals and trace.tb_frame.f_locals["block"] is None
        if not null_slot or not null_block or str(exc) != "'NoneType' object is not subscriptable":
            raise
        text = None
        format_error = f"{type(exc).__name__}: {exc}"
    return text, format_error


def json_roundtrip_preserved(observation, expected):
    """Compare the original athlete and complete prescription to saved JSON."""
    original = observation["original"]
    loaded = observation["loaded"]
    return [f"{key}: saved JSON differs from the generated input"
            for key in ("athlete", "workout") if loaded.get(key) != original[key]]


def _prescribed_rows(workout):
    blocks = [workout[key] for key in (
        "main_lift_lower", "main_lift_upper_push", "main_lift_upper_pull", "core"
    ) if workout.get(key)] + workout.get("accessories", [])
    return [(block["exercise"]["name"], str(block["sets"]), str(block["reps"]))
            for block in blocks]


def _text_rows(text):
    """Parse names, sets, reps, and order from the human export independently."""
    section = None
    warmup = []
    rows = []
    pending = None
    for line in text.splitlines():
        if line in ("WARM-UP", "MAIN", "CORE / FINISHER", "ACCESSORIES"):
            section = line
        elif line.startswith("TOTAL LOAD SCORE:"):
            section = None
        elif line.startswith("- "):
            name = line[2:]
            if section == "WARM-UP":
                warmup.append(name)
            elif section in ("MAIN", "CORE / FINISHER", "ACCESSORIES"):
                if pending is not None:
                    rows.append((pending, None, None))
                if section == "MAIN":
                    name = re.sub(r"^(Lower|Upper Push|Upper Pull): ", "", name)
                pending = name
        elif line.lstrip().startswith("Sets:") and pending is not None:
            prescription = re.fullmatch(r"\s+Sets: (.*?) \| Reps: (.*?) \| Rest: .*", line)
            if prescription:
                rows.append((pending, prescription[1], prescription[2]))
            else:
                rows.append((pending, None, None))
            pending = None
    if pending is not None:
        rows.append((pending, None, None))
    return warmup, rows


def text_prescriptions_preserved(observation, expected):
    """Require every warm-up and ordered exercise prescription in the text."""
    if observation.get("format_error"):
        return [f"text export failed: {observation['format_error']}"]
    if not isinstance(observation.get("text"), str):
        return ["text export is absent"]
    workout = observation["original"]["workout"]
    warmup, rows = _text_rows(observation["text"])
    expected_warmup = [item["name"] if isinstance(item, dict) else item
                       for item in workout.get("warmup", [])]
    violations = []
    if warmup != expected_warmup:
        violations.append("warm-up exercises or their order differ from the generated workout")
    if rows != _prescribed_rows(workout):
        violations.append("exercise names, sets, reps, or their order differ from the generated workout")
    return violations


def observe_flask_roundtrip(case, workout):
    """Use an isolated SQLite database and the existing completed-log edit route."""
    # Blank both accepted database settings before import. The imported module also
    # receives explicit temporary paths before any database function is called.
    with patch.dict(os.environ, {"DATABASE_URL": "", "WORKOUT_GENERATOR_DB_URL": ""}):
        with redirect_stdout(io.StringIO()):
            application = importlib.import_module("app")
    original = {"athlete": deepcopy(case["athlete"]), "workout": deepcopy(workout)}
    target = case["scenario"]["edit"]
    with TemporaryDirectory(prefix="workout-eval-sqlite-") as directory:
        data_dir = Path(directory)
        with patch.object(application, "DATABASE_URL", ""), \
                patch.object(application, "DATA_DIR", data_dir), \
                patch.object(application, "DB_PATH", data_dir / "eval.db"), \
                patch.object(work_gen, "EXERCISE_LIBRARY", deepcopy(work_gen.EXERCISE_LIBRARY)), \
                patch.dict(application.app.config, {
                    "TESTING": True, "SECRET_KEY": "synthetic-eval-session",
                    "SESSION_COOKIE_SECURE": False,
                }):
            application._init_db()
            user_id = "synthetic-eval-athlete"
            conn = application._db()
            with conn:
                conn.execute(
                    "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, "synthetic-eval@example.invalid", "unused", "2026-10-26T12:00:00"),
                )
            conn.close()
            workout_id = application._save_workout(user_id, workout)
            stored = application._fetch_workout(user_id, workout_id)
            first_key, category = next((key, category) for key, category in (
                ("main_lift_lower", "lower"), ("main_lift_upper_push", "upper_push"),
                ("main_lift_upper_pull", "upper_pull"), ("core", "core")
            ) if workout.get(key))
            first = workout[first_key]["exercise"]
            conn = application._db()
            with conn:
                cursor = conn.execute(
                    "INSERT INTO completed_logs "
                    "(user_id, workout_id, date, exercise_id, exercise_name, category, phase, weight, reps) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, workout_id, "2026-10-26", first.get("id"), first["name"], category,
                     case["athlete"]["phase"], 40.0, 5),
                )
                log_id = cursor.lastrowid
            conn.close()
            with application.app.test_client() as client:
                with client.session_transaction() as session:
                    session["user_id"] = user_id
                response = client.post(f"/history/edit/{log_id}", data=target)
            conn = application._db()
            completed = dict(conn.execute(
                "SELECT date, weight, reps FROM completed_logs WHERE id = ? AND user_id = ?",
                (log_id, user_id),
            ).fetchone())
            conn.close()
            after_edit = application._fetch_workout(user_id, workout_id)
    text, format_error = _text_export(case["athlete"], after_edit)
    return {"original": original, "stored_workout": stored,
            "after_edit_workout": after_edit, "completed_log": completed,
            "expected_completed_log": target, "edit_status": response.status_code,
            "edit_location": response.headers.get("Location"),
            "text": text, "format_error": format_error}


def flask_workout_preserved(observation, expected):
    """Require complete saved JSON before and after a completed-log edit."""
    original = observation["original"]["workout"]
    return [f"{key}: saved prescription changed"
            for key in ("stored_workout", "after_edit_workout")
            if observation[key] != original]


def completed_log_edit_preserved(observation, expected):
    """Require the submitted date, weight, and reps in the saved completed log."""
    violations = []
    if observation["edit_status"] != 302 or observation["edit_location"] != "/history":
        violations.append("completed-log edit did not redirect to history")
    for key, value in observation["expected_completed_log"].items():
        if observation["completed_log"].get(key) != value:
            violations.append(f"{key}: completed-log edit differs from the submitted value")
    return violations
