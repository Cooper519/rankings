#!/usr/bin/env python3
"""Integrate recovery v5 discovered URLs into feature2_coverage.json.

Also adds any schools from the capture report that are missing from
feature2_coverage, and updates summary statistics.
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2] if __name__ != '__main__' or 'scraper' in str(Path(__file__).resolve()) else Path.cwd()
if not (ROOT / 'frontend').exists():
    ROOT = Path(__file__).resolve().parents[1]

CAPTURE = ROOT / 'frontend' / 'public' / 'data' / 'top500_capture_report.json'
FEATURE2 = ROOT / 'frontend' / 'public' / 'data' / 'feature2_coverage.json'
RECOVERY = ROOT / 'scraper' / 'playwright' / 'recovery_v5' / 'merged_results.json'

# URL types that count as "feature2" coverage (official application-related URLs)
FEATURE2_TYPES = {
    'master-catalog', 'engineering-cs-catalog', 'program-page',
    'admission-requirements', 'application-deadline', 'required-documents',
    'language-requirements'
}

def is_official_url(url):
    """Check if URL is an official HTTP/HTTPS URL (not aggregator)."""
    if not url or not url.startswith('http'):
        return False
    return True

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    capture = load_json(CAPTURE)
    feature2 = load_json(FEATURE2)
    recovery = load_json(RECOVERY)

    # Build recovery lookup
    recovery_by_id = {}
    for r in recovery.get('results', []):
        recovery_by_id[r['canonicalId']] = r

    # Build feature2 lookup
    f2_by_id = {s['canonicalId']: s for s in feature2['schools']}

    # Step 1: Integrate recovery v5 URLs into existing feature2 schools
    updated_count = 0
    for cid, rec in recovery_by_id.items():
        if cid not in f2_by_id:
            continue
        school = f2_by_id[cid]
        discovered = rec.get('discoveredUrls', [])
        # Filter to feature2-relevant URL types and official URLs
        new_urls = set(school.get('urls', []))
        for du in discovered:
            url = du.get('url', '')
            utype = du.get('type', '')
            if is_official_url(url) and utype in FEATURE2_TYPES:
                new_urls.add(url)
        if new_urls:
            school['urls'] = sorted(new_urls)
            school['urlCount'] = len(new_urls)
            school['coverageStatus'] = 'covered'
            updated_count += 1

    # Step 2: Add missing schools from capture report
    cap_by_id = {s['canonicalId']: s for s in capture['schools']}
    added_count = 0
    for cid, cap_school in cap_by_id.items():
        if cid in f2_by_id:
            continue
        # Build a feature2 record for this school
        ranks = cap_school.get('ranks', {})
        selections = []
        for source, info in ranks.items():
            selections.append({
                'source': source,
                'rowIndex': max(0, (info.get('rank', 500) - 1)),
                'displayedRank': info.get('rank'),
                'year': info.get('year'),
            })
        selections.sort(key=lambda x: x.get('displayedRank', 9999))

        # Check if recovery v5 has URLs for this school
        rec = recovery_by_id.get(cid)
        urls = []
        if rec:
            for du in rec.get('discoveredUrls', []):
                url = du.get('url', '')
                utype = du.get('type', '')
                if is_official_url(url) and utype in FEATURE2_TYPES:
                    urls.append(url)
        urls = sorted(set(urls))

        new_school = {
            'canonicalId': cid,
            'name': cap_school['name'],
            'country': cap_school.get('country', ''),
            'rankingSources': cap_school.get('rankingSources', []),
            'selections': selections,
            'coverageStatus': 'covered' if urls else 'missing',
            'urlCount': len(urls),
            'urls': urls,
            'rankingUniversityIds': [cid],
        }
        feature2['schools'].append(new_school)
        f2_by_id[cid] = new_school
        added_count += 1

    # Step 3: Update summary
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

    save_json(FEATURE2, feature2)
    print(f'Updated {updated_count} existing schools with recovery v5 URLs')
    print(f'Added {added_count} missing schools to feature2_coverage')
    print(f'Summary: {len(all_schools)} schools, {len(covered)} covered, {len(missing)} missing')
    print(f'Coverage: {feature2["summary"]["coveragePercent"]}%')
    print(f'Official URL assignments: {feature2["summary"]["officialUrlAssignments"]}')
    print(f'Unique official URLs: {feature2["summary"]["uniqueOfficialUrls"]}')

if __name__ == '__main__':
    main()
