"""
Quantum-Inspired Emotion Engine for InnerLight.

This is NOT quantum computing — no qubits, no quantum hardware. It is a
classical model designed using PRINCIPLES borrowed from quantum mechanics,
which gives InnerLight a genuinely different and more honest way to read
human emotion than any competitor.

Three quantum ideas, applied:

1. SUPERPOSITION
   A person is never just "sad." They are a blend — maybe 55% grief,
   25% anger, 20% relief. Instead of collapsing to one label immediately,
   InnerLight holds all emotional possibilities at once, each with a
   probability amplitude, and only "collapses" to a response when there is
   enough signal.

2. ENTANGLEMENT
   Text, face, and voice are not read independently. They are linked. A
   shift in one instantly changes how the others are interpreted. If the
   voice trembles, the same words mean something different. The signals
   are entangled.

3. INTERFERENCE
   When signals agree, their amplitudes reinforce (constructive
   interference) and confidence rises. When they conflict — words say
   "fine," face says "sad" — they interfere destructively, and the model
   surfaces that contradiction instead of hiding it.

The output is an "emotional state vector" — a probability distribution over
emotions — plus a measure of coherence (how much the signals agree). The
sound engine and conversation engine both read this vector.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# The emotional basis states (like quantum basis states)
EMOTION_BASIS = [
    "joy", "sadness", "anger", "fear", "calm",
    "grief", "anxiety", "hope", "numbness", "overwhelm",
]


# ---------------------------------------------------------------------------
# SIGNAL → AMPLITUDE MAPPING
# ---------------------------------------------------------------------------

# Map raw text emotion words to basis-state contributions
TEXT_EMOTION_MAP = {
    "happy": {"joy": 0.8, "hope": 0.2},
    "joy": {"joy": 1.0},
    "excited": {"joy": 0.7, "hope": 0.3},
    "grateful": {"joy": 0.5, "calm": 0.3, "hope": 0.2},
    "sad": {"sadness": 0.8, "grief": 0.2},
    "depressed": {"sadness": 0.6, "numbness": 0.4},
    "grieving": {"grief": 0.9, "sadness": 0.1},
    "heartbroken": {"grief": 0.7, "sadness": 0.3},
    "angry": {"anger": 0.9, "overwhelm": 0.1},
    "furious": {"anger": 1.0},
    "frustrated": {"anger": 0.6, "overwhelm": 0.4},
    "scared": {"fear": 0.9, "anxiety": 0.1},
    "afraid": {"fear": 0.9, "anxiety": 0.1},
    "anxious": {"anxiety": 0.8, "fear": 0.2},
    "nervous": {"anxiety": 0.7, "fear": 0.3},
    "worried": {"anxiety": 0.7, "fear": 0.3},
    "overwhelmed": {"overwhelm": 0.8, "anxiety": 0.2},
    "calm": {"calm": 1.0},
    "peaceful": {"calm": 0.8, "hope": 0.2},
    "hopeful": {"hope": 0.9, "joy": 0.1},
    "hopeless": {"sadness": 0.5, "numbness": 0.5},
    "numb": {"numbness": 1.0},
    "empty": {"numbness": 0.7, "sadness": 0.3},
    "lonely": {"sadness": 0.6, "grief": 0.4},
    "alone": {"sadness": 0.5, "fear": 0.3, "grief": 0.2},
    "exhausted": {"overwhelm": 0.5, "numbness": 0.5},
    "stressed": {"anxiety": 0.6, "overwhelm": 0.4},
}

# Map face-api emotions to basis states
FACE_EMOTION_MAP = {
    "happy": {"joy": 0.8, "hope": 0.2},
    "sad": {"sadness": 0.7, "grief": 0.3},
    "angry": {"anger": 0.9, "overwhelm": 0.1},
    "fearful": {"fear": 0.8, "anxiety": 0.2},
    "disgusted": {"anger": 0.6, "overwhelm": 0.4},
    "surprised": {"fear": 0.4, "joy": 0.3, "anxiety": 0.3},
    "neutral": {"calm": 0.6, "numbness": 0.4},
}

# Voice tone features → basis states
# (derived from pitch variance, speaking rate, energy)
def voice_features_to_amplitudes(features: Dict[str, float]) -> Dict[str, float]:
    """
    Convert voice acoustic features into emotional amplitudes.
    features: {pitch_variance, energy, rate, tremor}
    """
    amps: Dict[str, float] = {}
    pitch_var = features.get("pitch_variance", 0.5)
    energy = features.get("energy", 0.5)
    rate = features.get("rate", 0.5)
    tremor = features.get("tremor", 0.0)

    # High energy + high pitch variance = joy or anger (disambiguated by text/face)
    if energy > 0.6 and pitch_var > 0.6:
        amps["joy"] = amps.get("joy", 0) + 0.4
        amps["anger"] = amps.get("anger", 0) + 0.3
    # Low energy + low pitch variance = sadness/numbness
    if energy < 0.4 and pitch_var < 0.4:
        amps["sadness"] = amps.get("sadness", 0) + 0.4
        amps["numbness"] = amps.get("numbness", 0) + 0.3
    # Tremor = fear/anxiety
    if tremor > 0.3:
        amps["fear"] = amps.get("fear", 0) + tremor * 0.5
        amps["anxiety"] = amps.get("anxiety", 0) + tremor * 0.4
    # Fast rate = anxiety/overwhelm
    if rate > 0.65:
        amps["anxiety"] = amps.get("anxiety", 0) + 0.3
        amps["overwhelm"] = amps.get("overwhelm", 0) + 0.2
    # Slow rate + low energy = grief
    if rate < 0.4 and energy < 0.4:
        amps["grief"] = amps.get("grief", 0) + 0.3
    # Moderate everything = calm
    if 0.4 <= energy <= 0.6 and 0.4 <= pitch_var <= 0.6 and tremor < 0.2:
        amps["calm"] = amps.get("calm", 0) + 0.4

    return amps


# ---------------------------------------------------------------------------
# THE QUANTUM-INSPIRED STATE VECTOR
# ---------------------------------------------------------------------------

class EmotionalStateVector:
    """
    Holds emotional possibilities in superposition. Each basis emotion has
    an amplitude. The vector is normalized so probabilities sum to 1.
    """

    def __init__(self):
        self.amplitudes: Dict[str, float] = {e: 0.0 for e in EMOTION_BASIS}

    def add_signal(self, contributions: Dict[str, float], weight: float = 1.0):
        """Add a signal's contributions to the superposition (entanglement)."""
        for emotion, amp in contributions.items():
            if emotion in self.amplitudes:
                self.amplitudes[emotion] += amp * weight

    def normalize(self):
        """Normalize so probabilities sum to 1 (like a quantum state)."""
        total = sum(self.amplitudes.values())
        if total > 0:
            for e in self.amplitudes:
                self.amplitudes[e] /= total

    def probabilities(self) -> Dict[str, float]:
        """Return the probability distribution over emotions."""
        self.normalize()
        return dict(self.amplitudes)

    def collapse(self) -> Tuple[str, float]:
        """
        'Measure' the state — collapse to the most probable emotion.
        Returns (emotion, probability).
        """
        self.normalize()
        if not any(self.amplitudes.values()):
            return ("calm", 0.0)
        top = max(self.amplitudes.items(), key=lambda kv: kv[1])
        return top

    def top_blend(self, n: int = 3) -> List[Tuple[str, float]]:
        """Return the top n emotions as a blend (superposition view)."""
        self.normalize()
        ranked = sorted(self.amplitudes.items(), key=lambda kv: kv[1], reverse=True)
        return [(e, round(p, 3)) for e, p in ranked[:n] if p > 0.01]

    def coherence(self) -> float:
        """
        Measure how 'coherent' the signals are. High coherence = signals
        agree (one dominant emotion). Low coherence = conflict/contradiction.
        Uses normalized entropy: low entropy = high coherence.
        """
        self.normalize()
        probs = [p for p in self.amplitudes.values() if p > 0]
        if not probs:
            return 0.0
        entropy = -sum(p * math.log(p) for p in probs)
        max_entropy = math.log(len(EMOTION_BASIS))
        # Coherence is inverse of normalized entropy
        return round(1.0 - (entropy / max_entropy), 3) if max_entropy > 0 else 1.0


