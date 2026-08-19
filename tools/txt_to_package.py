"""Convert a line-oriented TXT file into a RankingSelect university package.

The converter uses only the Python standard library. See the repository README
for the TXT format and the generated package contract.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

SCHEMA_VERSION = 1
VERIFICATION_STATUSES = {
    "discovered", "extracted", "needs_review", "verified", "stale", "rejected",
}
REQUIREMENT_STATUSES = {"required", "optional", "not_required", "unknown"}
DATE_TYPES = {"exact", "month", "range", "rolling", "tba", "unknown"}
FEE_TYPES = {"tuition", "registration"}
SOURCE_TYPES = {"official_web", "official_api", "official_pdf", "manual_entry", "archive"}
SECTION_KINDS = {
    "manifest", "source", "project", "cycle", "timeline", "requirements", "fee", "review",
}
ENTRY_TERMS = {"fall", "spring", "summer", "rolling"}
CYCLE_STATUSES = {"current", "historical"}
ENTITY_STATUSES = {"active", "inactive", "archived"}
REVIEW_ENTITY_TYPES = {"project", "cycle", "timeline", "requirements", "fee"}
ID_RE = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?$")
CYCLE_RE = re.compile(r"^(\d{2})(fall|spring|summer|rolling)$")


class PackageError(ValueError):
    """A user-facing TXT package validation error."""


@dataclass
class Section:
    kind: str
    ids: Tuple[str, ...]
    fields: Dict[str, str]
    line: int


def _split_list(value: str) -> List[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def _required(fields: Dict[str, str], key: str, section: Section) -> str:
    value = fields.get(key, "").strip()
    if not value:
        raise PackageError("line {}: [{}] requires '{}'".format(section.line, section.kind, key))
    return value


def _optional(fields: Dict[str, str], key: str, default: Optional[str] = None) -> Optional[str]:
    value = fields.get(key)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _valid_id(value: str, label: str) -> str:
    if not ID_RE.fullmatch(value):
        raise PackageError(
            "invalid {} '{}'; use lowercase letters, numbers, '_' or '-'.".format(label, value)
        )
    return value


def parse_txt(path: Path) -> List[Section]:
    """Parse the documented INI-like TXT format."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PackageError("{} must be UTF-8 text: {}".format(path, exc)) from exc
    sections: List[Section] = []
    current: Optional[Section] = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            try:
                tokens = shlex.split(line[1:-1])
            except ValueError as exc:
                raise PackageError("line {}: invalid section header: {}".format(line_number, exc)) from exc
            if not tokens:
                raise PackageError("line {}: empty section header".format(line_number))
            kind = tokens[0].lower()
            if kind not in SECTION_KINDS:
                raise PackageError("line {}: unknown section [{}]".format(line_number, kind))
            current = Section(kind, tuple(tokens[1:]), {}, line_number)
            sections.append(current)
            continue
        if current is None:
            raise PackageError("line {}: key/value appears before a section".format(line_number))
        if "=" not in line:
            raise PackageError("line {}: expected 'key = value'".format(line_number))
        key, value = (part.strip() for part in line.split("=", 1))
        if not key:
            raise PackageError("line {}: empty field name".format(line_number))
        if key in current.fields:
            raise PackageError("line {}: duplicate field '{}'".format(line_number, key))
        current.fields[key] = value
    return sections


def _only_sections(sections: Sequence[Section], kind: str) -> Iterable[Section]:
    return (section for section in sections if section.kind == kind)


def _parse_tests(value: Optional[str], section: Section) -> List[Dict[str, str]]:
    tests: List[Dict[str, str]] = []
    for item in _split_list(value or ""):
        if ":" not in item:
            raise PackageError("line {}: language_tests items must use TEST:MIN_SCORE".format(section.line))
        name, score = (part.strip() for part in item.split(":", 1))
        if not name or not score:
            raise PackageError("line {}: language test name and score are required".format(section.line))
        tests.append({"name": name, "min_score": score})
    return tests


def _parse_status(fields: Dict[str, str], key: str, section: Section) -> str:
    value = _optional(fields, key, "unknown") or "unknown"
    if value not in REQUIREMENT_STATUSES:
        raise PackageError(
            "line {}: {} must be one of {}".format(section.line, key, sorted(REQUIREMENT_STATUSES))
        )
    return value


