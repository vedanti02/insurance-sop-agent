"""Field normalization for identity matching. This is where the fixtures' difficulty lives:
aliases, date formats, spoken digits, spelled names, phone formatting."""
from __future__ import annotations

import re
from datetime import date

from dateutil import parser as dateparser

from .data.models import Policyholder

_WORD_DIGITS = {"zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def spoken_digits(text: str) -> str:
    """'four four seven two' -> '4472'; digits pass through; other words are dropped."""
    out = []
    for tok in re.split(r"[\s,-]+", text.lower()):
        if tok in _WORD_DIGITS:
            out.append(_WORD_DIGITS[tok])
        elif tok.isdigit():
            out.append(tok)
    return "".join(out)


def norm_name(v: str) -> str:
    v = v.strip()
    # spelled-out names: "M-A-R-G-A-R-E-T Chen" or "m a r g a r e t"
    parts = []
    for word in re.split(r"\s{2,}|,", v) or [v]:
        letters = re.findall(r"\b([A-Za-z])\b", word)
        if letters and len(letters) >= 3 and len(letters) == len(re.findall(r"[A-Za-z]+", word)):
            parts.append("".join(letters))
        else:
            parts.append(word)
    v = " ".join(parts)
    v = re.sub(r"-(?=[A-Za-z]\b)", "", v)  # collapse M-A-R-G-A-R-E-T
    v = re.sub(r"\b([A-Za-z])-(?=[A-Za-z])", r"\1", v)
    toks = re.findall(r"[a-z]+", v.casefold())
    toks = [t for t in toks if t not in {"mr", "mrs", "ms", "dr", "miss"}]
    return " ".join(sorted(toks))


def norm_dob(v: str) -> set[str]:
    """All plausible ISO parses (day-first and month-first both count)."""
    out: set[str] = set()
    v = v.strip()
    for dayfirst in (False, True):
        try:
            d = dateparser.parse(v, dayfirst=dayfirst, yearfirst=v[:4].isdigit(), default=date(1900, 1, 1))  # type: ignore[arg-type]
            out.add(d.date().isoformat() if hasattr(d, "date") else str(d))
        except (ValueError, OverflowError):
            pass
    return out


def norm_phone(v: str) -> str:
    digits = re.sub(r"\D", "", v) or spoken_digits(v)
    return digits[-10:]


def norm_email(v: str) -> str:
    return v.strip().lower().replace(" at ", "@").replace(" dot ", ".")


def norm_last4(v: str) -> str:
    digits = re.sub(r"\D", "", v) or spoken_digits(v)
    return digits[-4:]


def candidates_for(record: Policyholder, field: str) -> set[str]:
    if field == "full_name":
        return {norm_name(record.name), *(norm_name(a) for a in record.name_aliases)}
    if field == "dob":
        return {record.dob.isoformat()}
    if field == "phone":
        return {norm_phone(record.phone), *(norm_phone(a) for a in record.phone_aliases)}
    if field == "email":
        return {norm_email(record.email), *(norm_email(a) for a in record.email_aliases)}
    if field == "id_last4":
        return {record.id_last4}
    raise KeyError(field)


def matches(field: str, value: str, record: Policyholder) -> bool:
    cands = candidates_for(record, field)
    if field == "dob":
        return bool(norm_dob(value) & cands)
    if field == "full_name":
        return norm_name(value) in cands
    if field == "phone":
        return norm_phone(value) in cands and len(norm_phone(value)) == 10
    if field == "email":
        return norm_email(value) in cands
    if field == "id_last4":
        return norm_last4(value) in cands and len(norm_last4(value)) == 4
    return False
