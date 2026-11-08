"""Carvis PDF ingestion: explicit applicability, content caching, reviewed v2 records."""
from __future__ import annotations

import argparse
from contextlib import closing
import asyncio
import hashlib
import json
import os
import re
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from qdrant_v2 import STAGING_COLLECTION, open_client, upsert_records
from spec_extract import extract_records
from spec_schema import EMBEDDING_MODEL, Vehicle, digest

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")
PARSE_CACHE_DIR = PROJECT_ROOT / ".carvis_parse_cache"
PARSER_VERSION = os.getenv("CARVIS_PARSER_VERSION", "latest")
PARSE_PROMPT = (
    "Transcribe the manual faithfully as Markdown, preserving all numerical values, "
    "units, table columns, variant headers, ordered steps, warnings and footnotes. "
    "Do not synthesize torque tables, infer missing cells, convert units, or fill missing values."
)

_UNIT_EXPANSION_RULES: Sequence[tuple[re.Pattern[str], str]] = (
    (re.compile(r"\blb\.\s*ft\.", re.IGNORECASE), "foot-pounds"),
    (re.compile(r"\blb\.\s*ft\b", re.IGNORECASE), "foot-pounds"),
    (re.compile(r"\blb\.\-ft\.?", re.IGNORECASE), "foot-pounds"),
    (re.compile(r"\blb\s*-\s*ft\.?\b", re.IGNORECASE), "foot-pounds"),
    (re.compile(r"\bft\.\s*lb\.?", re.IGNORECASE), "foot-pounds"),
    (re.compile(r"\bft\s*-\s*lb\.?\b", re.IGNORECASE), "foot-pounds"),
    (re.compile(r"\bft\s+lbs?\b", re.IGNORECASE), "foot-pounds"),
    (re.compile(r"(?<=\d)ft\s*lbs?\b", re.IGNORECASE), " foot-pounds"),
    (re.compile(r"\blb\.\s*in\.", re.IGNORECASE), "inch-pounds"),
    (re.compile(r"\blb\.\s*in\b", re.IGNORECASE), "inch-pounds"),
    (re.compile(r"\blb\.\-in\.?", re.IGNORECASE), "inch-pounds"),
    (re.compile(r"\blb\s*-\s*in\.?\b", re.IGNORECASE), "inch-pounds"),
    (re.compile(r"\bin\.\s*lb\.?", re.IGNORECASE), "inch-pounds"),
    (re.compile(r"\bin\s*-\s*lb\.?\b", re.IGNORECASE), "inch-pounds"),
    (re.compile(r"\bin\s+lbs?\b", re.IGNORECASE), "inch-pounds"),
    (re.compile(r"\bN\s*[·•\.]\s*m\b"), "newton-meters"),
    (re.compile(r"\bN\s*-\s*m\b"), "newton-meters"),
    (re.compile(r"\bNm\b"), "newton-meters"),
)


def expand_mechanical_units(text: str) -> str:
    for pattern, replacement in _UNIT_EXPANSION_RULES:
        text = pattern.sub(replacement, text)
    return text


def document_ref_from_path(path: Path) -> str:
    return path.stem.strip().lower().replace(" ", "_")


def content_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parser_config(premium: bool = False) -> dict:
    return {"provider": "llamaparse", "sdk_version": version("llama-cloud-services"),
            "version": PARSER_VERSION, "tier": "cost_effective",
            "premium_mode": premium, "prompt": PARSE_PROMPT, "format": "page-json-v2"}


def cache_key(path: Path, config: dict) -> str:
    return digest({"pdf_sha256": content_hash(path), "parser": config})


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        temp = Path(stream.name)
    temp.replace(path)


