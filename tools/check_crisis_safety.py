#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# check_crisis_safety.py — FATAL crisis-safety regression guard
# (FOUNDER_WORKLIST.md items #1 and #2; Immutable Principles 1, 10, 13).
#
# Proves, repeatably, that the two fatal laws cannot silently regress:
#
#   #1  LOVED-ONE HOLDING. A loved-one crisis message ("my daughter was just
#       put on a 5150 hold") gets NO pushed handoff/referral card in the first
#       turn (witness_grief), while the permanent 988/911 human_help fixture
#       stays present.
#
#   #2  NO DEAD DOORS. With NO clinical provider on call, a high/critical
#       NON-loved-one message emits NO provider/counselor/video button
#       (handoff type "none") but STILL carries the always-free 988 / 988-chat
#       / 911 / Text-HOME-741741 fixture. With a clinical provider marked
#       available=1, the telehealth/counselor button DOES appear — proving the
#       gate is availability-driven, not a blanket removal.
#
# Runs standalone (python tools/check_crisis_safety.py) and is wired into
# verify.sh. Uses a throwaway on-call DB so it never touches real state.
# Exit code 0 = all green; non-zero = a fatal law regressed.
# ---------------------------------------------------------------------------
import os
import sys
import tempfile

# Isolate the on-call registry to a throwaway file BEFORE the app imports it
# (the module reads ONCALL_DB_FILE at import time). This keeps the founder's
# real availability state untouched and gives us a clean, empty table.
_TMP = tempfile.mkdtemp(prefix="il_crisis_check_")
os.environ["ONCALL_DB_FILE"] = os.path.join(_TMP, "oncall_test.db")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
sys.path.insert(0, "core")
import axiom_harmony_unified_app as a  # noqa: E402

client = a.app.test_client()
failures = []


def _check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  -> " + detail) if detail else ""))
    if not ok:
        failures.append(name)


def _set_all_clinical(available):
    """Force every clinical role to the given availability in the test DB."""
    with a._ONCALL_LOCK:
        conn = a._oncall_db()
        try:
            conn.execute(
                "UPDATE provider_availability SET available=? WHERE side='clinical'",
                (1 if available else 0,),
            )
            conn.commit()
        finally:
            conn.close()
    # The public availability endpoint caches for 10s; clear it so the gate
    # reads the state we just set.
    try:
        a._ONCALL_CACHE["data"] = None
        a._ONCALL_CACHE["t"] = 0.0
    except Exception:
        pass


print("crisis-safety regression guard")

# Baseline: no one on call (the honest default).
_set_all_clinical(False)

# --- ITEM #1: loved-one holding ------------------------------------------------
print("[#1] loved-one crisis -> pure holding, no pushed card, rail stays")
r = client.post("/api/checkin", json={
    "message": "my daughter was just put on a 5150 hold and I dont know what to do"})
j = r.get_json() or {}
h = j.get("handoff") or {}
_check("loved-one: no pushed handoff card", h.get("type") == "none",
       "handoff=" + repr(h))
_check("loved-one: witness_grief flagged", h.get("witness_grief") is True)
_check("loved-one: 988/911 human_help fixture still present", bool(j.get("human_help")))
hh = j.get("human_help") or {}
_check("loved-one: human_help carries 988", hh.get("lifeline") == "988")
_check("loved-one: human_help carries Text HOME 741741",
       "741741" in str(hh.get("text_line", "")))

# The internal witness-grief detector itself.
_check("_witness_grief true for family+event, no self-harm",
       a._witness_grief("my daughter was just put on a 5150 hold") is True)
_check("_witness_grief false for the person's own self-harm",
       a._witness_grief("i want to kill myself") is False)

# --- ITEM #2a: NO provider on call -> no dead door ----------------------------
print("[#2] no clinical provider on call -> no provider button, free doors live")
r = client.post("/api/checkin", json={
    "message": "I feel hopeless and I cant take it anymore, I need to talk to someone"})
j = r.get_json() or {}
h = j.get("handoff") or {}
_check("no-provider: no telehealth/counselor button emitted", h.get("type") != "telehealth",
       "handoff=" + repr(h))
_check("no-provider: 988/911 human_help fixture still present", bool(j.get("human_help")))
# If a crisis card surfaced, its always-free public doors must survive and the
# dead-end monitor button must be gone.
if h.get("type") == "crisis":
    br = h.get("bridge") or {}
    _check("no-provider crisis card: 988 call door kept",
           (br.get("primary") or {}).get("action") == "call_988")
    _check("no-provider crisis card: 911 door kept",
           (br.get("emergency") or {}).get("action") == "call_911")
    _check("no-provider crisis card: live-monitor button stripped", "tertiary" not in br)

# --- ITEM #2b: provider on call -> the button returns -------------------------
print("[#2] a clinical provider available=1 -> the counselor button returns")
_set_all_clinical(True)
try:
    _check("_clinical_on_call() true when a clinical row is available", a._clinical_on_call() is True)
    # Route a telehealth-shaped handoff through the gate directly (deterministic).
    routed = a._route_handoff(
        {"type": "telehealth", "urgency": "soon", "label": "Talk with a licensed professional",
         "bridge": {"primary": {"action": "request_video",
                                "label": "Start a video session with a counselor", "value": "video"}}},
        "I need to talk to a counselor")
    _check("provider-on-call: telehealth card is EMITTED (gate is availability-driven)",
           routed.get("type") == "telehealth", "routed=" + repr(routed.get("type")))
    # And with no one on call it must vanish again.
    _set_all_clinical(False)
    routed_off = a._route_handoff(
        {"type": "telehealth", "urgency": "soon", "label": "Talk with a licensed professional",
         "bridge": {"primary": {"action": "request_video",
                                "label": "Start a video session with a counselor", "value": "video"}}},
        "I need to talk to a counselor")
    _check("no-provider: same telehealth card is suppressed", routed_off.get("type") == "none",
           "routed=" + repr(routed_off))
finally:
    _set_all_clinical(False)

print("")
if failures:
    print("CRISIS-SAFETY GUARD FAILED: " + ", ".join(failures))
    sys.exit(1)
print("crisis-safety guard: all fatal laws hold (loved-one holding + no dead doors)")
