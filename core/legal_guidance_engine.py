"""
Legal Guidance Engine for InnerLight.

Detects legal issues in the conversation and provides:
- Your rights (what the law says, in plain language)
- Specific questions to ask an attorney
- Where to find free/low-cost legal help
- Steps you can take right now

CRITICAL BOUNDARIES:
- Never says "you should sue" or "file this"
- Never represents itself as legal counsel
- Always frames output as "information to discuss with an attorney"
- Always includes the disclaimer
- Provides maximum useful information without crossing into practice of law

The goal: "If you want answers, go to InnerLight."
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# LEGAL ISSUE DETECTION
# ---------------------------------------------------------------------------

LEGAL_PATTERNS: List[Tuple[str, str, str]] = [
    # (regex, issue_code, plain_label)
    # Housing
    (r"\b(evict|kicked out|lost .{1,15}(?:home|house|apartment)|landlord|lease|rent increase|no heat|no water|mold|habitability|section 8|housing authority)\b", "housing", "housing rights"),
    (r"\b(homeless|shelter|living in .{1,10}car|on the street|couch surfing)\b", "homelessness", "emergency housing"),
    # Employment
    (r"\b(fired|terminated|laid off|wrongful.{0,10}termination|discrimination at work|hostile work|sexual harassment at work|unpaid wages|overtime|retaliation|whistleblow|fmla|workers comp|unemployment benefits|denied .{1,10}(?:raise|promotion))\b", "employment", "employment rights"),
    (r"\b(fired .{0,20}(?:pregnant|disability|race|religion|age|gender)|discriminat)\b", "employment_discrimination", "employment discrimination"),
    # Family / custody
    (r"\b(custody|visitation|child support|alimony|divorce|restraining order|protective order|cps|child protective|foster care|adoption|parental rights|guardianship)\b", "family", "family law"),
    (r"\b(took .{1,10}(?:kid|child|children|baby)|won't let me see|denied .{1,15}(?:visit|custody))\b", "custody", "custody rights"),
    # Domestic violence
    (r"\b(hit me|beat me|abused|domestic violence|dv|restraining order|order of protection|stalking|threatening)\b", "domestic_violence", "domestic violence protection"),
    # Criminal
    (r"\b(arrested|charged|arraign|bail|bond|public defender|plea|probation|parole|criminal record|expunge|seal .{1,10}record|felony|misdemeanor)\b", "criminal", "criminal defense rights"),
    # Immigration
    (r"\b(deport|deportation|immigration|ice|visa|asylum|daca|undocumented|green card|citizenship|detained by immigration|immigration court|immigration judge|ICE agent)\b", "immigration", "immigration rights"),
    # Education
    (r"\b(expelled|suspended|iep|504 plan|special education|school discipline|title ix|bullying at school|denied .{1,15}(?:enrollment|education))\b", "education", "education rights"),
    # Healthcare
    (r"\b(denied .{1,15}(?:treatment|coverage|insurance|medication)|medical malpractice|hipaa|patient rights|involuntary commit|5150|Baker Act|forced medication)\b", "healthcare", "patient rights"),
    # Disability
    (r"\b(ADA|disability .{1,10}(?:accommodation|discrimination|rights)|denied .{1,10}accommodation|ssi|ssdi|disability benefits)\b", "disability", "disability rights"),
    # Consumer / debt
    (r"\b(debt collector|debt collectors|collection agency|sued for debt|garnish|repossess|bankruptcy|foreclosure|predatory lending|scam)\b", "consumer", "consumer protection"),
    # Civil rights
    (r"\b(racial profiling|police brutality|excessive force|civil rights|discrimination|hate crime|bias|profiling)\b", "civil_rights", "civil rights"),
]


def detect_legal_issues(text: str) -> List[Dict[str, str]]:
    """Detect legal issues in user text. Returns list of {code, label, matched}."""
    lower = text.lower()
    found = []
    seen_codes = set()
    for pattern, code, label in LEGAL_PATTERNS:
        m = re.search(pattern, lower)
        if m and code not in seen_codes:
            found.append({"code": code, "label": label, "matched": m.group(0)})
            seen_codes.add(code)
    return found


# ---------------------------------------------------------------------------
# RIGHTS AND GUIDANCE DATABASE
# ---------------------------------------------------------------------------

LEGAL_GUIDANCE: Dict[str, Dict[str, Any]] = {
    "housing": {
        "rights": [
            "In most states, a landlord cannot evict you without proper written notice and a court order.",
            "You have the right to habitable housing — that means working heat, water, plumbing, and no dangerous conditions.",
            "Retaliatory eviction (evicting you for complaining about conditions) is illegal in most states.",
            "If you receive government housing assistance, there are additional protections against termination.",
        ],
        "ask_attorney": [
            "Was proper legal notice given before eviction proceedings?",
            "Does my situation qualify for tenant protections under state or local law?",
            "Am I entitled to relocation assistance or additional time?",
            "Can I file a complaint with the housing authority?",
        ],
        "free_help": [
            "Legal Aid Society — free legal help for tenants (search 'legal aid [your city]')",
            "HUD (Housing and Urban Development) — file a complaint at hud.gov",
            "Local tenant rights organizations",
            "211 hotline — dial 2-1-1 for local housing resources",
        ],
        "steps_now": [
            "Document everything: save all notices, texts, emails, and photos of conditions.",
            "Do not sign anything without reading it carefully or having someone review it.",
            "If you are being locked out or utilities are shut off, that may be an illegal eviction — call legal aid immediately.",
        ],
    },
    "homelessness": {
        "rights": [
            "You have the right to emergency shelter in many cities and states.",
            "Children experiencing homelessness have the right to continue attending school (McKinney-Vento Act).",
            "You cannot be denied government services because you lack a permanent address.",
        ],
        "ask_attorney": [
            "What emergency housing options exist in my area?",
            "Am I eligible for rapid rehousing or transitional housing programs?",
            "What benefits am I entitled to apply for without a permanent address?",
        ],
        "free_help": [
            "211 hotline — dial 2-1-1 for immediate shelter and services",
            "National Alliance to End Homelessness — endhomelessness.org",
            "Local shelters and emergency housing programs",
            "Salvation Army and Catholic Charities — emergency assistance",
        ],
        "steps_now": [
            "Call 211 for immediate help finding shelter and services in your area.",
            "If you have children, contact the school district's homeless liaison.",
            "Keep your ID and important documents safe and accessible.",
        ],
    },
    "employment": {
        "rights": [
            "You cannot be fired for your race, color, religion, sex, national origin, age (40+), disability, or genetic information (Title VII, ADA, ADEA).",
            "You have the right to file a complaint with the Equal Employment Opportunity Commission (EEOC) within 180 days.",
            "Employers must pay you for all hours worked, including overtime if you are non-exempt.",
            "Retaliation for reporting harassment, discrimination, or safety violations is illegal.",
        ],
        "ask_attorney": [
            "Was my termination lawful under state and federal employment law?",
            "Do I have grounds for a wrongful termination or discrimination claim?",
            "What is the deadline to file a complaint with the EEOC or state agency?",
            "Am I entitled to severance, unpaid wages, or unemployment benefits?",
        ],
        "free_help": [
            "EEOC — eeoc.gov — free complaint filing, no attorney needed",
            "State labor board or department of labor",
            "Legal aid employment law clinics",
            "Worker rights hotlines (varies by state)",
        ],
        "steps_now": [
            "Write down everything that happened: dates, what was said, who was present.",
            "Save any emails, texts, performance reviews, or termination letters.",
            "File for unemployment benefits immediately — do not wait.",
            "Do not sign a severance agreement without having it reviewed.",
        ],
    },
    "employment_discrimination": {
        "rights": [
            "Firing or disciplining someone because of pregnancy, disability, race, gender, religion, or age is illegal under federal and state law.",
            "The EEOC investigates these claims at no cost to you.",
            "You are protected from retaliation for reporting discrimination.",
        ],
        "ask_attorney": [
            "Do I have a viable discrimination claim based on the facts?",
            "Should I file with the EEOC, state agency, or both?",
            "What evidence do I need to support my case?",
            "What are the potential remedies (reinstatement, back pay, damages)?",
        ],
        "free_help": [
            "EEOC — eeoc.gov — free complaint filing",
            "ACLU — may take discrimination cases",
            "Local civil rights organizations",
            "Law school employment law clinics",
        ],
        "steps_now": [
            "Document the timeline: when did the discrimination start, what was said, who witnessed it.",
            "Request your personnel file and any written performance reviews.",
            "File an EEOC charge before the 180-day deadline passes.",
        ],
    },
    "family": {
        "rights": [
            "Both parents generally have the right to seek custody and visitation unless there is a safety concern.",
            "Child support is calculated based on income and state guidelines — it is modifiable if circumstances change.",
            "You have the right to request a modification of custody or support orders when situations change significantly.",
        ],
        "ask_attorney": [
            "What custody arrangement would a court likely consider in my situation?",
            "How do I file for a modification of an existing custody or support order?",
            "What are my rights if the other parent is not following the court order?",
            "Am I eligible for a fee waiver to file family court documents?",
        ],
        "free_help": [
            "Family court self-help center (most courthouses have one)",
            "Legal aid family law division",
            "Local bar association lawyer referral service (often free first consultation)",
            "Women's law center — womenslaw.org",
        ],
        "steps_now": [
            "Keep a written log of all interactions with the other parent.",
            "Save all communication (texts, emails, voicemails).",
            "Do not violate any existing court orders, even if the other parent is.",
        ],
    },
    "custody": {
        "rights": [
            "A parent's rights cannot be terminated without due process — you have the right to notice and a hearing.",
            "If CPS is involved, you have the right to an attorney (and one will be appointed if you cannot afford one).",
            "Courts decide custody based on the best interest of the child, not punishment of the parent.",
        ],
        "ask_attorney": [
            "What are my rights in the current custody proceeding?",
            "How do I challenge a CPS finding or custody decision?",
            "What evidence would help my case?",
            "Can I request supervised visitation as an alternative?",
        ],
        "free_help": [
            "Court-appointed attorney (if CPS is involved, you have a right to one)",
            "Legal aid family law hotline",
            "Parent advocacy organizations",
        ],
        "steps_now": [
            "Attend every court date and CPS meeting — your presence matters.",
            "Complete any services the court orders (parenting classes, counseling, etc.).",
            "Document your involvement in your child's life: school events, doctor visits, daily care.",
        ],
    },
    "domestic_violence": {
        "rights": [
            "You have the right to a protective order (restraining order) against your abuser.",
            "Many courts have expedited processes for emergency protective orders.",
            "The Violence Against Women Act provides federal protections including housing and employment rights.",
            "You cannot be evicted for calling 911 about domestic violence in most states.",
        ],
        "ask_attorney": [
            "How do I obtain an emergency protective order?",
            "What happens after I file — will the abuser be notified?",
            "What if the abuser violates the order?",
            "Am I eligible for victim compensation or relocation assistance?",
        ],
        "free_help": [
            "National Domestic Violence Hotline: 1-800-799-7233 (thehotline.org)",
            "Local DV shelters — call 211 for your nearest one",
            "Legal aid DV advocacy programs (many file protective orders at no cost)",
            "RAINN: 1-800-656-4673 for sexual assault",
        ],
        "steps_now": [
            "If you are in immediate danger, call 911.",
            "Create a safety plan: pack essentials, keep important documents accessible, identify a safe place to go.",
            "Save evidence: photos of injuries, threatening messages, dates and descriptions of incidents.",
            "Tell someone you trust what is happening.",
        ],
    },
    "criminal": {
        "rights": [
            "You have the right to remain silent — you do not have to answer police questions without an attorney.",
            "You have the right to an attorney. If you cannot afford one, a public defender will be appointed.",
            "You have the right to know the charges against you.",
            "You have the right to a speedy trial and to confront witnesses.",
        ],
        "ask_attorney": [
            "What are the charges and potential penalties?",
            "Should I accept a plea offer or go to trial?",
            "Are there any defenses or mitigating factors in my case?",
            "Am I eligible for diversion, deferred adjudication, or record expungement?",
        ],
        "free_help": [
            "Public defender's office (you have a constitutional right to one)",
            "Legal aid criminal defense clinics",
            "Innocence Project (wrongful conviction cases)",
            "Reentry programs for those with criminal records",
        ],
        "steps_now": [
            "Do not discuss your case with anyone except your attorney.",
            "Write down everything you remember about the incident while it is fresh.",
            "Show up to every court date — failure to appear creates additional charges.",
            "If you are eligible, apply for a public defender immediately.",
        ],
    },
    "immigration": {
        "rights": [
            "You have constitutional rights regardless of immigration status, including the right to remain silent and the right to an attorney.",
            "ICE cannot enter your home without a judicial warrant (not an administrative warrant).",
            "You have the right to speak to your consulate if detained.",
            "Children have the right to education regardless of immigration status.",
        ],
        "ask_attorney": [
            "What forms of relief (asylum, visa, DACA, cancellation of removal) might apply to my situation?",
            "What are my rights if ICE contacts me or comes to my home?",
            "How do I find a qualified immigration attorney (not a notario)?",
            "What deadlines apply to my case?",
        ],
        "free_help": [
            "CLINIC (Catholic Legal Immigration Network) — cliniclegal.org",
            "Local immigration legal services (search 'free immigration attorney [your city]')",
            "ACLU immigrants' rights project",
            "National Immigration Law Center — nilc.org",
        ],
        "steps_now": [
            "Know your rights: you can say 'I wish to remain silent' and 'I want to speak to an attorney.'",
            "Carry a know-your-rights card.",
            "Do not sign any documents you do not understand.",
            "Keep copies of all immigration documents in a safe place and give copies to someone you trust.",
        ],
    },
    "education": {
        "rights": [
            "Students have the right to due process before suspension or expulsion.",
            "Students with disabilities have the right to a free appropriate public education (IDEA/Section 504).",
            "Title IX prohibits sex-based discrimination in education, including sexual harassment.",
            "Homeless students have the right to remain in their school of origin (McKinney-Vento Act).",
        ],
        "ask_attorney": [
            "Was proper procedure followed in the disciplinary action?",
            "Is my child entitled to an IEP or 504 plan?",
            "How do I file a complaint with the school district or Office for Civil Rights?",
        ],
        "free_help": [
            "Office for Civil Rights (OCR) — ed.gov/ocr — free complaint filing",
            "Parent training and information centers (PTI)",
            "Disability rights organizations",
            "School district ombudsman or parent advocate",
        ],
        "steps_now": [
            "Request a copy of all school records and disciplinary files.",
            "Put all requests to the school in writing (email counts).",
            "Attend all meetings and bring a supportive person with you.",
        ],
    },
    "healthcare": {
        "rights": [
            "You have the right to informed consent — to understand and agree to treatment before it happens.",
            "EMTALA requires emergency rooms to treat you regardless of ability to pay.",
            "You have the right to access your medical records.",
            "Involuntary commitment requires specific legal criteria and judicial review.",
        ],
        "ask_attorney": [
            "Was I denied treatment or coverage unlawfully?",
            "How do I appeal an insurance denial?",
            "Was the involuntary hold lawful under state mental health law?",
            "Do I have a medical malpractice claim?",
        ],
        "free_help": [
            "Patient advocate at your hospital or clinic",
            "State insurance commissioner — file a complaint about denials",
            "Health rights hotlines (varies by state)",
            "Legal aid health law programs",
        ],
        "steps_now": [
            "Request copies of all medical records and billing statements.",
            "File an appeal with your insurance company for any denied coverage.",
            "Document what happened: dates, providers, what was said.",
        ],
    },
    "disability": {
        "rights": [
            "The ADA requires reasonable accommodations in employment, public services, and public accommodations.",
            "Employers cannot discriminate against qualified individuals with disabilities.",
            "You have the right to apply for SSI/SSDI benefits if your disability prevents substantial work.",
        ],
        "ask_attorney": [
            "Am I entitled to a reasonable accommodation at work or school?",
            "How do I file an ADA complaint?",
            "What is the process for appealing a denied disability benefits claim?",
        ],
        "free_help": [
            "Disability Rights organization in your state (every state has one)",
            "ADA National Network — adata.org",
            "Social Security Administration — ssa.gov",
            "Legal aid disability rights programs",
        ],
        "steps_now": [
            "Put your accommodation request in writing.",
            "Get medical documentation supporting your need.",
            "Keep records of all interactions about your accommodation.",
        ],
    },
    "consumer": {
        "rights": [
            "Debt collectors cannot harass, threaten, or contact you at unreasonable hours (Fair Debt Collection Practices Act).",
            "You have the right to request written verification of any debt.",
            "Wage garnishment has legal limits — a percentage of your income is protected.",
            "Bankruptcy can stop collections and give you a fresh start.",
        ],
        "ask_attorney": [
            "Is this debt valid, and is the statute of limitations expired?",
            "Should I consider bankruptcy, and which type?",
            "Are the debt collector's actions violating the FDCPA?",
            "How do I respond to a lawsuit for debt?",
        ],
        "free_help": [
            "Consumer Financial Protection Bureau (CFPB) — consumerfinance.gov",
            "Legal aid consumer law programs",
            "National Foundation for Credit Counseling — nfcc.org",
            "State attorney general's consumer protection office",
        ],
        "steps_now": [
            "Do not ignore court papers — respond within the deadline.",
            "Send a written debt validation request within 30 days of first contact.",
            "Keep records of all collector communications.",
        ],
    },
    "civil_rights": {
        "rights": [
            "You are protected from discrimination based on race, color, religion, sex, national origin, disability, and age.",
            "Excessive force by law enforcement violates your Fourth Amendment rights.",
            "You have the right to file a complaint with the Department of Justice Civil Rights Division.",
        ],
        "ask_attorney": [
            "Do I have a civil rights claim under federal or state law?",
            "What evidence do I need to document?",
            "What are the filing deadlines for my complaint?",
            "Am I eligible for damages?",
        ],
        "free_help": [
            "ACLU — aclu.org",
            "NAACP Legal Defense Fund",
            "Department of Justice Civil Rights Division — justice.gov/crt",
            "Local civil rights organizations and legal clinics",
        ],
        "steps_now": [
            "Document everything: dates, witnesses, video/photos if available.",
            "File a complaint with the appropriate agency (DOJ, EEOC, OCR).",
            "Get medical attention and documentation if there were physical injuries.",
        ],
    },
}


def generate_legal_guidance(issues: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """Generate legal guidance for detected issues. Returns structured guidance or None."""
    if not issues:
        return None

    primary = issues[0]
    code = primary["code"]
    guidance = LEGAL_GUIDANCE.get(code)
    if not guidance:
        return None

    return {
        "issue_detected": primary["label"],
        "issue_code": code,
        "your_rights": guidance["rights"],
        "questions_for_attorney": guidance["ask_attorney"],
        "free_legal_help": guidance["free_help"],
        "steps_you_can_take_now": guidance["steps_now"],
        "disclaimer": (
            "This is legal information, not legal advice. InnerLight is not an attorney and does not "
            "practice law. This information is provided so you can have an informed conversation with "
            "a qualified attorney. Laws vary by state and situation — an attorney can tell you how "
            "these rights apply to your specific case."
        ),
        "additional_issues": [i["label"] for i in issues[1:]],
    }


if __name__ == "__main__":
    tests = [
        "My landlord kicked me out without any notice",
        "I got fired because I'm pregnant",
        "My ex won't let me see my kids",
        "My dad hit me again last night",
        "I got arrested and I don't know what to do",
        "ICE came to my neighbor's house and I'm scared",
        "I'm living in my car with my kids",
        "The debt collectors won't stop calling me",
    ]
    for text in tests:
        issues = detect_legal_issues(text)
        if issues:
            g = generate_legal_guidance(issues)
            print(f"\n--- '{text}' ---")
            print(f"Issue: {g['issue_detected']}")
            print(f"Rights: {g['your_rights'][0]}")
            print(f"Ask attorney: {g['questions_for_attorney'][0]}")
            print(f"Free help: {g['free_legal_help'][0]}")
            print(f"Step now: {g['steps_you_can_take_now'][0]}")
        else:
            print(f"\n--- '{text}' --- No legal issue detected")