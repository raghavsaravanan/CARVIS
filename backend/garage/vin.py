"""North American VIN validation (M2 B3a; 49 CFR Part 565).

Scope (owner decision, 2026-11-24): the V1 pilot market is the United States and Canada, so this module applies the
North American rule, including the check digit. A 17-character VIN from another market that does not carry a valid
check digit is refused (``check_digit``); the vehicle can still be added manually without a VIN. This is not a
universal ISO 3779 validator.

Rules, checked in order (49 CFR 565, text verified 2026-11-24):

1. ``length``: exactly 17 characters (565.13(b)).
2. ``character``: only ``0-9`` and ``A-Z`` without ``I``, ``O`` and ``Q`` (565.13(g)), compared against an explicit set.
3. ``model_year``: position 10 is a model-year code; ``U``, ``Z`` and ``0`` are never used (565.15(d)(1), Table VII).
4. ``check_digit``: position 9 equals the weighted transliteration sum modulo 11, with 10 written ``X`` (565.15(c)).

:func:`normalize_vin` only strips surrounding whitespace and upper-cases ASCII letters. It never "corrects" ``O`` to
``0`` or ``I`` to ``1``: that would invent vehicle identity. Non-ASCII input stays non-ASCII and fails ``character``.
The database enforces only length and character set (``vehicles_vin_format``); this module is the application rule
that B3b applies on create and update.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VIN_LENGTH = 17
ALLOWED = frozenset("0123456789ABCDEFGHJKLMNPRSTUVWXYZ")
EXCLUDED_MODEL_YEAR = frozenset("UZ0")
# 565.15(c) Table IV (transliteration) and Table V (weights by position).
TRANSLITERATION = {**{str(d): d for d in range(10)},
                   "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
                   "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
                   "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9}
WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
CHECK_POSITION = 8  # zero-based index of position 9
MODEL_YEAR_POSITION = 9  # zero-based index of position 10

Reason = Literal["length", "character", "model_year", "check_digit"]


@dataclass(frozen=True)
class VinCheck:
    ok: bool
    reason: Reason | None = None


def normalize_vin(raw: str) -> str:
    """Strip surrounding whitespace and upper-case ASCII letters only; nothing else is rewritten."""
    if not isinstance(raw, str):
        raise TypeError("normalize_vin takes a string")
    return "".join(c.upper() if "a" <= c <= "z" else c for c in raw.strip())


def check_digit(vin: str) -> str:
    """The 565.15(c) check digit for a 17-character VIN of allowed characters (position 9 is ignored)."""
    total = sum(TRANSLITERATION[c] * w for c, w in zip(vin, WEIGHTS))
    remainder = total % 11
    return "X" if remainder == 10 else str(remainder)


def validate_vin(vin: str) -> VinCheck:
    """Validate an already normalized VIN under the North American rule; the first failing rule is reported."""
    if not isinstance(vin, str):
        raise TypeError("validate_vin takes a string")
    if len(vin) != VIN_LENGTH:
        return VinCheck(False, "length")
    if any(c not in ALLOWED for c in vin):
        return VinCheck(False, "character")
    if vin[MODEL_YEAR_POSITION] in EXCLUDED_MODEL_YEAR:
        return VinCheck(False, "model_year")
    if vin[CHECK_POSITION] != check_digit(vin):
        return VinCheck(False, "check_digit")
    return VinCheck(True)
