"""
AHP Juggernaut commercial readiness checks.

This module verifies whether the install has the dependencies, configuration,
attribution notices, training artifacts, and compliance acknowledgements needed
to hand the program to an operator or company.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List


ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
ATTRIBUTION_PATH = ROOT / "ATTRIBUTION_AND_LICENSE.md"
MODEL_ARTIFACT_DIR = ROOT / "model_artifacts"
VIABILITY_REPORT_JSON = ROOT / "viability_reports" / "latest_viability_report.json"

CORE_DEPENDENCIES = [
    "flask",
    "numpy",
    "sklearn",
    "joblib",
    "requests",
]

OPTIONAL_DEPENDENCIES = {
    "blockchain": ["web3", "cryptography"],
    "audio": ["pygame", "simpleaudio"],
    "voice_capture": ["pyaudio", "webrtcvad"],
    "visual_emotion": ["cv2", "mediapipe"],
    "dashboards": ["pandas", "matplotlib", "plotly"],
}

CONFIG_KEYS = {
    "AHP_OPERATOR_NAME": "Name of installing company/operator.",
    "AHP_CREDIT_TEXT": "Required creator credit displayed by the program.",
    "AHP_LICENSE_ACCEPTED": "Must be true before commercial operation.",
    "AHP_COMPLIANCE_ACKNOWLEDGED": "Must be true after responsible officer review.",
    "PORT": "Primary Flask/API port.",
    "FLASK_DEBUG": "Must be False in production.",
    "ENCRYPTION_KEY": "Local encryption key or secret reference.",
    "ETH_PROVIDER_URL": "Optional Ethereum/Web3 provider URL.",
    "ETH_PRIVATE_KEY": "Optional Ethereum private key; prefer vault/secret manager in production.",
    "OPENAI_API_KEY": "Optional LLM API key if LLM-backed features are enabled.",
    "SENDGRID_API_KEY": "Optional email delivery key.",
    "TWILIO_ACCOUNT_SID": "Optional SMS account SID.",
    "TWILIO_AUTH_TOKEN": "Optional SMS auth token.",
}

COMPLIANCE_ACKS = [
    "AHP_HIPAA_REVIEWED",
    "AHP_BAA_REVIEWED",
    "AHP_FDA_SAMD_REVIEWED",
    "AHP_FTC_HEALTH_BREACH_REVIEWED",
    "AHP_STATE_LICENSING_REVIEWED",
    "AHP_PRIVACY_POLICY_READY",
    "AHP_SECURITY_POLICY_READY",
    "AHP_INCIDENT_RESPONSE_READY",
]


def parse_env(path: Path = ENV_PATH) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:4] + "***" + value[-4:]


def dependency_status(names: Iterable[str]) -> Dict[str, bool]:
    return {name: importlib.util.find_spec(name) is not None for name in names}


def config_status(env: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    status: Dict[str, Dict[str, str]] = {}
    for key, description in CONFIG_KEYS.items():
        value = env.get(key, "")
        status[key] = {
            "present": bool(value),
            "value": mask_secret(value) if "KEY" in key or "TOKEN" in key or "SECRET" in key else value,
            "description": description,
        }
    return status


def compliance_status(env: Dict[str, str]) -> Dict[str, bool]:
    return {key: env.get(key, "").lower() == "true" for key in COMPLIANCE_ACKS}


def artifact_status() -> Dict[str, bool]:
    return {
        "threat_model.joblib": (MODEL_ARTIFACT_DIR / "threat_model.joblib").exists(),
        "threat_vectorizer.joblib": (MODEL_ARTIFACT_DIR / "threat_vectorizer.joblib").exists(),
        "threat_model_metadata.json": (MODEL_ARTIFACT_DIR / "threat_model_metadata.json").exists(),
        "latest_viability_report.json": VIABILITY_REPORT_JSON.exists(),
    }


def viability_status() -> Dict[str, object]:
    if not VIABILITY_REPORT_JSON.exists():
        return {"present": False, "usable_for_sale_claims": False, "blockers": ["Missing viability report."]}
    try:
        report = json.loads(VIABILITY_REPORT_JSON.read_text(encoding="utf-8"))
        viability = report.get("viability", {})
        return {
            "present": True,
            "usable_for_internal_demo": bool(viability.get("usable_for_internal_demo")),
            "usable_for_sale_claims": bool(viability.get("usable_for_sale_claims")),
            "blockers": viability.get("blockers", []),
            "warnings": viability.get("warnings", []),
            "accuracy": report.get("accuracy"),
            "macro_f1": report.get("macro_f1"),
            "record_count": report.get("record_count"),
            "evidence_sources": report.get("evidence_sources", {}),
        }
    except Exception as exc:
        return {"present": True, "usable_for_sale_claims": False, "blockers": [f"Invalid viability report: {exc}"]}


def attribution_status(env: Dict[str, str]) -> Dict[str, object]:
    credit = env.get("AHP_CREDIT_TEXT", "")
    expected = "Toshay S. Zeigler"
    return {
        "attribution_file_present": ATTRIBUTION_PATH.exists(),
        "credit_text_present": bool(credit),
        "creator_named": expected.lower() in credit.lower() if credit else False,
        "required_creator": expected,
    }


def readiness_report() -> Dict:
    env = parse_env()
    core = dependency_status(CORE_DEPENDENCIES)
    optional = {group: dependency_status(names) for group, names in OPTIONAL_DEPENDENCIES.items()}
    config = config_status(env)
    compliance = compliance_status(env)
    artifacts = artifact_status()
    viability = viability_status()
    attribution = attribution_status(env)

    blockers: List[str] = []
    if not all(core.values()):
        blockers.append("Missing one or more core Python dependencies.")
    if not ENV_PATH.exists():
        blockers.append("Missing .env configuration file.")
    if env.get("AHP_LICENSE_ACCEPTED", "").lower() != "true":
        blockers.append("Commercial license/attribution terms not accepted in .env.")
    if env.get("AHP_COMPLIANCE_ACKNOWLEDGED", "").lower() != "true":
        blockers.append("Compliance acknowledgement not completed in .env.")
    if not attribution["attribution_file_present"]:
        blockers.append("Missing attribution/license notice file.")
    if not attribution["creator_named"]:
        blockers.append("AHP_CREDIT_TEXT must credit Toshay S. Zeigler.")
    if not all(artifacts.values()):
        blockers.append("Threat prediction model artifacts are missing or incomplete.")
    if not viability.get("usable_for_sale_claims", False):
        blockers.append("Threat model viability is not proven for sale claims.")

    warnings: List[str] = []
    missing_acks = [key for key, ok in compliance.items() if not ok]
    if missing_acks:
        warnings.append("Compliance review flags not all true: " + ", ".join(missing_acks))
    if env.get("FLASK_DEBUG", "").lower() == "true":
        warnings.append("FLASK_DEBUG=true is not safe for production.")
    for group, values in optional.items():
        missing = [name for name, ok in values.items() if not ok]
        if missing:
            warnings.append(f"Optional {group} dependencies missing: {', '.join(missing)}")

    return {
        "root": str(ROOT),
        "ready_for_commercial_handoff": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "core_dependencies": core,
        "optional_dependencies": optional,
        "config": config,
        "compliance": compliance,
        "model_artifacts": artifacts,
        "viability": viability,
        "attribution": attribution,
        "notes": [
            "This readiness tool does not grant HIPAA, FDA, FTC, state licensing, or legal certification.",
            "A responsible company officer and qualified counsel/compliance experts must complete review before production health/legal use.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check AHP Juggernaut commercial readiness.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    args = parser.parse_args()
    report = readiness_report()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Ready for commercial handoff: {report['ready_for_commercial_handoff']}")
        if report["blockers"]:
            print("Blockers:")
            for item in report["blockers"]:
                print(f"  - {item}")
        if report["warnings"]:
            print("Warnings:")
            for item in report["warnings"]:
                print(f"  - {item}")
    return 0 if report["ready_for_commercial_handoff"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
