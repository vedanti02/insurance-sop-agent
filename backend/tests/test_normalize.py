import pytest

from app.normalize import matches, norm_dob, norm_last4, norm_name, norm_phone, spoken_digits


@pytest.fixture(scope="session")
def P9(store):
    return store.by_party["P9"]


@pytest.fixture(scope="session")
def P13(store):
    return store.by_party["P13"]


@pytest.mark.parametrize("v", ["Margaret Chen", "margaret chen", "Chen Margaret", "Mrs. Margaret Chen",
                               "M-A-R-G-A-R-E-T Chen", "MARGARET CHEN."])
def test_name_variants_match(P9, v):
    assert matches("full_name", v, P9)


def test_name_alias_matches_p13(P13):
    assert matches("full_name", "Yaven Li", P13)
    assert matches("full_name", "Ya Wen Li", P13)
    assert not matches("full_name", "Ya Li", P13)


def test_name_near_miss_does_not_match(P9):
    assert not matches("full_name", "Margret Chen", P9)
    assert not matches("full_name", "Margaret Chan", P9)


@pytest.mark.parametrize("v", ["1985-03-15", "March 15 1985", "March 15, 1985", "3/15/85", "15/03/1985",
                               "03/15/1985", "15 March 1985", "15th of March 1985"])
def test_dob_formats(P9, v):
    assert matches("dob", v, P9)


def test_dob_day_month_ambiguity_accepts_both_orders(P13):
    assert matches("dob", "12/03/1989", P13)   # Dec 3 (US) — correct
    assert matches("dob", "03/12/1989", P13)   # 3 Dec (day-first) — also accepted
    assert not matches("dob", "12/04/1989", P13)


def test_dob_wrong_year(P9):
    assert not matches("dob", "1986-03-15", P9)


@pytest.mark.parametrize("v", ["+16505212836", "650-521-2836", "(650) 521 2836", "6505212836", "1 650 521 2836",
                               "six five zero five two one two eight three six"])
def test_phone_formats(P9, v):
    assert matches("phone", v, P9)


def test_phone_collision_is_exact(P9, P13):
    # P9 ends ...2836, P13 ends ...2830 — one digit apart; no prefix/fuzzy matching allowed
    assert not matches("phone", "+16505212830", P9)
    assert matches("phone", "+16505212830", P13)
    assert not matches("phone", "6505212", P9)


def test_email_alias(P13, P9):
    assert matches("email", "yawen.li@example.com", P13)
    assert matches("email", "YaWen.Li@Gmail.com", P13)
    assert matches("email", "margaret at email dot com", P9)
    assert not matches("email", "margaret@example.com", P9)


@pytest.mark.parametrize("v", ["4472", "four four seven two", "4-4-7-2", "my ssn ends in 4472", "xxx-xx-4472"])
def test_last4_forms(P9, v):
    assert matches("id_last4", v, P9)


def test_last4_matches_regardless_of_id_type_label(store):
    p12 = store.by_party["P12"]        # national_id_last4 on file; caller calls it an SSN
    assert matches("id_last4", "6688", p12)
    assert not matches("id_last4", "4472", p12)


def test_helpers():
    assert spoken_digits("four four seven two") == "4472"
    assert norm_last4("12345") == "2345"
    assert norm_phone("+1 (650) 521-2836") == "6505212836"
    assert norm_name("Chen, Margaret") == "chen margaret"
    assert "1985-03-15" in norm_dob("3/15/85")
