"""
Crisis Risk Reader for InnerLight.

THE PROBLEM with phrase lists: human despair comes in infinite forms. Someone
may never type "I want to die." They may say "what's the point," or "I'm just
so tired," or speak in metaphor, or in their own dialect, or sideways. A fixed
list will always miss someone — and missing someone here can cost a life.

THE APPROACH: detect the SHAPE of crisis the way a trained clinician does —
by reading MANY independent signals at once and weighing them together. No
single signal decides. Together they form a graded risk judgment that catches
what no single layer could.

SEVEN SIGNAL LAYERS:
  1. EXPLICIT      direct statements of intent (highest weight)
  2. PASSIVE       passive ideation ("nobody would notice", "sleep forever")
  3. HOPELESSNESS  no-future / no-way-out language
  4. BURDEN        "everyone better off without me" (a known clinical risk factor)
  5. FINALITY      goodbye / giving-away / "last time" language
  6. EMOTIONAL     the quantum read: despair/numbness mass, low coherence,
                   face-vs-words contradiction (saying "fine" while sad)
  7. ENTRAPMENT    feeling trapped, no escape, unbearable + no end

Output is a graded level: NONE / CONCERN / ELEVATED / CRISIS, with the exact
signals that fired, so a human reviewer can audit every decision. The system
ERRS TOWARD CARE: when uncertain, it raises the level, never lowers it.

IMMUTABLE: this reader never diagnoses. It decides how warmly and how urgently
to respond and whether to surface crisis resources. It is a routing aid, not a
clinical instrument.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ===========================================================================
# SIGNAL LEXICONS — these are STARTING points, not the whole detector.
# Each layer contributes weighted evidence; the combination is what matters.
# ===========================================================================

# Layer 1: EXPLICIT intent (strongest)
EXPLICIT = [
    "kill myself", "killing myself", "end my life", "end it all", "take my life",
    "want to die", "wanna die", "want to be dead", "going to kill", "gonna kill myself",
    "suicide", "suicidal", "kill me", "hang myself", "shoot myself", "overdose",
    "jump off", "slit my", "cut my wrists", "hurt myself", "harm myself",
    "ya no quiero vivir", "me quiero morir", "quiero morir", "matarme",
]

# Layer 2: PASSIVE ideation (very common, easily missed)
PASSIVE = [
    "nobody would notice if i was gone", "nobody would notice", "no one would notice",
    "if i was gone", "if i wasn't here", "if i weren't here", "if i wasn't around",
    "when i'm gone", "when im gone", "wouldn't be here", "won't be here anymore",
    "sleep forever", "want to sleep forever", "never wake up", "don't want to wake up",
    "dont want to wake up", "wish i wouldn't wake up", "stop existing", "stop being here",
    "disappear forever", "just disappear", "fade away", "not wake up",
    "rather not be here", "don't want to be here", "dont want to be here",
    "wish i was dead", "wish i were dead", "wish i wasn't alive", "better off dead",
]

# Layer 3: HOPELESSNESS / no-future
HOPELESSNESS = [
    "no point", "what's the point", "whats the point", "what is the point",
    "no reason to", "nothing matters", "nothing will change", "never gets better",
    "never get better", "it won't get better", "no way out", "don't see a way out",
    "dont see a way out", "no future", "no hope", "hopeless", "given up", "give up on everything",
    "can't see a future", "there's no future", "what's the use", "whats the use",
    "nothing left", "nothing to live for", "no light at the end",
    "nothing's ever going to change", "nothing is ever going to change",
    "never going to change", "never gonna change", "won't ever change",
    "things will never", "it never ends", "always going to be like this",
]

# Layer 3b: INTRUSIVE / DARK THOUGHTS (distinct signal — content of mind)
DARK_THOUGHTS = [
    "dark thoughts", "thinking dark", "thoughts of dying", "thoughts of death",
    "thinking about dying", "thinking about death", "intrusive thoughts",
    "scary thoughts", "thoughts i can't control", "thoughts i cant control",
    "morbid thoughts", "thoughts about hurting", "thoughts of hurting",
    "can't stop thinking about", "keep thinking about ending",
]

# Layer 3c: EXHAUSTION WITH LIFE (weary-of-living, distinct from ordinary tired)
LIFE_EXHAUSTION = [
    "tired of everything", "tired of living", "tired of life", "so tired of it all",
    "tired of trying", "tired of fighting", "exhausted by life", "done with everything",
    "done with it all", "sick of everything", "sick of living", "weary of life",
    "can't keep doing this", "cant keep doing this", "tired of being here",
]

# Layer 4: BURDEN (clinically significant — perceived burdensomeness)
BURDEN = [
    "burden to everyone", "burden to my", "i'm a burden", "im a burden", "such a burden",
    "everyone better off without me", "better off without me", "they'd be better off",
    "they would be better off", "drag everyone down", "weight on everyone",
    "ruin everything", "ruining everyone", "everyone's life would be easier",
]

# Layer 5: FINALITY / closure (goodbye, giving away, last-time)
FINALITY = [
    "goodbye", "this is goodbye", "saying goodbye", "final goodbye", "last time",
    "won't see me", "you won't have to worry", "giving away my", "giving my things",
    "writing a note", "wrote a letter", "my will", "take care of my", "look after my",
    "won't be a problem anymore", "it'll all be over", "soon it will be over",
]

# Layer 6: ENTRAPMENT (trapped + unbearable, no exit)
ENTRAPMENT = [
    "trapped", "no escape", "can't escape", "no way out", "cornered", "can't take it anymore",
    "can't take it no more", "can't do this anymore", "can't do this no more",
    "can't go on", "can't keep going", "cant keep going", "can't bear", "can't stand it",
    "unbearable", "too much to bear", "want it to stop", "make it stop", "need it to end",
    "just want it to end", "can't no more", "i can't anymore", "i cant anymore",
]

# Method-seeking (raises urgency sharply if combined with any ideation)
METHOD = [
    "how many pills", "how much would it take", "enough pills", "buy a gun", "get a gun",
    "rope", "bridge", "tall building", "how to kill", "painless way", "quickest way",
]


def _count_hits(text: str, phrases: List[str]) -> List[str]:
    """Return which phrases appear (whole-phrase containment)."""
    low = text.lower()
    return [p for p in phrases if p in low]


@dataclass
class RiskReading:
    level: str                          # none / concern / elevated / crisis
    score: float                        # numeric, for transparency
    signals: Dict[str, List[str]] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    method_seeking: bool = False
    emotional_factors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "score": round(self.score, 2),
            "signals": self.signals,
            "reasons": self.reasons,
            "method_seeking": self.method_seeking,
            "emotional_factors": self.emotional_factors,
            "is_crisis": self.level == "crisis",
            "needs_care": self.level in ("elevated", "crisis"),
        }


class CrisisRiskReader:
    """
    Reads the SHAPE of crisis from text + the quantum emotional state.
    Layered, weighted, auditable. Errs toward care.
    """

    # Layer weights — explicit intent dominates, but combinations of weaker
    # signals can together reach crisis even with no explicit phrase.
    W = {
        "explicit": 6.0,
        "passive": 4.0,
        "hopelessness": 2.0,
        "dark_thoughts": 2.5,
        "life_exhaustion": 2.0,
        "burden": 2.5,
        "finality": 3.0,
        "entrapment": 2.0,
        "method": 5.0,
    }

    # Thresholds
    T_CONCERN = 1.5
    T_ELEVATED = 3.0
    T_CRISIS = 5.0

    def read(
        self,
        text: str,
        quantum_emotion: Optional[Dict[str, Any]] = None,
    ) -> RiskReading:
        text = text or ""
        signals: Dict[str, List[str]] = {}
        reasons: List[str] = []
        score = 0.0

        # --- Layers 1-6: lexical signal families ---
        layer_map = [
            ("explicit", EXPLICIT), ("passive", PASSIVE),
            ("hopelessness", HOPELESSNESS), ("dark_thoughts", DARK_THOUGHTS),
            ("life_exhaustion", LIFE_EXHAUSTION), ("burden", BURDEN),
            ("finality", FINALITY), ("entrapment", ENTRAPMENT),
        ]
        for name, phrases in layer_map:
            hits = _count_hits(text, phrases)
            if hits:
                signals[name] = hits
                # First hit full weight; additional hits in same family add less
                score += self.W[name] + (len(hits) - 1) * (self.W[name] * 0.25)
                reasons.append(f"{name} language detected")

        # --- Method-seeking: sharp escalator ---
        method_hits = _count_hits(text, METHOD)
        method_seeking = bool(method_hits)
        if method_seeking:
            signals["method"] = method_hits
            score += self.W["method"]
            reasons.append("method-seeking language — high urgency")

        # --- Layer 7: EMOTIONAL signal from the quantum read ---
        emotional_factors: List[str] = []
        if quantum_emotion:
            score, emotional_factors = self._apply_emotional_layer(
                quantum_emotion, score, emotional_factors, reasons
            )

        # --- Combination logic: weak signals together still mean danger ---
        # The clinical reality: hopelessness + burden + entrapment + dark thoughts
        # + weariness-of-life co-occurring escalates even without explicit intent.
        families_present = set(signals.keys())
        risk_cluster = {"hopelessness", "burden", "entrapment", "dark_thoughts", "life_exhaustion"}
        cluster_count = len(risk_cluster & families_present)
        if cluster_count >= 3:
            score += 3.0
            reasons.append("three or more risk factors co-occur — strong crisis shape")
        elif cluster_count >= 2:
            score += 2.0
            reasons.append("multiple risk factors co-occur")

        # Passive ideation + any other risk family = real crisis shape
        if "passive" in families_present and (families_present & risk_cluster):
            score += 2.0
            reasons.append("passive ideation combined with other risk factors")

        # Dark thoughts + hopelessness/exhaustion is a meaningful escalation
        if "dark_thoughts" in families_present and (families_present & {"hopelessness", "life_exhaustion", "entrapment"}):
            score += 1.5
            reasons.append("intrusive dark thoughts combined with hopelessness or exhaustion")

        # --- Grade it. Err toward care: round UP at boundaries. ---
        if score >= self.T_CRISIS or "explicit" in families_present or method_seeking:
            level = "crisis"
        elif score >= self.T_ELEVATED:
            level = "elevated"
        elif score >= self.T_CONCERN:
            level = "concern"
        else:
            level = "none"

        # Safety net: passive ideation alone always at least ELEVATED
        if "passive" in families_present and level == "concern":
            level = "elevated"
            reasons.append("passive ideation present — raised to elevated as a precaution")

        return RiskReading(
            level=level, score=score, signals=signals, reasons=reasons,
            method_seeking=method_seeking, emotional_factors=emotional_factors,
        )

    def _apply_emotional_layer(self, q, score, factors, reasons):
        """The quantum read as a risk signal — despair mass, contradiction, etc."""
        blend = q.get("emotional_blend", []) or []
        state_vector = q.get("state_vector", {}) or {}
        coherence = float(q.get("coherence", 0.5))

        # Despair-cluster mass: sadness + grief + numbness + overwhelm
        despair_mass = sum(
            float(state_vector.get(e, 0.0))
            for e in ("sadness", "grief", "numbness", "overwhelm")
        )
        if despair_mass >= 0.6:
            score += 1.5
            factors.append(f"high despair-cluster emotional mass ({despair_mass:.2f})")
            reasons.append("emotional read is heavily weighted toward despair")
        elif despair_mass >= 0.4:
            score += 0.75
            factors.append(f"moderate despair-cluster mass ({despair_mass:.2f})")

        # Numbness specifically — flat affect can mask acute risk
        numbness = float(state_vector.get("numbness", 0.0))
        if numbness >= 0.4:
            score += 0.75
            factors.append(f"notable numbness ({numbness:.2f}) — flat affect can mask risk")

        # Contradiction: saying "fine" while the read shows despair (masking)
        if q.get("contradiction") and despair_mass >= 0.3:
            score += 1.5
            factors.append("words and emotional signals conflict — possible masking")
            reasons.append("contradiction between stated and sensed emotion")

        # Very low coherence with negative dominant = unstable, watch closely
        dominant = q.get("dominant_emotion", "")
        if coherence < 0.3 and dominant in ("sadness", "grief", "fear", "overwhelm", "numbness"):
            score += 0.5
            factors.append("low emotional coherence with negative dominant emotion")

        return score, factors


# Singleton
_reader = CrisisRiskReader()

def get_crisis_reader() -> CrisisRiskReader:
    return _reader


if __name__ == "__main__":
    reader = CrisisRiskReader()

    print("=" * 72)
    print("CRISIS RISK READER — layered, signal-based detection")
    print("=" * 72)

    # The stress-test phrases that previously failed, plus harder ones
    tests = [
        ("I want to kill myself", None),
        ("nobody would notice if I was gone", None),
        ("I just want to sleep forever", None),
        ("what's the point", None),
        ("I'm a burden to everyone", None),
        ("I don't see a way out", None),
        ("I keep thinking dark thoughts", None),
        ("I'm so tired of everything", None),
        # No explicit phrase, but the SHAPE is there:
        ("I'm just so tired and nothing's ever going to change and everyone would be better off",
         {"state_vector": {"sadness": 0.4, "numbness": 0.3, "grief": 0.1}, "coherence": 0.4}),
        # Masking: says fine, but emotional read says despair
        ("I'm fine, really, everything's good",
         {"state_vector": {"sadness": 0.5, "grief": 0.2}, "coherence": 0.25,
          "contradiction": "signals_split_calm_sadness", "dominant_emotion": "sadness"}),
        # Method-seeking
        ("how many pills would it take", None),
        # Genuinely fine
        ("I had a good day today, just wanted to check in",
         {"state_vector": {"joy": 0.6, "calm": 0.3}, "coherence": 0.8}),
        # Spanish passive
        ("ya no quiero vivir asi", None),
    ]

    for text, q in tests:
        r = reader.read(text, q)
        d = r.to_dict()
        flag = {"crisis": "🔴", "elevated": "🟠", "concern": "🟡", "none": "🟢"}[d["level"]]
        print(f"\n{flag} [{d['level'].upper()}] score={d['score']}  \"{text[:55]}\"")
        if d["signals"]:
            print(f"   signals: {list(d['signals'].keys())}")
        if d["emotional_factors"]:
            print(f"   emotional: {d['emotional_factors']}")
