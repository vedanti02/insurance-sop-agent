import json

from conftest import MARGARET, P

from app import audit


def test_audit_record_masks_and_purges(make_session, tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    s = make_session([P(**MARGARET, case_type="auto")])
    s.turn("Margaret Chen 1985-03-15 4472 auto claim")
    audit.record(s.bb, "VERIFY_ID", [{"from": "VERIFY_ID", "to": "PROCESS_CASE"}], {"mode": "stub"})
    line = (tmp_path / "audit.jsonl").read_text().strip()
    entry = json.loads(line)
    assert entry["phase_after"] == "PROCESS_CASE" and entry["tools"][0]["name"] == "verify_identity"
    assert "4472" not in line and "Margaret" not in line          # PII masked
    assert audit.purge(s.bb.session_id) == 1
    assert (tmp_path / "audit.jsonl").read_text() == ""
