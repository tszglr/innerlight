from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class CrisisResult:
    risk: str
    severity: int
    category: str
    matched_phrases: List[str]
    public_response: str
    next_steps: List[str]
    questions: List[str]
    provider_focus: str
    sound_mode: str
    needs_immediate_support: bool

    def to_dict(self) -> Dict:
        return {
            "risk": self.risk,
            "severity": self.severity,
            "category": self.category,
            "matched_phrases": self.matched_phrases,
            "public_response": self.public_response,
            "next_steps": self.next_steps,
            "questions": self.questions,
            "provider_focus": self.provider_focus,
            "sound_mode": self.sound_mode,
            "needs_immediate_support": self.needs_immediate_support,
        }


class CrisisResponseCore:
    """
    Deterministic safety gate for public check-ins.

    This must run before GPT/model response generation. Learned response models
    can help with tone only after the safety category is already decided.
    """

    CRITICAL_PATTERNS = [
        r"\bi hate life\b",
        r"\bi hate my life\b",
        r"\bdo not want to live\b",
        r"\bdo not wanna live\b",
        r"\bdon'?t want to live\b",
        r"\bdon'?t wanna live\b",
        r"\bdon'?t want to be here\b",
        r"\bwant to die\b",
        r"\bwant to end my life\b",
        r"\bend my life\b",
        r"\bkill myself\b",
        r"\bgoing to kill myself\b",
        r"\bplan to kill myself\b",
        r"\bkill me\b",
        r"\bsuicid(?:e|al)\b",
        r"\bthinking about suicide\b",
        r"\bself[-\s]?harm\b",
        r"\bno reason to live\b",
        r"\brather be dead\b",
        r"\bwish i was dead\b",
        r"\blife is not worth living\b",
        r"\blife isn't worth living\b",
        r"\bi can'?t go on\b",
        r"\bi cannot go on\b",
        r"\bi can'?t do this anymore\b",
        r"\bi cannot do this anymore\b",
        r"\bi give up on life\b",
        # --- Sideways phrasings (people in crisis rarely use the textbook words;
        # --- these were added after testing showed real disclosures slipping past) ---
        r"\b(?:do not|don'?t) want to (?:be alive|exist|wake up)\b",
        r"\bwant to be dead\b",
        r"\bbetter off dead\b",
        r"\bbetter off without me\b",
        r"\btak(?:e|ing) my (?:own )?life\b",
        r"\bend(?:ing)? it (?:all|tonight|today|soon)\b",
        r"\bthinking (?:about|of) ending (?:it|things|everything|my life)\b",
        r"\b(?:hope|wish) i (?:die|don'?t wake up|do not wake up|never wake up)\b",
        r"\bnever want to wake up\b",
        r"\bgo to sleep and (?:not|never) wake up\b",
        r"\bunalive\b",
        r"\bno point in living\b",
        r"\bno point (?:in )?going on\b",
        r"\bdone with life\b",
        r"\bdone living\b",
        r"\bsay(?:ing)? my goodbyes\b",
        r"\bwish i wasn'?t here\b",
        r"\bwish i wasn'?t alive\b",
        r"\bwish i(?:'?d| had)? never been born\b",
        r"\b(?:want|wanna|going|gonna|thinking about|thought about|urge) (?:to )?hurt(?:ing)? myself\b",
        r"\b(?:been )?cutting myself\b",
        r"\bwant to cut myself\b",
        r"\bhang myself\b",
        r"\bshoot myself\b",
        r"\boverdose\b",
        r"\bsucide\b",
        r"\bsuiside\b",
    ]

    HIGH_PATTERNS = [
        r"\bi give up\b",
        r"\bi can'?t take it\b",
        r"\bi cannot take it\b",
        r"\bi feel hopeless\b",
        r"\bi am hopeless\b",
        r"\bnobody cares\b",
        r"\bno one cares\b",
        r"\bi feel trapped\b",
        r"\bi am trapped\b",
        r"\bi need help\b",
        r"\bhelp me\b",
        r"\bi hate everything\b",
        r"\bwant (?:it|everything) to (?:end|stop|be over)\b",
        r"\bwant the pain to (?:end|stop)\b",
        r"\bcan'?t keep going\b",
        r"\bcannot keep going\b",
        r"\bwhat'?s the point\b",
    ]

    MODERATE_PATTERNS = [
        r"\banxious\b",
        r"\bpanic\b",
        r"\boverwhelmed\b",
        r"\bdepressed\b",
        r"\bsad\b",
        r"\balone\b",
        r"\blost\b",
        r"\bscared\b",
        r"\bafraid\b",
    ]

    def evaluate(self, text: str, preferred_name: str | None = None) -> CrisisResult:
        normalized = self._normalize(text)
        name = self._safe_name(preferred_name)
        address = f"{name}, " if name else ""
        critical = self._matches(normalized, self.CRITICAL_PATTERNS)
        if critical:
            return CrisisResult(
                risk="critical",
                severity=10,
                category="immediate_crisis_support",
                matched_phrases=critical,
                public_response=(
                    f"{address}you are loved. You are important. Stay with me for a moment. "
                    "You do not have to solve your whole life right now; we only need to protect the next few minutes. "
                    "Why do you feel this way right now? I am going to ask short questions so we can understand what is happening "
                    "and guide you toward the right kind of help. If you might hurt yourself right now, call or text 988 in the U.S. "
                    "or call emergency services while you stay here."
                ),
                next_steps=[
                    "Answer the first question below with one word if that is all you can manage.",
                    "Move away from weapons, pills, or anything you could use to hurt yourself.",
                    "Put one trusted person near you or on the phone if you can.",
                    "If you are close to acting on self-harm, call or text 988 in the U.S. or call emergency services now.",
                ],
                questions=[
                    "Are you in immediate danger of hurting yourself right now: yes, no, or not sure?",
                    "Are you alone right now, or is there one trusted person nearby?",
                    "Is there anything near you that you could use to hurt yourself?",
                    "What happened today that made life feel unbearable?",
                    "What is one reason, person, promise, memory, or responsibility that can help you stay alive for the next ten minutes?",
                    "Do you want immediate crisis support, a therapist, a psychiatrist, a spiritual/community support person, or help finding the right provider?",
                ],
                provider_focus="Immediate crisis stabilization first, then therapist/psychiatry routing after safety is confirmed.",
                sound_mode="crisis",
                needs_immediate_support=True,
            )

        high = self._matches(normalized, self.HIGH_PATTERNS)
        if high:
            return CrisisResult(
                risk="high",
                severity=8,
                category="urgent_support",
                matched_phrases=high,
                public_response=(
                    f"{address}I am glad you told me. I hear that this is heavy, and I am not going to rush past it. "
                    "Let us slow the moment down, understand what kind of support you need, and choose the safest next step."
                ),
                next_steps=[
                    "Answer one question below before you make any big decision.",
                    "Reach out to a trusted person if you can.",
                    "If thoughts of self-harm are present, call or text 988 in the U.S.",
                ],
                questions=[
                    "Are you having thoughts of hurting yourself, or is this more about exhaustion and overwhelm?",
                    "What is the strongest feeling right now: fear, anger, grief, shame, numbness, or something else?",
                    "Do you feel safer talking, listening to calming sound, praying, breathing, or being connected to a provider?",
                    "Would you prefer help from a therapist, psychiatrist, crisis counselor, peer support, or faith/community support?",
                ],
                provider_focus="Urgent support screening; route to crisis counselor if self-harm is present, otherwise therapist or psychiatrist based on symptoms.",
                sound_mode="calming",
                needs_immediate_support=True,
            )

        moderate = self._matches(normalized, self.MODERATE_PATTERNS)
        if moderate:
            return CrisisResult(
                risk="moderate",
                severity=6,
                category="supportive_grounding",
                matched_phrases=moderate,
                public_response=(
                    f"{address}thank you for saying that clearly. This moment deserves care, not judgment. "
                    "Let us understand what is happening and choose the kind of help that actually fits."
                ),
                next_steps=[
                    "Answer one question below.",
                    "Sit somewhere quieter or drink water if you can.",
                    "Let the sound layer run while you name what support would help.",
                ],
                questions=[
                    "Is this mostly anxiety, sadness, anger, trauma, stress, loneliness, or something mixed?",
                    "How long has this been building: today, this week, months, or years?",
                    "What has helped even a little in the past?",
                    "Would you like therapy, psychiatry, coaching, peer support, spiritual support, or help deciding?",
                ],
                provider_focus="Non-emergency mental health support; route by symptom pattern, duration, and preferred support type.",
                sound_mode="encouragement",
                needs_immediate_support=False,
            )

        return CrisisResult(
            risk="low",
            severity=2,
            category="steady_checkin",
            matched_phrases=[],
            public_response=(
                f"{address}thank you for checking in. I am here with you. We can take this one step at a time and learn what kind of support fits."
            ),
            next_steps=[
                "Answer one question below.",
                "Keep the sound layer on if it helps you settle.",
            ],
            questions=[
                "What made you open this check-in today?",
                "Do you want emotional support, practical guidance, provider matching, or spiritual support?",
                "What would make the next ten minutes easier?",
            ],
            provider_focus="General support and provider matching based on what the person says next.",
            sound_mode="greeting",
            needs_immediate_support=False,
        )

    @staticmethod
    def _normalize(text: str) -> str:
        lowered = (text or "").lower()
        lowered = lowered.replace("â€™", "'")
        return re.sub(r"\s+", " ", lowered).strip()

    @staticmethod
    def _matches(text: str, patterns: List[str]) -> List[str]:
        return [pattern for pattern in patterns if re.search(pattern, text)]

    @staticmethod
    def _safe_name(value: str | None) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9 .'-]", "", value or "").strip()
        return cleaned[:40]

