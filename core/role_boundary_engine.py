"""
Role-Boundary Engine for InnerLight.

This is the legal and clinical safety backbone. It classifies EVERY action
the system might take into a tier, and enforces — in code — what is allowed
at each tier. The boundaries are not suggestions or guidelines; they are
gates. The system literally cannot perform a higher-tier action without the
required human authorization on file.

This protects three parties:
  - The USER (they always understand who represents them)
  - The ATTORNEY/CLINICIAN (their license is never put at risk)
  - INNERLIGHT (it never commits unauthorized practice of law or medicine)

=========================================================================
THE FOUR LEGAL TIERS
=========================================================================
  TIER 0 — INFORMATION         Always allowed. Rights, deadlines, "the law
                               says X." This is publishing, not practice.

  TIER 1 — DOCUMENT ACCESS     Allowed. Help find the correct BLANK official
                               form. Explain fields in plain language. User
                               or attorney fills it.

  TIER 2 — DOCUMENT PREP       GATED. Filling legal content. Permitted ONLY
                               as scrivener (user dictates) OR under attorney
                               supervision (attorney agreement on file +
                               user release of information).

  TIER 3 — REPRESENTATION      NEVER. Advising strategy, choosing what to
                               file, appearing/signing as agent. The bright
                               line. Always refused, always redirected to a
                               licensed attorney.

=========================================================================
THE FOUR CLINICAL TIERS (parallel structure)
=========================================================================
  TIER 0 — PSYCHOEDUCATION     Always allowed. General mental-health info.
  TIER 1 — SCREENING SUPPORT   Allowed. Validated questionnaires (PHQ-9 etc.)
                               presented as self-assessment, not diagnosis.
  TIER 2 — CLINICAL REVIEW     GATED. Any interpretation/treatment guidance
                               requires a licensed clinician in the loop.
  TIER 3 — DIAGNOSIS/TREATMENT NEVER by AI alone. Only a licensed clinician
                               diagnoses or prescribes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# TIERS
# ---------------------------------------------------------------------------

class LegalTier(IntEnum):
    INFORMATION = 0
    DOCUMENT_ACCESS = 1
    DOCUMENT_PREP = 2
    REPRESENTATION = 3


class ClinicalTier(IntEnum):
    PSYCHOEDUCATION = 0
    SCREENING_SUPPORT = 1
    CLINICAL_REVIEW = 2
    DIAGNOSIS_TREATMENT = 3


# What InnerLight (the AI) may do autonomously, with no human authorization:
MAX_AUTONOMOUS_LEGAL = LegalTier.DOCUMENT_ACCESS      # Tier 0-1 only
MAX_AUTONOMOUS_CLINICAL = ClinicalTier.SCREENING_SUPPORT  # Tier 0-1 only


# ---------------------------------------------------------------------------
# AUTHORIZATION RECORDS (what must be on file to unlock gated tiers)
# ---------------------------------------------------------------------------

@dataclass
class UserConsent:
    """A user's explicit, informed consent and release of information."""
    user_reference: str
    understood_not_representation: bool = False   # they understand we are NOT their lawyer
    release_of_information: bool = False           # they authorize sharing their info
    consent_to_document_prep: bool = False         # they authorize filling forms
    scope: str = ""                                # what exactly they consented to
    timestamp: str = ""

    def valid_for_prep(self) -> bool:
        return (
            self.understood_not_representation
            and self.release_of_information
            and self.consent_to_document_prep
        )


@dataclass
class AttorneyAgreement:
    """A participating attorney's agreement to supervise document prep."""
    attorney_reference: str
    bar_number: str = ""
    bar_state: str = ""
    verified: bool = False               # human-verified the bar license is active
    agrees_to_supervise: bool = False    # they agree to direct & review prep work
    scope: str = ""                      # categories they cover
    timestamp: str = ""

    def valid(self) -> bool:
        return self.verified and self.agrees_to_supervise


@dataclass
class ClinicianAgreement:
    """A licensed clinician's agreement to review/monitor."""
    clinician_reference: str
    license_number: str = ""
    license_state: str = ""
    license_type: str = ""               # psychiatrist, psychologist, LCSW, etc.
    verified: bool = False               # human-verified the license is active
    agrees_to_review: bool = False
    timestamp: str = ""

    def valid(self) -> bool:
        return self.verified and self.agrees_to_review


# ---------------------------------------------------------------------------
# THE GATE: decides whether a requested action is permitted
# ---------------------------------------------------------------------------

@dataclass
class ActionRequest:
    """A request to perform some action, which must be classified and gated."""
    domain: str              # "legal" or "clinical"
    description: str
    requested_tier: int