async def parse_pdf_pages(path: Path, *, force_parse: bool = False,
                          premium_mode: bool = False) -> tuple[list[dict], str, str]:
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ValueError(f"An explicit PDF path is required: {path}")
    config = parser_config(premium_mode)
    pdf_hash = content_hash(path)
    key = digest({"pdf_sha256": pdf_hash, "parser": config})
    cached = PARSE_CACHE_DIR / f"{key}.json"
    if cached.is_file() and not force_parse:
        data = json.loads(cached.read_text())
        if data["pdf_sha256"] != pdf_hash or data["parser"] != config:
            raise ValueError("Parse cache provenance mismatch")
        return data["pages"], pdf_hash, config["version"]
    api_key = (os.getenv("LLAMA_CLOUD_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("LLAMA_CLOUD_API_KEY is required to parse an uncached PDF")
    from llama_parse import LlamaParse
    parser = LlamaParse(api_key=api_key, result_type="markdown", language="en",
                        tier=config["tier"], version=config["version"],
                        premium_mode=premium_mode, system_prompt=PARSE_PROMPT,
                        invalidate_cache=force_parse, do_not_cache=False,
                        ignore_errors=False)
    results = await parser.aget_json(str(path))
    pages = []
    for result in results:
        for page in result.get("pages", []):
            if page.get("success") is False:
                raise ValueError("A source page failed parsing; existing data was left intact")
            markdown = page.get("md")
            number = page.get("page")
            if not isinstance(markdown, str) or not isinstance(number, int) or number < 1:
                raise ValueError("Parser returned missing page text/number; cannot fabricate provenance")
            pages.append({"page": number, "markdown": markdown})
    if not pages or len({p["page"] for p in pages}) != len(pages):
        raise ValueError("Empty or duplicate parser pages")
    atomic_json(cached, {"pdf_sha256": pdf_hash, "parser": config, "pages": pages})
    return pages, pdf_hash, config["version"]


async def run_ingest(pdf_path: Path, year: str, make: str, model: str, embedding_model=None,
                     *, shop_id: str, force_parse: bool = False, premium_mode: bool = False,
                     transmission: str | None = None, engine_code: str | None = None,
                     trim: str | None = None, market: str | None = None,
                     wheel_size: str | None = None,
                     document_ref: str | None = None, collection: str = STAGING_COLLECTION,
                     export: Path | None = None, client=None,
                     page_evidence: Path | None = None) -> int:
    vehicle = Vehicle(shop_id=shop_id, year=year, make=make, model=model,
                      transmission=transmission, engine_code=engine_code, trim=trim, market=market,
                      wheel_size=wheel_size)
    if page_evidence:
        # Explicit transcription fallback for scans/merged cells. This still
        # creates pending records and never authorizes technical answers.
        evidence = json.loads(page_evidence.read_text())
        pdf_hash = content_hash(pdf_path)
        if evidence.get("pdf_sha256") != pdf_hash or not evidence.get("transcribed_by"):
            raise ValueError("Page evidence must identify the transcriber and match the original PDF hash")
        pages = evidence["pages"]
        if not pages or any(not isinstance(p.get("page"), int) or p["page"] < 1
                            or not isinstance(p.get("markdown"), str) for p in pages):
            raise ValueError("Page evidence requires numbered source pages and text")
        parser_version = "source-transcription:" + digest(evidence)
    else:
        pages, pdf_hash, parser_version = await parse_pdf_pages(
            pdf_path, force_parse=force_parse, premium_mode=premium_mode)
    records = extract_records(pages, vehicle, document_ref=document_ref or document_ref_from_path(pdf_path),
                              source_file=pdf_path.name, document_hash=pdf_hash, parser_version=parser_version)
    if not records:
        raise ValueError("No atomic records extracted; existing data was left intact")
    if export:
        atomic_json(export, [r.model_dump() for r in records])
    if embedding_model is None:
        from fastembed import TextEmbedding
        embedding_model = TextEmbedding(model_name=EMBEDDING_MODEL)
    if client is not None:
        return upsert_records(client, embedding_model, records, collection)
    with closing(open_client()) as owned:
        return upsert_records(owned, embedding_model, records, collection)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Ingest Carvis manuals to staging; all new records require source review")
    parser.add_argument("pdf_paths", nargs="*")
    parser.add_argument("--manifest", type=Path, help="JSON documents list; paths relative to the manifest")
    parser.add_argument("--page-evidence", type=Path, help="Explicit source transcription fallback, bound to the PDF hash")
    for name in ("year", "make", "model", "shop-id", "transmission", "engine-code", "trim", "market", "wheel-size"):
        parser.add_argument("--" + name)
    parser.add_argument("--collection", default=STAGING_COLLECTION)
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument("--premium", action="store_true")
    parser.add_argument("--export-dir", type=Path, help="Local review JSON (keep it outside Git)")
    args = parser.parse_args(argv)
    if bool(args.pdf_paths) == bool(args.manifest):
        parser.error("Supply explicit PDF paths OR a vehicle manifest")
    if args.manifest and (args.page_evidence or any(getattr(args, name) for name in ("year", "make", "model", "shop_id", *("transmission", "engine_code", "trim", "market", "wheel_size")))):
        parser.error("Put applicability in each manifest entry, not in both CLI and manifest")
    if not args.manifest and not all((args.year, args.make, args.model, args.shop_id)):
        parser.error("--year, --make, --model and --shop-id are required")
    return args


def ingestion_jobs(args) -> list[dict]:
    if args.manifest:
        raw = json.loads(args.manifest.read_text())
        docs = raw["documents"]
        base = args.manifest.resolve().parent
    else:
        fields = {k: getattr(args, k) for k in Vehicle.model_fields}
        docs = [{"path": p, **fields} for p in args.pdf_paths]
        base = Path.cwd()
    if not isinstance(docs, list) or not docs:
        raise ValueError("Manifest needs a nonempty documents list")
    jobs = []
    for doc in docs:
        unknown = set(doc) - set(Vehicle.model_fields) - {"path", "document_ref", "page_evidence"}
        if unknown:
            raise ValueError(f"Unknown manifest fields: {sorted(unknown)}")
        vehicle = Vehicle(**{k: doc[k] for k in Vehicle.model_fields if k in doc})
        path = (base / doc["path"]).resolve()
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise ValueError(f"PDF not found: {path}")
        evidence_path = doc.get("page_evidence") if args.manifest else args.page_evidence
        evidence_path = (base / evidence_path).resolve() if evidence_path else None
        if evidence_path and not evidence_path.is_file():
            raise ValueError("Page evidence file not found")
        jobs.append({"pdf_path": path, **vehicle.model_dump(), "document_ref": doc.get("document_ref"), "page_evidence": evidence_path})
    return jobs


async def ingest_jobs(args):
    jobs = ingestion_jobs(args)  # Validate the entire manifest before any paid parse or write.
    from fastembed import TextEmbedding
    embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
    for job in jobs:
        export = args.export_dir / f"{content_hash(job['pdf_path'])}.json" if args.export_dir else None
        count = await run_ingest(**job, embedding_model=embedder, collection=args.collection,
                                 force_parse=args.force_parse, premium_mode=args.premium, export=export)
        print(f"Carvis: {count} records staged for review from {job['pdf_path'].name}")


def main(argv=None):
    asyncio.run(ingest_jobs(parse_args(argv)))


if __name__ == "__main__":
    main()
