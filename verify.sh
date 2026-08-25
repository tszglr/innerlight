#!/usr/bin/env bash
set -e  # every gate step is fatal — a silent middle failure can never pass again
# InnerLight verified-deploy gate. Runs inside Render's build step:
# if any check fails, the BUILD fails and Render keeps the previous good
# version live — a broken commit can never reach a person in crisis.
set -euo pipefail
pip install -r requirements.txt 2>/dev/null || pip install -r requirements.txt --break-system-packages
echo "== syntax gate (SyntaxWarning = failure) =="
python -W error::SyntaxWarning -m py_compile core/*.py
echo "== frontend script blocks =="
if command -v node >/dev/null 2>&1; then
  python check_frontend.py core/axiom_harmony_unified_app.py
else
  echo "SKIPPED: node not present in this environment (frontend blocks are verified in development, where node exists)"
fi
echo "== language parity: every dictionary, every language =="
python tools/check_lang_parity.py
echo "== live smoke test =="
python - <<'PY'
import sys
sys.path.insert(0, "core")
import axiom_harmony_unified_app as app_mod
c = app_mod.app.test_client()
assert c.get("/").status_code == 200, "home failed"
r = c.post("/api/checkin", json={"message": "hello"})
assert r.status_code == 200 and "response" in r.get_json(), "checkin failed"
assert c.get("/research").status_code == 200, "research failed"
assert c.get("/safety").status_code == 200, "safety failed"
print("smoke: all green")
PY
echo "== VERIFIED: safe to serve =="
