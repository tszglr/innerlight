from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from crisis_response_core import CrisisResponseCore
from innerlight_emotion_module import InnerLightEmotionModule
from provider_database import ProviderDatabase


class InnerLightSystem:
    """
    Unified InnerLight routing core.

    This is not a diagnostic engine. It organizes user-reported symptoms,
    safety needs, cultural context, telehealth routing, provider matching,
    Zenisys sound mode, and CRASH/VEIL legal activation for clinician or
    attorney review.
    """

    LEGAL_TERMS = [
        "medication", "pharmacy", "prescription", "insurance", "denied",
        "access", "daughter", "son", "child", "school", "iep", "504",
        "accommodation", "discrimination", "court", "law", "rights",
        "custody", "guardian", "hospital", "agency", "state", "federal",
        "city", "county", "police", "housing", "benefits",
    ]

    def __init__(self):
        self.crisis_core = CrisisResponseCore()
        self.emotions = InnerLightEmotionModule()
        self.providers = ProviderDatabase()

    def process(self, payload: Dict[str, Any], clarion_analysis: Dict[str, Any], culture_signal: str, local_context: str) -> Dict[str, Any]:
        message = str(payload.get("message", "")).strip()
        profile = self._profile(payload)
        crisis = self.crisis_core.evaluate(message, profile.get("name"))
        emotion_profile = self.emotions.analyze(payload)
        symptom_signals = self._symptom_signals(message, profile, emotion_profile)
        telehealth = self._telehealth_plan(crisis, symptom_signals, payload, emotion_profile)
        providers = self._provider_matches(crisis, symptom_signals, profile)
        legal_activation = self._legal_activation(payload, message, profile)
        case_file = self._case_file(
            message=message,
            profile=profile,
            crisis=crisis.to_dict(),
            clarion_analysis=clarion_analysis,
            symptom_signals=symptom_signals,
            culture_signal=culture_signal,
            local_context=local_context,
            emotion_profile=emotion_profile,
            telehealth=telehealth,
            providers=providers,
            legal_activation=legal_activation,
            consent=bool(payload.get("consent_case_file")),
        )

        return {
            "profile_safe": self._safe_profile_summary(profile),
            "crisis": crisis.to_dict(),
            "response": crisis.public_response,
            "questions": self._dedupe_questions(
                crisis.questions
                + emotion_profile.get("questions", [])
                + self._targeted_questions(symptom_signals, legal_activation)
            ),
            "next_steps": crisis.next_steps,
            "provider_focus": self._combined_provider_focus(crisis.provider_focus, emotion_profile),
            "symptom_signals": symptom_signals,
            "emotion_profile": emotion_profile,
            "telehealth": telehealth,
            "provider_matches": providers,
            "legal_activation": legal_activation,
            "case_file": case_file,
            "zenisys": self._zenisys_plan(crisis.sound_mode, payload, emotion_profile),
        }

    def _profile(self, payload: Dict[str, Any]) -> Dict[str, str]:
        return {
            "name": self._clean(payload.get("name")),
            "birthdate": self._clean(payload.get("birthdate")),
            "location": self._clean(payload.get("location")),
            "culture": self._clean(payload.get("culture")),
            "language": self._clean(payload.get("language") or "English"),
            "known_diagnoses": self._clean(payload.get("known_diagnoses")),
            "support_preference": self._clean(payload.get("support_preference")),
            "sound_preference": self._clean(payload.get("sound_preference")),
        }

    def _symptom_signals(self, message: str, profile: Dict[str, str], emotion_profile: Dict[str, Any]) -> Dict[str, Any]:
        text = f"{message} {profile.get('known_diagnoses', '')}".lower()
        domains = []
        rules = [
            ("anxiety_or_panic", ["anxious", "panic", "worry", "fear", "racing heart", "can't breathe"]),
            ("depressive_or_grief_signals", ["sad", "depressed", "hopeless", "empty", "worthless", "hate life", "no reason"]),
            ("trauma_or_stress_response", ["trauma", "flashback", "nightmare", "abuse", "unsafe", "triggered"]),
            ("psychosis_reality_testing_concern", ["voices", "hearing things", "seeing things", "paranoid", "being watched"]),
            ("mania_or_sleep_disruption", ["manic", "no sleep", "too much energy", "racing thoughts", "impulsive"]),
            ("neurodevelopmental_support", ["autism", "adhd", "sensory", "overstimulated", "social cues"]),
            ("substance_or_medication_concern", ["medication", "pills", "withdrawal", "substance", "alcohol", "drug"]),
            ("access_or_rights_barrier", ["denied", "access", "insurance", "pharmacy", "school", "accommodation"]),
        ]
        for domain, terms in rules:
            hits = [term for term in terms if term in text]
            if hits:
                domains.append({"domain": domain, "matched_terms": hits})
        primary_emotion = emotion_profile.get("primary_emotion", "")
        if primary_emotion and primary_emotion not in {"needs_more_context", "calm_or_hopeful"}:
            domains.append({
                "domain": "emotion_related_support_need",
                "matched_terms": [primary_emotion],
                "distress_score": emotion_profile.get("distress_score"),
            })
        if not domains:
            domains.append({"domain": "needs_more_context", "matched_terms": []})

        return {
            "notice": "These are symptom-domain possibilities for professional review, not a diagnosis.",
            "framework_language": "DSM-5/ICD-informed symptom domains without clinical diagnosis.",
            "domains": domains,
        }

    def _telehealth_plan(
        self,
        crisis,
        symptom_signals: Dict[str, Any],
        payload: Dict[str, Any],
        emotion_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        requested = bool(payload.get("telehealth_requested"))
        safety_flags = set(emotion_profile.get("safety_flags", []))
        urgent = (
            crisis.risk in {"critical", "high"}
            or requested
            or int(emotion_profile.get("distress_score", 0)) >= 8
            or "possible_self_harm_language" in safety_flags
            or "possible_means_or_environment_risk" in safety_flags
        )
        return {
            "available": True,
            "availability": "24/7 telehealth practitioner routing target",
            "urgency": "immediate" if urgent else "standard",
            "video_room": "/telehealth/urgent" if urgent else "/telehealth/intake",
            "handoff": "A nurse practitioner, therapist, psychiatrist, or crisis-trained practitioner should receive the encrypted case summary after user consent.",
            "status": "prototype_waiting_room_ready",
            "emotion_reason": emotion_profile.get("primary_emotion", ""),
        }

    def _provider_matches(self, crisis, symptom_signals: Dict[str, Any], profile: Dict[str, str]) -> List[Dict[str, Any]]:
        matches = self.providers.query({"risk": crisis.risk, "symptom_signals": symptom_signals, "profile": profile})
        enriched = []
        for provider in matches:
            enriched.append({
                "name": provider.get("name"),
                "specialty": provider.get("specialty"),
                "verified": provider.get("verified"),
                "rating": provider.get("rating"),
                "telehealth": provider.get("telehealth", True),
                "role": provider.get("role", "mental_health_professional"),
            })
        return enriched

    def _legal_activation(self, payload: Dict[str, Any], message: str, profile: Dict[str, str]) -> Dict[str, Any]:
        legal_issue = str(payload.get("legal_issue", "")).strip()
        text = f"{message} {legal_issue}".lower()
        activated = bool(legal_issue) or any(term in text for term in self.LEGAL_TERMS)
        issue = legal_issue or message
        special_tracks = []
        if any(term in text for term in ["medication", "pharmacy", "prescription"]):
            special_tracks.extend(["healthcare_access", "pharmacy_access", "medication_continuity"])
        if any(term in text for term in ["daughter", "son", "child", "school", "iep", "504"]):
            special_tracks.extend(["child_family_rights", "education_access"])
        if any(term in text for term in ["insurance", "benefits", "denied"]):
            special_tracks.append("insurance_or_benefits_review")

        return {
            "activated": activated,
            "engine": "CRASH Supreme Engine + VEIL Legislation Engine",
            "issue_fingerprint": self._fingerprint(issue) if issue else "",
            "research_start": "Cornell Law Legal Information Institute, then local/state/federal authority review",
            "jurisdiction_layers": [
                "local/neighborhood",
                "city",
                "county",
                "state",
                "federal",
                "agency/regulator",
                "court pathway",
                "legislative pathway",
            ],
            "special_tracks": sorted(set(special_tracks)),
            "outputs_to_prepare": [
                "issue profile",
                "jurisdiction map",
                "evidence and timeline questions",
                "agency/official letter draft",
                "legislative proposal draft",
                "petition/community escalation draft",
                "attorney-review litigation or injunction outline",
            ],
            "notice": "Legal outputs are advocacy drafts and research organization, not legal advice.",
        }

    def _case_file(
        self,
        message: str,
        profile: Dict[str, str],
        crisis: Dict[str, Any],
        clarion_analysis: Dict[str, Any],
        symptom_signals: Dict[str, Any],
        culture_signal: str,
        local_context: str,
        emotion_profile: Dict[str, Any],
        telehealth: Dict[str, Any],
        providers: List[Dict[str, Any]],
        legal_activation: Dict[str, Any],
        consent: bool,
    ) -> Dict[str, Any]:
        summary = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "case_reference": self._fingerprint(f"{message}|{profile.get('birthdate')}|{datetime.now(timezone.utc).date()}"),
            "share_authorized_by_user": consent,
            "clinical_notice": "This report organizes symptoms and needs for licensed professional review. It is not a diagnosis.",
            "profile_summary": self._safe_profile_summary(profile),
            "risk": crisis.get("risk"),
            "severity": crisis.get("severity"),
            "symptom_domains": symptom_signals.get("domains", []),
            "clarion_analysis": clarion_analysis,
            "emotion_profile": emotion_profile,
            "culture_signal": culture_signal,
            "local_context": local_context,
            "telehealth": telehealth,
            "provider_matches": providers,
            "legal_activation": legal_activation,
            "recommended_handoff": "Share with practitioner only after user consent.",
        }
        return summary

    def _targeted_questions(self, symptom_signals: Dict[str, Any], legal_activation: Dict[str, Any]) -> List[str]:
        questions = []
        domains = {item["domain"] for item in symptom_signals.get("domains", [])}
        if "psychosis_reality_testing_concern" in domains:
            questions.append("Are you hearing or seeing something that other people do not seem to hear or see?")
        if "mania_or_sleep_disruption" in domains:
            questions.append("How many hours did you sleep last night, and has your energy felt unusually high?")
        if "substance_or_medication_concern" in domains:
            questions.append("Are medications, withdrawal, side effects, or pharmacy access part of what is happening?")
        if legal_activation.get("activated"):
            questions.append("What city, county, state, agency, school, pharmacy, or provider is involved in the legal/access problem?")
            questions.append("What outcome do you need first: medication access, records review, accommodation, appeal, emergency care, or official accountability?")
        return questions[:4]

    def _zenisys_plan(self, sound_mode: str, payload: Dict[str, Any], emotion_profile: Dict[str, Any]) -> Dict[str, Any]:
        preference = self._clean(payload.get("sound_preference")) or "warm ambient"
        emotion_mode = emotion_profile.get("zenisys_mode_hint") or sound_mode
        priority = {"crisis": 4, "calming": 3, "grounding": 3, "encouragement": 2, "greeting": 1}
        mode = emotion_mode if priority.get(emotion_mode, 0) > priority.get(sound_mode, 0) else sound_mode
        return {
            "name": "Zenisys Sound System",
            "mode": mode,
            "preference": preference,
            "adaptive_goal": "Shift tone, tempo, and texture while the person responds so the session feels calmer by the end.",
            "browser_audio": True,
            "emotion_feedback": {
                "primary_emotion": emotion_profile.get("primary_emotion", ""),
                "distress_score": emotion_profile.get("distress_score"),
                "mode_hint": emotion_mode,
            },
        }

    def legal_activation(self, payload: Dict[str, Any], message: str = "", profile: Dict[str, str] | None = None) -> Dict[str, Any]:
        return self._legal_activation(payload, message or str(payload.get("legal_issue", "")), profile or self._profile(payload))

    @staticmethod
    def _combined_provider_focus(crisis_focus: str, emotion_profile: Dict[str, Any]) -> str:
        hint = emotion_profile.get("provider_focus_hint", "")
        if hint and hint not in crisis_focus:
            return f"{crisis_focus} Emotion learning adds: {hint}"
        return crisis_focus

    @staticmethod
    def _dedupe_questions(questions: List[str]) -> List[str]:
        seen = set()
        result = []
        for question in questions:
            cleaned = str(question).strip()
            key = cleaned.lower()
            if cleaned and key not in seen:
                result.append(cleaned)
                seen.add(key)
        return result[:12]

    def _safe_profile_summary(self, profile: Dict[str, str]) -> Dict[str, str]:
        return {
            "name": profile.get("name", ""),
            "location": profile.get("location", ""),
            "culture": profile.get("culture", ""),
            "language": profile.get("language", ""),
            "support_preference": profile.get("support_preference", ""),
            "sound_preference": profile.get("sound_preference", ""),
        }

    @staticmethod
    def _clean(value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text[:500]

    @staticmethod
    def _fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def module_available(name: str) -> bool:
    return (Path(__file__).resolve().parent / name).exists()
