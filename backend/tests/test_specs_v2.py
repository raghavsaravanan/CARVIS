"""Safety regression tests using real local Qdrant and deterministic test embeddings.

Oil facts are transcribed from wrxOilAmount.pdf, page 1, CAPACITY table:
the engine-oil cells span both 6MT/CVT columns. Values/units were visually
checked against the original PDF. Other numerical fixtures below are SYNTHETIC
adversarial inputs, never production/manual evidence.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from qdrant_client import QdrantClient, models
from fastapi.testclient import TestClient

import ingest
import main
import migrate_v2
from migrate_v2 import activate, review_records, validate_collection
from qdrant_v2 import LEGACY_COLLECTION, configure, upsert_records
from spec_extract import extract_records
from spec_retrieval import SpecificationRefusal, evaluate_candidates, lookup, normalize_request
from spec_schema import SpecRecord, Vehicle, evidence_errors, parse_quantity

VEHICLE = Vehicle(shop_id="shop_demo", year="2022", make="subaru", model="wrx")
COLLECTION = "carvis_specs_v2_test"
OIL_TABLE = """## SPECIFICATIONS > WRX CAPACITY
| Model | Item | Unit | 2.4 L DOHC turbo 6MT | 2.4 L DOHC turbo CVT |
| --- | --- | --- | --- | --- |
| Engine oil | Total capacity (at overhaul) | L (US qt, Imp qt) | 5.55 (5.9, 4.9) | 5.55 (5.9, 4.9) |
| Engine oil | When replacing engine oil and oil filter | L (US qt, Imp qt) | 4.5 (4.8, 4.0) | 4.5 (4.8, 4.0) |
| Engine oil | When replacing engine oil only | L (US qt, Imp qt) | 4.3 (4.5, 3.8) | 4.3 (4.5, 3.8) |
"""


class Embeddings:
    def embed(self, texts):
        for _ in texts:
            yield [1.0] + [0.0] * 383


def extracted(text=OIL_TABLE, document_hash="a" * 64, source_file="wrxOilAmount.pdf"):
    return extract_records([{"page": 1, "markdown": text,
        "table_row_offsets": {"1": 1} if text == OIL_TABLE else {}}], VEHICLE,
        document_ref="wrx-capacity", source_file=source_file,
        document_hash=document_hash, parser_version="test-source-transcription")


def reviewed(record):
    record = record.model_copy(deep=True)
    assert not evidence_errors(record, require_review=False)
    record.verification_status = "verified"
    record.verified_by = "test-fixture-review"
    record.verified_at = "2026-11-07T00:00:00Z"
    record.verification_digest = record.evidence_digest()
    return record


@pytest.fixture
def db():
    client = QdrantClient(":memory:")
    try:
        configure(client, COLLECTION)
        yield client
    finally:
        client.close()


def put(db, records):
    upsert_records(db, Embeddings(), records, COLLECTION)


def ask(db, query, **vehicle):
    return lookup(db, Embeddings(), COLLECTION, query, VEHICLE.model_copy(update=vehicle))


@pytest.mark.parametrize("transmission", ["6MT", "CVT"])
@pytest.mark.parametrize("operation,value,raw", [
    ("with filter", "4.5", "4.5 (4.8, 4.0)"),
    ("without filter", "4.3", "4.3 (4.5, 3.8)"),
])
def test_wrx_original_document_values(db, transmission, operation, value, raw):
    records = [reviewed(r) for r in extracted()]
    put(db, records)
    answer = ask(db, f"Engine oil capacity {operation} {transmission}")
    assert len(answer.records) == 1
    assert answer.records[0].numeric_value == value
    assert answer.records[0].raw_value == raw
    assert answer.records[0].unit == "L"
    assert answer.records[0].transmission == transmission.lower()
    assert f"{value} liters" in answer.answer
    assert "newton" not in answer.answer
    assert answer.sources[0]["source_page"] == 1
    assert answer.sources[0]["source_row"] == (3 if operation == "with filter" else 4)
    assert "wrxOilAmount.pdf" in answer.source
    assert all(v >= 0 for v in answer.timings_ms.values())


def test_missing_transmission_even_when_values_equal(db):
    put(db, [reviewed(r) for r in extracted()])
    with pytest.raises(SpecificationRefusal, match="transmission"):
        ask(db, "engine oil capacity with filter")


def test_missing_filter_context(db):
    with pytest.raises(SpecificationRefusal, match="operation"):
        ask(db, "engine oil capacity 6MT")


@pytest.mark.parametrize("vehicle", [{"year": "2021"}, {"model": "forester"}, {"make": "honda"}, {"shop_id": "other"}])
def test_no_cross_vehicle_or_shop_fallback(db, vehicle):
    put(db, [reviewed(r) for r in extracted()])
    with pytest.raises(SpecificationRefusal, match="No verified"):
        ask(db, "engine oil capacity with filter 6MT", **vehicle)


def test_question_vehicle_year_conflict(db):
    with pytest.raises(SpecificationRefusal, match="year"):
        ask(db, "2021 engine oil capacity with filter 6MT")


def test_transmission_values_remain_distinct(db):
    # Deliberately divergent synthetic values expose variant substitution.
    rows = extracted()
    for row in rows:
        if row.operation == "oil_and_filter" and row.transmission == "cvt":
            row.raw_value = "9.9 L"
            cells = row.source_excerpt.split("|")
            cells[-2] = " 9.9 L "
            row.source_excerpt = "|".join(cells)
            row.numeric_value = "9.9"
    put(db, [reviewed(r) for r in rows])
    assert ask(db, "engine oil capacity with filter CVT").records[0].numeric_value == "9.9"
    assert ask(db, "engine oil capacity with filter 6MT").records[0].numeric_value == "4.5"


def test_wheel_and_camber_fasteners_are_separate(db):
    synthetic = """## Synthetic fastener disambiguation
