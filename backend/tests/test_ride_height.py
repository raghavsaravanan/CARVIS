"""Suspension (ride) height: nominal by axle and wheel size, tolerance as its own record.

Values transcribed from 02_Suspension.pdf page 14 (2022 WRX) and compared with the
rendered original: Front 133/138 mm, Rear -14/-9 mm, tolerance +24/-12 mm.
"""
from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from qdrant_v2 import configure, upsert_records
from spec_extract import extract_records
from spec_retrieval import SpecificationRefusal, format_records, lookup, normalize_request, ungrounded_numbers
from spec_schema import SpecRecord, Vehicle, evidence_errors, parse_quantity

COLLECTION = "carvis_specs_v2_ride"
VEHICLE = Vehicle(shop_id="shop_demo", year="2022", make="subaru", model="wrx")
BASE = "FRONT SUSPENSION > Wheel Alignment > INSPECTION > 1. SUSPENSION HEIGHT"
PAGE = {"page": 14, "markdown": (
    "Note: Unload any cargo, load the spare tire (tire puncture repair kit), jack and service tools, and fill up the fuel tank.\n\n"
    f"## {BASE} > Suspension height specification mm (in)\n\n"
    "| Model | Front | Rear | Unit |\n| --- | --- | --- | --- |\n"
    "| 17-inch model | 133 (5.24) | -14 (-0.55) | mm (in) |\n"
    "| 18-inch model | 138 (5.43) | -9 (-0.35) | mm (in) |\n\n"
    f"## {BASE} > Suspension height tolerance\n\n"
    "| Item | Value | Unit |\n| --- | --- | --- |\n"
    "| Suspension height tolerance | +24 mm -12 mm (+0.94 in -0.47 in) | mm (in) |\n")}


class Embeddings:
    def embed(self, texts):
        for _ in texts:
            yield [1.0] + [0.0] * 383


def records() -> list[SpecRecord]:
    out = extract_records([PAGE], VEHICLE, document_ref="wrx-suspension", source_file="02_Suspension.pdf",
                          document_hash="b" * 64, parser_version="test-source-transcription")
    specs = [r for r in out if r.record_kind == "specification"]
    for record in specs:
        assert not evidence_errors(record, require_review=False)
        record.verification_status = "verified"
        record.verified_by = "test-fixture-review"
        record.verified_at = "2026-11-08T00:00:00Z"
        record.verification_digest = record.evidence_digest()
    return specs


@pytest.fixture
def db():
    client = QdrantClient(":memory:")
    try:
        configure(client, COLLECTION)
        upsert_records(client, Embeddings(), records(), COLLECTION)
        yield client
    finally:
        client.close()


def ask(db, query, **variants):
    vehicle = VEHICLE.model_copy(update=variants)
    return lookup(db, Embeddings(), COLLECTION, query, vehicle)


def test_tolerance_is_parsed_as_signed_offsets_not_a_range_of_magnitudes():
    assert parse_quantity("+24 mm -12 mm (+0.94 in -0.47 in)", "mm (in)") == {
        "value_min": "-12", "value_max": "+24", "unit": "mm"}


def test_negative_nominal_keeps_its_sign():
    assert parse_quantity("-14 (-0.55)", "mm (in)") == {"numeric_value": "-14", "unit": "mm"}


def test_tolerance_is_a_separate_record_from_every_nominal_height():
    specs = records()
    tolerance = [r for r in specs if r.spec_type == "tolerance"]
    nominal = [r for r in specs if r.spec_type == "dimension"]
    assert len(tolerance) == 1 and len(nominal) == 4
    assert tolerance[0].numeric_value is None
    assert all(r.value_min is None for r in nominal)
    assert {r.point_id() for r in tolerance}.isdisjoint(r.point_id() for r in nominal)


def test_tolerance_answer_speaks_both_signs_and_units(db):
    result = ask(db, "what is the ride height tolerance")
    assert [r.spec_type for r in result.records] == ["tolerance"]
    assert "plus 24 millimeters, minus 12 millimeters" in result.answer
    assert "plus 0.94 inches, minus 0.47 inches" in result.answer
    assert result.sources[0]["source_page"] == 14
    assert not ungrounded_numbers(result.answer, result.records)


def test_tolerance_applies_to_either_axle_and_needs_no_wheel_size(db):
    assert ask(db, "ride height tolerance at the rear").records[0].component == "suspension_height"
    assert ask(db, "front ride height tolerance").records[0].value_max == "+24"


def test_nominal_requires_an_axle():
    with pytest.raises(SpecificationRefusal) as refused:
        normalize_request("what is the ride height")
    assert refused.value.code == "clarification"


def test_nominal_requires_a_wheel_size(db):
    with pytest.raises(SpecificationRefusal) as refused:
        ask(db, "what is the rear ride height")
    assert refused.value.code == "clarification"
    assert "wheel size" in str(refused.value)


@pytest.mark.parametrize("query,wheel,value,spoken", [
    ("front ride height", "17-inch", "133", "133 millimeters (5.24 inches)"),
    ("rear ride height", "17-inch", "-14", "minus 14 millimeters (minus 0.55 inches)"),
    ("front ride height", "18-inch", "138", "138 millimeters (5.43 inches)"),
    ("rear ride height", "18-inch", "-9", "minus 9 millimeters (minus 0.35 inches)"),
])
def test_nominal_selects_axle_and_wheel_size(db, query, wheel, value, spoken):
    result = ask(db, query, wheel_size=wheel)
    assert [r.numeric_value for r in result.records] == [value]
    assert spoken in result.answer
    assert not ungrounded_numbers(result.answer, result.records)


def test_wheel_size_in_the_question_is_honored(db):
    assert ask(db, "rear ride height on the 18 inch model").records[0].numeric_value == "-9"


def test_question_contradicting_confirmed_wheel_size_is_refused(db):
    with pytest.raises(SpecificationRefusal) as refused:
        ask(db, "front ride height on the 18 inch model", wheel_size="17-inch")
    assert refused.value.code == "ambiguous"


def test_confirmed_transmission_does_not_hide_records_that_apply_to_all_transmissions(db):
    assert ask(db, "ride height tolerance", transmission="6mt").records[0].value_max == "+24"


def test_a_record_for_another_variant_stays_excluded(db):
    with pytest.raises(SpecificationRefusal):
        ask(db, "front ride height", wheel_size="19-inch")


def test_spoken_text_with_an_invented_number_is_detected():
    specs = [r for r in records() if r.spec_type == "tolerance"]
    assert ungrounded_numbers(format_records(specs) + " Torque it to 99.", specs) == ["99"]


def test_wheel_size_field_does_not_change_existing_review_signatures():
    record = SpecRecord(shop_id="s", year="2022", make="subaru", model="wrx", document_ref="d",
                        source_excerpt="x", source_document_hash="a" * 64, parser_version="p", search_text="x")
    dumped = record.model_dump()
    assert dumped["wheel_size"] is None
    legacy = {k: v for k, v in dumped.items()
              if k not in ("wheel_size", "verification_status", "verified_by", "verified_at", "verification_digest")}
    from spec_schema import digest
    assert record.evidence_digest() == digest(legacy)
