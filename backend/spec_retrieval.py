"""Exact-filtered Carvis retrieval with complete candidate conflict checks."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from qdrant_client import models

from qdrant_v2 import LEGACY_COLLECTION
from spec_extract import component_from_text, operation_from_text, spec_type_from_text
from spec_schema import SpecRecord, UNIT_LABELS, VARIANTS, Vehicle, citation, evidence_errors


class SpecificationRefusal(ValueError):
    def __init__(self, message: str, code: str = "unavailable"):
        super().__init__(message)
        self.code = code


@dataclass
class LookupResult:
    answer: str
    records: list[SpecRecord]
    timings_ms: dict[str, float] = field(default_factory=dict)

    @property
    def sources(self):
        return [citation(r) for r in self.records]

    @property
    def source(self):
        return "; ".join(f"{r.source_file}, page {r.source_page}, {r.source_section}, row {r.source_row}"
                         for r in self.records)


def normalize_request(query: str, context: dict | None = None) -> dict:
    context = {k: str(v).strip().lower() for k, v in (context or {}).items() if v}
    if re.search(r"\b(?:wheel|lug)\b", query, re.I) and re.search(r"camber", query, re.I):
        raise SpecificationRefusal("Please select wheel fasteners or camber fasteners.", "clarification")
    if re.search(r"(?:with\s+and\s+without|without\s+and\s+with)\b", query, re.I):
        raise SpecificationRefusal("Please select one oil-filter replacement condition.", "clarification")
    component = component_from_text(query)
    operation = operation_from_text(query, component)
    spec_type = spec_type_from_text(query, component)
    result = {}
    for name, inferred in (("component", component), ("operation", operation), ("spec_type", spec_type)):
        explicit = context.get(name)
        if explicit and inferred and explicit != inferred:
            raise SpecificationRefusal(f"The question conflicts with the supplied {name}. Please clarify.", "ambiguous")
        result[name] = explicit or inferred
    if not result["component"]:
        raise SpecificationRefusal("Please name and confirm the exact component. Visual recognition alone is insufficient.", "clarification")
    if not result["operation"]:
        raise SpecificationRefusal("Please specify the operation, including whether the oil filter is being replaced.", "clarification")
    if not result["spec_type"]:
        raise SpecificationRefusal("Please specify which documented specification you need.", "clarification")
    transmissions = set(re.findall(r"\b(?:6mt|cvt)\b", query.lower()))
    if len(transmissions) > 1:
        raise SpecificationRefusal("Please select one transmission: 6MT or CVT.", "clarification")
    if transmissions:
        transmission = next(iter(transmissions))
        if context.get("transmission") and context["transmission"] != transmission:
            raise SpecificationRefusal("Transmission context conflicts with the question.", "ambiguous")
        context["transmission"] = transmission
    for variant in VARIANTS:
        result[variant] = context.get(variant)
    return result


def request_filter(vehicle: Vehicle, slots: dict) -> models.Filter:
    fields = {key: getattr(vehicle, key) for key in ("shop_id", "year", "make", "model")}
    fields.update({key: value for key, value in slots.items() if value is not None})
    fields.update(schema_version=2, verification_status="verified")
    return models.Filter(must=[models.FieldCondition(key=key, match=models.MatchValue(value=value))
                               for key, value in fields.items()] + [models.FieldCondition(
                                   key="record_kind", match=models.MatchAny(any=["specification", "procedure_step"]))])


def evaluate_candidates(payloads: list[dict], vehicle: Vehicle, slots: dict) -> list[SpecRecord]:
    """Validate again in Python; a high semantic score never authorizes an answer."""
    candidates = []
    for payload in payloads:
        try:
            record = SpecRecord.model_validate(payload)
        except ValueError:
            raise SpecificationRefusal("A retrieved record has an invalid evidence schema.", "unverified") from None
        expected = {k: getattr(vehicle, k) for k in ("shop_id", "year", "make", "model")}
        expected.update({k: v for k, v in slots.items() if v is not None})
        if any(getattr(record, k) != v for k, v in expected.items()):
            continue
        if evidence_errors(record):
            raise SpecificationRefusal("The matching specification has incomplete or unverified source evidence.", "unverified")
        candidates.append(record)
    if not candidates:
        raise SpecificationRefusal("No verified specification matches the vehicle, component, and operation.")
    for variant in VARIANTS:
        if slots.get(variant) is None and any(getattr(r, variant) is not None for r in candidates):
            raise SpecificationRefusal(f"Please confirm {variant.replace('_', ' ')} before I select a specification.", "clarification")
    revisions: dict[tuple, set] = {}
    for r in candidates:
        key = (r.shop_id, r.document_ref, r.year, r.make, r.model)
        revisions.setdefault(key, set()).add(r.source_document_hash)
    if any(len(v) > 1 for v in revisions.values()):
        raise SpecificationRefusal("Multiple document revisions match; source review is required.", "conflict")
    if any(r.record_kind == "procedure_step" for r in candidates):
        groups = {r.procedure_id for r in candidates}
        if None in groups or len(groups) != 1:
            raise SpecificationRefusal("Ambiguous multi-stage procedure; review the source.", "conflict")
        candidates.sort(key=lambda r: r.step_order or 0)
        count = candidates[0].step_count
        if len(candidates) != count or any(r.step_count != count for r in candidates) or [r.step_order for r in candidates] != list(range(1, len(candidates) + 1)):
            raise SpecificationRefusal("The complete ordered procedure is unavailable.", "incomplete")
        return candidates
    quantities = {(r.numeric_value, r.value_min, r.value_max, r.unit,
                   tuple(r.conditions), tuple(r.warnings), tuple(r.notes)) for r in candidates}
    if len(quantities) != 1:
        raise SpecificationRefusal("Matching manuals contain conflicting values or conditions; review the sources.", "conflict")
    return candidates


def format_records(records: list[SpecRecord]) -> str:
    sentences = []
    for r in records:
        if evidence_errors(r):
            raise SpecificationRefusal("Source evidence failed verification.", "unverified")
        value = r.numeric_value if r.numeric_value is not None else f"{r.value_min} to {r.value_max}"
        prefix = f"Step {r.step_order}: " if r.step_order else ""
        label = f"{r.year} {r.make.title()} {r.model.upper()}, {r.component.replace('_', ' ')} ({r.operation.replace('_', ' ')})"
        if r.transmission:
            label += f", {r.transmission.upper()}"
        sentences.append(f"{prefix}{label}: {value} {UNIT_LABELS[r.unit]}.")
        redundant = {r.component.replace("_", " ").lower()}
        oil_condition = {"oil_and_filter": "when replacing engine oil and oil filter",
                         "oil_only": "when replacing engine oil only"}
        if r.component == "engine_oil" and r.operation in oil_condition:
            redundant.add(oil_condition[r.operation])
        conditions = [text for text in r.conditions if text.strip().lower() not in redundant]
        for text in dict.fromkeys(conditions + r.warnings + r.notes):
            if text:
                sentences.append(text.rstrip(".") + ".")
    # Never truncate a multi-stage operation or a warning to satisfy a voice length target.
    return " ".join(sentences)


def lookup(client, embedder, collection: str, query: str, vehicle: Vehicle,
           context: dict | None = None) -> LookupResult:
    started = time.perf_counter()
    years = set(re.findall(r"\b(?:19|20|21)\d{2}\b", query))
    if years and years != {vehicle.year}:
        raise SpecificationRefusal("The question conflicts with the confirmed vehicle year.", "ambiguous")
    if collection == LEGACY_COLLECTION:
        raise SpecificationRefusal("Verified Carvis specifications are awaiting migration and source review.", "migration_pending")
    variants = {k: getattr(vehicle, k) for k in VARIANTS}
    variants.update({k: v for k, v in (context or {}).items() if v})
    slots = normalize_request(query, variants)
    filters = request_filter(vehicle, slots)
    # Enumerate the exact verified scope before ranking so a conflict outside top-k cannot hide.
    points, offset = client.scroll(collection, scroll_filter=filters, limit=257,
                                   with_payload=True, with_vectors=False)
    if offset is not None or len(points) > 256:
        raise SpecificationRefusal("Too many applicable records; narrow the component and operation.", "clarification")
    retrieved = time.perf_counter()
    records = evaluate_candidates([p.payload for p in points], vehicle, slots)
    verified = time.perf_counter()
    vector = list(embedder.embed([query]))[0]
    embedded = time.perf_counter()
    hits = client.query_points(collection, query=list(vector), query_filter=filters,
                               limit=16, with_payload=True).points
    # Every selected record came from the fully evaluated set. Ranking only selects a citation.
    if records[0].record_kind != "procedure_step":
        ranks = {str(hit.id): n for n, hit in enumerate(hits)}
        records = [min(records, key=lambda r: (ranks.get(r.point_id(), 999), r.point_id()))]
    finished = time.perf_counter()
    return LookupResult(format_records(records), records, {
        "retrieval": (retrieved-started + finished-embedded)*1000,
        "verification": (verified-retrieved)*1000,
        "embedding": (embedded-verified)*1000,
        "total": (finished-started)*1000,
    })
