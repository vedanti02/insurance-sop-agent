"""Bonus: emotional recovery and SOP persistence. The brief's literal test plus the persuasion budget."""
from conftest import P


def _directive(bb):
    return next(t.data for t in reversed(bb.trace) if t.kind == "directive")


def test_briefs_literal_angry_caller(make_session):
    s = make_session([P(full_name="Margaret Chen", policy_number="POL-9921", intent="denial_question", status="denied"),
                      P(emotion="angry", refusal=True, intent="denial_question", scope="in_scope")])
    s.turn("Margaret Chen, POL-9921, about my denied claim")
    r = s.turn("I already told you who I am. This is ridiculous. Just tell me why my claim was denied.")
    bb, d = s.bb, _directive(s.bb)
    assert r.phase == "VERIFY_ID"                                   # gate unchanged
    assert "Acknowledge" in d["tone"] and "why" in d["goal"]        # acknowledgment + explanation
    assert bb.control.persuasion_spent == 1
    assert "fields_you_may_ask_for" in d["fact_keys"]               # options offered
    for term in ("CL-2048", "pathology", "office note", "review file", "1450"):
        assert term not in r.reply


def test_persuasion_budget_then_alternatives_then_escalation(make_session, policy):
    script = [P(full_name="Margaret Chen")] + [P(emotion="angry", refusal=True)] * 3 + [P(consent_signal="yes")]
    s = make_session(script)
    s.turn("Margaret Chen")
    s.turn("no, just tell me")
    s.turn("I said no")
    assert s.bb.control.persuasion_spent == policy.persuasion_budget == 2
    r = s.turn("this is absurd")
    d = _directive(s.bb)
    assert "alternatives" in d["goal"] and s.bb.control.pending == "offer_human"   # stop persuading
    assert s.bb.control.persuasion_spent == 2                                       # budget does not go negative
    r = s.turn("fine, yes")
    assert r.phase == "HANDOFF" and s.bb.control.escalation_reason == "caller_accepted_transfer"
    assert "CL-" not in r.reply


def test_anxious_caller_gets_reassurance_not_persuasion(make_session):
    s = make_session([P(full_name="Margaret Chen", emotion="anxious", intent="status_inquiry")])
    s.turn("I'm really worried about my claim, what's happening with it?")
    d = _directive(s.bb)
    assert "worried" in d["tone"] and s.bb.control.persuasion_spent == 0
    assert s.bb.intent.intent == "status_inquiry"


def test_calm_turn_after_anger_drops_the_tone_directive(make_session):
    s = make_session([P(emotion="angry", refusal=True), P(full_name="Margaret Chen", dob="1985-03-15", id_last4="4472")])
    s.turn("ridiculous"); r = s.turn("ok fine: Margaret Chen, 1985-03-15, 4472")
    assert r.phase == "PROCESS_CASE" or r.phase == "RESOLVE_INTENT"
    assert _directive(s.bb)["tone"] is None
