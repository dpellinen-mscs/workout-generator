"""Unit tests for pure load checks, including boundary behavior."""

import pytest

from eval.tools.load_checks import (
    no_warnings, pattern_counts_within_caps, prescribed_pattern_counts,
    warnings_include, weekly_load_within_cap, session_load_scores_match,
    history_load_equals, prescribed_load_scores,
)


def test_reported_load_must_match_prescribed_block_sum():
    assert session_load_scores_match({"reported_session_loads": [12], "session_loads": [12]}, True) == []
    assert session_load_scores_match({"reported_session_loads": [0], "session_loads": [12]}, True)


@pytest.mark.parametrize("total,passes", [(199, True), (200, True), (201, False)])
def test_weekly_load_within_cap_boundary(total, passes):
    assert (weekly_load_within_cap({"weekly_load": total}, 200) == []) is passes


def test_history_load_equals():
    assert history_load_equals({"history_caps": {"total_load": 9}}, 9) == []
    assert history_load_equals({"history_caps": {"total_load": 0}}, 9)


def test_load_oracle_rejects_missing_or_unknown_metadata():
    style = {"intensity_scale": {"heavy": 3}, "muscle_mass_scale": {"large": 4}}
    block = {"intensity": "heavy", "exercise": {"muscle_mass": "large"}}
    assert prescribed_load_scores([{"core": block}], style) == [12]
    del block["exercise"]["muscle_mass"]
    with pytest.raises(KeyError):
        prescribed_load_scores([{"core": block}], style)
    block["exercise"]["muscle_mass"] = "large"
    block["intensity"] = "unknown"
    with pytest.raises(KeyError):
        prescribed_load_scores([{"core": block}], style)


@pytest.mark.parametrize("count,passes", [(2, True), (3, True), (4, False)])
def test_pattern_counts_within_caps_boundary(count, passes):
    observation = {"pattern_counts": {"pull": count, "uncapped": 100}}
    assert (pattern_counts_within_caps(observation, {"pull": 3, "hinge": 3}) == []) is passes


def test_warnings_include_checks_exact_expected_messages():
    observation = {"warnings": ["Weekly load cap exceeded: 201 > 200", "Another warning"]}
    assert warnings_include(observation, ["Weekly load cap exceeded: 201 > 200"]) == []
    assert warnings_include(observation, ["Weekly load cap exceeded: 202 > 200"])


def test_no_warnings_detects_unexpected_message():
    assert no_warnings({"warnings": []}, True) == []
    assert no_warnings({"warnings": ["Unexpected"]}, True)


def test_prescribed_pattern_counts_counts_every_block_and_normalizes_carry():
    def block(pattern):
        return {"exercise": {"pattern": pattern}}
    workout = {"main_lift_lower": block("squat"), "main_lift_upper_push": None,
               "main_lift_upper_pull": block("pull"), "core": block("carry"),
               "accessories": [block("pull"), block("core")],
               "pattern_counts": {"pull": 999}, "warmup": ["Ignore warmup"]}
    assert prescribed_pattern_counts([workout, workout]) == {"squat": 2, "pull": 4, "core": 4}
