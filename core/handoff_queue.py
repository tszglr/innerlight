"""
handoff_queue.py — the RECEIVING end of InnerLight.

When a person in crisis reviews their summary and taps "Connect now," their
*consented* handoff lands here. This is intentionally separate from the private
session store (which keeps nothing): a handoff is something the person has
explicitly chosen to send to a provider or attorney, so it must actually reach
the administrator/provider — it does not vanish like ephemeral session data.

The queue lives in the running process. It holds only what the person approved:
their conversation summary, any clarification they added, the route type
(clinical or legal), and a risk flag. No diagnosis is ever stored or shown —
the receiver forms their own assessment from the person's own words.

This module has NO external dependencies and is safe to import anywhere.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional

# Thread-safe in-process store. Newest first when listed.
_LOCK = threading.Lock()
_HANDOFFS: List[Dict[str, Any]] = []
_MAX_KEPT = 200  # rolling cap so memory stays bounded


def _short_ref() -> str:
    """A short, human-friendly reference the person and provider can both see.
    Not derived from any personal data."""
    return "IL-" + uuid.uuid4().hex[:6].upper()


def submit_handoff(
    *,
    route: str,
    conversation: List[Dict[str, str]],
    clarification: str = "",
    added_note: str = "",
    risk: str = "low",
    display_name: str = "",
) -> Dict[str, Any]:
    """Record a consented handoff. Returns the stored record (with its ref)."""
    route_norm = "legal" if str(route).lower().startswith("leg") else "clinical"
    record = {
        "ref": _short_ref(),
        "route": route_norm,                       # "clinical" | "legal"
        "conversation": conversation or [],        # [{role, text}], the person's own words
        "clarification": (clarification or "").strip(),
        "added_note": (added_note or "").strip(),
        "risk": (risk or "low").lower(),
        "display_name": (display_name or "").strip(),  # optional, person-volunteered only
        "status": "waiting",                       # waiting | viewed | connected | closed
        "created_at": time.time(),
        "created_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "viewed_at": None,
    }
    with _LOCK:
        _HANDOFFS.append(record)
        # keep the list bounded
        if len(_HANDOFFS) > _MAX_KEPT:
            del _HANDOFFS[: len(_HANDOFFS) - _MAX_KEPT]
    return record


def list_handoffs(route: Optional[str] = None) -> List[Dict[str, Any]]:
    """Newest first. Optionally filter to 'clinical' or 'legal'."""
    with _LOCK:
        items = list(_HANDOFFS)
    if route in ("clinical", "legal"):
        items = [h for h in items if h["route"] == route]
    items.sort(key=lambda h: h["created_at"], reverse=True)
    return items


def get_handoff(ref: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        for h in _HANDOFFS:
            if h["ref"] == ref:
                return dict(h)
    return None


def set_status(ref: str, status: str) -> bool:
    status = status if status in ("waiting", "viewed", "connected", "closed") else "viewed"
    with _LOCK:
        for h in _HANDOFFS:
            if h["ref"] == ref:
                h["status"] = status
                if status == "viewed" and not h.get("viewed_at"):
                    h["viewed_at"] = time.time()
                return True
    return False


def diagnostics() -> Dict[str, Any]:
    """Simple operational health numbers for the admin to monitor the system."""
    with _LOCK:
        items = list(_HANDOFFS)
    now = time.time()
    waiting = [h for h in items if h["status"] == "waiting"]
    handled = [h for h in items if h["status"] in ("viewed", "connected", "closed")]
    # average time-to-first-view (a real "is it working" signal), in seconds
    views = [h["viewed_at"] - h["created_at"] for h in items if h.get("viewed_at")]
    avg_view = round(sum(views) / len(views), 1) if views else None
    return {
        "total": len(items),
        "waiting": len(waiting),
        "handled": len(handled),
        "clinical": len([h for h in items if h["route"] == "clinical"]),
        "legal": len([h for h in items if h["route"] == "legal"]),
        "oldest_waiting_secs": round(now - min([h["created_at"] for h in waiting]), 0) if waiting else 0,
        "avg_seconds_to_first_view": avg_view,
    }
