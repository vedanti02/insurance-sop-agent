from conftest import P

from app.blackboard import Blackboard
from app.verify import find_party, identify_representative, verify_candidates


def bb_with(cands: dict) -> Blackboard:
    b = Blackboard(session_id="t", vertical="insurance_claims_v1")
    b.identity.candidates = cands
    return b


def test_policy_number_resolves_but_verifies_nothing(store, policy):
    b = bb_with({"policy_number": "POL-9921"})
    r = verify_candidates(b, store, policy)
    assert b.identity.resolved_party == "P9" and r["verified_count"] == 0 and r["evaluated"] == []


def test_policy_number_formats(store):
    for v in ("POL-9921", "pol 9921", "POL9921", "policy 9921"):
        assert find_party(store, {"policy_number": v}).party_id == "P9"


def test_unique_name_resolves(store):
    assert find_party(store, {"full_name": "Yaven Li"}).party_id == "P13"
    assert find_party(store, {"full_name": "Nobody Here"}) is None


def test_two_strong_fields_resolve_without_name(store):
    assert find_party(store, {"dob": "1985-03-15", "id_last4": "4472"}).party_id == "P9"
    assert find_party(store, {"dob": "1985-03-15"}) is None


def test_three_fields_verify(store, policy):
    b = bb_with({"full_name": "Margaret Chen", "dob": "March 15 1985", "id_last4": "four four seven two"})
    r = verify_candidates(b, store, policy)
    assert r["verified_count"] == 3 and r["remaining_required"] == 0
    assert all(e["match"] for e in r["evaluated"])
    assert "4472" not in str(r) and "Margaret" not in str(r)   # booleans only


def test_alias_caller_with_alias_email(store, policy):
    b = bb_with({"full_name": "Yaven Li", "email": "yawen.li@example.com", "dob": "1989-12-03"})
    assert verify_candidates(b, store, policy)["verified_count"] == 3


def test_unknown_policy_counts_attempts(store, policy):
    b = bb_with({"policy_number": "POL-0000"})
    verify_candidates(b, store, policy)
    b.identity.candidates = {"policy_number": "POL-1111"}
    verify_candidates(b, store, policy)
    assert b.identity.resolved_party is None and b.identity.unknown_policy_attempts == 2
    assert b.identity.mismatched_turns == 2


def test_lockout_after_repeated_guesses(store, policy):
    b = bb_with({"full_name": "Margaret Chen", "dob": "1985-03-15"})
    verify_candidates(b, store, policy)
    assert b.verified_count == 2
    for guess in ("0001", "0002", "0003", "0004", "0005"):
        b.identity.candidates = {"id_last4": guess}
        verify_candidates(b, store, policy)
    assert b.identity.locked and b.identity.mismatched_turns == 5
    assert b.verified_count == 2           # never crossed 3 by brute force


def test_correction_after_miss_is_accepted(store, policy):
    b = bb_with({"full_name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4471"})
    verify_candidates(b, store, policy)
    assert b.verified_count == 0 and b.identity.mismatched_turns == 1     # strong miss: nothing credited
    b.identity.candidates = {"full_name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"}
    assert verify_candidates(b, store, policy)["verified_count"] == 3


def test_representative_lookup(store):
    assert identify_representative(store, "David Chen", "son", "P9")
    assert identify_representative(store, "david chen", None, "P9")
    assert identify_representative(store, "David Chen", "mother", "P9")      # relationship phrased from the other side
    assert not identify_representative(store, "David Chen", "son", "P12")
    assert not identify_representative(store, "Someone Else", "son", "P9")
    assert not identify_representative(store, None, "son", "P9")


def test_scripted_unknown_policy_offers_human(make_session):
    s = make_session([P(policy_number="POL-0000"), P(policy_number="POL-0001")])
    s.turn("POL-0000"); r = s.turn("POL-0001")
    assert r.phase == "VERIFY_ID" and s.bb.control.pending == "offer_human"
    assert "POL-0001" not in r.reply
