# Public constraint findings

| Finding | Severity | Status | Case |
| --- | --- | --- | --- |
| F-001 | wrong-program | open | equip-001, equip-002, equip-003 |
| F-002 | wrong-program | open | library-001 |
| F-003 | wrong-program | open | days-offseason-2-distinct, days-offseason-3-distinct, days-inseason-2-distinct, days-inseason-3-distinct, days-inseason-4-distinct, days-inseason-5-distinct, days-inseason-6-distinct |
| F-004 | wrong-program | open | days-offseason-2-limit, days-offseason-3-limit, days-offseason-4-limit, days-offseason-5-limit, days-offseason-6-limit, days-inseason-2-limit, days-inseason-3-limit, days-inseason-4-limit, days-inseason-5-limit, days-inseason-6-limit |
| F-005 | blocks-use | open | injury-shoulder-military, injury-shoulder-core-power |
| F-006 | blocks-use | open | injury-elbow-patterns, injury-knee-patterns, injury-back-hinge, injury-hip-patterns |

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

## F-003: The requested day index does not select distinct sessions for some weekly plans

- Severity: wrong-program
- Status: open
- Case(s): eval/cases/days.json#days-offseason-2-distinct, eval/cases/days.json#days-offseason-3-distinct, eval/cases/days.json#days-inseason-2-distinct, eval/cases/days.json#days-inseason-3-distinct, eval/cases/days.json#days-inseason-4-distinct, eval/cases/days.json#days-inseason-5-distinct, eval/cases/days.json#days-inseason-6-distinct
- Repro:
  ```python
  athlete = {"position": "RHP", "goal": "power", "phase": "offseason", "days_per_week": 3, "injuries": []}
  import random, work_gen; random.seed(0); first = work_gen.generate_workout(athlete, history=[], day_index=0)
  random.seed(0); second = work_gen.generate_workout(athlete, history=[], day_index=1)
  ```
- Observed: With the audit clock fixed to 2026-10-26 and the same seed for every index, 2- and 3-day off-season schedules return 1 distinct session. All 2- through 6-day in-season schedules return 1 distinct session. The requested day index does not change the prescribed blocks.
- Expected: The indices 0 through days_per_week - 1 must select days_per_week distinct sessions.
- Notes: The off-season plan is None below 4 days. In-season generation has no day plan. The 4-, 5-, and 6-day off-season plans produce the requested number of distinct sessions.

## F-004: The engine returns a session beyond the stated weekly day limit

- Severity: wrong-program
- Status: open
- Case(s): eval/cases/days.json#days-offseason-2-limit, eval/cases/days.json#days-offseason-3-limit, eval/cases/days.json#days-offseason-4-limit, eval/cases/days.json#days-offseason-5-limit, eval/cases/days.json#days-offseason-6-limit, eval/cases/days.json#days-inseason-2-limit, eval/cases/days.json#days-inseason-3-limit, eval/cases/days.json#days-inseason-4-limit, eval/cases/days.json#days-inseason-5-limit, eval/cases/days.json#days-inseason-6-limit
- Repro:
  ```python
  athlete = {"position": "RHP", "goal": "power", "phase": "offseason", "days_per_week": 3, "injuries": []}
  import work_gen, random; random.seed(0)
  workout = work_gen.generate_workout(athlete, history=[], day_index=3)
  ```
- Observed: Both phases return workouts at day_index == days_per_week and days_per_week + 1. This affects every tested 2- through 6-day schedule. Off-season plans with at least 4 days wrap to the start of the day template.
- Expected: A request at or after days_per_week must return no session or reject the day index.
- Notes: ValueError and IndexError are accepted index rejections only for requests outside the schedule. Errors at a valid index remain hard failures.

## F-005: The shoulder filter permits excluded overhead exercises

- Severity: blocks-use
- Status: open
- Case(s): eval/cases/injury_exclusions.json#injury-shoulder-military, eval/cases/injury_exclusions.json#injury-shoulder-core-power
- Repro:
  ```python
  athlete = {'position': 'RHP', 'goal': 'power', 'phase': 'offseason', 'days_per_week': 6, 'injuries': ['shoulder']}
  import work_gen, random; random.seed(0)
  work_gen.generate_workout(athlete, history=[{'exercise_name': 'Barbell military press', 'category': 'upper_push', 'date': '2026-10-25'}], focus=None, day_index=5)
  ```
- Observed: The six-day shoulder profile receives Barbell military press on day 5. Power focus also selects Walking overhead slam on day 0.
- Expected: The program must exclude each reviewed shoulder exercise ID in the case contract.
- Notes: The core power pool bypasses the injury filter. Military presses survive its name checks. The catalog uses reviewed IDs because current metadata cannot identify overhead movements.

## F-006: The generator ignores four stated injury restriction profiles

- Severity: blocks-use
- Status: open
- Case(s): eval/cases/injury_exclusions.json#injury-elbow-patterns, eval/cases/injury_exclusions.json#injury-knee-patterns, eval/cases/injury_exclusions.json#injury-back-hinge, eval/cases/injury_exclusions.json#injury-hip-patterns
- Repro:
  ```python
  athlete = {'position': 'RHP', 'goal': 'power', 'phase': 'offseason', 'days_per_week': 3, 'injuries': ['elbow']}
  import work_gen, random; random.seed(0)
  work_gen.generate_workout(athlete, history=[], focus=None, day_index=0)
  ```
- Observed: Elbow, knee, back, and hip profiles receive push or pull, squat or knee extension, hinge, and lateral exercises respectively.
- Expected: Each program must exclude the movement patterns and families that its synthetic profile prohibits.
- Notes: The case catalog defines explicit scenario restrictions. It does not define medical exclusions for all athletes with each injury. The engine only implements a shoulder filter.
