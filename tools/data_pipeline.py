"""Build RankingSelect's canonical SQLite database and static JSON exports.

The pipeline has one direction only::

    raw university/ranking inputs -> normalized/rankingselect.sqlite
        -> generated JSON -> frontend/public/data JSON

It intentionally does not read ``frontend/public/data/programs.json``.  That
file used to be both an input and an output, which made stale legacy records
impossible to distinguish from data built from the versioned raw packages.

The implementation uses only the Python standard library so it can run in CI
without installing the scraper's optional dependencies.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
RANKING_SOURCES = ("qs", "the", "arwu", "usnews", "csrankings")
ID_RE = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")


COUNTRY_ALIASES = {
    "us": "United States",
    "usa": "United States",
    "uk": "United Kingdom",
    "britain": "United Kingdom",
    "uae": "United Arab Emirates",
    "russian federation": "Russia",
    "south korea": "Korea, South",
    "republic of korea": "Korea, South",
    "hong kong sar": "Hong Kong",
    "macao": "Macau",
    "china-taiwan": "Taiwan",
    "brunei": "Brunei Darussalam",
    "czech republic": "Czechia",
    "northern cyprus": "Cyprus",
    "turkiye": "Turkey",
}

COUNTRY_TO_REGION: Dict[str, str] = {}


def _fill_region(countries: Sequence[str], region: str) -> None:
    for country in countries:
        COUNTRY_TO_REGION[country] = region


_fill_region(
    ["France", "Germany", "Netherlands", "Belgium", "Austria", "Switzerland", "Luxembourg"],
    "Western Europe",
)
_fill_region(
    ["Sweden", "Norway", "Denmark", "Finland", "Iceland", "Ireland", "Estonia", "Latvia", "Lithuania"],
    "Northern Europe",
)
_fill_region(
    ["Italy", "Spain", "Portugal", "Greece", "Cyprus", "Malta", "Slovenia", "Croatia", "Serbia"],
    "Southern Europe",
)
_fill_region(
    ["Poland", "Czechia", "Hungary", "Romania", "Bulgaria", "Slovakia", "Ukraine", "Russia"],
    "Eastern Europe",
)
_fill_region(["United States", "Canada"], "North America")
_fill_region(["Mexico", "Brazil", "Argentina", "Chile", "Colombia", "Peru", "Costa Rica"], "Latin America")
_fill_region(["United Kingdom"], "United Kingdom")
_fill_region(["Australia", "New Zealand"], "Oceania")
_fill_region(["China", "Hong Kong", "Macau", "Taiwan"], "China")
_fill_region(
    [
        "Turkey", "Israel", "Saudi Arabia", "United Arab Emirates", "Qatar", "Jordan",
        "Lebanon", "Oman", "Bahrain", "Egypt", "Iran", "Iraq", "Kuwait", "Morocco",
    ],
    "Middle East",
)
_fill_region(
    [
        "Japan", "Korea, South", "Singapore", "India", "Malaysia", "Thailand", "Indonesia",
        "Pakistan", "Vietnam", "Philippines", "Kazakhstan", "Uzbekistan", "Brunei Darussalam",
        "Bangladesh", "Sri Lanka",
    ],
    "Asia",
)
_fill_region(["South Africa", "Ghana", "Nigeria", "Kenya"], "Africa")


SCHEMA_SQL = """
CREATE TABLE schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE universities (
    university_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    package_status TEXT NOT NULL DEFAULT 'ranking_only',
    source_path TEXT NOT NULL DEFAULT ''
);

CREATE TABLE university_aliases (
    alias_id TEXT PRIMARY KEY,
    canonical_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (alias_id) REFERENCES universities(university_id),
    FOREIGN KEY (canonical_id) REFERENCES universities(university_id)
);

CREATE TABLE data_packages (
    university_id TEXT PRIMARY KEY,
    package_path TEXT NOT NULL,
    package_version TEXT NOT NULL DEFAULT '',
    manifest_status TEXT NOT NULL,
    projects_status TEXT NOT NULL,
    sources_status TEXT NOT NULL,
    project_count INTEGER NOT NULL DEFAULT 0,
    source_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (university_id) REFERENCES universities(university_id)
);

CREATE TABLE campuses (
    university_id TEXT NOT NULL,
    campus_id TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (university_id, campus_id),
    FOREIGN KEY (university_id) REFERENCES universities(university_id)
);

CREATE TABLE sources (
    university_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '',
    retrieved_at TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    evidence_text TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (university_id, source_id),
    FOREIGN KEY (university_id) REFERENCES universities(university_id)
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    university_id TEXT NOT NULL,
    campus_id TEXT NOT NULL,
    normalized_program_code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    degree TEXT,
    subject TEXT,
    department TEXT,
    study_mode TEXT,
    teaching_language_json TEXT NOT NULL DEFAULT '[]',
    official_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    verification_status TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (university_id, campus_id) REFERENCES campuses(university_id, campus_id)
);

