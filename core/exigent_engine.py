"""
EXIGENT CIRCUMSTANCES ENGINE — physical-help dispatch readiness.

BUILT, DORMANT, READY (the Dispatch pattern, applied to emergencies).

WHY THIS EXISTS NOW
The law already mandates crisis REFERRAL: California SB 243 (effective
Jan 1, 2026) requires companion-chatbot operators to promptly direct users
expressing suicidal ideation to crisis service providers, publish the
protocol, and — beginning July 1, 2027 — keep meticulous crisis-interaction
records; Oregon SB 1546 and New York GBL §1700 impose parallel duties, and
several states now grant private rights of action. Physical DISPATCH is not
yet mandated for tools like InnerLight — but a statute, a 988-system
subcontract, or a county mobile-crisis contract could require it, and the
founder's law is that the capability must activate seamlessly the day it is
required. This engine is that seam.

THE THREE TIERS (doctrine, in code)
  Tier 1 — USER-INITIATED (always live, today): the person taps 988 / 911 /
           chat themselves. This engine adds nothing and gates nothing here.
  Tier 2 — USER-CONSENTED DISPATCH (this engine, when active): the person
           explicitly asks "send help to my location," confirms, and shares
           location for that purpose. Consent is the trigger; InnerLight is
           the courier.
  Tier 3 — EXIGENT BREAK-GLASS (defined, double-locked): imminent risk with
           incapacity to self-summon. Requires: engine active + provider
           ready + founder-enabled break-glass flag + documented legal
           review for the operating jurisdictions. Consistent with the
           public FAQ's honest-limits promise; never silent as policy.

Every activation, deactivation, and dispatch attempt is logged (no personal
content). The engine has no hooks in the care path while dormant; its only
public surface is a boolean availability flag.
"""

import json
import os
import time

_STATE_DIR = "/var/data" if os.path.isdir("/var/data") else "/tmp"
_STATE_PATH = os.path.join(_STATE_DIR, "exigent_state.json")

LEGAL_BASIS = [
    "California SB 243 (eff. 2026-01-01): mandatory crisis-referral protocol, published, "
    "with records and crisis-interaction reporting duties from 2027-07-01.",
    "Oregon SB 1546 (2026): suicidal-ideation detection with crisis referral interruptions.",
    "New York GBL \u00a71700 et seq. (eff. 2025-11-05): AI companion crisis safeguards.",
    "No statute yet mandates physical dispatch by tools like InnerLight; 988-system or "
    "county contracts may require it sooner. This engine is readiness, not obligation.",
]

# Provider seams. Each becomes READY when its credentials/partnership exist in
# the environment. Descriptions state real, named integration paths.
PROVIDERS = [
    {
        "id": "rapidsos_911",
        "name": "RapidSOS 911 API (data + location to PSAPs)",
        "how": ("The integration platform apps use to reach 911: links rich data and "
                "device location into 15,000+ first-responder agencies nationwide. "
                "Requires a RapidSOS partnership and API credentials."),
        "env": "EXIGENT_RAPIDSOS_API_KEY",
    },
    {
        "id": "lifeline_988_warm",
        "name": "988 Lifeline warm transfer with imminent-risk procedures",
        "how": ("Contracted warm-transfer into the 988 network, whose counselors "
                "operate established imminent-risk (active rescue) procedures. "
                "Requires a 988-system agreement."),
        "env": "EXIGENT_988_PARTNER_TOKEN",
    },
    {
        "id": "county_mobile_crisis",
        "name": "County mobile crisis team API",
        "how": ("Direct dispatch request into a county's mobile crisis / alternative "
                "response system (the care-first responders InnerLight exists to "
                "bridge toward). Requires a county integration agreement."),
        "env": "EXIGENT_COUNTY_CRISIS_KEY",
    },
    {
        "id": "text911_gateway",
        "name": "Text-to-911 gateway",
        "how": ("Carrier/NG911 text gateway for jurisdictions with text-to-911 "
                "coverage. Requires a gateway provider agreement."),
        "env": "EXIGENT_TEXT911_KEY",
    },
]

NEVER = [
    "Never silent as policy: dispatch is consent-anchored (Tier 2); the break-glass tier "
    "stays locked until founder activation plus documented legal review.",
    "Never location without purpose: location is requested only for a dispatch the person "
    "asked for, used once, never stored.",
    "Never a substitute: dispatch capability never replaces the human doors (988/911) "
    "already on every screen.",
    "Never revenue-touched: this engine is care infrastructure; Dispatch (the monetary "
    "engine) has no hooks here, enforced by the same isolation discipline.",
]


def _load():
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            st = json.load(f)
        if isinstance(st, dict) and "active" in st:
            st.setdefault("log", [])
            st.setdefault("break_glass", False)
            return st
    except Exception:
        pass
    return {"active": False, "break_glass": False, "activated_at": None, "log": []}


def _save(st):
    try:
        tmp = _STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, _STATE_PATH)
        return True
    except Exception as e:
        print(f"[exigent] state save failed: {str(e)[:120]}")
        return False


def provider_status():
    out = []
    for p in PROVIDERS:
        ready = bool(os.environ.get(p["env"], "").strip())
        out.append({**p, "ready": ready})
    return out


def is_available():
    """True only when the founder has activated the engine AND at least one
    provider is configured. This is the single flag the crisis surface reads."""
    st = _load()
    if not st.get("active"):
        return False
    return any(p["ready"] for p in provider_status())


def get_status():
    st = _load()
    return {
        "active": bool(st.get("active")),
        "break_glass": bool(st.get("break_glass")),
        "available": is_available(),
        "activated_at": st.get("activated_at"),
        "providers": provider_status(),
        "legal_basis": LEGAL_BASIS,
        "never": NEVER,
        "log": st.get("log", [])[-12:],
        "persistent": _STATE_DIR == "/var/data",
    }


def set_active(active, actor="founder"):
    st = _load()
    st["active"] = bool(active)
    st["activated_at"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()) if active else None
    if not active:
        st["break_glass"] = False  # deactivation always re-locks the break-glass tier
    st.setdefault("log", []).append({
        "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "action": "activated" if active else "deactivated",
        "by": str(actor)[:40],
    })
    st["log"] = st["log"][-100:]
    ok = _save(st)
    return {"ok": ok, "active": st["active"], "available": is_available()}


def log_dispatch_attempt(kind="tier2_request"):
    """Audit trail for dispatch attempts. Content-free by design: what is
    logged is that an attempt occurred and its disposition — never words,
    never identity."""
    st = _load()
    st.setdefault("log", []).append({
        "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "action": kind,
        "by": "system",
    })
    st["log"] = st["log"][-100:]
    _save(st)
