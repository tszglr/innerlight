"""
DISPATCH — InnerLight's monetary engine (Immutable Principle 7).

BUILT, DORMANT, READY. This engine exists so that the day the founder chooses
to activate revenue, the machinery is already here — and until that day it is
invisible to every person InnerLight serves.

CARE ISOLATION GUARANTEE (Principle 3 in code):
This module is imported ONLY by the founder's administration surface. It has
no hooks into the conversation, crisis, routing, or handoff paths, so
activation or deactivation CANNOT change what any person in crisis
experiences. Routing to help is decided by need and provider quality alone;
nothing in this engine can buy influence over it. A repository test enforces
that the care path never imports this module.

State persists at /var/data/dispatch_state.json (Render persistent disk) with
a local fallback, and every activation or deactivation is logged with time
and actor.
"""

import json
import os
import time

_STATE_DIR = "/var/data" if os.path.isdir("/var/data") else "/tmp"
_STATE_PATH = os.path.join(_STATE_DIR, "dispatch_state.json")

# The revenue streams Dispatch is built to operate — every one grounded in the
# 2026 crisis-financing landscape, and every one bound by the guardrails below.
IDENTITY = (
    "THE RESOLUTION EXCHANGE. InnerLight sells exactly one thing: a verified "
    "resolution — a person in crisis reaching the right human, measured, "
    "consent-based, privacy-preserving. We are paid only when someone reaches "
    "help, and only by institutions that already owe the system that outcome. "
    "Never by the person. Never for attention, data, or access."
)

STREAMS = [
    {
        "id": "resolution_gap",
        "name": "The Gap Engine — paid per verified follow-up (HEDIS FUM/FUA/FUH)",
        "how": (
            "Health plans are formally graded on whether people get mental-health "
            "follow-up after an ED crisis visit (NCQA HEDIS measures FUM, FUA, "
            "FUH), and people who get no aftercare have 6x the odds of returning "
            "to the ED within two months. Telehealth, telephone visits, e-visits, "
            "and virtual check-ins COUNT toward the measure — which means "
            "InnerLight's consent-based warm handoff into a follow-up visit IS "
            "the gap-closer. The plan pays per verified closed gap; the person "
            "pays nothing and their words are never shared. No one else sells "
            "crisis-moment measure closure — this is InnerLight's native product."
        ),
    },
    {
        "id": "boarding_relief",
        "name": "Boarding relief — shared savings with hospitals",
        "how": (
            "Psychiatric patients wait (board) in EDs longer and cost more than "
            "any other category, and un-followed crisis visits come back. "
            "Hospitals pay a share of independently measured avoided return "
            "visits and boarding hours among people InnerLight bridged to care. "
            "If nothing is avoided, nothing is owed — the model only earns when "
            "the system genuinely worked."
        ),
    },
    {
        "id": "pay_for_success",
        "name": "Pay-for-success instruments",
        "how": (
            "Philanthropy fronts the risk capital; a county repays only against "
            "independently verified improvement in time-to-resolution — the "
            "single metric InnerLight was built to measure. The field's own "
            "evaluations name outcome data as its gap; our measurement layer is "
            "the collateral."
        ),
    },
    {
        "id": "lifeline_988",
        "name": "The 988 ecosystem lane",
        "how": (
            "Thirteen states and counting fund 988 through permanent telecom "
            "surcharges (California's flows into a dedicated 988 Crisis Service "
            "Fund), and the federal Designation Act explicitly allows those "
            "funds to support the WHOLE crisis system — outreach and "
            "stabilization included, not just call centers. InnerLight "
            "subcontracts as the digital front door and hold-the-wait layer for "
            "state 988 systems; parity laws increasingly require insurers to "
            "cover crisis services regardless of network."
        ),
    },
    {
        "id": "dmht_future",
        "name": "Digital mental health treatment reimbursement (watched, not claimed)",
        "how": (
            "CMS has begun paying for digital mental health treatment devices "
            "under physician billing pathways. That lane requires FDA clearance "
            "InnerLight does not have and does not claim — it is tracked here "
            "honestly as the engine's future gear, activated only if and when "
            "the clearance path is real."
        ),
    },
    {
        "id": "sustaining_circle",
        "name": "The Sustaining Circle",
        "how": (
            "Someone InnerLight held through their worst night may — later, "
            "never at the moment of crisis, never required, never prompted "
            "during care — choose to fund another person's wait. Reported "
            "publicly in aggregate. The only consumer revenue this engine will "
            "ever contain, and it is a gift, not a fee."
        ),
    },
]

# Hard lines, stated in code so they travel with the engine forever.
NEVER = [
    "No advertising, anywhere, ever.",
    "No sale or sharing of personal data — the AHP encryption design makes this impossible by construction.",
    "No fees charged to a person at their moment of crisis.",
    "No pay-for-priority: money can never change who gets routed to help, or how fast.",
    "No revenue consideration may ever appear in the care path's code.",
]


def _load():
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            st = json.load(f)
        if isinstance(st, dict) and "active" in st:
            st.setdefault("log", [])
            return st
    except Exception:
        pass
    return {"active": False, "activated_at": None, "log": []}


def _save(st):
    try:
        tmp = _STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, _STATE_PATH)
        return True
    except Exception as e:
        print(f"[dispatch] state save failed: {str(e)[:120]}")
        return False


def is_active():
    """The single switch partner/billing surfaces consult. Care paths never call this."""
    return bool(_load().get("active"))


def get_status():
    st = _load()
    return {
        "identity": IDENTITY,
        "active": bool(st.get("active")),
        "activated_at": st.get("activated_at"),
        "streams": STREAMS,
        "never": NEVER,
        "log": st.get("log", [])[-12:],
        "persistent": _STATE_DIR == "/var/data",
    }


def set_active(active, actor="founder"):
    """Flip the engine. Founder-only (enforced at the route). Every flip is logged."""
    st = _load()
    st["active"] = bool(active)
    st["activated_at"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()) if active else None
    st.setdefault("log", []).append({
        "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "action": "activated" if active else "deactivated",
        "by": str(actor)[:40],
    })
    st["log"] = st["log"][-100:]
    ok = _save(st)
    return {"ok": ok, "active": st["active"]}
