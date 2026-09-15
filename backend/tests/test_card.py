"""Card dispute vertical on the same engine: scripted perceptions, stub responder, no model."""
import pytest
from conftest import P

from app import verticals
from app.blackboard import Blackboard
from app.perceive import ScriptedPerceiver
from app.policy import load_policy
from app.respond import StubResponder
from app.session import Session
from app.tools import ToolCtx, ToolError, dispatch
from app.tools.card import LEDGER
from app.validate import default_validators

PRIYA = dict(full_name="Priya Natarajan", dob="June 21 1988")


@pytest.fixture(scope="module")
def card():
    v = verticals.get("card_disputes_v1")
    return v, v.load_store(), load_policy("card_disputes_v1")


@pytest.fixture
def make_card(card, settings):
    v, store, policy = card

    def _make(script):
        bb = Blackboard(session_id="card", vertical="card_disputes_v1")
        ctx = ToolCtx(bb=bb, store=store, policy=policy, settings=settings, vertical=v)
        return Session(ctx, ScriptedPerceiver(script), StubResponder(), default_validators())
    return _make


def test_two_field_gate(make_card):
    s = make_card([P(full_name="Priya Natarajan"), P(dob="1988-06-21", merchant="Skyline")])
    r1 = s.turn("Priya")
    assert r1.phase == "VERIFY_ID" and s.bb.verified_count == 1
    r2 = s.turn("born June 21 1988, Skyline dispute")
    assert r2.phase == "PROCESS_CASE" and s.bb.intent.resolved_case == "DS-1001"


def test_merchant_and_amount_matching(make_card):
    s = make_card([P(**PRIYA, amount="about 430 dollars")])
    s.turn("...")
    assert s.bb.intent.resolved_case == "DS-1001"
    s2 = make_card([P(**PRIYA, period="February")])
    s2.turn("...")
    assert s2.bb.phase == "RESOLVE_INTENT" and set(s2.bb.control.pending_options) == {"DS-1001", "DS-1002"}


def test_bundle_has_evidence_window_and_offer(make_card):
    s = make_card([P(**PRIYA, merchant="Skyline Electronics", intent="evidence_submission")])
    s.turn("...")
    b = s.bb.bundle
    assert [e["name"] for e in b["evidence"]] == ["order confirmation", "delivery tracking"]
    assert b["dispute"]["window_state"] == "open" and "2026-04-04" in b["window_guidance"]
    assert b["provisional_credit"]["status"].startswith("offered")


def test_provisional_credit_accept_and_decline(make_card):
    LEDGER.clear()
    s = make_card([P(**PRIYA, merchant="Skyline"), P(done=True), P(consent_signal="yes")])
    s.turn("a"); r2 = s.turn("that's all")
    assert r2.phase == "POST_PROCESS" and s.bb.control.pending == "post_offer"
    assert s.bb.post_process.summary["provisional_credit_offer"]["amount"] == "429.99"
    r3 = s.turn("yes")
    assert r3.phase == "CLOSED" and s.bb.post_process.decision == "accept" and s.bb.post_process.receipt == "PC-1001"
    assert LEDGER[-1]["case_id"] == "DS-1001"
    s.ctx.store.records_by_id["DS-1001"].provisional_credit_status = "offered"   # reset fixture state
    d = make_card([P(**PRIYA, merchant="Skyline"), P(done=True), P(consent_signal="no")])
    d.turn("a"); d.turn("done"); r = d.turn("no")
    assert r.phase == "CLOSED" and d.bb.post_process.decision == "decline" and d.bb.post_process.receipt is None


def test_no_offer_closes_after_recap(make_card):
    s = make_card([P(**PRIYA, merchant="Cafe Roma"), P(done=True)])
    s.turn("a"); r = s.turn("that's all")
    assert r.phase == "CLOSED" and s.bb.post_process.decision == "not_offered"


def test_cross_account_dispute_refused(make_card):
    s = make_card([P(**PRIYA, case_id="DS-1003")])
    r = s.turn("tell me about DS-1003")
    assert s.bb.intent.resolved_case is None and "1299" not in r.reply
    with pytest.raises(ToolError):
        dispatch(s.ctx, "get_dispute", {"case_id": "DS-1003"})


def test_leakage_terms_are_card_specific(make_card):
    from app.validate import forbidden_terms
    s = make_card([P(full_name="Priya Natarajan")])
    s.turn("Priya")
    terms = forbidden_terms(s.ctx)
    assert "skyline electronics" in terms["merchant"] and "ds-1001" in terms["case_id"] and "429.99" in terms["amount"]
    assert "tom alvarez" in terms["pii"]


def test_no_disputes_caller(make_card):
    s = make_card([P(full_name="Lena Fischer", dob="1993-02-14", intent="dispute_status")])
    r = s.turn("any disputes?")
    assert r.phase == "CLOSED" and s.bb.intent.no_claims and s.bb.post_process.decision == "not_offered"
