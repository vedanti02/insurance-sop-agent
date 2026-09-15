from conftest import MARGARET, P

from app.guidance import render, select_guidance


def topics(store, claim, intent, utt):
    return [g["topic"] for g in select_guidance(store, claim, intent, utt)]


def test_longest_phrase_wins(store):
    c = store.claims_by_id["CL-2048"]
    assert topics(store, c, "document_submission", "how soon do I need to submit these?")[0] == "submission_timing"
    assert topics(store, c, "next_steps", "how long after I send them does it take?")[0] == "processing_time_after_submission"


def test_intent_only_entry_selected_without_phrase(store):
    c = store.claims_by_id["CL-2048"]
    assert topics(store, c, "denial_question", "why was it denied") == ["missing_required_material_alternatives"]


def test_no_documents_means_only_fallback(store):
    auto = store.claims_by_id["CL-2102"]
    assert topics(store, auto, "next_steps", "how long will this take?") == ["fallback"]


def test_render_fills_documents_and_processing_time(store):
    c = store.claims_by_id["CL-2048"]
    entry = next(g for g in store.guideline["claim_followup_guidance"] if g["topic"] == "processing_time_after_submission")
    text = render(store, entry, c)
    assert "CL-2048" in text and "the pathology report and the office note" in text and "less than a week" in text


def test_bundle_for_margaret_denial(make_session):
    s = make_session([P(**MARGARET, intent="denial_question", case_type="healthcare", status="denied")])
    s.turn("why was my denied healthcare claim denied?")
    b = s.bb.bundle
    assert b["claim"]["case_id"] == "CL-2048" and b["claim"]["deadline_state"] == "upcoming"
    assert [d["name"] for d in b["documents"]] == ["pathology report", "office note"]
    assert "patient name" in b["documents"][0]["requirements"]          # resolved via alias to the pathology guidance
    assert "alternative" not in b["documents"][0]
    assert "2026-03-18" in b["deadline_guidance"]


def test_document_unavailable_offers_alternative_then_exhausts(make_session):
    s = make_session([P(**MARGARET, intent="next_steps", case_type="healthcare", status="denied"),
                      P(document_unavailable="pathology report"),
                      P(document_unavailable="office note"),
                      P(document_unavailable="all")])
    s.turn("next steps on the denied healthcare one")
    s.turn("I can't get the pathology report")
    d = {x["name"]: x for x in s.bb.bundle["documents"]}
    assert d["pathology report"]["state"] == "alternative_offered" and "replacement copy" in d["pathology report"]["alternative"]
    s.turn("and I can't get the office note either")
    assert s.bb.documents == {"pathology report": "alternative_offered", "office note": "alternative_offered"}
    s.turn("none of those work for me")
    assert s.bb.control.escalation_reason == "alternatives_exhausted" and s.bb.control.pending == "offer_human"
    assert "human_review" in s.bb.bundle


def test_passed_deadline_suppresses_within_a_week(make_session, settings):
    from dataclasses import replace
    from datetime import date
    s = make_session([P(**MARGARET, intent="document_submission", case_type="healthcare", status="denied")])
    s.ctx.settings = replace(settings, demo_today=date(2026, 9, 14))
    s.turn("how soon do I need to submit?")
    b = s.bb.bundle
    assert b["claim"]["deadline_state"] == "passed" and "already passed" in b["deadline_guidance"]
    assert "submission_timing" not in [g["topic"] for g in b["followup_guidance"]]


def test_resolve_doc_phrases():
    from app.guidance import _resolve_doc
    docs = ["pathology report", "office note"]
    assert _resolve_doc("the pathology report", docs) == ["pathology report"]
    assert _resolve_doc("anything from the clinic", docs) == docs
    assert _resolve_doc("none of those", docs) == docs
    assert _resolve_doc("all", docs) == docs
    assert _resolve_doc("the x-ray", docs) == []


def test_diagnosis_report_falls_back_to_default_guidance(store):
    assert store.resolve_document_key("diagnosis report") is None
    assert store.document_guidance("diagnosis report") == store.guideline["default_guidance"]["en"]
    assert store.document_alternative("diagnosis report") == store.guideline["document_alternative_guidance"]["default"]["en"]
