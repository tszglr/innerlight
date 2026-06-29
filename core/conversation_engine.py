"""
Conversation Engine v2 for InnerLight.

Comprehensive rewrite. Extracts meaning from what the user actually said —
their specific people, events, feelings, actions, needs, situations — and
generates ONE natural follow-up that builds on their words.

Handles diverse expression (AAVE, slang, formal, fragments) without guessing
identity. The system does not care WHO the user is; it cares WHAT they said
and HOW they feel. Cultural awareness means understanding more language, not
categorizing people.

Legal output is framed as "recommendations for your attorney" — never as
legal action taken by the system.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# TOPIC EXTRACTION — much broader than v1
# ---------------------------------------------------------------------------

PERSON_WORDS = (
    "mom|mother|mama|momma|ma|dad|father|papa|pops|brother|bro|sister|sis|"
    "son|daughter|husband|wife|partner|spouse|boyfriend|girlfriend|bf|gf|"
    "friend|best friend|homie|homeboy|homegirl|bestie|bff|"
    "boss|manager|supervisor|coworker|colleague|classmate|teacher|professor|"
    "therapist|counselor|doctor|nurse|psychiatrist|"
    "child|baby|kid|toddler|infant|teenager|teen|"
    "grandma|grandmother|nana|granny|abuela|grandpa|grandfather|papa|abuelo|"
    "uncle|tio|aunt|tia|cousin|nephew|niece|godmother|godfather|"
    "stepmom|stepdad|stepbrother|stepsister|foster parent|foster mom|foster dad|"
    "roommate|neighbor|landlord|"
    "dog|cat|pet|puppy|kitten|bird|fish|hamster|rabbit|"
    "ex|ex-husband|ex-wife|ex-boyfriend|ex-girlfriend|baby daddy|baby mama|"
    "fiancee|fiance|significant other|lover|crush"
)

FEELING_WORDS = {
    # Core emotions
    "happy": "happy", "glad": "happy", "joyful": "happy", "excited": "excited",
    "grateful": "grateful", "thankful": "grateful", "blessed": "grateful",
    "peaceful": "peaceful", "calm": "calm", "content": "content", "relieved": "relieved",
    # Sadness
    "sad": "sad", "depressed": "depressed", "down": "down", "blue": "sad",
    "heartbroken": "heartbroken", "grieving": "grieving", "mourning": "grieving",
    "miserable": "miserable", "devastated": "devastated", "crushed": "crushed",
    # Anger
    "angry": "angry", "mad": "angry", "furious": "furious", "pissed": "angry",
    "livid": "furious", "heated": "angry", "fed up": "fed up", "sick of": "fed up",
    "irritated": "irritated", "frustrated": "frustrated", "annoyed": "annoyed",
    "enraged": "furious", "hostile": "hostile",
    # Fear/anxiety
    "scared": "scared", "afraid": "afraid", "terrified": "terrified",
    "anxious": "anxious", "nervous": "nervous", "worried": "worried",
    "panicking": "panicking", "paranoid": "paranoid", "on edge": "on edge",
    "uneasy": "uneasy", "freaking out": "panicking", "stressed": "stressed",
    # Shame/guilt
    "ashamed": "ashamed", "guilty": "guilty", "embarrassed": "embarrassed",
    "humiliated": "humiliated", "disgusted with myself": "self-disgust",
    # Hopelessness
    "hopeless": "hopeless", "worthless": "worthless", "useless": "worthless",
    "pointless": "hopeless", "empty": "empty", "hollow": "empty",
    "numb": "numb", "dead inside": "numb", "don't care anymore": "numb",
    # Confusion
    "confused": "confused", "lost": "lost", "overwhelmed": "overwhelmed",
    "stuck": "stuck", "trapped": "trapped", "helpless": "helpless",
    # Loneliness
    "lonely": "lonely", "alone": "alone", "isolated": "isolated",
    "abandoned": "abandoned", "forgotten": "forgotten", "invisible": "invisible",
    "nobody cares": "abandoned", "no one cares": "abandoned",
    # Betrayal
    "betrayed": "betrayed", "stabbed in the back": "betrayed",
    "used": "used", "manipulated": "manipulated", "lied to": "betrayed",
    # Exhaustion
    "exhausted": "exhausted", "burnt out": "burnt out", "drained": "drained",
    "tired of everything": "exhausted", "can't take it anymore": "overwhelmed",
    "done": "done", "over it": "done",
    # Diverse expression (AAVE, slang, informal — understood, not categorized)
    "heated": "angry", "tight": "angry", "salty": "irritated",
    "pressed": "stressed", "shook": "scared", "wilding": "overwhelmed",
    "bugging": "anxious", "buggin": "anxious", "tripping": "confused",
    "going through it": "struggling", "in my feelings": "emotional",
    "can't deal": "overwhelmed", "bout to snap": "about to break",
    "finna lose it": "about to break", "low key sad": "sad",
    "big sad": "depressed", "messed up": "hurt", "jacked up": "hurt",
    "sick and tired": "fed up", "had it": "fed up", "at my limit": "overwhelmed",
    "broken": "broken", "shattered": "broken", "falling apart": "broken",
    "drowning": "overwhelmed",
}

EVENT_PATTERNS = [
    (r"\b(died|passed away|passed|funeral|death)\b", "death"),
    (r"\b(accident|crash|wreck|collision)\b", "accident"),
    (r"\b(fire|burned down|house fire)\b", "fire"),
    (r"\blost .{1,25}(job|position|career)\b", "job_loss"),
    (r"\b(got fired|terminated|laid off|let go)\b", "job_loss"),
    (r"\b(arrested|locked up|jailed|incarcerated|in jail|in prison)\b", "arrest"),
    (r"\b(hospitalized|hospital|ER|emergency room|admitted)\b", "hospital"),
    (r"\b(surgery|operation|procedure|treatment)\b", "medical"),
    (r"\b(divorce|separated|split up)\b", "divorce"),
    (r"\b(breakup|broke up|broken up|dumped|left me)\b", "breakup"),
    (r"\b(moved|relocated|had to leave)\b", "move"),
    (r"\b(evicted|kicked out|lost .{1,15}(home|house|apartment|place))\b", "eviction"),
    (r"\b(deployed|deployment)\b", "deployment"),
    (r"\b(cheated|unfaithful|affair|side piece)\b", "infidelity"),
    (r"\b(hit|beat|punch|slap|attacked|assaulted|jumped)\b", "violence"),
    (r"\b(raped|molested|abused|touched me)\b", "assault"),
    (r"\b(overdosed|relapsed|using again)\b", "substance"),
    (r"\b(miscarriage|stillborn|lost .{1,10}baby)\b", "pregnancy_loss"),
    (r"\b(diagnosed|found out I have|test came back)\b", "diagnosis"),
    (r"\b(expelled|suspended|dropped out|flunked)\b", "school"),
    (r"\b(homeless|on the street|living in .{1,10}car)\b", "homelessness"),
    (r"\b(deported|immigration|ICE|detained)\b", "immigration"),
    (r"\b(robbed|stolen|burglarized|scammed)\b", "crime_victim"),
    (r"\b(promoted|got a raise|new job|accepted|graduated)\b", "positive_event"),
    (r"\b(pregnant|expecting|having a baby)\b", "pregnancy"),
    (r"\b(custody|took .{1,10}kid|CPS|child protective)\b", "custody"),
]

ACTION_PATTERNS = [
    (r"\b(drinking|drunk|alcohol|liquor|beer|wine)\b", "drinking"),
    (r"\b(smoking|weed|marijuana|pot|high)\b", "marijuana"),
    (r"\b(using|drugs|pills|meth|heroin|fentanyl|crack|cocaine|opioid)\b", "drugs"),
    (r"\b(cutting|cut myself|self.?harm|hurting myself)\b", "self_harm"),
    (r"\b(starving|not eating|binging|purging|throwing up)\b", "eating"),
    (r"\b(can't sleep|insomnia|nightmares|night terrors|up all night)\b", "sleep"),
    (r"\b(fighting|fought|hit|punched|beat up|jumped)\b", "fighting"),
    (r"\b(stole|stealing|shoplifting|robbed)\b", "stealing"),
    (r"\b(ran away|running away|left home)\b", "running"),
    (r"\b(skipping|dropped out|won't go to school|not going)\b", "avoidance"),
    (r"\b(lying|lied|hiding|keeping secret)\b", "hiding"),
]

CRISIS_PHRASES = [
    "kill myself", "end it all", "suicide", "suicidal", "want to die",
    "wanna die", "hurt myself", "cut myself", "jump off", "overdose",
    "no reason to live", "better off dead", "can't go on", "not worth living",
    "don't want to be here", "end my life", "wish i was dead",
    "wish i wasn't here", "rather be dead", "planning to",
    "nobody would miss me", "world be better without me",
    "just want it to stop", "can't do this anymore", "done with life",
    "no point", "nothing matters", "won't be here",
    # --- Indirect / passive ideation (caught from stress test) ---
    "what's the point", "whats the point", "what is the point",
    "sleep forever", "want to sleep forever", "never wake up",
    "nobody would notice if i was gone", "nobody would notice",
    "if i was gone", "if i wasn't around", "when i'm gone",
    "i'm a burden", "im a burden", "burden to everyone",
    "burden to my", "don't see a way out", "dont see a way out",
    "no way out", "dark thoughts", "thinking dark",
    "tired of everything", "tired of living", "can't keep going",
    "cant keep going", "give up on everything", "don't want to wake up",
    "dont want to wake up", "stop existing", "disappear forever",
    "everyone better off without me", "they'd be better off",
]

# Phrases that REQUIRE a gentle qualifying check (ambiguous but possibly serious)
QUALIFY_PHRASES = [
    "tired of everything", "so tired", "what's the point", "whats the point",
    "sleep forever", "dark thoughts", "burden", "way out", "give up",
    "can't anymore", "cant anymore", "done", "over it", "had enough",
]

NEGATIVE_SIGNALS = [
    "no", "not safe", "i'm not", "i am not", "nowhere safe",
    "nobody", "no one", "can't", "don't have anyone", "alone",
    "i have no one", "there is no one", "not really", "nope",
    "hell no", "nah", "ain't nobody", "ain't no one",
    "nobody here", "no one here", "by myself", "on my own",
    "i can't", "don't know anyone", "there's nobody",
]


def extract_topics(text: str) -> Dict[str, List[str]]:
    lower = text.lower()
    result: Dict[str, List[str]] = {}

    # People/loved ones
    person_pat = rf"\b(?:my|our)\s+({PERSON_WORDS})\b"
    for m in re.finditer(person_pat, lower):
        result.setdefault("person", []).append(m.group(1).strip())

    # Feelings
    for phrase, label in FEELING_WORDS.items():
        if phrase in lower:
            result.setdefault("feeling", [])
            if label not in result["feeling"]:
                result["feeling"].append(label)

    # Events
    for pat, label in EVENT_PATTERNS:
        if re.search(pat, lower):
            raw = re.search(pat, lower).group(0)
            result.setdefault("event", []).append(label)
            result.setdefault("event_raw", []).append(raw)

    # Actions
    for pat, label in ACTION_PATTERNS:
        if re.search(pat, lower):
            result.setdefault("action", []).append(label)

    # Time references
    time_pat = r"\b(today|yesterday|last (?:night|week|month|year)|this morning|right now|for (?:years|months|weeks|days)|since|ago|recently|lately)\b"
    for m in re.finditer(time_pat, lower):
        result.setdefault("time", []).append(m.group(0))

    # Places
    place_pat = r"\b(school|work|job|home|house|apartment|hospital|church|shelter|jail|prison|court|pharmacy|clinic|office|dorm|barracks|base|street|park|car|outside)\b"
    for m in re.finditer(place_pat, lower):
        result.setdefault("place", []).append(m.group(0))

    return result


def _extract_subject(text: str, event_word: str) -> Optional[str]:
    lower = text.lower()
    skip = {"i", "it", "he", "she", "we", "they", "that", "this", "and", "but",
            "the", "a", "an", "just", "got", "was", "been", "had", "have", "has",
            "get", "is", "are", "were", "my", "our", "his", "her", "their", "so"}
    pat = rf"(?:my|our)\s+(\w+(?:\s+\w+)?)\s+(?:{re.escape(event_word.split()[0])})"
    m = re.search(pat, lower)
    if m:
        subj = m.group(1).strip()
        if subj not in skip:
            return subj
    words = lower.split()
    try:
        idx = words.index(event_word.split()[0])
        for i in range(idx - 1, -1, -1):
            if words[i] not in skip and len(words[i]) > 1:
                return words[i]
    except (ValueError, IndexError):
        pass
    return None


def detect_contradiction(text: str, face_emotion: str) -> Optional[str]:
    if not face_emotion:
        return None
    face = face_emotion.lower()
    if face == "neutral":
        return None
    positive = any(w in text.lower() for w in ("happy", "fine", "good", "great", "ok", "okay", "alright", "blessed", "grateful", "calm"))
    neg_face = face in ("sad", "angry", "fearful", "disgusted")
    if positive and neg_face:
        return f"positive_text_{face}_face"
    return None


# ---------------------------------------------------------------------------
# RESPONSE GENERATION — context-aware, never generic
# ---------------------------------------------------------------------------

def generate_response(
    user_text: str,
    topics: Dict[str, List[str]],
    face_emotion: str,
    risk: str,
    turn_count: int,
    asked_topics: List[str],
) -> Tuple[str, str]:
    text_lower = user_text.lower().strip()
    words = text_lower.split()

    # ---- CRISIS: immediate, warm, specific ----
    is_crisis = any(p in text_lower for p in CRISIS_PHRASES) or risk == "critical"
    if is_crisis:
        # Mark that we are in a crisis conversation so subsequent "no" answers are handled
        if "crisis" not in asked_topics:
            asked_topics.append("crisis")
        if "safety" not in asked_topics:
            asked_topics.append("safety")
        return (
            "I hear you, and I want you to know that what you are feeling right now matters. You reached out, and that takes strength.",
            _next_crisis_question(asked_topics),
        )

    # ---- QUALIFY: ambiguous-but-serious statements get a gentle safety check ----
    # These are not explicit crisis, but a caring listener would NOT brush past
    # them. We respond with genuine acknowledgement and a caring qualifying
    # question that stays on what they said — never generic.
    if any(p in text_lower for p in QUALIFY_PHRASES) and not is_crisis:
        focus = None
        for p in QUALIFY_PHRASES:
            if p in text_lower:
                focus = p
                break
        return (
            "I want to slow down for a moment, because what you just said sounds heavy.",
            f"When you say you're {focus}, I want to understand it the right way \u2014 "
            "can you tell me more about what that feels like for you?"
        )

    # ---- TEXT CONTRADICTION: 'fine' but describing distress ----
    # e.g. "everything is fine I just can't sleep or eat" / "I'm fine I just cry every night"
    fine_words = ("fine", "okay", "ok", "good", "great", "alright", "all right", "never better")
    distress_words = ("cry", "crying", "can't sleep", "cant sleep", "can't eat", "cant eat",
                      "not sleeping", "not eating", "tired", "exhausted", "hurt", "alone",
                      "scared", "anxious", "panic", "shaking", "every night", "all the time")
    said_fine = any(re.search(r"\b" + re.escape(w) + r"\b", text_lower) for w in fine_words)
    said_distress = any(d in text_lower for d in distress_words)
    if said_fine and said_distress:
        # Reflect BOTH sides — the 'fine' and the distress underneath
        distress_found = next((d for d in distress_words if d in text_lower), "what you described")
        return (
            "I noticed you said you're fine, but you also mentioned something that sounds really hard. "
            "Both of those can be true at once, and I'd rather not gloss over the hard part.",
            f"Tell me more about the {distress_found} \u2014 how long has that been happening?"
        )

    # ---- MIXED EMOTIONS: two opposing feelings named together ----
    pos_feel = ("happy", "good", "great", "excited", "glad", "fine")
    neg_feel = ("sad", "down", "depressed", "angry", "scared", "anxious", "empty", "lonely", "hurt")
    has_pos = any(re.search(r"\b" + re.escape(w) + r"\b", text_lower) for w in pos_feel)
    has_neg = any(re.search(r"\b" + re.escape(w) + r"\b", text_lower) for w in neg_feel)
    if has_pos and has_neg:
        p = next(w for w in pos_feel if re.search(r"\b" + re.escape(w) + r"\b", text_lower))
        n = next(w for w in neg_feel if re.search(r"\b" + re.escape(w) + r"\b", text_lower))
        return (
            f"Feeling {p} and {n} at the same time is real \u2014 a lot of people carry both together, "
            "and it doesn't make either one less true.",
            f"Can you tell me about both? What's bringing the {p}, and what's bringing the {n}?"
        )

    # ---- ANGER / FRUSTRATION AIMED AT THE APP ----
    app_frustration = ("you don't understand", "you dont understand", "that's not what i said",
                       "thats not what i said", "stop asking", "you're useless", "youre useless",
                       "you are useless", "just help me", "you already asked", "not helping",
                       "this is stupid", "this isn't working", "this isnt working")
    if any(p in text_lower for p in app_frustration):
        return (
            "You're right, and I'm sorry I'm not getting this the way you need. "
            "I don't want to make this harder.",
            "Let me try differently \u2014 tell me, in your own words, what would actually help you right now?"
        )

    # ---- META / IDENTITY QUESTIONS about the app itself ----
    meta_q = ("what are you", "who made you", "are you a robot", "are you ai", "are you real",
              "are you human", "what can you do", "do you even work", "can you hear me",
              "how do you work", "are you a bot", "is this real")
    if any(p in text_lower for p in meta_q):
        return (
            "Fair question. I'm InnerLight \u2014 a supportive space built to listen, help you sort "
            "through what you're feeling, and connect you to real human help when you want it. "
            "I'm not a person, and I won't pretend to be.",
            "But I'm here for you right now \u2014 what's going on that brought you here today?"
        )

    # ---- NEGATIVE to safety question ----
    is_neg = any(w in text_lower for w in NEGATIVE_SIGNALS) or (len(words) <= 3 and "no" in words)
    if is_neg and (risk in ("critical", "high") or any(t in asked_topics for t in ("safety", "crisis"))):
        # Stay in crisis mode
        if "crisis" not in asked_topics:
            asked_topics.append("crisis")
        return _negative_safety_response(turn_count, topics)

    # ---- CONTRADICTION: face vs text ----
    contradiction = detect_contradiction(text_lower, face_emotion)
    if contradiction:
        return _contradiction_response(face_emotion)

    # ---- DEATH / LOSS ----
    if "event" in topics and any(e in ("death", "pregnancy_loss") for e in topics["event"]):
        person = topics["person"][0] if "person" in topics else _extract_subject(user_text, "died") or _extract_subject(user_text, "passed")
        if person:
            for p in ("my ", "our ", "a "):
                if person.startswith(p): person = person[len(p):]
            return (
                f"I am so sorry about your {person}. That is a real and painful loss.",
                f"How have you been doing since losing your {person}? There is no right way to grieve."
            )
        return (
            "I am so sorry for your loss. That kind of pain is real and it matters.",
            "Can you tell me about who you lost and what they meant to you?"
        )

    # ---- VIOLENCE / ASSAULT ----
    if "event" in topics and any(e in ("violence", "assault") for e in topics["event"]):
        return (
            "Thank you for trusting me with something that difficult. What you went through was not okay.",
            "Are you safe right now, and is the person who did this still in your life?"
        )

    # ---- SUBSTANCE USE ----
    if "action" in topics and any(a in ("drinking", "drugs", "marijuana") for a in topics["action"]):
        substance = topics["action"][0].replace("_", " ")
        return (
            "I appreciate you being honest about that. It takes courage.",
            f"Is the {substance} something that started recently, or has it been going on for a while?"
        )

    # ---- SELF HARM (not suicidal but harming) ----
    if "action" in topics and "self_harm" in topics["action"]:
        return (
            "I hear you. Thank you for telling me that — it matters that you said it.",
            "When was the last time? And is there anything that helps you resist the urge, even a little?"
        )

    # ---- PERSON + EVENT (not death) ----
    if "person" in topics and "event" in topics:
        person = topics["person"][0]
        for p in ("my ", "our ", "a "): 
            if person.startswith(p): person = person[len(p):]
        event_label = topics["event"][0].replace("_", " ")
        return (
            f"That sounds really difficult, what happened with your {person}.",
            f"Can you tell me more about the situation with your {person}? How is it affecting you right now?"
        )

    # ---- PERSON mentioned alone ----
    if "person" in topics and "person" not in asked_topics:
        person = topics["person"][0]
        for p in ("my ", "our ", "a "): 
            if person.startswith(p): person = person[len(p):]
        return (
            f"Thank you for bringing up your {person}.",
            f"What is happening with your {person} that you want to talk about?"
        )

    # ---- EVENT alone (job loss, eviction, etc.) ----
    if "event" in topics and "event" not in asked_topics:
        event_label = topics["event"][0].replace("_", " ")
        subject = None
        if "event_raw" in topics:
            subject = _extract_subject(user_text, topics["event_raw"][0])
        if event_label == "positive event":
            return (
                "That sounds like something to feel good about.",
                "What made this happen, and how are you feeling about it?"
            )
        return (
            "That is a lot to deal with.",
            f"Can you walk me through what happened? How has the {event_label} been affecting your day-to-day?"
        )

    # ---- FEELING with context ----
    if "feeling" in topics:
        feeling = topics["feeling"][0]
        # Positive feelings
        if feeling in ("happy", "excited", "grateful", "peaceful", "calm", "content", "relieved"):
            return (
                f"It sounds like you are feeling {feeling}, and I am glad to hear that.",
                f"What is contributing to feeling {feeling} today?"
            )
        # "About to break" — urgent
        if feeling in ("about to break", "overwhelmed", "done"):
            return (
                "I can hear that you are at a breaking point. I am right here.",
                "What is the one thing pushing you the hardest right now?"
            )
        # Negative feeling + time
        if "time" in topics:
            time_ref = topics["time"][0]
            return (
                f"I hear that you have been feeling {feeling}.",
                f"You mentioned this has been going on {time_ref}. What started it?"
            )
        # Negative feeling + place
        if "place" in topics:
            place = topics["place"][0]
            return (
                f"I hear that you are feeling {feeling}.",
                f"Is {place} connected to why you feel this way? Tell me more about what is happening there."
            )
        # Negative feeling alone
        return (
            f"I hear that you are feeling {feeling}. That is real, and it matters.",
            f"What do you think is at the root of feeling that way? Take your time."
        )

    # ---- ACTION alone ----
    if "action" in topics and "action" not in asked_topics:
        action = topics["action"][0].replace("_", " ")
        return (
            "Thank you for being honest with me about that.",
            f"How long has the {action} been going on, and what usually triggers it?"
        )

    # ---- PLACE alone (only if no event/action already handled it) ----
    if "place" in topics and "place" not in asked_topics and "event" not in topics and "action" not in topics:
        place = topics["place"][0]
        return (
            "Thank you for sharing that.",
            f"What is happening at {place} that is affecting you?"
        )

    # ---- REFLECT THEIR WORDS — always anchored to what they actually said ----
    # HARD RULE: every question after the first is built ONLY from the user's
    # own words, topic, and flow. No generic questions are ever generated.
    return _anchored_response(user_text, topics, words)


def _meaningful_words(words):
    """Pull the content-bearing words from the user's message (skip filler)."""
    stop = {
        "i", "me", "my", "im", "i'm", "a", "an", "the", "is", "are", "am",
        "was", "were", "be", "been", "to", "of", "and", "but", "or", "so",
        "it", "this", "that", "just", "really", "very", "feel", "feeling",
        "like", "have", "has", "had", "do", "does", "did", "you", "your",
        "for", "in", "on", "at", "with", "about", "right", "now", "today",
        "can", "cant", "not", "no", "yes", "ok", "okay", "ive", "im",
    }
    out = []
    for w in words:
        c = w.strip(".,!?;:\"'")
        if c and c.lower() not in stop:
            out.append(c)
    return out


