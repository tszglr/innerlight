#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# check_hybrid_fallback.py — HYBRID degrade-gracefully regression guard
# (FEAT-009; Immutable Principles 1, 13, 15).
#
# Proves, repeatably, that the live-voice / built-in-words hybrid stays honest
# and OBSERVABLE, and that no person is ever turned away when the live voice is
# unavailable:
#
#   #1  NO KEY -> WARM REPLY, NO DEAD END. With ANTHROPIC_API_KEY unset,
#       /api/checkin still returns 200 with a warm reply (the built-in words),
#       and the live-voice-vs-built-in-words telemetry records a fallback with
#       a named reason (not a silent failure).
#
#   #2  NO KEY -> NO SPEND. When no key is set, the daily Claude budget counter
#       is NOT consumed (no live call was made, so nothing was spent).
#
#   #3  CAP REACHED -> STILL ANSWERED. When the daily Claude cap is reached, a
#       person in crisis is NOT hit with a "busy" 429; /api/checkin returns 200
#       with a warm reply and the telemetry marks fallback_budget.
#
# This test NEVER calls the real Anthropic API: it runs with the key unset, and
# for the cap test it exhausts the in-memory budget counter directly.
#
# Runs standalone (python tools/check_hybrid_fallback.py) and is wired into
# verify.sh. Exit code 0 = all green; non-zero = the hybrid regressed.
# ---------------------------------------------------------------------------
import os
import sys
import tempfile

# Make sure the real key is never used, even if present in the environment.
os.environ.pop("ANTHROPIC_API_KEY", None)

# Isolate any on-call registry to a throwaway file (the app reads it at import).
_TMP = tempfile.mkdtemp(prefix="il_hybrid_check_")
os.environ["ONCALL_DB_FILE"] = os.path.join(_TMP, "oncall_test.db")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
sys.path.insert(0, "core")
import axiom_harmony_unified_app as a  # noqa: E402
import comprehension_engine as ce  # noqa: E402

client = a.app.test_client()
failures = []


def _check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  -> " + detail) if detail else ""))
    if not ok:
        failures.append(name)


def _ai_counts():
    with a._AI_SOURCE_LOCK:
        return dict(a._AI_SOURCE.get("counts", {}))


def _claude_used():
    with a._BUDGET_LOCK:
        return int(a._BUDGET.get("counts", {}).get("claude", 0))


print("hybrid degrade-gracefully regression guard")

# Sanity: the live voice reports itself unavailable with no key.
_check("live voice reports unavailable with no key", ce.available() is False)

# --- #1 + #2: no key -> warm reply, fallback recorded, no budget spent --------
print("[#1/#2] no key -> warm 200 reply, fallback telemetry, no Claude spend")
before_used = _claude_used()
before_fb = sum(v for k, v in _ai_counts().items() if k != "live")
r = client.post("/api/checkin", json={
    "message": "I feel hopeless and alone tonight and I dont know what to do"})
_check("no-key: /api/checkin returns 200 (not a 'busy' 429)", r.status_code == 200,
       "status=" + str(r.status_code))
j = r.get_json() or {}
_check("no-key: a warm reply is present", bool(j.get("response")),
       "response=" + repr(j.get("response"))[:80])
after_used = _claude_used()
_check("no-key: Claude budget counter NOT consumed", after_used == before_used,
       "before=%d after=%d" % (before_used, after_used))
after_fb = sum(v for k, v in _ai_counts().items() if k != "live")
_check("no-key: a fallback bucket incremented (observable, not silent)", after_fb > before_fb,
       "counts=" + repr(_ai_counts()))
_check("no-key: fallback classified as 'no_key'", _ai_counts().get("fallback_no_key", 0) > 0,
       "counts=" + repr(_ai_counts()))

# --- #3: cap reached -> still answered, marked fallback_budget ----------------
# This branch only fires when a key is configured (a real call would be made),
# so simulate a configured key WITHOUT ever letting a real HTTP call happen:
# pin the live voice to "available" and pre-exhaust the daily budget so the
# route takes the budget-blocked path before any network call.
print("[#3] cap reached -> person still answered warmly, marked fallback_budget")
_orig_available = ce.available
try:
    ce.available = lambda: True  # pretend a key is set; budget gate fires first
    # Exhaust the daily Claude budget so _budget_room('claude') is False.
    with a._BUDGET_LOCK:
        a._BUDGET["day"] = __import__("time").strftime("%Y-%m-%d")
        a._BUDGET["counts"]["claude"] = a._BUDGET_CAPS.get("claude", 1500)
    before_budget_fb = _ai_counts().get("fallback_budget", 0)
    r = client.post("/api/checkin", json={
        "message": "I cant take it anymore, everything is falling apart"})
    _check("cap-reached: /api/checkin returns 200 (never a 'busy' 429)", r.status_code == 200,
           "status=" + str(r.status_code))
    j = r.get_json() or {}
    _check("cap-reached: a warm reply is present", bool(j.get("response")))
    _check("cap-reached: telemetry marks fallback_budget",
           _ai_counts().get("fallback_budget", 0) > before_budget_fb,
           "counts=" + repr(_ai_counts()))
finally:
    ce.available = _orig_available

# --- admin readout carries the new fields (founder session) -------------------
print("[watch] /api/admin/abuse exposes the live-voice readout to the founder")
with client.session_transaction() as s:
    s["founder_ok"] = True
r = client.get("/api/admin/abuse")
_check("abuse endpoint returns 200 for founder", r.status_code == 200,
       "status=" + str(r.status_code))
d = r.get_json() or {}
_check("abuse: ai_source counts present", isinstance(d.get("ai_source"), dict))
_check("abuse: near_cap indicator present", "near_cap" in d)
_check("abuse: claude_pct_of_cap present", "claude_pct_of_cap" in d)
_check("abuse: last_fallback_reason present", "last_fallback_reason" in d)

print("")
if failures:
    print("HYBRID GUARD FAILED: " + ", ".join(failures))
    sys.exit(1)
print("hybrid guard: live voice is primary, built-in words degrade gracefully and are observable")