| Application | Torque |
| --- | --- |
| Wheel nuts | 101 N·m |
| Camber bolt | 202 N·m |
"""
    put(db, [reviewed(r) for r in extracted(synthetic)])
    assert ask(db, "wheel bolt torque").records[0].numeric_value == "101"
    assert ask(db, "camber bolt torque").records[0].numeric_value == "202"


def test_camber_only_and_height_cannot_answer_wheel_torque(db):
    text = """## Synthetic camber
| Application | Torque |
| --- | --- |
| Camber bolt | 202 N·m |
"""
    put(db, [reviewed(r) for r in extracted(text)])
    with pytest.raises(SpecificationRefusal, match="No verified"):
        ask(db, "wheel bolt torque")


@pytest.mark.parametrize("query", ["wheel and camber bolt torque", "oil capacity with and without filter 6MT"])
def test_ambiguous_requests_refuse(query):
    with pytest.raises(SpecificationRefusal):
        normalize_request(query)


def test_pending_and_tampered_evidence_never_authoritative(db):
    records = extracted()
    put(db, records)
    with pytest.raises(SpecificationRefusal):
        ask(db, "engine oil capacity with filter 6MT")
    record = reviewed(records[2])
    record.numeric_value = "99"
    assert evidence_errors(record)
    db.overwrite_payload(COLLECTION, record.model_dump(), [records[2].point_id()])
    with pytest.raises(SpecificationRefusal, match="unverified"):
        ask(db, "engine oil capacity with filter 6MT")


def test_conflicting_manual_values_refuse(db):
    first = [reviewed(r) for r in extracted()]
    other = extracted(OIL_TABLE.replace("4.5 (4.8, 4.0)", "4.6 (4.9, 4.1)"), "b" * 64)
    for row in other:
        row.document_ref = "second-manual"
    put(db, first + [reviewed(r) for r in other])
    with pytest.raises(SpecificationRefusal) as exc:
        ask(db, "engine oil capacity with filter 6MT")
    assert exc.value.code == "conflict"


def test_same_document_revision_conflict(db):
    put(db, [reviewed(r) for r in extracted() + extracted(document_hash="b" * 64)])
    with pytest.raises(SpecificationRefusal, match="revisions"):
        ask(db, "engine oil capacity with filter 6MT")


def test_missing_numeric_evidence():
    r = extracted()[2]
    r.numeric_value = None
    assert evidence_errors(r, require_review=False)
    with pytest.raises(SpecificationRefusal):
        evaluate_candidates([r.model_dump()], VEHICLE, normalize_request("engine oil capacity with filter 6MT"))


@pytest.mark.parametrize("raw", ["120 N·m then 90 degrees", "120 N·m; 155 N·m", "11.64 (12.3) *1; 11.98 (12.6) *2", "—", "approximately 4.5 L"])
def test_multi_value_cells_are_not_flattened(raw):
    assert parse_quantity(raw, "L") == {}


def test_ordered_multi_stage_procedure(db):
    synthetic = """## Synthetic torque procedure
