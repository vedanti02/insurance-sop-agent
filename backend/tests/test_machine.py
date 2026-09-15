from app.blackboard import Blackboard
from app.machine import next_exit
from app.verify import update_access


def bb(**kw) -> Blackboard:
    b = Blackboard(session_id="t", vertical="insurance_claims_v1")
    for k, v in kw.items():
        b.phase = v if k == "phase" else b.phase
    return b


def test_verify_requires_three_fields(policy):
    b = bb()
    b.identity.verified_fields = ["full_name", "dob"]
    update_access(b, policy)
    assert next_exit(b, policy) is None
    b.identity.verified_fields.append("id_last4")
    update_access(b, policy)
    assert next_exit(b, policy).to == "RESOLVE_INTENT"


def test_policy_number_alone_does_not_open_gate(policy):
    b = bb()
    b.identity.resolved_party = "P9"          # resolved is not verified
    update_access(b, policy)
    assert next_exit(b, policy) is None


def test_representative_needs_consent(policy):
    b = bb()
    b.identity.verified_fields = ["full_name", "dob", "id_last4"]
    b.identity.caller_role, b.identity.rep_verified = "representative", True
    update_access(b, policy)
    assert next_exit(b, policy) is None
    b.post_process.consent.state = "approved"
    update_access(b, policy)
    assert next_exit(b, policy).to == "RESOLVE_INTENT"


def test_human_request_is_global(policy):
    for phase in ("VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS"):
        b = bb(); b.phase = phase
        b.control.wants_human = True
        assert next_exit(b, policy).to == "HANDOFF"


def test_lock_wins_over_verified(policy):
    b = bb()
    b.identity.verified_fields = ["full_name", "dob", "id_last4"]
    b.identity.locked = True
    update_access(b, policy)
    assert next_exit(b, policy).to == "HANDOFF"


def test_reentry_edge(policy):
    b = bb(); b.phase = "PROCESS_CASE"
    b.intent.resolved_case = "CL-2048"
    assert next_exit(b, policy) is None
    b.intent.new_case_request = True
    assert next_exit(b, policy).to == "RESOLVE_INTENT"


def test_post_process_only_when_done(policy):
    b = bb(); b.phase = "PROCESS_CASE"
    b.intent.resolved_case = "CL-2048"
    b.control.done = True
    assert next_exit(b, policy).to == "POST_PROCESS"


def test_post_process_closes_on_decision(policy):
    b = bb(); b.phase = "POST_PROCESS"; b.control.done = True
    assert next_exit(b, policy) is None
    b.post_process.decision = "decline"
    assert next_exit(b, policy).to == "CLOSED"


def test_terminal_has_no_exits(policy):
    b = bb(); b.phase = "CLOSED"; b.control.wants_human = True
    assert next_exit(b, policy) is None
