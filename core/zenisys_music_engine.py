"""
Zenisys Sound System v2 — Real instrumental music, emotion-responsive.

Uses the Freesound.org API to fetch real CC-licensed instrumental/ambient tracks
matched to the user's emotional state (detected from voice input), learns
preferences over time, and plays them in the browser.

Setup:
1. Sign up at https://freesound.org/register/ (instant, free)
2. Get your API key from your profile
3. Set: export FREESOUND_API_KEY="your_key_here"

This module is imported by the unified app. When a user checks in and their
emotion is detected, Zenisys searches Freesound for matching tracks, stores
the results, and the frontend plays the audio.
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY", "fobd3ArM7QgxdQqD0hQ6yFXBiLTounH7dgY9Nz4a")
FREESOUND_BASE = "https://freesound.org/apiv2"

# Emotion → Freesound mood tags mapping
EMOTION_TO_MOODS = {
    "calm": ["ambient", "relaxation", "peaceful"],
    "peaceful": ["ambient", "calm", "meditation"],
    "hopeful": ["uplifting", "positive", "inspiring"],
    "happy": ["uplifting", "cheerful", "inspiring"],
    "sadness": ["melancholic", "sad", "introspective"],
    "fear": ["tension", "dark", "mysterious"],
    "anxiety": ["tension", "unsettling", "dark"],
    "anger": ["aggressive", "intense", "powerful"],
    "neutral": ["ambient", "background"],
    "despair": ["dark", "melancholic", "introspective"],
    "numb": ["ambient", "minimal", "sparse"],
}

DEFAULT_DURATION = (30, 300)  # 30s to 5min tracks


def _log_freesound_access(session_id: str, emotion: str, track_id: int, track_name: str) -> None:
    """Log which sounds were played for which emotions (for learning)."""
    db_path = os.environ.get(
        "AHP_UNIFIED_DB",
        str(Path(__file__).resolve().parent.parent / "data" / "axiom_harmony_unified.db"),
    )
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS zenisys_playback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                session_id TEXT,
                emotion TEXT,
                freesound_track_id INTEGER,
                track_name TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO zenisys_playback(created_at, session_id, emotion, freesound_track_id, track_name) VALUES (?,?,?,?,?)",
            (
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                session_id,
                emotion,
                track_id,
                track_name,
            ),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass  # Fail gracefully; playback continues


def search_freesound(emotion: str, limit: int = 5) -> list[dict]:
    """
    Search Freesound.org for tracks matching an emotion.
    Returns a list of {id, name, url, duration_seconds, license}.
    """
    if not FREESOUND_API_KEY:
        return []

    moods = EMOTION_TO_MOODS.get((emotion or "").lower(), ["ambient"])
    mood_str = " ".join(moods)

    # Query: instrumental + mood tags, 30–300s, most downloaded
    params = urllib.parse.urlencode(
        {
            "query": f"instrumental {mood_str}",
            "filter": f"duration:[{DEFAULT_DURATION[0]} TO {DEFAULT_DURATION[1]}]",
            "sort": "downloads-desc",
            "limit": limit,
            "fields": "id,name,duration,download,previews,license",
        }
    )
    url = f"{FREESOUND_BASE}/search/text/?{params}"
    headers = {"Authorization": f"Token {FREESOUND_API_KEY}"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = []
        for sound in data.get("results", []):
            # Freesound preview keys use HYPHENS: preview-hq-ogg, preview-hq-mp3,
            # preview-lq-ogg, preview-lq-mp3. (Underscores do not exist and would
            # silently drop every track.)
            previews = sound.get("previews", {})
            audio_url = (
                previews.get("preview-hq-mp3")
                or previews.get("preview-hq-ogg")
                or previews.get("preview-lq-mp3")
                or previews.get("preview-lq-ogg")
            )
            if audio_url:
                results.append(
                    {
                        "id": sound["id"],
                        "name": sound["name"],
                        "url": audio_url,
                        "duration": sound["duration"],
                        "license": sound.get("license", "unknown"),
                        "freesound_url": sound.get("url", ""),
                    }
                )
        return results
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, Exception):
        return []


class ZenisysSound:
    """
    Emotion-responsive music engine.
    Detects emotion → searches Freesound → returns playable tracks with metadata.
    """

    def __init__(self):
        self.last_emotion = None
        self.current_session = None
        self.cache = {}  # emotion -> list of tracks

    def set_session(self, session_id: str):
        """Track which session this belongs to for learning."""
        self.current_session = session_id

    def detect_and_fetch(self, user_input: str) -> dict:
        """
        Detect emotion from text, search Freesound, return playable tracks.
        This is what the app calls when a user checks in or continues.
        """
        emotion = self._detect_emotion(user_input)
        self.last_emotion = emotion

        # Try cache first
        if emotion in self.cache:
            tracks = self.cache[emotion]
        else:
            tracks = search_freesound(emotion, limit=5)
            self.cache[emotion] = tracks

        return {
            "emotion": emotion,
            "emotion_label": emotion.replace("_", " ").title(),
            "tracks": tracks,
            "cache_hit": emotion in self.cache,
            "status": "ready" if tracks else "no_tracks_found",
        }

    def log_playback(self, track_id: int, track_name: str):
        """Record that a sound was played (for learning)."""
        if self.current_session and self.last_emotion:
            _log_freesound_access(self.current_session, self.last_emotion, track_id, track_name)

    def _detect_emotion(self, text: str) -> str:
        """
        Rough emotion detection from text keywords.
        This is a simple version; a real one would use ML.
        """
        text_lower = (text or "").lower()

        keywords = {
            "calm": ["calm", "peaceful", "relaxed", "content", "serene"],
            "peaceful": ["peaceful", "tranquil", "still", "quiet"],
            "hopeful": ["hopeful", "optimistic", "encouraged", "inspired"],
            "happy": ["happy", "joyful", "glad", "excited", "cheerful"],
            "sadness": ["sad", "down", "blue", "unhappy", "melancholy"],
            "fear": ["afraid", "scared", "fearful", "terrified", "panic"],
            "anxiety": ["anxious", "worried", "nervous", "stressed", "tense"],
            "anger": ["angry", "furious", "rage", "mad", "upset"],
            "despair": ["hopeless", "despair", "suicidal", "worthless"],
            "numb": ["numb", "empty", "blank", "disconnected"],
        }

        for emotion, words in keywords.items():
            if any(w in text_lower for w in words):
                return emotion

        return "neutral"


# Singleton instance
_zenisys = ZenisysSound()


def get_zenisys_engine() -> ZenisysSound:
    """Get the shared Zenisys instance."""
    return _zenisys


if __name__ == "__main__":
    import sys

    if not FREESOUND_API_KEY:
        print("Error: Set FREESOUND_API_KEY environment variable")
        print("Get a free key at https://freesound.org/register/")
        sys.exit(1)

    zen = get_zenisys_engine()
    zen.set_session("test-session")

    test_inputs = [
        "I feel anxious and alone",
        "I am calm and at peace",
        "Everything feels hopeless",
    ]

    for inp in test_inputs:
        print(f"\n--- Input: '{inp}' ---")
        result = zen.detect_and_fetch(inp)
        print(f"Detected emotion: {result['emotion_label']}")
        print(f"Tracks found: {len(result['tracks'])}")
        for t in result["tracks"][:2]:
            print(f"  • {t['name']} ({t['duration']:.0f}s) — {t['url'][:60]}...")
