"""
Compatibility Clarion text-emotion engine.

Hardware/audio/vision Clarion modules can replace this later; this baseline is
small, deterministic, importable, and suitable for tests.
"""

from __future__ import annotations

from crisis_response_core import CrisisResponseCore


class Clarion:
    def __init__(self):
        self.crisis_core = CrisisResponseCore()

    def evaluate(self, text: str):
        crisis = self.crisis_core.evaluate(text)
        if crisis.risk == "critical":
            return {"category": crisis.category, "severity": crisis.severity, "confidence": 0.99}
        if crisis.risk == "high":
            return {"category": crisis.category, "severity": crisis.severity, "confidence": 0.9}
        if crisis.risk == "moderate":
            return {"category": crisis.category, "severity": crisis.severity, "confidence": 0.75}

        text_lower = (text or "").lower()
        if any(word in text_lower for word in ("suicide", "kill myself", "end my life", "self harm")):
            return {"category": "crisis", "severity": 10, "confidence": 0.95}
        if any(word in text_lower for word in ("panic", "afraid", "anxious", "overwhelmed")):
            return {"category": "anxious", "severity": 8, "confidence": 0.8}
        if any(word in text_lower for word in ("sad", "alone", "hopeless", "disconnected")):
            return {"category": "sad", "severity": 6, "confidence": 0.7}
        if any(word in text_lower for word in ("good", "okay", "fine", "calm")):
            return {"category": "stable", "severity": 2, "confidence": 0.65}
        return {"category": "unclear", "severity": 4, "confidence": 0.4}
