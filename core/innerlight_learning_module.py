from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from crisis_response_core import CrisisResponseCore
from innerlight_emotion_module import InnerLightEmotionModule


class InnerLightLearningModule:
    """
    Progressive learning layer for InnerLight.

    This learns inside a user's session. It does not diagnose. It updates risk,
    symptom domains, legal/access flags, provider direction, next questions,
    and Zenisys sound mode as the person answers.
    """

    def __init__(self):
        self.crisis_core = CrisisResponseCore()
        self.emotions = InnerLightEmotionModule()

    def start_state(self, initial_result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "version": "innerlight-learning-v1",
            "created_at": self._now(),
            "updated_at": self._now(),
            "turn_count": 0,
            "risk_history": [initial_result.get("risk", "low")],
            "current_risk": initial_result.get("risk", "low"),
            "current_severity": initial_result.get("severity", 2),
            "emotion_history": [initial_result.get("emotion_profile", {})] if initial_result.get("emotion_profile") else [],
            "current_emotion": (initial_result.get("emotion_profile") or {}).get("primary_emotion", ""),
            "emotion_confidence": (initial_result.get("emotion_profile") or {}).get("confidence", 0),
            "learned_preferences": {
                "sound": (initial_result.get("zenisys") or {}).get("preference", "warm ambient"),
                "support": "",
                "culture": initial_result.get("culture_signal", ""),
                "language": "",
            },
            "learned_needs": [],
            "symptom_domains": [
                item.get("domain") for item in ((initial_result.get("symptom_signals") or {}).get("domains") or [])
            ],
            "legal_flags": [],
            "safety": {
                "alone": "unknown",
                "immediate_danger": "unknown",
                "means_nearby": "unknown",
                "trusted_person": "unknown",
            },
            "case_notes": [],
            "next_question_index": 0,
        }

    def learn(self, answer: str, state: Dict[str, Any] | None, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        state = dict(state or {})
        if not state:
            state = self.start_state(context or {})

        answer = (answer or "").strip()
        normalized = self._normalize(answer)
        crisis = self.crisis_core.evaluate(answer)
        emotion_payload = dict(context or {})
        emotion_payload["message"] = answer
        emotion_payload["known_diagnoses"] = " ".join(state.get("symptom_domains", []))
        emotion_profile = self.emotions.analyze(emotion_payload)
        state["turn_count"] = int(state.get("turn_count", 0)) + 1
        state["updated_at"] = self._now()
        state["current_emotion"] = emotion_profile.get("primary_emotion", "")
        state["emotion_confidence"] = emotion_profile.get("confidence", 0)
        state.setdefault("emotion_history", []).append({
            "turn": state["turn_count"],
            "primary_emotion": emotion_profile.get("primary_emotion", ""),
            "distress_score": emotion_profile.get("distress_score"),
            "confidence": emotion_profile.get("confidence"),
            "safety_flags": emotion_profile.get("safety_flags", []),
            "created_at": emotion_profile.get("created_at"),
        })
        state.setdefault("case_notes", []).append({
            "turn": state["turn_count"],
            "answer_fingerprint": self._fingerprint(answer),
            "observed_at": self._now(),
            "summary": self._summarize_answer(answer),
        })

        self._learn_safety(normalized, state)
        self._learn_domains(normalized, state)
        self._learn_preferences(normalized, state)
        self._learn_legal_flags(normalized, state)

        risk = self._combined_risk(crisis.risk, state, emotion_profile)
        severity = {"critical": 10, "high": 8, "moderate": 6, "low": 2}.get(risk, 4)
        state["current_risk"] = risk
        state["current_severity"] = severity
        state.setdefault("risk_history", []).append(risk)

        next_questions = self._next_questions(state, emotion_profile)
        sound_mode = self._sound_mode(state, emotion_profile)
        telehealth = self._telehealth(state)

        return {
            "status": "learned",
            "learning_state": state,
            "risk": risk,
            "severity": severity,
            "response": self._response_for_state(state, emotion_profile),
            "questions": next_questions,
            "emotion_profile": emotion_profile,
            "zenisys": {
                "name": "Zenisys Sound System",
                "mode": sound_mode,
                "adaptive_learning": True,
                "reason": "Updated from the latest answer, emotion signals, and session risk.",
                "emotion_feedback": {
                    "primary_emotion": emotion_profile.get("primary_emotion", ""),
                    "distress_score": emotion_profile.get("distress_score"),
                    "confidence": emotion_profile.get("confidence"),
                },
            },
            "telehealth": telehealth,
            "provider_focus": self._provider_focus(state),
            "case_file_update": {
                "case_reference": self._fingerprint(str(state.get("created_at", "")) + str(state.get("turn_count", ""))),
                "turn_count": state["turn_count"],
                "professional_review_notice": "Session learning organizes symptoms and needs for licensed professional review; it is not a diagnosis.",
            },
        }

    def _learn_safety(self, text: str, state: Dict[str, Any]) -> None:
        safety = state.setdefault("safety", {})
        if re.search(r"\b(yes|right now|immediate|not safe|danger|i might|i will)\b", text):
            if any(term in text for term in ["hurt", "kill", "die", "danger", "not safe"]):
                safety["immediate_danger"] = "yes"
        if re.search(r"\b(no|not right now|safe|i am safe)\b", text):
            safety["immediate_danger"] = "no"
        if "alone" in text:
            safety["alone"] = "yes" if not any(term in text for term in ["not alone", "with someone"]) else "no"
        if any(term in text for term in ["weapon", "gun", "knife", "pills", "medication near", "means"]):
            safety["means_nearby"] = "yes"
        if any(term in text for term in ["called", "texted", "friend", "mother", "father", "sister", "brother", "trusted"]):
            safety["trusted_person"] = "possible"

    def _learn_domains(self, text: str, state: Dict[str, Any]) -> None:
        domains = set(state.get("symptom_domains", []))
        rules = {
            "anxiety_or_panic": ["anxious", "panic", "worry", "scared", "fear"],
            "depressive_or_grief_signals": ["sad", "depressed", "hopeless", "empty", "worthless"],
            "trauma_or_stress_response": ["trauma", "abuse", "flashback", "unsafe", "trigger"],
            "psychosis_reality_testing_concern": ["voices", "hearing", "seeing", "paranoid", "watched"],
            "mania_or_sleep_disruption": ["no sleep", "manic", "racing", "impulsive", "too much energy"],
            "neurodevelopmental_support": ["autism", "adhd", "sensory", "overstimulated"],
            "substance_or_medication_concern": ["medication", "pills", "withdrawal", "alcohol", "drug"],
            "access_or_rights_barrier": ["denied", "access", "insurance", "pharmacy", "school", "rights"],
        }
        for domain, terms in rules.items():
            if any(term in text for term in terms):
                domains.add(domain)
        state["symptom_domains"] = sorted(domains)

    def _learn_preferences(self, text: str, state: Dict[str, Any]) -> None:
        prefs = state.setdefault("learned_preferences", {})
        if any(term in text for term in ["piano", "music"]):
            prefs["sound"] = "soft piano"
        elif any(term in text for term in ["nature", "rain", "ocean", "water"]):
            prefs["sound"] = "nature-like"
        elif any(term in text for term in ["quiet", "low", "soft"]):
            prefs["sound"] = "low calming tone"
        if any(term in text for term in ["therapist", "therapy"]):
            prefs["support"] = "therapy"
        elif any(term in text for term in ["psychiatrist", "medication"]):
            prefs["support"] = "psychiatry"
        elif any(term in text for term in ["legal", "law", "rights"]):
            prefs["support"] = "legal/access help"

    def _learn_legal_flags(self, text: str, state: Dict[str, Any]) -> None:
        flags = set(state.get("legal_flags", []))
        rules = {
            "medication_access": ["medication", "pharmacy", "prescription", "pills"],
            "child_or_family_access": ["daughter", "son", "child", "custody", "guardian"],
            "education_rights": ["school", "iep", "504", "teacher"],
            "insurance_or_benefits": ["insurance", "benefits", "denied"],
            "civil_rights_or_discrimination": ["discrimination", "rights", "ada", "civil rights"],
        }
        for flag, terms in rules.items():
            if any(term in text for term in terms):
                flags.add(flag)
        state["legal_flags"] = sorted(flags)

    def _combined_risk(self, latest_risk: str, state: Dict[str, Any], emotion_profile: Dict[str, Any]) -> str:
        safety = state.get("safety", {})
        emotion_flags = set(emotion_profile.get("safety_flags", []))
        distress = int(emotion_profile.get("distress_score", 0))
        if safety.get("immediate_danger") == "yes" or safety.get("means_nearby") == "yes":
            return "critical"
        if distress >= 9 or "possible_self_harm_language" in emotion_flags or "possible_means_or_environment_risk" in emotion_flags:
            return "critical"
        if latest_risk == "critical":
            return "critical"
        if latest_risk == "high" or safety.get("alone") == "yes" or distress >= 7:
            return "high"
        if latest_risk == "moderate" or distress >= 5:
            return "moderate"
        return state.get("current_risk", "low")

    def _next_questions(self, state: Dict[str, Any], emotion_profile: Dict[str, Any]) -> List[str]:
        safety = state.get("safety", {})
        domains = set(state.get("symptom_domains", []))
        legal_flags = set(state.get("legal_flags", []))
        questions = list(emotion_profile.get("questions", []))
        if safety.get("immediate_danger") == "unknown":
            questions.append("Are you safe from hurting yourself right now: yes, no, or not sure?")
        if safety.get("alone") == "unknown":
            questions.append("Are you alone right now, or is someone safe nearby?")
        if safety.get("trusted_person") == "unknown":
            questions.append("Who is one person you could message or call while we keep talking?")
        if "psychosis_reality_testing_concern" in domains:
            questions.append("Are the voices, visions, or fears telling you to do anything unsafe?")
        if "mania_or_sleep_disruption" in domains:
            questions.append("How much have you slept in the last 24 hours?")
        if "substance_or_medication_concern" in domains:
            questions.append("Are medication side effects, missed doses, withdrawal, or pharmacy access involved?")
        if legal_flags:
            questions.append("What city, county, state, agency, school, pharmacy, or provider is involved?")
        questions.append("What would help you feel one degree safer in the next five minutes?")
        return self._dedupe(questions)[:7]

    def _sound_mode(self, state: Dict[str, Any], emotion_profile: Dict[str, Any]) -> str:
        risk = state.get("current_risk", "low")
        if risk == "critical":
            return "crisis"
        if risk == "high":
            return "calming"
        hint = emotion_profile.get("zenisys_mode_hint")
        if hint in {"grounding", "calming", "encouragement"}:
            return hint
        if risk == "moderate":
            return "encouragement"
        return "greeting"

    def _telehealth(self, state: Dict[str, Any]) -> Dict[str, Any]:
        risk = state.get("current_risk", "low")
        return {
            "available": True,
            "urgency": "immediate" if risk in {"critical", "high"} else "standard",
            "video_room": "/telehealth/urgent" if risk in {"critical", "high"} else "/telehealth/intake",
            "handoff": "Encrypted learning summary can be sent to a practitioner only with user consent.",
        }

    def _provider_focus(self, state: Dict[str, Any]) -> str:
        domains = set(state.get("symptom_domains", []))
        if "psychosis_reality_testing_concern" in domains or "mania_or_sleep_disruption" in domains:
            return "Prioritize psychiatry or urgent telehealth review."
        if "substance_or_medication_concern" in domains:
            return "Prioritize nurse practitioner, psychiatry, pharmacy access, or medication review."
        if state.get("legal_flags"):
            return "Coordinate mental health support with CRASH/VEIL legal-access routing."
        return "Continue guided InnerLight intake and match to therapy, psychiatry, telehealth, or community support."

    def _response_for_state(self, state: Dict[str, Any], emotion_profile: Dict[str, Any]) -> str:
        risk = state.get("current_risk", "low")
        emotion = str(emotion_profile.get("primary_emotion", "")).replace("_", " ")
        emotion_line = f" I may be reading {emotion}; if that is wrong, correct me and I will adjust." if emotion else ""
        if risk == "critical":
            return "You are loved. You are important. Stay with me and answer one small question at a time. We are building the safest next step together." + emotion_line
        if risk == "high":
            return "I hear you. Let us keep this gentle and specific. Your answers are helping InnerLight understand what kind of support fits." + emotion_line
        if risk == "moderate":
            return "Thank you. I am learning what is happening so the support can become more accurate and less generic." + emotion_line
        return "Thank you. I am learning your preferences, needs, and next best support path." + emotion_line

    @staticmethod
    def _dedupe(items: List[str]) -> List[str]:
        seen = set()
        result = []
        for item in items:
            text = str(item).strip()
            key = text.lower()
            if text and key not in seen:
                result.append(text)
                seen.add(key)
        return result

    @staticmethod
    def _summarize_answer(answer: str) -> str:
        clean = re.sub(r"\s+", " ", answer).strip()
        return clean[:220]

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").lower()).strip()

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
