"""Persist and account for browser-rendered raw recovery captures.

This module deliberately contains no browser automation.  Callers must stop
their recovery workflow when ``captchaDetected`` is true; the helpers only
preserve the rendered evidence and mark the queue item as blocked.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union


CAPTURE_TYPE = "browser-rendered-dom"
RESULT_STATUSES = {"captured", "blocked", "error"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CAPTCHA_RE = re.compile(
    r"(?:captcha\s+(?:challenge|verification|required)|"
    r"verify\s+(?:that\s+)?you(?:'|&#39;|&apos;)?re\s+human|"
    r"verify\s+you\s+are\s+(?:a\s+)?human|are\s+you\s+(?:a\s+)?human|"
    r"cf-chl-|challenges\.cloudflare\.com/turnstile)",
    re.IGNORECASE,
)
_CAPTCHA_WIDGET_RE = re.compile(r"(?:g-recaptcha|hcaptcha)", re.IGNORECASE)
_INVISIBLE_RECAPTCHA_RE = re.compile(
    r"(?:size(?:=|%3D)(?:&quot;|['\"])?invisible|"
    r"grecaptcha-badge[^>]*visibility\s*:\s*hidden)",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_captcha(dom: Union[str, bytes], title: str = "") -> bool:
    """Return whether rendered content contains a recognizable CAPTCHA gate."""
    if isinstance(dom, bytes):
        text = dom.decode("utf-8", errors="replace")
    elif isinstance(dom, str):
        text = dom
    else:
        raise TypeError("dom must be str or bytes")
    combined = "%s\n%s" % (title or "", text)
    if _CAPTCHA_RE.search(combined):
        return True
    if _CAPTCHA_WIDGET_RE.search(combined):
        return not bool(_INVISIBLE_RECAPTCHA_RE.search(combined))
    return False


def _safe_prefix(value: str) -> str:
    prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "page")).strip("_.")
    return prefix or "page"


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".tmp-", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write_bytes(path, data)


def _load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object: %s" % path)
    return value


def _raw_path_from_manifest(manifest_file: Path, manifest: Dict[str, Any]) -> Path:
    raw_value = manifest.get("rawFile")
    if not isinstance(raw_value, str) or not raw_value:
        raise ValueError("manifest rawFile must be a non-empty string")
    raw_path = Path(raw_value)
    if not raw_path.is_absolute():
        raw_path = manifest_file.parent / raw_path
    return raw_path


def verify_browser_capture(manifest_file: Union[str, Path]) -> Dict[str, Any]:
    """Load a browser manifest and verify its schema and raw DOM hash."""
    path = Path(manifest_file)
    manifest = _load_json(path)
    required = (
        "captureType", "requestedUrl", "finalUrl", "title", "capturedAt",
        "bytes", "sha256", "status", "captchaDetected", "rawFile",
    )
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ValueError("browser manifest missing fields: %s" % ", ".join(missing))
    if manifest["captureType"] != CAPTURE_TYPE:
        raise ValueError("unexpected captureType: %r" % manifest["captureType"])
    if manifest["status"] not in RESULT_STATUSES:
        raise ValueError("unexpected browser capture status: %r" % manifest["status"])
    if not isinstance(manifest["captchaDetected"], bool):
        raise ValueError("captchaDetected must be boolean")
    if manifest["captchaDetected"] and manifest["status"] != "blocked":
        raise ValueError("CAPTCHA captures must have blocked status")
    if not isinstance(manifest["requestedUrl"], str) or not manifest["requestedUrl"]:
        raise ValueError("requestedUrl must be a non-empty string")
    if not isinstance(manifest["finalUrl"], str) or not manifest["finalUrl"]:
        raise ValueError("finalUrl must be a non-empty string")
    if not isinstance(manifest["title"], str):
        raise ValueError("title must be a string")
    if not isinstance(manifest["capturedAt"], str) or not manifest["capturedAt"]:
        raise ValueError("capturedAt must be a non-empty string")
    if isinstance(manifest["bytes"], bool) or not isinstance(manifest["bytes"], int):
        raise ValueError("bytes must be an integer")
    digest = manifest["sha256"]
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ValueError("sha256 must be a lowercase hexadecimal SHA-256 digest")
    source_status = manifest.get("sourceStaticStatus")
    if source_status is not None and (
        isinstance(source_status, bool) or not isinstance(source_status, int)
    ):
        raise ValueError("sourceStaticStatus must be an integer when present")

    raw_path = _raw_path_from_manifest(path, manifest)
    try:
        raw = raw_path.read_bytes()
    except FileNotFoundError:
        raise ValueError("raw DOM file does not exist: %s" % raw_path)
    if len(raw) != manifest["bytes"]:
        raise ValueError("raw DOM byte count does not match manifest")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("raw DOM SHA-256 does not match manifest")
    return manifest


def persist_browser_capture(
    output_directory: Union[str, Path],
    kind: str,
    requested_url: str,
    final_url: str,
    title: str,
    dom: Union[str, bytes],
    status: str = "captured",
    source_static_status: Optional[int] = None,
    captcha_detected: Optional[bool] = None,
    captured_at: Optional[str] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomically persist rendered DOM and a hash-verified manifest.

    CAPTCHA detection is monotonic: an explicit false value cannot suppress a
    CAPTCHA marker found in the rendered content.  Such captures are always
    stored with ``blocked`` status so a caller cannot accidentally continue.
    """
    if status not in RESULT_STATUSES:
        raise ValueError("status must be captured, blocked, or error")
    if not isinstance(requested_url, str) or not requested_url:
        raise ValueError("requested_url must be a non-empty string")
    if not isinstance(final_url, str) or not final_url:
        raise ValueError("final_url must be a non-empty string")
    if not isinstance(title, str):
        raise TypeError("title must be a string")
    if source_static_status is not None and (
        isinstance(source_static_status, bool) or not isinstance(source_static_status, int)
    ):
        raise TypeError("source_static_status must be an integer when provided")
    if captcha_detected is not None and not isinstance(captcha_detected, bool):
        raise TypeError("captcha_detected must be boolean when provided")
    if isinstance(dom, str):
        raw = dom.encode("utf-8")
    elif isinstance(dom, bytes):
        raw = dom
    else:
        raise TypeError("dom must be str or bytes")

    found_captcha = detect_captcha(raw, title)
    captcha = bool(captcha_detected) or found_captcha
    effective_status = "blocked" if captcha else status
    digest = hashlib.sha256(raw).hexdigest()
    # The full digest remains authoritative in the manifest. A bounded digest
    # prefix keeps long canonical university IDs below Windows MAX_PATH.
    prefix = _safe_prefix(kind) + "_rendered_sha256=" + digest[:24]
    directory = Path(output_directory)
    raw_file = directory / (prefix + ".html")
    manifest_file = directory / (prefix + ".manifest.json")

    _atomic_write_bytes(raw_file, raw)
    written = raw_file.read_bytes()
    if len(written) != len(raw) or hashlib.sha256(written).hexdigest() != digest:
        raise IOError("raw DOM failed post-write hash verification: %s" % raw_file)

    manifest: Dict[str, Any] = {
        "schemaVersion": 1,
        "kind": kind,
        "captureType": CAPTURE_TYPE,
        "requestedUrl": requested_url,
        "finalUrl": final_url,
        "title": title,
        "capturedAt": captured_at or utc_now(),
        "bytes": len(raw),
        "sha256": digest,
        "rawFile": str(raw_file.resolve()),
        "status": effective_status,
        "captchaDetected": captcha,
    }
    if source_static_status is not None:
        manifest["sourceStaticStatus"] = source_static_status
    if error is not None:
        manifest["error"] = str(error)
    _atomic_write_json(manifest_file, manifest)
    verified = verify_browser_capture(manifest_file)
    return dict(verified, manifestFile=str(manifest_file.resolve()))