@dataclass
class GateDecision:
    allowed: bool
    tier: int
    domain: str
    reason: str
    required_authorizations: List[str] = field(default_factory=list)
    user_disclosure: str = ""   # what the user must be told
    redirect: str = ""          # where to send them if blocked


class RoleBoundaryEngine:
    """
    Classifies actions and enforces tier boundaries. Nothing above the
    autonomous ceiling happens without the required human authorizations.
    """

    # ---- Classification keyword maps ----
    LEGAL_TIER_SIGNALS = {
        LegalTier.REPRESENTATION: [
            "you should sue", "i'll file", "i will file", "file this for you",
            "represent you", "on your behalf", "i'll appear", "your lawyer",
            "as your attorney", "draft and submit", "file in court",
            "i recommend you plead", "you should settle", "sign here as",
            "i'll submit", "we'll file", "let me file", "file it for you",
        ],
        LegalTier.DOCUMENT_PREP: [
            "fill out", "fill in", "complete the", "prepare the",
            "write the complaint", "fill the", "draft the", "filling out",
            "completing the", "i'll write", "let me write", "let me complete",
            "let me prepare", "let me fill", "i'll prepare", "i'll fill",
            "i'll complete", "i'll draft",
        ],
        LegalTier.DOCUMENT_ACCESS: [
            "which form", "what form do i need", "find the form", "blank form",
            "where do i get the", "official form", "court form", "the petition",
        ],
    }

    CLINICAL_TIER_SIGNALS = {
        ClinicalTier.DIAGNOSIS_TREATMENT: [
            "you have depression", "you have ptsd", "you are bipolar",
            "you have major depress", "you have bipolar", "you have anxiety disorder",
            "you have a disorder", "you have an anxiety", "you're depressed clinically",
            "diagnose", "diagnosis", "you should take", "you need to take",
            "prescribe", "increase your dose", "lower your dose", "adjust your medication",
            "stop taking your", "your diagnosis is", "should take medication",
            "you have a mental illness", "you meet criteria for", "you clearly have",
            "sounds like you have", "you probably have",
        ],
        ClinicalTier.CLINICAL_REVIEW: [
            "your symptoms mean", "this indicates", "treatment plan",
            "you need therapy for", "clinical interpretation", "your symptoms suggest",
            "this is a sign of", "symptoms point to",
        ],
        ClinicalTier.SCREENING_SUPPORT: [
            "phq-9", "gad-7", "screening", "questionnaire", "self-assessment",
            "how often have you", "rate your",
        ],
    }

    def classify_legal(self, text: str) -> LegalTier:
        lower = text.lower()
        for tier in (LegalTier.REPRESENTATION, LegalTier.DOCUMENT_PREP, LegalTier.DOCUMENT_ACCESS):
            for signal in self.LEGAL_TIER_SIGNALS.get(tier, []):
                if signal in lower:
                    return tier
        return LegalTier.INFORMATION

    def classify_clinical(self, text: str) -> ClinicalTier:
        lower = text.lower()
        for tier in (ClinicalTier.DIAGNOSIS_TREATMENT, ClinicalTier.CLINICAL_REVIEW, ClinicalTier.SCREENING_SUPPORT):
            for signal in self.CLINICAL_TIER_SIGNALS.get(tier, []):
                if signal in lower:
                    return tier
        return ClinicalTier.PSYCHOEDUCATION

    # ---- The gate ----
    def evaluate_legal(
        self,
        proposed_text: str,
        user_consent: Optional[UserConsent] = None,
        attorney_agreement: Optional[AttorneyAgreement] = None,
    ) -> GateDecision:
        tier = self.classify_legal(proposed_text)

        # TIER 3 — never
        if tier == LegalTier.REPRESENTATION:
            return GateDecision(
                allowed=False, tier=int(tier), domain="legal",
                reason="This would constitute legal representation or advice, which only a licensed attorney may provide.",
                user_disclosure="I'm not a lawyer and can't advise you on what to do or represent you. A licensed attorney can. Let me help you connect with one.",
                redirect="attorney_match",
            )

        # TIER 2 — gated on consent + attorney supervision
        if tier == LegalTier.DOCUMENT_PREP:
            missing = []
            if not (user_consent and user_consent.valid_for_prep()):
                missing.append("user_informed_consent_and_release")
            if not (attorney_agreement and attorney_agreement.valid()):
                missing.append("supervising_attorney_agreement")
            if missing:
                return GateDecision(
                    allowed=False, tier=int(tier), domain="legal",
                    reason="Filling legal documents is only permitted with the user's informed consent AND a supervising attorney's agreement on file.",
                    required_authorizations=missing,
                    user_disclosure="Before I help organize any documents, I'd need your permission and a participating attorney directing the work. I'm not a lawyer — the attorney would be your representative, not me.",
                    redirect="consent_and_attorney_flow",
                )
            return GateDecision(
                allowed=True, tier=int(tier), domain="legal",
                reason="Document preparation permitted: user consent and supervising attorney both on file.",
                user_disclosure="I'll help organize this information as directed by the participating attorney. They are your legal representative — I am only assisting with organization.",
            )

        # TIER 0-1 — always allowed (information & blank form access)
        return GateDecision(
            allowed=True, tier=int(tier), domain="legal",
            reason="Legal information and access to official blank forms is permitted (this is information, not legal practice).",
            user_disclosure="This is legal information to help you talk with an attorney — it is not legal advice.",
        )

    def evaluate_clinical(
        self,
        proposed_text: str,
        clinician_agreement: Optional[ClinicianAgreement] = None,
    ) -> GateDecision:
        tier = self.classify_clinical(proposed_text)

        # TIER 3 — never by AI
        if tier == ClinicalTier.DIAGNOSIS_TREATMENT:
            return GateDecision(
                allowed=False, tier=int(tier), domain="clinical",
                reason="Diagnosis and treatment decisions can only be made by a licensed clinician.",
                user_disclosure="I can't diagnose you or advise on medication — only a licensed clinician can. I can help connect you with one.",
                redirect="clinician_match",
            )

        # TIER 2 — gated on clinician in the loop
        if tier == ClinicalTier.CLINICAL_REVIEW:
            if not (clinician_agreement and clinician_agreement.valid()):
                return GateDecision(
                    allowed=False, tier=int(tier), domain="clinical",
                    reason="Clinical interpretation requires a licensed clinician reviewing.",
                    required_authorizations=["reviewing_clinician_agreement"],
                    user_disclosure="What you're describing deserves a real clinician's eyes. I can share this with a licensed professional who's reviewing, with your permission.",
                    redirect="clinician_review_flow",
                )
            return GateDecision(
                allowed=True, tier=int(tier), domain="clinical",
                reason="Clinical review permitted: licensed clinician is in the loop.",
                user_disclosure="A licensed clinician is reviewing this with me.",
            )

        # TIER 0-1 — always allowed
        return GateDecision(
            allowed=True, tier=int(tier), domain="clinical",
            reason="General mental-health information and self-assessment screening is permitted.",
            user_disclosure="This is general information and self-reflection support, not a diagnosis.",
        )


