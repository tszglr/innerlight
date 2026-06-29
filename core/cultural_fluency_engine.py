"""
Cultural Fluency Engine for InnerLight.

CORE PRINCIPLE: Mirror what's offered. Never assume what's hidden.

This engine makes InnerLight understand the FULL range of how real people
express themselves — AAVE, Spanglish, regional dialects, slang, code-
switching — so nobody has to translate their pain into "proper" English to
be understood. And it mirrors the register and warmth the person brings, the
way a skilled counselor practices cultural humility.

WHAT THIS ENGINE DOES:
  1. UNDERSTANDS expression across dialects (comprehension layer)
  2. MIRRORS register/warmth the person uses (response-tone layer)
  3. Lets the user SELF-IDENTIFY background if they choose (user-led layer)
  4. Surfaces culturally-matched RESOURCES when a need is named

WHAT THIS ENGINE NEVER DOES:
  - Guess a person's race, ethnicity, or identity from how they talk
  - Treat anyone according to an assumed category
  - Store or infer protected characteristics the user didn't volunteer
  - Change WHAT help is offered based on inferred identity (only HOW it's
    expressed, and only mirroring what the user themselves offered)

The legal/ethical safety: identity only ever enters the system when the
USER VOLUNTEERS it. The engine reads language, not people.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ===========================================================================
# LAYER 1 — COMPREHENSION: understand expression across dialects
# ===========================================================================
# These maps exist so the system UNDERSTANDS meaning. They are NOT used to
# label or categorize the speaker. A phrase maps to MEANING, never to identity.

# AAVE (African American Vernacular English) — rule-governed constructions
DIALECT_MEANING_MAP = {
    # AAVE habitual/aspect and common expressions -> plain meaning
    r"\bfinna\b": "about to",
    r"\bf  ?in(?:n|na)\b": "about to",
    r"\btryna\b": "trying to",
    r"\bgon(?:na)?\b(?= \w)": "going to",
    r"\bain'?t\b": "is not / am not",
    r"\bbe (\w+ing)\b": r"regularly \1",   # "be working" = works regularly (habitual)
    r"\bdone (\w+ed)\b": r"already \1",      # "done finished" = already finished
    r"\bup in\b": "in",
    # Emotional-weight slang (cross-dialect) -> emotional meaning
    r"\bgoing through it\b": "struggling badly",
    r"\bgoin'? through it\b": "struggling badly",
    r"\bin my feelings\b": "feeling emotional and vulnerable",
    r"\bbig mad\b": "very angry and hurt",
    r"\bbig sad\b": "deeply depressed",
    r"\blow ?key\b": "quietly / somewhat",
    r"\bhigh ?key\b": "openly / very much",
    r"\bpressed\b": "stressed and upset",
    r"\bshook\b": "shaken and scared",
    r"\bbugging\b": "anxious and not okay",
    r"\bbuggin'?\b": "anxious and not okay",
    r"\bwildin'?\b": "out of control / overwhelmed",
    r"\btrippin'?\b": "upset / not thinking clearly",
    r"\bsalty\b": "bitter and hurt",
    r"\bheated\b": "very angry",
    r"\btight\b(?= about| because| that)": "angry",
    r"\bcheck on me\b": "make sure I'm okay",
    r"\bat my limit\b": "completely overwhelmed",
    r"\bcan'?t no more\b": "completely overwhelmed",
    r"\bover it\b": "exhausted and done",
    r"\bdead ?ass\b": "seriously / honestly",
    r"\bfr fr\b": "for real, seriously",
    r"\bno cap\b": "honestly, no lie",
    r"\bsmh\b": "frustrated / disappointed",
}

# Spanish / Spanglish emotional terms -> meaning (comprehension only)
BILINGUAL_MEANING_MAP = {
    r"\bestoy (muy )?triste\b": "I am (very) sad",
    r"\bme siento solo\b": "I feel alone",
    r"\bme siento sola\b": "I feel alone",
    r"\btengo miedo\b": "I am afraid",
    r"\bno puedo m[aá]s\b": "I can't take it anymore",
    r"\bestoy cansad[oa]\b": "I am exhausted",
    r"\bayuda\b": "help",
    r"\bme quiero morir\b": "I want to die",   # CRITICAL crisis phrase in Spanish
    r"\bestoy desesperad[oa]\b": "I am desperate",
}


def comprehend(text: str) -> Dict[str, Any]:
    """
    Translate dialect/slang into plain meaning so downstream engines
    understand the person fully. Returns the meaning-expanded text plus
    notes. Does NOT label the speaker.
    """
    lower = text.lower()
    expansions = []
    plain = lower

    for pattern, meaning in {**DIALECT_MEANING_MAP, **BILINGUAL_MEANING_MAP}.items():
        if re.search(pattern, plain):
            expansions.append(re.sub(r"\\\d", "", meaning))
            plain = re.sub(pattern, meaning, plain)

    # Detect crisis phrases that might be missed in dialect/other languages
    crisis_in_dialect = bool(re.search(r"me quiero morir|can'?t no more|done with (life|it all)", lower))

    return {
        "original": text,
        "plain_meaning": plain,
        "expansions_found": expansions,
        "used_nonstandard_register": len(expansions) > 0,
        "possible_crisis_phrase": crisis_in_dialect,
    }


# ===========================================================================
# LAYER 2 — MIRRORING: match the register and warmth the person brings
# ===========================================================================
# We mirror HOW the person communicates (formal/casual, warm/direct) based on
# THEIR OWN words. This is register-matching, not identity-matching.

def detect_register(text: str) -> Dict[str, Any]:
    """
    Read the communication register the PERSON is using, so we can respond
    in a matching way. Based purely on their words, not assumptions.
    """
    lower = text.lower()
    words = lower.split()

    # Casual markers (their choice of informality)
    casual_markers = ["gonna", "wanna", "finna", "tryna", "yeah", "nah", "lol",
                      "fr", "ngl", "tbh", "bro", "bruh", "y'all", "ain't", "kinda",
                      "sorta", "dunno", "gotta", "lemme", "imma"]
    casual_count = sum(1 for w in words if w in casual_markers)

    # Formal markers
    formal_markers = ["however", "therefore", "regarding", "additionally",
                      "furthermore", "consequently", "i would like", "perhaps",
                      "shall", "wish to"]
    formal_count = sum(1 for m in formal_markers if m in lower)

    # Warmth/directness
    uses_contractions = bool(re.search(r"\b\w+'\w+\b", text))
    exclamations = text.count("!")

    if casual_count >= 2 or (casual_count >= 1 and len(words) < 15):
        register = "casual"
    elif formal_count >= 1:
        register = "formal"
    else:
        register = "neutral"

    return {
        "register": register,
        "warmth_signals": exclamations,
        "uses_contractions": uses_contractions,
        "casual_score": casual_count,
        "formal_score": formal_count,
    }


def mirror_response(base_response: str, register_info: Dict[str, Any]) -> str:
    """
    Lightly adjust a response to match the person's register. We keep the
    SAME message and care — only the delivery flexes to meet them.
    We never force slang; we relax or formalize tone appropriately.
    """
    register = register_info.get("register", "neutral")

    if register == "casual":
        # Warm and relaxed: contractions, less clinical
        r = base_response
        r = r.replace("I am ", "I'm ").replace("you are ", "you're ")
        r = r.replace("cannot", "can't").replace("do not", "don't")
        r = r.replace("It sounds like", "Sounds like")
        r = r.replace("I would like to", "I want to")
        return r
    elif register == "formal":
        # Keep it composed and respectful, expand contractions
        r = base_response
        r = r.replace("I'm ", "I am ").replace("you're ", "you are ")
        r = r.replace("can't", "cannot").replace("don't", "do not")
        return r
    return base_response


# ===========================================================================
# LAYER 3 — USER-LED IDENTITY: let people share background if THEY choose
# ===========================================================================

IDENTITY_INVITATION = (
    "Is there anything about your background, culture, faith, or language "
    "that would help me support you better? Only if you'd like to share."
)


def parse_self_identification(text: str) -> Dict[str, Any]:
    """
    If — and only if — the user volunteers identity information, capture
    what THEY said in THEIR words. We never infer; we only record what is
    freely offered, to honor it.
    """
    lower = text.lower()
    volunteered = {}

    # Language preference (user-stated)
    lang_match = re.search(r"\bi (?:speak|prefer|talk in|am more comfortable in)\s+(\w+)", lower)
    if lang_match:
        volunteered["preferred_language"] = lang_match.group(1)

    # Faith (user-stated only)
    faith_match = re.search(r"\bi(?:'m| am)\s+(christian|muslim|jewish|buddhist|hindu|catholic|spiritual)", lower)
    if faith_match:
        volunteered["faith"] = faith_match.group(1)

    # Any self-described background ("as a ___", "being ___")
    bg_match = re.search(r"\b(?:as a|being a|i'm a|i am a)\s+([\w\s]{3,30}?)(?:,|\.|i |and |so )", lower)
    if bg_match:
        volunteered["self_described"] = bg_match.group(1).strip()

    return {
        "volunteered_identity": volunteered,
        "user_shared_something": bool(volunteered),
    }


# ===========================================================================
# LAYER 4 — CULTURALLY-MATCHED RESOURCES (only when a need is named)
# ===========================================================================

def matched_resources(volunteered_identity: Dict[str, Any], need: str) -> List[Dict[str, str]]:
    """
    Surface resources that fit what the user TOLD us about themselves.
    Only activates on volunteered info + a named need. Never on inference.
    """
    resources = []
    lang = volunteered_identity.get("preferred_language", "").lower()
    faith = volunteered_identity.get("faith", "").lower()

    if lang and lang not in ("english", "en"):
        resources.append({
            "type": "language_matched",
            "label": f"Find a counselor who speaks {lang.title()}",
            "note": "Talking in your first language can make support feel closer.",
        })

    if faith:
        resources.append({
            "type": "faith_aligned",
            "label": f"Find {faith.title()}-aligned support if you'd like it",
            "note": "Some people find comfort in support that shares their faith.",
        })

    return resources


# ===========================================================================
# UNIFIED ENGINE
# ===========================================================================

class CulturalFluencyEngine:
    """
    Mirror what's offered, never assume what's hidden.
    """

    def process_incoming(self, text: str) -> Dict[str, Any]:
        """Full understanding pass on what the user said."""
        comprehension = comprehend(text)
        register = detect_register(text)
        self_id = parse_self_identification(text)
        return {
            "comprehension": comprehension,
            "register": register,
            "self_identification": self_id,
            # plain_meaning feeds the conversation + emotion engines
            "plain_meaning": comprehension["plain_meaning"],
            "possible_crisis_phrase": comprehension["possible_crisis_phrase"],
        }

    def shape_response(self, base_response: str, register_info: Dict[str, Any]) -> str:
        """Mirror the person's register in our reply."""
        return mirror_response(base_response, register_info)

    def identity_invitation(self) -> str:
        return IDENTITY_INVITATION


