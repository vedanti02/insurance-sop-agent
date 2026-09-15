"""Full SOP walks with scripted perceptions and the stub responder. Zero model calls."""
from conftest import MARGARET, P

from app.tools.insurance import OUTBOX


def _kinds(bb, kind):
    return [t for t in bb.trace if t.kind == kind]


def test_identity_plus_intent_on_first_turn_stays_in_verify(make_session):
    s = make_session([P(full_name="Margaret Chen", policy_number="POL-9921", intent="denial_question",
                        case_type="healthcare", status="denied", period="January")])
    r = s.turn("My name is Margaret Chen, POL-9921, calling about my denied healthcare claim from January")
    bb = s.bb
    assert r.phase == "VERIFY_ID"
    assert bb.identity.resolved_party == "P9"
    assert bb.verified_count == 1                       # name only; policy number never counts
    assert bb.intent.intent == "denial_question" and bb.intent.intent_turn == 1
    assert bb.intent.case_hints.case_type == "healthcare" and bb.intent.case_hints.status == "denied"
    mem = [t.data for t in _kinds(bb, "memory") if t.data.get("event") == "intent_captured"]
    assert mem and mem[0]["deferred"] is True
    assert not _kinds(bb, "transition")
    assert "CL-2048" not in r.reply and "pathology" not in r.reply


def test_margaret_happy_path_to_closed(make_session):
    OUTBOX.clear()
    s = make_session([
        P(caller_role_claim="self", intent="denial_question", case_type="healthcare", status="denied", period="January", **MARGARET),
        P(intent="document_submission"),
        P(done=True),
        P(consent_signal="yes"),
    ])
    r1 = s.turn("I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied "
                "healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.")
    bb = s.bb
    assert [t["to"] for t in r1.transitions] == ["RESOLVE_INTENT", "PROCESS_CASE"]
    assert bb.verified_count == 3 and bb.intent.resolved_case == "CL-2048"
    # no claim tool ran before the gate opened
    order = [(t.kind, t.data.get("name") or t.data.get("to")) for t in bb.trace]
    assert order.index(("transition", "RESOLVE_INTENT")) < order.index(("tool", "get_claim"))
    assert "CL-2048" in r1.reply                        # stub renders the bundle after verification

    r2 = s.turn("How do I submit the documents?")
    assert r2.phase == "PROCESS_CASE" and not r2.transitions

    r3 = s.turn("No, that's all.")
    assert r3.phase == "POST_PROCESS"
    assert bb.post_process.summary and bb.post_process.summary["cases"][0]["case_id"] == "CL-2048"
    assert bb.control.pending == "post_offer"

    r4 = s.turn("Yes please")
    assert r4.phase == "CLOSED" and bb.closed
    assert bb.post_process.decision == "accept"
    assert OUTBOX and OUTBOX[-1]["to"] == "margaret@email.com" and OUTBOX[-1]["to_masked"] == "m***@email.com"


def test_email_skip_is_a_success_path(make_session):
    s = make_session([P(**MARGARET, case_type="auto"), P(done=True), P(consent_signal="no")])
    s.turn("hi"); s.turn("that's it"); r = s.turn("no thanks")
    assert r.phase == "CLOSED" and s.bb.post_process.decision == "decline"
    assert s.bb.post_process.receipt is None


def test_ambiguous_hint_disambiguates(make_session):
    s = make_session([P(**MARGARET, case_type="healthcare", period="January"), P(case_id="CL-2011")])
    r1 = s.turn("healthcare claim from January")
    assert r1.phase == "RESOLVE_INTENT" and s.bb.control.pending == "disambiguate"
    assert set(s.bb.control.pending_options) == {"CL-2048", "CL-2011"}
    r2 = s.turn("the older one")
    assert r2.phase == "PROCESS_CASE" and s.bb.intent.resolved_case == "CL-2011"


def test_case_switch_reenters_resolve_without_reverify(make_session):
    s = make_session([P(**MARGARET, case_type="healthcare", status="denied"),
                      P(new_case_request=True, case_type="auto")])
    s.turn("denied healthcare")
    r = s.turn("actually, what about my auto claim")
    assert r.phase == "PROCESS_CASE" and s.bb.intent.resolved_case == "CL-2102"
    assert s.bb.intent.handled_cases == ["CL-2048"]
    assert s.bb.verified_count == 3 and not any(t["to"] == "VERIFY_ID" for t in r.transitions)


def test_no_claims_caller_goes_to_post_process(make_session):
    s = make_session([P(full_name="Ava Lopez", dob="1990-08-21", id_last4="9180", intent="status_inquiry")])
    r = s.turn("status of my claim?")
    assert r.phase == "POST_PROCESS" and s.bb.intent.no_claims
    assert s.bb.post_process.summary["no_claims_on_file"] is True


def test_human_request_before_verification_hands_off_without_data(make_session):
    s = make_session([P(wants_human=True, full_name="Margaret Chen")])
    r = s.turn("just get me a human")
    assert r.phase == "HANDOFF" and s.bb.closed
    assert "CL-" not in r.reply and "denied" not in r.reply


def test_out_of_scope_strikes_escalate(make_session):
    s = make_session([P(scope="out_of_scope")] * 4)
    for _ in range(3):
        r = s.turn("what is reinforcement learning?")
    assert r.phase == "VERIFY_ID" and s.bb.control.pending == "offer_human"
    r = s.turn("what is RL though")
    assert r.phase == "HANDOFF"


def test_strikes_reset_on_in_scope_turn(make_session):
    s = make_session([P(scope="out_of_scope"), P(full_name="Margaret Chen"), P(scope="out_of_scope")])
    s.turn("what is RL?"); s.turn("Margaret Chen"); s.turn("what is RL?")
    assert s.bb.control.scope_strikes == 1


def test_wrong_strong_field_fails_the_turn_and_is_never_named(make_session):
    s = make_session([P(full_name="Margaret Chen", dob="1985-03-15", id_last4="9180", phone="+16505212836")])
    r = s.turn("...")
    bb = s.bb
    assert r.phase == "VERIFY_ID" and bb.verified_count == 0      # wrong id_last4 -> nothing credited
    assert bb.identity.mismatched_turns == 1 and bb.identity.mismatched_fields_last_turn == ["id_last4"]
    assert "9180" not in r.reply and "4472" not in r.reply


def test_weak_field_typo_still_credits_strong_matches(make_session):
    s = make_session([P(full_name="Margret Chen", dob="1985-03-15", id_last4="4472", phone="650-521-2836")])
    r = s.turn("...")
    assert s.bb.identity.resolved_party == "P9" and s.bb.verified_count == 3
    assert r.phase == "PROCESS_CASE" or r.phase == "RESOLVE_INTENT"
    assert s.bb.identity.mismatched_turns == 1


def test_lockout_after_five_mismatched_turns(make_session):
    s = make_session([P(full_name="Margaret Chen", id_last4=str(1000 + i)) for i in range(5)])
    for i in range(5):
        r = s.turn("guess")
    assert s.bb.identity.locked and r.phase == "HANDOFF"
    assert "CL-" not in r.reply


def test_closed_session_ignores_further_input(make_session):
    s = make_session([P(wants_human=True), P(**MARGARET)])
    s.turn("human please")
    r = s.turn("Margaret Chen 1985-03-15 4472")
    assert r.phase == "HANDOFF" and s.bb.verified_count == 0
