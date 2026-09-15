"""Data sanity check: `python -m app.data.check`.

Prints every policyholder with claim counts and flags documents_needed strings that do
not appear verbatim in document_guidance (CL-2048's two are the expected offenders), then
shows whether the alias resolver rescues them.
"""
from __future__ import annotations

from .loader import load_store


def main() -> int:
    store = load_store()
    guidance_keys = set(store.guideline["document_guidance"])
    problems = 0

    print("Policyholders")
    for p in store.policyholders:
        claims = store.claims_by_party.get(p.party_id, [])
        reps = store.reps_by_buyer.get(p.party_id, [])
        print(f"  {p.party_id:>4} {p.name:<14} {p.policy_number}  id_type={p.id_type:<18} "
              f"claims={len(claims)} reps={len(reps)}")

    print("\nClaims")
    for c in store.claims:
        print(f"  {c.case_id} {c.party_id} {c.case_type:<10} {c.status:<7} created={c.created_at} "
              f"deadline={c.appeal_deadline}")
        for doc in c.documents_needed:
            exact = doc.lower() in guidance_keys
            resolved = store.resolve_document_key(doc)
            flag = "" if exact else ("  -> alias resolves to %r" % resolved if resolved else "  !! UNRESOLVED")
            if not exact:
                problems += 1
            print(f"      doc {doc!r:<32} exact_key={exact}{flag}")

    orphan_claims = [c.case_id for c in store.claims if c.party_id not in store.by_party]
    if orphan_claims:
        print(f"\n!! claims with unknown party: {orphan_claims}")
    print(f"\n{problems} documents_needed strings do not match a guidance key verbatim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