def _parse_date_fields(fields: Dict[str, str], section: Section) -> Dict[str, Optional[str]]:
    date_type = _required(fields, "date_type", section).lower()
    if date_type not in DATE_TYPES:
        raise PackageError("line {}: date_type must be one of {}".format(section.line, sorted(DATE_TYPES)))
    start = _optional(fields, "date")
    end = _optional(fields, "date_end")
    if date_type == "exact" and (not start or not DATE_RE.fullmatch(start)):
        raise PackageError("line {}: exact dates must use YYYY-MM-DD".format(section.line))
    if date_type == "month" and (not start or not MONTH_RE.fullmatch(start)):
        raise PackageError("line {}: month dates must use YYYY-MM".format(section.line))
    if date_type == "range":
        if not start or not DATE_RE.fullmatch(start) or not end or not DATE_RE.fullmatch(end):
            raise PackageError("line {}: range timelines require date and date_end".format(section.line))
    if date_type in {"rolling", "tba", "unknown"} and (start or end):
        raise PackageError("line {}: {} timelines cannot contain dates".format(section.line, date_type))
    try:
        if date_type == "exact":
            date.fromisoformat(start or "")
        elif date_type == "month":
            date.fromisoformat("{}-01".format(start))
        elif date_type == "range":
            start_date = date.fromisoformat(start or "")
            end_date = date.fromisoformat(end or "")
            if end_date < start_date:
                raise PackageError("line {}: date_end cannot be before date".format(section.line))
    except ValueError as exc:
        raise PackageError("line {}: timeline contains an invalid calendar date".format(section.line)) from exc
    return {"date_type": date_type, "date": start, "date_end": end}


def _validate_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PackageError("{} must be an http(s) URL: '{}'".format(label, value))
    return value


def _validate_date(value: str, label: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise PackageError("{} must be a valid YYYY-MM-DD date: '{}'".format(label, value)) from exc
    return value


def _validate_datetime(value: str, label: str) -> str:
    if "T" not in value or not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value):
        raise PackageError("{} must include time and timezone: '{}'".format(label, value))
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PackageError("{} must be a valid ISO 8601 timestamp: '{}'".format(label, value)) from exc
    return value


