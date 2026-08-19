"""Import browser-rendered programme pages into hash-verified raw manifests."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from scraper.programs.browser_recovery_raw import persist_browser_capture


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = (
    ROOT / "scraper" / "playwright" / "_top350_engineering_browser_recovered_raw_v1"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("browser handoff must be a JSON object")
    return value


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".tmp-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def import_handoff(
    handoff: Dict[str, Any],
    output_root: Path,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    university_id = str(handoff.get("universityId") or "").strip()
    if not university_id:
        raise ValueError("handoff universityId is required")
    pages = handoff.get("pages")
    if not isinstance(pages, list):
        raise ValueError("handoff pages must be a list")

    university_root = output_root / university_id
    capture_root = university_root / "browser-pages"
    program_candidates: Dict[str, Any] = {}
    page_records: Dict[str, Any] = {}
    statuses = Counter()
    stopped_reason = None

    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise ValueError("handoff page %d must be an object" % index)
        requested_url = str(page.get("requestedUrl") or "").strip()
        final_url = str(page.get("finalUrl") or requested_url).strip()
        title = str(page.get("title") or "")
        dom_file = Path(str(page.get("domFile") or ""))
        if not requested_url or not final_url or not dom_file.is_file():
            raise ValueError("handoff page %d has invalid URL or domFile" % index)
        dom = dom_file.read_bytes()
        capture = persist_browser_capture(
            capture_root,
            kind=str(page.get("kind") or "program"),
            requested_url=requested_url,
            final_url=final_url,
            title=title,
            dom=dom,
            status=str(page.get("status") or "captured"),
            captcha_detected=page.get("captchaDetected"),
            captured_at=page.get("capturedAt"),
            error=page.get("error"),
        )
        statuses[capture["status"]] += 1
        record = {
            "kind": str(page.get("kind") or "program"),
            "status": capture["status"],
            "captureMethod": capture["captureType"],
            "documentTitle": capture["title"],
            "candidateText": page.get("candidateText"),
            "sourceUrl": page.get("sourceUrl"),
            "browserManifestFile": capture["manifestFile"],
            "rawFile": capture["rawFile"],
            "bytes": capture["bytes"],
            "sha256": capture["sha256"],
            "captchaDetected": capture["captchaDetected"],
            "capturedAt": capture["capturedAt"],
        }
        page_records[final_url] = record
        if capture["status"] == "captured":
            program_candidates[final_url] = {
                "text": page.get("candidateText") or title,
                "sourceUrl": page.get("sourceUrl"),
                "captureMethod": capture["captureType"],
                "browserManifestFile": capture["manifestFile"],
                "sha256": capture["sha256"],
            }
        if capture["captchaDetected"]:
            stopped_reason = "captcha-detected"
            break

    processed = sum(statuses.values())
    status = "raw-complete" if processed == len(pages) and not stopped_reason else "raw-partial"
    manifest = {
        "schemaVersion": 1,
        "generatedAt": generated_at or utc_now(),
        "universityId": university_id,
        "universityName": handoff.get("universityName"),
        "country": handoff.get("country"),
        "officialDomains": handoff.get("officialDomains") or [],
        "indexUrl": handoff.get("indexUrl"),
        "discoveryStrategy": "browser-rendered-program-handoff",
        "status": status,
        "discovery": {
            "status": "complete" if status == "raw-complete" else "partial",
            "programCandidates": program_candidates,
            "stoppedReason": stopped_reason,
        },
        "pages": page_records,
        "counts": {
            "requested": len(pages),
            "processed": processed,
            "programCandidates": len(program_candidates),
            "statusCounts": dict(sorted(statuses.items())),
        },
        "policy": {
            "rawFirst": True,
            "captchaPolicy": "stop",
            "applicationDetailsExtracted": False,
        },
    }
    atomic_write_json(university_root / "manifest.json", manifest)
    return manifest


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    result = import_handoff(load_json(args.handoff), args.output_root)
    print(json.dumps(result["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
