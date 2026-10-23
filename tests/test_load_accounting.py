from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json

import pytest
from flask import template_rendered

import work_gen
import log_workout


def mixed_workout(identity=1):
    return {
        "workout_id": identity,
        "main_lift_lower": {"intensity": "heavy", "exercise": {
            "id": "jump", "name": "Power jump", "pattern": "squat", "muscle_mass": "very_large"}},
        "core": {"intensity": "light", "exercise": {
            "id": "carry", "name": "Carry", "pattern": "carry", "muscle_mass": "medium"}},
        "accessories": [{"intensity": "moderate", "exercise": {
            "id": "push", "name": "Small push", "pattern": "push", "muscle_mass": "small"}}],
        "total_load_score": 22,
    }


def completed(workout, date=None):
    return [{
        "workout_id": workout["workout_id"],
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "category": category,
        "exercise_name": block["exercise"]["name"],
        "exercise_id": block["exercise"]["id"],
        "exercise": deepcopy(block["exercise"]),
        "intensity": block["intensity"],
        "phase": "offseason",
    } for category, block in work_gen.workout_blocks(workout)]


def test_mixed_intensity_power_snapshot_keeps_total_and_patterns(monkeypatch):
    workout = mixed_workout()
    # Saved metadata remains authoritative if the current library changes.
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", {"warmup": ["Walk"]})
    planned = work_gen.compute_history_caps_from_history([], "offseason", workout)
    logged = work_gen.compute_history_caps_from_history(completed(workout), "offseason", workout)
    assert planned == logged
    assert logged["total_load"] == 22
    assert logged["pattern_counts"] == {"push": 1, "pull": 0, "squat": 1, "hinge": 0, "lateral": 0, "core": 1}


def test_distinct_identical_sessions_are_both_counted():
    first, second = mixed_workout(1), mixed_workout(2)
    planned = work_gen.compute_history_caps_from_history(completed(first), "offseason", second)
    logged = work_gen.compute_history_caps_from_history(completed(first) + completed(second), "offseason", second)
    assert planned == logged
    assert logged["total_load"] == 44
    assert logged["pattern_counts"]["squat"] == 2
    assert logged["pattern_counts"]["core"] == 2


@pytest.mark.parametrize("offset,expected", [(0, 22), (-6, 22), (-7, 0), (1, 0)])
def test_completed_date_window_does_not_reintroduce_plan(offset, expected):
    workout = mixed_workout()
    date = (datetime.now().date() + timedelta(days=offset)).isoformat()
    caps = work_gen.compute_history_caps_from_history(completed(workout, date), "offseason", workout)
    assert caps["total_load"] == expected
    assert sum(caps["pattern_counts"].values()) == (3 if expected else 0)


@pytest.mark.parametrize("bad_date", ["invalid", "2026-02-30", None, 123])
def test_invalid_completed_dates_are_excluded_without_becoming_plans(bad_date):
    workout = mixed_workout()
    history = completed(workout)
    for row in history:
        row["date"] = bad_date
    caps = work_gen.compute_history_caps_from_history(history, "offseason", workout)
    assert caps["total_load"] == 0
    assert sum(caps["pattern_counts"].values()) == 0


def test_legacy_fallback_includes_power_and_ignores_unknown(monkeypatch):
    exercise = mixed_workout()["main_lift_lower"]["exercise"]
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", {"warmup": ["Walk"], "lower_power": [exercise]})
    today = datetime.now().strftime("%Y-%m-%d")
    history = [
        {"date": today, "exercise_name": exercise["name"], "phase": "inseason"},
        {"date": today, "exercise_name": "Unknown", "phase": "offseason"},
    ]
    caps = work_gen.compute_history_caps_from_history(history, "offseason", {})
    assert caps["total_load"] == 5
    assert caps["pattern_counts"]["squat"] == 1


