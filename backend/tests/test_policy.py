import pytest

from app.policy import evaluate

STATE = {"identity": {"verified_fields": ["full_name", "dob"], "locked": False},
         "intent": {"resolved_case": None}, "post_process": {"email_decision": "send"},
         "control": {"scope_strikes": 2}}


@pytest.mark.parametrize("pred,expected", [
    ("identity.verified_fields count>= 2", True),
    ("identity.verified_fields count>= 3", False),
    ("identity.locked == true", False),
    ("identity.locked == false", True),
    ("intent.resolved_case != null", False),
    ("intent.resolved_case == null", True),
    ("post_process.email_decision in [send, skip]", True),
    ("post_process.email_decision in [skip]", False),
    ("control.scope_strikes >= 2", True),
    ("control.scope_strikes <= 1", False),
    ("missing.path == null", True),
    ("missing.path >= 1", False),
])
def test_evaluate(pred, expected):
    assert evaluate(pred, STATE) is expected


def test_bad_predicate_raises():
    with pytest.raises(ValueError):
        evaluate("__import__('os')", STATE)


def test_policy_loads_all_phases(policy):
    assert set(policy.phases) == {"VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS", "HANDOFF", "CLOSED"}
    assert policy.phase("VERIFY_ID").style == "strict"
    assert policy.phase("VERIFY_ID").disclosable == []
    assert "get_claim" not in policy.phase("VERIFY_ID").tools_allowed