CREATE TABLE admission_cycles (
    project_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    academic_year INTEGER,
    entry_term TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT '',
    source_id TEXT,
    PRIMARY KEY (project_id, cycle_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);

CREATE TABLE timelines (
    project_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    timeline_id TEXT NOT NULL,
    event TEXT NOT NULL DEFAULT '',
    date_type TEXT NOT NULL DEFAULT 'unknown',
    date TEXT,
    date_end TEXT,
    applicant_group TEXT NOT NULL DEFAULT 'all',
    round TEXT,
    source_id TEXT,
    verification_status TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (project_id, cycle_id, timeline_id),
    FOREIGN KEY (project_id, cycle_id) REFERENCES admission_cycles(project_id, cycle_id)
);

CREATE TABLE requirements (
    project_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    language_status TEXT NOT NULL DEFAULT 'unknown',
    language_tests_json TEXT NOT NULL DEFAULT '[]',
    gre_status TEXT NOT NULL DEFAULT 'unknown',
    gre_min_score TEXT,
    gmat_status TEXT NOT NULL DEFAULT 'unknown',
    gmat_min_score TEXT,
    academic_status TEXT NOT NULL DEFAULT 'unknown',
    academic_description TEXT,
    notes TEXT NOT NULL DEFAULT '',
    source_id TEXT,
    verification_status TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (project_id, cycle_id),
    FOREIGN KEY (project_id, cycle_id) REFERENCES admission_cycles(project_id, cycle_id)
);

CREATE TABLE fees (
    project_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    fee_id TEXT NOT NULL,
    fee_type TEXT NOT NULL DEFAULT '',
    amount TEXT,
    currency TEXT,
    period TEXT,
    applicant_group TEXT NOT NULL DEFAULT 'all',
    condition TEXT NOT NULL DEFAULT '',
    source_id TEXT,
    verification_status TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (project_id, cycle_id, fee_id),
    FOREIGN KEY (project_id, cycle_id) REFERENCES admission_cycles(project_id, cycle_id)
);

CREATE TABLE reviews (
    university_id TEXT NOT NULL,
    review_id TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    field_name TEXT NOT NULL DEFAULT '',
    selected_source_id TEXT,
    rejected_source_ids_json TEXT NOT NULL DEFAULT '[]',
    decision TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (university_id, review_id),
    FOREIGN KEY (university_id) REFERENCES universities(university_id)
);

CREATE TABLE ranking_entries (
    source TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    edition INTEGER,
    rank INTEGER NOT NULL,
    university_id TEXT NOT NULL,
    name TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    score REAL,
    source_path TEXT NOT NULL,
    PRIMARY KEY (source, row_index),
    FOREIGN KEY (university_id) REFERENCES universities(university_id)
);

CREATE TABLE validation_issues (
    issue_id INTEGER PRIMARY KEY,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    package_id TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL
);

CREATE INDEX idx_projects_university ON projects(university_id);
CREATE INDEX idx_cycles_status ON admission_cycles(status);
CREATE INDEX idx_timelines_date_type ON timelines(date_type);
CREATE INDEX idx_rankings_university ON ranking_entries(university_id);
CREATE INDEX idx_issues_code ON validation_issues(code);
"""


class PipelineError(RuntimeError):
    """Raised when an output cannot be built safely."""


class IssueCollector:
    def __init__(self) -> None:
        self.items: List[Dict[str, str]] = []

    def add(
        self,
        severity: str,
        code: str,
        message: str,
        package_id: str = "",
        entity_type: str = "",
        entity_id: str = "",
        source_path: str = "",
    ) -> None:
        self.items.append(
            {
                "severity": severity,
                "code": code,
                "packageId": package_id,
                "entityType": entity_type,
                "entityId": entity_id,
                "sourcePath": source_path,
                "message": message,
            }
        )

    def counts(self) -> Dict[str, int]:
        return dict(sorted(Counter(item["severity"] for item in self.items).items()))


def normalize_country(value: Any) -> str:
    text = str(value or "").strip()
    return COUNTRY_ALIASES.get(text.lower(), text) if text else ""


def region_for(country: str) -> str:
    return COUNTRY_TO_REGION.get(country, "Other")


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"\s*\(.*?\)\s*", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json(path: Path, issues: IssueCollector, package_id: str, label: str, default: Any) -> Any:
    if not path.is_file():
        issues.add(
            "warning",
            "%s_missing" % label,
            "%s is missing" % path.name,
            package_id=package_id,
            source_path=str(path),
        )
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        issues.add(
            "error",
            "%s_unreadable" % label,
            "%s cannot be parsed: %s" % (path.name, exc),
            package_id=package_id,
            source_path=str(path),
        )
        return default


def _valid_id(value: Any) -> bool:
    return bool(value and ID_RE.match(str(value)))


def _parse_timestamp(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.combine(date.fromisoformat(text[:10]), datetime.min.time())
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stable_timestamp(values: Iterable[Any]) -> str:
    parsed = [stamp for stamp in (_parse_timestamp(value) for value in values) if stamp is not None]
    if not parsed:
        return "1970-01-01T00:00:00+00:00"
    return max(parsed).isoformat(timespec="seconds")


def _source_files(root: Path) -> List[Path]:
    files: List[Path] = []
    raw_universities = root / "raw" / "universities"
    if raw_universities.is_dir():
        for package in sorted(path for path in raw_universities.iterdir() if path.is_dir()):
            for name in ("manifest.json", "projects.json", "sources.json", "reviews.json"):
                path = package / name
                if path.is_file():
                    files.append(path)
    alias_path = _alias_input_path(root)
    if alias_path.is_file():
        files.append(alias_path)
    for source in RANKING_SOURCES:
        path = _ranking_input_path(root, source)
        if path.is_file():
            files.append(path)
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def _corpus_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _source_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _ranking_input_path(root: Path, source: str) -> Path:
    canonical = root / "raw" / "rankings" / source / "normalized.json"
    if canonical.is_file():
        return canonical
    return root / "frontend" / "public" / "data" / "rankings" / (source + ".json")


def _alias_input_path(root: Path) -> Path:
    canonical = root / "raw" / "university_aliases.json"
    if canonical.is_file():
        return canonical
    return root / "frontend" / "public" / "data" / "university_aliases.json"


def _upsert_university(
    conn: sqlite3.Connection,
    university_id: str,
    name: str,
    country: str = "",
    region: str = "",
    website: str = "",
    updated_at: str = "",
    package_status: str = "ranking_only",
    source_path: str = "",
) -> None:
    country = normalize_country(country)
    region = region or region_for(country)
    existing = conn.execute(
        "SELECT * FROM universities WHERE university_id = ?", (university_id,)
    ).fetchone()
    if existing is None:
        conn.execute(
            """INSERT INTO universities
               (university_id, name, country, region, website, updated_at, package_status, source_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                university_id,
                name or university_id,
                country,
                region,
                website or "",
                updated_at or "",
                package_status,
                source_path,
            ),
        )
        return
    conn.execute(
        """UPDATE universities SET
               name = CASE WHEN ? <> '' THEN ? ELSE name END,
               country = CASE WHEN ? <> '' THEN ? ELSE country END,
               region = CASE WHEN ? <> '' AND ? <> 'Other' THEN ? ELSE region END,
               website = CASE WHEN ? <> '' THEN ? ELSE website END,
               updated_at = CASE WHEN ? <> '' THEN ? ELSE updated_at END,
               package_status = CASE WHEN ? = 'package' THEN 'package' ELSE package_status END,
               source_path = CASE WHEN ? <> '' THEN ? ELSE source_path END
           WHERE university_id = ?""",
        (
            name or "", name or "", country, country, region, region, region,
            website or "", website or "", updated_at or "", updated_at or "",
            package_status, source_path, source_path, university_id,
        ),
    )


def _generated_id(prefix: str, *parts: Any) -> str:
    body = "|".join(str(part or "") for part in parts).encode("utf-8")
    return "%s_%s" % (prefix, hashlib.sha256(body).hexdigest()[:12])


