import json
import os
import sqlite3
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

import work_gen

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "workouts.db"
# Support both explicit DATABASE_URL and Render's default datastore var naming.
DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("WORKOUT_GENERATOR_DB_URL") or "").strip()
ADMIN_REGISTRATION_CODE = os.getenv("WG_ADMIN_CODE", "coach-admin-123")
EXERCISE_LIBRARY_PATH = APP_DIR / "exercise_library.json"

app = Flask(__name__)
app.secret_key = os.getenv("WG_SECRET_KEY", "dev-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("WG_SECURE_COOKIES", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)

TIME_BASED_KEYWORDS = [
    "plank",
    "side bridge",
    "farmer carry",
    "farmers carry",
    "farmer's carry",
]

WARMUP_VERSION = 3
WARMUP_SEQUENCE = [
    "Self-myofascial release / foam roll: T-spine, lats, pecs/chest, hip flexors, delts, adductors, IT band, glutes, calves, hamstrings (30–60s each)",
    "90/90 hip stretch 15–20s/side",
    "Half-kneeling hip flexor stretch 15–20s/side",
    "Mobility: Shoulder INT-EXT rotation (band or cable) x 10/side",
    "Mobility: Wall ankle mobilizations x 8/side",
    "Activation: X-band walks x 12/side",
    "Activation: Band pull-aparts x 15",
    "Activation: Dead bug x 8/side",
]

CATEGORY_LABELS = {
    "upper_push": "Push",
    "upper_pull": "Pull",
    "lower": "Lower Body",
    "core": "Trunk Stability",
    "accessory": "Supplemental",
    "warmup": "Warm-Up",
}

PATTERN_LABELS = {
    "push": "Push",
    "pull": "Pull",
    "squat": "Squat",
    "hinge": "Hinge",
    "lunge": "Lunge / Single-Leg",
    "single_leg": "Lunge / Single-Leg",
    "lateral": "Lateral",
    "carry": "Carry",
    "rotation": "Rotation / Anti-Rotation",
    "core": "Trunk Stability",
    "trunk_stability": "Trunk Stability",
    "push_horizontal": "Push (Horizontal)",
    "push_vertical": "Push (Vertical)",
    "pull_horizontal": "Pull (Horizontal)",
    "pull_vertical": "Pull (Vertical)",
    "knee_flexion": "Knee Flexion",
    "knee_extension": "Knee Extension",
    "hip_flexion": "Hip Flexion",
}


def is_time_based_exercise(name: str | None) -> bool:
    if not name:
        return False
    value = name.lower()
    return any(keyword in value for keyword in TIME_BASED_KEYWORDS)


app.jinja_env.globals["is_time_based_exercise"] = is_time_based_exercise
app.jinja_env.globals["display_category_label"] = lambda c: CATEGORY_LABELS.get(c, (c or "").replace("_", " ").title())
app.jinja_env.globals["display_pattern_label"] = lambda p: PATTERN_LABELS.get((p or "").lower(), (p or "").replace("_", " ").title())


def _is_postgres() -> bool:
    return DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")


print(f"[startup] db_backend={'postgres' if _is_postgres() else 'sqlite'}")


class DBConn:
    def __init__(self, raw, postgres: bool):
        self.raw = raw
        self.postgres = postgres

    def _adapt(self, query: str) -> str:
        if not self.postgres:
            return query
        return query.replace("?", "%s")

    def execute(self, query: str, params=()):
        return self.raw.execute(self._adapt(query), params)

    def executemany(self, query: str, seq):
        adapted = self._adapt(query)
        # psycopg3 connections don't expose executemany; cursors do.
        if self.postgres:
            with self.raw.cursor() as cur:
                for params in seq:
                    cur.execute(adapted, params)
            return None
        return self.raw.executemany(adapted, seq)

    def close(self):
        return self.raw.close()

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.raw.__exit__(exc_type, exc, tb)


def _db() -> sqlite3.Connection:
    if _is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        return DBConn(conn, postgres=True)

    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return DBConn(conn, postgres=False)


def _init_db() -> None:
    conn = _db()
    with conn:
        if _is_postgres():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    full_name TEXT,
                    dob TEXT,
                    height_in DOUBLE PRECISION,
                    weight_lbs DOUBLE PRECISION,
                    max_bench_lbs DOUBLE PRECISION,
                    max_deadlift_lbs DOUBLE PRECISION,
                    max_back_squat_lbs DOUBLE PRECISION,
                    standing_vertical_jump_in DOUBLE PRECISION,
                    rotational_scoop_toss_ft DOUBLE PRECISION,
                    cable_chop_lbs DOUBLE PRECISION,
                    max_exit_velocity_mph DOUBLE PRECISION,
                    estimated_bench_1rm_lbs DOUBLE PRECISION,
                    estimated_back_squat_1rm_lbs DOUBLE PRECISION,
                    estimated_deadlift_1rm_lbs DOUBLE PRECISION,
                    estimated_reverse_lunge_1rm_lbs DOUBLE PRECISION,
                    estimated_dumbbell_row_1rm_lbs DOUBLE PRECISION,
                    med_ball_chest_pass_ft DOUBLE PRECISION,
                    position TEXT,
                    goal TEXT,
                    phase TEXT,
                    days_per_week INTEGER,
                    injuries TEXT,
                    is_admin INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workouts (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    workout_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_logs (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workout_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    exercise_id TEXT,
                    exercise_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    phase TEXT,
                    weight DOUBLE PRECISION,
                    reps INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS performance_logs (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    exit_velocity_mph DOUBLE PRECISION,
                    throw_velocity_mph DOUBLE PRECISION,
                    dash_60_time_s DOUBLE PRECISION,
                    broad_jump_in DOUBLE PRECISION,
                    lateral_broad_jump_in DOUBLE PRECISION,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS exercises (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    movement_family TEXT,
                    pattern TEXT,
                    muscle_mass TEXT,
                    unilateral INTEGER,
                    sort_order INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    full_name TEXT,
                    dob TEXT,
                    height_in REAL,
                    weight_lbs REAL,
                    max_bench_lbs REAL,
                    max_deadlift_lbs REAL,
                    max_back_squat_lbs REAL,
                    standing_vertical_jump_in REAL,
                    rotational_scoop_toss_ft REAL,
                    cable_chop_lbs REAL,
                    max_exit_velocity_mph REAL,
                    estimated_bench_1rm_lbs REAL,
                    estimated_back_squat_1rm_lbs REAL,
                    estimated_deadlift_1rm_lbs REAL,
                    estimated_reverse_lunge_1rm_lbs REAL,
                    estimated_dumbbell_row_1rm_lbs REAL,
                    med_ball_chest_pass_ft REAL,
                    position TEXT,
                    goal TEXT,
                    phase TEXT,
                    days_per_week INTEGER,
                    injuries TEXT,
                    is_admin INTEGER DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    workout_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS completed_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    workout_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    exercise_id TEXT,
                    exercise_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    phase TEXT,
                    weight REAL,
                    reps INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS performance_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    exit_velocity_mph REAL,
                    throw_velocity_mph REAL,
                    dash_60_time_s REAL,
                    broad_jump_in REAL,
                    lateral_broad_jump_in REAL,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS exercises (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    name TEXT NOT NULL,
                    movement_family TEXT,
                    pattern TEXT,
                    muscle_mass TEXT,
                    unilateral INTEGER,
                    sort_order INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
        if _is_postgres():
            existing_logs = {
                row["column_name"]
                for row in conn.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'completed_logs'
                    """
                ).fetchall()
            }
            if "exercise_id" not in existing_logs:
                conn.execute("ALTER TABLE completed_logs ADD COLUMN IF NOT EXISTS exercise_id TEXT")
        else:
            existing_logs = {row["name"] for row in conn.execute("PRAGMA table_info(completed_logs)").fetchall()}
            if "exercise_id" not in existing_logs:
                conn.execute("ALTER TABLE completed_logs ADD COLUMN exercise_id TEXT")
    conn.close()
    _load_exercise_library()


def _ensure_user_columns() -> None:
    conn = _db()
    if _is_postgres():
        existing = {
            row["column_name"]
            for row in conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'users'
                """
            ).fetchall()
        }
    else:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    required = {
        "full_name": "TEXT",
        "dob": "TEXT",
        "height_in": "REAL",
        "weight_lbs": "REAL",
        "max_bench_lbs": "REAL",
        "max_deadlift_lbs": "REAL",
        "max_back_squat_lbs": "REAL",
        "standing_vertical_jump_in": "REAL",
        "rotational_scoop_toss_ft": "REAL",
        "cable_chop_lbs": "REAL",
        "max_exit_velocity_mph": "REAL",
        "estimated_bench_1rm_lbs": "REAL",
        "estimated_back_squat_1rm_lbs": "REAL",
        "estimated_deadlift_1rm_lbs": "REAL",
        "estimated_reverse_lunge_1rm_lbs": "REAL",
        "estimated_dumbbell_row_1rm_lbs": "REAL",
        "med_ball_chest_pass_ft": "REAL",
        "position": "TEXT",
        "goal": "TEXT",
        "phase": "TEXT",
        "days_per_week": "INTEGER",
        "injuries": "TEXT",
        "is_admin": "INTEGER DEFAULT 0",
    }
    for name, col_type in required.items():
        if name not in existing:
            if _is_postgres():
                conn.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {col_type}")
            else:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {col_type}")
    if _is_postgres():
        conn.raw.commit()
    # Backfill from legacy field name if present.
    if (not _is_postgres()) and "cable_chop_distance_ft" in existing and "cable_chop_lbs" in {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}:
        conn.execute(
            """
            UPDATE users
            SET cable_chop_lbs = cable_chop_distance_ft
            WHERE cable_chop_lbs IS NULL AND cable_chop_distance_ft IS NOT NULL
            """
        )
    conn.close()


def _get_user_id() -> str | None:
    return session.get("user_id")


def _current_user_email() -> str | None:
    user_id = _get_user_id()
    if not user_id:
        return None
    conn = _db()
    row = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row["email"] if row else None


def _current_user_profile() -> dict | None:
    user_id = _get_user_id()
    if not user_id:
        return None
    conn = _db()
    row = conn.execute(
        """
        SELECT id, email, full_name, dob, height_in, weight_lbs, max_bench_lbs, max_deadlift_lbs, max_back_squat_lbs,
               standing_vertical_jump_in, rotational_scoop_toss_ft, cable_chop_lbs, max_exit_velocity_mph, med_ball_chest_pass_ft,
               estimated_bench_1rm_lbs, estimated_back_squat_1rm_lbs, estimated_deadlift_1rm_lbs,
               estimated_reverse_lunge_1rm_lbs, estimated_dumbbell_row_1rm_lbs,
               position, goal, phase, days_per_week, injuries, is_admin
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _is_admin() -> bool:
    profile = _current_user_profile()
    return bool(profile and profile.get("is_admin") == 1)


def _age_from_dob(dob: str | None) -> int:
    if not dob:
        return 24
    try:
        birth = datetime.strptime(dob, "%Y-%m-%d").date()
    except ValueError:
        return 24
    today = datetime.now().date()
    years = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        years -= 1
    return max(years, 0)


def _parse_float(raw: str | None, min_val: float | None = None, max_val: float | None = None) -> float | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        num = float(value)
    except ValueError:
        return None
    if min_val is not None and num < min_val:
        return None
    if max_val is not None and num > max_val:
        return None
    return num


def _parse_int(raw: str | None, min_val: int | None = None, max_val: int | None = None) -> int | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        num = int(value)
    except ValueError:
        return None
    if min_val is not None and num < min_val:
        return None
    if max_val is not None and num > max_val:
        return None
    return num


def _validate_float_field(
    raw: str | None,
    label: str,
    min_val: float | None = None,
    max_val: float | None = None,
) -> tuple[float | None, str | None]:
    if raw is None or not raw.strip():
        return None, None
    value = _parse_float(raw, min_val=min_val, max_val=max_val)
    if value is None:
        bounds = []
        if min_val is not None:
            bounds.append(f">= {min_val}")
        if max_val is not None:
            bounds.append(f"<= {max_val}")
        bound_text = f" ({', '.join(bounds)})" if bounds else ""
        return None, f"{label} must be a valid number{bound_text}."
    return value, None


def _validate_int_field(
    raw: str | None,
    label: str,
    min_val: int | None = None,
    max_val: int | None = None,
) -> tuple[int | None, str | None]:
    if raw is None or not raw.strip():
        return None, None
    value = _parse_int(raw, min_val=min_val, max_val=max_val)
    if value is None:
        bounds = []
        if min_val is not None:
            bounds.append(f">= {min_val}")
        if max_val is not None:
            bounds.append(f"<= {max_val}")
        bound_text = f" ({', '.join(bounds)})" if bounds else ""
        return None, f"{label} must be a valid whole number{bound_text}."
    return value, None


def _fetch_history(user_id: str) -> list[dict]:
    conn = _db()
    rows = conn.execute(
        "SELECT date, exercise_id, exercise_name, category, phase, weight, reps FROM completed_logs WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _fetch_completed_logs(user_id: str) -> list[dict]:
    conn = _db()
    rows = conn.execute(
        """
        SELECT id, workout_id, date, exercise_id, exercise_name, category, phase, weight, reps
        FROM completed_logs
        WHERE user_id = ?
        ORDER BY date DESC, workout_id DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _fetch_performance_logs(user_id: str) -> list[dict]:
    conn = _db()
    rows = conn.execute(
        """
        SELECT id, date, exit_velocity_mph, throw_velocity_mph, dash_60_time_s,
               broad_jump_in, lateral_broad_jump_in, notes
        FROM performance_logs
        WHERE user_id = ?
        ORDER BY date DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _group_logs_by_workout(logs: list[dict]) -> list[dict]:
    groups = []
    by_key = {}
    for log in logs:
        key = (log.get("workout_id"), log.get("date"))
        if key not in by_key:
            group = {
                "workout_id": log.get("workout_id"),
                "date": log.get("date"),
                "entries": [],
            }
            by_key[key] = group
            groups.append(group)
        by_key[key]["entries"].append(log)
    return groups


def _load_exercise_library() -> dict:
    conn = _db()
    # Ensure warm-up sequence is updated once after migrations.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    meta = conn.execute("SELECT value FROM app_meta WHERE key = 'warmup_version'").fetchone()
    current_version = int(meta["value"]) if meta and meta["value"] and str(meta["value"]).isdigit() else 0
    if current_version < WARMUP_VERSION:
        with conn:
            conn.execute("DELETE FROM exercises WHERE category = ?", ("warmup",))
            sort_order = 0
            for item in WARMUP_SEQUENCE:
                sort_order += 1
                conn.execute(
                    """
                    INSERT INTO exercises
                    (id, category, name, movement_family, pattern, muscle_mass, unilateral, sort_order, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"warmup:{uuid.uuid4().hex[:8]}",
                        "warmup",
                        item,
                        None,
                        None,
                        None,
                        None,
                        sort_order,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
            if _is_postgres():
                conn.execute(
                    "INSERT INTO app_meta (key, value) VALUES ('warmup_version', ?) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (str(WARMUP_VERSION),),
                )
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('warmup_version', ?)",
                    (str(WARMUP_VERSION),),
                )
    count_row = conn.execute("SELECT COUNT(*) AS cnt FROM exercises").fetchone()
    count = count_row["cnt"] if count_row else 0
    if count == 0:
        seed = json.loads(EXERCISE_LIBRARY_PATH.read_text())
        sort_order = 0
        for category, items in seed.items():
            if not isinstance(items, list):
                continue
            for ex in items:
                sort_order += 1
                if isinstance(ex, str):
                    conn.execute(
                        """
                        INSERT INTO exercises
                        (id, category, name, movement_family, pattern, muscle_mass, unilateral, sort_order, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{category}:{uuid.uuid4().hex[:8]}",
                            category,
                            ex,
                            None,
                            None,
                            None,
                            None,
                            sort_order,
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                    continue
                if not isinstance(ex, dict):
                    continue
                ex_id = ex.get("id") or f"{category}:{uuid.uuid4().hex[:8]}"
                movement_family = ex.get("movement_family") or _infer_movement_family(ex.get("name", ""))
                conn.execute(
                    """
                    INSERT INTO exercises
                    (id, category, name, movement_family, pattern, muscle_mass, unilateral, sort_order, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ex_id,
                        category,
                        ex.get("name") or "",
                        movement_family,
                        ex.get("pattern") or "unknown",
                        ex.get("muscle_mass") or "medium",
                        1 if ex.get("unilateral") else 0,
                        sort_order,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
        conn.raw.commit()

    conn.close()
    conn = _db()
    rows = conn.execute(
        """
        SELECT id, category, name, movement_family, pattern, muscle_mass, unilateral
        FROM exercises
        ORDER BY category, sort_order, name
        """
    ).fetchall()
    conn.close()
    data: dict[str, list] = {}
    for row in rows:
        category = row["category"]
        if category == "warmup":
            data.setdefault(category, []).append(row["name"])
            continue
        data.setdefault(category, []).append({
            "id": row["id"],
            "name": row["name"],
            "movement_family": row["movement_family"] or _infer_movement_family(row["name"]),
            "pattern": row["pattern"] or "unknown",
            "muscle_mass": row["muscle_mass"] or "medium",
            "unilateral": bool(row["unilateral"]) if row["unilateral"] is not None else False,
        })
    # Keep runtime generator in sync without restart.
    work_gen.EXERCISE_LIBRARY = data
    return data


def _save_exercise_library(data: dict) -> None:
    conn = _db()
    conn.execute("DELETE FROM exercises")
    sort_order = 0
    for category, items in data.items():
        if not isinstance(items, list):
            continue
        for ex in items:
            sort_order += 1
            if isinstance(ex, str):
                conn.execute(
                    """
                    INSERT INTO exercises
                    (id, category, name, movement_family, pattern, muscle_mass, unilateral, sort_order, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{category}:{uuid.uuid4().hex[:8]}",
                        category,
                        ex,
                        None,
                        None,
                        None,
                        None,
                        sort_order,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                continue
            if not isinstance(ex, dict):
                continue
            ex_id = ex.get("id") or f"{category}:{uuid.uuid4().hex[:8]}"
            movement_family = ex.get("movement_family") or _infer_movement_family(ex.get("name", ""))
            conn.execute(
                """
                INSERT INTO exercises
                (id, category, name, movement_family, pattern, muscle_mass, unilateral, sort_order, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ex_id,
                    category,
                    ex.get("name") or "",
                    movement_family,
                    ex.get("pattern") or "unknown",
                    ex.get("muscle_mass") or "medium",
                    1 if ex.get("unilateral") else 0,
                    sort_order,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
    conn.raw.commit()
    conn.close()
    work_gen.EXERCISE_LIBRARY = data


def _infer_movement_family(name: str) -> str:
    n = (name or "").lower()
    if "bench" in n:
        return "bench_press"
    if "back squat" in n:
        return "back_squat"
    if "deadlift" in n and "straight-leg" not in n:
        return "deadlift"
    if "reverse lunge" in n:
        return "reverse_lunge"
    if "dumbbell row" in n:
        return "dumbbell_row"
    return "general"


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    idx = (len(vals) - 1) * p
    low = int(idx)
    high = min(low + 1, len(vals) - 1)
    frac = idx - low
    return vals[low] * (1 - frac) + vals[high] * frac


def _benchmark_recommendation(
    user_id: str,
    height_in: float | None,
    max_bench_lbs: float | None,
    med_ball_chest_pass_ft: float | None,
    max_deadlift_lbs: float | None,
    max_back_squat_lbs: float | None,
    standing_vertical_jump_in: float | None,
    rotational_scoop_toss_ft: float | None,
    cable_chop_lbs: float | None,
    max_exit_velocity_mph: float | None,
) -> dict:
    if (
        not height_in
        or not max_bench_lbs
        or not med_ball_chest_pass_ft
        or not max_deadlift_lbs
        or not max_back_squat_lbs
        or not standing_vertical_jump_in
    ):
        return {
            "status": "insufficient_data",
            "message": "Add height, max bench, med-ball chest pass, max deadlift, max back squat, and standing vertical jump to unlock full benchmark recommendations.",
        }

    # 2-inch height buckets for peer comparisons
    bucket_min = int(height_in // 2) * 2
    bucket_max = bucket_min + 1.999

    conn = _db()
    rows = conn.execute(
        """
        SELECT max_bench_lbs, med_ball_chest_pass_ft, max_deadlift_lbs, max_back_squat_lbs, standing_vertical_jump_in, max_exit_velocity_mph
        FROM users
        WHERE id != ?
          AND height_in BETWEEN ? AND ?
          AND max_bench_lbs IS NOT NULL
          AND med_ball_chest_pass_ft IS NOT NULL
          AND max_deadlift_lbs IS NOT NULL
          AND max_back_squat_lbs IS NOT NULL
          AND standing_vertical_jump_in IS NOT NULL
          AND max_exit_velocity_mph IS NOT NULL
        """,
        (user_id, bucket_min, bucket_max),
    ).fetchall()

    rot_rows = conn.execute(
        """
        SELECT rotational_scoop_toss_ft, cable_chop_lbs
        FROM users
        WHERE id != ?
          AND height_in BETWEEN ? AND ?
          AND rotational_scoop_toss_ft IS NOT NULL
          AND cable_chop_lbs IS NOT NULL
        """,
        (user_id, bucket_min, bucket_max),
    ).fetchall()
    conn.close()

    if len(rows) < 3:
        return {
            "status": "insufficient_peers",
            "message": "Not enough peer data in your height range yet. Keep logging users to improve comparisons.",
            "peer_count": len(rows),
        }

    avg_bench = sum(r["max_bench_lbs"] for r in rows) / len(rows)
    avg_pass = sum(r["med_ball_chest_pass_ft"] for r in rows) / len(rows)
    avg_deadlift = sum(r["max_deadlift_lbs"] for r in rows) / len(rows)
    avg_back_squat = sum(r["max_back_squat_lbs"] for r in rows) / len(rows)
    avg_vertical_jump = sum(r["standing_vertical_jump_in"] for r in rows) / len(rows)
    avg_exit_velocity = sum(r["max_exit_velocity_mph"] for r in rows) / len(rows)
    bench_ratio = max_bench_lbs / avg_bench if avg_bench else 1.0
    pass_ratio = med_ball_chest_pass_ft / avg_pass if avg_pass else 1.0
    deadlift_ratio = max_deadlift_lbs / avg_deadlift if avg_deadlift else 1.0
    back_squat_ratio = max_back_squat_lbs / avg_back_squat if avg_back_squat else 1.0
    vertical_jump_ratio = standing_vertical_jump_in / avg_vertical_jump if avg_vertical_jump else 1.0
    exit_velocity_ratio = max_exit_velocity_mph / avg_exit_velocity if avg_exit_velocity and max_exit_velocity_mph else None

    upper_strength = bench_ratio
    upper_power = pass_ratio
    upper_profile = (upper_power / upper_strength) if upper_strength else 1.0

    lower_strength = (deadlift_ratio + back_squat_ratio) / 2
    lower_power = vertical_jump_ratio
    lower_profile = (lower_power / lower_strength) if lower_strength else 1.0

    core_focus = "balanced_priority"
    rotation_profile = None
    avg_rot_toss = None
    avg_rot_chop = None
    if rotational_scoop_toss_ft and cable_chop_lbs and len(rot_rows) >= 3:
        avg_rot_toss = sum(r["rotational_scoop_toss_ft"] for r in rot_rows) / len(rot_rows)
        avg_rot_chop = sum(r["cable_chop_lbs"] for r in rot_rows) / len(rot_rows)
        toss_ratio = rotational_scoop_toss_ft / avg_rot_toss if avg_rot_toss else 1.0
        chop_ratio = cable_chop_lbs / avg_rot_chop if avg_rot_chop else 1.0
        rotation_profile = (toss_ratio / chop_ratio) if chop_ratio else 1.0
        if rotation_profile < 0.95:
            core_focus = "power_speed_priority"
            core_reason = "Rotational toss is lagging cable chop strength vs peers."
        elif rotation_profile > 1.05:
            core_focus = "strength_priority"
            core_reason = "Rotational toss is ahead of cable chop strength vs peers."
        else:
            core_reason = "Rotational power and rotational strength are balanced vs peers."
    else:
        core_reason = "Need rotational toss and cable chop inputs (and peers) to personalize core focus."

    if upper_profile < 0.95:
        upper_focus = "power_speed_priority"
        upper_reason = "Upper power (chest pass) lags upper strength (bench) vs peers."
    elif upper_profile > 1.05:
        upper_focus = "strength_priority"
        upper_reason = "Upper power is ahead of upper strength vs peers."
    else:
        upper_focus = "balanced_priority"
        upper_reason = "Upper power and strength are balanced vs peers."

    if lower_profile < 0.95:
        lower_focus = "power_speed_priority"
        lower_reason = "Lower power (vertical jump) lags lower strength (deadlift/squat) vs peers."
    elif lower_profile > 1.05:
        lower_focus = "strength_priority"
        lower_reason = "Lower power is ahead of lower strength vs peers."
    else:
        lower_focus = "balanced_priority"
        lower_reason = "Lower power and strength are balanced vs peers."

    exit_velocity_note = None
    if exit_velocity_ratio is not None:
        # First evaluate exit velo directly versus peers.
        if exit_velocity_ratio < 0.9:
            if rotation_profile is not None and rotation_profile >= 0.95:
                exit_velocity_note = "Exit velocity is well below peers despite a decent rotational profile. Likely transfer/technique bottleneck."
            else:
                exit_velocity_note = "Exit velocity is well below peers. Build rotational power and transfer mechanics."
        elif exit_velocity_ratio < 0.98:
            exit_velocity_note = "Exit velocity is slightly below peers. Keep emphasizing rotational power and quality contact."
        elif exit_velocity_ratio > 1.1 and rotation_profile is not None and rotation_profile < 0.95:
            exit_velocity_note = "Exit velocity is strong, but rotational profile is lagging peers. You may be relying on non-rotational compensations."
        else:
            exit_velocity_note = "Exit velocity is tracking reasonably with peers."

    if upper_focus == "power_speed_priority" or lower_focus == "power_speed_priority":
        overall_focus = "power_speed_priority"
        message = "You show a power-speed gap in at least one profile. Bias training toward explosive work there."
    elif upper_focus == "strength_priority" and lower_focus == "strength_priority":
        overall_focus = "strength_priority"
        message = "You are power-efficient relative to strength. You can emphasize strength progression."
    else:
        overall_focus = "balanced_priority"
        message = "You are relatively balanced. Keep a mixed strength + power approach."

    return {
        "status": "ok",
        "focus": overall_focus,
        "upper_focus": upper_focus,
        "lower_focus": lower_focus,
        "core_focus": core_focus,
        "upper_reason": upper_reason,
        "lower_reason": lower_reason,
        "core_reason": core_reason,
        "overall_focus": overall_focus,
        "message": message,
        "peer_count": len(rows),
        "height_bucket": f"{bucket_min:.0f}-{bucket_max:.1f} in",
        "bench_ratio": round(bench_ratio, 2),
        "pass_ratio": round(pass_ratio, 2),
        "deadlift_ratio": round(deadlift_ratio, 2),
        "back_squat_ratio": round(back_squat_ratio, 2),
        "vertical_jump_ratio": round(vertical_jump_ratio, 2),
        "exit_velocity_ratio": round(exit_velocity_ratio, 2) if exit_velocity_ratio is not None else None,
        "peer_avg_bench_lbs": round(avg_bench, 1),
        "peer_avg_med_ball_ft": round(avg_pass, 1),
        "peer_avg_deadlift_lbs": round(avg_deadlift, 1),
        "peer_avg_back_squat_lbs": round(avg_back_squat, 1),
        "peer_avg_vertical_jump_in": round(avg_vertical_jump, 1),
        "peer_avg_exit_velocity_mph": round(avg_exit_velocity, 1),
        "peer_avg_rotational_scoop_toss_ft": round(avg_rot_toss, 1) if avg_rot_toss else None,
        "peer_avg_cable_chop_lbs": round(avg_rot_chop, 1) if avg_rot_chop else None,
        "rotation_profile_ratio": round(rotation_profile, 2) if rotation_profile else None,
        "rotation_peer_count": len(rot_rows),
        "upper_profile_ratio": round(upper_profile, 2),
        "lower_profile_ratio": round(lower_profile, 2),
        "exit_velocity_note": exit_velocity_note,
    }


def _estimate_1rm(user_id: str, movement_families: list[str], fallback_keywords: list[str]) -> float | None:
    library = _load_exercise_library()
    id_to_family = {}
    for items in library.values():
        if not isinstance(items, list):
            continue
        for ex in items:
            if isinstance(ex, dict) and ex.get("id"):
                id_to_family[ex["id"]] = ex.get("movement_family", "general")

    conn = _db()
    rows = conn.execute(
        """
        SELECT weight, reps, exercise_id, exercise_name
        FROM completed_logs
        WHERE user_id = ?
          AND weight IS NOT NULL
          AND reps IS NOT NULL
          AND reps > 0
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return None
    estimates = []
    for row in rows:
        exercise_name = (row["exercise_name"] or "").lower()
        exercise_id = row["exercise_id"]
        family = id_to_family.get(exercise_id) if exercise_id else None
        if family not in movement_families:
            if not any(keyword in exercise_name for keyword in fallback_keywords):
                continue
        weight = row["weight"]
        reps = row["reps"]
        est_1rm = weight * (1 + (reps / 30.0))
        estimates.append(est_1rm)
    return round(max(estimates), 1) if estimates else None


def _refresh_estimated_lifts(user_id: str) -> None:
    est_bench = _estimate_1rm(user_id, ["bench_press"], ["bench"])
    est_back_squat = _estimate_1rm(user_id, ["back_squat"], ["barbell back squat", "back squat"])
    est_deadlift = _estimate_1rm(user_id, ["deadlift"], ["barbell deadlift", "trap bar deadlift", "deadlift"])
    est_reverse_lunge = _estimate_1rm(user_id, ["reverse_lunge"], ["reverse lunge", "front-loaded reverse lunge"])
    est_dumbbell_row = _estimate_1rm(user_id, ["dumbbell_row"], ["dumbbell row"])
    conn = _db()
    with conn:
        conn.execute(
            """
            UPDATE users
            SET estimated_bench_1rm_lbs = ?,
                estimated_back_squat_1rm_lbs = ?,
                estimated_deadlift_1rm_lbs = ?,
                estimated_reverse_lunge_1rm_lbs = ?,
                estimated_dumbbell_row_1rm_lbs = ?
            WHERE id = ?
            """,
            (
                est_bench,
                est_back_squat,
                est_deadlift,
                est_reverse_lunge,
                est_dumbbell_row,
                user_id,
            ),
        )
    conn.close()


def _save_workout(user_id: str, workout: dict) -> int:
    conn = _db()
    with conn:
        if _is_postgres():
            cursor = conn.execute(
                "INSERT INTO workouts (user_id, created_at, workout_json) VALUES (?, ?, ?) RETURNING id",
                (user_id, datetime.now().isoformat(timespec="seconds"), json.dumps(workout)),
            )
            workout_id = cursor.fetchone()["id"]
        else:
            cursor = conn.execute(
                "INSERT INTO workouts (user_id, created_at, workout_json) VALUES (?, ?, ?)",
                (user_id, datetime.now().isoformat(timespec="seconds"), json.dumps(workout)),
            )
            workout_id = cursor.lastrowid
    conn.close()
    return int(workout_id)


def _recent_workouts(user_id: str, days: int = 7) -> list[dict]:
    conn = _db()
    rows = conn.execute(
        "SELECT created_at, workout_json FROM workouts WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
        (user_id,),
    ).fetchall()
    conn.close()
    cutoff = datetime.now() - timedelta(days=days)
    recent = []
    for row in rows:
        created_raw = row.get("created_at") if isinstance(row, dict) else row["created_at"]
        try:
            created = datetime.fromisoformat(created_raw)
        except (TypeError, ValueError):
            continue
        if created >= cutoff:
            recent.append({"created_at": created_raw, "workout_json": row["workout_json"]})
    return recent


def _workout_entries(workout: dict) -> list[dict]:
    entries = []
    for key, category in [
        ("main_lift_lower", "lower"),
        ("main_lift_upper_push", "upper_push"),
        ("main_lift_upper_pull", "upper_pull"),
        ("core", "core"),
    ]:
        block = workout.get(key)
        if not block:
            continue
        entries.append({
            "exercise_id": block["exercise"].get("id"),
            "exercise_name": block["exercise"]["name"],
            "category": category,
        })
    for block in workout.get("accessories", []):
        entries.append({
            "exercise_id": block["exercise"].get("id"),
            "exercise_name": block["exercise"]["name"],
            "category": "accessory",
        })
    return entries


def _fetch_workout(user_id: str, workout_id: int) -> dict | None:
    conn = _db()
    row = conn.execute(
        "SELECT workout_json FROM workouts WHERE id = ? AND user_id = ?",
        (workout_id, user_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return json.loads(row["workout_json"])


def _is_workout_logged(user_id: str, workout_id: int) -> bool:
    conn = _db()
    row = conn.execute(
        "SELECT 1 FROM completed_logs WHERE user_id = ? AND workout_id = ? LIMIT 1",
        (user_id, workout_id),
    ).fetchone()
    conn.close()
    return row is not None


@app.route("/", methods=["GET"])
def index():
    _init_db()
    _ensure_user_columns()
    profile = _current_user_profile()
    if not profile:
        return redirect(url_for("login"))
    return render_template("index.html", profile=profile)


@app.route("/generate", methods=["POST"])
def generate():
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))
    _refresh_estimated_lifts(user_id)

    profile = _current_user_profile()
    if not profile:
        return redirect(url_for("login"))

    athlete = {
        "age": _age_from_dob(profile.get("dob")),
        "position": (profile.get("position") or "outfielder").lower(),
        "injuries": [s.strip().lower() for s in (profile.get("injuries") or "").split(",") if s.strip()],
        "goal": (profile.get("goal") or "power").lower(),
        "phase": (profile.get("phase") or "offseason").lower(),
        "days_per_week": profile.get("days_per_week") or 3,
    }

    benchmark_bench = profile.get("estimated_bench_1rm_lbs") or profile.get("max_bench_lbs")
    benchmark = _benchmark_recommendation(
        user_id=user_id,
        height_in=profile.get("height_in"),
        max_bench_lbs=benchmark_bench,
        med_ball_chest_pass_ft=profile.get("med_ball_chest_pass_ft"),
        max_deadlift_lbs=profile.get("estimated_deadlift_1rm_lbs") or profile.get("max_deadlift_lbs"),
        max_back_squat_lbs=profile.get("estimated_back_squat_1rm_lbs") or profile.get("max_back_squat_lbs"),
        standing_vertical_jump_in=profile.get("standing_vertical_jump_in"),
        rotational_scoop_toss_ft=profile.get("rotational_scoop_toss_ft"),
        cable_chop_lbs=profile.get("cable_chop_lbs"),
        max_exit_velocity_mph=profile.get("max_exit_velocity_mph"),
    )
    history = _fetch_history(user_id)
    recent_workouts = _recent_workouts(user_id, days=7)
    days_per_week = athlete.get("days_per_week") or 3
    day_index = len(recent_workouts) % max(days_per_week, 1)
    workout = work_gen.generate_workout(athlete, history=history, focus=benchmark, day_index=day_index)
    caps = work_gen.compute_history_caps_from_history(history, athlete["phase"], workout, days=7)

    workout_id = _save_workout(user_id, workout)
    exercise_entries = _workout_entries(workout)

    return render_template(
        "result.html",
        athlete=athlete,
        profile=profile,
        workout=workout,
        workout_id=workout_id,
        exercise_entries=exercise_entries,
        already_logged=False,
        caps=caps,
        benchmark=benchmark,
        workout_date=datetime.now().strftime("%Y-%m-%d"),
    )


@app.route("/reset", methods=["POST"])
def reset():
    user_id = _get_user_id()
    if user_id:
        conn = _db()
        with conn:
            conn.execute("DELETE FROM completed_logs WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM workouts WHERE user_id = ?", (user_id,))
        conn.close()
    return redirect(url_for("index"))


@app.route("/log/<int:workout_id>", methods=["POST"])
def log_workout_web(workout_id: int):
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))
    _refresh_estimated_lifts(user_id)

    workout = _fetch_workout(user_id, workout_id)
    profile = _current_user_profile()
    if not workout or not profile:
        return redirect(url_for("index"))
    form_error = None

    athlete = {
        "age": _age_from_dob(profile.get("dob")),
        "position": (profile.get("position") or "outfielder").lower(),
        "injuries": [s.strip().lower() for s in (profile.get("injuries") or "").split(",") if s.strip()],
        "goal": (profile.get("goal") or "power").lower(),
        "phase": (profile.get("phase") or "offseason").lower(),
    }

    if _is_workout_logged(user_id, workout_id):
        history = _fetch_history(user_id)
        caps = work_gen.compute_history_caps_from_history(history, athlete["phase"], workout, days=7)
        benchmark_bench = profile.get("estimated_bench_1rm_lbs") or profile.get("max_bench_lbs")
        benchmark = _benchmark_recommendation(
            user_id=user_id,
            height_in=profile.get("height_in"),
            max_bench_lbs=benchmark_bench,
            med_ball_chest_pass_ft=profile.get("med_ball_chest_pass_ft"),
            max_deadlift_lbs=profile.get("estimated_deadlift_1rm_lbs") or profile.get("max_deadlift_lbs"),
            max_back_squat_lbs=profile.get("estimated_back_squat_1rm_lbs") or profile.get("max_back_squat_lbs"),
            standing_vertical_jump_in=profile.get("standing_vertical_jump_in"),
            rotational_scoop_toss_ft=profile.get("rotational_scoop_toss_ft"),
            cable_chop_lbs=profile.get("cable_chop_lbs"),
            max_exit_velocity_mph=profile.get("max_exit_velocity_mph"),
        )
        return render_template(
            "result.html",
            athlete=athlete,
            profile=profile,
            workout=workout,
            workout_id=workout_id,
            exercise_entries=_workout_entries(workout),
            already_logged=True,
            caps=caps,
            benchmark=benchmark,
            workout_date=request.form.get("log_date") or datetime.now().strftime("%Y-%m-%d"),
        )

    log_date = request.form.get("log_date", "").strip() or datetime.now().strftime("%Y-%m-%d")
    rows = []
    for entry in _workout_entries(workout):
        exercise_id = entry["exercise_id"] or entry["exercise_name"]
        exercise_name = entry["exercise_name"]
        category = entry["category"]
        weight_raw = request.form.get(f"weight::{exercise_id}", "").strip()
        reps_raw = request.form.get(f"reps::{exercise_id}", "").strip()
        weight, weight_err = _validate_float_field(weight_raw, f"{exercise_name} weight", min_val=0)
        reps, reps_err = _validate_int_field(reps_raw, f"{exercise_name} reps", min_val=0)
        if weight_err or reps_err:
            form_error = weight_err or reps_err
            break
        rows.append((user_id, workout_id, log_date, entry["exercise_id"], exercise_name, category, athlete["phase"], weight, reps))

    if form_error:
        history = _fetch_history(user_id)
        caps = work_gen.compute_history_caps_from_history(history, athlete["phase"], workout, days=7)
        benchmark_bench = profile.get("estimated_bench_1rm_lbs") or profile.get("max_bench_lbs")
        benchmark = _benchmark_recommendation(
            user_id=user_id,
            height_in=profile.get("height_in"),
            max_bench_lbs=benchmark_bench,
            med_ball_chest_pass_ft=profile.get("med_ball_chest_pass_ft"),
            max_deadlift_lbs=profile.get("estimated_deadlift_1rm_lbs") or profile.get("max_deadlift_lbs"),
            max_back_squat_lbs=profile.get("estimated_back_squat_1rm_lbs") or profile.get("max_back_squat_lbs"),
            standing_vertical_jump_in=profile.get("standing_vertical_jump_in"),
            rotational_scoop_toss_ft=profile.get("rotational_scoop_toss_ft"),
            cable_chop_lbs=profile.get("cable_chop_lbs"),
            max_exit_velocity_mph=profile.get("max_exit_velocity_mph"),
        )
        return render_template(
            "result.html",
            athlete=athlete,
            profile=profile,
            workout=workout,
            workout_id=workout_id,
            exercise_entries=_workout_entries(workout),
            already_logged=False,
            caps=caps,
            benchmark=benchmark,
            workout_date=log_date,
            error=form_error,
        )

    conn = _db()
    with conn:
        conn.executemany(
            """
            INSERT INTO completed_logs (user_id, workout_id, date, exercise_id, exercise_name, category, phase, weight, reps)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    conn.close()
    _refresh_estimated_lifts(user_id)
    profile = _current_user_profile()

    history = _fetch_history(user_id)
    caps = work_gen.compute_history_caps_from_history(history, athlete["phase"], workout, days=7)
    benchmark_bench = profile.get("estimated_bench_1rm_lbs") or profile.get("max_bench_lbs")
    benchmark = _benchmark_recommendation(
        user_id=user_id,
        height_in=profile.get("height_in"),
        max_bench_lbs=benchmark_bench,
        med_ball_chest_pass_ft=profile.get("med_ball_chest_pass_ft"),
        max_deadlift_lbs=profile.get("estimated_deadlift_1rm_lbs") or profile.get("max_deadlift_lbs"),
        max_back_squat_lbs=profile.get("estimated_back_squat_1rm_lbs") or profile.get("max_back_squat_lbs"),
        standing_vertical_jump_in=profile.get("standing_vertical_jump_in"),
        rotational_scoop_toss_ft=profile.get("rotational_scoop_toss_ft"),
        cable_chop_lbs=profile.get("cable_chop_lbs"),
        max_exit_velocity_mph=profile.get("max_exit_velocity_mph"),
    )
    return render_template(
        "result.html",
        athlete=athlete,
        profile=profile,
        workout=workout,
        workout_id=workout_id,
        exercise_entries=_workout_entries(workout),
        already_logged=True,
        caps=caps,
        benchmark=benchmark,
        workout_date=log_date,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    _init_db()
    _ensure_user_columns()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        full_name = request.form.get("full_name", "").strip()
        dob = request.form.get("dob", "").strip()
        height_in_raw = request.form.get("height_in", "").strip()
        weight_lbs_raw = request.form.get("weight_lbs", "").strip()
        max_bench_raw = request.form.get("max_bench_lbs", "").strip()
        max_deadlift_raw = request.form.get("max_deadlift_lbs", "").strip()
        max_back_squat_raw = request.form.get("max_back_squat_lbs", "").strip()
        vertical_jump_raw = request.form.get("standing_vertical_jump_in", "").strip()
        rotational_scoop_toss_raw = request.form.get("rotational_scoop_toss_ft", "").strip()
        cable_chop_lbs_raw = request.form.get("cable_chop_lbs", "").strip()
        max_exit_velocity_raw = request.form.get("max_exit_velocity_mph", "").strip()
        med_ball_raw = request.form.get("med_ball_chest_pass_ft", "").strip()
        position = request.form.get("position", "").strip().lower()
        goal = request.form.get("goal", "").strip().lower()
        phase = request.form.get("phase", "").strip().lower()
        days_per_week_raw = request.form.get("days_per_week", "").strip()
        injuries = request.form.get("injuries", "").strip().lower()
        admin_code = request.form.get("admin_code", "").strip()
        errors = []
        height_in, e = _validate_float_field(height_in_raw, "Height", min_val=36, max_val=96)
        if e: errors.append(e)
        weight_lbs, e = _validate_float_field(weight_lbs_raw, "Weight", min_val=50, max_val=600)
        if e: errors.append(e)
        max_bench_lbs, e = _validate_float_field(max_bench_raw, "Max bench", min_val=1)
        if e: errors.append(e)
        max_deadlift_lbs, e = _validate_float_field(max_deadlift_raw, "Max deadlift", min_val=1)
        if e: errors.append(e)
        max_back_squat_lbs, e = _validate_float_field(max_back_squat_raw, "Max back squat", min_val=1)
        if e: errors.append(e)
        standing_vertical_jump_in, e = _validate_float_field(vertical_jump_raw, "Standing vertical jump", min_val=1)
        if e: errors.append(e)
        rotational_scoop_toss_ft, e = _validate_float_field(rotational_scoop_toss_raw, "Rotational scoop toss", min_val=1)
        if e: errors.append(e)
        cable_chop_lbs, e = _validate_float_field(cable_chop_lbs_raw, "Cable chop load", min_val=1)
        if e: errors.append(e)
        max_exit_velocity_mph, e = _validate_float_field(max_exit_velocity_raw, "Ball exit velo", min_val=1)
        if e: errors.append(e)
        med_ball_chest_pass_ft, e = _validate_float_field(med_ball_raw, "Med ball chest pass", min_val=1)
        if e: errors.append(e)
        days_per_week, e = _validate_int_field(days_per_week_raw, "Days per week", min_val=2, max_val=7)
        if e: errors.append(e)
        if days_per_week is None:
            days_per_week = 3
        is_admin = 1 if admin_code and admin_code == ADMIN_REGISTRATION_CODE else 0
        if not email or not password:
            return render_template("register.html", error="Email and password are required.")
        if errors:
            return render_template("register.html", error=" ".join(errors))

        user_id = str(uuid.uuid4())
        password_hash = generate_password_hash(password)
        conn = _db()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO users
                    (id, email, password_hash, created_at, full_name, dob, height_in, weight_lbs, max_bench_lbs, max_deadlift_lbs, max_back_squat_lbs, standing_vertical_jump_in, rotational_scoop_toss_ft, cable_chop_lbs, max_exit_velocity_mph, med_ball_chest_pass_ft, position, goal, phase, days_per_week, injuries, is_admin)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        email,
                        password_hash,
                        datetime.now().isoformat(timespec="seconds"),
                        full_name,
                        dob,
                        height_in,
                        weight_lbs,
                        max_bench_lbs,
                        max_deadlift_lbs,
                        max_back_squat_lbs,
                        standing_vertical_jump_in,
                        rotational_scoop_toss_ft,
                        cable_chop_lbs,
                        max_exit_velocity_mph,
                        med_ball_chest_pass_ft,
                        position,
                        goal,
                        phase,
                        days_per_week,
                        injuries,
                        is_admin,
                    ),
                )
        except sqlite3.IntegrityError:
            conn.close()
            return render_template("register.html", error="Email already exists.")
        conn.close()

        session["user_id"] = user_id
        session.permanent = True
        return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    _init_db()
    _ensure_user_columns()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        conn = _db()
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        conn.close()
        if not row or not check_password_hash(row["password_hash"], password):
            return render_template("login.html", error="Invalid email or password.")
        session["user_id"] = row["id"]
        session.permanent = True
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
def profile():
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        dob = request.form.get("dob", "").strip()
        height_in_raw = request.form.get("height_in", "").strip()
        weight_lbs_raw = request.form.get("weight_lbs", "").strip()
        max_bench_raw = request.form.get("max_bench_lbs", "").strip()
        max_deadlift_raw = request.form.get("max_deadlift_lbs", "").strip()
        max_back_squat_raw = request.form.get("max_back_squat_lbs", "").strip()
        vertical_jump_raw = request.form.get("standing_vertical_jump_in", "").strip()
        rotational_scoop_toss_raw = request.form.get("rotational_scoop_toss_ft", "").strip()
        cable_chop_lbs_raw = request.form.get("cable_chop_lbs", "").strip()
        max_exit_velocity_raw = request.form.get("max_exit_velocity_mph", "").strip()
        med_ball_raw = request.form.get("med_ball_chest_pass_ft", "").strip()
        position = request.form.get("position", "").strip().lower()
        goal = request.form.get("goal", "").strip().lower()
        phase = request.form.get("phase", "").strip().lower()
        days_per_week_raw = request.form.get("days_per_week", "").strip()
        injuries = request.form.get("injuries", "").strip().lower()
        errors = []
        height_in, e = _validate_float_field(height_in_raw, "Height", min_val=36, max_val=96)
        if e: errors.append(e)
        weight_lbs, e = _validate_float_field(weight_lbs_raw, "Weight", min_val=50, max_val=600)
        if e: errors.append(e)
        max_bench_lbs, e = _validate_float_field(max_bench_raw, "Max bench", min_val=1)
        if e: errors.append(e)
        max_deadlift_lbs, e = _validate_float_field(max_deadlift_raw, "Max deadlift", min_val=1)
        if e: errors.append(e)
        max_back_squat_lbs, e = _validate_float_field(max_back_squat_raw, "Max back squat", min_val=1)
        if e: errors.append(e)
        standing_vertical_jump_in, e = _validate_float_field(vertical_jump_raw, "Standing vertical jump", min_val=1)
        if e: errors.append(e)
        rotational_scoop_toss_ft, e = _validate_float_field(rotational_scoop_toss_raw, "Rotational scoop toss", min_val=1)
        if e: errors.append(e)
        cable_chop_lbs, e = _validate_float_field(cable_chop_lbs_raw, "Cable chop load", min_val=1)
        if e: errors.append(e)
        max_exit_velocity_mph, e = _validate_float_field(max_exit_velocity_raw, "Ball exit velo", min_val=1)
        if e: errors.append(e)
        med_ball_chest_pass_ft, e = _validate_float_field(med_ball_raw, "Med ball chest pass", min_val=1)
        if e: errors.append(e)
        days_per_week, e = _validate_int_field(days_per_week_raw, "Days per week", min_val=2, max_val=7)
        if e: errors.append(e)
        if days_per_week is None:
            days_per_week = 3
        if errors:
            profile = _current_user_profile()
            return render_template("profile.html", profile=profile, error=" ".join(errors))
        conn = _db()
        with conn:
            conn.execute(
                """
                UPDATE users
                SET full_name = ?, dob = ?, height_in = ?, weight_lbs = ?, max_bench_lbs = ?, max_deadlift_lbs = ?, max_back_squat_lbs = ?, standing_vertical_jump_in = ?, rotational_scoop_toss_ft = ?, cable_chop_lbs = ?, max_exit_velocity_mph = ?, med_ball_chest_pass_ft = ?,
                    position = ?, goal = ?, phase = ?, days_per_week = ?, injuries = ?
                WHERE id = ?
                """,
                (
                    full_name,
                    dob,
                    height_in,
                    weight_lbs,
                    max_bench_lbs,
                    max_deadlift_lbs,
                    max_back_squat_lbs,
                    standing_vertical_jump_in,
                    rotational_scoop_toss_ft,
                    cable_chop_lbs,
                    max_exit_velocity_mph,
                    med_ball_chest_pass_ft,
                    position,
                    goal,
                    phase,
                    days_per_week,
                    injuries,
                    user_id,
                ),
            )
        conn.close()
        return redirect(url_for("index"))

    profile = _current_user_profile()
    return render_template("profile.html", profile=profile)


@app.route("/history", methods=["GET"])
def history():
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))
    profile = _current_user_profile()
    logs = _fetch_completed_logs(user_id)
    grouped_logs = _group_logs_by_workout(logs)
    return render_template("history.html", profile=profile, grouped_logs=grouped_logs)


@app.route("/performance", methods=["GET", "POST"])
def performance():
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))
    profile = _current_user_profile()

    if request.method == "POST":
        date = request.form.get("date", "").strip() or datetime.now().strftime("%Y-%m-%d")
        exit_velocity_raw = request.form.get("exit_velocity_mph", "").strip()
        throw_velocity_raw = request.form.get("throw_velocity_mph", "").strip()
        dash_60_raw = request.form.get("dash_60_time_s", "").strip()
        broad_jump_raw = request.form.get("broad_jump_in", "").strip()
        lateral_broad_jump_raw = request.form.get("lateral_broad_jump_in", "").strip()
        notes = request.form.get("notes", "").strip()

        errors = []
        exit_velocity_mph, e = _validate_float_field(exit_velocity_raw, "Exit velo", min_val=1)
        if e: errors.append(e)
        throw_velocity_mph, e = _validate_float_field(throw_velocity_raw, "Throw velo", min_val=1)
        if e: errors.append(e)
        dash_60_time_s, e = _validate_float_field(dash_60_raw, "60-yard dash", min_val=1)
        if e: errors.append(e)
        broad_jump_in, e = _validate_float_field(broad_jump_raw, "Broad jump", min_val=1)
        if e: errors.append(e)
        lateral_broad_jump_in, e = _validate_float_field(lateral_broad_jump_raw, "Lateral broad jump", min_val=1)
        if e: errors.append(e)
        if errors:
            logs = _fetch_performance_logs(user_id)
            return render_template("performance.html", profile=profile, logs=logs, today=date, error=" ".join(errors))

        conn = _db()
        with conn:
            conn.execute(
                """
                INSERT INTO performance_logs
                (user_id, date, exit_velocity_mph, throw_velocity_mph, dash_60_time_s, broad_jump_in, lateral_broad_jump_in, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    date,
                    exit_velocity_mph,
                    throw_velocity_mph,
                    dash_60_time_s,
                    broad_jump_in,
                    lateral_broad_jump_in,
                    notes or None,
                ),
            )
        conn.close()
        return redirect(url_for("performance"))

    logs = _fetch_performance_logs(user_id)
    return render_template("performance.html", profile=profile, logs=logs, today=datetime.now().strftime("%Y-%m-%d"))


@app.route("/performance/edit/<int:log_id>", methods=["GET", "POST"])
def edit_performance(log_id: int):
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))

    conn = _db()
    row = conn.execute(
        """
        SELECT id, date, exit_velocity_mph, throw_velocity_mph, dash_60_time_s, broad_jump_in, lateral_broad_jump_in, notes
        FROM performance_logs
        WHERE id = ? AND user_id = ?
        """,
        (log_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return redirect(url_for("performance"))

    if request.method == "POST":
        date = request.form.get("date", "").strip() or row["date"]
        exit_velocity_raw = request.form.get("exit_velocity_mph", "").strip()
        throw_velocity_raw = request.form.get("throw_velocity_mph", "").strip()
        dash_60_raw = request.form.get("dash_60_time_s", "").strip()
        broad_jump_raw = request.form.get("broad_jump_in", "").strip()
        lateral_broad_jump_raw = request.form.get("lateral_broad_jump_in", "").strip()
        notes = request.form.get("notes", "").strip()
        errors = []
        exit_velocity_mph, e = _validate_float_field(exit_velocity_raw, "Exit velo", min_val=1)
        if e: errors.append(e)
        throw_velocity_mph, e = _validate_float_field(throw_velocity_raw, "Throw velo", min_val=1)
        if e: errors.append(e)
        dash_60_time_s, e = _validate_float_field(dash_60_raw, "60-yard dash", min_val=1)
        if e: errors.append(e)
        broad_jump_in, e = _validate_float_field(broad_jump_raw, "Broad jump", min_val=1)
        if e: errors.append(e)
        lateral_broad_jump_in, e = _validate_float_field(lateral_broad_jump_raw, "Lateral broad jump", min_val=1)
        if e: errors.append(e)
        if errors:
            log = dict(row)
            conn.close()
            return render_template("edit_performance.html", log=log, error=" ".join(errors))

        with conn:
            conn.execute(
                """
                UPDATE performance_logs
                SET date = ?, exit_velocity_mph = ?, throw_velocity_mph = ?, dash_60_time_s = ?,
                    broad_jump_in = ?, lateral_broad_jump_in = ?, notes = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    date,
                    exit_velocity_mph,
                    throw_velocity_mph,
                    dash_60_time_s,
                    broad_jump_in,
                    lateral_broad_jump_in,
                    notes or None,
                    log_id,
                    user_id,
                ),
            )
        conn.close()
        return redirect(url_for("performance"))

    log = dict(row)
    conn.close()
    return render_template("edit_performance.html", log=log)


@app.route("/performance/delete/<int:log_id>", methods=["POST"])
def delete_performance(log_id: int):
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))
    conn = _db()
    with conn:
        conn.execute("DELETE FROM performance_logs WHERE id = ? AND user_id = ?", (log_id, user_id))
    conn.close()
    return redirect(url_for("performance"))


@app.errorhandler(Exception)
def handle_unexpected_error(exc: Exception):
    if isinstance(exc, HTTPException):
        return exc
    traceback.print_exc()
    return render_template("error.html"), 500


@app.route("/history/edit/<int:log_id>", methods=["GET", "POST"])
def edit_history_log(log_id: int):
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))

    conn = _db()
    row = conn.execute(
        "SELECT id, workout_id, date, exercise_id, exercise_name, category, phase, weight, reps FROM completed_logs WHERE id = ? AND user_id = ?",
        (log_id, user_id),
    ).fetchone()
    if not row:
        conn.close()
        return redirect(url_for("history"))

    if request.method == "POST":
        date = request.form.get("date", "").strip() or row["date"]
        weight_raw = request.form.get("weight", "").strip()
        reps_raw = request.form.get("reps", "").strip()
        weight = _parse_float(weight_raw, min_val=0)
        reps = _parse_int(reps_raw, min_val=0)
        with conn:
            conn.execute(
                "UPDATE completed_logs SET date = ?, weight = ?, reps = ? WHERE id = ? AND user_id = ?",
                (date, weight, reps, log_id, user_id),
            )
        conn.close()
        return redirect(url_for("history"))

    log = dict(row)
    conn.close()
    return render_template("edit_log.html", log=log)


@app.route("/history/delete/<int:log_id>", methods=["POST"])
def delete_history_log(log_id: int):
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))
    conn = _db()
    with conn:
        conn.execute("DELETE FROM completed_logs WHERE id = ? AND user_id = ?", (log_id, user_id))
    conn.close()
    return redirect(url_for("history"))


@app.route("/admin", methods=["GET"])
def admin_dashboard():
    _init_db()
    _ensure_user_columns()
    user_id = _get_user_id()
    if not user_id:
        return redirect(url_for("login"))
    if not _is_admin():
        return redirect(url_for("index"))

    conn = _db()
    users = conn.execute(
        """
        SELECT u.id, u.email, u.full_name, u.is_admin,
               COUNT(cl.id) AS log_count
        FROM users u
        LEFT JOIN completed_logs cl ON cl.user_id = u.id
        GROUP BY u.id
        ORDER BY u.created_at DESC
        """
    ).fetchall()
    conn.close()
    return render_template("admin.html", users=[dict(u) for u in users])


@app.route("/admin/workouts", methods=["GET"])
def admin_workouts():
    _init_db()
    _ensure_user_columns()
    if not _get_user_id():
        return redirect(url_for("login"))
    if not _is_admin():
        return redirect(url_for("index"))

    conn = _db()
    rows = conn.execute(
        """
        SELECT w.id, w.created_at, w.user_id, w.workout_json,
               u.email, u.full_name
        FROM workouts w
        JOIN users u ON u.id = w.user_id
        ORDER BY w.id DESC
        """
    ).fetchall()
    conn.close()

    workouts = []
    for row in rows:
        workout = json.loads(row["workout_json"])
        workouts.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "user_id": row["user_id"],
            "user_name": row["full_name"] or row["email"],
            "phase": workout.get("main_lift_lower", {}).get("intensity", "-"),
            "total_load_score": workout.get("total_load_score", "-"),
        })
    return render_template("admin_workouts.html", workouts=workouts)


