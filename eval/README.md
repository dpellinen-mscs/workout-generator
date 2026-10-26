# Constraint eval

This corpus measures stated constraints of the workout generator.
It contains synthetic inputs, expected properties, a reference scorer, and raw baseline outputs.
It follows the [reference eval](https://github.com/dpellinen-mscs/slack-inventree-connector/tree/main/eval) structure.
No case defines a training preference as a defect.

| Path | Content |
| --- | --- |
| `cases/*.json` | One JSON file per theme |
| `schema/case-file.schema.json` | Case format and check value types |
| `tools/validate_corpus.py` | Standard library corpus validator |
| `tools/score.py` | Case runner and pure property checks |
| `recorded/baseline.json` | Raw outputs, input hashes, source hashes, and scores |
| `../FINDINGS.md` | Public finding records |

Each file has `format_version: 1` and a nonempty `cases` array.
Each case has `id`, `tags`, `athlete`, `history`, `day_index`, and `expect`.
The optional fields are `seed`, `focus`, `scenario`, `finding`, and `notes`.
The schema defines the full format.

```json
{
  "id": "equip-001",
  "tags": ["equipment"],
  "athlete": {"position": "RHP", "goal": "power", "phase": "offseason", "days_per_week": 3, "injuries": [], "equipment": ["dumbbell", "bodyweight"]},
  "history": [],
  "day_index": 0,
  "seed": 0,
  "expect": {"all_exercises_use_only": ["dumbbell", "bodyweight"]},
  "finding": "F-001",
  "notes": "The engine accepts this equipment field but ignores it."
}
```

Each `expect` key names a pure check in `CHECKS`.
A check returns a list of violations. An empty list means pass.

A failed case with a `finding` is `known`. A failed case without a finding is `fail`.
The scorer exits with 1 for `fail`.
It exits with 0 for `pass` and `known`.
An unexpected execution error always fails the run.
A fault scenario can capture its confirmed error as raw evidence.

Pytest uses strict xfail for known cases. A complete fix causes XPASS and fails CI until the finding marker changes.

The runner supplies explicit history and saves and restores the Python random state.
The default seed is 0. Cases can state a different seed.
The seed controls reproducible measurement. It does not add a seed input to the generator.

The runner never calls `load_history()`.
The eval clock stays at 2026-10-26 12:00.
This date fixes the calendar week that controls lower lift selection.

Run these commands from the repository root with Python 3.11:

```sh
python -m pip install pytest==8.2.2
pytest -q
python eval/tools/validate_corpus.py
python eval/tools/score.py
python eval/tools/score.py --record eval/recorded/baseline.json
python eval/tools/score.py --replay eval/recorded/baseline.json
```

Record again when case inputs or source hashes change.
Replay verifies those hashes before it scores the stored outputs.
CI compares current check results with the baseline. A check that passed before must not drop.
Keep the baseline from the audit until the owner approves a new baseline.
Add each check and its unit test in the same PR as its cases.

The library uses equipment lists as AND requirements.
The tag script assigns one canonical version when a name permits alternatives.
`other` includes distinct support items, such as a bench, rack, or TRX straps.
This coarse token cannot establish that all support items are available.

The manual review file identifies 20 common selections from synthetic profiles.
Warmup entries contain metadata in the library. Generator output keeps the original warmup text.

Rotation cases treat the supplied history as one block.
The requested no-repeat constraint differs from the configured four-use policy.
The owner requires the no-repeat rule. F-007 records the conflict.

The fixture defines the block boundary. Real history has no block boundary field.
Accessory fixtures use synthetic session IDs and row order to identify the previous pair when dates tie.

The engine has no seed argument. Callers can reset Python random state to reproduce a session.

Load cases cover all five configured phases and all four goals.
No separate session load cap exists, so this audit cannot verify a session cap.
Weekly pattern counts include all prescribed blocks, with carry under core.
The warning cases include exact boundaries and dated synthetic history.

Load scores use configured intensity and muscle mass. They exclude set and rep volume.
The four goals therefore produce the same load in each phase for this sample.
The 20 phase and goal profiles produce three distinct six-session sequences.
The fixed date covers an even calendar week. The audit does not claim all week parities or history window edges.

Round-trip cases use temporary JSON files and an isolated SQLite database.
The Flask edit route changes completed logs. It does not edit saved prescriptions.
The audit verifies the existing route and reports the missing program-edit path as a scope difference.
