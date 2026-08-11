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
    import ast
    src = open(path, encoding="utf-8").read()
    # Walk the module's string constants via ast: Constant.value is the string
    # AFTER Python evaluates escapes (and untouched for r"" raw templates), so
    # we validate the JS exactly as the browser will receive it — not the raw
    # source text, which differs for cooked templates (e.g. \\s in source is
    # \s at runtime).
    consts = [(n.lineno, n.value) for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    consts.sort(key=lambda t: t[0])
    rendered = "\n".join(v for _, v in consts)
    # Grab <script>...</script> blocks that have no src= attribute (inline JS).
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", rendered, re.DOTALL)
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
