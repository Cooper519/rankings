#!/usr/bin/env python3
"""Regenerate school lists from updated capture report."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if 'scraper' in str(Path(__file__).resolve()) else Path.cwd()
if not (ROOT / 'frontend').exists():
    ROOT = Path(__file__).resolve().parent.parent

CAPTURE = ROOT / 'frontend' / 'public' / 'data' / 'top500_capture_report.json'
OUT_DIR = ROOT / 'scraper' / 'playwright' / 'school_lists'
OUT_DIR.mkdir(parents=True, exist_ok=True)

capture = json.load(open(CAPTURE, encoding='utf-8'))

def min_rank(s):
    ranks = s.get('ranks', {})
    vals = [v.get('rank', 9999) for v in ranks.values()]
    return min(vals) if vals else 9999

categories = {
    'captured': lambda s: s['captureStatus'] == 'captured',
    'blocked': lambda s: s['captureStatus'] == 'blocked',
    'checked_no_program': lambda s: s['captureStatus'] == 'checked-no-program',
    'needs_review': lambda s: s['captureStatus'] == 'needs-review',
    'pending': lambda s: s['captureStatus'] not in ('captured', 'blocked', 'checked-no-program', 'needs-review'),
}

for cat_name, filter_fn in categories.items():
    schools = [s for s in capture['schools'] if filter_fn(s)]
    schools.sort(key=min_rank)

    # JSON
    json_data = {
        'category': cat_name,
        'count': len(schools),
        'schools': [{'canonicalId': s['canonicalId'], 'name': s['name'], 'country': s.get('country',''), 'bestRank': min_rank(s), 'captureStatus': s['captureStatus'], 'mainlandChina': s.get('mainlandChina', False)} for s in schools],
    }
    json.dump(json_data, open(OUT_DIR / f'{cat_name}.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    # CSV
    with open(OUT_DIR / f'{cat_name}.csv', 'w', encoding='utf-8') as f:
        f.write('canonicalId,name,country,bestRank,captureStatus,mainlandChina\n')
        for s in schools:
            f.write(f'"{s["canonicalId"]}","{s["name"]}","{s.get("country","")}",{min_rank(s)},{s["captureStatus"]},{s.get("mainlandChina",False)}\n')

    # TXT
    with open(OUT_DIR / f'{cat_name}.txt', 'w', encoding='utf-8') as f:
        for s in schools:
            f.write(f'{s["canonicalId"]} | {s["name"]} | {s.get("country","")} | rank={min_rank(s)} | {s["captureStatus"]}\n')

print(f'School lists regenerated:')
for cat_name, filter_fn in categories.items():
    count = sum(1 for s in capture['schools'] if filter_fn(s))
    print(f'  {cat_name}: {count}')

# Also generate a combined summary
summary = {
    'total': len(capture['schools']),
    'statusCounts': capture['summary']['statusCounts'],
    'recoveryV5': capture['summary'].get('recoveryV5', {}),
    'recoveryV6': capture['summary'].get('recoveryV6', {}),
}
json.dump(summary, open(OUT_DIR / 'summary.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'Summary: {summary["statusCounts"]}')