def _anchored_response(user_text, topics, words):
    """
    Build a response + question ANCHORED to the user's actual words.
    This is the ONLY fallback. It never produces a generic question —
    it always reflects the user's own language back and asks them to
    expand on what THEY said. This enforces the hard listening rule.
    """
    clean = user_text.strip().rstrip(".!?")
    content = _meaningful_words(words)

    # Very short / minimal input — vary by what they actually typed, gently.
    if len(words) <= 2:
        low = user_text.lower().strip().rstrip(".!?")
        greetings = {"hi", "hey", "hello", "yo", "hiya", "sup", "wassup"}
        deflect = {"idk", "dunno", "nothing", "whatever", "k", "meh", "nvm"}
        unsure = {"maybe", "i guess", "kinda", "sorta", "sometimes"}
        if low in greetings:
            return ("Hi. I'm really glad you're here.",
                    "Whenever you're ready, what's bringing you here today?")
        if low in deflect:
            return ("That's okay. We don't have to put a name to it yet.",
                    "We can start small — what's one thing that's been sitting with you lately?")
        if low in unsure:
            return ("That's alright — you don't have to be sure.",
                    "What's the part you're least sure about? We can start there.")
        if low in {"...", "?", ""}:
            return ("I'm here. No rush at all.",
                    "Take a breath — when you're ready, tell me whatever's on your mind.")
        if content:
            return ("I hear you.",
                    f'You said "{content[0]}" — can you tell me what that\'s about for you?')
        return ("I'm here with you.",
                "When you're ready, tell me what brought you here.")

    # Longer input — reflect their actual content words back, ask them to expand.
    if content:
        focus = content[0]
        if len(content) == 2:
            phrase = f"{content[0]} and {content[1]}"
        elif len(content) >= 3:
            phrase = f"{content[0]}, {content[1]}, and {content[2]}"
        else:
            phrase = content[0]
        return (
            f"I'm hearing you talk about {focus}.",
            f"You mentioned {phrase} — can you tell me more about what that's been like for you?"
        )

    # No content words at all (rare) — reflect the literal phrase, still not generic
    short = clean if len(clean) <= 60 else clean[:60].rsplit(" ", 1)[0] + "..."
    return (
        "I hear what you're saying.",
        f'When you say "{short}" — what\'s underneath that for you?'
    )