| Application | Step | Torque |
| --- | --- | --- |
| Wheel nuts | 1 | 10 N·m |
| Wheel nuts | 2 | 20 N·m |
"""
    records = extracted(synthetic)
    assert [r.step_count for r in records] == [2, 2]
    put(db, [reviewed(r) for r in records])
    result = ask(db, "wheel bolt torque")
    assert result.answer.index("10 newton-meters") < result.answer.index("20 newton-meters")
    assert len(result.sources) == 2


def test_incomplete_procedure_refuses(db):
    r = extracted("""## Synthetic torque
| Application | Step | Torque |
| --- | --- | --- |
| Wheel nuts | 1 | 10 N·m |
""")[0]
    r.step_count = 2
    put(db, [reviewed(r)])
    with pytest.raises(SpecificationRefusal, match="complete"):
        ask(db, "wheel bolt torque")


def test_duplicate_document_preserves_review(db):
    records = [reviewed(r) for r in extracted()]
    put(db, records)
    put(db, extracted())
    assert db.count(COLLECTION).count == len(records)
    assert ask(db, "engine oil capacity with filter 6MT").records[0].verification_status == "verified"


def test_updated_pdf_same_filename_cache_and_ids(tmp_path):
    path = tmp_path / "manual.pdf"
    path.write_bytes(b"%PDF-version-one")
    key1 = ingest.cache_key(path, {"version": "one"})
    hash1 = ingest.content_hash(path)
    path.write_bytes(b"%PDF-version-two")
    key2 = ingest.cache_key(path, {"version": "one"})
    assert key1 != key2
    assert key2 != ingest.cache_key(path, {"version": "two"})
    assert extracted(document_hash=hash1)[0].point_id() != extracted(document_hash=ingest.content_hash(path))[0].point_id()


def test_embedding_failure_without_data_loss(db):
    put(db, extracted())
    before = db.count(COLLECTION).count
    class Broken:
        def embed(self, texts):
            raise RuntimeError("embedding unavailable")
    with pytest.raises(RuntimeError):
        upsert_records(db, Broken(), extracted(document_hash="b" * 64), COLLECTION)
    assert db.count(COLLECTION).count == before


def test_parser_failure_without_data_loss(db, monkeypatch, tmp_path):
    put(db, extracted())
    before = db.count(COLLECTION).count
    monkeypatch.setattr(ingest, "parse_pdf_pages", AsyncMock(side_effect=RuntimeError("parse failed")))
    with pytest.raises(RuntimeError):
        asyncio.run(ingest.run_ingest(tmp_path / "manual.pdf", "2022", "subaru", "wrx",
                    shop_id="shop_demo", client=db, embedding_model=Embeddings(), collection=COLLECTION))
    assert db.count(COLLECTION).count == before


def test_protected_legacy_and_active_collection(db):
    with pytest.raises(ValueError):
        configure(db, LEGACY_COLLECTION)
    db.update_collection_aliases([models.CreateAliasOperation(create_alias=models.CreateAlias(
        alias_name="carvis_specs_active", collection_name=COLLECTION))])
    with pytest.raises(ValueError, match="alias"):
        put(db, extracted())


def test_manifest_requires_explicit_metadata_and_validates_all_files(tmp_path):
    path = tmp_path / "input.pdf"
    path.write_bytes(b"%PDF")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": [{"path": "input.pdf", **VEHICLE.model_dump()}]}))
    args = ingest.parse_args(["--manifest", str(manifest)])
    assert ingest.ingestion_jobs(args)[0]["pdf_path"] == path
    manifest.write_text(json.dumps({"documents": [{"path": "input.pdf", "make": "subaru"}]}))
    with pytest.raises(ValueError):
        ingest.ingestion_jobs(args)
    with pytest.raises(SystemExit):
        ingest.parse_args([str(path)])


def test_source_review_is_bound_to_pdf_and_evidence(db, tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-synthetic-review-only")
    records = extracted(document_hash=ingest.content_hash(path), source_file=path.name)
    put(db, records)
    with pytest.raises(ValueError):
        review_records(db, COLLECTION, [r.model_dump() for r in records], source=path, reviewer="reviewer", confirm_source_reviewed=False)
    assert review_records(db, COLLECTION, [r.model_dump() for r in records], source=path, reviewer="reviewer", confirm_source_reviewed=True) == 6
    path.write_bytes(b"%PDF-changed")
    with pytest.raises(ValueError, match="hash"):
        review_records(db, COLLECTION, [r.model_dump() for r in records], source=path, reviewer="reviewer", confirm_source_reviewed=True)


def test_unreviewed_collection_cannot_pass_migration(db):
    put(db, extracted())
    with pytest.raises(ValueError, match="No reviewed"):
        validate_collection(db, Embeddings(), COLLECTION, [], require_indexes=False)


def test_vision_and_vapi_contracts(db, monkeypatch):
    put(db, [reviewed(r) for r in extracted()])
    monkeypatch.setattr(main, "COLLECTION_NAME", COLLECTION)
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "test-only")
    monkeypatch.setattr(main, "identify_component", AsyncMock(side_effect=AssertionError("Inference unnecessary")))
    main.app.state.qdrant = db
    main.app.state.embedder = Embeddings()
    client = TestClient(main.app)
    response = client.post("/vision-query", files={"file": ("frame.jpg", b"\xff\xd8\xff\xe0demo", "image/jpeg")},
        data={"question": "engine oil capacity with filter", "session_id": "test", "year": "2022", "make": "subaru", "model": "wrx", "transmission": "6mt"})
    assert response.status_code == 200, response.text
    assert response.json()["source_grounded"] is True
    assert "4.5 liters" in response.json()["answer"]
    payload = {"message": {"toolCallList": [{"id": "call-1", "function": {
        "arguments": json.dumps({"query": "engine oil capacity with filter", **VEHICLE.model_dump(), "transmission": "cvt"})}}]}}
    response = client.post("/vapi-tool", json=payload, headers={"x-vapi-secret": "test-only"})
    item = response.json()["results"][0]
    assert item["toolCallId"] == "call-1"
    assert item["source_grounded"] and "4.5 liters" in item["result"]
    assert client.post("/vapi-tool", json=payload).status_code == 401


def test_legacy_requires_migration(db):
    with pytest.raises(SpecificationRefusal) as exc:
        lookup(db, Embeddings(), LEGACY_COLLECTION, "wheel nut torque", VEHICLE)
    assert exc.value.code == "migration_pending"


def test_renamed_identical_document_does_not_duplicate(db):
    put(db, [reviewed(r) for r in extracted()])
    renamed = extracted(source_file="renamed.pdf")
    for r in renamed:
        r.document_ref = "renamed"
    put(db, renamed)
    assert db.count(COLLECTION).count == 6
    assert ask(db, "engine oil capacity with filter 6MT").records[0].source_file == "wrxOilAmount.pdf"


def test_split_header_never_copies_missing_variant_cell():
    text = """## WRX CAPACITY
