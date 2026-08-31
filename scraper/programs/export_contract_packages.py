"""Export captured programme pages as contract-compliant university packages.

The exporter is deliberately conservative. A captured page becomes a project
only when its title or URL has a master's-degree signal and the shared quality
rules do not classify it as a directory, admission guide, news item, or other
non-project page. Unknown cycle facts stay unknown and remain needs_review.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .quality import non_program_reason_strict


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS = ROOT / "raw" / "rankings" / "round1_50_250_targets.json"
DEFAULT_CRAWL_ROOT = ROOT / "scraper" / "work" / "round1_50_250_raw"
DEFAULT_OUTPUT = ROOT / "raw" / "universities"
DEFAULT_REPORT = ROOT / "raw" / "rankings" / "round1_50_250_export_report.json"
DEGREE_SIGNAL = re.compile(
    r"\b(?:master(?:'s|s)?|msc|m\.sc\.?|ma|m\.a\.?|meng|m\.eng|mba|llm|ll\.m|"
    r"graduate degree|postgraduate degree|second[ -]?cycle|laurea magistrale|magister)\b",
    re.IGNORECASE,
)
GENERIC_TITLE = re.compile(
    r"^(?:master(?:'s)? programmes?|graduate programmes?|postgraduate programmes?|"
    r"degree programmes?|courses?|programmes?|admissions?|application|how to apply|"
    r"entry requirements?|tuition fees?)$",
    re.IGNORECASE,
)
TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")
ID_CLEAN = re.compile(r"[^a-z0-9]+")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def slug(value: str, fallback: str = "programme") -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    result = ID_CLEAN.sub("_", ascii_value).strip("_")
    return (result[:72].strip("_") or fallback)


def compact_text(value: str) -> str:
    text = TAG.sub(" ", value or "")
    return SPACE.sub(" ", text).strip()


def read_capture(crawl_dir: Path, record: Mapping[str, Any]) -> Tuple[bytes, str]:
    relative = str(record.get("file") or "")
    if not relative:
        return b"", ""
    path = (crawl_dir / relative).resolve()
    if not str(path).startswith(str(crawl_dir.resolve())) or not path.exists():
        return b"", ""
    try:
        raw = gzip.open(str(path), "rb").read() if path.suffix == ".gz" else path.read_bytes()
    except (OSError, EOFError):
        return b"", ""
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw, raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw, raw.decode("utf-8", "replace")


def project_name(url: str, record: Mapping[str, Any]) -> str:
    link_text = SPACE.sub(" ", str(record.get("text") or "")).strip()
    document_title = SPACE.sub(" ", str(record.get("documentTitle") or "")).strip()
    candidates = [link_text, document_title]
    for value in candidates:
        if not value or len(value) > 220:
            continue
        if GENERIC_TITLE.fullmatch(value):
            continue
        reason = non_program_reason_strict(value, url)
        if reason:
            continue
        if DEGREE_SIGNAL.search(value + " " + url):
            return value
    return ""


def infer_degree(name: str) -> Optional[str]:
    patterns = (
        (r"\bMSc\b|\bM\.Sc\.?\b", "MSc"),
        (r"\bMBA\b", "MBA"),
        (r"\bLLM\b|\bLL\.M\b", "LLM"),
        (r"\bMEng\b|\bM\.Eng\b", "MEng"),
        (r"\bMA\b|\bM\.A\.?\b", "MA"),
        (r"\bMaster", "Master"),
    )
    for pattern, value in patterns:
        if re.search(pattern, name, re.IGNORECASE):
            return value
    return None


def infer_subject(name: str) -> Optional[str]:
    fields = (
        (r"computer|informatics|artificial intelligence|data science|cyber", "Computer Science"),
        (r"electrical|electronic", "Electrical Engineering"),
        (r"mechanical|mechatronic|aerospace", "Mechanical Engineering"),
        (r"civil|structural|construction", "Civil Engineering"),
        (r"business|management|finance|economics", "Business and Economics"),
        (r"biology|biomedical|biotechnology|medicine|health", "Life Sciences"),
        (r"physics|quantum", "Physics"),
        (r"mathematics|statistics", "Mathematics"),
    )
    for pattern, value in fields:
        if re.search(pattern, name, re.IGNORECASE):
            return value
    return None


def build_project(
    university_id: str,
    name: str,
    url: str,
    source_id: str,
    used_codes: set,
) -> Dict[str, Any]:
    base_code = slug(name)
    code = base_code
    if code in used_codes:
        code = f"{base_code[:60]}_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:8]}"
    used_codes.add(code)
    project_id = f"{university_id}_main_{code}"
    timeline = {
        "timeline_id": "application_deadline",
        "event": "application_deadline",
        "date_type": "unknown",
        "date": None,
        "date_end": None,
        "applicant_group": "all",
        "round": None,
        "source_id": source_id,
        "verification_status": "needs_review",
    }
    requirements = {
        "language": {"status": "unknown", "tests": []},
        "gre": {"status": "unknown", "min_score": None},
        "gmat": {"status": "unknown", "min_score": None},
        "academic": {"status": "unknown", "description": None},
        "notes": "First-pass capture found no safely structured requirement values.",
        "source_id": source_id,
        "verification_status": "needs_review",
    }
    fee = {
        "fee_id": "tuition",
        "type": "tuition",
        "amount": "unknown",
        "currency": "unknown",
        "period": "unknown",
        "applicant_group": "all",
        "condition": "Consult the official source for the current academic year.",
        "source_id": source_id,
        "verification_status": "needs_review",
    }
    return {
        "project_id": project_id,
        "university_id": university_id,
        "campus_id": "main",
        "normalized_program_code": code,
        "name": name,
        "degree": infer_degree(name),
        "subject": infer_subject(name),
        "study_mode": None,
        "teaching_language": [],
        "official_url": url,
        "admission_cycles": [{
            "cycle_id": "27fall",
            "academic_year": 2027,
            "entry_term": "fall",
            "status": "current",
            "timelines": [timeline],
            "requirements": requirements,
            "fees": [fee],
        }],
        "status": "active",
        "notes": "Discovered from an official page and pending human verification.",
    }


def validate_package(package: Mapping[str, Any]) -> None:
    manifest = package["manifest"]
    sources = package["sources"]
    projects = package["projects"]
    source_ids = {row["source_id"] for row in sources}
    if not source_ids or len(source_ids) != len(sources):
        raise ValueError("package sources must be non-empty and unique")
    if not projects:
        raise ValueError("package projects must be non-empty")
    for project in projects:
        expected = "{}_{}_{}".format(
            manifest["university_id"], project["campus_id"], project["normalized_program_code"]
        )
        if project["project_id"] != expected:
            raise ValueError("project id does not follow the contract")
        cycles = project["admission_cycles"]
        if len(cycles) != 1 or cycles[0]["cycle_id"] != "27fall" or cycles[0]["status"] != "current":
            raise ValueError("round-1 export requires one current 27fall cycle")
        cycle = cycles[0]
        for timeline in cycle["timelines"]:
            if timeline["source_id"] not in source_ids:
                raise ValueError("timeline source is missing")
            if timeline["date_type"] == "unknown" and (timeline["date"] is not None or timeline["date_end"] is not None):
                raise ValueError("unknown timeline cannot contain a date")
        if cycle["requirements"].get("source_id") not in source_ids:
            raise ValueError("requirements source is missing")
        for fee in cycle["fees"]:
            if fee["source_id"] not in source_ids or not re.fullmatch(r"unknown|\d+(?:\.\d+)?", fee["amount"]):
                raise ValueError("invalid fee source or amount")


def build_package(
    target: Mapping[str, Any],
    crawl_dir: Path,
    manifest: Mapping[str, Any],
    max_projects: int,
) -> Optional[Dict[str, Any]]:
    candidates = []
    for url, record in (manifest.get("pages") or {}).items():
        if record.get("kind") != "program" or record.get("status") != "captured" or record.get("blocked"):
            continue
        name = project_name(url, record)
        if name:
            candidates.append((name, url, record))
    candidates.sort(key=lambda row: (row[0].casefold(), row[1]))
    if not candidates:
        return None
    projects = []
    sources = []
    evidence = []
    used_codes = set()
    seen_urls = set()
    for name, url, record in candidates:
        if url in seen_urls or len(projects) >= max_projects:
            continue
        seen_urls.add(url)
        raw, text = read_capture(crawl_dir, record)
        source_id = "src_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        captured_at = str(record.get("capturedAt") or datetime.now(timezone.utc).isoformat())
        digest = str(record.get("sha256") or hashlib.sha256(raw).hexdigest())
        sources.append({
            "source_id": source_id,
            "url": url,
            "source_type": "official_web",
            "retrieved_at": captured_at,
            "verification_status": "extracted",
            "title": str(record.get("documentTitle") or name),
            "content_hash": digest,
            "evidence_text": compact_text(text)[:2000],
        })
        evidence.append({
            "source_id": source_id,
            "url": url,
            "captured_at": captured_at,
            "response_url": record.get("responseUrl"),
            "http_status": record.get("statusCode"),
            "content_type": record.get("contentType"),
            "content_hash": digest,
            "document_title": record.get("documentTitle"),
            "text_excerpt": compact_text(text)[:4000],
        })
        projects.append(build_project(str(target["universityId"]), name, url, source_id, used_codes))
    if not projects:
        return None
    target_url = str(target.get("indexUrl") or "")
    manifest_doc = {
        "schema_version": 1,
        "package_version": "2026.08.19.1",
        "university_id": str(target["universityId"]),
        "name": str(target["name"]),
        "country": str(target["country"]),
        "region": str(target.get("region") or "Unknown"),
        "updated_at": "2026-08-19",
        "notes": "Automated first-pass package; all structured cycle facts require human review.",
        "converter": "scraper.programs.export_contract_packages",
        "input_file": str(crawl_dir.name) + "/manifest.json",
    }
    if target.get("urlKind") == "school-homepage" and target_url:
        manifest_doc["website"] = target_url
    package = {
        "manifest": manifest_doc,
        "projects": projects,
        "sources": sources,
        "reviews": [],
        "evidence": evidence,
    }
    validate_package(package)
    return package


def write_package(output_root: Path, package: Mapping[str, Any]) -> None:
    university_id = str(package["manifest"]["university_id"])
    output_dir = output_root / university_id
    if output_dir.exists():
        existing = load_json(output_dir / "manifest.json", {})
        converter = existing.get("converter") if isinstance(existing, dict) else None
        if converter not in {None, "scraper.programs.export_contract_packages"}:
            raise ValueError(f"refusing to overwrite manually maintained package: {university_id}")
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "manifest.json", package["manifest"])
    write_json(output_dir / "projects.json", package["projects"])
    write_json(output_dir / "sources.json", package["sources"])
    write_json(output_dir / "reviews.json", package["reviews"])
    write_json(raw_dir / "source_evidence.json", package["evidence"])
    (output_dir / "notes.md").write_text(
        "# {}\n\nGenerated from first-pass official-page captures. All cycle facts are `needs_review`.\n".format(
            package["manifest"]["name"]
        ),
        encoding="utf-8",
    )


def export(
    targets: Iterable[Mapping[str, Any]],
    crawl_root: Path,
    output_root: Path,
    max_projects: int,
) -> Dict[str, Any]:
    target_rows = list(targets)
    statuses = Counter()
    packages = 0
    projects = 0
    for target in target_rows:
        crawl_dir = crawl_root / slug(str(target["universityId"]), "unknown")
        manifest = load_json(crawl_dir / "manifest.json", None)
        if not manifest:
            statuses["not_crawled"] += 1
            continue
        package = build_package(target, crawl_dir, manifest, max_projects)
        if not package:
            statuses["no_concrete_project"] += 1
            continue
        write_package(output_root, package)
        packages += 1
        projects += len(package["projects"])
        statuses["exported"] += 1
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": "four rankings, ranks 50-250 inclusive, mainland China excluded",
        "summary": {
            "targets": len(target_rows),
            "packages": packages,
            "projects": projects,
            "statuses": dict(statuses),
            "maxProjectsPerUniversity": max_projects,
        },
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--crawl-root", type=Path, default=DEFAULT_CRAWL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-projects-per-university", type=int, default=5)
    args = parser.parse_args(argv)
    if args.max_projects_per_university < 1:
        raise SystemExit("--max-projects-per-university must be positive")
    report = export(
        load_json(args.targets, []),
        args.crawl_root.resolve(),
        args.output.resolve(),
        args.max_projects_per_university,
    )
    write_json(args.report, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
