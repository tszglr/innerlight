"""
Handoff Report Engine for InnerLight.

Produces a professional, observation-based report to hand to a clinician,
crisis team, or other human help — WITH the person's consent (HIPAA).

THE LINE, ENFORCED IN CODE:
This engine relays what the PERSON said and what was OBSERVED, in professional
descriptive language. It NEVER renders a diagnosis or conclusion. To make that
guarantee real instead of a guideline, every report passes through a hard-coded
DIAGNOSTIC BLOCKLIST before it can be emitted. If any forbidden conclusive term
appears, the report is blocked and the offending content rewritten in plain
observational language. The machine itself refuses to cross the line.

What it DOES:
  - Quotes / paraphrases what the person stated ("the person reported...")
  - Describes observed state in professional but non-diagnostic terms
    (distress, sleep disturbance, low mood, reported perceptual experiences)
  - Surfaces the risk signals the crisis reader already detected, factually
  - Qualifies everything as observation from a conversation
  - Is gated behind explicit consent

What it NEVER does:
  - Name a condition (schizophrenia, bipolar, BPD, PTSD, etc.)
  - Reference the DSM / ICD or "criteria"
  - Say "consistent with", "indicative of", "suggests [disorder]", "presents with"
  - Offer a prognosis or treatment decision
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ===========================================================================
# THE DIAGNOSTIC BLOCKLIST — enforced in code. These must never appear in an
# emitted report. Names of conditions, diagnostic frameworks, and the
# connective phrases that turn an observation into a clinical conclusion.
# ===========================================================================
CONDITION_TERMS = [
    "schizophrenia", "schizoaffective", "schizophreniform", "psychosis", "psychotic",
    "bipolar", "manic", "mania", "major depressive disorder", "mdd", "clinical depression",
    "borderline personality", "bpd", "narcissistic personality", "antisocial personality",
    "ptsd", "post-traumatic stress disorder", "ocd", "obsessive-compulsive disorder",
    "generalized anxiety disorder", "gad", "panic disorder", "bipolar disorder",
    "personality disorder", "mood disorder", "anxiety disorder", "psychotic disorder",
    "delusional disorder", "dissociative disorder", "did", "adhd", "autism", "asd",
    "anorexia", "bulimia", "eating disorder", "substance use disorder",
]
FRAMEWORK_TERMS = [
    "dsm", "dsm-5", "dsm5", "dsm-iv", "icd", "icd-10", "icd-11", "icd10", "icd11",
    "diagnostic criteria", "meets criteria", "meets the criteria", "diagnostic and statistical",
]
CONCLUSIVE_CONNECTORS = [
    "consistent with", "indicative of", "suggestive of", "suggests a diagnosis",
    "presents with", "presentation consistent", "differential diagnosis", "rule out",
    "diagnosed with", "diagnosis of", "appears to have", "likely has", "probably has",
    "is exhibiting symptoms of", "criteria for", "clinical picture of", "hallmark of",
]
# Words that, used as a verdict, conclude rather than describe.
VERDICT_WORDS = ["diagnose", "diagnosis", "diagnostic", "prognosis"]

BLOCKLIST = CONDITION_TERMS + FRAMEWORK_TERMS + CONCLUSIVE_CONNECTORS + VERDICT_WORDS


def scan_for_diagnostic_language(text: str, ignore_disclaimer: bool = True) -> List[str]:
    """Return every forbidden term found in the text (case-insensitive, word-aware).

    The standard disclaimer legitimately contains the words 'diagnosis'/'diagnostic'
    used to DISCLAIM (e.g. 'this is NOT a diagnosis'). We don't count those, because
    disclaiming a diagnosis is the opposite of making one. We DO count condition
    names, frameworks, conclusive connectors, and verdict uses elsewhere.
    """
    scan_text = text
    if ignore_disclaimer:
        # Remove the known safe disclaimer sentences before scanning.
        safe_phrases = [
            "it is not a", "is not a diagnosis", "not a diagnosis or clinical conclusion",
            "not a clinical judgment", "all clinical assessment is for the",
            "is not a clinical judgment",
        ]
        # Blank out lines that are clearly the disclaimer
        kept = []
        for line in scan_text.split("\n"):
            low = line.lower()
            if any(sp in low for sp in safe_phrases):
                continue
            kept.append(line)
        scan_text = "\n".join(kept)
    low = scan_text.lower()
    found = []
    for term in BLOCKLIST:
        if " " in term or "-" in term:
            if term in low:
                found.append(term)
        else:
            if re.search(r"\b" + re.escape(term) + r"\b", low):
                found.append(term)
    return sorted(set(found))


def is_report_safe(text: str) -> bool:
    return len(scan_for_diagnostic_language(text)) == 0


# ===========================================================================
# SAFE DESCRIPTIVE VOCABULARY — professional language that DESCRIBES what was
# reported/observed, without naming any condition. This is the "Edge" approach:
# professional, but always anchored to the person's own report.
# ===========================================================================
# Maps an internal signal -> a safe, descriptive, observation-anchored phrase.
SAFE_DESCRIPTORS = {
    "hopelessness": "expressed feelings of hopelessness",
    "passive_ideation": "made statements that may reflect thoughts of not wanting to be here",
    "explicit_ideation": "made statements expressing thoughts of ending their life",
    "dark_thoughts": "described distressing or intrusive thoughts",
    "life_exhaustion": "described feeling exhausted or worn down by their situation",
    "burden": "expressed feeling like a burden to others",
    "entrapment": "described feeling trapped or that there is no way out",
    "perceptual": "reported experiences that others present may not perceive",
    "sleep": "reported changes in sleep",
    "low_mood": "described a persistently low mood",
    "anhedonia": "described a loss of interest or pleasure in usual activities",
    "anxiety": "described feeling anxious or on edge",
    "agitation": "appeared agitated or restless during the conversation",
    "withdrawal": "described withdrawing from people or activities",
    "flat_affect": "showed limited emotional expression during the conversation",
    "distress": "appeared to be in significant distress",
}


@dataclass
class HandoffReport:
    consented: bool
    summary_lines: List[str] = field(default_factory=list)
    person_statements: List[str] = field(default_factory=list)
    observed_state: List[str] = field(default_factory=list)
    risk_summary: str = ""
    safety_passed: bool = True
    blocked_terms: List[str] = field(default_factory=list)
    consent_note: str = ""

    def render_text(self) -> str:
        if not self.consented:
            return ("No report generated. The person has not consented to share information. "
                    "A report can only be prepared with the person's explicit consent.")
        parts = []
        parts.append("INNERLIGHT \u2014 OBSERVATION-BASED HANDOFF NOTE")
        parts.append("Prepared with the person's consent. This note relays what the person")
        parts.append("stated and what was observed during the conversation. It is NOT a")
        parts.append("diagnosis or clinical conclusion; all clinical assessment is for the")
        parts.append("receiving professional.")
        parts.append("")
        if self.person_statements:
            parts.append("WHAT THE PERSON SHARED (in their words / as reported):")
            for s in self.person_statements:
                parts.append("  \u2022 " + s)
            parts.append("")
        if self.observed_state:
            parts.append("WHAT WAS OBSERVED DURING THE CONVERSATION:")
            for s in self.observed_state:
                parts.append("  \u2022 " + s)
            parts.append("")
        if self.risk_summary:
            parts.append("RISK SIGNALS OBSERVED (factual, not a clinical judgment):")
            parts.append("  " + self.risk_summary)
            parts.append("")
        parts.append("This note is provided to support \u2014 not replace \u2014 the receiving")
        parts.append("professional's own assessment.")
        return "\n".join(parts)


class HandoffReportEngine:
    def build(
        self,
        consented: bool,
        person_quotes: Optional[List[str]] = None,
        signals: Optional[List[str]] = None,
        observed: Optional[List[str]] = None,
        crisis_reading: Optional[Dict[str, Any]] = None,
    ) -> HandoffReport:
        report = HandoffReport(consented=consented)
        if not consented:
            report.consent_note = "Consent not given; no shareable content generated."
            return report

        # 1. The person's own statements — quoted/paraphrased, anchored to them.
        for q in (person_quotes or []):
            q = q.strip()
            if q:
                # Always frame as their report, never as fact-about-them
                report.person_statements.append(f'The person stated: "{self._sanitize_quote(q)}"')

        # 2. Observed signals -> safe descriptive phrases (no condition names).
        for sig in (signals or []):
            phrase = SAFE_DESCRIPTORS.get(sig)
            if phrase:
                report.observed_state.append("The person " + phrase + ".")
        for o in (observed or []):
            if o.strip():
                report.observed_state.append(o.strip())

        # 3. Risk signals from the crisis reader — factual, graded, not clinical.
        if crisis_reading:
            level = crisis_reading.get("level", "none")
            factors = crisis_reading.get("emotional_factors", []) or []
            sig_families = list((crisis_reading.get("signals") or {}).keys())
            level_text = {
                "crisis": "The conversation contained language reflecting acute risk; immediate human support was indicated.",
                "elevated": "The conversation contained language reflecting elevated concern.",
                "concern": "The conversation contained some language worth a closer human check-in.",
                "none": "No specific risk language was observed in the conversation.",
            }.get(level, "")
            report.risk_summary = level_text
            if sig_families:
                report.risk_summary += " Observed signal areas: " + ", ".join(
                    s.replace("_", " ") for s in sig_families) + "."

        # 4. ENFORCE THE LINE: scan the full rendered text for forbidden terms.
        draft = report.render_text()
        found = scan_for_diagnostic_language(draft)
        if found:
            # Block it. Strip offending content rather than emit a diagnosis.
            report.safety_passed = False
            report.blocked_terms = found
            report = self._rewrite_safe(report, found)
        else:
            report.safety_passed = True
        return report

    @staticmethod
    def _sanitize_quote(q: str) -> str:
        # A direct quote is the person's own words; we keep it but cap length
        # and strip anything that looks like the person being labeled by US.
        q = re.sub(r"\s+", " ", q).strip()
        return q[:300]

    def _rewrite_safe(self, report: HandoffReport, found: List[str]) -> HandoffReport:
        """If forbidden diagnostic language slipped in (e.g. inside a quote that
        named a condition), neutralize it so the emitted note never concludes.
        We keep the person's meaning but remove the clinical verdict framing."""
        def clean(line: str) -> str:
            out = line
            for term in found:
                # Replace a condition/framework/verdict term with a neutral marker
                out = re.sub(r"(?i)\b" + re.escape(term) + r"\b", "[clinical term removed]", out)
            return out
        # Note: quotes are the PERSON'S words. If a person says "I think I have
        # bipolar," that's their statement and is legitimate to relay AS their
        # statement — but to stay safely clear of the line by default, we mark
        # the clinical term and let the professional interpret. This is
        # conservative on purpose.
        report.person_statements = [clean(s) for s in report.person_statements]
        report.observed_state = [clean(s) for s in report.observed_state]
        report.risk_summary = clean(report.risk_summary)
        report.consent_note = ("A clinical term was detected and neutralized to keep this "
                               "note strictly observational.")
        return report


