"""Non-destructive Carvis collection configuration and idempotent staging writes."""
from __future__ import annotations

import argparse
from contextlib import closing
import os
import math
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

from spec_schema import EMBEDDING_MODEL, VECTOR_SIZE, SpecRecord

load_dotenv(Path(__file__).parent / ".env")
# This is an existing external identifier, retained solely for migration compatibility.
LEGACY_COLLECTION = "george_specs"
STAGING_COLLECTION = os.getenv("CARVIS_INGEST_COLLECTION", "carvis_specs_v2")
ACTIVE_ALIAS = "carvis_specs_active"
READ_COLLECTION = os.getenv("CARVIS_QDRANT_COLLECTION", LEGACY_COLLECTION)
KEYWORD_FIELDS = ("shop_id", "year", "make", "model", "document_ref", "component",
                  "spec_type", "operation", "transmission", "record_kind",
                  "verification_status", "engine_code", "trim", "market", "wheel_size")


def open_client() -> QdrantClient:
    url, key = os.getenv("QDRANT_URL"), os.getenv("QDRANT_API_KEY")
    if bool(url) != bool(key):
        raise ValueError("QDRANT_URL and QDRANT_API_KEY must be configured together")
    if url:
        return QdrantClient(url=url, api_key=key, timeout=30)
    return QdrantClient(path=str(Path(__file__).parent / "carvis_mvp_db"))


def assert_staging(client, collection: str) -> None:
    if collection == LEGACY_COLLECTION or not collection.startswith("carvis_specs_v2"):
        raise ValueError("Writes require a dedicated carvis_specs_v2 staging collection")
    aliases = client.get_aliases().aliases
    if any(a.collection_name == collection for a in aliases):
        raise ValueError("Cannot mutate a collection behind an alias; build a new staging generation")


def configure(client, collection: str = STAGING_COLLECTION, *, full_text: bool = True) -> None:
    assert_staging(client, collection)
    if not client.collection_exists(collection):
        client.create_collection(collection, vectors_config=models.VectorParams(
            size=VECTOR_SIZE, distance=models.Distance.COSINE))
    info = client.get_collection(collection)
    vector = info.config.params.vectors
    if not isinstance(vector, models.VectorParams) or vector.size != VECTOR_SIZE or vector.distance != models.Distance.COSINE:
        raise ValueError("Existing staging vector configuration is incompatible; no changes made")
    fields = {name: models.PayloadSchemaType.KEYWORD for name in KEYWORD_FIELDS}
    fields["schema_version"] = models.PayloadSchemaType.INTEGER
    if full_text:
        fields["search_text"] = models.PayloadSchemaType.TEXT
    for name, kind in fields.items():
        existing = info.payload_schema.get(name)
        if existing and existing.data_type != kind:
            raise ValueError(f"Incompatible payload index: {name}")
        if not existing:
            client.create_payload_index(collection, name, kind, wait=True)


def upsert_records(client, embedder, records: list[SpecRecord], collection: str = STAGING_COLLECTION) -> int:
    """Build and validate every vector before writes. Never delete prior data."""
    assert_staging(client, collection)
    if not records:
        raise ValueError("No records extracted; existing data was left intact")
    unique = {r.point_id(): r for r in records}
    vectors = list(embedder.embed([r.search_text for r in unique.values()]))
    if len(vectors) != len(unique) or any(len(v) != VECTOR_SIZE or not all(math.isfinite(float(x)) for x in v) for v in vectors):
        raise ValueError("Embedding shape mismatch; existing data was left intact")
    configure(client, collection)
    existing = {}
    ids = list(unique)
    for start in range(0, len(ids), 128):
        for point in client.retrieve(collection, ids[start:start + 128], with_payload=True):
            existing[str(point.id)] = point.payload
    points = []
    for (point_id, record), vector in zip(unique.items(), vectors, strict=True):
        old = existing.get(point_id)
        if old:
            previous = SpecRecord.model_validate(old)
            if previous.point_id() != record.point_id():
                raise ValueError("Point ID collision or modified stored evidence")
            # Re-ingestion cannot erase an existing review decision.
            record = previous
        points.append(models.PointStruct(id=point_id, vector=list(vector), payload=record.model_dump()))
    for start in range(0, len(points), 64):
        client.upsert(collection, points=points[start:start + 64], wait=True)
    return len(points)


def all_points(client, collection: str):
    offset = None
    while True:
        points, offset = client.scroll(collection, limit=128, offset=offset,
                                       with_payload=True, with_vectors=False)
        yield from points
        if offset is None:
            break


def main():
    parser = argparse.ArgumentParser(description="Configure Carvis staging indexes without deleting data")
    parser.add_argument("--collection", default=STAGING_COLLECTION)
    parser.add_argument("--no-full-text", action="store_true", help="For servers without text index support")
    args = parser.parse_args()
    with closing(open_client()) as client:
        configure(client, args.collection, full_text=not args.no_full_text)
    print(f"Carvis staging configured: {args.collection}; model={EMBEDDING_MODEL}")


if __name__ == "__main__":
    main()
