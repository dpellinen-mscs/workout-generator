#!/usr/bin/env python3
"""Rank named main, core, and accessory selections in a fixed synthetic sample.

This uses synthetic profiles. It does not read athlete history or usage data.
"""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import random
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import work_gen
from eval.tools.score import seeded


def selection_counts():
    counts = Counter()
    for fixed_date in (datetime(2026, 10, 19), datetime(2026, 10, 26)):
        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_date
        with patch.object(work_gen, 'datetime', FixedDateTime):
            for phase in ('offseason', 'inseason'):
                for goal in ('power', 'speed', 'hypertrophy', 'general'):
                    for days in (2, 3, 4, 5, 6):
                        for day in range(days):
                            for seed in range(10):
                                with seeded(seed):
                                    workout = work_gen.generate_workout(
                                    {'position': 'RHP', 'goal': goal, 'phase': phase,
                                     'days_per_week': days, 'injuries': []},
                                    history=[], day_index=day,
                                )
                                for key in ('main_lift_lower', 'main_lift_upper_push', 'main_lift_upper_pull', 'core'):
                                    block = workout.get(key)
                                    if block:
                                        counts[block['exercise']['name']] += 1
                                for block in workout['accessories']:
                                    counts[block['exercise']['name']] += 1
    return counts


if __name__ == '__main__':
    destination = ROOT / 'eval/catalog/equipment_selection_counts.json'
    destination.write_text(json.dumps(dict(selection_counts().most_common()), indent=2) + '\n')
    print(destination)
