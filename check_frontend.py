#!/usr/bin/env python3
"""Extract every embedded <script> block from the app's rendered templates and
run `node --check` on each, so a stray apostrophe or broken JS is caught before
it can take the site down. Usage: python3 check_frontend.py <path-to-app.py>
"""
import re
import subprocess
import sys
import tempfile
import os

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "core/axiom_harmony_unified_app.py"
    src = open(path, encoding="utf-8").read()
    # Grab <script>...</script> blocks that have no src= attribute (inline JS).
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.DOTALL)
    failures = 0
    checked = 0
    for i, code in enumerate(blocks):
        js = code.strip()
        if not js:
            continue
        checked += 1
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(js)
            tmp = f.name
        try:
            r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                failures += 1
                print(f"FAIL block #{i}:")
                print(r.stderr.strip()[:800])
        finally:
            os.unlink(tmp)
    print(f"{checked} script blocks checked, {failures} failures")
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    main()
