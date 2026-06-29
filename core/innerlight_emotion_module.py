from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

try:
    from facial_emotion_recognition import analyze_image_data_url
except Exception:
    analyze_image_data_url = None


class InnerLightEmotionModule:
    """
    Multimodal emotion learning for InnerLight.

    The module reads typed words, microphone transcripts/tone hints, and
    visual emotion signals. It does not diagnose and it does not treat
    visual/voice inference as perfect; it creates correctable cues that
    InnerLight can use to ask better questions and adapt Zenisys.
    """

    EMOTION_RULES: Dict[str, List[str]] = {
        "despair": [
            "hate life", "hate my life", "want to die", "end my life", "kill myself",
            "no reason to live", "rather be dead", "can't go on", "cannot go on",
            "hopeless", "worthless", "give up on life",
        ],
        "fear_or_anxiety": [
            "anxious", "panic", "scared", "afraid", "terrified", "worried",
            "can't breathe", "cannot breathe", "racing heart", "overwhelmed",
        ],
        "sadness_or_grief": [
            "sad", "depressed", "crying", "grief", "lost someone", "empty",
            "lonely", "alone", "hurt",
        ],
        "anger_or_betrayal": [
            "angry", "mad", "furious", "rage", "betrayed", "unfair",
            "they did this", "lied", "ignored",
        ],
        "shame_or_guilt": [
            "ashamed", "guilty", "embarrassed", "my fault", "burden",
            "disappointed in me",
        ],
        "numb_or_dissociated": [
            "numb", "nothing feels real", "can't feel", "cannot feel",
            "blank", "detached", "outside my body",
        ],
        "confusion_or_uncertainty": [
            "confused", "don't know", "do not know", "not sure", "unclear",
            "lost", "what is happening",
        ],
        "calm_or_hopeful": [
            "calm", "safe", "hopeful", "better", "relieved", "okay",
            "i am safe", "not going to hurt myself",
        ],
    }

    VISUAL_MAP = {
        "angry": "anger_or_betrayal",
        "anger": "anger_or_betrayal",
        "fear": "fear_or_anxiety",
        "sad": "sadness_or_grief",
        "sadness": "sadness_or_grief",
        "disgust": "distress_or_discomfort",
        "surprise": "confusion_or_uncertainty",
        "happy": "calm_or_hopeful",
        "neutral": "neutral_or_masked",
        "calm": "calm_or_hopeful",
        "crying": "sadness_or_grief",
        "flat": "numb_or_dissociated",
    }

    DISTRESS_WEIGHTS = {
        "despair": 10,
        "fear_or_anxiety": 8,
        "sadness_or_grief": 7,
        "anger_or_betrayal": 7,
        "shame_or_guilt": 7,
        "numb_or_dissociated": 7,
        "confusion_or_uncertainty": 5,
        "distress_or_discomfort": 6,
        "neutral_or_masked": 4,
        "calm_or_hopeful": 2,
    }

    def analyze(self, payload: Dict[str, Any], extra_text: Iterable[str] | None = None) -> Dict[str, Any]:
        extra_text = list(extra_text or [])
        typed_text = " ".join([
            str(payload.get("message", "")),
            str(payload.get("known_diagnoses", "")),
            str(payload.get("typed_emotion", "")),
            *[str(value) for value in extra_text],
        ]).strip()
        voice_text = " ".join([
            str(payload.get("voice_transcript", "")),
            str(payload.get("voice_emotion", "")),
        ]).strip()
        visual_hint = str(payload.get("visual_emotion", "")).strip()
        visual_frame = str(payload.get("visual_frame", "")).strip()

        source_scores: Dict[str, Dict[str, Any]] = {}
        source_scores["typed"] = self._score_text(typed_text, "typed")
        source_scores["voice"] = self._score_text(voice_text, "voice")
        source_scores["visual"] = self._score_visual(visual_hint, visual_frame)

        combined: Dict[str, float] = {}
        for source, profile in source_scores.items():
            weight = {"typed": 1.0, "voice": 0.9, "visual": 0.8}.get(source, 0.7)
            for emotion, score in profile.get("scores", {}).items():
                combined[emotion] = combined.get(emotion, 0.0) + (float(score) * weight)

        if not combined:
            combined["needs_more_context"] = 1.0

        primary_emotion = "despair" if combined.get("despair", 0) > 0 else max(combined.items(), key=lambda item: item[1])[0]
        distress_score = self._distress_score(combined)
        confidence = self._confidence(source_scores, combined)
        safety_flags = self._safety_flags(combined, source_scores, typed_text, voice_text)

        return {
            "status": "emotion_profile_ready",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "primary_emotion": primary_emotion,
            "emotion_scores": {key: round(value, 3) for key, value in sorted(combined.items())},
            "distress_score": distress_score,
            "confidence": confidence,
            "sources": source_scores,
            "safety_flags": safety_flags,
            "zenisys_mode_hint": self._zenisys_hint(primary_emotion, distress_score, safety_flags),
            "questions": self._questions(primary_emotion, safety_flags, source_scores),
            "provider_focus_hint": self._provider_focus(primary_emotion, distress_score),
            "notice": "Emotion cues are used to ask better questions and route support. They are not a diagnosis, and the user can correct them.",
        }

    def _score_text(self, text: str, source: str) -> Dict[str, Any]:
        normalized = self._normalize(text)
        scores: Dict[str, float] = {}
        matches: Dict[str, List[str]] = {}
        for emotion, terms in self.EMOTION_RULES.items():
            hits = [term for term in terms if term in normalized]
            if hits:
                scores[emotion] = scores.get(emotion, 0.0) + len(hits)
                matches[emotion] = hits
        if normalized and not scores:
            scores["confusion_or_uncertainty"] = 0.4
        return {
            "source": source,
            "available": bool(normalized),
            "primary_emotion": max(scores.items(), key=lambda item: item[1])[0] if scores else "",
            "scores": scores,
            "matched_terms": matches,
            "fingerprint": self._fingerprint(normalized) if normalized else "",
        }

    def _score_visual(self, visual_hint: str, visual_frame: str) -> Dict[str, Any]:
        scores: Dict[str, float] = {}
        detected = ""
        status = "not_provided"
        fingerprint = self._fingerprint(visual_frame) if visual_frame else ""

        if visual_frame and analyze_image_data_url is not None:
            result = analyze_image_data_url(visual_frame)
            status = result.get("status", "analyzed")
            detected = str(result.get("dominant_emotion", "")).strip()
        elif visual_frame:
            status = "visual_engine_unavailable"

        label = (detected or visual_hint).strip().lower()
        mapped = self.VISUAL_MAP.get(label, label.replace(" ", "_")) if label else ""
        if mapped:
            scores[mapped] = 1.0
            status = status if detected else "hint_received"

        return {
            "source": "visual",
            "available": bool(mapped or visual_frame),
            "status": status,
            "dominant_emotion": detected or visual_hint,
            "primary_emotion": mapped,
            "scores": scores,
            "fingerprint": fingerprint,
            "stored_raw_image": False,
        }

    def _distress_score(self, combined: Dict[str, float]) -> int:
        numerator = 0.0
        denominator = 0.0
        for emotion, score in combined.items():
            numerator += self.DISTRESS_WEIGHTS.get(emotion, 5) * score
            denominator += score
        if denominator <= 0:
            return 4
        return max(1, min(10, round(numerator / denominator)))

    def _confidence(self, source_scores: Dict[str, Dict[str, Any]], combined: Dict[str, float]) -> float:
        active_sources = sum(1 for item in source_scores.values() if item.get("available"))
        total_strength = sum(combined.values())
        confidence = min(0.95, 0.25 + (active_sources * 0.2) + min(total_strength, 4.0) * 0.08)
        return round(confidence, 2)

    def _safety_flags(
        self,
        combined: Dict[str, float],
        source_scores: Dict[str, Dict[str, Any]],
        typed_text: str,
        voice_text: str,
    ) -> List[str]:
        flags: List[str] = []
        if combined.get("despair", 0) > 0:
            flags.append("possible_self_harm_language")
        if self._distress_score(combined) >= 8:
            flags.append("high_visible_or_reported_distress")
        if "numb_or_dissociated" in combined:
            flags.append("possible_shutdown_or_dissociation")
        typed_primary = source_scores.get("typed", {}).get("primary_emotion")
        visual_primary = source_scores.get("visual", {}).get("primary_emotion")
        voice_primary = source_scores.get("voice", {}).get("primary_emotion")
        if typed_primary and visual_primary and typed_primary != visual_primary:
            flags.append("typed_visual_emotion_mismatch")
        if typed_primary and voice_primary and typed_primary != voice_primary:
            flags.append("typed_voice_emotion_mismatch")
        text = self._normalize(f"{typed_text} {voice_text}")
        if any(term in text for term in ["pills", "gun", "knife", "weapon", "bridge", "rope"]):
            flags.append("possible_means_or_environment_risk")
        return sorted(set(flags))

    def _zenisys_hint(self, primary_emotion: str, distress_score: int, safety_flags: List[str]) -> str:
        if distress_score >= 9 or "possible_self_harm_language" in safety_flags:
            return "crisis"
        if primary_emotion in {"fear_or_anxiety", "anger_or_betrayal", "sadness_or_grief"} or distress_score >= 7:
            return "calming"
        if primary_emotion in {"numb_or_dissociated", "confusion_or_uncertainty"}:
            return "grounding"
        if primary_emotion == "calm_or_hopeful":
            return "encouragement"
        return "greeting"

    def _questions(
        self,
        primary_emotion: str,
        safety_flags: List[str],
        source_scores: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        questions = []
        if "typed_visual_emotion_mismatch" in safety_flags or "typed_voice_emotion_mismatch" in safety_flags:
            questions.append("Your words, voice, or face may be showing different emotions. Which one feels most true right now?")
        if primary_emotion == "despair":
            questions.append("What happened that made life feel unbearable today?")
        elif primary_emotion == "fear_or_anxiety":
            questions.append("What feels most threatening right now: your body, your thoughts, another person, or a situation?")
        elif primary_emotion == "anger_or_betrayal":
            questions.append("Who or what made you feel harmed, betrayed, ignored, or unsafe?")
        elif primary_emotion == "sadness_or_grief":
            questions.append("Is this sadness connected to loss, loneliness, exhaustion, or something that happened today?")
        elif primary_emotion == "numb_or_dissociated":
            questions.append("Do you feel shut down, disconnected, or like things around you do not feel real?")
        else:
            questions.append("What emotion is strongest in your body right now?")
        if source_scores.get("visual", {}).get("available"):
            questions.append("Does the visual emotion reading feel accurate, or should InnerLight correct it?")
        if source_scores.get("voice", {}).get("available"):
            questions.append("Did speaking that out loud change the feeling, even a little?")
        questions.append("Should Zenisys become softer, quieter, warmer, or more grounding?")
        return questions[:5]

    def _provider_focus(self, primary_emotion: str, distress_score: int) -> str:
        if distress_score >= 9 or primary_emotion == "despair":
            return "Immediate safety screening with crisis-trained clinician or telehealth practitioner."
        if primary_emotion in {"fear_or_anxiety", "numb_or_dissociated"}:
            return "Therapist or psychiatric review after safety questions, with grounding support."
        if primary_emotion in {"anger_or_betrayal"}:
            return "Trauma-informed support and legal/access review if rights, safety, or medication access are involved."
        return "Supportive intake, symptom-domain review, and provider matching."

    @staticmethod
    def _normalize(value: str) -> str:
        text = value.lower().replace("’", "'")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]