# ---------------------------------------------------------------------------
# THE ENGINE
# ---------------------------------------------------------------------------

class QuantumEmotionEngine:
    """
    Combines text, face, and voice into a single quantum-inspired
    emotional state vector with entanglement and interference.
    """

    # Signal weights — face and voice often more honest than words
    WEIGHT_TEXT = 1.0
    WEIGHT_FACE = 1.2
    WEIGHT_VOICE = 1.1

    def analyze(
        self,
        text_emotion: Optional[str] = None,
        face_emotion: Optional[str] = None,
        face_scores: Optional[Dict[str, float]] = None,
        voice_features: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Produce the emotional state vector from all available signals.
        """
        state = EmotionalStateVector()
        signals_present = []

        # TEXT signal
        if text_emotion:
            contrib = TEXT_EMOTION_MAP.get(text_emotion.lower())
            if contrib:
                state.add_signal(contrib, self.WEIGHT_TEXT)
                signals_present.append("text")

        # FACE signal — use full score distribution if available (richer)
        if face_scores:
            for face_emo, score in face_scores.items():
                contrib = FACE_EMOTION_MAP.get(face_emo.lower())
                if contrib and score > 0.05:
                    weighted = {k: v * score for k, v in contrib.items()}
                    state.add_signal(weighted, self.WEIGHT_FACE)
            signals_present.append("face")
        elif face_emotion:
            contrib = FACE_EMOTION_MAP.get(face_emotion.lower())
            if contrib:
                state.add_signal(contrib, self.WEIGHT_FACE)
                signals_present.append("face")

        # VOICE signal
        if voice_features:
            contrib = voice_features_to_amplitudes(voice_features)
            if contrib:
                state.add_signal(contrib, self.WEIGHT_VOICE)
                signals_present.append("voice")

        # Collapse and analyze
        dominant, dominant_prob = state.collapse()
        blend = state.top_blend(3)
        coherence = state.coherence()

        # INTERFERENCE: detect contradiction
        contradiction = None
        if len(signals_present) >= 2:
            # Check if positive and negative emotions both have significant presence
            positive = {"joy", "calm", "hope"}
            negative = {"sadness", "anger", "fear", "grief", "anxiety", "overwhelm", "numbness"}
            pos_mass = sum(p for e, p in state.probabilities().items() if e in positive)
            neg_mass = sum(p for e, p in state.probabilities().items() if e in negative)
            # Contradiction when both sides carry real weight (destructive interference)
            if pos_mass > 0.25 and neg_mass > 0.25:
                contradiction = self._describe_contradiction(blend)
            elif coherence < 0.35:
                contradiction = self._describe_contradiction(blend)

        return {
            "dominant_emotion": dominant,
            "dominant_probability": round(dominant_prob, 3),
            "emotional_blend": blend,  # the superposition
            "coherence": coherence,    # how much signals agree
            "signals_used": signals_present,
            "contradiction": contradiction,
            "state_vector": state.probabilities(),
            "music_target": self._music_target(dominant, blend),
        }

    @staticmethod
    def _describe_contradiction(blend: List[Tuple[str, float]]) -> str:
        if len(blend) < 2:
            return None
        e1, e2 = blend[0][0], blend[1][0]
        positive = {"joy", "calm", "hope"}
        negative = {"sadness", "anger", "fear", "grief", "anxiety", "overwhelm", "numbness"}
        if (e1 in positive and e2 in negative) or (e1 in negative and e2 in positive):
            return f"signals_split_{e1}_{e2}"
        return None

    @staticmethod
    def _music_target(dominant: str, blend: List[Tuple[str, float]]) -> str:
        """Map the emotional state to a music search target."""
        music_map = {
            "joy": "uplifting warm acoustic",
            "sadness": "gentle comforting piano",
            "grief": "soft healing ambient",
            "anger": "grounding calming slow",
            "fear": "safe reassuring soft",
            "anxiety": "slow breathing calm ambient",
            "calm": "peaceful flowing ambient",
            "hope": "gentle hopeful warm",
            "numbness": "gentle awakening soft melodic",
            "overwhelm": "simple spacious quiet calm",
        }
        return music_map.get(dominant, "calm peaceful ambient")


# Singleton
_engine = QuantumEmotionEngine()

def get_quantum_engine() -> QuantumEmotionEngine:
    return _engine


if __name__ == "__main__":
    engine = QuantumEmotionEngine()

    print("=== Test 1: Words say fine, face says sad (contradiction) ===")
    r = engine.analyze(
        text_emotion="calm",
        face_scores={"sad": 0.7, "neutral": 0.2, "happy": 0.1},
    )
    print(f"Dominant: {r['dominant_emotion']} ({r['dominant_probability']})")
    print(f"Blend: {r['emotional_blend']}")
    print(f"Coherence: {r['coherence']}")
    print(f"Contradiction: {r['contradiction']}")
    print(f"Music target: {r['music_target']}")

    print("\n=== Test 2: All signals agree on grief ===")
    r = engine.analyze(
        text_emotion="grieving",
        face_scores={"sad": 0.8, "neutral": 0.2},
        voice_features={"pitch_variance": 0.3, "energy": 0.3, "rate": 0.35, "tremor": 0.2},
    )
    print(f"Dominant: {r['dominant_emotion']} ({r['dominant_probability']})")
    print(f"Blend: {r['emotional_blend']}")
    print(f"Coherence: {r['coherence']}")
    print(f"Music target: {r['music_target']}")

    print("\n=== Test 3: Complex blend ===")
    r = engine.analyze(
        text_emotion="overwhelmed",
        face_scores={"angry": 0.4, "sad": 0.3, "fearful": 0.3},
        voice_features={"pitch_variance": 0.7, "energy": 0.7, "rate": 0.7, "tremor": 0.3},
    )
    print(f"Dominant: {r['dominant_emotion']} ({r['dominant_probability']})")
    print(f"Blend (superposition): {r['emotional_blend']}")
    print(f"Coherence: {r['coherence']}")
    print(f"Music target: {r['music_target']}")
