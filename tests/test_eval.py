import pytest

from eval.tools.score import evaluate, load_cases


@pytest.mark.parametrize("case", [
    pytest.param(case, id=case["id"], marks=pytest.mark.xfail(
        strict=True, raises=AssertionError, reason=case["finding"]
    )) if case.get("finding") else pytest.param(case, id=case["id"])
    for case in load_cases()
])
def test_constraint_case(case):
    _, result = evaluate(case)
    if result["error"]:
        raise RuntimeError(result["error"])
    assert result["status"] == "pass", result["checks"]
