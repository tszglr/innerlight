"""
Warm Handoff Module for InnerLight.

The handoff is the most emotionally charged moment in the whole experience —
the bridge from InnerLight to a real human helper. It must never feel like a
cold transfer ("here's a number, goodbye"). It must feel like a warm hand on
the shoulder.

A warm handoff has SIX parts:
  1. ACKNOWLEDGE   — reflect what the person shared, so they feel heard
  2. AFFIRM        — name the brave/right thing they are doing
  3. PREPARE       — tell them exactly what to expect next (removes fear of
                     the unknown — the #1 reason people don't follow through)
  4. REASSURE      — InnerLight stays available, no guilt, no pressure
  5. REGISTER      — all of it shaped to how the person actually speaks
  6. VOICE         — spoken aloud, calm and slow

Plus a LEARNING layer: every handoff is logged with its outcome signal so the
phrasing can keep improving. Humans review; the system never auto-changes
safety-critical wording without review.

IMMUTABLE RULES (never violated):
  - Never practice medicine or law in the handoff
  - Never promise an outcome ("they will fix this")
  - Never pressure the person to stay
  - Never withhold the resource to create engagement
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# WHAT TO EXPECT — the "prepare" content for each handoff type.
# This is the part that removes fear of the unknown.
# ---------------------------------------------------------------------------

WHAT_TO_EXPECT = {
    "crisis": {
        "988": (
            "When you connect, a trained counselor will answer. "
            "They are calm, they have heard everything before, and they will not judge you. "
            "You can tell them as much or as little as you want. "
            "There is no script you have to follow."
        ),
        "operator": (
            "A real person from our support team will join you shortly. "
            "They are here only to help you stay safe and find the right next step."
        ),
        "911": (
            "If you are in immediate danger, emergency services can reach you fast. "
            "Tell them where you are and that you need help staying safe."
        ),
    },
    "legal": (
        "When you reach the attorney or legal aid office, you do not need to know "
        "all the legal words. Just tell them what happened in your own words. "
        "You already have the questions we prepared, so you will not forget what to ask."
    ),
    "telehealth": (
        "The counselor you connect with is licensed and trained to listen. "
        "The first few minutes are just about getting comfortable. "
        "You set the pace. You can share what you shared with me, or start fresh — "
        "whatever feels right."
    ),
    "community": (
        "When you call the resource line, they will ask a few simple questions "
        "to point you to the right help nearby. It is okay not to have all the answers. "
        "They do this every day and they want to help."
    ),
}


# ---------------------------------------------------------------------------
# THE SIX-PART WARM HANDOFF BUILDER
# ---------------------------------------------------------------------------

def build_warm_handoff(
    handoff_type: str,
    bridge_action: str = "",
    what_they_shared: str = "",
    register: str = "neutral",
    context_shared: bool = False,
) -> Dict[str, Any]:
    """
    Build a multi-part warm handoff, shaped to the person's register.
    Returns the spoken script (in order) plus a single combined string.
    """

    # --- Part 1: ACKNOWLEDGE what they shared ---
    if what_they_shared:
        acknowledge = "Thank you for telling me about this. What you shared matters."
    else:
        acknowledge = "Thank you for trusting me with what you're going through."

    # --- Part 2: AFFIRM the brave/right thing ---
    affirm_by_type = {
        "crisis": "Reaching out right now, in this moment, is one of the bravest things a person can do.",
        "legal": "Standing up for yourself and looking for the right help is the right move.",
        "telehealth": "Choosing to talk to someone takes real strength, and you're doing it.",
        "community": "Asking for help when you need it is a sign of strength, not weakness.",
        "none": "You did something good by reaching out today.",
    }
    affirm = affirm_by_type.get(handoff_type, affirm_by_type["none"])

    # --- Part 3: PREPARE — what to expect next ---
    if handoff_type == "crisis":
        expect = WHAT_TO_EXPECT["crisis"].get(bridge_action_key(bridge_action),
                                              WHAT_TO_EXPECT["crisis"]["988"])
    else:
        expect = WHAT_TO_EXPECT.get(handoff_type, "")

    # --- Part 4: REASSURE — we stay available, no pressure ---
    reassure_by_type = {
        "crisis": "I'm not going anywhere. After you connect, this space is still here for you, anytime.",
        "legal": "And whenever you want to talk it through, before or after, I'm right here.",
        "telehealth": "This space stays open for you, whenever you need it again.",
        "community": "Come back anytime — for anything, big or small. I'm here.",
        "none": "I'm here whenever you need me again. Take care of yourself.",
    }
    reassure = reassure_by_type.get(handoff_type, reassure_by_type["none"])

    if context_shared:
        reassure = "I've shared a short summary so you won't have to start over. " + reassure

    parts = [acknowledge, affirm, expect, reassure]
    parts = [p for p in parts if p]

    # --- Part 5: REGISTER shaping ---
    parts = [shape_register(p, register) for p in parts]

    combined = " ".join(parts)

    return {
        "parts": parts,            # for displaying/speaking in sequence
        "spoken_script": combined, # the full thing to speak aloud
        "handoff_type": handoff_type,
        "register": register,
        "speak": True,             # signal to the frontend to voice it
        "pace": "slow",            # calm delivery
    }


def bridge_action_key(action: str) -> str:
    a = (action or "").lower()
    if "988" in a:
        return "988"
    if "911" in a:
        return "911"
    if "operator" in a or "monitor" in a:
        return "operator"
    return "988"


def shape_register(text: str, register: str) -> str:
    """Mirror the person's register — same warmth, met where they are."""
    if register == "casual":
        t = text
        t = t.replace("I am ", "I'm ").replace("you are ", "you're ")
        t = t.replace("cannot", "can't").replace("do not", "don't")
        t = t.replace("you will ", "you'll ").replace("It is ", "It's ")
        t = t.replace("There is ", "There's ")
        return t
    elif register == "formal":
        t = text
        t = t.replace("I'm ", "I am ").replace("you're ", "you are ")
        t = t.replace("can't", "cannot").replace("don't", "do not")
        t = t.replace("you'll ", "you will ")
        return t
    return text


