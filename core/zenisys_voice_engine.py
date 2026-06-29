import asyncio
import os
import platform
import random
from typing import Optional

import numpy as np

try:
    import pygame
except ImportError:
    pygame = None

try:
    import simpleaudio as sa
except ImportError:
    sa = None


def _audio_available() -> bool:
    return pygame is not None


def _ensure_mixer() -> bool:
    if pygame is None:
        return False
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2)
        return True
    except Exception as exc:
        print(f"[Zenisys] Audio mixer unavailable: {exc}")
        return False


def play_audio(file_path: str, wait: bool = False) -> bool:
    """Play a wave file when audio dependencies and devices are available."""
    if not os.path.exists(file_path):
        print(f"[Zenisys] Missing audio file: {file_path}")
        return False
    if sa is not None and file_path.lower().endswith(".wav"):
        try:
            play_obj = sa.WaveObject.from_wave_file(file_path).play()
            if wait:
                play_obj.wait_done()
            return True
        except Exception as exc:
            print(f"[Zenisys] simpleaudio playback failed: {exc}")
    if _ensure_mixer():
        try:
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            return True
        except Exception as exc:
            print(f"[Zenisys] pygame playback failed: {exc}")
    print(f"[Zenisys] Audio unavailable; playback skipped for {file_path}")
    return False


class ZenisysSound:
    """
    Therapeutic audio response engine.

    It is intentionally safe to import on machines without pygame, simpleaudio,
    speakers, or audio clips. In that case methods report that playback was skipped.
    """

    def __init__(self, base_path: str = "audio_clips"):
        self.base_path = base_path
        self.voice_responses = {
            "greeting": ["greeting_1.wav", "greeting_2.wav"],
            "encouragement": ["encourage_1.wav", "encourage_2.wav"],
            "calming": ["calming_1.wav", "calming_2.wav"],
            "crisis": ["crisis_1.wav", "crisis_2.wav"],
        }
        self.genres = {
            "ambient": {"freq_range": (100, 300), "tempo": 60},
            "classical": {"freq_range": (200, 500), "tempo": 80},
            "nature": {"freq_range": (50, 200), "tempo": 50},
        }
        self.distress_level = 0
        self.audio_enabled = _audio_available()
        print("[Zenisys] ZenisysSound initialized.")

    def play_voice_clip(self, category: str) -> bool:
        clips = self.voice_responses.get(category, [])
        if not clips:
            print(f"[Zenisys] No clips found for category: {category!r}")
            return False
        selected_clip = random.choice(clips)
        full_path = os.path.join(self.base_path, category, selected_clip)
        return play_audio(full_path, wait=True)

    def play_voice(self, category: str) -> bool:
        return self.play_voice_clip(category)

    def generate_therapeutic_sound(self, genre: str = "ambient", duration: int = 5) -> bool:
        if not _ensure_mixer():
            print(f"[Zenisys] Audio unavailable; {genre} tone skipped for {duration}s.")
            return False

        genre = genre.lower()
        params = self.genres.get(genre, self.genres["ambient"])
        freq_min, freq_max = params["freq_range"]
        freq = freq_min + (freq_max - freq_min) * (1 - self.distress_level / 10)
        sample_rate = 44100
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        base_wave = 0.5 * np.sin(2 * np.pi * freq * t)
        overtone = 0.2 * np.sin(2 * np.pi * (freq * 2) * t)
        audio = ((base_wave + overtone) * 32767).astype(np.int16)
        stereo_audio = np.column_stack((audio, audio))
        sound = pygame.sndarray.make_sound(stereo_audio)
        sound.play()
        pygame.time.wait(int(duration * 1000))
        return True

    def detect_distress(self, face_data=None, voice_data=None, user_input: Optional[str] = None):
        if user_input:
            mood = user_input.strip().lower()
            self.distress_level = {"calm": 2, "stressed": 7, "anxious": 9}.get(mood, 5)
        else:
            self.distress_level = random.randint(0, 10)
        print(f"[Zenisys] Detected distress level: {self.distress_level}/10")
        return self.distress_level

    def adjust_soundscape(self, emotional_score):
        severity = emotional_score.get("severity", 5) if isinstance(emotional_score, dict) else 5
        self.distress_level = max(0, min(10, int(severity)))
        return {"status": "adjusted", "distress_level": self.distress_level}

    def trigger_scene(self, emotional_score, culture_profile: str = "unknown"):
        category = emotional_score.get("category", "neutral") if isinstance(emotional_score, dict) else "neutral"
        return {"status": "scene_selected", "emotion": category, "culture": culture_profile}

    async def therapy_session(self, genre: str = "ambient", duration: int = 5):
        try:
            user_input = input("How are you feeling? (calm/stressed/anxious): ")
        except Exception:
            user_input = "calm"
        self.detect_distress(user_input=user_input)
        if self.distress_level > 7:
            self.play_voice_clip("calming")
        elif self.distress_level > 4:
            self.play_voice_clip("encouragement")
        else:
            self.play_voice_clip("greeting")
        self.generate_therapeutic_sound(genre=genre, duration=duration)


ZenisysVoiceEngine = ZenisysSound


async def main():
    engine = ZenisysSound()
    await engine.therapy_session(genre="nature", duration=5)


if platform.system() == "Emscripten":
    asyncio.ensure_future(main())
elif __name__ == "__main__":
    asyncio.run(main())
