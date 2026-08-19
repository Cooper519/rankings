#!/usr/bin/env python3
"""Integrate recovery v6 discovered URLs into feature2_coverage.json and update capture report."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1] if 'scraper' in str(Path(__file__).resolve()) else Path.cwd()
if not (ROOT / 'frontend').exists():
    ROOT = Path(__file__).resolve().parent.parent

CAPTURE = ROOT / 'frontend' / 'public' / 'data' / 'top500_capture_report.json'
FEATURE2 = ROOT / 'frontend' / 'public' / 'data' / 'feature2_coverage.json'
RECOVERY_V6_DIR = ROOT / 'scraper' / 'playwright' / 'recovery_v6'

FEATURE2_TYPES = {
    'master-catalog', 'engineering-cs-catalog', 'program-page',
    'admission-requirements', 'application-deadline', 'required-documents',
    'language-requirements'
}

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Load all v6 batch results
v6_results = []
if RECOVERY_V6_DIR.exists():
    for f in sorted(os.listdir(RECOVERY_V6_DIR)):
        if f.startswith('batch_') and f.endswith('.json'):
            d = load_json(RECOVERY_V6_DIR / f)
            v6_results.extend(d.get('results', []))

print(f'Loaded {len(v6_results)} v6 results')

# Build v6 lookup
v6_by_id = {}
for r in v6_results:
    v6_by_id[r['canonicalId']] = r

# Load data
feature2 = load_json(FEATURE2)
capture = load_json(CAPTURE)

f2_by_id = {s['canonicalId']: s for s in feature2['schools']}
cap_by_id = {s['canonicalId']: s for s in capture['schools']}

# Step 1: Integrate v6 URLs into feature2_coverage
updated_f2 = 0
newly_covered = 0
for cid, rec in v6_by_id.items():
    if cid not in f2_by_id:
        continue
    school = f2_by_id[cid]
    discovered = rec.get('discoveredUrls', [])
    new_urls = set(school.get('urls', []))
    for du in discovered:
        url = du.get('url', '')
        utype = du.get('type', '')
        if url and url.startswith('http') and utype in FEATURE2_TYPES:
            new_urls.add(url)
    if new_urls:
        was_missing = school.get('coverageStatus') == 'missing'
        school['urls'] = sorted(new_urls)
        school['urlCount'] = len(new_urls)
        school['coverageStatus'] = 'covered'
        updated_f2 += 1
        if was_missing:
            newly_covered += 1

# Step 2: Update capture report statuses for v6 recovered schools
status_changes = {}
for cid, rec in v6_by_id.items():
    if cid not in cap_by_id:
        continue
    cap_school = cap_by_id[cid]
    discovered = rec.get('discoveredUrls', [])
    feature2_urls = [du for du in discovered if du.get('type') in FEATURE2_TYPES]

    if len(feature2_urls) > 0 and cap_school['captureStatus'] in ('needs-review', 'blocked', 'checked-no-program'):
        old_status = cap_school['captureStatus']
        cap_school['captureStatus'] = 'captured'
        cap_school['goalCategory'] = 'recovery-v6-captured'
        status_changes[old_status] = status_changes.get(old_status, 0) + 1

        # Add recoveryV6 field
        cap_school['recoveryV6'] = {
            'discoveredUrls': len(discovered),
            'visitedPages': len(rec.get('visited', [])),
            'errors': rec.get('errors', []),
            'urlTypes': {},
        }
        for du in discovered:
            t = du.get('type', 'unknown')
            cap_school['recoveryV6']['urlTypes'][t] = cap_school['recoveryV6']['urlTypes'].get(t, 0) + 1
    elif len(feature2_urls) > 0 and cap_school['captureStatus'] == 'captured':
        # Already captured, just add recoveryV6 info
        cap_school['recoveryV6'] = {
            'discoveredUrls': len(discovered),
            'visitedPages': len(rec.get('visited', [])),
            'errors': rec.get('errors', []),
            'urlTypes': {},
        }
        for du in discovered:
            t = du.get('type', 'unknown')
            cap_school['recoveryV6']['urlTypes'][t] = cap_school['recoveryV6']['urlTypes'].get(t, 0) + 1

# Step 3: Update capture report status counts
status_counts = {}
for s in capture['schools']:
    st = s['captureStatus']
    status_counts[st] = status_counts.get(st, 0) + 1
capture['summary']['statusCounts'] = status_counts

# Update raw counts from v6
total_v6_raw = 0
v6_raw_dir = ROOT / 'scraper' / 'raw' / 'official-discovery' / 'recovery-v6'
if v6_raw_dir.exists():
    for d in os.listdir(v6_raw_dir):
        school_dir = v6_raw_dir / d
        if school_dir.is_dir():
            total_v6_raw += len([f for f in os.listdir(school_dir) if f.endswith('.html')])

capture['summary']['rawProgramCaptured'] = capture['summary'].get('rawProgramCaptured', 0) + total_v6_raw
capture['summary']['rawProgramCandidates'] = capture['summary'].get('rawProgramCandidates', 0) + total_v6_raw

# Add recoveryV6 summary
capture['summary']['recoveryV6'] = {
    'totalProcessed': len(v6_results),
    'recovered': len([r for r in v6_results if len([u for u in r.get('discoveredUrls', []) if u.get('type') in FEATURE2_TYPES]) > 0]),
    'stillNoUrls': len([r for r in v6_results if len(r.get('discoveredUrls', [])) == 0]),
    'totalDiscoveredUrls': sum(len(r.get('discoveredUrls', [])) for r in v6_results),
    'totalVisitedPages': sum(len(r.get('visited', [])) for r in v6_results),
    'totalRawFiles': total_v6_raw,
}

# Step 4: Update feature2 summary
all_schools = feature2['schools']
covered = [s for s in all_schools if s['coverageStatus'] == 'covered']
missing = [s for s in all_schools if s['coverageStatus'] == 'missing']
all_urls = set()
for s in all_schools:
    for u in s.get('urls', []):
        all_urls.add(u)

feature2['summary'] = {
    'schools': len(all_schools),
    'coveredSchools': len(covered),
    'missingSchools': len(missing),
    'coveragePercent': round(len(covered) / len(all_schools) * 100, 1) if all_schools else 0,
    'recordsInFile': len(all_schools),
    'officialUrlAssignments': sum(s.get('urlCount', 0) for s in all_schools),
    'uniqueOfficialUrls': len(all_urls),
}
feature2['generatedAt'] = datetime.now(timezone.utc).isoformat()

# Save
save_json(FEATURE2, feature2)
save_json(CAPTURE, capture)

print(f'Feature2 updated: {updated_f2} schools modified, {newly_covered} newly covered')
print(f'Feature2 summary: {len(covered)} covered, {len(missing)} missing, {feature2["summary"]["coveragePercent"]}%')
print(f'Capture report status changes: {status_changes}')
print(f'New status counts: {status_counts}')
print(f'V6 raw files: {total_v6_raw}')
print(f'V6 summary: {capture["summary"]["recoveryV6"]}')