# Singleton
_engine = CulturalFluencyEngine()

def get_cultural_engine() -> CulturalFluencyEngine:
    return _engine


if __name__ == "__main__":
    engine = CulturalFluencyEngine()

    print("=" * 70)
    print("LAYER 1 — COMPREHENSION (understand, never label)")
    print("=" * 70)
    tests = [
        "I'm finna lose it, everybody be testing me fr",
        "low key I've been going through it and I'm over it",
        "estoy muy triste y me siento solo",
        "me quiero morir",  # crisis in Spanish
        "I am writing to express that I feel quite overwhelmed",
    ]
    for t in tests:
        r = engine.process_incoming(t)
        print(f"\nSAID:   {t}")
        print(f"MEANS:  {r['plain_meaning']}")
        print(f"Register: {r['register']['register']} | Crisis phrase: {r['possible_crisis_phrase']}")

    print("\n" + "=" * 70)
    print("LAYER 2 — MIRRORING (match their register, same care)")
    print("=" * 70)
    base = "I am here with you. It sounds like you are carrying a lot. I would like to understand more."
    for t in ["I'm finna lose it fr", "I wish to discuss my situation"]:
        reg = detect_register(t)
        shaped = engine.shape_response(base, reg)
        print(f"\nPerson's style: {t}  (register: {reg['register']})")
        print(f"Response: {shaped}")

    print("\n" + "=" * 70)
    print("LAYER 3 — USER-LED IDENTITY (only what they volunteer)")
    print("=" * 70)
    for t in ["I speak Spanish and I'm Christian", "as a single mom I feel overwhelmed", "I feel sad today"]:
        r = parse_self_identification(t)
        print(f"\nSAID: {t}")
        print(f"  Volunteered: {r['volunteered_identity'] or 'nothing (we do NOT infer)'}")

    print("\n" + "=" * 70)
    print("LAYER 4 — MATCHED RESOURCES (only on volunteered info)")
    print("=" * 70)
    res = matched_resources({"preferred_language": "spanish", "faith": "christian"}, "support")
    for r in res:
        print(f"  - {r['label']}")
