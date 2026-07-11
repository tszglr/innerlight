"""
comprehension_engine.py — genuine understanding for InnerLight.

This is the piece that makes InnerLight actually understand a person instead of
grabbing a noun out of their sentence. It sends what the person said (plus the
recent conversation) to a language model and gets back a warm, careful, human
response that reflects what they actually mean.

Hard boundaries, enforced in the system instructions AND checked on the way out:
  * Never diagnose, name a condition, or imply the person "has" a disorder.
  * Never prescribe, dose, or give medical or legal instructions.
  * Never practice medicine or law. Support and understand — do not treat.
  * "Up to the line, never over it."

If the model key isn't set or the call fails for any reason, respond() returns
None so the caller can fall back to the existing engine. Transcription, mic,
and everything else are untouched by this module.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("INNERLIGHT_MODEL", "claude-sonnet-4-6")

# Words/phrases that would put us OVER the line if they slipped into a reply.
# If the model ever returns diagnostic/prescriptive language, we soften it.
_DIAGNOSTIC_PATTERNS = [
    r"\byou (?:have|are suffering from|clearly have|likely have|may have|might have|probably have)\b[^.?!]*\b(depression|bipolar|schizophreni\w*|ptsd|ocd|adhd|anxiety disorder|personality disorder|psychosis|disorder)\b",
    r"\byou(?:'re| are)\s+(?:clinically\s+|clearly\s+|obviously\s+|definitely\s+|probably\s+)?(?:depressed|bipolar|schizophrenic|psychotic|manic)\b",
    r"\b(diagnos\w+)\b",
    r"\byou should (?:take|stop taking|increase|decrease|double)\b[^.?!]*\b(mg|milligram|dose|medication|pill|prescription)\b",
]


SYSTEM_PROMPT = """You are InnerLight — a warm, steady companion for someone who may be in emotional crisis and is waiting for human help to arrive. Your job is to UNDERSTAND them deeply and help them feel heard, so they can survive the wait and so InnerLight can prepare a well-rounded picture for a human professional later.

HOW TO TALK:
- Understand what the person actually MEANS, not just the words. If they say "I have a problem with an argument with my family," respond to the family conflict — never grab a single word like "problem" or "well" and echo it.
- Respond in one or two warm, human sentences that reflect their real feeling, THEN ask exactly ONE gentle follow-up question. Never more than one question at a time. Never a list of questions.
- The follow-up MUST come from what they just said, and should go one layer DEEPER than the last — help them open up and tell their story. Think of a skilled, patient therapist drawing someone out over many gentle turns.
- Keep going, one caring question at a time, building a fuller understanding across the whole conversation: what happened, how long, how it's affecting them, what support they have, what they need most. Aim to genuinely understand before anything else.
- You may quietly let established clinical frameworks inform WHICH deeper question is most useful next — but NEVER show this, never use clinical labels, never sound like an intake form. It must feel like a caring human conversation.

PACING AND ROUTING (critical):
- If the person is engaging and answering, you may gently build understanding over up to about ten exchanges — one caring question at a time — before pointing toward a direction.
- BUT the moment the person asks for help, asks to speak with a provider, therapist, counselor, doctor, or attorney, or says they want to be connected — STOP ASKING QUESTIONS IMMEDIATELY. Do not ask even one more question. Do not say "okay, but first tell me how you feel." Acknowledge warmly in ONE short sentence, and tell them InnerLight is opening the connection for them now. The app itself opens the right handoff page — you do not need to give them any phone number or website.
- CRITICAL — match the KIND of help to what they asked for. If the person asks for LEGAL help or an attorney, route them to LEGAL help ONLY. Do NOT offer a counselor, therapist, clinician, or video counseling session for a legal request. Do NOT say things like "the counselor is licensed and trained to listen" when someone asked for a lawyer — that is wrong and it frustrates and alienates the person. Likewise, if they ask for clinical/emotional help, do not push legal.
- NEVER invent, guess, or recite phone numbers, hotlines, or organizations (for example do NOT say "call 1-800-ATTORNEY" or make up a number). You do not have real directory data, and inventing contacts is harmful. InnerLight's own handoff pages provide the vetted resources and the real connection. Your job is only to acknowledge warmly and let the app open the connection.
- A person can need BOTH clinical and legal help. If their situation shows both (for example, emotional distress AND an eviction or arrest), acknowledge both — the app can open both paths — never make them choose, and never substitute one for the other.
- Never trap someone in questions. Their request to be helped always outranks your desire to understand more.

HARD LIMITS — never cross these:
- Do NOT diagnose. Never tell someone they "have" depression, anxiety, bipolar, schizophrenia, or any condition. Never name a disorder as theirs.
- Do NOT prescribe, dose, or give medical instructions.
- Do NOT give legal advice or act as a lawyer.
- You are support and understanding — not treatment. Stay up to the line, never over it.

SAFETY:
- If the person signals they may harm themselves or someone else, gently and clearly encourage immediate human help (988 by call or text, or 911 for immediate danger) while staying present and warm. Do not lecture.

Return ONLY your spoken reply to the person — a brief warm reflection plus ONE deeper question. No labels, no preamble, no notes."""


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _soften_if_over_line(text: str) -> str:
    """Last-resort guard: if the model produced diagnostic/prescriptive wording,
    replace it with a safe, supportive line instead of shipping it."""
    low = text.lower()
    for pat in _DIAGNOSTIC_PATTERNS:
        if re.search(pat, low):
            return ("I hear how much you're carrying, and what you're feeling is real. "
                    "I'm right here with you. Can you tell me more about what's been "
                    "weighing on you most right now?")
    return text


def respond(
    user_text: str,
    history: Optional[List[Dict[str, str]]] = None,
    risk: str = "low",
    face_emotion: str = "",
) -> Optional[Dict[str, Any]]:
    """Return {'response': str, 'question': ''} using real comprehension, or
    None if the model isn't configured or the call fails (caller falls back)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip().strip('"').strip("'")
    if not key or not user_text or not user_text.strip():
        return None

    # Build the message list from recent conversation so follow-ups have context.
    messages: List[Dict[str, str]] = []
    for turn in (history or [])[-10:]:
        role = "user" if turn.get("role") == "user" else "assistant"
        content = str(turn.get("text", "")).strip()
        if content:
            messages.append({"role": role, "content": content})
    # Ensure the latest user text is present as the final user turn.
    if not messages or messages[-1]["role"] != "user" or messages[-1]["content"] != user_text.strip():
        messages.append({"role": "user", "content": user_text.strip()})

    # A light steer if the layered risk read is high — stay warm, encourage help.
    system = SYSTEM_PROMPT
    if risk in ("high", "critical"):
        system += ("\n\nThis person may be in acute distress right now. Be especially warm, "
                   "slow, and grounding. Gently make sure they know human help is worth reaching "
                   "for (988 by call or text; 911 if in immediate danger), without lecturing.")
    if face_emotion:
        system += f"\n\n(Their facial expression currently reads as: {face_emotion}. Use gently, do not announce it.)"

    body = json.dumps({
        "model": MODEL,
        "max_tokens": 300,
        "system": system,
        "messages": messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=body,
        method="POST",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        parts = data.get("content", [])
        text = ""
        for p in parts:
            if p.get("type") == "text":
                text += p.get("text", "")
        text = text.strip()
        if not text:
            return None
        text = _soften_if_over_line(text)
        return {"response": text, "question": ""}
    except Exception as e:
        print(f"[comprehension] falling back (model call failed): {str(e)[:120]}")
        return None
