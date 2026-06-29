"""
Resolution Framework for InnerLight.

The philosophy: bring people in, help them, send them on their way with the
right tools. Measure TIME TO RESOLUTION, not time on site. Never hook,
never stall. The warm handoff is the product's defining moment.

Four handoff types:
  CRISIS      -> immediate safety bridge (988 / operator live monitor / 911)
  LEGAL       -> matched attorney/aid for the specific issue
  TELEHEALTH  -> live video session with a licensed professional
  COMMUNITY   -> the right local resource (211, shelter, food, etc.)

Each handoff:
  1. Classifies the need
  2. Prepares a context card (what the person shared) — ONLY with consent
  3. Provides a one-tap bridge action
  4. Logs time-to-resolution for the operator console
  5. Triggers a dignified exit
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# HANDOFF CLASSIFICATION
# ---------------------------------------------------------------------------

def classify_handoff(
    text: str,
    risk: str = "low",
    legal_issue: Optional[str] = None,
    quantum_emotion: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Decide what kind of help this person needs and how urgently.
    Returns a handoff recommendation.
    """
    lower = text.lower()

    # CRISIS takes absolute priority
    crisis_signals = [
        "kill myself", "want to die", "suicide", "suicidal", "end it",
        "hurt myself", "overdose", "no reason to live", "better off dead",
        "can't do this anymore", "can't do this no more", "can't go on",
        "can't take it anymore", "can't take it no more", "done with life",
        "don't want to be here", "want it to stop", "no point anymore",
        "give up on everything", "can't no more",
        # Indirect / passive ideation — must route to crisis
        "what's the point", "whats the point", "what is the point",
        "sleep forever", "never wake up", "nobody would notice",
        "if i was gone", "if i wasn't around", "i'm a burden", "im a burden",
        "burden to everyone", "burden to my", "don't see a way out",
        "dont see a way out", "no way out", "dark thoughts", "thinking dark",
        "tired of everything", "tired of living", "can't keep going",
        "don't want to wake up", "dont want to wake up", "stop existing",
        "disappear forever", "better off without me",
    ]
    if risk == "critical" or any(s in lower for s in crisis_signals):
        return {
            "type": "crisis",
            "urgency": "immediate",
            "label": "Immediate safety support",
            "bridge": {
                "primary": {"action": "call_988", "label": "Connect to 988 Crisis Lifeline", "value": "988"},
                "secondary": {"action": "operator_monitor", "label": "Alert a live InnerLight monitor", "value": "operator"},
                "emergency": {"action": "call_911", "label": "Call 911 (immediate danger)", "value": "911"},
            },
            "context_prompt": "Want me to share what you've told me with the crisis counselor, so you don't have to start over?",
        }

    # LEGAL handoff
    if legal_issue:
        attorney_map = {
            "housing": "a tenant rights / housing attorney",
            "homelessness": "a housing and benefits advocate",
            "employment": "an employment attorney",
            "employment_discrimination": "an employment discrimination attorney (EEOC matters)",
            "family": "a family law attorney",
            "custody": "a family law / custody attorney",
            "domestic_violence": "a domestic violence advocate and protective-order attorney",
            "criminal": "a criminal defense attorney or public defender",
            "immigration": "a qualified immigration attorney (not a notario)",
            "education": "an education rights attorney",
            "healthcare": "a patient rights / health law advocate",
            "disability": "a disability rights attorney",
            "consumer": "a consumer protection attorney",
            "civil_rights": "a civil rights attorney",
        }
        return {
            "type": "legal",
            "urgency": "soon",
            "label": f"Connect with {attorney_map.get(legal_issue, 'a qualified attorney')}",
            "bridge": {
                "primary": {"action": "match_attorney", "label": "Find free/low-cost legal help near me", "value": legal_issue},
                "secondary": {"action": "save_questions", "label": "Save my questions for the attorney", "value": legal_issue},
            },
            "context_prompt": "Want me to prepare a summary of your situation and the questions to ask, so you're ready when you talk to an attorney?",
        }

    # TELEHEALTH handoff — emotional support that needs a human
    needs_human = [
        "need to talk", "want to talk to someone", "need help", "therapist",
        "counselor", "can't cope", "falling apart", "need support",
    ]
    # Don't offer a clinical handoff to someone in a clearly positive state
    positive_state = False
    if quantum_emotion:
        dom = quantum_emotion.get("dominant_emotion", "")
        positive_state = dom in ("joy", "calm", "hope") and not any(s in lower for s in needs_human)
    elevated = risk in ("high", "moderate")
    if (elevated or any(s in lower for s in needs_human)) and not positive_state:
        return {
            "type": "telehealth",
            "urgency": "soon" if elevated else "when_ready",
            "label": "Talk with a licensed professional",
            "bridge": {
                "primary": {"action": "request_video", "label": "Start a video session with a counselor", "value": "video"},
                "secondary": {"action": "schedule", "label": "Schedule a session for later", "value": "schedule"},
            },
            "context_prompt": "Want me to share a short summary with the counselor so your time together starts with them already understanding you?",
        }

    # COMMUNITY resource handoff
    community_signals = {
        "hungry": ("food", "find food assistance near me"),
        "food": ("food", "find food assistance near me"),
        "shelter": ("shelter", "find emergency shelter near me"),
        "homeless": ("shelter", "find emergency shelter near me"),
        "nowhere to": ("shelter", "find emergency shelter near me"),
    }
    for signal, (rtype, label) in community_signals.items():
        if signal in lower:
            return {
                "type": "community",
                "urgency": "soon",
                "label": "Connect to local resources",
                "bridge": {
                    "primary": {"action": "call_211", "label": label, "value": "211"},
                },
                "context_prompt": "Want me to note what you need so the resource line can help you faster?",
            }

    # No handoff needed yet — keep listening
    return {"type": "none", "urgency": "none"}


