"""M2 B3a: North American VIN validation (49 CFR 565). Pure; no database."""
from __future__ import annotations

import pytest

from garage.vin import ALLOWED, check_digit, normalize_vin, validate_vin

# Widely published valid VINs (check digit X; the all-ones vector; a common documentation example).
VALID = ("1M8GDM9AXKP042788", "11111111111111111", "1HGCM82633A004352")


def _with_check(base: str) -> str:
    """Replace position 9 with the correct check digit."""
    return base[:8] + check_digit(base) + base[9:]


@pytest.mark.parametrize("vin", VALID)
def test_published_vins_are_valid(vin):
    assert validate_vin(vin).ok


@pytest.mark.parametrize("digit", list("0123456789X"))
def test_every_check_digit_value_is_computed_and_accepted(digit):
    # Vary positions 16 and 17 until the check digit takes each value, then confirm acceptance and rejection.
    candidates = (_with_check("1M8GDM9A0KP0427" + a + b) for a in sorted(ALLOWED) for b in sorted(ALLOWED))
    vin = next(v for v in candidates if v[8] == digit)
    assert validate_vin(vin).ok
    wrong = "0" if digit != "0" else "1"
    assert validate_vin(vin[:8] + wrong + vin[9:]).reason == "check_digit"


def test_check_digit_ten_is_x():
    assert check_digit("1M8GDM9AXKP042788") == "X"


@pytest.mark.parametrize("vin,reason", [
    ("1M8GDM9AXKP04278", "length"),
    ("1M8GDM9AXKP0427888", "length"),
    ("", "length"),
    ("1M8GDM9AXKP04278I", "character"),
    ("1M8GDM9AXKP04278O", "character"),
    ("1M8GDM9AXKP04278Q", "character"),
    ("1M8GDM9AXKP04278-", "character"),
    ("1m8gdm9axkp042788", "character"),  # validate_vin expects normalized input
    ("1M8GDM9AXUP042788", "model_year"),
    ("1M8GDM9AXZP042788", "model_year"),
    ("1M8GDM9AX0P042788", "model_year"),
    ("1M8GDM9A1KP042788", "check_digit"),
])
def test_refusal_reasons(vin, reason):
    result = validate_vin(vin)
    assert not result.ok and result.reason == reason


def test_rules_are_checked_in_order():
    # Wrong length wins over bad characters; bad characters win over model year and check digit.
    assert validate_vin("IOQ").reason == "length"
    assert validate_vin("1M8GDM9AXUP04278O").reason == "character"
    assert validate_vin("1M8GDM9A1UP042788").reason == "model_year"


def test_normalization_strips_and_uppercases_ascii_only():
    assert normalize_vin("  1m8gdm9axkp042788\n") == "1M8GDM9AXKP042788"
    assert validate_vin(normalize_vin(" 1m8gdm9axkp042788 ")).ok


def test_normalization_never_corrects_lookalikes():
    assert normalize_vin("1M8GDM9AXKPO42788") == "1M8GDM9AXKPO42788"
    assert validate_vin(normalize_vin("1M8GDM9AXKPO42788")).reason == "character"
    assert normalize_vin("1M8GDM9AXKP042788").count("I") == 0


@pytest.mark.parametrize("raw", ["１M8GDM9AXKP042788", "1M8GDM9AXKP04278８", "1M8GDM9AXKP04278İ"])
def test_non_ascii_lookalikes_are_refused(raw):
    assert validate_vin(normalize_vin(raw)).reason == "character"


def test_unicode_case_mapping_cannot_produce_a_valid_vin():
    # U+017F LATIN SMALL LETTER LONG S upper-cases to ASCII "S" under str.upper(); it must stay non-ASCII.
    vin = _with_check("1M8GDM9A0KP04278S")
    assert validate_vin(vin).ok
    assert validate_vin(normalize_vin(vin[:-1] + "\u017f")).reason == "character"


def test_non_north_american_vin_without_check_digit_is_refused():
    # A well-formed 17-character VIN (European style, position 9 not a check digit) is refused under the
    # pilot's North American rule (owner decision, 2026-11-24); manual entry without a VIN remains available.
    vin = "WVWZZZ1JZXW000001"
    assert all(c in ALLOWED for c in vin) and vin[8] != check_digit(vin)
    assert validate_vin(vin).reason == "check_digit"


@pytest.mark.parametrize("value", [None, 17, b"1M8GDM9AXKP042788"])
def test_non_strings_raise(value):
    with pytest.raises(TypeError):
        validate_vin(value)
    with pytest.raises(TypeError):
        normalize_vin(value)
