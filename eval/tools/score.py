"""Run synthetic constraint cases and score raw observations with pure checks."""

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import work_gen
from eval.tools.days import CHECKS as DAY_CHECKS, observe_days

CASES_DIR = ROOT / "eval" / "cases"
BASELINE = ROOT / "eval" / "recorded" / "baseline.json"


def exercise_blocks(workout):
    """Return prescribed blocks in export order, without absent main slots."""
    return [workout[key] for key in (
        "main_lift_lower", "main_lift_upper_push", "main_lift_upper_pull", "core"
    ) if workout.get(key)] + workout.get("accessories", [])


def all_exercises_use_only(observation, allowed):
    violations = []
    workout = observation["workout"]
    exercises = [b["exercise"] for b in exercise_blocks(workout)]
    exercises += [e if isinstance(e, dict) else {
        "name": e, "equipment": observation.get("warmup_equipment", {}).get(e)
    } for e in workout.get("warmup", [])]
    for exercise in exercises:
        equipment = exercise.get("equipment")
        if not isinstance(equipment, list) or not equipment:
            violations.append(f"{exercise['name']}: equipment metadata absent")
        elif set(equipment) - set(allowed):
            violations.append(f"{exercise['name']}: requires {sorted(set(equipment) - set(allowed))}")
    return violations


def library_categories_nonempty(observation, categories):
    return [f"{name}: category is empty" for name in categories
            if observation["category_sizes"].get(name, 0) == 0]


CHECKS = {
    "all_exercises_use_only": all_exercises_use_only,
    "library_categories_nonempty": library_categories_nonempty,
}
CHECKS.update(DAY_CHECKS)


def load_cases(cases_dir=CASES_DIR):
    from eval.tools.validate_corpus import load_cases as validated_cases
    return validated_cases(cases_dir)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("work_gen.py", "exercise_library.json", "coaching_style.json")}


@contextmanager
def seeded(seed):
    state = random.getstate()
    random.seed(seed)
    try:
        yield
    finally:
        random.setstate(state)


class AuditDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 26, 12, tzinfo=tz)


def generate_case(case, day_index):
    with seeded(case.get("seed", 0)), patch.object(work_gen, "datetime", AuditDateTime):
        return work_gen.generate_workout(
            case["athlete"], history=case["history"], focus=case.get("focus"),
            day_index=day_index,
        )


def observe(case):
    if case.get("scenario", {}).get("kind") == "days":
        return observe_days(case, lambda index: generate_case(case, index))
    workout = generate_case(case, case["day_index"])
    return {"workout": workout,
            "warmup_equipment": {e["name"]: e["equipment"] for e in work_gen.EXERCISE_LIBRARY["warmup"]},
            "category_sizes": {k: len(v) for k, v in work_gen.EXERCISE_LIBRARY.items()}}


def score_observation(case, observation):
    checks = {name: CHECKS[name](observation, expected)
              for name, expected in case["expect"].items()}
    failed = [name for name, violations in checks.items() if violations]
    return {"id": case["id"], "status": "known" if failed and case.get("finding")
            else "fail" if failed else "pass", "checks": checks,
            "finding": case.get("finding"), "error": None}


def evaluate(case):
    try:
        observation = observe(case)
        return observation, score_observation(case, observation)
    except Exception as exc:
        return None, {"id": case["id"], "status": "fail", "checks": {},
                      "finding": case.get("finding"), "error": f"{type(exc).__name__}: {exc}"}


def make_record(cases):
    records = []
    for case in cases:
        observation, result = evaluate(case)
        records.append({"id": case["id"], "input_sha256": digest(case),
                        "observation": observation, "result": result})
    return {"format_version": 1, "source_sha256": source_hashes(), "cases": records}


def replay(cases, recording):
    if recording["source_sha256"] != source_hashes():
        raise ValueError("Baseline source hashes differ. Record the current audit source.")
    records = {row["id"]: row for row in recording["cases"]}
    if set(records) != {case["id"] for case in cases}:
        raise ValueError("Baseline case IDs differ from the corpus.")
    results = []
    for case in cases:
        row = records[case["id"]]
        if row["input_sha256"] != digest(case):
            raise ValueError(f"{case['id']}: baseline input hash differs")
        if row["observation"] is None:
            raise ValueError(f"{case['id']}: baseline has no observation")
        results.append(score_observation(case, row["observation"]))
    return results


def score_drops(results, baseline_results):
    current = {row["id"]: row for row in results}
    return [f"{old['id']}: {name}" for old in baseline_results
            for name, violations in old["checks"].items() if not violations
            and (old["id"] not in current or current[old["id"]]["error"]
                 or name not in current[old["id"]]["checks"]
                 or current[old["id"]]["checks"][name])]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args(argv)
    try:
        cases = load_cases()
        baseline_results = [row["result"] for row in json.loads(BASELINE.read_text())["cases"]] if BASELINE.exists() else []
        if args.replay:
            results = replay(cases, json.loads(args.replay.read_text()))
        else:
            record = make_record(cases)
            results = [row["result"] for row in record["cases"]]
            if args.record and not score_drops(results, baseline_results) and not any(row["error"] for row in results):
                args.record.parent.mkdir(parents=True, exist_ok=True)
                args.record.write_text(json.dumps(record, indent=2) + "\n")
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    print("case id | result | failed check | finding")
    for row in results:
        failed = ", ".join(name for name, violations in row["checks"].items() if violations)
        print(f"{row['id']} | {row['status']} | {failed or row['error'] or '-'} | {row['finding'] or '-'}")
    counts = Counter(row["status"] for row in results)
    print(f"pass={counts['pass']} known={counts['known']} fail={counts['fail']}")
    drops = score_drops(results, baseline_results)
    for drop in drops:
        print(f"Baseline score drop: {drop}")
    return int(bool(counts["fail"] or drops))


if __name__ == "__main__":
    sys.exit(main())