@pytest.fixture
def web(tmp_path, monkeypatch):
    import app as web_app
    monkeypatch.setattr(web_app, "DATABASE_URL", "")
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "DB_PATH", tmp_path / "data" / "workouts.db")
    monkeypatch.setitem(web_app.app.config, "TESTING", True)
    monkeypatch.setitem(web_app.app.config, "SECRET_KEY", "isolated-test-secret")
    # _init_db updates this module-level library; restore it after the test.
    monkeypatch.setattr(work_gen, "EXERCISE_LIBRARY", deepcopy(work_gen.EXERCISE_LIBRARY))
    web_app._init_db()
    conn = web_app._db()
    with conn:
        conn.execute("""INSERT INTO users
            (id, email, password_hash, created_at, full_name, dob, position, goal, phase, days_per_week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("test-user", "test@example.invalid", "unused", datetime.now().isoformat(),
             "Test Athlete", "2000-01-01", "outfielder", "power", "offseason", 3))
    conn.close()
    return web_app


def test_flask_generate_log_repeat_preserves_caps_and_row_count(web):
    contexts = []
    def capture(sender, template, context, **extra):
        if template.name == "result.html":
            contexts.append(deepcopy({key: context[key] for key in
                ("caps", "workout", "workout_id", "already_logged")}))

    with web.app.test_client() as client, template_rendered.connected_to(capture, web.app):
        with client.session_transaction() as session:
            session["user_id"] = "test-user"
        assert client.post("/generate").status_code == 200
        generated = contexts[-1]
        workout_id = generated["workout_id"]
        assert generated["caps"]["total_load"] == generated["workout"]["total_load_score"]
        expected_rows = len(web._workout_entries(generated["workout"]))
        for _ in range(2):
            assert client.post(f"/log/{workout_id}").status_code == 200
            assert contexts[-1]["caps"] == generated["caps"]
            assert contexts[-1]["already_logged"] is True
            history = web._fetch_history("test-user")
            assert len(history) == expected_rows
            assert all(row["workout_id"] == workout_id for row in history)
            assert all(row.get("exercise") and row.get("intensity") for row in history)


def test_saved_metadata_distinguishes_repeated_exercise_blocks(web):
    workout = mixed_workout()
    workout["accessories"] = [deepcopy(workout["core"]), deepcopy(workout["core"])]
    workout["accessories"][1]["intensity"] = "heavy"
    workout_id = web._save_workout("test-user", workout)
    conn = web._db()
    with conn:
        for entry in web._workout_entries(workout):
            conn.execute("""INSERT INTO completed_logs
                (user_id, workout_id, date, exercise_id, exercise_name, category, phase)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("test-user", workout_id, datetime.now().strftime("%Y-%m-%d"),
                 entry["exercise_id"], entry["exercise_name"], entry["category"], "offseason"))
    conn.close()
    history = web._fetch_history("test-user")
    assert [entry["intensity"] for entry in history] == ["heavy", "light", "light", "heavy"]
    caps = work_gen.compute_history_caps_from_history(history, "offseason", web._fetch_workout("test-user", workout_id))
    assert caps["total_load"] == 30


def test_cli_new_sessions_have_distinct_stable_ids_and_legacy_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(work_gen, "__file__", str(tmp_path / "work_gen.py"))
    first = mixed_workout()
    first.pop("workout_id")
    second = deepcopy(first)
    athlete = {"position": "outfielder"}
    first_path = work_gen.save_workout_to_json(athlete, first)
    second_path = work_gen.save_workout_to_json(athlete, second)
    assert first_path != second_path
    assert log_workout._workout_id_from_file(first_path) == first["workout_id"]
    assert log_workout._workout_id_from_file(second_path) != first["workout_id"]
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"workout_id": "old-payload-hash", "workout": {}}))
    assert log_workout._workout_id_from_file(legacy) == hashlib.sha256(legacy.read_bytes()).hexdigest()


def test_cli_logging_keeps_metadata_and_repeated_log_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(work_gen, "__file__", str(tmp_path / "work_gen.py"))
    monkeypatch.setattr(log_workout, "__file__", str(tmp_path / "log_workout.py"))
    workout = mixed_workout("cli-session")
    path = work_gen.save_workout_to_json({"position": "outfielder", "phase": "offseason"}, workout)
    answers = iter([str(path), "", "100", "5", "20", "8", "10", "12"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    log_workout.main()
    history_path = tmp_path / "workouts" / "history.jsonl"
    first = history_path.read_text()
    rows = [json.loads(line) for line in first.splitlines()]
    assert [row["intensity"] for row in rows] == ["heavy", "light", "moderate"]
    assert work_gen.compute_history_caps_from_history(rows, "offseason", workout)["total_load"] == 22
    monkeypatch.setattr("builtins.input", lambda _: str(path))
    log_workout.main()
    assert history_path.read_text() == first


@pytest.mark.parametrize("deleted_index", [0, 1])
def test_deleted_repeated_block_uses_legacy_fallback(web, deleted_index):
    exercise = deepcopy(work_gen.EXERCISE_LIBRARY["upper_push"][0])
    workout = {"accessories": [
        {"exercise": exercise, "intensity": "light"},
        {"exercise": exercise, "intensity": "heavy"},
    ], "total_load_score": 0}
    workout_id = web._save_workout("test-user", workout)
    conn = web._db()
    with conn:
        for _ in range(2):
            conn.execute("""INSERT INTO completed_logs
                (user_id, workout_id, date, exercise_id, exercise_name, category, phase)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("test-user", workout_id, datetime.now().strftime("%Y-%m-%d"),
                 exercise.get("id"), exercise["name"], "accessory", "inseason"))
        ids = conn.execute("SELECT id FROM completed_logs ORDER BY id").fetchall()
        conn.execute("DELETE FROM completed_logs WHERE id = ?", (ids[deleted_index]["id"],))
    conn.close()
    history = web._fetch_history("test-user")
    assert len(history) == 1
    assert "intensity" not in history[0]
    assert "exercise" not in history[0]
    caps = work_gen.compute_history_caps_from_history(history, "offseason", web._fetch_workout("test-user", workout_id))
    assert caps["total_load"] == work_gen.compute_load_score(work_gen.get_phase_intensity("inseason"), exercise)
    assert sum(caps["pattern_counts"].values()) == 1