def _insert_package(
    conn: sqlite3.Connection,
    package_dir: Path,
    issues: IssueCollector,
    timestamps: List[Any],
    seen_project_ids: MutableMapping[str, str],
) -> None:
    directory_id = package_dir.name
    manifest_path = package_dir / "manifest.json"
    manifest = _read_json(manifest_path, issues, directory_id, "manifest", {})
    if not isinstance(manifest, dict):
        issues.add("error", "manifest_not_object", "manifest.json must be an object", directory_id)
        manifest = {}

    manifest_id = str(manifest.get("university_id") or directory_id)
    university_id = directory_id
    if manifest_id != directory_id:
        issues.add(
            "error",
            "manifest_directory_mismatch",
            "manifest university_id %r differs from package directory %r" % (manifest_id, directory_id),
            directory_id,
            "university",
            manifest_id,
            str(manifest_path),
        )
    if not _valid_id(university_id):
        issues.add(
            "warning",
            "noncanonical_university_id",
            "university id does not match the ASCII contract",
            directory_id,
            "university",
            university_id,
            str(manifest_path),
        )
    updated_at = str(manifest.get("updated_at") or "")
    if updated_at:
        timestamps.append(updated_at)
    _upsert_university(
        conn,
        university_id,
        str(manifest.get("name") or university_id),
        str(manifest.get("country") or ""),
        str(manifest.get("region") or ""),
        str(manifest.get("website") or ""),
        updated_at,
        "package",
        str(package_dir.relative_to(package_dir.parents[2])).replace("\\", "/"),
    )

    sources_path = package_dir / "sources.json"
    sources = _read_json(sources_path, issues, university_id, "sources", [])
    sources_status = "ok" if sources_path.is_file() and isinstance(sources, list) else "invalid"
    if not isinstance(sources, list):
        issues.add("error", "sources_not_array", "sources.json must be an array", university_id)
        sources = []
    source_ids: set = set()
    source_count = 0
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            issues.add("error", "source_not_object", "source entry %d is not an object" % index, university_id)
            continue
        source_id = str(source.get("source_id") or _generated_id("src", university_id, index, source.get("url")))
        if source_id in source_ids:
            issues.add(
                "error", "duplicate_source_id", "duplicate source_id in package",
                university_id, "source", source_id, str(sources_path),
            )
            continue
        source_ids.add(source_id)
        retrieved_at = str(source.get("retrieved_at") or "")
        if retrieved_at:
            timestamps.append(retrieved_at)
        conn.execute(
            """INSERT INTO sources
               (university_id, source_id, url, source_type, retrieved_at, verification_status,
                title, content_hash, evidence_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                university_id,
                source_id,
                str(source.get("url") or ""),
                str(source.get("source_type") or ""),
                retrieved_at,
                str(source.get("verification_status") or ""),
                str(source.get("title") or ""),
                str(source.get("content_hash") or ""),
                str(source.get("evidence_text") or ""),
            ),
        )
        source_count += 1

    projects_path = package_dir / "projects.json"
    projects = _read_json(projects_path, issues, university_id, "projects", [])
    projects_status = "ok" if projects_path.is_file() and isinstance(projects, list) else "missing_or_invalid"
    if not isinstance(projects, list):
        issues.add("error", "projects_not_array", "projects.json must be an array", university_id)
        projects = []
    if projects_path.is_file() and not projects:
        projects_status = "empty"
        issues.add(
            "warning",
            "projects_empty",
            "projects.json contains no project records",
            package_id=university_id,
            source_path=str(projects_path),
        )

    imported_projects = 0
    for project_index, project in enumerate(projects):
        if not isinstance(project, dict):
            issues.add("error", "project_not_object", "project entry is not an object", university_id)
            continue
        project_id = str(project.get("project_id") or "")
        project_name = str(project.get("name") or "").strip()
        if not project_id or not project_name:
            issues.add(
                "error", "project_missing_identity", "project requires project_id and name",
                university_id, "project", project_id, str(projects_path),
            )
            continue
        if project_id in seen_project_ids:
            issues.add(
                "error",
                "duplicate_project_id",
                "project id already appeared in package %s; duplicate quarantined" % seen_project_ids[project_id],
                university_id,
                "project",
                project_id,
                str(projects_path),
            )
            continue
        seen_project_ids[project_id] = university_id
        project_university_id = str(project.get("university_id") or university_id)
        if project_university_id != university_id:
            issues.add(
                "error", "project_university_mismatch",
                "project university_id %r differs from package %r" % (project_university_id, university_id),
                university_id, "project", project_id, str(projects_path),
            )
            project_university_id = university_id
        campus_id = str(project.get("campus_id") or "main")
        conn.execute(
            "INSERT OR IGNORE INTO campuses (university_id, campus_id, name) VALUES (?, ?, ?)",
            (university_id, campus_id, campus_id.replace("_", " ").title()),
        )
        conn.execute(
            """INSERT INTO projects
               (project_id, university_id, campus_id, normalized_program_code, name, degree,
                subject, department, study_mode, teaching_language_json, official_url, status,
                verification_status, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                project_university_id,
                campus_id,
                str(project.get("normalized_program_code") or ""),
                project_name,
                project.get("degree"),
                project.get("subject"),
                project.get("department"),
                project.get("study_mode"),
                _json_text(project.get("teaching_language") or []),
                str(project.get("official_url") or ""),
                str(project.get("status") or "active"),
                str(project.get("verification_status") or ""),
                str(project.get("notes") or ""),
            ),
        )
        imported_projects += 1

        cycles = project.get("admission_cycles") or []
        if not isinstance(cycles, list):
            issues.add(
                "error", "cycles_not_array", "admission_cycles must be an array",
                university_id, "project", project_id, str(projects_path),
            )
            cycles = []
        seen_cycles: set = set()
        for cycle_index, cycle in enumerate(cycles):
            if not isinstance(cycle, dict):
                issues.add("error", "cycle_not_object", "cycle is not an object", university_id, "project", project_id)
                continue
            cycle_id = str(cycle.get("cycle_id") or _generated_id("cycle", project_id, cycle_index))
            if cycle_id in seen_cycles:
                issues.add(
                    "error", "duplicate_cycle_id", "duplicate cycle_id within project",
                    university_id, "cycle", "%s:%s" % (project_id, cycle_id), str(projects_path),
                )
                continue
            seen_cycles.add(cycle_id)
            academic_year = cycle.get("academic_year")
            if not isinstance(academic_year, int):
                academic_year = None
            conn.execute(
                """INSERT INTO admission_cycles
                   (project_id, cycle_id, academic_year, entry_term, status, verification_status, source_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    cycle_id,
                    academic_year,
                    str(cycle.get("entry_term") or ""),
                    str(cycle.get("status") or ""),
                    str(cycle.get("verification_status") or ""),
                    cycle.get("source_id"),
                ),
            )

            timelines = cycle.get("timelines") or []
            if not isinstance(timelines, list):
                issues.add("error", "timelines_not_array", "timelines must be an array", university_id, "cycle", cycle_id)
                timelines = []
            seen_timelines: set = set()
            for timeline_index, timeline in enumerate(timelines):
                if not isinstance(timeline, dict):
                    issues.add("error", "timeline_not_object", "timeline is not an object", university_id, "cycle", cycle_id)
                    continue
                timeline_id = str(
                    timeline.get("timeline_id")
                    or _generated_id("timeline", project_id, cycle_id, timeline_index, timeline.get("event"))
                )
                if timeline_id in seen_timelines:
                    timeline_id = _generated_id("timeline", project_id, cycle_id, timeline_index, timeline_id)
                seen_timelines.add(timeline_id)
                date_type = str(timeline.get("date_type") or "unknown")
                start_date = timeline.get("date")
                end_date = timeline.get("date_end")
                if start_date and not DATE_RE.match(str(start_date)):
                    issues.add(
                        "error", "invalid_timeline_date", "timeline date is not ISO YYYY-MM[-DD]",
                        university_id, "timeline", timeline_id, str(projects_path),
                    )
                if end_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(end_date)):
                    issues.add(
                        "error", "invalid_timeline_date_end", "timeline date_end is not ISO YYYY-MM-DD",
                        university_id, "timeline", timeline_id, str(projects_path),
                    )
                source_id = timeline.get("source_id")
                if source_id and source_id not in source_ids:
                    issues.add(
                        "error", "missing_source_reference", "timeline references an unknown source_id",
                        university_id, "timeline", timeline_id, str(projects_path),
                    )
                conn.execute(
                    """INSERT INTO timelines
                       (project_id, cycle_id, timeline_id, event, date_type, date, date_end,
                        applicant_group, round, source_id, verification_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_id,
                        cycle_id,
                        timeline_id,
                        str(timeline.get("event") or ""),
                        date_type,
                        start_date,
                        end_date,
                        str(timeline.get("applicant_group") or "all"),
                        timeline.get("round"),
                        source_id,
                        str(timeline.get("verification_status") or ""),
                    ),
                )

            requirements = cycle.get("requirements") or {}
            if not isinstance(requirements, dict):
                issues.add("error", "requirements_not_object", "requirements must be an object", university_id, "cycle", cycle_id)
                requirements = {}
            language = requirements.get("language") or {}
            gre = requirements.get("gre") or {}
            gmat = requirements.get("gmat") or {}
            academic = requirements.get("academic") or {}
            for block_name, block in (("language", language), ("gre", gre), ("gmat", gmat), ("academic", academic)):
                if not isinstance(block, dict):
                    issues.add(
                        "error", "requirement_block_not_object", "%s requirement must be an object" % block_name,
                        university_id, "cycle", cycle_id, str(projects_path),
                    )
            language = language if isinstance(language, dict) else {}
            gre = gre if isinstance(gre, dict) else {}
            gmat = gmat if isinstance(gmat, dict) else {}
            academic = academic if isinstance(academic, dict) else {}
            req_source = requirements.get("source_id")
            conn.execute(
                """INSERT INTO requirements
                   (project_id, cycle_id, language_status, language_tests_json, gre_status,
                    gre_min_score, gmat_status, gmat_min_score, academic_status,
                    academic_description, notes, source_id, verification_status, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    cycle_id,
                    str(language.get("status") or "unknown"),
                    _json_text(language.get("tests") or []),
                    str(gre.get("status") or "unknown"),
                    gre.get("min_score"),
                    str(gmat.get("status") or "unknown"),
                    gmat.get("min_score"),
                    str(academic.get("status") or "unknown"),
                    academic.get("description"),
                    str(requirements.get("notes") or ""),
                    req_source,
                    str(requirements.get("verification_status") or ""),
                    _json_text(requirements),
                ),
            )

            fees = cycle.get("fees") or []
            if not isinstance(fees, list):
                issues.add("error", "fees_not_array", "fees must be an array", university_id, "cycle", cycle_id)
                fees = []
            seen_fees: set = set()
            for fee_index, fee in enumerate(fees):
                if not isinstance(fee, dict):
                    issues.add("error", "fee_not_object", "fee is not an object", university_id, "cycle", cycle_id)
                    continue
                fee_id = str(fee.get("fee_id") or _generated_id("fee", project_id, cycle_id, fee_index))
                if fee_id in seen_fees:
                    fee_id = _generated_id("fee", project_id, cycle_id, fee_index, fee_id)
                seen_fees.add(fee_id)
                amount = fee.get("amount")
                if amount == "unknown":
                    amount = None
                conn.execute(
                    """INSERT INTO fees
                       (project_id, cycle_id, fee_id, fee_type, amount, currency, period,
                        applicant_group, condition, source_id, verification_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_id,
                        cycle_id,
                        fee_id,
                        str(fee.get("type") or fee.get("fee_type") or ""),
                        amount,
                        fee.get("currency"),
                        fee.get("period"),
                        str(fee.get("applicant_group") or "all"),
                        str(fee.get("condition") or ""),
                        fee.get("source_id"),
                        str(fee.get("verification_status") or ""),
                    ),
                )

    reviews_path = package_dir / "reviews.json"
    reviews = _read_json(reviews_path, issues, university_id, "reviews", [])
    if not isinstance(reviews, list):
        issues.add("error", "reviews_not_array", "reviews.json must be an array", university_id)
        reviews = []
    seen_reviews: set = set()
    for review_index, review in enumerate(reviews):
        if not isinstance(review, dict):
            continue
        review_id = str(review.get("review_id") or _generated_id("review", university_id, review_index))
        if review_id in seen_reviews:
            continue
        seen_reviews.add(review_id)
        conn.execute(
            """INSERT INTO reviews
               (university_id, review_id, entity_type, entity_id, field_name, selected_source_id,
                rejected_source_ids_json, decision, reviewed_by, reviewed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                university_id,
                review_id,
                str(review.get("entity_type") or ""),
                str(review.get("entity_id") or ""),
                str(review.get("field_name") or ""),
                review.get("selected_source_id"),
                _json_text(review.get("rejected_source_ids") or []),
                str(review.get("decision") or ""),
                str(review.get("reviewed_by") or ""),
                str(review.get("reviewed_at") or ""),
            ),
        )

    manifest_status = "ok" if manifest_path.is_file() and manifest else "missing_or_invalid"
    conn.execute(
        """INSERT INTO data_packages
           (university_id, package_path, package_version, manifest_status, projects_status,
            sources_status, project_count, source_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            university_id,
            str(package_dir.relative_to(package_dir.parents[2])).replace("\\", "/"),
            str(manifest.get("package_version") or ""),
            manifest_status,
            projects_status,
            sources_status,
            imported_projects,
            source_count,
        ),
    )


