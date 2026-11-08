"""Conservative row extraction. OCR output is always pending original-source review."""
from __future__ import annotations

import re
from collections import defaultdict

from spec_schema import SpecRecord, Vehicle, digest, parse_quantity

# Explicit aliases, shared by ingestion and request normalization. Order matters.
COMPONENTS = {
    "camber_fastener": (r"camber.*(?:bolt|nut|fastener)|(?:bolt|nut|fastener).*camber",),
    "oil_drain_plug": (r"(?:oil\s+)?drain\s+plug",),
    "oil_filter": (r"oil filter",),
    "wheel_fastener": (r"\b(?:wheel|lug)[ -]?(?:bolts?|nuts?|fasteners?)\b",),
    "engine_oil": (r"engine oil|oil capacity|oil amount|how much oil|oil change",),
    "intake_manifold_fastener": (r"intake.*(?:bolt|nut|torque)|intake manifold",),
    "suspension_height_front": (r"\bfront\s+(?:suspension|ride|vehicle)\s+height\b",
                                r"\b(?:suspension|ride|vehicle)\s+height\b.{0,24}\bfront\b",),
    "suspension_height_rear": (r"\b(?:rear|back)\s+(?:suspension|ride|vehicle)\s+height\b",
                               r"\b(?:suspension|ride|vehicle)\s+height\b.{0,24}\b(?:rear|back)\b",),
    "suspension_height": (r"suspension height|ride height|vehicle height",),
}


def component_from_text(text: str) -> str | None:
    text = text.lower().replace("_", " ")
    # Capacity applies to the fluid, not the oil filter mentioned as a condition.
    if re.search(r"oil capacity|oil amount|how much oil|replacing engine oil|engine oil.*capacity", text):
        return "engine_oil"
    for name, patterns in COMPONENTS.items():
        if any(re.search(p, text) for p in patterns):
            return name
    return None


def operation_from_text(text: str, component: str | None) -> str | None:
    text = text.lower().replace("_", " ")
    if component == "engine_oil":
        if "overhaul" in text or "dry fill" in text:
            return "overhaul_fill"
        if re.search(r"oil only|without (?:the |an? )?(?:oil )?filter|no filter", text):
            return "oil_only"
        if "filter" in text:
            return "oil_and_filter"
        return None
    if component == "wheel_fastener":
        return "installation"
    if component == "camber_fastener":
        return "alignment"
    if component and component.startswith("suspension_height"):
        return "inspection"
    if re.search(r"install|tighten|torque", text):
        return "installation"
    return None