def _next_crisis_question(asked: List[str]) -> str:
    flow = [
        ("safety", "Are you somewhere safe right now?"),
        ("get_safe", "Is there a way we can help you think through getting to a safer place?"),
        ("someone", "Is there anyone nearby — a neighbor, a friend, anyone — who could be with you right now?"),
        ("one_person", "Who is one person you trust, even if they are far away? Can you reach them by phone or text right now?"),
        ("grounding", "I am staying right here. Can you tell me one thing you can see where you are?"),
        ("next_minute", "Let us just focus on the next sixty seconds. What is one small thing you can do right now to feel even slightly safer?"),
        ("still_here", "I am not going anywhere. Keep talking to me — there is no wrong thing to say."),
    ]
    for topic, q in flow:
        if topic not in asked:
            return q
    return "I am still right here with you. Tell me whatever comes to mind."


def _negative_safety_response(turn_count: int, topics: Dict) -> Tuple[str, str]:
    responses = [
        ("I hear you. You are not alone in this, even though it feels that way right now.",
         "Is there any way we can help you think through getting to a safer place?"),
        ("I am staying right here with you. Nothing you say will make me leave this conversation.",
         "Can you tell me where you are right now? I want to help you think about your next step."),
        ("That took real courage to say. I want you to know that reaching out matters.",
         "What is one small thing — even tiny — that has helped you feel a little safer before?"),
        ("I am not going anywhere. You reached out, and that means something important.",
         "Is there anyone nearby — a neighbor, someone at a store, even a stranger — who could be with you right now?"),
        ("You are doing the right thing by talking to me. Please keep going.",
         "Let us focus on just the next few minutes. What is one thing you could do to change where you are right now?"),
        ("I am still right here. You matter, and this conversation matters.",
         "If you could have one thing right now that would help, what would it be?"),
    ]
    idx = min(turn_count, len(responses) - 1)
    return responses[idx]


