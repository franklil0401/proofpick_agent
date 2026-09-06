"""Keep the frozen per-task scorer; adapt only the phase denominator."""

from smartbuy.eval.trusted79_independent.aggregate import aggregate


def metrics(scores, raw):
    result = aggregate(scores, raw)
    result.pop("trusted79_gate_passed")
    result["planned"] = 15
    result["remaining_in_phase"] = 15 - len(raw)
    result.pop("remaining")
    result["remaining64_executed"] = 0
    result["exposed15_regression_passed"] = len(raw) == len(scores) == 15 and result["passed"] == 15 and not result["safety"]
    result["new_holdout_or_release_result"] = False
    return result