def _insert_rankings(
    conn: sqlite3.Connection,
    root: Path,
    issues: IssueCollector,
    timestamps: List[Any],
) -> None:
    for source in RANKING_SOURCES:
        path = _ranking_input_path(root, source)
        if "frontend/public/data" in path.as_posix():
            issues.add(
                "warning", "ranking_legacy_fallback",
                "ranking snapshot still comes from frontend output; migrate it to raw/rankings/%s/normalized.json" % source,
                source_path=str(path),
            )
        rows = _read_json(path, issues, source, "ranking", [])
        if not isinstance(rows, list):
            issues.add("error", "ranking_not_array", "ranking snapshot must be an array", source_path=str(path))
            continue
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                issues.add("error", "ranking_row_not_object", "ranking row is not an object", source_path=str(path))
                continue
            university_id = str(row.get("universityId") or row.get("university_id") or "")
            name = str(row.get("name") or university_id)
            rank = row.get("rank")
            if not university_id or not isinstance(rank, int):
                issues.add(
                    "error", "ranking_row_missing_identity", "ranking row requires integer rank and university id",
                    source, "ranking", str(row_index), str(path),
                )
                continue
            _upsert_university(
                conn,
                university_id,
                name,
                str(row.get("country") or ""),
                package_status="ranking_only",
                source_path=str(path.relative_to(root)).replace("\\", "/"),
            )
            edition = row.get("year")
            if isinstance(edition, int):
                timestamps.append("%04d-01-01" % edition)
            score = row.get("score")
            if not isinstance(score, (int, float)):
                score = None
            conn.execute(
                """INSERT INTO ranking_entries
                   (source, row_index, edition, rank, university_id, name, country, score, source_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    source,
                    row_index,
                    edition if isinstance(edition, int) else None,
                    rank,
                    university_id,
                    name,
                    normalize_country(row.get("country")),
                    score,
                    str(path.relative_to(root)).replace("\\", "/"),
                ),
            )


def _insert_aliases(conn: sqlite3.Connection, root: Path, issues: IssueCollector) -> int:
    path = _alias_input_path(root)
    if "frontend/public/data" in path.as_posix():
        issues.add(
            "warning", "aliases_legacy_fallback",
            "alias registry still comes from frontend output; migrate it to raw/university_aliases.json",
            source_path=str(path),
        )
    document = _read_json(path, issues, "aliases", "aliases", {})
    if not isinstance(document, dict):
        document = {}
    canonical_by_id = document.get("canonicalById") or {}
    reason_by_id = document.get("reasonById") or {}
    if not isinstance(canonical_by_id, dict):
        issues.add("error", "aliases_not_object", "canonicalById must be an object", source_path=str(path))
        canonical_by_id = {}
    existing_ids = {
        row[0] for row in conn.execute("SELECT university_id FROM universities ORDER BY university_id")
    }
    for university_id in sorted(existing_ids):
        canonical_by_id.setdefault(university_id, university_id)
    for alias_id in sorted(canonical_by_id):
        canonical_id = str(canonical_by_id.get(alias_id) or alias_id)
        alias_id = str(alias_id)
        alias_row = conn.execute("SELECT * FROM universities WHERE university_id = ?", (alias_id,)).fetchone()
        canonical_row = conn.execute("SELECT * FROM universities WHERE university_id = ?", (canonical_id,)).fetchone()
        template = canonical_row or alias_row
        if alias_row is None:
            _upsert_university(
                conn,
                alias_id,
                template["name"] if template else alias_id,
                template["country"] if template else "",
                template["region"] if template else "",
                template["website"] if template else "",
                package_status="alias_only",
            )
        if canonical_row is None:
            template = alias_row or conn.execute(
                "SELECT * FROM universities WHERE university_id = ?", (alias_id,)
            ).fetchone()
            _upsert_university(
                conn,
                canonical_id,
                template["name"] if template else canonical_id,
                template["country"] if template else "",
                template["region"] if template else "",
                template["website"] if template else "",
                package_status="alias_only",
            )
        conn.execute(
            "INSERT INTO university_aliases (alias_id, canonical_id, reason) VALUES (?, ?, ?)",
            (alias_id, canonical_id, str(reason_by_id.get(alias_id) or "")),
        )
    version = document.get("version")
    return version if isinstance(version, int) else 1


def _database_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    tables = (
        "universities", "data_packages", "projects", "admission_cycles", "timelines",
        "requirements", "fees", "sources", "reviews", "ranking_entries", "validation_issues",
    )
    return {table: conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0] for table in tables}


def build_database(root: Path = ROOT, database_path: Optional[Path] = None) -> Dict[str, Any]:
    root = root.resolve()
    database_path = (database_path or root / "normalized" / "rankingselect.sqlite").resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = database_path.with_name(database_path.name + ".tmp")
    if temp_path.exists():
        temp_path.unlink()

    issues = IssueCollector()
    timestamps: List[Any] = []
    corpus_hash = _corpus_hash(root)
    conn = sqlite3.connect(str(temp_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA page_size = 4096")
        conn.executescript(SCHEMA_SQL)
        seen_project_ids: Dict[str, str] = {}
        raw_dir = root / "raw" / "universities"
        if not raw_dir.is_dir():
            raise PipelineError("raw/universities does not exist")
        for package_dir in sorted(path for path in raw_dir.iterdir() if path.is_dir()):
            _insert_package(conn, package_dir, issues, timestamps, seen_project_ids)
        _insert_rankings(conn, root, issues, timestamps)
        alias_version = _insert_aliases(conn, root, issues)
        built_at = _stable_timestamp(timestamps)

        for issue_id, issue in enumerate(issues.items, 1):
            issue_source_path = issue["sourcePath"]
            if issue_source_path:
                try:
                    issue_source_path = str(Path(issue_source_path).resolve().relative_to(root)).replace("\\", "/")
                except (OSError, ValueError):
                    issue_source_path = str(issue_source_path).replace("\\", "/")
            conn.execute(
                """INSERT INTO validation_issues
                   (issue_id, severity, code, package_id, entity_type, entity_id, source_path, message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    issue_id,
                    issue["severity"],
                    issue["code"],
                    issue["packageId"],
                    issue["entityType"],
                    issue["entityId"],
                    issue_source_path,
                    issue["message"],
                ),
            )
        metadata = {
            "schema_version": str(SCHEMA_VERSION),
            "corpus_hash": corpus_hash,
            "data_timestamp": built_at,
            "alias_version": str(alias_version),
        }
        conn.executemany(
            "INSERT INTO schema_metadata (key, value) VALUES (?, ?)", sorted(metadata.items())
        )
        foreign_key_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_issues:
            raise PipelineError("SQLite foreign key check failed with %d issue(s)" % len(foreign_key_issues))
        conn.commit()
        counts = _database_counts(conn)
        conn.execute("VACUUM")
        conn.commit()
    except Exception:
        conn.close()
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
    os.replace(str(temp_path), str(database_path))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "dataTimestamp": built_at,
        "corpusHash": corpus_hash,
        "database": str(database_path),
        "counts": counts,
        "issuesBySeverity": issues.counts(),
    }