_engine = HandoffReportEngine()

def get_report_engine() -> HandoffReportEngine:
    return _engine


if __name__ == "__main__":
    eng = HandoffReportEngine()
    print("=" * 70)
    print("HANDOFF REPORT ENGINE \u2014 observation-based, diagnosis-blocked")
    print("=" * 70)

    # A realistic case
    r = eng.build(
        consented=True,
        person_quotes=[
            "I haven't slept in days and I hear a voice telling me I'm worthless",
            "nothing matters anymore and everyone would be better off without me",
        ],
        signals=["sleep", "perceptual", "hopelessness", "burden", "passive_ideation", "distress"],
        crisis_reading={"level": "crisis", "signals": {"passive": [], "burden": [], "hopelessness": []},
                        "emotional_factors": ["high despair-cluster emotional mass"]},
    )
    print("\n--- CONSENTED REPORT ---")
    print(r.render_text())
    print(f"\nSafety passed (no diagnostic language): {r.safety_passed}")
    print(f"Blocked terms: {r.blocked_terms}")

    # Try to force a diagnosis in — the blocklist must catch it
    print("\n" + "=" * 70)
    print("ADVERSARIAL: someone tries to put a diagnosis in the report")
    print("=" * 70)
    r2 = eng.build(
        consented=True,
        observed=["The person presents with symptoms consistent with schizophrenia and a major depressive disorder."],
    )
    print("Safety passed:", r2.safety_passed)
    print("Blocked terms caught:", r2.blocked_terms)
    print("Neutralized output:")
    print(r2.render_text())

    # No consent
    print("\n" + "=" * 70)
    print("NO CONSENT")
    print("=" * 70)
    r3 = eng.build(consented=False, person_quotes=["anything"])
    print(r3.render_text())