def _contradiction_response(face_emotion: str) -> Tuple[str, str]:
    face = (face_emotion or "").lower()
    if face == "sad":
        return (
            "I appreciate you sharing that.",
            "Sometimes what we say and what we feel inside can be different things. Is there something weighing on you that is hard to put into words?"
        )
    if face == "angry":
        return (
            "Thank you for telling me that.",
            "I want to make sure I understand the full picture. Is there something frustrating or upsetting underneath what you are describing?"
        )
    if face == "fearful":
        return (
            "I hear you.",
            "Sometimes we say things are fine even when something feels scary or uncertain. Is there anything worrying you that you have not said yet?"
        )
    return (
        "Thank you for sharing.",
        "I want to make sure I really understand how you are feeling. Can you tell me more?"
    )


class ConversationEngine:
    def __init__(self):
        self.asked_topics: List[str] = []
        self.turn_history: List[Dict[str, Any]] = []

    def respond(
        self,
        user_text: str,
        face_emotion: str = "",
        risk: str = "low",
        learning_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = learning_state or {}
        turn_count = int(state.get("turn_count", 0))
        topics = extract_topics(user_text)

        response, question = generate_response(
            user_text, topics, face_emotion, risk, turn_count, self.asked_topics,
        )

        for cat in topics:
            if cat not in ("event_raw",) and cat not in self.asked_topics:
                self.asked_topics.append(cat)

        self.turn_history.append({
            "turn": turn_count,
            "user": user_text[:200],
            "topics": {k: v for k, v in topics.items() if k != "event_raw"},
            "face": face_emotion,
            "response": response,
            "question": question,
        })

        return {
            "response": response,
            "question": question,
            "topics_detected": {k: v for k, v in topics.items() if k != "event_raw"},
            "face_emotion_used": face_emotion,
            "asked_topics_so_far": list(self.asked_topics),
        }


_engine = ConversationEngine()

def get_conversation_engine() -> ConversationEngine:
    return _engine


if __name__ == "__main__":
    engine = ConversationEngine()
    tests = [
        ("My dog died yesterday", "sad"),
        ("My mom passed away last month", "sad"),
        ("I feel happy because I just beat up five people", "angry"),
        ("I'm fine everything is great", "sad"),
        ("I want to die", "fearful"),
        ("No", "fearful"),
        ("I've been drinking a lot since my girlfriend left me", "sad"),
        ("I got evicted and I'm living in my car", "fearful"),
        ("My dad hit me again last night", "fearful"),
        ("I'm going through it right now fr", "sad"),
        ("I'm finna lose it", "angry"),
        ("Nobody cares about me", "sad"),
        ("I just got promoted at work", "happy"),
    ]
    for text, face in tests:
        r = engine.respond(text, face_emotion=face, risk="critical" if "want to die" in text.lower() or "kill myself" in text.lower() else "low")
        print(f"\nUSER: {text}  (face: {face})")
        print(f"  AI: {r['response']}")
        print(f"  Q:  {r['question']}")
