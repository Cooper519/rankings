"""Run every scraper test module's main() and report pass/fail.

pytest is unavailable offline, so this invokes each test_*.py module that
exposes a main() entrypoint and aggregates results.
"""
from __future__ import annotations
import importlib
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

test_files = []
for base in [ROOT / "scraper", ROOT / "scraper" / "programs", ROOT / "scraper" / "rankings"]:
    test_files.extend(sorted(base.glob("test_*.py")))

passed, failed = [], []
for path in test_files:
    rel = path.relative_to(ROOT)
    modname = ".".join(rel.with_suffix("").parts)
    try:
        mod = importlib.import_module(modname)
    except Exception as exc:  # import error
        failed.append((rel, "import", str(exc)))
        continue
    if not hasattr(mod, "main"):
        continue
    try:
        mod.main()
        passed.append(rel)
    except Exception as exc:
        failed.append((rel, "run", traceback.format_exc(limit=4)))

print("\n==== TEST RUN SUMMARY ====")
print("passed: %d" % len(passed))
print("failed: %d" % len(failed))
for rel, kind, info in failed:
    print("\n--- FAIL %s (%s) ---" % (rel, kind))
    print(info)
sys.exit(1 if failed else 0)
