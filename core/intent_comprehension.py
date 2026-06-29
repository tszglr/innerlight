"""
Intent Comprehension Layer for InnerLight.

THE PROBLEM it fixes: the conversation engine was keyword-matching. Someone
says "I don't like your voice" and it answers "You mentioned voice — tell me
more about voice." It could not tell the difference between:

  - a COMPLAINT ABOUT THE APP itself ("your mic doesn't work", "I hate this voice")
  - a META question about the app ("how does this work?", "are you a real person?")
  - a statement about a PERSON ("Michael won't talk to me")
  - real emotional DISTRESS ("I feel hopeless")
  - ordinary conversation

This layer runs FIRST and figures out what the person actually MEANS, so the
engine can respond appropriately instead of blindly reflecting a noun back.

It is not a clinician and makes no diagnosis. It only classifies conversational
intent so the response is sane and human.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional


# Words that refer to the APP / the technology itself
APP_NOUNS = [
    "mic", "microphone", "voice", "audio", "sound", "music", "speaker", "volume",
    "screen", "button", "app", "application", "website", "site", "page", "video",
    "camera", "webcam", "text", "typing", "keyboard", "interface", "setup",
    "system", "program", "bot", "ai", "chatbot", "robot", "computer", "settings",
    "connection", "loading", "glitch", "bug", "feature", "the way you", "your voice",
]

# Signals of a COMPLAINT / negative reaction (about anything)
COMPLAINT_SIGNALS = [
    "don't like", "do not like", "dont like", "hate", "annoying", "irritating",
    "irritated", "frustrating", "frustrated", "doesn't work", "does not work",
    "doesnt work", "not working", "won't work", "wont work", "broken", "broke",
    "can't hear", "cant hear", "can't see", "cant see", "too loud", "too quiet",
    "stop", "turn off", "turn it off", "make it stop", "creepy", "weird", "robotic",
    "sounds like a robot", "sounds like a computer", "fix", "problem with", "issue with",
    "the way your", "the way you", "set up", "setup", "bad", "terrible", "awful",
    "not good", "useless", "garbage", "trash", "stupid",
]

# META questions ABOUT the app / how it works / what it is
META_SIGNALS = [
    "how does this work", "how do you work", "what are you", "who are you",
    "are you real", "are you a real person", "are you human", "are you a bot",
    "are you ai", "what is this", "what's this", "how do i", "how does this",
    "can you actually", "do you actually", "what can you do", "is this real",
    "how are you doing this", "what's the point of this", "why do you",
]

# Words referring to OTHER PEOPLE (to distinguish "Michael" from "the mic")
RELATION_NOUNS = [
    "mom", "mother", "dad", "father", "son", "daughter", "kid", "child", "children",
    "wife", "husband", "partner", "boyfriend", "girlfriend", "ex", "friend", "boss",
    "coworker", "neighbor", "brother", "sister", "aunt", "uncle", "cousin", "grandma",
    "grandpa", "grandmother", "grandfather", "family", "roommate", "landlord",
    "teacher", "doctor", "therapist", "they", "him", "her", "them", "he ", "she ",
]

# Emotional / distress vocabulary (real internal state)
FEELING_SIGNALS = [
    "feel", "feeling", "felt", "hopeless", "alone", "lonely", "scared", "afraid",
    "anxious", "depressed", "sad", "angry", "overwhelmed", "exhausted", "tired",
    "empty", "numb", "lost", "worthless", "hurt", "hurting", "broken", "crying",
    "panic", "stressed", "worried", "ashamed", "guilty", "grief", "grieving",
    "can't cope", "cant cope", "falling apart", "give up", "no point",
]


@dataclass
class Intent:
    primary: str            # app_complaint / app_meta / about_person / distress / general
    confidence: float
    app_target: Optional[str] = None   # which app thing they referenced
    reasons: List[str] = None

    def to_dict(self):
        return {"primary": self.primary, "confidence": round(self.confidence, 2),
                "app_target": self.app_target, "reasons": self.reasons or []}


def _has(text: str, phrases: List[str]) -> List[str]:
    low = text.lower()
    out = []
    for p in phrases:
        if " " in p:
            if p in low:
                out.append(p)
        elif re.search(r"\b" + re.escape(p) + r"\b", low):
            out.append(p)
    return out


def classify_intent(text: str) -> Intent:
    text = text or ""
    low = text.lower()
    reasons = []

    complaint_hits = _has(text, COMPLAINT_SIGNALS)
    app_hits = _has(text, APP_NOUNS)
    meta_hits = _has(text, META_SIGNALS)
    relation_hits = _has(text, RELATION_NOUNS)
    feeling_hits = _has(text, FEELING_SIGNALS)

    # --- META question about the app ("how does this work", "are you real") ---
    if meta_hits and not feeling_hits:
        reasons.append("asks about the app/how it works")
        return Intent("app_meta", 0.85, app_target=(app_hits[0] if app_hits else None), reasons=reasons)

    # --- APP COMPLAINT: a complaint signal + an app noun, with no real feeling ---
    if complaint_hits and app_hits:
        # but if there's ALSO strong feeling language, it may be real distress
        # expressed through frustration — only treat as pure app complaint if
        # feeling language is absent or weak.
        if not feeling_hits:
            reasons.append(f"complaint ({complaint_hits[0]}) about app element ({app_hits[0]})")
            return Intent("app_complaint", 0.9, app_target=app_hits[0], reasons=reasons)
        else:
            reasons.append("complaint about app but feeling language also present")
            return Intent("app_complaint", 0.6, app_target=app_hits[0], reasons=reasons)

    # --- A complaint with NO app noun but an app-ish "the way you" phrasing ---
    if complaint_hits and ("the way you" in low or "your voice" in low or "you sound" in low):
        reasons.append("complaint directed at the assistant")
        return Intent("app_complaint", 0.75, app_target="voice", reasons=reasons)

    # --- DISTRESS: real feeling language present ---
    if feeling_hits:
        # If they also mention a person, it's distress ABOUT a relationship —
        # still distress, we note the person.
        reasons.append(f"feeling language ({feeling_hits[0]})")
        return Intent("distress", 0.8,
                      app_target=None, reasons=reasons)

    # --- ABOUT A PERSON: relationship noun present, no app complaint ---
    if relation_hits and not app_hits:
        reasons.append(f"refers to a person ({relation_hits[0].strip()})")
        return Intent("about_person", 0.7, reasons=reasons)

    # --- ABOUT A PERSON by SHAPE: a capitalized name acting as a subject,
    # e.g. "Michael won't talk to me", "Sarah said", "David keeps..." ---
    name_verb = re.search(
        r"\b([A-Z][a-z]+)\s+(won't|wont|will not|doesn't|doesnt|does not|keeps|said|told|"
        r"hates|hit|left|ignored|ignores|yelled|yells|called|hurt|loves|won't talk|stopped)\b",
        text)
    if name_verb and not app_hits and name_verb.group(1).lower() not in (
            "i", "the", "this", "that", "it", "he", "she", "they", "we", "you"):
        reasons.append(f"a named person acting ({name_verb.group(1)})")
        return Intent("about_person", 0.65, reasons=reasons)

    # --- A bare app noun with no complaint and no feeling: ambiguous, lean app if isolated ---
    if app_hits and not relation_hits and not feeling_hits and len(text.split()) <= 4:
        reasons.append(f"isolated app reference ({app_hits[0]})")
        return Intent("app_meta", 0.5, app_target=app_hits[0], reasons=reasons)

    reasons.append("ordinary conversation")
    return Intent("general", 0.5, reasons=reasons)


# Human responses for app-related intents (NOT reflective therapy questions)
def app_complaint_response(intent: Intent) -> Dict[str, str]:
    target = (intent.app_target or "that").strip()
    # Tailor to the specific thing they complained about
    specific = {
        "mic": ("Sorry the mic's giving you trouble. You can type instead, that works just as well. "
                "If you want voice, it usually needs the page to be on a secure (https) connection and "
                "permission to use the microphone."),
        "microphone": ("Sorry the microphone isn't cooperating. Typing works perfectly here too. "
                       "Voice input needs a secure connection and mic permission to work."),
        "voice": ("Got it — I'll quiet the spoken voice. You can turn it off entirely with the Voice button, "
                  "and we can just keep things in text."),
        "music": ("I hear you on the music — I can change it or turn it off. Just say the word."),
        "video": ("Thanks for telling me about the video. You can turn the camera off anytime; "
                  "it's never required."),
        "sound": ("I'll ease off on the sound. You can turn audio off with the controls anytime."),
    }
    msg = specific.get(target,
        f"Thanks for telling me — that's useful feedback about the {target}. "
        f"You can always type instead, and you can turn off voice, music, or video with the controls.")
    return {
        "response": msg,
        "question": "Want me to adjust that now, or would you rather just keep going?",
        "is_app_feedback": True,
    }


def app_meta_response(intent: Intent) -> Dict[str, str]:
    return {
        "response": ("Fair question. I'm not a person — I'm a supportive tool built to listen, help you "
                     "sort through what you're feeling, and connect you to real human help when you want it. "
                     "I don't diagnose or replace a professional."),
        "question": "Is there something on your mind you'd like to talk through?",
        "is_app_feedback": True,
    }


if __name__ == "__main__":
    tests = [
        "I don't like your voice right now",
        "the mic doesn't work",
        "I don't like the way your mic is set up",
        "your voice sounds like a robot",
        "how does this work?",
        "are you a real person?",
        "Michael won't talk to me anymore",
        "my mom keeps yelling at me",
        "I feel so hopeless and alone",
        "I'm overwhelmed and I can't cope",
        "the music is annoying",
        "turn off the music",
        "I feel like Michael doesn't care about me",
        "what can you do?",
        "I had a good day today",
    ]
    print("=" * 72)
    print("INTENT COMPREHENSION — what does the person actually MEAN?")
    print("=" * 72)
    for t in tests:
        intent = classify_intent(t)
        print(f"\n  \"{t}\"")
        print(f"    -> {intent.primary.upper()} (conf {intent.confidence}) "
              f"{'target='+intent.app_target if intent.app_target else ''}")
        print(f"       {intent.reasons}")
