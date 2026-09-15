"""Typed views of the fixture files. Field names match the JSON exactly."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class Policyholder(BaseModel):
    party_id: str
    name: str
    name_aliases: list[str] = Field(default_factory=list)
    policy_number: str
    dob: date
    id_type: str
    id_last4: str
    phone: str
    phone_aliases: list[str] = Field(default_factory=list)
    email: str
    email_aliases: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    case_id: str
    party_id: str
    case_type: str
    created_at: date
    status: str
    summary: str
    denial_reason: str | None = None
    documents_needed: list[str] = Field(default_factory=list)
    appeal_deadline: date | None = None
    expected_reimbursement_amount: str
    allowed_max_amount: str
    net_pay: str
    net_fee: str


class Representative(BaseModel):
    rep_name: str
    relationship: str
    buyer_name: str
    buyer_party_id: str


class ConsentScenario(BaseModel):
    status_sequence: list[str]