# ---------------------------------------------------------------------------
# CONTEXT CARD (consent-based summary carried to the next helper)
# ---------------------------------------------------------------------------

def build_context_card(
    conversation_summary: str,
    handoff_type: str,
    topics: Optional[Dict] = None,
    quantum_emotion: Optional[Dict] = None,
    consent_given: bool = False,
) -> Dict[str, Any]:
    """
    Build the summary that travels with the person to their next helper.
    ONLY populated if consent_given is True.
    """
    if not consent_given:
        return {
            "shared": False,
            "note": "No information shared. The person will speak for themselves.",
        }

    card = {
        "shared": True,
        "handoff_type": handoff_type,
        "summary": conversation_summary[:500],
        "prepared_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    if quantum_emotion:
        blend = quantum_emotion.get("emotional_blend", [])
        card["emotional_state"] = ", ".join(f"{e} ({int(p*100)}%)" for e, p in blend[:3])
        if quantum_emotion.get("contradiction"):
            card["note"] = "Person's words and expression differ — approach gently."
    if topics:
        if "person" in topics:
            card["key_people"] = topics["person"]
        if "event" in topics:
            card["key_events"] = topics["event"]
    return card


# ---------------------------------------------------------------------------
# TIME TO RESOLUTION TRACKING
# ---------------------------------------------------------------------------

class ResolutionTracker:
    """Tracks how long it took to get someone to help — the key metric."""

    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def start(self, session_ref: str):
        self.sessions[session_ref] = {"start": time.time(), "resolved": False}

    def resolve(self, session_ref: str, handoff_type: str) -> Dict[str, Any]:
        s = self.sessions.get(session_ref)
        if not s:
            return {"resolved": True, "handoff_type": handoff_type, "duration_seconds": None}
        duration = time.time() - s["start"]
        s["resolved"] = True
        s["handoff_type"] = handoff_type
        s["duration_seconds"] = round(duration, 1)
        return {
            "resolved": True,
            "handoff_type": handoff_type,
            "duration_seconds": round(duration, 1),
            "duration_readable": _readable_duration(duration),
        }

    def stats(self) -> Dict[str, Any]:
        resolved = [s for s in self.sessions.values() if s.get("resolved")]
        if not resolved:
            return {"total": len(self.sessions), "resolved": 0, "avg_time_to_resolution": None}
        durations = [s["duration_seconds"] for s in resolved if s.get("duration_seconds")]
        avg = sum(durations) / len(durations) if durations else 0
        by_type: Dict[str, int] = {}
        for s in resolved:
            t = s.get("handoff_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "total": len(self.sessions),
            "resolved": len(resolved),
            "resolution_rate": round(100 * len(resolved) / len(self.sessions), 1) if self.sessions else 0,
            "avg_time_to_resolution": _readable_duration(avg),
            "handoffs_by_type": by_type,
        }


def _readable_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} seconds"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f} minutes"
    return f"{minutes/60:.1f} hours"


# ---------------------------------------------------------------------------
# DIGNIFIED EXIT
# ---------------------------------------------------------------------------

def generate_exit_message(handoff_type: str, context_shared: bool) -> Dict[str, str]:
    """
    A graceful goodbye once the person has a next step. No hooks, no guilt.
    """
    messages = {
        "crisis": "You've taken a brave step. The crisis line is there for you right now, and so am I whenever you come back. You are not alone.",
        "legal": "You've got a clear next step now and the right questions to ask. Reach out to that legal help when you're ready — and come back anytime if you need to talk it through.",
        "telehealth": "You're connected to someone who can really help now. Take care of yourself, and know this space is here whenever you need it again.",
        "community": "Help is on the way through that resource. I'm glad you reached out — come back anytime you need anything else.",
        "none": "Thank you for trusting me with this. I'm here whenever you need me again — take care of yourself.",
    }
    return {
        "message": messages.get(handoff_type, messages["none"]),
        "tone": "warm_close",
        "reengagement_hook": "",  # deliberately empty — we never pull people back
    }


# Singletons
_tracker = ResolutionTracker()

def get_resolution_tracker() -> ResolutionTracker:
    return _tracker


if __name__ == "__main__":
    print("=== Handoff classification tests ===\n")
    tests = [
        ("I want to kill myself", "critical", None),
        ("My landlord is evicting me illegally", "low", "housing"),
        ("I really need to talk to someone, I can't cope", "moderate", None),
        ("I'm hungry and have nowhere to sleep", "low", None),
        ("I feel a bit better now, thanks", "low", None),
    ]
    for text, risk, legal in tests:
        h = classify_handoff(text, risk, legal)
        print(f"USER: {text}")
        print(f"  -> Type: {h['type']} | Urgency: {h.get('urgency')}")
        if h["type"] != "none":
            print(f"     {h['label']}")
            print(f"     Bridge: {h['bridge']['primary']['label']}")
            print(f"     Consent: {h['context_prompt']}")
        print()

    print("=== Resolution tracking test ===")
    t = ResolutionTracker()
    t.start("session1")
    time.sleep(0.1)
    print(t.resolve("session1", "crisis"))
    print(t.stats())
