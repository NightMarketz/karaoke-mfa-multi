"""Negative-control harness: patch one anchor, run one test file, restore.

Usage: python sabotage.py <source-file> <test-file> <case-file>
The case file is JSON: [[label, old, new], ...]
"""
import json
import subprocess
import sys
from pathlib import Path

src = Path(sys.argv[1])
tests = sys.argv[2].split()
cases = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
backup = src.read_text(encoding="utf-8")

try:
    for label, old, new in cases:
        if old not in backup:
            print(f"-- {label}\n   !! ANCHOR NOT FOUND: {old!r}")
            continue
        src.write_text(backup.replace(old, new), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *tests, "-q", "--no-header", "--tb=no"],
            capture_output=True, text=True,
        )
        fails = [line.split("::")[-1] for line in r.stdout.splitlines()
                 if line.startswith(("FAILED", "SUBFAIL"))]
        totals = [line for line in r.stdout.splitlines()
                  if "passed" in line or "failed" in line]
        summary = totals[-1] if totals else r.stdout[-300:]
        print(f"-- {label}\n   {summary}")
        for f in fails:
            print(f"   red: {f}")
        # Trust the totals line, not the FAILED names: pytest-subtests reports
        # subtest failures without a FAILED line, so name-counting called a real
        # red "green" once already.
        # A run over zero tests is a universal green. Report it as the error it
        # is, never as a passing fence.
        if "no tests ran" in summary or "error" in summary:
            print("   !! NO CARDINALITY -- the harness ran nothing, verdict void")
        elif "failed" not in summary:
            print("   !! STAYED GREEN -- this fence does not catch what it claims")
finally:
    src.write_text(backup, encoding="utf-8")
    print("\nrestored")
