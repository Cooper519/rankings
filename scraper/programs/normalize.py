"""Deadline åŽå¤„ç†:è§£æžä¸º ISOã€è¿‡æ»¤è¿‡åŽ»æ—¥æœŸã€ä¿ç•™/è§„èŒƒåŒ– Non-EU/EU è½®æ¬¡æ ‡ç­¾ã€‚

è¾“å…¥ deadlines: [{round, date}]  (date ä¸ºåŽŸå§‹å­—ç¬¦ä¸²,å¦‚ "9 June 2026" / "2026-06-09")
è¾“å‡º deadlines: [{round, date}]  (date ä¸º ISO YYYY-MM-DD æˆ– YYYY-MM;è¿‡æ»¤æŽ‰ä»Šå¤©ä¹‹å‰çš„)
"""
from __future__ import annotations
import re
from datetime import date

TODAY = date.today()

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_D1 = re.compile(r"\b(\d{1,2})\s+([A-Za-z]+)\s+20(\d{2})\b")          # 9 June 2026
_D2 = re.compile(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+20(\d{2})\b")       # June 9, 2026
_D3 = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")                   # 2026-06-09
_DM = re.compile(r"\b(20\d{2})-(\d{2})\b")                          # 2026-06


def _parse(raw: str):
    raw = (raw or "").strip()
    m = _D3.search(raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _DM.search(raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
    m = _D1.search(raw)
    if m:
        mon = MONTHS.get(m.group(2).lower())
        if mon:
            try:
                return date(2000 + int(m.group(3)), mon, int(m.group(1)))
            except ValueError:
                return None
    m = _D2.search(raw)
    if m:
        mon = MONTHS.get(m.group(1).lower())
        if mon:
            try:
                return date(2000 + int(m.group(3)), mon, int(m.group(2)))
            except ValueError:
                return None
    return None


def normalize_deadlines(deadlines: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for d in deadlines or []:
        round_ = (d.get("round") or "Application").strip() or "Application"
        dt = _parse(d.get("date") or "")
        if dt is None:
            continue
        if dt < TODAY:           # è¿‡æ»¤è¿‡åŽ»æ—¥æœŸ
            continue
        iso = dt.isoformat()
        key = (round_, iso)
        if key in seen:
            continue
        seen.add(key)
        group = d.get("applicantGroup") or d.get("applicant_group")
        if group not in {"EU", "Non-EU", "All", "Unknown"}:
            label = round_.lower()
            compact = label.replace(" ", "").replace("-", "")
            # Non-EU must be tested before EU: the substring "eu" appears inside
            # "non-eu", so a naive EU-first check would mislabel Non-EU rounds.
            if (
                "noneu" in compact
                or "non-eu" in label
                or "international" in label
                or "visa" in label
                or "residence" in label
            ):
                group = "Non-EU"
            elif (
                label.startswith("eu")
                or " eu" in label
                or "/eu" in label
                or "eea" in label
                or "no visa" in label
                or "no residence" in label
            ):
                group = "EU"
            else:
                group = "Unknown"
        out.append({"round": round_, "date": iso, "applicantGroup": group})
    out.sort(key=lambda x: x["date"])
    return out