def spec_type_from_text(text: str, component: str | None) -> str | None:
    if re.search(r"torque|tighten|newton.meters|\bNm\b|N·m", text, re.I):
        return "torque"
    if component == "engine_oil" and re.search(r"capacity|amount|how much|replacing|liters|\bL\b", text, re.I):
        return "fluid_capacity"
    if component and component.startswith("suspension_height"):
        # The allowed variation is a different fact from the nominal height.
        return "tolerance" if re.search(r"toleran|allowable|allowed|plus or minus|out of spec|within spec", text, re.I) else "dimension"
    return None


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def extract_records(pages: list[dict], vehicle: Vehicle, *, document_ref: str,
                    source_file: str | None, document_hash: str,
                    parser_version: str) -> list[SpecRecord]:
    records: list[SpecRecord] = []
    for page in pages:
        text = page["markdown"]
        lines = text.splitlines()
        section = page.get("section")
        i = 0
        table = 0
        # Conservative: retain every page warning/footnote; review narrows applicability.
        warnings = []
        warning = []
        for warning_line in lines + [""]:
            if re.match(r"\s*(?:>\s*)?(?:\*{0,2})(?:warning|caution|note|important)\b|\s*\*\d", warning_line, re.I):
                if warning:
                    warnings.append("\n".join(warning))
                warning = [warning_line.strip()]
            elif warning and warning_line.strip() and not warning_line.strip().startswith(("|", "#")):
                warning.append(warning_line.strip())
            elif warning:
                warnings.append("\n".join(warning))
                warning = []
        while i < len(lines):
            line = lines[i]
            if re.match(r"^#{1,6}\s", line):
                section = re.sub(r"^#+\s*", "", line).strip()
            if not line.strip().startswith("|") or i + 1 >= len(lines) or not re.match(r"^[\s|:\-]+$", lines[i + 1]):
                # Preserve ordered prose steps as evidence, never reinterpret them as verified specs.
                step = re.match(r"\s*(\d+)[.)]\s+(.+)", line)
                if step:
                    records.append(SpecRecord(**vehicle.model_dump(), record_kind="procedure_step",
                        document_ref=document_ref, source_file=source_file, source_page=page.get("page"),
                        source_section=section, source_row=i + 1, source_excerpt=line,
                        source_document_hash=document_hash, parser_version=parser_version,
                        warnings=warnings, notes=[step.group(2)], search_text=f"{section or ''}\n{line}",
                        procedure_id=digest([document_hash, page.get("page"), section]), step_order=int(step.group(1))))
                elif line.strip() and not line.startswith("#"):
                    # Retain prose, figure references and unsupported table shapes
                    # as searchable evidence; never manufacture a numeric spec.
                    records.append(SpecRecord(**vehicle.model_dump(), record_kind="unclassified",
                        document_ref=document_ref, source_file=source_file, source_page=page.get("page"),
                        source_section=section, source_row=i + 1, source_excerpt=line,
                        source_document_hash=document_hash, parser_version=parser_version,
                        warnings=warnings, search_text=f"{section or ''}\n{line}"))
                i += 1
                continue
            table += 1
            header_line = line
            headers = cells(line)
            lower = [h.lower() for h in headers]
            i += 2
            # LlamaParse sometimes emits a second header row for variant labels.
            # Preserve that evidence; never propagate a blank merged numeric cell.
            if i < len(lines) and lines[i].strip().startswith("|"):
                subheaders = cells(lines[i])
                if (len(subheaders) == len(headers)
                        and any(re.fullmatch(r"6MT|CVT", v, re.I) for v in subheaders)
                        and all(not v or re.fullmatch(r"6MT|CVT", v, re.I) for v in subheaders)):
                    headers = [(h + " " + sub).strip() for h, sub in zip(headers, subheaders)]
                    lower = [h.lower() for h in headers]
                    header_line = "| " + " | ".join(headers) + " |"
                    i += 1
            row_no = 0
            while i < len(lines) and lines[i].strip().startswith("|"):
                row_no += 1
                row_line = lines[i]
                row = cells(row_line)
                i += 1
                if len(row) != len(headers):
                    continue
                context = " ".join([section or "", header_line, row_line])
                component = component_from_text(context)
                operation = operation_from_text(" ".join(row), component)
                spec_type = spec_type_from_text(context, component)
                unit_hint = row[lower.index("unit")] if "unit" in lower else None
                if unit_hint is None:
                    source_unit = re.search(r"\b(?:L|mm)\s*\([^)]*\)", " ".join(row))
                    unit_hint = source_unit.group(0) if source_unit else None
                variants = [(n, "6mt" if "6mt" in h else "cvt") for n, h in enumerate(lower)
                            if "6mt" in h or "cvt" in h]
                row_transmissions = set(re.findall(r"\b(?:6mt|cvt)\b", " ".join(row), re.I))
                row_transmissions = {v.lower() for v in row_transmissions}
                row_transmission = next(iter(row_transmissions)) if len(row_transmissions) == 1 else None
                # Front/Rear columns give each axle its own record, read from its own cell.
                axles = {n: h for n, h in enumerate(lower) if h in ("front", "rear")} \
                    if component and component.startswith("suspension_height") else {}
                wheel_size = next((m.group(1) + "-inch" for cell in row
                                   if (m := re.fullmatch(r"(\d{2})-inch model", cell.strip(), re.I))), None)
                columns = variants or [(n, vehicle.transmission) for n in axles] or [(n, vehicle.transmission) for n, h in enumerate(lower)
                                      if h in ("torque", "value", "capacity", "specification")
                                      or re.search(r"(?:initial|final|stage\s*\d+|pass\s*\d+)\s+torque", h)]
                if not columns:
                    columns = [(None, vehicle.transmission)]
                for column, transmission in columns:
                    if not variants and row_transmission:
                        transmission = row_transmission
                    # Explicit uploader restriction cannot relabel a source variant.
                    if vehicle.transmission and transmission and vehicle.transmission != transmission:
                        continue
                    raw = row[column] if column is not None else None
                    quantity = parse_quantity(raw or "", unit_hint)
                    stage = None
                    if column is not None and re.search(r"initial|final|stage|pass", lower[column]):
                        stage = [n for n, _ in columns].index(column) + 1
                    elif "step" in lower and row[lower.index("step")].isdigit():
                        stage = int(row[lower.index("step")])
                    else:
                        stage_match = re.search(r"(?:stage|pass|step)\s*(\d+)", " ".join(row), re.I)
                        if stage_match:
                            stage = int(stage_match.group(1))
                    fields = vehicle.model_dump()
                    fields["transmission"] = transmission
                    if wheel_size:
                        fields["wheel_size"] = wheel_size
                    record_component = f"suspension_height_{axles[column]}" if column in axles else component
                    source_mismatch = False
                    for variant in ("engine_code", "trim", "market"):
                        labels = [h.strip().replace(" ", "_") for h in lower]
                        if variant in labels:
                            explicit = row[labels.index(variant)].strip().lower()
                            if explicit and explicit not in ("—", "-", "n/a"):
                                if getattr(vehicle, variant) and getattr(vehicle, variant) != explicit:
                                    source_mismatch = True
                                fields[variant] = explicit
                    if source_mismatch:
                        continue
                    records.append(SpecRecord(**fields, **quantity,
                        record_kind="procedure_step" if stage else ("specification" if quantity else "unclassified"),
                        component=record_component, component_aliases=[record_component.replace("_", " ")] if record_component else [],
                        operation=operation, spec_type=spec_type, raw_value=raw,
                        conditions=[value for n, value in enumerate(row) if value and n not in {c for c, _ in columns}
                                    and lower[n] not in ("unit", "notes", "step")
                                    and not any(v in lower[n] for v in ("6mt", "cvt"))],
                        warnings=warnings, notes=[row[lower.index("notes")]] if "notes" in lower else [],
                        document_ref=document_ref, source_file=source_file, source_page=page.get("page"),
                        source_section=section, source_table=f"table-{table}",
                        source_row=row_no + int(page.get("table_row_offsets", {}).get(str(table), 0)),
                        source_excerpt=row_line, source_header=header_line,
                        source_unit=unit_hint, source_value_column=headers[column] if column is not None else None,
                        source_document_hash=document_hash, parser_version=parser_version,
                        search_text=f"{vehicle.year} {vehicle.make} {vehicle.model} {transmission or ''} {section or ''}\n{header_line}\n{row_line}",
                        procedure_id=digest([document_hash, page.get("page"), table, component, transmission]) if stage else None,
                        step_order=stage))
    groups: dict[str, list[SpecRecord]] = defaultdict(list)
    for record in records:
        if record.procedure_id:
            groups[record.procedure_id].append(record)
    for group in groups.values():
        orders = sorted(r.step_order for r in group)
        # Missing, duplicate or non-contiguous steps are unreviewable for numeric output.
        if orders == list(range(1, len(group) + 1)):
            for record in group:
                record.step_count = len(group)
    return records