# ---------------------------------------------------------------------------
# LEARNING LAYER — log handoffs + outcomes so phrasing can improve.
# Humans review; safety-critical wording never auto-changes.
# ---------------------------------------------------------------------------

class HandoffLearning:
    """
    Records every handoff and any outcome signal we get (did they tap the
    bridge? did they come back?). This builds the dataset that lets a human
    reviewer improve the phrasing over time. The system NEVER auto-rewrites
    crisis wording without human review.
    """

    def __init__(self, log_path: Optional[str] = None):
        self.log_path = Path(log_path) if log_path else None
        self.events: List[Dict[str, Any]] = []

    def log_handoff(self, handoff_type: str, register: str, script: str,
                    session_ref: str = "") -> str:
        event_id = f"ho_{int(time.time()*1000)}"
        event = {
            "id": event_id,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "handoff_type": handoff_type,
            "register": register,
            "script_len": len(script),
            "session_ref": session_ref,
            "outcome": None,  # filled in later
        }
        self.events.append(event)
        self._persist()
        return event_id

    def record_outcome(self, event_id: str, outcome: str):
        """outcome: 'bridge_tapped', 'returned', 'no_signal'"""
        for e in self.events:
            if e["id"] == event_id:
                e["outcome"] = outcome
                break
        self._persist()

    def _persist(self):
        if self.log_path:
            try:
                self.log_path.write_text(json.dumps(self.events, indent=2))
            except Exception:
                pass

    def stats(self) -> Dict[str, Any]:
        total = len(self.events)
        tapped = sum(1 for e in self.events if e.get("outcome") == "bridge_tapped")
        by_type: Dict[str, int] = {}
        for e in self.events:
            by_type[e["handoff_type"]] = by_type.get(e["handoff_type"], 0) + 1
        return {
            "total_handoffs": total,
            "bridge_tap_rate": round(100 * tapped / total, 1) if total else 0,
            "by_type": by_type,
        }


# Singleton
_learning = HandoffLearning()

def get_handoff_learning() -> HandoffLearning:
    return _learning


if __name__ == "__main__":
    print("=" * 70)
    print("WARM HANDOFF — CRISIS (casual register)")
    print("=" * 70)
    h = build_warm_handoff(
        handoff_type="crisis",
        bridge_action="call_988",
        what_they_shared="I just feel like I can't do this anymore and nobody cares",
        register="casual",
        context_shared=True,
    )
    for i, part in enumerate(h["parts"], 1):
        print(f"\n[{i}] {part}")
    print(f"\n--- SPOKEN ALOUD ---\n{h['spoken_script']}")

    print("\n" + "=" * 70)
    print("WARM HANDOFF — LEGAL (formal register)")
    print("=" * 70)
    h2 = build_warm_handoff(
        handoff_type="legal",
        what_they_shared="My landlord is trying to evict me without notice",
        register="formal",
        context_shared=True,
    )
    print(h2["spoken_script"])

    print("\n" + "=" * 70)
    print("WARM HANDOFF — TELEHEALTH (neutral)")
    print("=" * 70)
    h3 = build_warm_handoff(handoff_type="telehealth", register="neutral")
    print(h3["spoken_script"])

    print("\n" + "=" * 70)
    print("LEARNING LAYER")
    print("=" * 70)
    L = HandoffLearning()
    eid = L.log_handoff("crisis", "casual", h["spoken_script"], "sess1")
    L.record_outcome(eid, "bridge_tapped")
    L.log_handoff("legal", "formal", h2["spoken_script"], "sess2")
    print(json.dumps(L.stats(), indent=2))
