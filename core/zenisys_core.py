"""
ZENISYS — Therapeutic Sound Engine (standalone core).

Zenisys is a therapeutic instrument in its own right. It can run standalone
(a person chooses a state, or just sits in it) OR be driven live by
InnerLight's emotional read. Either way, the SAME core decides what the
sound should actually do.

This is not "pick a playlist." It computes, for any emotional state, the
real sound PARAMETERS grounded in how sound affects the nervous system:

  TEMPO ENTRAINMENT   Heart rate and breath synchronize to rhythm. Music
                      at 60-70 BPM pulls the body toward a resting pulse.
                      To calm someone activated, we don't jump straight to
                      slow — we meet their tempo, then gradually slow it
                      (the ISO principle from music therapy).

  HARMONIC SAFETY     Consonance, drones, and slow chord motion signal
                      safety. Dissonance and sudden change signal threat.
                      Calm states get wide consonant intervals and slow
                      harmonic rhythm.

  SPECTRAL SOFTNESS   Rolled-off highs, no sharp transients, gentle
                      attack/release. The absence of startle cues is itself
                      calming.

  BINAURAL / BRAINWAVE Two near-frequencies create a perceived beat that
                      can encourage brainwave states: delta (deep rest),
                      theta (meditative), alpha (relaxed), beta (alert).

  SOLFEGGIO / TUNING  Specific frequencies (396/432/528 Hz) many people
                      find meaningful for calm and "healing." Offered as an
                      optional layer, honestly framed.

The core returns a SoundscapePlan: a complete, layer-by-layer description
the frontend audio engine (Web Audio + Tone.js) renders in real time, plus
search targets for the curated real-track bed (realism leads).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


# ===========================================================================
# THERAPEUTIC PROFILES — the heart of the engine.
# For each emotional state, the SCIENCE-BASED target parameters.
# ===========================================================================

# Brainwave target bands (Hz of the binaural beat, not the carrier)
BRAINWAVE = {
    "delta": 2.0,    # deep rest, sleep
    "theta": 6.0,    # deep meditation, release
    "alpha": 10.0,   # relaxed, calm-alert
    "beta": 18.0,    # alert (rarely used here)
}

# Carrier frequencies that feel grounding (root tones)
SOLFEGGIO = {
    "release_fear": 396.0,   # "liberation from fear/guilt"
    "change": 417.0,
    "love_528": 528.0,       # "transformation / repair"
    "connection": 639.0,
    "intuition": 852.0,
    "natural_432": 432.0,    # alternative tuning many find warm
}


@dataclass
class SoundscapePlan:
    """A complete description of the therapeutic soundscape to render."""
    emotion: str
    intent: str                       # what we're trying to do for them
    # Tempo
    start_bpm: int                    # meet them here
    target_bpm: int                   # gently move toward here
    bpm_glide_seconds: int            # how slowly to get there (ISO principle)
    # Harmony
    key_root: str                     # musical root
    scale: str                        # major/minor/lydian/dorian etc.
    chord_change_seconds: float       # slow harmonic rhythm = safety
    consonance: float                 # 0..1, higher = more consonant/safe
    # Spectral / timbre
    brightness: float                 # 0..1, lower = warmer/softer (rolled highs)
    attack_seconds: float             # gentle onset
    release_seconds: float            # long tails
    volume: float                     # 0..1, calming = low
    density: float                    # 0..1, how busy the texture is
    # Brainwave / frequency layers (optional)
    binaural_band: Optional[str]      # delta/theta/alpha/None
    binaural_beat_hz: Optional[float]
    carrier_hz: Optional[float]
    solfeggio: Optional[float]
    # Curated bed (realism leads)
    bed_search_terms: List[str]
    # Movement / morphing
    morph_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# The therapeutic map. Each entry encodes the music-therapy intent.
# Note the ISO principle: for activated states (anxiety, anger, panic) we
# START near their arousal and GLIDE down, rather than jarring them with
# instant calm.
THERAPEUTIC_PROFILES: Dict[str, Dict[str, Any]] = {
    "calm": dict(
        intent="sustain and deepen calm",
        start_bpm=64, target_bpm=60, glide=40,
        key="C", scale="major", chord_secs=12.0, consonance=0.95,
        brightness=0.35, attack=2.0, release=6.0, volume=0.30, density=0.30,
        band="alpha", carrier=SOLFEGGIO["natural_432"], solf=SOLFEGGIO["natural_432"],
        bed=["peaceful ambient", "soft drone", "gentle pads"],
    ),
    "peaceful": dict(
        intent="hold a safe, still space",
        start_bpm=60, target_bpm=56, glide=45,
        key="G", scale="major", chord_secs=14.0, consonance=0.97,
        brightness=0.30, attack=2.5, release=7.0, volume=0.28, density=0.25,
        band="alpha", carrier=SOLFEGGIO["natural_432"], solf=SOLFEGGIO["natural_432"],
        bed=["meditation ambient", "calm drone", "still water"],
    ),
    "anxiety": dict(
        intent="meet the racing, then slow the body (ISO principle)",
        start_bpm=92, target_bpm=66, glide=90,   # start fast, glide WAY down slowly
        key="A", scale="dorian", chord_secs=8.0, consonance=0.85,
        brightness=0.40, attack=1.5, release=5.0, volume=0.32, density=0.40,
        band="alpha", carrier=440.0, solf=SOLFEGGIO["release_fear"],
        bed=["slow breathing ambient", "calming drone", "warm pad"],
    ),
    "fear": dict(
        intent="signal safety, reduce startle, ground",
        start_bpm=80, target_bpm=62, glide=80,
        key="D", scale="major", chord_secs=10.0, consonance=0.92,
        brightness=0.30, attack=2.5, release=7.0, volume=0.30, density=0.30,
        band="theta", carrier=SOLFEGGIO["release_fear"], solf=SOLFEGGIO["release_fear"],
        bed=["safe warm ambient", "soft enveloping pad", "low drone"],
    ),
    "anger": dict(
        intent="match the intensity, then channel it downward",
        start_bpm=100, target_bpm=70, glide=100,  # honor the heat, then release
        key="E", scale="minor", chord_secs=6.0, consonance=0.80,
        brightness=0.45, attack=1.0, release=4.0, volume=0.34, density=0.50,
        band="alpha", carrier=SOLFEGGIO["change"], solf=SOLFEGGIO["change"],
        bed=["grounding rhythmic ambient", "deep slow pulse", "earthy drone"],
    ),
    "sadness": dict(
        intent="sit WITH the sadness (don't force brightness), then warmth",
        start_bpm=66, target_bpm=64, glide=50,
        key="A", scale="minor", chord_secs=11.0, consonance=0.90,
        brightness=0.35, attack=2.0, release=6.5, volume=0.30, density=0.30,
        band="theta", carrier=SOLFEGGIO["love_528"], solf=SOLFEGGIO["love_528"],
        bed=["gentle comforting piano", "warm sad strings", "tender ambient"],
    ),
    "grief": dict(
        intent="hold space for loss with tenderness, no rushing",
        start_bpm=60, target_bpm=58, glide=60,
        key="F", scale="minor", chord_secs=13.0, consonance=0.92,
        brightness=0.28, attack=3.0, release=8.0, volume=0.28, density=0.25,
        band="theta", carrier=SOLFEGGIO["love_528"], solf=SOLFEGGIO["love_528"],
        bed=["soft healing ambient", "gentle requiem pad", "comforting drone"],
    ),
    "numbness": dict(
        intent="gently invite feeling back without overwhelm",
        start_bpm=62, target_bpm=66, glide=70,   # very slight lift
        key="C", scale="lydian", chord_secs=12.0, consonance=0.93,
        brightness=0.40, attack=2.5, release=6.0, volume=0.30, density=0.30,
        band="alpha", carrier=SOLFEGGIO["love_528"], solf=SOLFEGGIO["love_528"],
        bed=["gentle awakening ambient", "soft melodic pad", "warm light drone"],
    ),
    "overwhelm": dict(
        intent="strip away clutter, create spacious quiet",
        start_bpm=84, target_bpm=60, glide=85,
        key="G", scale="major", chord_secs=14.0, consonance=0.95,
        brightness=0.30, attack=3.0, release=8.0, volume=0.26, density=0.18,  # very sparse
        band="alpha", carrier=SOLFEGGIO["natural_432"], solf=SOLFEGGIO["natural_432"],
        bed=["spacious quiet ambient", "minimal drone", "single sustained tone"],
    ),
    "hope": dict(
        intent="nurture the lift gently, don't oversell it",
        start_bpm=70, target_bpm=72, glide=40,
        key="D", scale="major", chord_secs=9.0, consonance=0.95,
        brightness=0.55, attack=1.5, release=5.0, volume=0.32, density=0.40,
        band="alpha", carrier=SOLFEGGIO["love_528"], solf=SOLFEGGIO["love_528"],
        bed=["gentle hopeful warm", "soft uplifting pad", "morning light ambient"],
    ),
    "joy": dict(
        intent="celebrate softly, stay warm not manic",
        start_bpm=78, target_bpm=76, glide=30,
        key="C", scale="major", chord_secs=8.0, consonance=0.96,
        brightness=0.60, attack=1.0, release=4.0, volume=0.34, density=0.50,
        band="alpha", carrier=SOLFEGGIO["connection"], solf=SOLFEGGIO["love_528"],
        bed=["uplifting warm acoustic", "bright gentle pad", "sunlit ambient"],
    ),
    "neutral": dict(
        intent="quiet, unobtrusive presence",
        start_bpm=66, target_bpm=63, glide=40,
        key="C", scale="major", chord_secs=12.0, consonance=0.93,
        brightness=0.38, attack=2.0, release=6.0, volume=0.28, density=0.28,
        band="alpha", carrier=SOLFEGGIO["natural_432"], solf=SOLFEGGIO["natural_432"],
        bed=["calm peaceful ambient", "soft neutral drone"],
    ),
}


class ZenisysCore:
    """The standalone therapeutic sound brain."""

    def plan(
        self,
        emotion: str,
        intensity: float = 0.5,
        enable_binaural: bool = False,
        enable_solfeggio: bool = False,
        prev_emotion: Optional[str] = None,
    ) -> SoundscapePlan:
        """
        Build a complete SoundscapePlan for an emotional state.

        intensity (0..1): how activated the person is. Higher intensity
        pushes the START tempo up (we meet them) and lengthens the glide
        (we take longer to bring them down) — the ISO principle.
        """
        key = (emotion or "neutral").lower()
        p = THERAPEUTIC_PROFILES.get(key, THERAPEUTIC_PROFILES["neutral"])

        # ISO principle: scale the starting arousal by intensity for
        # activated states, so we genuinely meet the person where they are.
        activated = key in ("anxiety", "anger", "fear", "overwhelm")
        start_bpm = p["start_bpm"]
        glide = p["glide"]
        if activated:
            start_bpm = int(p["start_bpm"] + (intensity - 0.5) * 30)
            glide = int(p["glide"] + intensity * 30)

        # If we're morphing FROM another emotion, note it for smooth blending
        morph = ""
        if prev_emotion and prev_emotion.lower() != key:
            morph = f"morph from {prev_emotion} to {key} smoothly over ~{glide}s"

        return SoundscapePlan(
            emotion=key,
            intent=p["intent"],
            start_bpm=max(50, start_bpm),
            target_bpm=p["target_bpm"],
            bpm_glide_seconds=glide,
            key_root=p["key"],
            scale=p["scale"],
            chord_change_seconds=p["chord_secs"],
            consonance=p["consonance"],
            brightness=p["brightness"],
            attack_seconds=p["attack"],
            release_seconds=p["release"],
            volume=p["volume"],
            density=p["density"],
            binaural_band=p["band"] if enable_binaural else None,
            binaural_beat_hz=BRAINWAVE.get(p["band"]) if enable_binaural else None,
            carrier_hz=p["carrier"] if enable_binaural else None,
            solfeggio=p["solf"] if enable_solfeggio else None,
            bed_search_terms=p["bed"],
            morph_note=morph,
        )

    def plan_from_quantum(
        self,
        quantum_emotion: Dict[str, Any],
        enable_binaural: bool = False,
        enable_solfeggio: bool = False,
        prev_emotion: Optional[str] = None,
    ) -> SoundscapePlan:
        """
        Build a plan directly from InnerLight's quantum emotion read.
        Uses the dominant emotion and its probability as intensity, and
        respects contradictions by softening (don't over-commit when the
        person's signals conflict).
        """
        dominant = quantum_emotion.get("dominant_emotion", "neutral")
        prob = float(quantum_emotion.get("dominant_probability", 0.5))
        coherence = float(quantum_emotion.get("coherence", 0.5))

        # Intensity from how strongly the dominant emotion reads
        intensity = min(1.0, prob + (1 - coherence) * 0.2)

        plan = self.plan(
            emotion=dominant,
            intensity=intensity,
            enable_binaural=enable_binaural,
            enable_solfeggio=enable_solfeggio,
            prev_emotion=prev_emotion,
        )

        # If signals contradict (low coherence), keep it extra gentle/neutral-leaning
        if quantum_emotion.get("contradiction"):
            plan.density = min(plan.density, 0.30)
            plan.volume = min(plan.volume, 0.30)
            plan.morph_note = (plan.morph_note + " | signals mixed: stay gentle, "
                               "don't impose a single mood").strip(" |")
        return plan


# Singleton
_core = ZenisysCore()

def get_zenisys_core() -> ZenisysCore:
    return _core


if __name__ == "__main__":
    core = ZenisysCore()
    print("=" * 70)
    print("ZENISYS THERAPEUTIC CORE — sound plans by emotional state")
    print("=" * 70)

    for emo in ["anxiety", "grief", "anger", "numbness", "overwhelm", "calm"]:
        plan = core.plan(emo, intensity=0.8, enable_binaural=True, enable_solfeggio=True)
        print(f"\n--- {emo.upper()} ---")
        print(f"  Intent: {plan.intent}")
        print(f"  Tempo: start {plan.start_bpm} -> target {plan.target_bpm} BPM over {plan.bpm_glide_seconds}s (ISO)")
        print(f"  Harmony: {plan.key_root} {plan.scale}, chord change every {plan.chord_change_seconds}s, consonance {plan.consonance}")
        print(f"  Timbre: brightness {plan.brightness}, vol {plan.volume}, density {plan.density}")
        print(f"  Binaural: {plan.binaural_band} ({plan.binaural_beat_hz}Hz beat on {plan.carrier_hz}Hz carrier)")
        print(f"  Solfeggio: {plan.solfeggio}Hz")
        print(f"  Real-track bed: {plan.bed_search_terms}")

    print("\n" + "=" * 70)
    print("DRIVEN BY QUANTUM EMOTION (with contradiction)")
    print("=" * 70)
    q = {"dominant_emotion": "sadness", "dominant_probability": 0.55,
         "coherence": 0.3, "contradiction": "signals_split_calm_sadness"}
    plan = core.plan_from_quantum(q, enable_binaural=True)
    print(f"  Dominant: {q['dominant_emotion']}, contradiction present")
    print(f"  Intent: {plan.intent}")
    print(f"  Density kept low: {plan.density}, Volume kept low: {plan.volume}")
    print(f"  Note: {plan.morph_note}")