def build_package(sections: Sequence[Section], input_name: str) -> Dict[str, object]:
    """Validate sections and return normalized package documents."""
    manifest_sections = list(_only_sections(sections, "manifest"))
    if len(manifest_sections) != 1 or manifest_sections[0].ids:
        raise PackageError("TXT must contain exactly one [manifest] section")
    manifest_section = manifest_sections[0]
    fields = manifest_section.fields
    try:
        schema_version = int(_required(fields, "schema_version", manifest_section))
    except ValueError as exc:
        raise PackageError("manifest schema_version must be an integer") from exc
    if schema_version != SCHEMA_VERSION:
        raise PackageError("unsupported schema_version {}; expected {}".format(schema_version, SCHEMA_VERSION))
    university_id = _valid_id(_required(fields, "university_id", manifest_section), "university_id")
    name = _required(fields, "name", manifest_section)
    country = _required(fields, "country", manifest_section)
    updated_at = _validate_date(_required(fields, "updated_at", manifest_section), "manifest.updated_at")
    package_version = _required(fields, "package_version", manifest_section)
    manifest: Dict[str, object] = {
        "schema_version": schema_version,
        "package_version": package_version,
        "university_id": university_id,
        "name": name,
        "country": country,
        "updated_at": updated_at,
        "converter": "tools.txt_to_package",
        "input_file": input_name,
    }
    for key in ("website", "region", "notes"):
        value = _optional(fields, key)
        if value is not None:
            if key == "website":
                _validate_url(value, "manifest.website")
            manifest[key] = value

    sources: List[Dict[str, object]] = []
    source_ids = set()
    for section in _only_sections(sections, "source"):
        if len(section.ids) != 1:
            raise PackageError("line {}: use [source SOURCE_ID]".format(section.line))
        source_id = _valid_id(section.ids[0], "source_id")
        if source_id in source_ids:
            raise PackageError("line {}: duplicate source_id '{}'".format(section.line, source_id))
        source_ids.add(source_id)
        status = _optional(section.fields, "verification_status", "needs_review")
        if status not in VERIFICATION_STATUSES:
            raise PackageError("line {}: invalid source verification_status".format(section.line))
        source_type = _required(section.fields, "source_type", section)
        if source_type not in SOURCE_TYPES:
            raise PackageError("line {}: source_type must be one of {}".format(section.line, sorted(SOURCE_TYPES)))
        source: Dict[str, object] = {
            "source_id": source_id,
            "url": _validate_url(_required(section.fields, "url", section), "source {}.url".format(source_id)),
            "source_type": source_type,
            "retrieved_at": _validate_datetime(
                _required(section.fields, "retrieved_at", section),
                "source {}.retrieved_at".format(source_id),
            ),
            "verification_status": status,
        }
        for key in ("title", "content_hash", "evidence_text"):
            value = _optional(section.fields, key)
            if value is not None:
                source[key] = value
        sources.append(source)
    if not sources:
        raise PackageError("TXT must contain at least one [source SOURCE_ID] section")

    project_sections = list(_only_sections(sections, "project"))
    if not project_sections:
        raise PackageError("TXT must contain at least one [project PROJECT_ID] section")
    projects: List[Dict[str, object]] = []
    project_map: Dict[str, Dict[str, object]] = {}
    for section in project_sections:
        if len(section.ids) != 1:
            raise PackageError("line {}: use [project PROJECT_ID]".format(section.line))
        project_id = _valid_id(section.ids[0], "project_id")
        if project_id in project_map:
            raise PackageError("line {}: duplicate project_id '{}'".format(section.line, project_id))
        project_university_id = _optional(section.fields, "university_id", university_id) or university_id
        if project_university_id != university_id:
            raise PackageError("line {}: project university_id must match manifest".format(section.line))
        official_url = _required(section.fields, "official_url", section)
        _validate_url(official_url, "project {}.official_url".format(project_id))
        campus_id = _valid_id(_optional(section.fields, "campus_id", "main") or "main", "campus_id")
        program_code = _valid_id(
            _required(section.fields, "normalized_program_code", section),
            "normalized_program_code",
        )
        expected_project_id = "{}_{}_{}".format(university_id, campus_id, program_code)
        if project_id != expected_project_id:
            raise PackageError(
                "line {}: project_id must be '{}'".format(section.line, expected_project_id)
            )
        project_status = _optional(section.fields, "status", "active")
        if project_status not in ENTITY_STATUSES:
            raise PackageError("line {}: project status must be one of {}".format(section.line, sorted(ENTITY_STATUSES)))
        project: Dict[str, object] = {
            "project_id": project_id,
            "university_id": university_id,
            "campus_id": campus_id,
            "normalized_program_code": program_code,
            "name": _required(section.fields, "name", section),
            "degree": _optional(section.fields, "degree"),
            "subject": _optional(section.fields, "subject"),
            "study_mode": _optional(section.fields, "study_mode"),
            "teaching_language": _split_list(_optional(section.fields, "teaching_language", "") or ""),
            "official_url": official_url,
            "admission_cycles": [],
            "status": project_status,
            "notes": _optional(section.fields, "notes", "") or "",
        }
        project_map[project_id] = project
        projects.append(project)

    cycle_map: Dict[Tuple[str, str], Dict[str, object]] = {}
    for section in _only_sections(sections, "cycle"):
        if len(section.ids) != 2:
            raise PackageError("line {}: use [cycle PROJECT_ID CYCLE_ID]".format(section.line))
        project_id, cycle_id = section.ids
        _valid_id(project_id, "project_id")
        _valid_id(cycle_id, "cycle_id")
        if project_id not in project_map:
            raise PackageError("line {}: cycle references unknown project '{}'".format(section.line, project_id))
        key = (project_id, cycle_id)
        if key in cycle_map:
            raise PackageError("line {}: duplicate cycle '{}/{}'".format(section.line, project_id, cycle_id))
        academic_year = _required(section.fields, "academic_year", section)
        if not academic_year.isdigit() or len(academic_year) != 4:
            raise PackageError("line {}: academic_year must be YYYY".format(section.line))
        cycle_match = CYCLE_RE.fullmatch(cycle_id)
        if not cycle_match or cycle_match.group(1) != academic_year[-2:]:
            raise PackageError(
                "line {}: cycle_id must match academic_year, for example 27fall for 2027".format(section.line)
            )
        entry_term = _optional(section.fields, "entry_term", "fall")
        cycle_status = _optional(section.fields, "status", "historical")
        if entry_term not in ENTRY_TERMS:
            raise PackageError("line {}: entry_term must be one of {}".format(section.line, sorted(ENTRY_TERMS)))
        if cycle_status not in CYCLE_STATUSES:
            raise PackageError("line {}: cycle status must be one of {}".format(section.line, sorted(CYCLE_STATUSES)))
        cycle: Dict[str, object] = {
            "cycle_id": cycle_id,
            "academic_year": int(academic_year),
            "entry_term": entry_term,
            "status": cycle_status,
            "timelines": [],
            "requirements": {},
            "fees": [],
        }
        cycle_map[key] = cycle
        project_map[project_id]["admission_cycles"].append(cycle)

    def require_cycle(section: Section) -> Tuple[str, str, Dict[str, object]]:
        if len(section.ids) < 2:
            raise PackageError("line {}: section requires PROJECT_ID and CYCLE_ID".format(section.line))
        project_id, cycle_id = section.ids[0], section.ids[1]
        key = (project_id, cycle_id)
        if key not in cycle_map:
            raise PackageError("line {}: unknown cycle '{}/{}'".format(section.line, project_id, cycle_id))
        return project_id, cycle_id, cycle_map[key]

    timeline_ids: Dict[Tuple[str, str], set] = {}
    for section in _only_sections(sections, "timeline"):
        require_cycle(section)
        if len(section.ids) != 3:
            raise PackageError("line {}: timeline header must include TIMELINE_ID".format(section.line))
        timeline_id = _valid_id(section.ids[2], "timeline_id")
        cycle_key = (section.ids[0], section.ids[1])
        if timeline_id in timeline_ids.setdefault(cycle_key, set()):
            raise PackageError("line {}: duplicate timeline_id '{}'".format(section.line, timeline_id))
        timeline_ids[cycle_key].add(timeline_id)
        source_id = _required(section.fields, "source_id", section)
        if source_id not in source_ids:
            raise PackageError("line {}: timeline references unknown source '{}'".format(section.line, source_id))
        timeline: Dict[str, object] = {
            "timeline_id": timeline_id,
            "event": _required(section.fields, "event", section),
            **_parse_date_fields(section.fields, section),
            "applicant_group": _required(section.fields, "applicant_group", section),
            "round": _optional(section.fields, "round"),
            "source_id": source_id,
            "verification_status": _optional(section.fields, "verification_status", "needs_review"),
        }
        if timeline["verification_status"] not in VERIFICATION_STATUSES:
            raise PackageError("line {}: invalid timeline verification_status".format(section.line))
        cycle_map[(section.ids[0], section.ids[1])]["timelines"].append(timeline)

    requirements_cycles = set()
    for section in _only_sections(sections, "requirements"):
        require_cycle(section)
        cycle_key = (section.ids[0], section.ids[1])
        if cycle_key in requirements_cycles:
            raise PackageError("line {}: duplicate requirements section for '{}/{}'".format(
                section.line, section.ids[0], section.ids[1]
            ))
        requirements_cycles.add(cycle_key)
        source_id = _optional(section.fields, "source_id")
        if source_id and source_id not in source_ids:
            raise PackageError("line {}: requirements references unknown source '{}'".format(section.line, source_id))
        status = _optional(section.fields, "verification_status", "needs_review")
        if status not in VERIFICATION_STATUSES:
            raise PackageError("line {}: invalid requirements verification_status".format(section.line))
        requirements: Dict[str, object] = {
            "language": {
                "status": _parse_status(section.fields, "language_status", section),
                "tests": _parse_tests(_optional(section.fields, "language_tests"), section),
            },
            "gre": {
                "status": _parse_status(section.fields, "gre_status", section),
                "min_score": _optional(section.fields, "gre_min_score"),
            },
            "gmat": {
                "status": _parse_status(section.fields, "gmat_status", section),
                "min_score": _optional(section.fields, "gmat_min_score"),
            },
            "academic": {
                "status": _parse_status(section.fields, "academic_status", section),
                "description": _optional(section.fields, "academic_description"),
            },
            "notes": _optional(section.fields, "notes", "") or "",
            "verification_status": status,
        }
        if source_id:
            requirements["source_id"] = source_id
        cycle_map[(section.ids[0], section.ids[1])]["requirements"] = requirements

    fee_ids: Dict[Tuple[str, str], set] = {}
    for section in _only_sections(sections, "fee"):
        require_cycle(section)
        if len(section.ids) != 3:
            raise PackageError("line {}: fee header must include FEE_ID".format(section.line))
        fee_id = _valid_id(section.ids[2], "fee_id")
        cycle_key = (section.ids[0], section.ids[1])
        if fee_id in fee_ids.setdefault(cycle_key, set()):
            raise PackageError("line {}: duplicate fee_id '{}'".format(section.line, fee_id))
        fee_ids[cycle_key].add(fee_id)
        fee_type = _required(section.fields, "type", section)
        if fee_type not in FEE_TYPES:
            raise PackageError("line {}: fee type must be one of {}".format(section.line, sorted(FEE_TYPES)))
        amount = _required(section.fields, "amount", section)
        if amount != "unknown" and not NUMBER_RE.fullmatch(amount):
            raise PackageError("line {}: fee amount must be 'unknown' or a numeric string".format(section.line))
        source_id = _required(section.fields, "source_id", section)
        if source_id not in source_ids:
            raise PackageError("line {}: fee references unknown source '{}'".format(section.line, source_id))
        status = _optional(section.fields, "verification_status", "needs_review")
        if status not in VERIFICATION_STATUSES:
            raise PackageError("line {}: invalid fee verification_status".format(section.line))
        fee = {
            "fee_id": fee_id,
            "type": fee_type,
            "amount": amount,
            "currency": _required(section.fields, "currency", section),
            "period": _required(section.fields, "period", section),
            "applicant_group": _required(section.fields, "applicant_group", section),
            "condition": _optional(section.fields, "condition", "") or "",
            "source_id": source_id,
            "verification_status": status,
        }
        cycle_map[(section.ids[0], section.ids[1])]["fees"].append(fee)

    reviews: List[Dict[str, object]] = []
    review_ids = set()
    known_review_entities = {
        "project": set(project_map),
        "cycle": {"{}/{}".format(project_id, cycle_id) for project_id, cycle_id in cycle_map},
        "timeline": {
            "{}/{}/{}".format(project_id, cycle_id, timeline_id)
            for (project_id, cycle_id), ids in timeline_ids.items()
            for timeline_id in ids
        },
        "requirements": {
            "{}/{}".format(project_id, cycle_id) for project_id, cycle_id in requirements_cycles
        },
        "fee": {
            "{}/{}/{}".format(project_id, cycle_id, fee_id)
            for (project_id, cycle_id), ids in fee_ids.items()
            for fee_id in ids
        },
    }
    for section in _only_sections(sections, "review"):
        if len(section.ids) != 1:
            raise PackageError("line {}: use [review REVIEW_ID]".format(section.line))
        review_id = _valid_id(section.ids[0], "review_id")
        if review_id in review_ids:
            raise PackageError("line {}: duplicate review_id '{}'".format(section.line, review_id))
        review_ids.add(review_id)
        selected_source_id = _required(section.fields, "selected_source_id", section)
        rejected_source_ids = _split_list(_optional(section.fields, "rejected_source_ids", "") or "")
        referenced_sources = [selected_source_id] + rejected_source_ids
        missing_sources = [source_id for source_id in referenced_sources if source_id not in source_ids]
        if missing_sources:
            raise PackageError(
                "line {}: review references unknown source(s): {}".format(section.line, ", ".join(missing_sources))
            )
        if selected_source_id in rejected_source_ids:
            raise PackageError("line {}: selected source cannot also be rejected".format(section.line))
        entity_type = _required(section.fields, "entity_type", section)
        if entity_type not in REVIEW_ENTITY_TYPES:
            raise PackageError(
                "line {}: review entity_type must be one of {}".format(
                    section.line, sorted(REVIEW_ENTITY_TYPES)
                )
            )
        entity_id = _required(section.fields, "entity_id", section)
        if entity_id not in known_review_entities[entity_type]:
            raise PackageError(
                "line {}: review references unknown {} '{}'".format(
                    section.line, entity_type, entity_id
                )
            )
        reviews.append({
            "review_id": review_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_name": _required(section.fields, "field_name", section),
            "selected_source_id": selected_source_id,
            "rejected_source_ids": rejected_source_ids,
            "decision": _required(section.fields, "decision", section),
            "reviewed_by": _required(section.fields, "reviewed_by", section),
            "reviewed_at": _validate_datetime(
                _required(section.fields, "reviewed_at", section),
                "review {}.reviewed_at".format(review_id),
            ),
        })

    for project in projects:
        current_cycles = [cycle for cycle in project["admission_cycles"] if cycle["status"] == "current"]
        if len(current_cycles) > 1:
            raise PackageError("project '{}' has more than one current cycle".format(project["project_id"]))
        project["admission_cycles"].sort(key=lambda item: str(item["cycle_id"]))
    sources.sort(key=lambda item: str(item["source_id"]))
    projects.sort(key=lambda item: str(item["project_id"]))
    reviews.sort(key=lambda item: str(item["review_id"]))
    return {
        "manifest": manifest,
        "projects": projects,
        "sources": sources,
        "reviews": reviews,
        "sections": sections,
    }


