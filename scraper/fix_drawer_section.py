"""Remove the official project directory section from UniversityDrawer.tsx."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] if 'scraper' in str(Path(__file__).resolve()) else Path.cwd()
if not (ROOT / 'frontend').exists():
    ROOT = Path(__file__).resolve().parent.parent

p = ROOT / 'frontend' / 'src' / 'components' / 'UniversityDrawer.tsx'
content = p.read_text(encoding='utf-8')

# Find and remove the section between "官方项目目录" sub-header and "硕士项目与申请要求" sub-header
# Use regex to match the entire block
pattern = r'\n              <div className="sub-h">官方项目目录 <span className="line" /></div>\n.*?\n              <div className="sub-h">硕士项目与申请要求 <span className="line" /></div>'
replacement = '\n              <div className="sub-h">硕士项目与申请要求 <span className="line" /></div>'

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
if new_content == content:
    print("WARNING: Pattern not matched, trying alternative approach")
    # Find line numbers
    lines = content.split('\n')
    start = None
    end = None
    for i, line in enumerate(lines):
        if '官方项目目录' in line and 'sub-h' in line:
            start = i
        if '硕士项目与申请要求' in line and 'sub-h' in line and start is not None:
            end = i
            break
    if start is not None and end is not None:
        # Remove lines from start to end (exclusive)
        lines = lines[:start] + lines[end:]
        new_content = '\n'.join(lines)
        print(f"Removed lines {start+1} to {end}")
    else:
        print(f"Could not find section. start={start}, end={end}")
else:
    print("Section removed via regex")

# Also remove unused canonicalId variable if it's not used elsewhere
# Check if canonicalId is used after the removal
if 'canonicalId' in new_content:
    # Count usages - if only declared once, remove it
    uses = [i for i, line in enumerate(new_content.split('\n')) if 'canonicalId' in line]
    if len(uses) <= 1:
        new_content = new_content.replace(
            "  const canonicalId = universityId ? canonicalById[universityId] || universityId : null\n",
            ""
        )
        print("Removed unused canonicalId")

# Fix the import line - remove the entire import if all are unused
# Check which imports are actually used
import_line = "import { useState } from 'react'"
if import_line in new_content:
    # Check if useState is used
    if 'useState' not in new_content.replace(import_line, ''):
        new_content = new_content.replace(import_line + '\n', '')
        print("Removed unused useState import")

# Also check if there's an empty import left
if "import {  } from 'react'" in new_content or "import {} from 'react'" in new_content:
    new_content = re.sub(r"import \{ ?\} from 'react'\n", '', new_content)

# Check the first import line
first_import = "import { useState } from 'react'"
if first_import in new_content:
    rest = new_content.replace(first_import, '')
    if 'useState' not in rest:
        new_content = new_content.replace(first_import + '\n', '')

p.write_text(new_content, encoding='utf-8')
print('UniversityDrawer.tsx official URLs section removed')

# Also fix Ranking.tsx - remove unused ExternalLink import
rp = ROOT / 'frontend' / 'src' / 'pages' / 'Ranking.tsx'
ranking = rp.read_text(encoding='utf-8')
# Check if ExternalLink is used in the file body (not just the import)
ranking_body = ranking.split('\n', 15)[14] if len(ranking.split('\n')) > 14 else ''
if 'ExternalLink' in ranking.replace("  ExternalLink,\n", ''):
    pass  # Still used
else:
    ranking = ranking.replace("  ExternalLink,\n", '')
    print('Removed unused ExternalLink from Ranking.tsx imports')

rp.write_text(ranking, encoding='utf-8')
