from conftest import MARGARET, P

from app.perceive import RepresentativeClaim
from app.tools.insurance import OUTBOX

DAVID = dict(caller_role_claim="representative", representative=RepresentativeClaim(rep_name="David Chen", relationship="son"))


def test_representative_default_scenario_approves_on_second_poll(make_session):
    OUTBOX.clear()
    s = make_session([P(**MARGARET, **DAVID, intent="status_inquiry", case_type="auto"), P(), P(done=True), P(consent_signal="yes")])
    r1 = s.turn("This is David Chen calling for my mother Margaret Chen ...")
    bb = s.bb
    assert r1.phase == "VERIFY_ID" and bb.identity.rep_verified and bb.verified_count == 3
    assert bb.post_process.consent.state == "pending" and bb.control.pending == "consent_wait"
    assert "CL-" not in r1.reply
    r2 = s.turn("ok")
    assert bb.post_process.consent.state == "approved" and bb.post_process.consent.polls == 2
    assert r2.phase == "PROCESS_CASE" and bb.intent.resolved_case == "CL-2102"
    polls = [t for t in bb.trace if t.kind == "tool" and t.data["name"] == "check_consent_status"]
    assert [p.data["result"]["state"] for p in polls] == ["pending", "approved"]
    s.turn("that's all"); r4 = s.turn("yes")
    assert r4.phase == "CLOSED" and OUTBOX[-1]["to"] == "margaret@email.com"   # policyholder's address, never the rep's


def test_representative_timeout_scenario_denies_and_offers_alternatives(make_session):
    s = make_session([P(**MARGARET, **DAVID, intent="denial_question", case_type="healthcare"), P(), P(consent_signal="no", done=True)],
                     consent_scenario="timeout")
    s.turn("David Chen for Margaret Chen"); r2 = s.turn("still here")
    bb = s.bb
    assert bb.post_process.consent.state == "denied" and bb.post_process.consent.polls == 5
    assert r2.phase == "VERIFY_ID" and bb.control.pending == "offer_human"
    assert bb.control.escalation_reason == "consent_not_granted"
    assert "CL-" not in r2.reply and "pathology" not in r2.reply
    r3 = s.turn("no thanks, I'll have her call")
    assert r3.phase == "CLOSED"


def test_unlisted_representative_is_refused(make_session):
    s = make_session([P(**MARGARET, caller_role_claim="representative",
                        representative=RepresentativeClaim(rep_name="Someone Else", relationship="husband"))])
    r = s.turn("I'm her husband")
    assert r.phase == "VERIFY_ID" and not s.bb.identity.rep_verified and not s.bb.identity.access_granted
    assert s.bb.control.pending == "offer_human"


def test_rep_cannot_read_claims_without_consent(make_session):
    from app.tools import ToolError, dispatch
    s = make_session([P(**MARGARET, **DAVID)], consent_scenario="timeout")
    s.turn("David for Margaret")
    ctx = s.ctx
    ctx.bb.phase = "PROCESS_CASE"     # even if the phase were forced, dispatch refuses
    try:
        dispatch(ctx, "get_claim", {"case_id": "CL-2048"})
        assert False, "should refuse"
    except ToolError as e:
        assert "consent" in str(e)