@app.route("/admin/benchmarks", methods=["GET"])
def admin_benchmarks():
    _init_db()
    _ensure_user_columns()
    if not _get_user_id():
        return redirect(url_for("login"))
    if not _is_admin():
        return redirect(url_for("index"))

    conn = _db()
    rows = conn.execute(
        """
        SELECT height_in, max_bench_lbs, med_ball_chest_pass_ft,
               max_deadlift_lbs, max_back_squat_lbs, standing_vertical_jump_in,
               rotational_scoop_toss_ft, cable_chop_lbs, max_exit_velocity_mph
        FROM users
        WHERE height_in IS NOT NULL
        """
    ).fetchall()
    conn.close()

    metrics = [
        "max_bench_lbs",
        "med_ball_chest_pass_ft",
        "max_deadlift_lbs",
        "max_back_squat_lbs",
        "standing_vertical_jump_in",
        "rotational_scoop_toss_ft",
        "cable_chop_lbs",
        "max_exit_velocity_mph",
    ]

    buckets = {}
    for r in rows:
        h = float(r["height_in"])
        bucket = int(h // 2) * 2
        key = f"{bucket}-{bucket + 1.9:.1f} in"
        if key not in buckets:
            buckets[key] = {m: [] for m in metrics}
            buckets[key]["n"] = 0
        buckets[key]["n"] += 1
        for m in metrics:
            v = r[m]
            if v is not None:
                buckets[key][m].append(float(v))

    bucket_rows = []
    for bucket_label in sorted(buckets.keys(), key=lambda s: float(s.split("-")[0])):
        data = buckets[bucket_label]
        row = {"bucket": bucket_label, "n": data["n"], "stats": {}}
        for m in metrics:
            vals = data[m]
            if not vals:
                row["stats"][m] = None
                continue
            row["stats"][m] = {
                "avg": round(sum(vals) / len(vals), 1),
                "p25": round(_percentile(vals, 0.25), 1),
                "p50": round(_percentile(vals, 0.50), 1),
                "p75": round(_percentile(vals, 0.75), 1),
            }
        bucket_rows.append(row)

    overall = {}
    for m in metrics:
        vals = [float(r[m]) for r in rows if r[m] is not None]
        if not vals:
            overall[m] = None
            continue
        overall[m] = {
            "avg": round(sum(vals) / len(vals), 1),
            "p25": round(_percentile(vals, 0.25), 1),
            "p50": round(_percentile(vals, 0.50), 1),
            "p75": round(_percentile(vals, 0.75), 1),
            "n": len(vals),
        }

    return render_template("admin_benchmarks.html", bucket_rows=bucket_rows, overall=overall)


@app.route("/admin/workout/<int:workout_id>", methods=["GET"])
def admin_workout_detail(workout_id: int):
    _init_db()
    _ensure_user_columns()
    if not _get_user_id():
        return redirect(url_for("login"))
    if not _is_admin():
        return redirect(url_for("index"))

    conn = _db()
    row = conn.execute(
        """
        SELECT w.id, w.created_at, w.workout_json, u.email, u.full_name
        FROM workouts w
        JOIN users u ON u.id = w.user_id
        WHERE w.id = ?
        """,
        (workout_id,),
    ).fetchone()
    conn.close()
    if not row:
        return redirect(url_for("admin_workouts"))
    workout = json.loads(row["workout_json"])
    return render_template(
        "admin_workout_detail.html",
        workout_id=workout_id,
        created_at=row["created_at"],
        user_name=row["full_name"] or row["email"],
        workout=workout,
    )


@app.route("/admin/user/<user_id>", methods=["GET"])
def admin_user_detail(user_id: str):
    _init_db()
    _ensure_user_columns()
    if not _get_user_id():
        return redirect(url_for("login"))
    if not _is_admin():
        return redirect(url_for("index"))

    conn = _db()
    user = conn.execute(
        "SELECT id, email, full_name, position, phase, goal FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    logs = conn.execute(
        """
        SELECT id, workout_id, date, exercise_id, exercise_name, category, phase, weight, reps
        FROM completed_logs
        WHERE user_id = ?
        ORDER BY date DESC, workout_id DESC, id DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    if not user:
        return redirect(url_for("admin_dashboard"))
    grouped_logs = _group_logs_by_workout([dict(r) for r in logs])
    return render_template("admin_user.html", user=dict(user), grouped_logs=grouped_logs)


@app.route("/admin/exercises", methods=["GET"])
def admin_exercises():
    _init_db()
    _ensure_user_columns()
    if not _get_user_id():
        return redirect(url_for("login"))
    if not _is_admin():
        return redirect(url_for("index"))
    library = _load_exercise_library()
    return render_template("admin_exercises.html", library=library)


@app.route("/admin/exercises/add", methods=["POST"])
def admin_exercises_add():
    _init_db()
    _ensure_user_columns()
    if not _get_user_id():
        return redirect(url_for("login"))
    if not _is_admin():
        return redirect(url_for("index"))

    category = request.form.get("category", "").strip()
    name = request.form.get("name", "").strip()
    movement_family = request.form.get("movement_family", "").strip()
    pattern = request.form.get("pattern", "").strip()
    muscle_mass = request.form.get("muscle_mass", "").strip()
    unilateral = request.form.get("unilateral", "false").strip().lower() == "true"
    if not category or not name:
        return redirect(url_for("admin_exercises"))

    library = _load_exercise_library()
    if category not in library or not isinstance(library[category], list):
        return redirect(url_for("admin_exercises"))

    library[category].append({
        "id": f"{category}:{uuid.uuid4().hex[:8]}",
        "name": name,
        "movement_family": movement_family or _infer_movement_family(name),
        "pattern": pattern or "unknown",
        "muscle_mass": muscle_mass or "medium",
        "unilateral": unilateral,
    })
    _save_exercise_library(library)
    return redirect(url_for("admin_exercises"))


@app.route("/admin/exercises/update", methods=["POST"])
def admin_exercises_update():
    _init_db()
    _ensure_user_columns()
    if not _get_user_id():
        return redirect(url_for("login"))
    if not _is_admin():
        return redirect(url_for("index"))

    category = request.form.get("category", "").strip()
    idx_raw = request.form.get("idx", "").strip()
    if not category or not idx_raw.isdigit():
        return redirect(url_for("admin_exercises"))
    idx = int(idx_raw)

    library = _load_exercise_library()
    if category not in library or idx < 0 or idx >= len(library[category]):
        return redirect(url_for("admin_exercises"))

    prev = library[category][idx]
    name = request.form.get("name", "").strip() or prev.get("name", "")
    movement_family = request.form.get("movement_family", "").strip() or prev.get("movement_family") or _infer_movement_family(name)
    library[category][idx] = {
        "id": prev.get("id") or f"{category}:{uuid.uuid4().hex[:8]}",
        "name": name,
        "movement_family": movement_family,
        "pattern": request.form.get("pattern", "").strip() or "unknown",
        "muscle_mass": request.form.get("muscle_mass", "").strip() or "medium",
        "unilateral": request.form.get("unilateral", "false").strip().lower() == "true",
    }
    _save_exercise_library(library)
    return redirect(url_for("admin_exercises"))


@app.route("/admin/exercises/delete", methods=["POST"])
def admin_exercises_delete():
    _init_db()
    _ensure_user_columns()
    if not _get_user_id():
        return redirect(url_for("login"))
    if not _is_admin():
        return redirect(url_for("index"))

    category = request.form.get("category", "").strip()
    idx_raw = request.form.get("idx", "").strip()
    if not category or not idx_raw.isdigit():
        return redirect(url_for("admin_exercises"))
    idx = int(idx_raw)

    library = _load_exercise_library()
    if category not in library or idx < 0 or idx >= len(library[category]):
        return redirect(url_for("admin_exercises"))

    del library[category][idx]
    _save_exercise_library(library)
    return redirect(url_for("admin_exercises"))


if __name__ == "__main__":
    _init_db()
    app.run(debug=True)
