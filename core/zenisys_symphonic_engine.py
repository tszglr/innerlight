import os
import random

from zenisys_voice_engine import play_audio

try:
    from cultural_detector import CulturalDetector
except ImportError:
    class CulturalDetector:
        def detect_ethnicity(self, user_input: str):
            return "unknown"

try:
    from clarion_engine import Clarion
except ImportError:
    class Clarion:
        def evaluate(self, user_input: str):
            text = (user_input or "").lower()
            if any(word in text for word in ("panic", "afraid", "anxious")):
                return {"category": "anxious", "severity": 8}
            if any(word in text for word in ("sad", "alone", "disconnected")):
                return {"category": "sad", "severity": 6}
            return {"category": "neutral", "severity": 3}


INSTRUMENT_BANK = {
    "african": ["kalimba.wav", "djembe_loop.wav"],
    "caribbean": ["reggae_pad.wav", "steel_drum.wav"],
    "east_asian": ["guzheng_loop.wav", "bamboo_flute.wav"],
    "american_blues": ["harmonica_melody.wav", "blues_guitar.wav"],
    "ambient": ["soft_piano.wav", "waterfall.wav", "crickets.wav"],
    "urban": ["lofi_beat.wav", "vinyl_drift.wav"],
}

AUDIO_PATH = os.environ.get(
    "ZENISYS_AUDIO_PATH",
    "C:/Users/maste/OneDrive/Desktop/FileTransfer_Toshay/AHP_Protocol/audio_clips",
)


class ZenisysSymphony:
    def __init__(self):
        self.clarion = Clarion()
        self.culture = CulturalDetector()

    def _genre_for_identity(self, identity: str) -> str:
        cultural_identity = (identity or "").lower()
        if "african" in cultural_identity:
            return "african"
        if "caribbean" in cultural_identity:
            return "caribbean"
        if "asian" in cultural_identity or "chinese" in cultural_identity:
            return "east_asian"
        if "black" in cultural_identity or "urban" in cultural_identity:
            return "urban"
        if "white" in cultural_identity or "european" in cultural_identity:
            return "american_blues"
        return "ambient"

    def generate_scene(self, user_input: str, voice_tone: str = None):
        mood = self.clarion.evaluate(user_input)
        cultural_identity = self.culture.detect_ethnicity(user_input).lower()
        genre_key = self._genre_for_identity(cultural_identity)
        instrument_set = INSTRUMENT_BANK.get(genre_key, INSTRUMENT_BANK["ambient"])
        selected_layers = random.sample(instrument_set, k=min(2, len(instrument_set)))
        playback = []
        for track in selected_layers:
            file_path = os.path.join(AUDIO_PATH, track)
            playback.append({"track": track, "played": play_audio(file_path)})
        return {
            "status": "playing" if any(item["played"] for item in playback) else "simulated",
            "genre": genre_key,
            "emotion": mood["category"],
            "severity": mood["severity"],
            "layers": selected_layers,
            "playback": playback,
            "voice_tone": voice_tone,
        }


if __name__ == "__main__":
    engine = ZenisysSymphony()
    print(engine.generate_scene("I feel anxious and disconnected", voice_tone="soft"))
