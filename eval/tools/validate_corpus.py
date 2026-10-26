"""Validate constraint cases with the local schema and scorer registry.

The stdlib validator supports the schema keywords used in case-file.schema.json.
Keep checks small and add a test when the schema needs another keyword.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_DIR = ROOT / "eval" / "cases"
SCHEMA_PATH = ROOT / "eval" / "schema" / "case-file.schema.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _is_type(value: Any, name: str) -> bool:
    types = {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }
    return types[name]()


def _validate(value: Any, rule: dict, schema: dict, path: str) -> list[str]:
    if "$ref" in rule:
        target = schema
        for part in rule["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return _validate(value, target, schema, path)
    errors = []
    if "anyOf" in rule and not any(
        not _validate(value, option, schema, path) for option in rule["anyOf"]
    ):
        return [f"{path}: does not match any allowed value type"]
    if "type" in rule and not _is_type(value, rule["type"]):
        return [f"{path}: expected {rule['type']}"]
    if "const" in rule and value != rule["const"]:
        errors.append(f"{path}: must equal {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{path}: must be one of {rule['enum']!r}")
    if isinstance(value, dict):
        properties = rule.get("properties", {})
        for key in rule.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required field {key!r}")
        if len(value) < rule.get("minProperties", 0):
            errors.append(f"{path}: needs at least {rule['minProperties']} field(s)")
        for key, item in value.items():
            if key in properties:
                errors.extend(_validate(item, properties[key], schema, f"{path}.{key}"))
            elif rule.get("additionalProperties") is False:
                errors.append(f"{path}: unknown field {key!r}")
    elif isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            errors.append(f"{path}: needs at least {rule['minItems']} item(s)")
        if rule.get("uniqueItems"):
            items = [json.dumps(item, sort_keys=True) for item in value]
            if len(items) != len(set(items)):
                errors.append(f"{path}: items must be unique")
        if "items" in rule:
            for index, item in enumerate(value):
                errors.extend(_validate(item, rule["items"], schema, f"{path}[{index}]"))
    elif isinstance(value, str):
        if len(value) < rule.get("minLength", 0):
            errors.append(f"{path}: needs at least {rule['minLength']} character(s)")
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            errors.append(f"{path}: must match {rule['pattern']!r}")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in rule and value < rule["minimum"]:
            errors.append(f"{path}: must be at least {rule['minimum']}")
        if "maximum" in rule and value > rule["maximum"]:
            errors.append(f"{path}: must be at most {rule['maximum']}")
    return errors


def _known_checks() -> set[str]:
    return set(importlib.import_module("eval.tools.score").CHECKS)


def _read_documents(cases_dir: Path) -> tuple[list[tuple[Path, Any]], list[str]]:
    if not cases_dir.is_dir():
        return [], [f"{cases_dir}: case directory does not exist"]
    files = sorted(cases_dir.rglob("*.json"))
    if not files:
        return [], [f"{cases_dir}: no JSON case files found"]
    documents = []
    errors = []
    for path in files:
        try:
            documents.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: cannot read JSON: {exc}")
    return documents, errors


def validate_corpus(cases_dir: Path | str = DEFAULT_CASES_DIR) -> list[str]:
    """Return all corpus errors. An empty list means the corpus is valid."""
    documents, errors = _read_documents(Path(cases_dir))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    known_checks = _known_checks()
    ids: dict[str, str] = {}
    for path, document in documents:
        errors.extend(_validate(document, schema, schema, str(path)))
        if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
            continue
        for index, case in enumerate(document["cases"]):
            if not isinstance(case, dict):
                continue
            location = f"{path}.cases[{index}]"
            case_id = case.get("id")
            if isinstance(case_id, str):
                if case_id in ids:
                    errors.append(f"{location}: duplicate case id {case_id!r}; first at {ids[case_id]}")
                else:
                    ids[case_id] = location
            if isinstance(case.get("expect"), dict):
                for name in case["expect"]:
                    if name not in known_checks:
                        errors.append(f"{location}.expect: unknown scorer check {name!r}")
    return errors


def load_cases(cases_dir: Path | str = DEFAULT_CASES_DIR) -> list[dict]:
    """Load validated cases, without adding fields to the case data."""
    errors = validate_corpus(cases_dir)
    if errors:
        raise ValueError("\n".join(errors))
    documents, _ = _read_documents(Path(cases_dir))
    return [case for _, document in documents for case in document["cases"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    args = parser.parse_args(argv)
    errors = validate_corpus(args.cases_dir)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    documents, _ = _read_documents(args.cases_dir)
    count = sum(len(document["cases"]) for _, document in documents)
    print(f"Valid corpus: {count} cases in {len(documents)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