def update_queue_status(
    queue_file: Union[str, Path],
    university_id: str,
    url: str,
    kind: str,
    capture: Union[Dict[str, Any], str, Path],
) -> Dict[str, Any]:
    """Atomically apply a verified capture result to one recovery queue item."""
    queue_path = Path(queue_file)
    queue = _load_json(queue_path)
    items = queue.get("items")
    if not isinstance(items, list):
        raise ValueError("queue items must be a list")

    if isinstance(capture, (str, Path)):
        manifest_path = Path(capture)
        manifest = verify_browser_capture(manifest_path)
    elif isinstance(capture, dict):
        manifest_path_value = capture.get("manifestFile")
        if not isinstance(manifest_path_value, str) or not manifest_path_value:
            raise ValueError("capture dictionary must include manifestFile")
        manifest_path = Path(manifest_path_value)
        manifest = verify_browser_capture(manifest_path)
        for field in ("sha256", "status", "captchaDetected"):
            if capture.get(field) != manifest.get(field):
                raise ValueError("capture dictionary does not match manifest field %s" % field)
    else:
        raise TypeError("capture must be a manifest path or capture dictionary")

    matches = [
        item for item in items
        if isinstance(item, dict)
        and item.get("universityId") == university_id
        and item.get("url") == url
        and item.get("kind") == kind
    ]
    if not matches:
        raise KeyError("recovery queue item not found")
    if len(matches) != 1:
        raise ValueError("recovery queue key is not unique")
    item = matches[0]
    if manifest.get("requestedUrl") != url:
        raise ValueError("capture requestedUrl does not match queue item URL")

    item.update({
        "status": manifest["status"],
        "captchaDetected": manifest["captchaDetected"],
        "browserRawFile": manifest["rawFile"],
        "browserManifestFile": str(manifest_path.resolve()),
        "browserFinalUrl": manifest["finalUrl"],
        "browserTitle": manifest["title"],
        "browserCapturedAt": manifest["capturedAt"],
        "browserBytes": manifest["bytes"],
        "browserSha256": manifest["sha256"],
    })
    if manifest.get("error") is not None:
        item["error"] = manifest["error"]
    else:
        item.pop("error", None)

    status_counts: Dict[str, int] = {}
    kind_counts: Dict[str, int] = {}
    for queued_item in items:
        item_status = str(queued_item.get("status") or "pending")
        item_kind = str(queued_item.get("kind") or "other")
        status_counts[item_status] = status_counts.get(item_status, 0) + 1
        kind_counts[item_kind] = kind_counts.get(item_kind, 0) + 1
    summary = queue.setdefault("summary", {})
    summary["tasks"] = len(items)
    summary["uniqueKeys"] = len({
        (item.get("universityId"), item.get("url"), item.get("kind"))
        for item in items if isinstance(item, dict)
    })
    summary["kindCounts"] = kind_counts
    summary["statusCounts"] = status_counts
    queue["updatedAt"] = utc_now()
    _atomic_write_json(queue_path, queue)
    return item.copy()


# Explicit aliases keep call sites readable without introducing a class layer.
save_browser_capture = persist_browser_capture
verify_capture_manifest = verify_browser_capture
update_queue_item = update_queue_status
