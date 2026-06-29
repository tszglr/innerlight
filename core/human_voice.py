"""
Human Voice (Text-to-Speech) for InnerLight.

The browser's built-in speech sounds robotic. This module produces genuinely
human-sounding audio on the server, then the browser just plays the audio file.

It is provider-flexible. If a voice-service API key is configured (environment
variable), it uses that service for a real human voice. If no key is set, the
endpoint returns "use_browser": true and the app falls back to the BEST neural
voice already on the person's machine (handled in the front end).

Supported providers (set ONE of these env vars with your key):
  ELEVENLABS_API_KEY   — ElevenLabs (most human, recommended)
  OPENAI_API_KEY       — OpenAI TTS (very natural)
  (others can be added the same way)

Nothing is hard-coded with a paid key. The app works without one (browser
voice), and sounds fully human the moment a key is added.
"""

from __future__ import annotations

import os
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, Any


# Default warm, calm voice IDs (can be overridden by env vars)
ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # "Sarah" - calm
OPENAI_VOICE = os.environ.get("OPENAI_TTS_VOICE", "shimmer")  # warm, soft

# OpenAI offers a fixed set of voices (no account fetch needed). These give
# male/female variety with different timbres. Offered as a comfort CHOICE.
OPENAI_VOICES = [
    {"id": "shimmer", "label": "Shimmer - warm female", "gender": "female"},
    {"id": "nova",    "label": "Nova - bright female",  "gender": "female"},
    {"id": "alloy",   "label": "Alloy - neutral",       "gender": "neutral"},
    {"id": "echo",    "label": "Echo - calm male",      "gender": "male"},
    {"id": "onyx",    "label": "Onyx - deep male",      "gender": "male"},
    {"id": "fable",   "label": "Fable - British male",  "gender": "male"},
]

# cache of voices fetched live from the ElevenLabs account
_eleven_voice_cache = None


def list_voices() -> Dict[str, Any]:
    """Return the voices the user can choose from, grouped for a comfortable
    pick. For ElevenLabs we fetch the account's LIVE voice list (so it always
    reflects what's actually available and never breaks when defaults change),
    grouped by gender and accent. For OpenAI we return the fixed set."""
    provider = voice_provider()
    if provider == "elevenlabs":
        try:
            return {"provider": "elevenlabs", "voices": _fetch_eleven_voices()}
        except Exception as e:
            print(f"[Voice] could not list ElevenLabs voices: {e}")
            return {"provider": "elevenlabs", "voices": []}
    if provider == "openai":
        return {"provider": "openai", "voices": OPENAI_VOICES}
    return {"provider": None, "voices": []}


def _fetch_eleven_voices():
    global _eleven_voice_cache
    if _eleven_voice_cache is not None:
        return _eleven_voice_cache
    key = os.environ["ELEVENLABS_API_KEY"]
    req = urllib.request.Request("https://api.elevenlabs.io/v1/voices",
                                 headers={"xi-api-key": key})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    out = []
    for v in data.get("voices", []):
        labels = v.get("labels", {}) or {}
        gender = labels.get("gender", "")
        accent = labels.get("accent", "")
        descriptor = labels.get("description", "") or labels.get("use_case", "")
        # Build a human, respectful label: name + accent + gender (no stereotyping)
        bits = [v.get("name", "Voice")]
        if accent: bits.append(accent.title())
        if gender: bits.append(gender)
        out.append({
            "id": v.get("voice_id"),
            "label": " - ".join(bits),
            "gender": gender,
            "accent": accent,
            "descriptor": descriptor,
        })
    _eleven_voice_cache = out
    return out


def voice_provider() -> Optional[str]:
    if os.environ.get("ELEVENLABS_API_KEY"):
        return "elevenlabs"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def synthesize(text: str, voice_id: str = "") -> Dict[str, Any]:
    """
    Return {"audio_b64": <mp3 base64>, "provider": ...} when a real voice
    service is configured, or {"use_browser": True} to fall back to the
    best on-device neural voice. An optional voice_id selects which voice.
    """
    text = (text or "").strip()
    if not text:
        return {"use_browser": True, "reason": "empty"}

    provider = voice_provider()
    if not provider:
        return {"use_browser": True, "reason": "no_voice_service_configured"}

    try:
        if provider == "elevenlabs":
            return _elevenlabs(text, voice_id or ELEVEN_VOICE)
        if provider == "openai":
            return _openai(text, voice_id or OPENAI_VOICE)
    except urllib.error.HTTPError as e:
        # Capture the REAL reason from the service so a bad key, quota, or
        # voice id is visible instead of silently falling back to the robot.
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = ""
        reason = f"{provider}_http_{e.code}: {detail}"
        print(f"[Voice] {reason}")
        return {"use_browser": True, "reason": reason}
    except Exception as e:
        print(f"[Voice] error: {e}")
        return {"use_browser": True, "reason": f"voice_service_error: {e}"}
    return {"use_browser": True}


def _elevenlabs(text: str, voice_id: str = "") -> Dict[str, Any]:
    import base64
    key = os.environ["ELEVENLABS_API_KEY"]
    vid = voice_id or ELEVEN_VOICE
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    model = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")  # current recommended, low-latency
    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75,
                           "style": 0.0, "use_speaker_boost": True},
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        audio = resp.read()
    return {"audio_b64": base64.b64encode(audio).decode(), "mime": "audio/mpeg",
            "provider": "elevenlabs", "model": model}


def _openai(text: str, voice_id: str = "") -> Dict[str, Any]:
    import base64
    key = os.environ["OPENAI_API_KEY"]
    url = "https://api.openai.com/v1/audio/speech"
    body = json.dumps({"model": "tts-1", "voice": voice_id or OPENAI_VOICE, "input": text}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        audio = resp.read()
    return {"audio_b64": base64.b64encode(audio).decode(), "mime": "audio/mpeg",
            "provider": "openai"}


if __name__ == "__main__":
    print("Voice provider configured:", voice_provider() or "none (browser fallback)")
    r = synthesize("I am here with you. You are not alone.")
    print("Result keys:", list(r.keys()))
    print(r.get("reason", "audio generated"))
