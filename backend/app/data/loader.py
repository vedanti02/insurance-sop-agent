"""Fixture loading plus the joins the fixtures withhold.

Joins built here:
  policy_number -> party_id
  party_id      -> claims[]            (claims link on party, not policy)
  buyer_party_id + rep_name -> representative
  documents_needed[] -> document_guidance key (via DOC_ALIASES + token overlap)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..config import FIXTURES_DIR
from .models import Claim, ConsentScenario, Policyholder, Representative

log = logging.getLogger(__name__)

# The claim records name documents differently from the guidance file. Explicit map first,
# token overlap as a fallback, and anything that resolves neither way is logged loudly.
DOC_ALIASES: dict[str, str] = {
    "pathology report": "original pathology report",
    "office note": "treating provider office note",
}


@dataclass
class Store:
    policyholders: list[Policyholder]
    claims: list[Claim]
    representatives: list[Representative]
    consent_scenarios: dict[str, ConsentScenario]
    guideline: dict
    claim_schema: dict
    by_party: dict[str, Policyholder] = field(init=False)
    by_policy: dict[str, Policyholder] = field(init=False)
    claims_by_party: dict[str, list[Claim]] = field(init=False)
    claims_by_id: dict[str, Claim] = field(init=False)
    reps_by_buyer: dict[str, list[Representative]] = field(init=False)
    records_by_party: dict[str, list[Claim]] = field(init=False)
    records_by_id: dict[str, Claim] = field(init=False)

    def __post_init__(self) -> None:
        self.by_party = {p.party_id: p for p in self.policyholders}
        self.by_policy = {p.policy_number.upper(): p for p in self.policyholders}
        self.claims_by_party = {}
        for c in self.claims:
            self.claims_by_party.setdefault(c.party_id, []).append(c)
        self.claims_by_id = {c.case_id: c for c in self.claims}
        self.reps_by_buyer = {}
        for r in self.representatives:
            self.reps_by_buyer.setdefault(r.buyer_party_id, []).append(r)
        # generic names the engine uses; a vertical's records are whatever it disputes/claims/etc.
        self.records_by_party = self.claims_by_party
        self.records_by_id = self.claims_by_id

    # --- document name resolution -------------------------------------------------
    def resolve_document_key(self, name: str) -> str | None:
        """Map a claim's documents_needed string to a document_guidance key, or None."""
        guidance = self.guideline.get("document_guidance", {})
        n = name.strip().lower()
        if n in guidance:
            return n
        if n in DOC_ALIASES and DOC_ALIASES[n] in guidance:
            return DOC_ALIASES[n]
        tokens = set(n.split())
        best, best_score = None, 0.0
        for key in guidance:
            ktoks = set(key.split())
            score = len(tokens & ktoks) / len(tokens | ktoks)
            if score > best_score:
                best, best_score = key, score
        if best and best_score >= 0.5 and tokens <= set(best.split()):
            return best
        log.warning("unresolved document name %r (best guess %r @ %.2f rejected)", name, best, best_score)
        return None

    def document_guidance(self, name: str) -> str:
        key = self.resolve_document_key(name)
        if key:
            return self.guideline["document_guidance"][key]["en"]
        return self.guideline["default_guidance"]["en"]

    def document_alternative(self, name: str) -> str:
        key = self.resolve_document_key(name)
        alts = self.guideline["document_alternative_guidance"]
        if key and key in alts:
            return alts[key]["en"]
        return alts["default"]["en"]


def _read(path: Path):
    with path.open() as f:
        return json.load(f)


def load_store(fixtures_dir: Path = FIXTURES_DIR) -> Store:
    return Store(
        policyholders=[Policyholder(**p) for p in _read(fixtures_dir / "policyholders.json")],
        claims=[Claim(**c) for c in _read(fixtures_dir / "claims.json")],
        representatives=[Representative(**r) for r in _read(fixtures_dir / "representatives.json")],
        consent_scenarios={k: ConsentScenario(**v) for k, v in _read(fixtures_dir / "consent_scenarios.json").items()},
        guideline=_read(fixtures_dir / "required_document_guideline.json"),
        claim_schema=_read(fixtures_dir / "claim_schema.json"),
    )