# Singleton
_engine = RoleBoundaryEngine()

def get_boundary_engine() -> RoleBoundaryEngine:
    return _engine


if __name__ == "__main__":
    engine = RoleBoundaryEngine()

    print("=" * 70)
    print("LEGAL BOUNDARY TESTS")
    print("=" * 70)
    legal_tests = [
        "Here's what the law says about eviction notice periods",
        "Which form do I need to request a fee waiver?",
        "Let me fill out the eviction defense petition for you",
        "You should sue your landlord and I'll file it for you",
    ]
    for t in legal_tests:
        d = engine.evaluate_legal(t)
        print(f"\nACTION: {t}")
        print(f"  Tier {d.tier} | {'ALLOWED' if d.allowed else 'BLOCKED'}")
        print(f"  Reason: {d.reason}")
        if not d.allowed and d.required_authorizations:
            print(f"  Needs: {', '.join(d.required_authorizations)}")
        print(f"  User hears: \"{d.user_disclosure}\"")

    # Now show document prep UNLOCKING with proper authorizations
    print("\n" + "=" * 70)
    print("DOCUMENT PREP — WITH AUTHORIZATIONS ON FILE")
    print("=" * 70)
    consent = UserConsent(
        user_reference="u1", understood_not_representation=True,
        release_of_information=True, consent_to_document_prep=True, scope="housing",
    )
    attorney = AttorneyAgreement(
        attorney_reference="a1", bar_number="12345", bar_state="CA",
        verified=True, agrees_to_supervise=True, scope="housing",
    )
    d = engine.evaluate_legal("fill out the form for the eviction defense", consent, attorney)
    print(f"\nWith consent + attorney: {'ALLOWED' if d.allowed else 'BLOCKED'}")
    print(f"  {d.reason}")
    print(f"  User hears: \"{d.user_disclosure}\"")

    print("\n" + "=" * 70)
    print("CLINICAL BOUNDARY TESTS")
    print("=" * 70)
    clinical_tests = [
        "Here's some general information about how anxiety works",
        "This is a PHQ-9 self-assessment you can fill out",
        "Your symptoms mean you need this treatment plan",
        "You have major depressive disorder and should take medication",
    ]
    for t in clinical_tests:
        d = engine.evaluate_clinical(t)
        print(f"\nACTION: {t}")
        print(f"  Tier {d.tier} | {'ALLOWED' if d.allowed else 'BLOCKED'}")
        print(f"  User hears: \"{d.user_disclosure}\"")
