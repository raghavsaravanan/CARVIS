"""Carvis specification payload v2 and deterministic evidence validation."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
VECTOR_SIZE = 384
EXTRACTION_VERSION = "carvis-specs-2.1"
VARIANTS = ("transmission", "engine_code", "trim", "market")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


class Vehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop_id: str
    year: str
    make: str
    model: str
    trim: str | None = None
    engine_code: str | None = None
    transmission: str | None = None
    market: str | None = None

    @field_validator("shop_id", "year", "make", "model", mode="before")
    @classmethod
    def required_text(cls, value):
        value = str(value).strip().lower() if value is not None else ""
        if not value:
            raise ValueError("explicit vehicle metadata is required")
        return value

    @field_validator("year")
    @classmethod
    def year_format(cls, value):
        if not re.fullmatch(r"\d{4}", value):
            raise ValueError("year must have four digits")
        return value

    @field_validator(*VARIANTS, mode="before")
    @classmethod
    def variant_text(cls, value):
        return str(value).strip().lower() or None if value is not None else None


class SpecRecord(Vehicle):
    schema_version: Literal[2] = 2
    record_kind: Literal["specification", "procedure_step", "unclassified"] = "specification"
    component: str | None = None
    component_aliases: list[str] = Field(default_factory=list)
    operation: str | None = None
    spec_type: str | None = None
    # Decimal strings preserve exact source precision; no binary float or conversions.
    numeric_value: str | None = None
    value_min: str | None = None
    value_max: str | None = None
    unit: str | None = None
    raw_value: str | None = None
    conditions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    document_ref: str
    source_file: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    source_section: str | None = None
    source_table: str | None = None
    source_row: int | None = Field(default=None, ge=1)
    source_excerpt: str
    source_header: str | None = None
    source_value_column: str | None = None
    source_unit: str | None = None
    source_document_hash: str
    parser_version: str
    extraction_version: str = EXTRACTION_VERSION
    embedding_model: str = EMBEDDING_MODEL
    verification_status: Literal["pending_review", "verified", "rejected"] = "pending_review"
    verified_by: str | None = None
    verified_at: str | None = None
    verification_digest: str | None = None
    search_text: str
    procedure_id: str | None = None
    step_order: int | None = Field(default=None, ge=1)
    step_count: int | None = Field(default=None, ge=1)

    @field_validator("numeric_value", "value_min", "value_max")
    @classmethod
    def decimal_string(cls, value):
        if value is not None:
            try:
                if not Decimal(value).is_finite():
                    raise ValueError("non-finite numeric evidence")
            except InvalidOperation as exc:
                raise ValueError("invalid decimal") from exc
        return value

    @model_validator(mode="after")
    def numeric_shape(self):
        if (self.value_min is None) != (self.value_max is None):
            raise ValueError("a range requires both endpoints")
        if self.numeric_value is not None and self.value_min is not None:
            raise ValueError("value and range are mutually exclusive")
        if self.value_min is not None and Decimal(self.value_min) > Decimal(self.value_max):
            raise ValueError("reversed range")
        return self

    def evidence_digest(self) -> str:
        return digest(self.model_dump(exclude={"verification_status", "verified_by",
                                              "verified_at", "verification_digest"}))

    def point_id(self) -> str:
        if self.extraction_version == "carvis-specs-2.0":
            return str(uuid.uuid5(uuid.NAMESPACE_URL, "carvis:spec:v2:" + self.evidence_digest()))
        # Renaming/moving identical source bytes cannot duplicate a specification.
        identity = self.model_dump(exclude={"verification_status", "verified_by", "verified_at",
            "verification_digest", "source_file", "document_ref", "search_text"})
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "carvis:spec:v2:" + digest(identity)))


UNIT_LABELS = {
    "L": "liters", "US qt": "US quarts", "Imp qt": "Imperial quarts",
    "N·m": "newton-meters", "ft-lb": "foot-pounds", "in-lb": "inch-pounds",
    "mm": "millimeters", "degree": "degrees",
}
UNIT_PATTERNS = {
    "L": r"(?<!\w)(?:L|liters?)(?!\w)",
    "US qt": r"US\s+qt", "Imp qt": r"Imp\s+qt",
    "N·m": r"\b(?:N\s*[·•.]?\s*m|newton-meters)\b",
    "ft-lb": r"\b(?:ft[. -]*lbs?|lb[. -]*ft|foot-pounds)\b",
    "in-lb": r"\b(?:in[. -]*lbs?|lb[. -]*in|inch-pounds)\b",
    "mm": r"\bmm\b", "degree": r"°|\bdegrees?\b",
}
NUMBER = r"[+-]?\d+(?:\.\d+)?"
VALUE = rf"(?P<first>{NUMBER})(?:\s*[–—-]\s*(?P<last>{NUMBER}))?"


def parse_quantity(raw: str, unit_hint: str | None = None) -> dict:
    """Read a leading quantity only. Never synthesize or convert a value/unit."""
    match = re.match(rf"\s*{VALUE}\s*(?P<tail>.*)$", raw)
    if not match:
        return {}
    tail = match.group("tail")
    unit = next((u for u, pattern in UNIT_PATTERNS.items()
                 if re.match(rf"(?:{pattern})", tail, re.I)), None)
    if unit is None and unit_hint and (not tail or tail.startswith("(")):
        unit = next((u for u, pattern in UNIT_PATTERNS.items()
                     if re.match(rf"(?:{pattern})", unit_hint.strip(), re.I)), None)
    if unit is None:
        return {}
    # A cell with multiple instructions/conditional quantities cannot be reduced
    # to its leading number. Parenthesized source conversions are retained raw.
    remainder = tail
    if remainder and not remainder.startswith("("):
        token = re.match(UNIT_PATTERNS[unit], remainder, re.I)
        if token:
            remainder = remainder[token.end():].strip()
    if remainder and not re.fullmatch(r"\([^()]*\)\s*(?:\\?\*\d+)?", remainder):
        return {}
    if match.group("last"):
        return {"value_min": match.group("first"), "value_max": match.group("last"), "unit": unit}
    return {"numeric_value": match.group("first"), "unit": unit}


def evidence_errors(record: SpecRecord, *, require_review: bool = True) -> list[str]:
    errors = []
    if record.record_kind == "unclassified":
        errors.append("unclassified evidence cannot authorize an answer")
    if record.embedding_model != EMBEDDING_MODEL:
        errors.append("incompatible embedding model")
    if not all((record.component, record.operation, record.spec_type, record.raw_value,
                record.source_excerpt, record.source_file, record.source_section,
                record.source_page, record.source_row)):
        errors.append("missing applicability or source location")
    quantity = parse_quantity(record.raw_value or "", record.source_unit)
    if not quantity or any(getattr(record, key) != quantity.get(key)
                           for key in ("numeric_value", "value_min", "value_max", "unit")):
        errors.append("numeric value/unit do not match the extracted source cell")
    if not record.raw_value or record.raw_value not in record.source_excerpt:
        errors.append("source cell absent from source row")
    if record.source_unit and record.source_unit not in (record.source_header or "") + record.source_excerpt:
        errors.append("unit header absent from evidence")
    if record.source_value_column and record.source_value_column not in (record.source_header or ""):
        errors.append("variant column absent from evidence")
    if record.source_header and record.source_value_column:
        headers = [v.strip() for v in record.source_header.strip().strip("|").split("|")]
        row = [v.strip() for v in record.source_excerpt.strip().strip("|").split("|")]
        if headers.count(record.source_value_column) != 1 or len(row) != len(headers):
            return errors + ["source table shape is invalid"]
        if row[headers.index(record.source_value_column)] != record.raw_value:
            errors.append("value does not match its source column")
        if record.transmission and any(v in record.source_value_column.lower() for v in ("6mt", "cvt")) and record.transmission not in record.source_value_column.lower():
            errors.append("transmission does not match source column")
        lowered = [h.strip().lower().replace(" ", "_") for h in headers]
        if "unit" in lowered and record.source_unit != row[lowered.index("unit")]:
            errors.append("unit does not match the source unit column")
        if record.source_unit and "unit" not in lowered and record.source_unit not in record.source_excerpt:
            errors.append("unit hint is not in the source row")
        for variant in ("transmission", "engine_code", "trim", "market"):
            if variant in lowered:
                source_variant = row[lowered.index(variant)].strip().lower()
                if source_variant and source_variant not in ("—", "-", "n/a") and getattr(record, variant) != source_variant:
                    errors.append(f"{variant} does not match the source row")
    if record.record_kind == "procedure_step" and not all((record.procedure_id, record.step_order, record.step_count)):
        errors.append("incomplete procedure metadata")
    if require_review and (record.verification_status != "verified" or not record.verified_by
                           or not record.verified_at or record.verification_digest != record.evidence_digest()):
        errors.append("record has not been reviewed or evidence changed since review")
    return errors


def citation(record: SpecRecord) -> dict:
    return {key: getattr(record, key) for key in ("document_ref", "source_file", "source_page",
            "source_section", "source_table", "source_row", "source_excerpt", "source_header",
            "source_document_hash")}
