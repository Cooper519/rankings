"""Repair duplicate source and project IDs in raw university packages.

The repair is intentionally conservative:

* source rows are merged only when URL, content hash, evidence, type and
  verification state agree;
* byte-for-byte equivalent projects are de-duplicated;
* same-ID projects differing only by name receive a new name-derived stable ID;
* same-ID, same-name projects differing only by department are merged with an
  explicit conflict note and an unknown department.

Run without ``--apply`` for a dry-run report. The command refuses to write if
any collision falls outside these rules.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parent.parent
SOURCE_IDENTITY_FIELDS = (
    "url",
    "content_hash",
    "evidence_text",
    "source_type",
    "verification_status",
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _atomic_json(path: Path, value: Any) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(str(temp_path), str(path))


def _same_source_identity(rows: Sequence[Mapping[str, Any]]) -> bool:
    if not rows:
        return False
    first = rows[0]
    return all(
        all(row.get(field) == first.get(field) for field in SOURCE_IDENTITY_FIELDS)
        for row in rows[1:]
    )


def _merge_source_rows(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    earliest = min(rows, key=lambda row: str(row.get("retrieved_at") or ""))
    merged = dict(earliest)
    titles = [str(row.get("title") or "").strip() for row in rows if row.get("title")]
    if titles:
        merged["title"] = min(titles, key=lambda title: (len(title), title))
    return merged


def _project_differences(left: Mapping[str, Any], right: Mapping[str, Any]) -> set:
    return {key for key in set(left) | set(right) if left.get(key) != right.get(key)}


def _program_code(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower().strip()
    text = re.sub(r"^(?:msc|ms|ma|meng|master(?:\s+of)?(?:\s+science)?)\s+", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "program"


def _merge_department_conflict(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    merged = dict(rows[0])
    departments = sorted({str(row.get("department") or "").strip() for row in rows if row.get("department")})
    merged["department"] = None
    conflict_note = "Department needs review; duplicate crawl candidates disagreed: %s." % "; ".join(departments)
    existing_note = str(merged.get("notes") or "").strip()
    merged["notes"] = (existing_note + " " + conflict_note).strip()
    merged["verification_status"] = "needs_review"
    return merged


def repair_package(package_dir: Path) -> Tuple[Dict[str, int], List[str], Dict[str, Any]]:
    counts = {
        "duplicateSourceRowsRemoved": 0,
        "duplicateProjectsRemoved": 0,
        "projectIdsRenamed": 0,
        "departmentConflictsMerged": 0,
    }
    unresolved: List[str] = []
    changes: Dict[str, Any] = {}

    sources_path = package_dir / "sources.json"
    sources = _read_json(sources_path, None)
    if isinstance(sources, list):
        grouped_sources: MutableMapping[str, List[Mapping[str, Any]]] = defaultdict(list)
        for row in sources:
            if isinstance(row, dict) and row.get("source_id"):
                grouped_sources[str(row["source_id"])].append(row)
        replacement_by_id: Dict[str, Dict[str, Any]] = {}
        for source_id, rows in grouped_sources.items():
            if len(rows) < 2:
                continue
            if not _same_source_identity(rows):
                unresolved.append("%s: source %s differs in evidence identity" % (package_dir.name, source_id))
                continue
            replacement_by_id[source_id] = _merge_source_rows(rows)
            counts["duplicateSourceRowsRemoved"] += len(rows) - 1
        if replacement_by_id:
            seen_source_ids = set()
            repaired_sources = []
            for row in sources:
                if not isinstance(row, dict) or not row.get("source_id"):
                    repaired_sources.append(row)
                    continue
                source_id = str(row["source_id"])
                if source_id in seen_source_ids:
                    continue
                seen_source_ids.add(source_id)
                repaired_sources.append(replacement_by_id.get(source_id, row))
            changes["sources.json"] = repaired_sources

    projects_path = package_dir / "projects.json"
    projects = _read_json(projects_path, None)
    if isinstance(projects, list):
        grouped_projects: MutableMapping[str, List[Mapping[str, Any]]] = defaultdict(list)
        for row in projects:
            if isinstance(row, dict) and row.get("project_id"):
                grouped_projects[str(row["project_id"])].append(row)
        repaired_by_id: Dict[str, List[Dict[str, Any]]] = {}
        existing_project_ids = set(grouped_projects)
        for project_id, rows in grouped_projects.items():
            if len(rows) < 2:
                continue
            if all(row == rows[0] for row in rows[1:]):
                repaired_by_id[project_id] = [dict(rows[0])]
                counts["duplicateProjectsRemoved"] += len(rows) - 1
                continue
            difference_sets = [_project_differences(rows[0], row) for row in rows[1:]]
            combined_differences = set().union(*difference_sets)
            if combined_differences == {"name"}:
                repaired_rows = [dict(rows[0])]
                used_ids = {project_id}
                rename_failed = False
                for row in rows[1:]:
                    renamed = dict(row)
                    code = _program_code(str(row.get("name") or ""))
                    new_id = "%s_%s_%s" % (
                        row.get("university_id"),
                        row.get("campus_id") or "main",
                        code,
                    )
                    if new_id in used_ids or new_id in existing_project_ids:
                        unresolved.append("%s: generated project id %s is still duplicated" % (package_dir.name, new_id))
                        rename_failed = True
                        break
                    used_ids.add(new_id)
                    renamed["normalized_program_code"] = code
                    renamed["project_id"] = new_id
                    repaired_rows.append(renamed)
                if not rename_failed:
                    repaired_by_id[project_id] = repaired_rows
                    counts["projectIdsRenamed"] += len(repaired_rows) - 1
                continue
            if combined_differences == {"department"} and len({row.get("name") for row in rows}) == 1:
                repaired_by_id[project_id] = [_merge_department_conflict(rows)]
                counts["departmentConflictsMerged"] += 1
                counts["duplicateProjectsRemoved"] += len(rows) - 1
                continue
            unresolved.append(
                "%s: project %s differs in unsupported fields %s"
                % (package_dir.name, project_id, sorted(combined_differences))
            )
        if repaired_by_id:
            emitted_ids = set()
            repaired_projects = []
            for row in projects:
                if not isinstance(row, dict) or not row.get("project_id"):
                    repaired_projects.append(row)
                    continue
                project_id = str(row["project_id"])
                if project_id in repaired_by_id:
                    if project_id not in emitted_ids:
                        repaired_projects.extend(repaired_by_id[project_id])
                        emitted_ids.add(project_id)
                    continue
                repaired_projects.append(row)
            changes["projects.json"] = repaired_projects

    return counts, unresolved, changes


def run(root: Path, apply: bool = False) -> Dict[str, Any]:
    raw_dir = root / "raw" / "universities"
    totals = {
        "packagesChanged": 0,
        "duplicateSourceRowsRemoved": 0,
        "duplicateProjectsRemoved": 0,
        "projectIdsRenamed": 0,
        "departmentConflictsMerged": 0,
    }
    unresolved: List[str] = []
    changes_by_package: Dict[Path, Dict[str, Any]] = {}
    for package_dir in sorted(path for path in raw_dir.iterdir() if path.is_dir()):
        counts, package_unresolved, changes = repair_package(package_dir)
        unresolved.extend(package_unresolved)
        if changes:
            totals["packagesChanged"] += 1
            changes_by_package[package_dir] = changes
        for key, value in counts.items():
            totals[key] += value
    if apply and unresolved:
        raise RuntimeError("refusing to write while unresolved collisions remain")
    if apply:
        for package_dir, changes in changes_by_package.items():
            for filename, value in changes.items():
                _atomic_json(package_dir / filename, value)
    return {
        "applied": apply,
        "totals": totals,
        "unresolved": unresolved,
        "changedPackages": [package.name for package in sorted(changes_by_package)],
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Repair duplicate IDs in raw university packages.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.root.resolve(), apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report["unresolved"] else 0


if __name__ == "__main__":
    sys.exit(main())