def _notes_markdown(package: Dict[str, object]) -> str:
    manifest = package["manifest"]
    lines = [
        "# Package notes",
        "",
        "This file was generated by python -m tools.txt_to_package.",
        "",
        "- University: {} ({})".format(manifest["name"], manifest["university_id"]),
        "- Package version: {}".format(manifest["package_version"]),
    ]
    if manifest.get("notes"):
        lines.extend(["", "## Manifest", "", str(manifest["notes"])])
    for project in package["projects"]:
        if project.get("notes"):
            lines.extend(["", "## {} ({})".format(project["name"], project["project_id"]), "", str(project["notes"])])
        for cycle in project["admission_cycles"]:
            notes = cycle.get("requirements", {}).get("notes", "")
            if notes:
                lines.extend(["", "### Cycle {}".format(cycle["cycle_id"]), "", str(notes)])
    lines.append("")
    return "\n".join(lines)


def write_package(package: Dict[str, object], input_path: Path, output_dir: Path, force: bool = False) -> None:
    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise PackageError(
            "output directory is not empty: {}; use --force to overwrite generated files".format(output_dir)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw").mkdir(exist_ok=True)
    for name, value in (
        ("manifest.json", package["manifest"]),
        ("projects.json", package["projects"]),
        ("sources.json", package["sources"]),
        ("reviews.json", package["reviews"]),
    ):
        (output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    shutil.copyfile(input_path, output_dir / "raw" / input_path.name)
    (output_dir / "notes.md").write_text(_notes_markdown(package), encoding="utf-8")


TEMPLATE = """# RankingSelect university package TXT
# UTF-8, one key = value per line. Use semicolons for lists.

[manifest]
schema_version = 1
package_version = 2026.08.19.1
university_id = u_example_university
name = Example University
country = Netherlands
website = https://www.example.edu
region = Western Europe
updated_at = 2026-08-19
notes = Replace this template with evidence from official university pages.

[source src_admissions]
url = https://www.example.edu/admissions
source_type = official_web
title = Admissions page
retrieved_at = 2026-08-19T00:00:00Z
verification_status = needs_review
evidence_text = Official admissions source.

[project u_example_university_main_cs_msc]
campus_id = main
normalized_program_code = cs_msc
name = MSc Computer Science
degree = MSc
subject = Computer Science
study_mode = full_time
teaching_language = English
official_url = https://www.example.edu/programmes/msc-computer-science
status = active
notes =

[cycle u_example_university_main_cs_msc 27fall]
academic_year = 2027
entry_term = fall
status = current

[timeline u_example_university_main_cs_msc 27fall deadline_1]
event = deadline
date_type = exact
date = 2026-12-15
applicant_group = non_eu
round = round_1
source_id = src_admissions
verification_status = needs_review

[requirements u_example_university_main_cs_msc 27fall]
language_status = required
language_tests = IELTS:7.0; TOEFL iBT:100
gre_status = unknown
gmat_status = not_required
academic_status = required
academic_description = Relevant bachelor's degree.
source_id = src_admissions
verification_status = needs_review
notes =

[fee u_example_university_main_cs_msc 27fall tuition_1]
type = tuition
amount = unknown
currency = EUR
period = per_year
applicant_group = non_eu
condition =
source_id = src_admissions
verification_status = needs_review
"""


def write_template(path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise PackageError("template already exists: {}; use --force to overwrite".format(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Convert TXT into a RankingSelect university package")
    parser.add_argument("input", nargs="?", type=Path, help="UTF-8 TXT input")
    parser.add_argument("--output", type=Path, help="output package directory")
    parser.add_argument("--force", action="store_true", help="overwrite generated files")
    parser.add_argument("--template", type=Path, help="write a starter TXT template and exit")
    args = parser.parse_args(argv)
    try:
        if args.template:
            write_template(args.template, args.force)
            print("wrote TXT template: {}".format(args.template))
            return 0
        if not args.input or not args.output:
            parser.error("input and --output are required unless --template is used")
        if not args.input.is_file():
            raise PackageError("input file not found: {}".format(args.input))
        package = build_package(parse_txt(args.input), args.input.name)
        write_package(package, args.input, args.output, args.force)
        print("wrote package: {}".format(args.output))
        print("projects: {}; sources: {}".format(len(package["projects"]), len(package["sources"])))
        return 0
    except PackageError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
