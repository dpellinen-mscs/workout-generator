#!/usr/bin/env python3
"""Add equipment metadata from exercise names. This tool does not select exercises.

Each list gives all equipment needed for the named version. ``other`` covers
support equipment outside the fixed vocabulary: benches, racks, TRX straps,
a landmine base, a trap bar, a box, and a foam roller. It cannot tell
those items apart. The name overrides below select one version when a name
does not state its load or permits alternatives. New names must match a rule
or gain an explicit override before the tool can tag them.

Run from the repo with ``python eval/tools/tag_equipment.py``. Use --input
and --output to inspect a generated file before replacing the source file.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EQUIPMENT = (
    "barbell", "dumbbell", "kettlebell", "cable", "machine",
    "band", "med_ball", "bodyweight", "other",
)

# These are metadata choices for this library, not general exercise rules.
# A list is an AND requirement; it cannot encode alternative equipment.
NAME_OVERRIDES = {
    "front shoulder raise": ("dumbbell",),
    "lateral shoulder raise": ("dumbbell",),
    "tricep kickbacks": ("dumbbell",),
    "chest-supported row": ("dumbbell", "other"),
    "renegade rows": ("dumbbell",),
    "reverse flies": ("dumbbell",),
    "hammer curls": ("dumbbell",),
    "split squat": ("bodyweight",),
    "reverse lunge": ("bodyweight",),
    "forward lunge": ("bodyweight",),
    "single-leg straight-leg deadlift": ("bodyweight",),
    "barbell back squat": ("barbell", "other"),
    "barbell front squat": ("barbell", "other"),
    "barbell military press": ("barbell", "other"),
    "trap bar deadlift": ("other",),
    "goblet squat": ("dumbbell",),
    "glute ham bridge": ("bodyweight",),
    "one-leg glute ham bridge": ("bodyweight",),
    "pallof press x 10/side": ("cable",),
    "farmer carry x 40 yards": ("dumbbell",),
    "walking overhead slam": ("med_ball",),
    "reactive box jump": ("bodyweight", "other"),
    "mobility: shoulder int-ext rotation (band or cable) x 10/side": ("band",),
    "mobility: wall ankle mobilizations x 8/side": ("bodyweight",),
}


def equipment_for_name(name: str) -> list[str]:
    """Return the required equipment for one named library exercise."""
    normalized = name.casefold().strip()
    if normalized in NAME_OVERRIDES:
        return list(NAME_OVERRIDES[normalized])
    if "foam roll" in normalized:
        return ["other"]
    if "trx" in normalized:
        return ["bodyweight", "other"]
    if "landmine" in normalized:
        return ["barbell", "other"]
    if "bench press" in normalized or normalized == "dumbbell chest fly":
        if "barbell" in normalized:
            return ["barbell", "other"]
        if "dumbbell" in normalized:
            return ["dumbbell", "other"]
    if normalized in {"leg curl", "leg extension", "leg press"}:
        return ["machine"]
    if "lat pulldown" in normalized or "cable" in normalized:
        return ["cable"]
    for token in ("barbell", "dumbbell", "kettlebell", "band"):
        if token in normalized:
            return [token]
    if "med ball" in normalized:
        return ["med_ball"]
    if any(token in normalized for token in ("plank", "stretch", "dead bug", "push-up")):
        return ["bodyweight"]
    raise ValueError(f"No equipment rule for exercise: {name!r}; add a name override")


def tag_library(library: dict) -> dict:
    """Return a tagged copy; wrap warmup strings without changing their names."""
    tagged = deepcopy(library)
    for category, entries in tagged.items():
        if not isinstance(entries, list):
            raise ValueError(f"Category {category!r} must contain a list")
        for index, entry in enumerate(entries):
            if isinstance(entry, str) and category == "warmup":
                entry = {"name": entry}
                entries[index] = entry
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                raise ValueError(f"Exercise {category}[{index}] must have a text name")
            entry["equipment"] = equipment_for_name(entry["name"])
    return tagged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "exercise_library.json")
    parser.add_argument("--output", type=Path, help="Default: replace the input file")
    args = parser.parse_args(argv)
    library = json.loads(args.input.read_text(encoding="utf-8"))
    tagged = tag_library(library)
    destination = args.output or args.input
    destination.write_text(json.dumps(tagged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Tagged {sum(len(entries) for entries in tagged.values())} entries: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
