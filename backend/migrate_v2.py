"""Carvis source review, validation, and atomic alias migration. No collection deletion.

Migrate legacy chunks by re-ingesting original PDFs, never by blessing legacy OCR.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path

from qdrant_client import models

from ingest import atomic_json, content_hash
from qdrant_v2 import (ACTIVE_ALIAS, KEYWORD_FIELDS, LEGACY_COLLECTION,
                       STAGING_COLLECTION, all_points, assert_staging, open_client)
from spec_retrieval import SpecificationRefusal, evaluate_candidates, lookup
from spec_schema import EMBEDDING_MODEL, VARIANTS, VECTOR_SIZE, SpecRecord, Vehicle, digest, evidence_errors


def inventory(client, collection):
    points = list(all_points(client, collection))
    return points, digest(sorted((str(p.id), digest(p.payload)) for p in points))


def export_collection(client, collection, destination):
    """Offline backup including vectors. Does not modify the collection."""
    points, offset = [], None
    while True:
        batch, offset = client.scroll(collection, offset=offset, limit=128,
                                      with_payload=True, with_vectors=True)
        points.extend(p.model_dump(mode="json") for p in batch)
        if offset is None:
            break
    atomic_json(destination, {"collection": collection, "points": points})
    return len(points)


def review_records(client, collection, records, *, source: Path, reviewer: str,
                   confirm_source_reviewed: bool):
    assert_staging(client, collection)
    if not confirm_source_reviewed or not reviewer.strip():
        raise ValueError("An identified reviewer must confirm comparison against the original source")
    source_hash = content_hash(source)
    reviewed = []
    for payload in records:
        record = SpecRecord.model_validate(payload)
        if record.source_document_hash != source_hash or record.source_file != source.name:
            raise ValueError("Review PDF hash/filename does not match record provenance")
        errors = evidence_errors(record, require_review=False)
        if errors:
            raise ValueError("Unreviewable record: " + "; ".join(errors))
        point = client.retrieve(collection, [record.point_id()], with_payload=True)
        if len(point) != 1 or SpecRecord.model_validate(point[0].payload).evidence_digest() != record.evidence_digest():
            raise ValueError("Stage the exact reviewed record before approving it")
        record.verification_status = "verified"
        record.verified_by = reviewer.strip()
        record.verified_at = datetime.now(timezone.utc).isoformat()
        record.verification_digest = record.evidence_digest()
        reviewed.append(record)
    if not reviewed:
        raise ValueError("Review selection is empty")
    for record in reviewed:
        client.overwrite_payload(collection, payload=record.model_dump(), points=[record.point_id()], wait=True)
    return len(reviewed)


def validate_collection(client, embedder, collection, suite: list[dict], *, require_indexes=True):
    info = client.get_collection(collection)
    vector = info.config.params.vectors
    if not isinstance(vector, models.VectorParams) or vector.size != VECTOR_SIZE or vector.distance != models.Distance.COSINE:
        raise ValueError("Wrong vector configuration")
    if require_indexes:
        for name in KEYWORD_FIELDS:
            if name not in info.payload_schema or info.payload_schema[name].data_type != models.PayloadSchemaType.KEYWORD:
                raise ValueError(f"Missing or incorrect keyword index: {name}")
        if "schema_version" not in info.payload_schema or info.payload_schema["schema_version"].data_type != models.PayloadSchemaType.INTEGER:
            raise ValueError("Missing or incorrect schema_version integer index")
    points, fingerprint = inventory(client, collection)
    verified = []
    for point in points:
        record = SpecRecord.model_validate(point.payload)
        if str(point.id) != record.point_id():
            raise ValueError("Non-deterministic point identifier")
        if record.verification_status == "verified":
            if evidence_errors(record):
                raise ValueError("Verified record failed evidence validation")
            verified.append(record)
    if not verified:
        raise ValueError("No reviewed specifications available")
    groups = {}
    keys = (*Vehicle.model_fields, "component", "operation", "spec_type")
    for record in verified:
        groups.setdefault(tuple(getattr(record, k) for k in keys), []).append(record)
    for group in groups.values():
        vehicle = Vehicle(**{k: getattr(group[0], k) for k in Vehicle.model_fields})
        slots = {k: getattr(group[0], k) for k in ("component", "operation", "spec_type", *VARIANTS)}
        evaluate_candidates([r.model_dump() for r in group], vehicle, slots)
    if not suite or not any("expected" in c for c in suite) or not any("refusal" in c for c in suite):
        raise ValueError("A source-reviewed acceptance suite must include answers and refusals")
    tested_ids, outcomes = set(), []
    for case in suite:
        vehicle = Vehicle.model_validate(case["vehicle"])
        try:
            result = lookup(client, embedder, collection, case["query"], vehicle, case.get("context"))
        except SpecificationRefusal as exc:
            if case.get("refusal") != exc.code:
                raise ValueError(f"Acceptance case failed: {case['name']}: {exc.code}") from exc
        else:
            if "refusal" in case:
                raise ValueError(f"Unsafe answer in refusal case: {case['name']}")
            expected = case["expected"]
            expected = expected if isinstance(expected, list) else [expected]
            required = {"component", "operation", "spec_type", "unit", "source_document_hash", "source_file", "source_page", "transmission"}
            if not expected or any(not required.issubset(row) or not row.get("source_document_hash")
                                   or not (row.get("numeric_value") is not None or row.get("value_min") is not None and row.get("value_max") is not None)
                                   for row in expected):
                raise ValueError("Expected answers require exact applicability, quantity/unit and original-source provenance")
            actual = [{k: getattr(r, k) for k in expected[n]} for n, r in enumerate(result.records)] if len(result.records) == len(expected) else []
            if not actual or actual != expected:
                raise ValueError(f"Source/value mismatch: {case['name']}")
            tested_ids.update(r.point_id() for r in result.records)
        outcomes.append({"name": case["name"], "passed": True})
    for group in groups.values():
        if not any(r.point_id() in tested_ids for r in group):
            raise ValueError("A verified specification scope has no source-grounded acceptance case")
    return {"collection": collection, "fingerprint": fingerprint, "passed": True,
            "verified": len(verified), "points": len(points), "cases": outcomes,
            "suite_digest": digest(suite), "validated_at": datetime.now(timezone.utc).isoformat()}


def activate(client, embedder, collection, suite, *, expected_previous: str | None):
    """Also used for rollback to a previously validated v2 collection."""
    if not collection.startswith("carvis_specs_v2") or collection not in {c.name for c in client.get_collections().collections}:
        raise ValueError("Activation requires a real Carvis v2 collection, not an alias or legacy collection")
    report = validate_collection(client, embedder, collection, suite)
    current = next((a.collection_name for a in client.get_aliases().aliases if a.alias_name == ACTIVE_ALIAS), None)
    if current != expected_previous:
        raise ValueError("Alias changed since inspection; expected previous target does not match")
    if inventory(client, collection)[1] != report["fingerprint"]:
        raise ValueError("Collection changed during validation")
    actions = []
    if current:
        actions.append(models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=ACTIVE_ALIAS)))
    actions.append(models.CreateAliasOperation(create_alias=models.CreateAlias(alias_name=ACTIVE_ALIAS, collection_name=collection)))
    client.update_collection_aliases(change_aliases_operations=actions)
    return {**report, "previous_target": current, "alias": ACTIVE_ALIAS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export-legacy", "export-review", "review", "validate", "activate"))
    parser.add_argument("--collection", default=STAGING_COLLECTION)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--records", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--reviewer")
    parser.add_argument("--confirm-source-reviewed", action="store_true")
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--expected-previous", help="Current alias target; omit only for initial activation")
    args = parser.parse_args()
    with closing(open_client()) as client:
        if args.command == "export-legacy":
            if not args.output:
                parser.error("--output is required; keep backups outside Git")
            result = {"exported": export_collection(client, LEGACY_COLLECTION, args.output)}
        elif args.command == "export-review":
            if not args.output:
                parser.error("--output is required")
            atomic_json(args.output, [p.payload for p in all_points(client, args.collection)])
            result = {"exported": True}
        elif args.command == "review":
            if not all((args.records, args.source, args.reviewer)):
                parser.error("--records, --source, and --reviewer are required")
            result = {"reviewed": review_records(client, args.collection, json.loads(args.records.read_text()),
                source=args.source, reviewer=args.reviewer, confirm_source_reviewed=args.confirm_source_reviewed)}
        else:
            if not args.suite:
                parser.error("--suite is required")
            from fastembed import TextEmbedding
            embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
            suite = json.loads(args.suite.read_text())
            if args.command == "activate":
                result = activate(client, embedder, args.collection, suite, expected_previous=args.expected_previous)
            else:
                result = validate_collection(client, embedder, args.collection, suite)
            if args.output:
                atomic_json(args.output, result)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
