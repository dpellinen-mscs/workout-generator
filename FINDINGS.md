# Public constraint findings

| Finding | Severity | Status | Case |
| --- | --- | --- | --- |
| F-001 | wrong-program | open | equip-001, equip-002, equip-003 |
| F-002 | wrong-program | open | library-001 |

## F-001: The generator ignores available equipment

- Severity: wrong-program
- Status: open
- Case(s): eval/cases/equipment.json#equip-001, eval/cases/equipment.json#equip-002, eval/cases/equipment.json#equip-003
- Repro:
  ```python
  athlete = {"position": "RHP", "goal": "power", "phase": "offseason", "days_per_week": 3, "injuries": [], "equipment": ["dumbbell", "bodyweight"]}
  import random, work_gen; random.seed(0)
  work_gen.generate_workout(athlete, history=[], day_index=0)
  ```
- Observed: The output prescribes Barbell back squat for a dumbbell and bodyweight profile. A no-machine profile receives Leg curl and Leg extension.
- Expected: Every exercise must use only the athlete's available equipment.
- Notes: The first baseline had no equipment model. The equipment PR adds metadata. The engine still ignores the available equipment input.

## F-002: The power pull category is empty

- Severity: wrong-program
- Status: open
- Case(s): eval/cases/library.json#library-001
- Repro:
  ```python
  athlete = {"position": "RHP", "goal": "power", "phase": "offseason", "days_per_week": 3, "injuries": []}
  import random, work_gen; random.seed(0)
  work_gen.generate_workout(athlete, history=[], focus="power_speed_priority", day_index=0)
  ```
- Observed: `upper_pull_power` contains zero entries. The generator uses a base pull without an output warning.
- Expected: Each requested power category must contain at least one exercise.
- Notes: The owner defines category completeness as an eval constraint. This case audits the library with power focus. The fallback does not crash.