| Model | | 2.4 L DOHC turbo | |
| --- | --- | --- | --- |
| | | 6MT | CVT |
| Engine oil — When replacing engine oil and oil filter (L (US qt, Imp qt)) | | 4.5 (4.8, 4.0) | |
"""
    records = extracted(text)
    assert len(records) == 2
    assert records[0].transmission == "6mt" and records[0].numeric_value == "4.5"
    assert records[1].transmission == "cvt" and records[1].numeric_value is None
    assert evidence_errors(records[1], require_review=False)


def test_initial_final_torque_columns_are_ordered(db):
    text = """## Synthetic installation
| Application | Initial torque | Final torque |
| --- | --- | --- |
| Wheel nuts | 10 N·m | 20 N·m |
"""
    records = extracted(text)
    assert [r.step_order for r in records] == [1, 2]
    put(db, [reviewed(r) for r in records])
    result = ask(db, "wheel bolt torque")
    assert len(result.records) == 2
    assert result.answer.count("10 newton-meters") == 1
    assert "20 N·m" not in result.answer


def test_column_and_review_digest_binding():
    r = reviewed(extracted()[2])
    r.source_value_column = "2.4 L DOHC turbo CVT"
    assert evidence_errors(r)
    r = extracted()[2]
    r.numeric_value, r.raw_value = "4.3", "4.3 (4.5, 3.8)"
    assert evidence_errors(r, require_review=False)


def test_page_evidence_requires_matching_pdf(db, monkeypatch, tmp_path):
    path, transcription = tmp_path / "input.pdf", tmp_path / "page.json"
    path.write_bytes(b"%PDF-synthetic")
    transcription.write_text(json.dumps({"pdf_sha256": "wrong", "transcribed_by": "test",
        "pages": [{"page": 1, "markdown": OIL_TABLE}]}))
    with pytest.raises(ValueError, match="hash"):
        asyncio.run(ingest.run_ingest(path, "2022", "subaru", "wrx", shop_id="shop_demo",
            page_evidence=transcription, client=db, embedding_model=Embeddings(), collection=COLLECTION))
    assert db.count(COLLECTION).count == 0


def test_validation_and_alias_cutover(db, monkeypatch):
    records = [reviewed(r) for r in extracted()]
    put(db, records)
    suite = [{"name": f"{r.operation}-{r.transmission}", "vehicle": VEHICLE.model_dump(),
              "query": "engine oil capacity", "context": {"component": r.component, "operation": r.operation,
              "spec_type": r.spec_type, "transmission": r.transmission},
              "expected": {k: getattr(r, k) for k in ("component", "operation", "spec_type", "transmission",
                 "numeric_value", "unit", "source_file", "source_page", "source_document_hash")}} for r in records]
    suite.append({"name": "no wheel evidence", "vehicle": VEHICLE.model_dump(), "query": "wheel bolt torque", "refusal": "unavailable"})
    original = validate_collection
    monkeypatch.setattr(migrate_v2, "validate_collection", lambda *a, **kw: original(*a, **kw, require_indexes=False))
    report = activate(db, Embeddings(), COLLECTION, suite, expected_previous=None)
    assert report["passed"] and report["verified"] == 6
    assert db.get_aliases().aliases[0].collection_name == COLLECTION
    with pytest.raises(ValueError, match="previous"):
        activate(db, Embeddings(), COLLECTION, suite, expected_previous=None)
    suite[0]["expected"]["numeric_value"] = "99"
    with pytest.raises(ValueError, match="mismatch"):
        original(db, Embeddings(), COLLECTION, suite, require_indexes=False)


def test_nemotron_client_reused(monkeypatch):
    import openai
    factory_calls = []
    class FakeClient:
        def __init__(self, **kwargs):
            factory_calls.append(kwargs)
            from types import SimpleNamespace
            response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"component":"wheel nut","confidence":0.8,"visual_context":"visible fastener"}'))])
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=response)))
    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-only")
    monkeypatch.setattr(main, "_VISION_CLIENT", None)
    monkeypatch.setattr(main, "VISION_PROVIDER", "nemotron")
    async def twice():
        first = await main.identify_component(b"test", "what is this?", "2022", "subaru", "wrx")
        second = await main.identify_component(b"test", "what is this?", "2022", "subaru", "wrx")
        assert first["component"] == second["component"] == "wheel nut"
    asyncio.run(twice())
    assert len(factory_calls) == 1


def test_vision_refuses_missing_filter_without_inference(db, monkeypatch):
    monkeypatch.setattr(main, "COLLECTION_NAME", COLLECTION)
    monkeypatch.setattr(main, "identify_component", AsyncMock(side_effect=AssertionError("A photo cannot confirm filter replacement")))
    main.app.state.qdrant, main.app.state.embedder = db, Embeddings()
    response = TestClient(main.app).post("/vision-query",
        files={"file": ("frame.jpg", b"\xff\xd8\xff\xe0demo", "image/jpeg")},
        data={"question": "engine oil capacity 6MT", "session_id": "test", "year": "2022", "make": "subaru", "model": "wrx"})
    assert response.status_code == 404
    assert response.json()["status"] == "clarification"
    assert response.json()["source_grounded"] is False


def test_partial_network_failure_preserves_existing_records(db, monkeypatch):
    original = [reviewed(r) for r in extracted()]
    put(db, original)
    records = []
    for n in range(12):
        records.extend(extracted(document_hash=f"{n:064x}"))
    real_upsert, calls = db.upsert, []
    def failing_upsert(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("network failed after first batch")
        return real_upsert(*args, **kwargs)
    monkeypatch.setattr(db, "upsert", failing_upsert)
    with pytest.raises(RuntimeError):
        put(db, records)
    assert len(calls) == 2
    stored = db.retrieve(COLLECTION, [r.point_id() for r in original], with_payload=True)
    assert len(stored) == len(original)
    assert all(p.payload["verification_status"] == "verified" for p in stored)


def test_json_schema_matches_runtime():
    path = Path(__file__).parents[1] / "schemas" / "specification-v2.json"
    assert json.loads(path.read_text()) == SpecRecord.model_json_schema()


def test_visual_and_language_hypotheses_cannot_authorize_values(db, monkeypatch):
    visual = main._parse_vision_result(json.dumps({"component": "wheel nut", "confidence": 1,
        "visual_context": "possible wheel fastener", "request_interpretation": {
            "component": "wheel_fastener", "operation": "installation", "spec_type": "torque",
            "numeric_value": "999", "year": "2023"}}))
    assert "numeric_value" not in visual["request_interpretation"]
    assert "year" not in visual["request_interpretation"]
    monkeypatch.setattr(main, "identify_component", AsyncMock(return_value=visual))
    monkeypatch.setattr(main, "COLLECTION_NAME", COLLECTION)
    main.app.state.qdrant, main.app.state.embedder = db, Embeddings()
    response = TestClient(main.app).post("/vision-query",
        files={"file": ("fixture.jpg", b"\xff\xd8\xff\xe0demo", "image/jpeg")},
        data={"question": "what torque for this?", "session_id": "test", "year": "2022", "make": "subaru", "model": "wrx"})
    assert response.status_code == 404
    assert response.json()["source_grounded"] is False
    assert response.json()["component"]["request_interpretation"]["component"] == "wheel_fastener"


def test_row_variants_are_extracted_and_filtered(db):
    text = """## Synthetic engine oil capacity
| Transmission | Engine code | Item | Unit | Capacity |
| --- | --- | --- | --- | --- |
| 6MT | engine-a | Oil and filter | L | 1.1 |
| CVT | engine-b | Oil and filter | L | 2.2 |
"""
    records = extracted(text)
    assert [(r.transmission, r.engine_code, r.numeric_value) for r in records] == [("6mt", "engine-a", "1.1"), ("cvt", "engine-b", "2.2")]
    put(db, [reviewed(r) for r in records])
    with pytest.raises(SpecificationRefusal, match="engine code"):
        ask(db, "engine oil capacity with filter 6MT")
    result = ask(db, "engine oil capacity with filter 6MT", engine_code="engine-a")
    assert result.records[0].numeric_value == "1.1"
    record = records[0].model_copy(update={"transmission": "cvt"})
    assert evidence_errors(record, require_review=False)
