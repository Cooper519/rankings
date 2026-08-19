"""Clean RankingSelect static datasets and write an auditable report.

This script is intentionally deterministic: it cleans already captured raw
JSON and the current frontend program store without reaching out to the
network. Run it after scraping/assembly and before frontend validation.

Usage:
  python -m scraper.clean_data
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from scraper.programs.normalize import normalize_deadlines
from scraper.programs.quality import denied_source, non_program_reason_strict
from scraper.programs.sanitize_v2 import infer_subject
from scraper.programs.scope_policy import is_mainland_china_country
from scraper.utils import first_int, slug, top_n, write_json


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "frontend" / "public" / "data"
RANKINGS = DATA / "rankings"
REPORT_PATH = DATA / "data_cleaning_report.json"

RANKING_SOURCES = {
    "qs": {"raw": ROOT / "_qs_raw.json", "out": RANKINGS / "qs.json", "year": 2026, "limit": 500},
    "usnews": {"raw": ROOT / "_usnews_raw.json", "out": RANKINGS / "usnews.json", "year": 2025, "limit": 500},
}

# Raw-batch sources: publish the latest top500.normalized.json from scraper/raw/rankings/
RAW_BATCH_SOURCES = {
    "the": {"raw_root": ROOT / "scraper" / "raw" / "rankings" / "the", "out": RANKINGS / "the.json", "year": 2026},
    "arwu": {"raw_root": ROOT / "scraper" / "raw" / "rankings" / "arwu", "out": RANKINGS / "arwu.json", "year": 2025, "full_response": "api-response.body"},
}

COUNTRY_ALIASES = {
    "China (Mainland)": "China",
    "Hong Kong SAR": "Hong Kong",
    "Macau SAR": "Macau",
    "Türkiye": "Turkey",
    "U.S.": "United States",
    "USA": "United States",
    "U.K.": "United Kingdom",
}

REQUIRED_REQUIREMENT_KEYS = ("gpa", "ielts", "toefl", "language", "academic")
LOW_SIGNAL_UNVERIFIED_MATERIALS = {"bachelor", "gre"}

ADMISSION_PROGRAM_TITLE = re.compile(
    r"^admission to the master'?s programme in\s+(.+)$",
    re.I,
)

MATERIAL_ALIASES = {
    "cv": "CV",
    "curriculum vitae": "CV",
    "transcript": "Transcript",
    "bachelor transcript": "Transcript",
    "transcript of records": "Transcript",
    "degree": "Degree certificate",
    "degree certificate": "Degree certificate",
    "bachelor degree": "Degree certificate",
    "recommendation": "Recommendation letter",
    "recommendation letter": "Recommendation letter",
    "recommendation letters": "Recommendation letter",
    "letter of recommendation": "Recommendation letter",
    "reference letter": "Recommendation letter",
    "2 references": "Recommendation letter",
    "2 recommendation letters": "Recommendation letter",
    "two recommendation letters": "Recommendation letter",
    "motivation letter": "Motivation letter",
    "letter of motivation": "Motivation letter",
    "statement of purpose": "Motivation letter",
    "project essay": "Motivation letter",
    "english proof": "English proof",
    "english proof (b2)": "English proof",
    "english proof (b2/c1)": "English proof",
    "english proof (c1)": "English proof",
    "english certificate (c1)": "English proof",
    "english certificate (b2/c1)": "English proof",
    "english/french proof": "Language proof",
    "language certificate": "Language proof",
    "application form": "Application form",
    "online application": "Application form",
    "passport": "Passport",
    "portfolio": "Portfolio",
    "course descriptions": "Course descriptions",
    "gre": "GRE",
}


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalized_country(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip())
    return COUNTRY_ALIASES.get(value, value)


def normalized_name(value: str) -> str:
    text = html.unescape(value or "")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ").replace("--", " ")
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text)
    text = re.sub(r"\s+-\s+(?:china|mainland china)$", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\b(the|of|university|universite|universitat|universidad|institute|technology|"
                  r"technische|technical|royal|school|college)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_ranking(source: str, cfg: dict) -> tuple[list[dict], dict]:
    raw = load_json(cfg["raw"], [])
    report = {
        "inputRows": len(raw),
        "outputRows": 0,
        "droppedRows": 0,
        "excludedMainlandChina": 0,
        "duplicateIds": 0,
        "nonAsciiIds": 0,
        "duplicateRanks": {},
        "countryAliasesApplied": Counter(),
        "scoreMonotonicWarnings": 0,
    }
    best: dict[str, dict] = {}
    dropped = 0
    excluded_china = 0
    aliases = report["countryAliasesApplied"]

    for row in raw:
        name = html.unescape(re.sub(r"<[^>]+>", "", str(row.get("name") or ""))).strip()
        rank = first_int(row.get("rank") or row.get("rank_display"))
        if not name or not rank or rank <= 0:
            dropped += 1
            continue
        country_raw = re.sub(r"\s+", " ", str(row.get("country") or row.get("location") or "").strip())
        country = normalized_country(country_raw)
        if country != country_raw:
            aliases[f"{country_raw} -> {country}"] += 1
        # NOTE: Mainland-China schools are KEPT in ranking data per product spec
        # ("保留历史本地状态和排名"). They are only excluded from crawl queues,
        # not from the rankings themselves.
        score = None
        try:
            value = row.get("score") if "score" in row else row.get("overall_score")
            if value not in (None, "", "N/A", "-"):
                parsed = float(value)
                score = parsed if 0 <= parsed <= 100 else None
        except (TypeError, ValueError):
            score = None
        item = {
            "rank": rank,
            "universityId": slug(name),
            "name": name,
            "country": country,
            "score": score,
            "year": cfg["year"],
        }
        current = best.get(item["universityId"])
        if current is None or item["rank"] < current["rank"]:
            best[item["universityId"]] = item

    report["duplicateIds"] = len(raw) - dropped - len(best)
    items = top_n(list(best.values()), n=cfg["limit"])
    prev_rank = None
    prev_score = None
    for item in items:
        if prev_rank is not None and item["score"] is not None and prev_score is not None:
            if item["rank"] > prev_rank and item["score"] > prev_score:
                report["scoreMonotonicWarnings"] += 1
        prev_rank = item["rank"]
        if item["score"] is not None:
            prev_score = item["score"]
    rank_counts = Counter(item["rank"] for item in items)
    report["duplicateRanks"] = {str(k): v for k, v in rank_counts.items() if v > 1}
    report["nonAsciiIds"] = sum(1 for item in items if not item["universityId"].isascii())
    report["droppedRows"] = dropped
    report["excludedMainlandChina"] = excluded_china
    report["outputRows"] = len(items)
    report["countryAliasesApplied"] = dict(aliases)
    write_json(cfg["out"], items)
    return items, report


def publish_raw_batch(source: str, cfg: dict) -> tuple[list[dict], dict]:
    """Publish the latest raw-batch to the frontend rankings dir.

    Reads from scraper/raw/rankings/{source}/year=YYYY/captured-at=*/.
    For sources with a ``full_response`` file (e.g. ARWU api-response.body),
    parses the full untruncated response so we can fill 500 slots after
    excluding mainland-China schools.  Otherwise reads top500.normalized.json.
    Normalises to the 6-field frontend schema, excludes mainland-China schools,
    and writes the result to cfg["out"].
    """
    raw_root = cfg["raw_root"]
    year = cfg["year"]
    year_dir = raw_root / f"year={year}"
    report = {"inputRows": 0, "outputRows": 0, "excludedMainlandChina": 0, "batchDir": ""}

    if not year_dir.exists():
        print(f"  [publish] {source}: no raw batch at {year_dir}, skipping")
        return [], report

    batch_dirs = sorted([d for d in year_dir.iterdir() if d.is_dir() and d.name.startswith("captured-at=")])
    if not batch_dirs:
        print(f"  [publish] {source}: no batch dir under {year_dir}, skipping")
        return [], report

    batch_dir = batch_dirs[-1]
    report["batchDir"] = batch_dir.name

    raw_rows: list[dict] = []
    full_resp_name = cfg.get("full_response")
    if full_resp_name and (batch_dir / full_resp_name).exists():
        # Parse full untruncated response (ARWU JSON API)
        body = (batch_dir / full_resp_name).read_bytes()
        import gzip as _gzip
        if body[:2] == _gzip.GZIP_MAGIC if hasattr(_gzip, 'GZIP_MAGIC') else body[:2] == b'\x1f\x8b':
            body = _gzip.decompress(body)
        payload = json.loads(body.decode("utf-8"))
        api_rows = payload.get("data", {}).get("rankings", [])
        report["inputRows"] = len(api_rows)
        for row in api_rows:
            name = html.unescape(str(row.get("univNameEn") or "")).strip()
            if not name:
                continue
            rank_display = str(row.get("ranking") or "")
            rank = first_int(rank_display)
            if not rank:
                continue
            country = normalized_country(str(row.get("region") or ""))
            # NOTE: Mainland-China schools are KEPT in ranking data per product spec.
            score = None
            try:
                val = row.get("score")
                if val not in (None, "", "N/A", "-"):
                    parsed = float(val)
                    score = parsed if 0 <= parsed <= 100 else None
            except (TypeError, ValueError):
                score = None
            raw_rows.append({
                "rank": rank,
                "universityId": slug(name),
                "name": name,
                "country": country,
                "score": score,
                "year": year,
            })
    else:
        normalized_path = batch_dir / "top500.normalized.json"
        if not normalized_path.exists():
            print(f"  [publish] {source}: no normalized data in {batch_dir.name}, skipping")
            return [], report
        raw_rows = json.loads(normalized_path.read_text(encoding="utf-8-sig"))
        report["inputRows"] = len(raw_rows)
        # Re-normalize universityId with the fixed slug and exclude China
        filtered: list[dict] = []
        for row in raw_rows:
            name = html.unescape(str(row.get("name") or "")).strip()
            rank = first_int(row.get("rank"))
            if not name or not rank:
                continue
            country = normalized_country(str(row.get("country") or ""))
            # NOTE: Mainland-China schools are KEPT in ranking data per product spec.
            score = None
            try:
                val = row.get("score")
                if val not in (None, "", "N/A", "-"):
                    parsed = float(val)
                    score = parsed if 0 <= parsed <= 100 else None
            except (TypeError, ValueError):
                score = None
            filtered.append({
                "rank": rank,
                "universityId": slug(name),
                "name": name,
                "country": country,
                "score": score,
                "year": year,
            })
        raw_rows = filtered

    # Sort by rank and take top 500
    raw_rows.sort(key=lambda r: (r["rank"] or 99999))
    items = raw_rows[:500]
    report["outputRows"] = len(items)
    write_json(cfg["out"], items)
    return items, report


def clean_csrankings() -> tuple[list[dict], dict]:
    union = load_json(ROOT / "_csr_global_union.json", [])
    existing = load_json(RANKINGS / "csrankings.json", [])
    existing_by_name = {row.get("name"): row for row in existing}
    # Stable country map cached from CS Rankings GitHub institutions/countries CSV.
    # This avoids a re-entrancy bug where the already-cleaned csrankings.json
    # (China excluded) can no longer supply country info for China schools on a
    # second run, letting them slip back in with country="".
    csr_country_map = load_json(ROOT / "_csr_country_map.json", {})
    report = {"inputRows": len(union), "outputRows": 0, "duplicateNames": 0, "missingCountry": 0, "excludedMainlandChina": 0}
    by_name: dict[str, dict] = {}
    excluded_china = 0

    for row in union:
        name = html.unescape(str(row.get("name") or "")).strip()
        if not name:
            continue
        try:
            adj = float(row.get("adj"))
            pubs = int(row.get("pubs"))
        except (TypeError, ValueError):
            continue
        prior = existing_by_name.get(name, {})
        country = normalized_country(prior.get("country") or csr_country_map.get(name) or "")
        # NOTE: Mainland-China schools are KEPT in ranking data per product spec.
        current = by_name.get(name)
        if current is None or adj > current["score"]:
            by_name[name] = {
                "rank": 0,
                "universityId": slug(name),
                "name": name,
                "country": country,
                "score": adj,
                "year": 2026,
                "_pubs": pubs,
            }

    rows = sorted(by_name.values(), key=lambda item: (-item["score"], -item["_pubs"], item["name"]))
    last_score = None
    current_rank = 0
    for index, row in enumerate(rows, 1):
        if row["score"] != last_score:
            current_rank = index
            last_score = row["score"]
        row["rank"] = current_rank
        row.pop("_pubs", None)

    report["duplicateNames"] = len(union) - len(by_name)
    report["missingCountry"] = sum(1 for row in rows if not row["country"])
    report["excludedMainlandChina"] = excluded_china
    # Truncate to top 500 to match the four-ranking scope
    rows = rows[:500]
    report["outputRows"] = len(rows)
    write_json(RANKINGS / "csrankings.json", rows)
    return rows, report


def source_url_is_valid(url: str) -> bool:
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def norm_program_key(value: str) -> str:
    return normalized_name(value)


def clean_program_title(value: str) -> str:
    title = re.sub(r"\s+", " ", (value or "").strip())
    match = ADMISSION_PROGRAM_TITLE.match(title)
    if match:
        return match.group(1).strip()
    return title


def canonical_material(value: str, verified: bool) -> str | None:
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if not raw:
        return None
    key = raw.lower()
    if not verified and key in LOW_SIGNAL_UNVERIFIED_MATERIALS:
        return None
    return MATERIAL_ALIASES.get(key, raw)


def clean_requirements(value) -> dict:
    source = value if isinstance(value, dict) else {}
    out = {}
    for key in REQUIRED_REQUIREMENT_KEYS:
        raw = source.get(key)
        if raw is None:
            out[key] = None
            continue
        text = re.sub(r"\s+", " ", str(raw).strip())
        out[key] = text or None
    return out


def program_signal_score(record: dict) -> tuple[int, int, int, int]:
    requirements = record.get("requirements") or {}
    return (
        1 if record.get("verified") else 0,
        len(record.get("deadlines") or []),
        sum(1 for key in REQUIRED_REQUIREMENT_KEYS if requirements.get(key)),
        len(record.get("materials") or []),
    )


def make_program_id(record: dict, used: set[str]) -> str:
    base = record.get("id") or f"{record['universityId']}_{slug(record.get('subject') or 'general')}_{slug(record['program'])}"
    base = re.sub(r"_+", "_", base).strip("_") or "program"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def clean_programs() -> tuple[list[dict], dict]:
    programs = load_json(DATA / "programs.json", [])
    universities = load_json(DATA / "universities.json", {})
    report = {
        "inputRows": len(programs),
        "outputRows": 0,
        "droppedRows": Counter(),
        "dedupedRows": 0,
        "deadlineRowsBefore": sum(1 for row in programs if row.get("deadlines")),
        "deadlineRowsAfter": 0,
        "deadlineValuesBefore": sum(len(row.get("deadlines") or []) for row in programs),
        "deadlineValuesAfter": 0,
        "materialsRemoved": Counter(),
        "orphanUniversityIds": Counter(),
    }

    selected: dict[tuple[str, str], dict] = {}
    deduped = 0
    for row in programs:
        uid = (row.get("universityId") or "").strip()
        title = clean_program_title(row.get("program") or "")
        source_url = (row.get("sourceUrl") or "").strip()
        verified = bool(row.get("verified"))
        if not uid or not title:
            report["droppedRows"]["missing-university-or-program"] += 1
            continue
        if uid not in universities:
            report["orphanUniversityIds"][uid] += 1
        if not source_url_is_valid(source_url) or denied_source(source_url):
            report["droppedRows"]["invalid-or-denied-source"] += 1
            continue
        reason = non_program_reason_strict(title, source_url)
        if reason and not verified:
            report["droppedRows"][reason] += 1
            continue

        subject = re.sub(r"\s+", " ", (row.get("subject") or "General").strip()) or "General"
        if subject == "General":
            subject = infer_subject(title)
        deadlines = normalize_deadlines(row.get("deadlines") or [])
        requirements = clean_requirements(row.get("requirements") or {})
        materials = []
        seen_materials = set()
        for item in row.get("materials") or []:
            raw_key = re.sub(r"\s+", " ", str(item or "").strip()).lower()
            cleaned = canonical_material(item, verified)
            if cleaned is None:
                report["materialsRemoved"][raw_key or "<empty>"] += 1
                continue
            if cleaned.lower() in seen_materials:
                continue
            seen_materials.add(cleaned.lower())
            materials.append(cleaned)

        cleaned_row = {
            "id": row.get("id") or "",
            "universityId": uid,
            "subject": subject,
            "dept": re.sub(r"\s+", " ", (row.get("dept") or "").strip()),
            "program": title,
            "deadlines": deadlines,
            "materials": materials,
            "requirements": requirements,
            "sourceUrl": source_url,
            "verified": verified,
            "updatedAt": (row.get("updatedAt") or "").strip(),
        }
        for optional in ("deadlineReviewed", "evidenceUrls", "fieldSources", "applicationWindows"):
            if optional in row:
                cleaned_row[optional] = normalize_deadlines(row[optional]) if optional == "applicationWindows" else row[optional]

        key = (uid, norm_program_key(title))
        current = selected.get(key)
        if current is None:
            selected[key] = cleaned_row
            continue
        deduped += 1
        if program_signal_score(cleaned_row) > program_signal_score(current):
            selected[key] = cleaned_row

    used_ids: set[str] = set()
    cleaned = []
    for row in selected.values():
        row["id"] = make_program_id(row, used_ids)
        cleaned.append(row)
    cleaned.sort(key=lambda row: (not row.get("verified", False), row["universityId"], row["subject"], row["program"]))

    report["dedupedRows"] = deduped
    report["outputRows"] = len(cleaned)
    report["deadlineRowsAfter"] = sum(1 for row in cleaned if row.get("deadlines"))
    report["deadlineValuesAfter"] = sum(len(row.get("deadlines") or []) for row in cleaned)
    report["droppedRows"] = dict(report["droppedRows"])
    report["materialsRemoved"] = dict(report["materialsRemoved"])
    report["orphanUniversityIds"] = dict(report["orphanUniversityIds"])
    write_json(DATA / "programs.json", cleaned)
    return cleaned, report


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-programs", action="store_true", help="Only clean ranking datasets")
    args = parser.parse_args()

    report = {"generatedAt": date.today().isoformat(), "rankings": {}, "programs": None}
    for source, cfg in RANKING_SOURCES.items():
        _items, source_report = clean_ranking(source, cfg)
        report["rankings"][source] = source_report
    for source, cfg in RAW_BATCH_SOURCES.items():
        _items, source_report = publish_raw_batch(source, cfg)
        report["rankings"][source] = source_report
    _csr, csr_report = clean_csrankings()
    report["rankings"]["csrankings"] = csr_report
    if not args.skip_programs:
        _programs, programs_report = clean_programs()
        report["programs"] = programs_report

    REPORT_PATH.write_bytes(json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    print(f"[clean-data] report -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
