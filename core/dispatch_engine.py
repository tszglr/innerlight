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
STREAMS = [
    {
        "id": "public_payer",
        "name": "Public-payer infrastructure (Medicaid / Medi-Cal)",
        "how": (
            "InnerLight contracts as the digital front door and time-to-resolution "
            "layer for county mobile-crisis and CBO providers. Federal CMS guidance "
            "for the community-based mobile crisis benefit provides enhanced "
            "matching pathways that include select IT services supporting crisis "
            "response. California's Medi-Cal benefit (State Plan Amendment 22-0043) "
            "carries an 85% federal match window through December 31, 2026, with "
            "the benefit proposed for recast from April 2027 — contracts are "
            "written with the county or provider, never with the person served."
        ),
    },
    {
        "id": "outcomes",
        "name": "Outcomes-based contracts",
        "how": (
            "Counties and health plans pay against independently measured "
            "improvement in time-to-resolution — the outcome InnerLight was built "
            "to measure from day one. The field's own evaluations name outcome "
            "data as the gap; InnerLight's measurement layer is the product."
        ),
    },
    {
        "id": "provider_network",
        "name": "Provider network infrastructure",
        "how": (
            "Enrolled commercial providers (telehealth practices, clinics) pay for "
            "warm-handoff infrastructure: consent-gated context summaries, "
            "scheduling, and language support. Payment NEVER affects routing "
            "order, visibility, or recommendation — placement is decided by fit "
            "and vetted quality alone (Principle 3)."
        ),
    },
    {
        "id": "institutional",
        "name": "Institutional licensing",
        "how": (
            "Universities, school districts, employers, and unions license "
            "InnerLight for their populations as a covered benefit — the "
            "institution pays; the person in crisis never does."
        ),
    },
    {
        "id": "grants",
        "name": "Grants and philanthropy",
        "how": (
            "The research-grade grant engine (public-record funder mapping, "
            "e.g. Arnold Ventures' crisis-response portfolio) — already the "
            "organization's active non-dilutive path."
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