def _dict_rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _atomic_json(path: Path, value: Any, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if pretty
        else _json_text(value)
    )
    temp_path.write_text(payload, encoding="utf-8")
    os.replace(str(temp_path), str(path))


def _decode_json_column(row: Dict[str, Any], key: str, default: Any) -> None:
    try:
        row[key[:-5] if key.endswith("_json") else key] = json.loads(row.pop(key))
    except (TypeError, ValueError):
        row[key[:-5] if key.endswith("_json") else key] = default


def _applicant_group(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized or normalized in ("all", "unknown"):
        return "All" if normalized != "unknown" else "Unknown"
    if normalized in ("non_eu", "non_eu_eea", "international"):
        return "Non-EU"
    if normalized in ("eu", "eu_eea"):
        return "EU"
    return "Unknown"


def _deadline_date(row: Mapping[str, Any], prefer_end: bool) -> Optional[str]:
    date_type = row.get("date_type")
    start = row.get("date")
    end = row.get("date_end")
    if date_type == "exact" and start:
        return str(start)
    if date_type == "month" and start and re.match(r"^\d{4}-\d{2}$", str(start)):
        year, month = [int(part) for part in str(start).split("-")]
        return "%04d-%02d-%02d" % (year, month, calendar.monthrange(year, month)[1])
    if date_type == "range":
        return str(end or start) if prefer_end and (end or start) else (str(start) if start else None)
    return None


def _requirements_for_front(row: Optional[Mapping[str, Any]]) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {
        "gpa": None,
        "ielts": None,
        "toefl": None,
        "gre": None,
        "gmat": None,
        "language": None,
        "academic": None,
    }
    if not row:
        return result
    try:
        tests = json.loads(str(row.get("language_tests_json") or "[]"))
    except ValueError:
        tests = []
    other_tests = []
    for test in tests if isinstance(tests, list) else []:
        if not isinstance(test, dict):
            continue
        name = str(test.get("name") or "").strip()
        score = str(test.get("min_score") or "").strip()
        if not name or not score:
            continue
        lowered = name.lower()
        if "ielts" in lowered and result["ielts"] is None:
            result["ielts"] = score
        elif "toefl" in lowered and result["toefl"] is None:
            result["toefl"] = score
        else:
            other_tests.append("%s %s" % (name, score))
    for key, label in (("gre", "GRE"), ("gmat", "GMAT")):
        status = row.get(key + "_status")
        score = row.get(key + "_min_score")
        if status in ("required", "optional"):
            suffix = "required" if status == "required" else "recommended"
            result[key] = "%s %s (%s)" % (label, score, suffix) if score else "%s %s" % (label, suffix)
    if other_tests:
        result["language"] = " / ".join(other_tests)
    if row.get("academic_status") in ("required", "optional"):
        result["academic"] = row.get("academic_description")
    return result


def _build_frontend_programs(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cycles_by_project: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in _dict_rows(conn, "SELECT * FROM admission_cycles ORDER BY project_id, cycle_id"):
        cycles_by_project[row["project_id"]].append(row)
    timelines_by_cycle: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in _dict_rows(conn, "SELECT * FROM timelines ORDER BY project_id, cycle_id, timeline_id"):
        timelines_by_cycle[(row["project_id"], row["cycle_id"])].append(row)
    requirements_by_cycle = {
        (row["project_id"], row["cycle_id"]): row
        for row in _dict_rows(conn, "SELECT * FROM requirements ORDER BY project_id, cycle_id")
    }
    fees_by_cycle: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in _dict_rows(conn, "SELECT * FROM fees ORDER BY project_id, cycle_id, fee_id"):
        fees_by_cycle[(row["project_id"], row["cycle_id"])].append(row)
    source_urls = {
        (row["university_id"], row["source_id"]): row["url"]
        for row in _dict_rows(conn, "SELECT university_id, source_id, url FROM sources ORDER BY university_id, source_id")
    }
    updated_by_university = {
        row["university_id"]: row["updated_at"][:10]
        for row in _dict_rows(conn, "SELECT university_id, updated_at FROM universities")
    }

    programs: List[Dict[str, Any]] = []
    for project in _dict_rows(conn, "SELECT * FROM projects WHERE status = 'active' ORDER BY project_id"):
        all_cycles = cycles_by_project.get(project["project_id"], [])
        cycles = [row for row in all_cycles if row["status"] == "current"]
        if not cycles:
            cycles = [row for row in all_cycles if row["status"] != "historical"]
        deadlines: List[Dict[str, str]] = []
        windows: List[Dict[str, str]] = []
        fees: List[Dict[str, Any]] = []
        requirement = _requirements_for_front(None)
        evidence_urls: set = set()
        verification_statuses = [project.get("verification_status")]
        deadline_statuses: List[str] = []
        for cycle in cycles:
            verification_statuses.append(cycle.get("verification_status"))
            key = (project["project_id"], cycle["cycle_id"])
            cycle_requirement = requirements_by_cycle.get(key)
            candidate = _requirements_for_front(cycle_requirement)
            for field, value in candidate.items():
                if value and not requirement.get(field):
                    requirement[field] = value
            if cycle_requirement:
                verification_statuses.append(cycle_requirement.get("verification_status"))
                source_id = cycle_requirement.get("source_id")
                url = source_urls.get((project["university_id"], source_id))
                if url:
                    evidence_urls.add(url)
            for timeline in timelines_by_cycle.get(key, []):
                event = str(timeline.get("event") or "").lower()
                source_id = timeline.get("source_id")
                url = source_urls.get((project["university_id"], source_id))
                if url:
                    evidence_urls.add(url)
                if "deadline" in event:
                    deadline_statuses.append(str(timeline.get("verification_status") or ""))
                    value = _deadline_date(timeline, True)
                    if value:
                        deadlines.append(
                            {
                                "round": str(timeline.get("round") or "Regular"),
                                "date": value,
                                "applicantGroup": _applicant_group(timeline.get("applicant_group")),
                            }
                        )
                elif any(token in event for token in ("open", "start", "window", "round")):
                    value = _deadline_date(timeline, False)
                    if value:
                        windows.append(
                            {
                                "round": str(timeline.get("round") or "Regular"),
                                "date": value,
                                "applicantGroup": _applicant_group(timeline.get("applicant_group")),
                            }
                        )
            for fee in fees_by_cycle.get(key, []):
                fees.append(
                    {
                        "type": fee.get("fee_type"),
                        "amount": fee.get("amount"),
                        "currency": fee.get("currency"),
                        "period": fee.get("period"),
                        "applicantGroup": _applicant_group(fee.get("applicant_group")),
                    }
                )
                url = source_urls.get((project["university_id"], fee.get("source_id")))
                if url:
                    evidence_urls.add(url)
        dedupe_deadline: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for deadline in deadlines:
            dedupe_deadline[(deadline["date"], deadline["round"], deadline["applicantGroup"])] = deadline
        deadlines = sorted(dedupe_deadline.values(), key=lambda row: (row["date"], row["round"]))
        dedupe_window: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for window in windows:
            dedupe_window[(window["date"], window["round"], window["applicantGroup"])] = window
        windows = sorted(dedupe_window.values(), key=lambda row: (row["date"], row["round"]))
        source_url = str(project.get("official_url") or "")
        if source_url:
            evidence_urls.add(source_url)
        programs.append(
            {
                "id": project["project_id"],
                "universityId": project["university_id"],
                "subject": project.get("subject") or "General",
                "dept": project.get("department") or "",
                "program": project["name"],
                "deadlines": deadlines,
                "materials": [],
                "requirements": requirement,
                "fees": fees,
                "sourceUrl": source_url,
                "verified": bool(verification_statuses) and all(status == "verified" for status in verification_statuses),
                "updatedAt": updated_by_university.get(project["university_id"]) or "",
                "deadlineReviewed": bool(deadlines) and bool(deadline_statuses) and all(
                    status == "verified" for status in deadline_statuses
                ),
                "evidenceUrls": sorted(evidence_urls),
                "applicationWindows": windows,
            }
        )
    return programs


def _has_requirement(program: Mapping[str, Any]) -> bool:
    return any((program.get("requirements") or {}).values())


def _build_frontend_universities(
    conn: sqlite3.Connection,
    programs: Sequence[Mapping[str, Any]],
    aliases: Mapping[str, str],
) -> Dict[str, Dict[str, Any]]:
    subjects_by_university: Dict[str, set] = defaultdict(set)
    for program in programs:
        subject = program.get("subject")
        if subject and subject != "General":
            subjects_by_university[str(program["universityId"])].add(str(subject))
    sources_by_university: Dict[str, set] = defaultdict(set)
    for row in conn.execute("SELECT source, university_id FROM ranking_entries ORDER BY source, row_index"):
        canonical = aliases.get(row["university_id"], row["university_id"])
        sources_by_university[canonical].add(row["source"])
    result: Dict[str, Dict[str, Any]] = {}
    for row in conn.execute("SELECT * FROM universities ORDER BY university_id"):
        university_id = row["university_id"]
        canonical = aliases.get(university_id, university_id)
        result[university_id] = {
            "id": university_id,
            "name": {"en": row["name"]},
            "country": row["country"],
            "region": row["region"] or region_for(row["country"]),
            "website": row["website"],
            "subjects": sorted(subjects_by_university.get(canonical, set()) | subjects_by_university.get(university_id, set())),
            "sources": sorted(sources_by_university.get(canonical, set())),
        }
    return result


def _build_coverage(
    universities: Mapping[str, Mapping[str, Any]],
    programs: Sequence[Mapping[str, Any]],
    aliases: Mapping[str, str],
    data_timestamp: str,
) -> List[Dict[str, Any]]:
    by_canonical: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for program in programs:
        canonical = aliases.get(str(program["universityId"]), str(program["universityId"]))
        by_canonical[canonical].append(program)
    rows: List[Dict[str, Any]] = []
    for university_id in sorted(universities):
        university = universities[university_id]
        canonical = aliases.get(university_id, university_id)
        group = by_canonical.get(canonical, [])
        deadline_count = sum(1 for program in group if program.get("deadlines"))
        requirement_count = sum(1 for program in group if _has_requirement(program))
        verified_count = sum(1 for program in group if program.get("verified"))
        if not group:
            status, completeness = "pending", 0
        else:
            completeness = round(
                sum(
                    (40 if program.get("deadlines") else 0)
                    + (40 if _has_requirement(program) else 0)
                    + (20 if program.get("verified") else 0)
                    for program in group
                )
                / len(group)
            )
            status = "verified" if verified_count == len(group) else (
                "extracted" if deadline_count or requirement_count else "partial"
            )
        website = str(university.get("website") or "")
        host = urlparse(website).netloc if website.startswith("http") else ""
        rows.append(
            {
                "universityId": university_id,
                "name": (university.get("name") or {}).get("en", university_id),
                "country": university.get("country") or "",
                "region": university.get("region") or "",
                "status": status,
                "programCount": len(group),
                "deadlineCount": deadline_count,
                "requirementCount": requirement_count,
                "verifiedCount": verified_count,
                "completeness": completeness,
                "officialDomains": [host] if host else [],
                "indexUrl": website,
                "updatedAt": data_timestamp[:10],
            }
        )
    return rows


def export_database(
    root: Path = ROOT,
    database_path: Optional[Path] = None,
    generated_dir: Optional[Path] = None,
    frontend_dir: Optional[Path] = None,
    write_frontend: bool = True,
) -> Dict[str, Any]:
    root = root.resolve()
    database_path = (database_path or root / "normalized" / "rankingselect.sqlite").resolve()
    generated_dir = (generated_dir or root / "generated").resolve()
    frontend_dir = frontend_dir.resolve() if frontend_dir is not None else (root / "frontend" / "public" / "data").resolve()
    if not database_path.is_file():
        raise PipelineError("database does not exist: %s" % database_path)

    conn = sqlite3.connect("file:%s?mode=ro" % database_path.as_posix(), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        metadata = dict(conn.execute("SELECT key, value FROM schema_metadata ORDER BY key"))
        foreign_key_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_issues:
            raise PipelineError("refusing to export a database with foreign key violations")
        counts = _database_counts(conn)
        aliases = {
            row["alias_id"]: row["canonical_id"]
            for row in conn.execute("SELECT alias_id, canonical_id FROM university_aliases ORDER BY alias_id")
        }
        reasons = {
            row["alias_id"]: row["reason"]
            for row in conn.execute("SELECT alias_id, reason FROM university_aliases WHERE reason <> '' ORDER BY alias_id")
        }
        programs = _build_frontend_programs(conn)
        universities = _build_frontend_universities(conn, programs, aliases)
        coverage = _build_coverage(universities, programs, aliases, metadata["data_timestamp"])

        ranking_documents: Dict[str, List[Dict[str, Any]]] = {}
        for source in RANKING_SOURCES:
            ranking_documents[source] = [
                {
                    "rank": row["rank"],
                    "universityId": row["university_id"],
                    "name": row["name"],
                    "country": row["country"],
                    "score": row["score"],
                    "year": row["edition"],
                }
                for row in conn.execute(
                    "SELECT * FROM ranking_entries WHERE source = ? ORDER BY row_index", (source,)
                )
            ]
        issue_counts = dict(
            conn.execute(
                "SELECT severity, COUNT(*) FROM validation_issues GROUP BY severity ORDER BY severity"
            ).fetchall()
        )
        unknown_timelines = conn.execute(
            "SELECT COUNT(*) FROM timelines WHERE date_type = 'unknown'"
        ).fetchone()[0]
        programs_with_deadline = sum(1 for program in programs if program.get("deadlines"))
        programs_with_requirement = sum(1 for program in programs if _has_requirement(program))
        programs_verified = sum(1 for program in programs if program.get("verified"))
        data_manifest = {
            "schemaVersion": int(metadata["schema_version"]),
            "dataTimestamp": metadata["data_timestamp"],
            "corpusHash": metadata["corpus_hash"],
            "sourceOfTruth": "normalized/rankingselect.sqlite",
            "counts": counts,
            "quality": {
                "issuesBySeverity": issue_counts,
                "unknownTimelines": unknown_timelines,
                "unknownTimelinePercent": round(unknown_timelines * 100 / max(counts["timelines"], 1), 2),
                "programsWithDeadline": programs_with_deadline,
                "programsWithRequirement": programs_with_requirement,
                "programsVerified": programs_verified,
            },
        }
        alias_document = {
            "version": int(metadata.get("alias_version", "1")),
            "generatedAt": metadata["data_timestamp"],
            "canonicalById": aliases,
            "reasonById": reasons,
        }

        normalized_projects = _dict_rows(conn, "SELECT * FROM projects ORDER BY project_id")
        for row in normalized_projects:
            _decode_json_column(row, "teaching_language_json", [])
        normalized_requirements = _dict_rows(conn, "SELECT * FROM requirements ORDER BY project_id, cycle_id")
        for row in normalized_requirements:
            _decode_json_column(row, "language_tests_json", [])
            _decode_json_column(row, "raw_json", {})
        normalized_reviews = _dict_rows(conn, "SELECT * FROM reviews ORDER BY university_id, review_id")
        for row in normalized_reviews:
            _decode_json_column(row, "rejected_source_ids_json", [])

        generated_documents = {
            "universities.json": universities,
            "projects.json": normalized_projects,
            "programs.json": programs,
            "program_coverage.json": coverage,
            "admission_cycles.json": _dict_rows(conn, "SELECT * FROM admission_cycles ORDER BY project_id, cycle_id"),
            "timelines.json": _dict_rows(conn, "SELECT * FROM timelines ORDER BY project_id, cycle_id, timeline_id"),
            "requirements.json": normalized_requirements,
            "fees.json": _dict_rows(conn, "SELECT * FROM fees ORDER BY project_id, cycle_id, fee_id"),
            "sources.json": _dict_rows(conn, "SELECT * FROM sources ORDER BY university_id, source_id"),
            "reviews.json": normalized_reviews,
            "university_aliases.json": alias_document,
            "validation_issues.json": _dict_rows(conn, "SELECT * FROM validation_issues ORDER BY issue_id"),
            "data-manifest.json": data_manifest,
            "build_report.json": data_manifest,
        }
        for filename, document in generated_documents.items():
            _atomic_json(generated_dir / filename, document)
        for source, document in ranking_documents.items():
            _atomic_json(generated_dir / "rankings" / (source + ".json"), document)

        if write_frontend:
            frontend_documents = {
                "universities.json": universities,
                "programs.json": programs,
                "program_coverage.json": coverage,
                "university_aliases.json": alias_document,
                "data-manifest.json": data_manifest,
            }
            for filename, document in frontend_documents.items():
                _atomic_json(frontend_dir / filename, document)
            for source, document in ranking_documents.items():
                _atomic_json(frontend_dir / "rankings" / (source + ".json"), document, pretty=True)
    finally:
        conn.close()
    return data_manifest


def run_all(
    root: Path = ROOT,
    database_path: Optional[Path] = None,
    generated_dir: Optional[Path] = None,
    frontend_dir: Optional[Path] = None,
    write_frontend: bool = True,
) -> Dict[str, Any]:
    build_database(root, database_path)
    return export_database(root, database_path, generated_dir, frontend_dir, write_frontend)


def _print_report(report: Mapping[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build and export RankingSelect's canonical data pipeline.")
    parser.add_argument("command", choices=("validate", "build", "export", "all"), nargs="?", default="all")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--generated-output", type=Path, default=None)
    parser.add_argument("--frontend-output", type=Path, default=None)
    parser.add_argument("--no-frontend", action="store_true")
    parser.add_argument("--strict", action="store_true", help="return non-zero when validation errors exist")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    database = args.database or root / "normalized" / "rankingselect.sqlite"
    generated = args.generated_output or root / "generated"
    frontend: Optional[Path]
    if args.no_frontend:
        frontend = None
    else:
        frontend = args.frontend_output or root / "frontend" / "public" / "data"

    if args.command == "validate":
        with tempfile.TemporaryDirectory(prefix="rankingselect-validate-") as temp_dir:
            temp_root = Path(temp_dir)
            report = build_database(root, temp_root / "rankingselect.sqlite")
    elif args.command == "build":
        report = build_database(root, database)
    elif args.command == "export":
        report = export_database(root, database, generated, frontend, not args.no_frontend)
    else:
        report = run_all(root, database, generated, frontend, not args.no_frontend)
    _print_report(report)
    issue_counts = report.get("issuesBySeverity") or (report.get("quality") or {}).get("issuesBySeverity") or {}
    return 1 if args.strict and issue_counts.get("error", 0) else 0


if __name__ == "__main__":
    sys.exit(main())
