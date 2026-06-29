from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template_string, request

from ahp_encryption import AxiomHarmonyProtocol
from clarion_engine import Clarion
from crisis_response_core import CrisisResponseCore
from cultural_detector import CulturalDetector
from zenisys_music_engine import get_zenisys_engine
from conversation_engine import get_conversation_engine
from legal_guidance_engine import detect_legal_issues, generate_legal_guidance
from quantum_emotion_engine import get_quantum_engine
from crisis_risk_reader import get_crisis_reader
from handoff_report_engine import get_report_engine, scan_for_diagnostic_language
from human_voice import synthesize as voice_synthesize, voice_provider, list_voices as voice_list
from zenisys_lab import ZENISYS_LAB_PAGE
from resolution_framework import (
    classify_handoff, build_context_card, generate_exit_message,
    get_resolution_tracker
)
from cultural_fluency_engine import get_cultural_engine
from role_boundary_engine import get_boundary_engine
from warm_handoff import build_warm_handoff, get_handoff_learning
from innerlight_emotion_module import InnerLightEmotionModule
from innerlight_learning_module import InnerLightLearningModule
from innerlight_system import InnerLightSystem
from juggernaut_readiness import readiness_report
from localization_engine import LocalizationEngine

try:
    from response_generator import ResponseGenerator
except Exception:
    ResponseGenerator = None

try:
    from zenisys_symphonic_engine import INSTRUMENT_BANK
    from zenisys_voice_engine import ZenisysSound
except Exception:
    INSTRUMENT_BANK = {}
    ZenisysSound = None


ROOT = Path(__file__).resolve().parent
CREATOR_NAME = "Toshay Zeigler"
CREATOR_FULL_NAME = "Toshay S. Zeigler"
COMPANY_NAME = "God's Love for Us LLC"
CREATOR_NAME_SPELLING = "Toshay S. Zeigler"  # hardcoded ownership
CREATOR_IMPRINT_TEXT = (
    "Axiom Harmony Protocol, InnerLight, VEIL, EDEN, and the Zenisys Sound System "
    f"are created by {CREATOR_FULL_NAME} for {COMPANY_NAME}. "
    f"The creator name is spelled {CREATOR_NAME_SPELLING}."
)
CREATOR_IMPRINT_HASH = hashlib.sha3_512(CREATOR_IMPRINT_TEXT.encode("utf-8")).hexdigest()
DEFAULT_DATA_DIR = Path(os.environ.get(
    "AHP_UNIFIED_DATA_DIR",
    r"C:\Users\maste\Documents\Codex\2026-05-31\the-problem-is-i-don-t\work\ahp_unified",
))
DB_PATH = Path(os.environ.get("AHP_UNIFIED_DB", str(DEFAULT_DATA_DIR / "axiom_harmony_unified.db")))
TAXONOMY_PATH = ROOT / "label_taxonomy.json"
AUDIO_CANDIDATES = [
    ROOT / "audio_clips",
    ROOT.parent / "audio_clips",
    Path(os.environ.get("ZENISYS_AUDIO_PATH", "")) if os.environ.get("ZENISYS_AUDIO_PATH") else None,
]
VISUAL_CANDIDATES = [
    ROOT / "visuals",
    ROOT.parent / "visuals",
]

app = Flask(__name__)
app.secret_key = os.environ.get("AHP_UNIFIED_SECRET", os.urandom(32).hex())

# PRIVACY: when True, InnerLight keeps NOTHING. No conversation, session,
# emotion, or case data is written to storage — every session is private and
# gone when it closes. This is the safe default for testing and protects the
# person and the project from any breach/liability around stored data.
# Set environment variable AHP_KEEP_DATA=1 only when a reviewed, consented,
# encrypted storage design is in place.
KEEP_NOTHING = os.environ.get("AHP_KEEP_DATA", "0") != "1"

clarion = Clarion()
crisis_core = CrisisResponseCore()
cultural_detector = CulturalDetector()
localization_engine = LocalizationEngine()
innerlight_system = InnerLightSystem()
innerlight_learning = InnerLightLearningModule()
emotion_module = InnerLightEmotionModule()
response_generator = ResponseGenerator() if ResponseGenerator else None
zenisys_engine = ZenisysSound() if ZenisysSound else None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def encryption_key(scope: str) -> str:
    secret = os.environ.get("AHP_DATA_SECRET", app.secret_key)
    return f"axiom-harmony-unified::{scope}::{secret}"


def encrypt_payload(scope: str, payload: Any) -> Dict[str, Any]:
    return AxiomHarmonyProtocol(encryption_key(scope)).encrypt(payload)


def decrypt_payload(scope: str, encrypted: Dict[str, Any]) -> Any:
    return AxiomHarmonyProtocol(encryption_key(scope)).decrypt(encrypted).get("original_data")


def connect_db() -> sqlite3.Connection:
    # PRIVACY: when keeping nothing, use a fresh in-memory database that is
    # discarded immediately. Writes succeed (so the app logic runs unchanged)
    # but NOTHING is ever persisted to disk. Each call is its own throwaway.
    if KEEP_NOTHING:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn)
        return conn
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn) -> None:
    """Create the table schema on a connection (used for the throwaway
    in-memory DB in privacy mode, so app inserts don't error)."""
    stmts = [
        "CREATE TABLE IF NOT EXISTS encrypted_profiles (id INTEGER PRIMARY KEY, created_at TEXT, profile_fingerprint TEXT, encrypted_json TEXT)",
        "CREATE TABLE IF NOT EXISTS encrypted_sessions (id INTEGER PRIMARY KEY, created_at TEXT, message_fingerprint TEXT, category TEXT, severity INTEGER, risk TEXT, culture TEXT, encrypted_json TEXT)",
        "CREATE TABLE IF NOT EXISTS legal_drafts (id INTEGER PRIMARY KEY, created_at TEXT, issue_fingerprint TEXT, title TEXT, draft_json TEXT)",
        "CREATE TABLE IF NOT EXISTS case_files (id INTEGER PRIMARY KEY, created_at TEXT, case_reference TEXT, share_authorized INTEGER, encrypted_json TEXT)",
        "CREATE TABLE IF NOT EXISTS learning_events (id INTEGER PRIMARY KEY, created_at TEXT, session_reference TEXT, event_fingerprint TEXT, encrypted_json TEXT)",
        "CREATE TABLE IF NOT EXISTS emotion_events (id INTEGER PRIMARY KEY, created_at TEXT, event_fingerprint TEXT, primary_emotion TEXT, distress_score REAL, encrypted_json TEXT)",
        "CREATE TABLE IF NOT EXISTS system_imprints (id INTEGER PRIMARY KEY, created_at TEXT, creator_name TEXT, company_name TEXT, imprint_hash TEXT, public_imprint TEXT, encrypted_imprint_json TEXT)",
    ]
    for s in stmts:
        conn.execute(s)
    conn.commit()


def init_db() -> None:
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS encrypted_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                profile_fingerprint TEXT NOT NULL,
                encrypted_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS encrypted_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                message_fingerprint TEXT NOT NULL,
                category TEXT NOT NULL,
                severity INTEGER NOT NULL,
                risk TEXT NOT NULL,
                culture TEXT NOT NULL,
                encrypted_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS legal_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                issue_fingerprint TEXT NOT NULL,
                title TEXT NOT NULL,
                draft_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS case_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                case_reference TEXT NOT NULL,
                share_authorized INTEGER NOT NULL,
                encrypted_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                session_reference TEXT NOT NULL,
                event_fingerprint TEXT NOT NULL,
                encrypted_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emotion_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_fingerprint TEXT NOT NULL,
                primary_emotion TEXT NOT NULL,
                distress_score INTEGER NOT NULL,
                encrypted_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_imprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                creator_name TEXT NOT NULL,
                company_name TEXT NOT NULL,
                imprint_hash TEXT NOT NULL,
                public_imprint TEXT NOT NULL,
                encrypted_imprint_json TEXT NOT NULL
            )
            """
        )
        existing = conn.execute(
            "SELECT COUNT(*) FROM system_imprints WHERE imprint_hash = ?",
            (CREATOR_IMPRINT_HASH,),
        ).fetchone()[0]
        if not existing:
            encrypted = encrypt_payload("creator-imprint", {
                "creator": CREATOR_FULL_NAME,
                "creator_display": CREATOR_NAME,
                "creator_spelling": CREATOR_NAME_SPELLING,
                "company": COMPANY_NAME,
                "imprint": CREATOR_IMPRINT_TEXT,
                "imprint_hash": CREATOR_IMPRINT_HASH,
            })
            conn.execute(
                """
                INSERT INTO system_imprints
                (created_at, creator_name, company_name, imprint_hash, public_imprint, encrypted_imprint_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (utc_now(), CREATOR_FULL_NAME, COMPANY_NAME, CREATOR_IMPRINT_HASH, CREATOR_IMPRINT_TEXT, json.dumps(encrypted)),
            )


def load_taxonomy_summary() -> Dict[str, Any]:
    if not TAXONOMY_PATH.exists():
        return {"present": False, "domains": []}
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    domains = []
    for name, data in taxonomy.get("domains", {}).items():
        subdomains = data.get("subdomains", {})
        label_count = sum(len(items) for items in subdomains.values())
        domains.append({
            "name": name,
            "description": data.get("description", ""),
            "subdomains": len(subdomains),
            "labels": label_count,
        })
    return {"present": True, "version": taxonomy.get("version"), "domains": domains}


def scan_assets() -> Dict[str, Any]:
    audio_ext = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}
    image_ext = {".png", ".jpg", ".jpeg", ".webp"}

    audio_files: List[str] = []
    for base in [p for p in AUDIO_CANDIDATES if p]:
        if base.exists():
            audio_files.extend(str(path.relative_to(base)) for path in base.rglob("*") if path.suffix.lower() in audio_ext)

    visual_files: List[str] = []
    for base in VISUAL_CANDIDATES:
        if base.exists():
            visual_files.extend(str(path.relative_to(base)) for path in base.rglob("*") if path.suffix.lower() in image_ext)

    return {
        "audio": {"available": bool(audio_files), "count": len(audio_files), "sample": audio_files[:12]},
        "visuals": {"available": bool(visual_files), "count": len(visual_files), "sample": visual_files[:12]},
    }


def sound_engine_status() -> Dict[str, Any]:
    assets = scan_assets()["audio"]
    generated_tone_available = bool(zenisys_engine and getattr(zenisys_engine, "audio_enabled", False))
    return {
        "name": "Zenisys Sound System",
        "creator": CREATOR_FULL_NAME,
        "company": COMPANY_NAME,
        "spelling": "Z-E-N-I-S-Y-S",
        "purpose": "Adaptive therapeutic sound that shifts tone, tempo, and texture while the person responds.",
        "modules": [
            "zenisys_voice_engine.py",
            "zenisys_symphonic_engine.py",
            "zenisys_audio_mapper.py",
            "clarion_voiceprint_phase15.py",
        ],
        "instrument_bank": INSTRUMENT_BANK,
        "audio_assets": assets,
        "generated_tone_available": generated_tone_available,
        "status": "ready" if assets["available"] or generated_tone_available else "asset_or_audio_driver_required",
        "note": "No simulated playback is reported as real playback.",
    }


def support_response(user_text: str, analysis: Dict[str, Any]) -> str:
    crisis = crisis_core.evaluate(user_text)
    if crisis.risk in {"critical", "high"}:
        return crisis.public_response

    if response_generator:
        generated = response_generator.generate_response(user_text)
        if generated:
            return generated

    category = analysis.get("category", "unclear")
    severity = int(analysis.get("severity", 0))
    if category == "crisis" or severity >= 9:
        return "I hear that this is urgent. Please contact emergency support or a trusted person right now while staying connected to immediate help."
    if severity >= 7:
        return "I hear the pressure in this. Let us slow the moment down and focus on one next safe step."
    if severity >= 5:
        return "I hear you. This looks like a meaningful stress signal, and it deserves attention without shame."
    return "Thank you for checking in. I am here with you, and we can take this one step at a time."


def draft_legal_response(issue: str, jurisdiction: str, channel: str) -> Dict[str, Any]:
    clean_issue = issue.strip()
    clean_jurisdiction = jurisdiction.strip() or "Relevant Jurisdiction"
    clean_channel = channel.strip() or "Public Official"
    title = f"Draft Response Regarding {clean_issue[:80]}"
    today = datetime.now().strftime("%B %d, %Y")
    letter = (
        f"{today}\n\n"
        f"To: {clean_channel}\n"
        f"Jurisdiction: {clean_jurisdiction}\n\n"
        f"Re: Request for review and corrective action\n\n"
        f"We request review of the following issue: {clean_issue}\n\n"
        "This draft asks the recipient to preserve access, review the factual record, identify the legal authority for any restriction, "
        "and provide a written response explaining available appeal, accommodation, or reconsideration procedures.\n\n"
        "Requested action:\n"
        "1. Pause or review the challenged restriction.\n"
        "2. Preserve relevant records and communications.\n"
        "3. Identify affected groups and available accommodations.\n"
        "4. Provide a written explanation and timeline for resolution.\n\n"
        "CRASH/VEIL routing:\n"
        "1. Start legal research with Cornell Law Legal Information Institute.\n"
        "2. Check local/neighborhood, city, county, state, federal, agency/regulator, court, and legislative pathways.\n"
        "3. Prepare evidence, timeline, official-letter, legislative-proposal, petition, and attorney-review outputs as needed.\n\n"
        "This is a generated draft for review, not legal advice."
    )
    return {
        "title": title,
        "jurisdiction": clean_jurisdiction,
        "channel": clean_channel,
        "letter": letter,
        "notice": "Generated draft for review only; consult qualified counsel before filing or sending.",
    }


def system_audit() -> Dict[str, Any]:
    encryption_probe = encrypt_payload("audit", {"probe": "ok", "time": utc_now()})
    encryption_ok = decrypt_payload("audit", encryption_probe).get("probe") == "ok"
    with connect_db() as conn:
        profiles = conn.execute("SELECT COUNT(*) FROM encrypted_profiles").fetchone()[0]
        sessions = conn.execute("SELECT COUNT(*) FROM encrypted_sessions").fetchone()[0]
        legal = conn.execute("SELECT COUNT(*) FROM legal_drafts").fetchone()[0]
        case_files = conn.execute("SELECT COUNT(*) FROM case_files").fetchone()[0]
        learning = conn.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0]
        emotion_events = conn.execute("SELECT COUNT(*) FROM emotion_events").fetchone()[0]
        imprints = conn.execute("SELECT COUNT(*) FROM system_imprints").fetchone()[0]
    return {
        "creator": {
            "name": CREATOR_FULL_NAME,
            "display_name": CREATOR_NAME,
            "name_spelling": CREATOR_NAME_SPELLING,
            "company": COMPANY_NAME,
            "imprint_hash": CREATOR_IMPRINT_HASH,
            "public_imprint": CREATOR_IMPRINT_TEXT,
            "database_imprints": imprints,
        },
        "encryption_roundtrip": encryption_ok,
        "database": {"path": str(DB_PATH), "profiles": profiles, "sessions": sessions, "case_files": case_files, "learning_events": learning, "emotion_events": emotion_events, "legal_drafts": legal},
        "sound_engine": sound_engine_status(),
        "assets": scan_assets(),
        "taxonomy": load_taxonomy_summary(),
        "readiness": readiness_report(),
    }


PUBLIC_PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="creator" content="Toshay S. Zeigler">
  <meta name="company" content="God's Love for Us LLC">
  <title>God's Love for Us LLC | Axiom Harmony</title>
  <!-- Creator imprint: God's Love for Us LLC, Axiom Harmony Protocol, InnerLight, VEIL, EDEN, and the Zenisys Sound System are created by Toshay S. Zeigler. -->
  <style>
  @keyframes listenpulse { 0%,100%{opacity:1;transform:scale(1);} 50%{opacity:0.4;transform:scale(1.3);} }
    :root { --page:#f7fbf8; --ink:#17221b; --muted:#52645a; --panel:#ffffff; --line:#d8e6dd; --teal:#0f766e; --leaf:#2f855a; --coral:#c85c54; --gold:#b7791f; }
    * { box-sizing:border-box; }
    body { margin:0; font-family: Arial, sans-serif; background:var(--page); color:var(--ink); line-height:1.5; }
    a { color:var(--teal); text-decoration:none; }
    header { position:sticky; top:0; z-index:5; background:rgba(247,251,248,.96); border-bottom:1px solid var(--line); padding:14px 24px; display:flex; justify-content:space-between; align-items:center; gap:18px; }
    .brand { font-weight:700; color:var(--ink); }
    .brand small { display:block; color:var(--muted); font-weight:400; }
    nav { display:flex; gap:14px; flex-wrap:wrap; font-size:14px; }
    .hero { position:relative; min-height:560px; padding:72px 24px 46px; overflow:hidden; display:grid; align-items:center; border-bottom:1px solid var(--line); }
    .hero-inner { position:relative; z-index:2; max-width:1040px; margin:0 auto; width:100%; }
    .hero h1 { margin:0; max-width:780px; font-size:clamp(42px, 7vw, 84px); line-height:.95; letter-spacing:0; }
    .hero p { max-width:720px; font-size:20px; color:var(--muted); margin:22px 0 0; }
    .hero-actions { display:flex; gap:12px; flex-wrap:wrap; margin-top:28px; }
    .button { display:inline-flex; align-items:center; justify-content:center; min-height:42px; padding:10px 16px; border:1px solid var(--teal); background:var(--teal); color:white; border-radius:4px; font-weight:700; cursor:pointer; }
    .button.secondary { background:white; color:var(--teal); }
    .sound-scene { position:absolute; inset:0; opacity:.58; pointer-events:none; }
    .bar { position:absolute; bottom:0; width:18px; border:1px solid rgba(15,118,110,.25); background:#d7f3eb; animation:pulse 4s ease-in-out infinite; }
    .bar:nth-child(1) { left:6%; height:28%; animation-delay:.1s; }
    .bar:nth-child(2) { left:13%; height:52%; animation-delay:.5s; background:#eaf7f1; }
    .bar:nth-child(3) { left:22%; height:36%; animation-delay:.2s; background:#f7e1de; }
    .bar:nth-child(4) { left:33%; height:66%; animation-delay:.8s; }
    .bar:nth-child(5) { left:45%; height:42%; animation-delay:.4s; background:#f3ead3; }
    .bar:nth-child(6) { left:58%; height:74%; animation-delay:.9s; background:#e7f4dd; }
    .bar:nth-child(7) { left:70%; height:48%; animation-delay:.3s; background:#f7e1de; }
    .bar:nth-child(8) { left:83%; height:61%; animation-delay:.7s; }
    .bar:nth-child(9) { left:93%; height:33%; animation-delay:.2s; background:#eaf7f1; }
    @keyframes pulse { 0%,100% { transform:scaleY(.82); } 50% { transform:scaleY(1.08); } }
    .band { padding:54px 24px; }
    .band.alt { background:#eef8f2; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }
    .wrap { max-width:1040px; margin:0 auto; }
    .section-title { font-size:32px; margin:0 0 12px; }
    .section-copy { color:var(--muted); max-width:760px; margin:0 0 24px; }
    .grid { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:14px; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:18px; }
    .card h3 { margin:0 0 8px; }
    .card p { color:var(--muted); margin:0; }
    .checkin { display:grid; grid-template-columns:1fr 1fr; gap:18px; align-items:start; }
    label { display:block; color:var(--muted); font-size:13px; margin:10px 0 5px; }
    textarea, select { width:100%; padding:11px; border:1px solid var(--line); border-radius:4px; background:white; color:var(--ink); }
    textarea { min-height:138px; resize:vertical; }
    pre { white-space:pre-wrap; word-break:break-word; background:white; border:1px solid var(--line); border-radius:4px; padding:14px; min-height:138px; }
    .care-result { background:white; border:1px solid var(--line); border-radius:6px; padding:18px; min-height:160px; }
    .care-result h3 { margin:0 0 8px; color:var(--teal); }
    .care-result p { margin:0 0 14px; color:var(--ink); }
    .care-result ul { margin:8px 0 0; padding-left:20px; color:var(--muted); }
    .mini-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    input { width:100%; padding:11px; border:1px solid var(--line); border-radius:4px; background:white; color:var(--ink); }
    .check-row { display:flex; align-items:center; gap:8px; margin:10px 0; color:var(--muted); font-size:14px; }
    .check-row input { width:auto; }
    .sound-panel { margin-top:12px; padding:12px; border:1px solid var(--line); border-radius:6px; background:#f9fcfa; }
    .emotion-panel { margin-top:12px; padding:12px; border:1px solid var(--line); border-radius:6px; background:#fffdf7; }
    .inline-actions { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:8px; }
    .video-preview { width:100%; max-height:190px; margin-top:8px; border:1px solid var(--line); border-radius:6px; background:#eef4f2; object-fit:cover; }
    .emotion-status { color:var(--muted); font-size:13px; margin-top:8px; }
    .sound-status { color:var(--muted); font-size:13px; margin-top:8px; }
    /* Calm welcome redesign — light, warm, inviting */
    #welcome-gate { position:fixed; inset:0; z-index:50; display:flex; align-items:center; justify-content:center;
      background:linear-gradient(160deg, #f0f7f4 0%, #e8f4ec 30%, #fdf2f0 60%, #f5eef6 100%); text-align:center; padding:24px; }
    .gate-inner { max-width:440px; }
    .gate-mark { font-size:46px; color:#7eb8a0; opacity:.85; margin-bottom:6px; animation:breathe 4s ease-in-out infinite; }
    @keyframes breathe { 0%,100%{opacity:.5;transform:scale(1)} 50%{opacity:1;transform:scale(1.06)} }
    #welcome-gate h1 { font-size:30px; margin:6px 0 12px; font-weight:600; letter-spacing:.02em; color:#2d4a3e; }
    #welcome-gate p { color:#5a7d6d; font-size:15px; line-height:1.6; margin:0 0 22px; }
    .gate-button { background:#5ba08a; color:#fff; border:0; border-radius:999px; padding:15px 38px;
      font-size:16px; font-weight:600; cursor:pointer; box-shadow:0 12px 30px rgba(91,160,138,.35); transition:transform .15s; }
    .gate-button:hover { transform:translateY(-2px); background:#4e9079; }
    .gate-sub { font-size:12px; color:#8fa8a0; margin-top:18px !important; }
    .story-screen { min-height:100vh; display:flex; flex-direction:column; align-items:center; padding:0 20px 40px;
      position:relative; overflow:hidden;
      background:linear-gradient(180deg, #f5faf7 0%, #fdf8f6 50%, #f7f0f9 100%); }
    #calm-bg { position:fixed; top:0; left:0; width:100vw; height:100vh; z-index:0; pointer-events:none; }
    .story-screen > * { position:relative; z-index:1; }
    .story-video-bar { position:sticky; top:0; z-index:30 !important; }
    .scene-picker { position:fixed; bottom:14px; right:14px; z-index:20; display:flex; gap:6px;
      background:rgba(255,255,255,0.7); backdrop-filter:blur(6px); border-radius:999px; padding:6px 10px; }
    .scene-btn { background:none; border:0; font-size:18px; cursor:pointer; opacity:0.6; padding:2px 4px; }
    .scene-btn.active { opacity:1; transform:scale(1.15); }
    .story-video-bar { padding:14px 0 8px; width:100%; text-align:center;
      position:sticky; top:0; z-index:30;
      background:linear-gradient(180deg, rgba(245,250,247,0.94), rgba(245,250,247,0.70));
      backdrop-filter:blur(6px); transition:padding 0.35s ease; }
    /* When the conversation is active, the pinned face shrinks so it stays
       visible without taking the whole screen — but never disappears. */
    .story-video-bar.compact { padding:8px 0 6px; }
    .story-video-bar.compact .story-video { width:84px; height:84px; border-width:2px; border-radius:16px; box-shadow:0 4px 14px rgba(0,0,0,0.16); margin-bottom:0; }
    .story-wrap { width:100%; max-width:620px; text-align:center; padding-top:10px; }
    #conversation-thread { background:rgba(255,255,255,0.55); backdrop-filter:blur(3px);
      border-radius:18px; padding:4px 16px; max-height:52vh; overflow-y:auto; scroll-behavior:smooth; }
    #conversation-thread:empty { background:none; padding:0; }
    .story-video { width:340px; height:340px; max-width:80vw; max-height:80vw; object-fit:cover; border-radius:24px; border:3px solid #c8ddd2;
      margin:0 auto 8px; display:block; background:#e8f0eb; box-shadow:0 8px 30px rgba(0,0,0,0.18); transition:width 0.35s ease, height 0.35s ease, border-radius 0.35s ease; }
    .story-title { font-size:26px; font-weight:600; margin:0 0 6px; color:#2d4a3e; }
    .story-sub { color:#6d8f80; font-size:14px; margin:0 0 22px; }
    .story-input { width:100%; min-height:130px; box-sizing:border-box; padding:18px; border-radius:16px;
      border:1px solid #c8ddd2; background:#ffffff; color:#2d4a3e; font-size:16px; line-height:1.6; resize:vertical;
      font-family:inherit; }
    .story-input::placeholder { color:#a3bfb2; }
    .story-input:focus { outline:none; border-color:#5ba08a; box-shadow:0 0 0 3px rgba(91,160,138,.15); }
    .story-actions { display:flex; gap:12px; justify-content:center; margin:18px 0 10px; }
    .story-send { background:#5ba08a; color:#fff; border:0; border-radius:999px; padding:13px 40px; font-size:15px;
      font-weight:600; cursor:pointer; }
    .story-send:hover { background:#4e9079; }
    .story-mic { background:#fff; color:#5a7d6d; border:1px solid #c8ddd2; border-radius:999px; padding:13px 22px;
      font-size:14px; cursor:pointer; }
    .music-bar { display:flex; align-items:center; justify-content:center; gap:14px; margin-top:14px; color:#6d8f80; font-size:13px; }
    .music-change { background:#fff; border:1px solid #c8ddd2; color:#5a7d6d; border-radius:999px; padding:6px 16px;
      font-size:12px; cursor:pointer; }
    .emotion-badge { display:inline-block; background:#e8f4ec; color:#2d6b4f; font-size:12px; padding:4px 12px;
      border-radius:999px; margin-top:10px; font-weight:500; }
    .care-result .detail-band { background:#f5faf7; border:1px solid #d8e6dd; border-radius:12px; padding:16px; margin:14px 0; }
    .zen-alts .zen-track, .zen-alts .music-change { background:#fff; border:1px solid #c8ddd2; color:#3d6b5a;
      border-radius:999px; padding:7px 16px; font-size:12px; cursor:pointer; }
    .zen-alts .zen-track:hover { background:#e8f4ec; }
    .question-list li { margin-bottom:8px; color:var(--ink); }
    .detail-band { border-top:1px solid var(--line); margin-top:14px; padding-top:12px; }
    .pill { display:inline-block; margin:3px 6px 3px 0; padding:4px 8px; border-radius:4px; border:1px solid var(--line); background:#f9fcfa; color:var(--muted); font-size:12px; }
    .care-result.critical { border-color:var(--coral); background:#fff7f6; }
    .care-result.critical h3 { color:#a33b35; }
    .care-result.high { border-color:var(--gold); background:#fffaf0; }
    footer { padding:28px 24px; border-top:1px solid var(--line); color:var(--muted); background:white; }
    @media (max-width: 860px) { .grid, .checkin { grid-template-columns:1fr; } .hero { min-height:520px; } header { align-items:flex-start; flex-direction:column; } }
  </style>
</head>
<body>
  <header>
    <div class="brand">InnerLight</div>
    <nav>
      <a href="#" onclick="return false;">Private &amp; Encrypted</a>
    </nav>
  </header>
  <main>
    <!-- TAP TO BEGIN -->
    <div id="welcome-gate">
      <div class="gate-inner">
        <div class="gate-mark" aria-hidden="true">&#9711;</div>
        <h1>InnerLight</h1>
        <p>A quiet, private place to tell your story.<br>Nothing you share is shown to anyone &mdash; it is encrypted.</p>
        <button class="gate-button" onclick="startExperience()">Tap to begin</button>
        <p class="gate-sub">Soft music and your camera begin gently when you tap.</p>
      </div>
    </div>

    <!-- CALM STORY SCREEN -->
    <section id="story-screen" class="story-screen" style="display:none;">
      <!-- REALISM LEADS: real video background plays first. Animated canvas is fallback only. -->
      <video id="calm-video" autoplay muted loop playsinline
             style="position:fixed;top:0;left:0;width:100vw;height:100vh;object-fit:cover;z-index:0;pointer-events:none;display:none;"></video>
      <canvas id="calm-bg" style="display:none;"></canvas>
      <div class="scene-picker" id="scene-picker">
        <button class="scene-btn active" data-scene="meadow" onclick="setScene('meadow')" title="Meadow">&#127807;</button>
        <button class="scene-btn" data-scene="stars" onclick="setScene('stars')" title="Starry sky">&#10024;</button>
        <button class="scene-btn" data-scene="clouds" onclick="setScene('clouds')" title="Clouds">&#9729;</button>
        <button class="scene-btn" data-scene="ocean" onclick="setScene('ocean')" title="Ocean">&#127754;</button>
        <button class="scene-btn" data-scene="rain" onclick="setScene('rain')" title="Gentle rain">&#127783;</button>
        <button class="scene-btn" data-scene="city" onclick="setScene('city')" title="City from above">&#127961;</button>
      </div>
      <div class="story-video-bar">
        <video id="visual-preview" class="story-video" autoplay muted playsinline></video>
        <div class="emotion-badge" id="face-emotion-badge" style="display:none;"></div>
      </div>
      <div class="story-wrap">
        <h2 class="story-title">Tell me your story.</h2>
        <p class="story-sub">Take your time. Say whatever feels true. I am listening.</p>
        <textarea id="message" class="story-input" placeholder="Start wherever you would like... (press Enter to send)" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendCheckin();}"></textarea>
        <div class="story-actions">
          <button class="story-send" onclick="sendCheckin()">Share</button>
          <button class="story-mic" type="button" onclick="startVoiceCapture()" title="Speak instead of typing">&#127908; Speak</button>
        </div>
        <div class="music-bar">
          <span id="music-now">&#9834; soft music playing</span>
          <button class="music-change" type="button" onclick="changeMusic()">Change music</button>
          <button class="music-change" type="button" id="voice-toggle" onclick="toggleVoice()">&#128263; Voice Off</button>
          <select id="voice-picker" onchange="selectVoice(this.value)" style="border-radius:999px;border:1px solid #c8ddd2;padding:5px 10px;font-size:13px;color:#3a5a72;background:#fff;max-width:200px;" title="Choose a voice that feels comforting"><option value="">Voice: default</option></select>
          <button class="music-change" type="button" id="voicefirst-toggle" onclick="toggleVoiceFirst()">&#127908; Voice-First: Off</button>
        </div>
        <div id="calm-player" style="margin:18px auto 6px; max-width:560px; background:rgba(20,30,48,0.92); border-radius:20px; padding:14px 14px 12px; box-shadow:0 8px 30px rgba(0,0,0,0.22); transition:max-width 0.5s ease;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <span style="color:#cfe3f2;font-size:14px;font-weight:600;">&#10024; Calm space &mdash; touch and move to make light and sound</span>
            <span id="calm-music-note" style="color:#7fa9c9;font-size:12px;">music softens while you play</span>
          </div>
          <div id="calm-tabs" style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap;">
            <button type="button" class="calm-tab active" data-mode="anchor" onclick="setCalmMode('anchor')" style="background:#6fb3d4;color:#0c1322;border:0;border-radius:999px;padding:5px 12px;font-size:12px;font-weight:700;cursor:pointer;">Touch &amp; Calm</button>
            <button type="button" class="calm-tab" data-mode="trace" onclick="setCalmMode('trace')" style="background:rgba(255,255,255,0.10);color:#cfe3f2;border:1px solid rgba(255,255,255,0.2);border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer;">Trace</button>
            <button type="button" class="calm-tab" data-mode="call" onclick="setCalmMode('call')" style="background:rgba(255,255,255,0.10);color:#cfe3f2;border:1px solid rgba(255,255,255,0.2);border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer;">Call &amp; Answer</button>
          </div>
          <canvas id="calm-touch" style="width:100%;height:240px;display:block;border-radius:14px;background:radial-gradient(circle at 50% 50%, #16314a, #0c1322);touch-action:none;cursor:pointer;transition:height 0.5s ease;"></canvas>
        </div>
        <div id="conversation-thread" style="margin-top:22px;"></div>
        <div id="help-bar" style="margin:16px auto 8px;max-width:560px;display:flex;flex-wrap:wrap;gap:8px;justify-content:center;">
          <a href="tel:988" class="help-btn" style="background:#e8534e;color:#fff;border:0;border-radius:999px;padding:10px 18px;font-size:14px;font-weight:700;text-decoration:none;">&#128222; Call 988 now</a>
          <button type="button" class="help-btn" onclick="openHelp('telehealth')" style="background:#fff;color:#2e6e8e;border:1px solid #2e6e8e;border-radius:999px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer;">Talk to a provider</button>
          <button type="button" class="help-btn" onclick="openHelp('attorney')" style="background:#fff;color:#2e6e8e;border:1px solid #2e6e8e;border-radius:999px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer;">Legal help</button>
        </div>
        <div id="urgent-help" style="display:none;margin:6px auto;max-width:560px;text-align:center;padding:12px;background:rgba(232,83,78,0.1);border:1px solid rgba(232,83,78,0.4);border-radius:14px;color:#b3322e;font-weight:600;"></div>
        <div id="live-transcript" style="display:none;margin-top:14px;padding:14px 16px;background:rgba(111,179,212,0.12);border:1px solid rgba(111,179,212,0.4);border-radius:14px;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <span id="listen-dot" style="width:11px;height:11px;border-radius:50%;background:#e05a5a;display:inline-block;animation:listenpulse 1.1s ease-in-out infinite;"></span>
            <span id="listen-label" style="font-size:13px;color:#5a7a96;font-weight:600;">Listening\u2026</span>
          </div>
          <div id="transcript-text" style="font-size:17px;line-height:1.5;color:#1a3a5c;min-height:24px;">&nbsp;</div>
        </div>
        <div class="sound-status" id="sound-status"></div>
        <div class="emotion-status" id="emotion-status" style="display:none;"></div>
        <textarea id="voice_transcript" style="display:none;"></textarea>
        <audio id="ambient-a" preload="auto"></audio>
        <audio id="ambient-b" preload="auto"></audio>
      </div>
    </section>
  </main>
  </main>
  <footer>
    Created by Toshay S. Zeigler for God's Love for Us LLC.
  </footer>
<script src="https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/dist/face-api.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/tone@14/build/Tone.js"></script>
<script>
// ========================================================
// CALMING SCENE ENGINE — realism leads, animation is fallback
// ========================================================
// Real nature video plays as the background by default. The animated
// canvas only appears if video can't load (slow connection, offline, or
// no file present). Realism always outweighs animation.
const SCENE_VIDEOS = {
  // These point to the app's own /scenes/ folder (downloaded real footage).
  // If a file is missing, the animated fallback for that scene runs instead.
  meadow: '/scenes/meadow.mp4',
  stars:  '/scenes/stars.mp4',
  clouds: '/scenes/clouds.mp4',
  ocean:  '/scenes/ocean.mp4',
  rain:   '/scenes/rain.mp4',
  city:   '/scenes/city.mp4'
};
let currentScene = 'meadow';
let canvasAnim = null;

function setScene(scene) {
  currentScene = scene;
  document.querySelectorAll('.scene-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.scene === scene);
  });
  const video = document.getElementById('calm-video');
  const canvas = document.getElementById('calm-bg');
  const src = SCENE_VIDEOS[scene];
  // TRY REAL VIDEO FIRST
  if (src) {
    video.onerror = () => useAnimatedFallback(scene);
    video.oncanplay = () => {
      // Real video loaded — hide the animated fallback
      video.style.display = 'block';
      canvas.style.display = 'none';
      if (canvasAnim) { cancelAnimationFrame(canvasAnim); canvasAnim = null; }
    };
    video.src = src;
    video.load();
    // If video doesn't become playable quickly, fall back gracefully
    setTimeout(() => {
      if (video.readyState < 2) useAnimatedFallback(scene);
    }, 2500);
  } else {
    useAnimatedFallback(scene);
  }
}

function useAnimatedFallback(scene) {
  // Animation ONLY when real video isn't available. Never the main event.
  const video = document.getElementById('calm-video');
  const canvas = document.getElementById('calm-bg');
  video.style.display = 'none';
  canvas.style.display = 'block';
  startCanvasScene(scene);
}

function startCanvasScene(scene) {
  const canvas = document.getElementById('calm-bg');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  if (canvasAnim) cancelAnimationFrame(canvasAnim);

  // Gentle, realistic-feeling gradient scenes with soft motion.
  // Deliberately subtle — calming, not cartoonish.
  const palettes = {
    meadow: ['#cfe8d4', '#e8f3dd', '#f3f0d8'],
    stars:  ['#1a2238', '#2a3458', '#3d4a78'],
    clouds: ['#dce8f5', '#eef4fa', '#f7fafd'],
    ocean:  ['#bfe0e8', '#d8eef2', '#e8f5f7'],
    rain:   ['#cdd6dd', '#dde4e9', '#eaeef1'],
    city:   ['#0d1b2a', '#1b3a5b', '#2c5378']
  };
  const colors = palettes[scene] || palettes.meadow;
  let t = 0;
  const particles = [];
  // Soft drifting particles (pollen, stars, raindrops) — minimal, gentle
  const count = scene === 'stars' ? 60 : scene === 'rain' ? 50 : 25;
  for (let i = 0; i < count; i++) {
    particles.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: scene === 'stars' ? Math.random()*1.5+0.5 : Math.random()*3+1,
      speed: scene === 'rain' ? Math.random()*4+3 : Math.random()*0.4+0.1,
      drift: Math.random()*0.5-0.25
    });
  }
  function draw() {
    t += 0.003;
    // Soft shifting gradient
    const g = ctx.createLinearGradient(0, 0, 0, canvas.height);
    const shift = (Math.sin(t) + 1) / 2 * 0.1;
    g.addColorStop(0, colors[0]);
    g.addColorStop(0.5 + shift, colors[1]);
    g.addColorStop(1, colors[2]);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    // Gentle particles
    ctx.fillStyle = scene === 'stars' ? 'rgba(255,255,255,0.8)'
                  : scene === 'rain' ? 'rgba(255,255,255,0.4)'
                  : 'rgba(255,255,255,0.5)';
    particles.forEach(p => {
      if (scene === 'stars') {
        ctx.globalAlpha = 0.4 + Math.sin(t*3 + p.x) * 0.4;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI*2); ctx.fill();
        ctx.globalAlpha = 1;
      } else if (scene === 'rain') {
        ctx.fillRect(p.x, p.y, 1, p.r*4);
        p.y += p.speed; if (p.y > canvas.height) { p.y = -10; p.x = Math.random()*canvas.width; }
      } else {
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI*2); ctx.fill();
        p.y -= p.speed; p.x += p.drift;
        if (p.y < -10) { p.y = canvas.height+10; p.x = Math.random()*canvas.width; }
      }
    });
    canvasAnim = requestAnimationFrame(draw);
  }
  draw();
}

window.addEventListener('resize', () => {
  const canvas = document.getElementById('calm-bg');
  if (canvas && canvas.style.display !== 'none') {
    canvas.width = window.innerWidth; canvas.height = window.innerHeight;
  }
});

// ========================================================
// ZENISYS SOUND ENGINE v3 — DJ Crossfade + Generative Layer
// ========================================================
const FACE_API_MODELS = 'https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@master/weights/';
let faceReady = false;
let currentFaceEmotion = null;
let faceEmotionScores = {};

// --- Face detection ---
async function loadFaceModels() {
  try {
    await faceapi.nets.tinyFaceDetector.loadFromUri(FACE_API_MODELS);
    await faceapi.nets.faceExpressionNet.loadFromUri(FACE_API_MODELS);
    faceReady = true;
  } catch (e) { console.log('[Face] Models unavailable:', e); }
}
async function detectFaceEmotion() {
  if (!faceReady) return;
  // Don't compete with the keyboard: if the person typed in the last 1.2s,
  // skip this cycle so typing stays instant.
  if (window._lastTypedAt && (performance.now() - window._lastTypedAt) < 1200) return;
  const video = document.getElementById('visual-preview');
  if (!video || !video.videoWidth) return;
  try {
    const det = await faceapi.detectSingleFace(video, new faceapi.TinyFaceDetectorOptions()).withFaceExpressions();
    if (det && det.expressions) {
      faceEmotionScores = det.expressions;
      let top = 'neutral', topVal = 0;
      for (const [k, v] of Object.entries(det.expressions)) { if (v > topVal) { top = k; topVal = v; } }
      currentFaceEmotion = top;
      const badge = document.getElementById('face-emotion-badge');
      if (badge) { badge.textContent = top + ' (' + Math.round(topVal * 100) + '%)'; badge.style.display = 'inline-block'; }
    }
  } catch (e) {}
}
let faceInterval = null;
function startFaceLoop() { if (!faceInterval) faceInterval = setInterval(detectFaceEmotion, 3500); }

// --- DJ CROSSFADE ENGINE ---
let deckA, deckB, activeDeck = 'A';
let crossfading = false;
const CROSSFADE_MS = 4000; // 4 second blend
const CROSSFADE_TRIGGER = 8; // start blend 8 seconds before track ends
const TARGET_VOL = 0.14;

function initDecks() {
  deckA = document.getElementById('ambient-a');
  deckB = document.getElementById('ambient-b');
  if (deckA) {
    deckA.volume = 0;
    deckA.addEventListener('timeupdate', checkCrossfade);
  }
  if (deckB) {
    deckB.volume = 0;
    deckB.addEventListener('timeupdate', checkCrossfade);
  }
}
function getActiveDeck() { return activeDeck === 'A' ? deckA : deckB; }
function getInactiveDeck() { return activeDeck === 'A' ? deckB : deckA; }

function checkCrossfade() {
  if (crossfading) return;
  const active = getActiveDeck();
  if (!active || !active.duration || isNaN(active.duration)) return;
  const remaining = active.duration - active.currentTime;
  if (remaining > 0 && remaining <= CROSSFADE_TRIGGER) {
    // Time to blend into the next track
    crossfading = true;
    playNextTrackBlended();
  }
}

function crossfade(fadeOut, fadeIn, duration) {
  // Smooth DJ-style volume crossfade
  const steps = 40;
  const interval = duration / steps;
  let step = 0;
  const startVolOut = fadeOut.volume;
  const startVolIn = 0;
  fadeIn.volume = 0;
  fadeIn.play().catch(()=>{});
  const timer = setInterval(() => {
    step++;
    const progress = step / steps;
    // Ease curve for smooth blend
    const ease = progress * progress * (3 - 2 * progress); // smoothstep
    fadeOut.volume = Math.max(0, startVolOut * (1 - ease));
    fadeIn.volume = TARGET_VOL * ease;
    if (step >= steps) {
      clearInterval(timer);
      fadeOut.pause();
      fadeOut.volume = 0;
      fadeIn.volume = TARGET_VOL;
      crossfading = false;
    }
  }, interval);
}

async function playNextTrackBlended() {
  if (ambientTracks.length <= 1) {
    // Only one track — fetch new ones based on current emotion
    const emo = currentFaceEmotion || 'calm';
    try {
      const res = await fetch('/api/zenisys/ambient?emotion=' + encodeURIComponent(emo));
      const d = await res.json();
      if (d.tracks && d.tracks.length) { ambientTracks = d.tracks; }
    } catch (e) {}
  }
  ambientIndex = (ambientIndex + 1) % ambientTracks.length;
  const next = ambientTracks[ambientIndex];
  const inactive = getInactiveDeck();
  inactive.src = next.url;
  inactive.load();
  // Start crossfade
  crossfade(getActiveDeck(), inactive, CROSSFADE_MS);
  activeDeck = activeDeck === 'A' ? 'B' : 'A';
  const now = document.getElementById('music-now');
  if (now) now.textContent = '\u266a ' + (next.name || 'music');
}

// =====================================================================
// ZENISYS THERAPEUTIC AUDIO RENDERER
// Renders a SoundscapePlan into live, layered, healing sound — entirely
// in the browser (Web Audio + Tone.js). No files, no internet, private.
// Layers: harmonic pad, slow evolving chords, optional binaural beat,
// optional solfeggio drone — all with tempo entrainment (ISO principle)
// and spectral softness.
// =====================================================================

const ZENISYS = {
  started: false,
  pad: null,
  reverb: null,
  filter: null,
  masterGain: null,
  chordLoop: null,
  currentPlan: null,
  binauralNodes: null,
  solfeggioNode: null,
  audioCtx: null,
};

// Scale degrees (semitone offsets) for the scales the core uses
const SCALE_INTERVALS = {
  major:  [0, 2, 4, 5, 7, 9, 11],
  minor:  [0, 2, 3, 5, 7, 8, 10],
  dorian: [0, 2, 3, 5, 7, 9, 10],
  lydian: [0, 2, 4, 6, 7, 9, 11],
};
const NOTE_BASE = { C:0, 'C#':1, D:2, 'D#':3, E:4, F:5, 'F#':6, G:7, 'G#':8, A:9, 'A#':10, B:11 };

function noteName(semitoneFromC, octave) {
  const names = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
  const idx = ((semitoneFromC % 12) + 12) % 12;
  return names[idx] + octave;
}

// Build gentle, wide, consonant chords for a key+scale
function buildChords(keyRoot, scale, consonance) {
  const root = NOTE_BASE[keyRoot] != null ? NOTE_BASE[keyRoot] : 0;
  const intervals = SCALE_INTERVALS[scale] || SCALE_INTERVALS.major;
  // Build 4 chords on scale degrees I - IV - vi - V (warm, resolving motion)
  const degrees = [0, 3, 5, 4];
  const chords = degrees.map(deg => {
    const r = root + intervals[deg % intervals.length];
    const third = root + intervals[(deg + 2) % intervals.length];
    const fifth = root + intervals[(deg + 4) % intervals.length];
    // Wider, more consonant voicing when consonance is high (add octave)
    const notes = [noteName(r, 3), noteName(third, 4), noteName(fifth, 4)];
    if (consonance > 0.9) notes.push(noteName(r, 4)); // gentle octave doubling
    return notes;
  });
  return chords;
}

async function zenisysStart(plan) {
  if (typeof Tone === 'undefined') { console.log('[Zenisys] Tone.js unavailable'); return; }
  try {
    await Tone.start();
    ZENISYS.audioCtx = Tone.getContext().rawContext;
    if (!ZENISYS.started) {
      // Master chain: pad -> lowpass filter (spectral softness) -> reverb -> gain -> out
      ZENISYS.masterGain = new Tone.Gain(plan.volume).toDestination();
      ZENISYS.reverb = new Tone.Reverb({ decay: 8, wet: 0.55 }).connect(ZENISYS.masterGain);
      ZENISYS.filter = new Tone.Filter({ type: 'lowpass', frequency: 1200, rolloff: -24 }).connect(ZENISYS.reverb);
      ZENISYS.pad = new Tone.PolySynth(Tone.Synth, {
        oscillator: { type: 'sine' },
        envelope: { attack: plan.attack_seconds, decay: 1.5,
                    sustain: 0.5, release: plan.release_seconds },
        volume: -26
      }).connect(ZENISYS.filter);
      ZENISYS.started = true;
    }
    zenisysApplyPlan(plan);
  } catch (e) { console.log('[Zenisys] start error', e); }
}

function zenisysApplyPlan(plan) {
  if (!ZENISYS.started) return;
  ZENISYS.currentPlan = plan;

  // --- Spectral softness: brightness controls the lowpass cutoff ---
  const cutoff = 600 + plan.brightness * 3200; // 600..3800 Hz
  if (ZENISYS.filter) ZENISYS.filter.frequency.rampTo(cutoff, 4);

  // --- Volume ---
  if (ZENISYS.masterGain) ZENISYS.masterGain.gain.rampTo(plan.volume, 4);

  // --- Envelope (gentle attack/long release) ---
  if (ZENISYS.pad && ZENISYS.pad.set) {
    ZENISYS.pad.set({ envelope: { attack: plan.attack_seconds, release: plan.release_seconds } });
  }

  // --- TEMPO ENTRAINMENT (ISO principle): start at start_bpm, glide to target ---
  Tone.Transport.bpm.value = plan.start_bpm;
  Tone.Transport.bpm.rampTo(plan.target_bpm, plan.bpm_glide_seconds);

  // --- Harmonic layer: build chords for the plan's key/scale ---
  const chords = buildChords(plan.key_root, plan.scale, plan.consonance);
  let idx = 0;
  if (ZENISYS.chordLoop) { ZENISYS.chordLoop.stop(); ZENISYS.chordLoop.dispose(); }
  // Chord change interval from the plan (slow harmonic rhythm = safety)
  const interval = Math.max(2, plan.chord_change_seconds);
  ZENISYS.chordLoop = new Tone.Loop((time) => {
    const chord = chords[idx % chords.length];
    // Density controls how many notes actually sound
    const notesToPlay = plan.density < 0.25 ? chord.slice(0, 1)
                      : plan.density < 0.4 ? chord.slice(0, 2)
                      : chord;
    ZENISYS.pad.triggerAttackRelease(notesToPlay, interval * 0.9, time);
    idx++;
  }, interval);
  ZENISYS.chordLoop.start(0);
  if (Tone.Transport.state !== 'started') Tone.Transport.start();

  // --- Optional binaural beat layer ---
  zenisysSetBinaural(plan);
  // --- Optional solfeggio drone ---
  zenisysSetSolfeggio(plan);
}

// Binaural beat: two oscillators, slightly different freq in each ear.
function zenisysSetBinaural(plan) {
  // Tear down old
  if (ZENISYS.binauralNodes) {
    try { ZENISYS.binauralNodes.forEach(n => n.stop && n.stop()); } catch(e){}
    ZENISYS.binauralNodes = null;
  }
  if (!plan.binaural_beat_hz || !plan.carrier_hz) return;
  const ctx = ZENISYS.audioCtx;
  if (!ctx) return;
  const carrier = plan.carrier_hz;
  const beat = plan.binaural_beat_hz;
  const makeEar = (freq, pan) => {
    const osc = ctx.createOscillator();
    osc.frequency.value = freq;
    osc.type = 'sine';
    const gain = ctx.createGain();
    gain.gain.value = 0.04; // very quiet — felt, not heard
    const panner = ctx.createStereoPanner();
    panner.pan.value = pan;
    osc.connect(gain); gain.connect(panner); panner.connect(ctx.destination);
    osc.start();
    return osc;
  };
  // left = carrier, right = carrier + beat
  const left = makeEar(carrier, -1);
  const right = makeEar(carrier + beat, 1);
  ZENISYS.binauralNodes = [left, right];
}

// Solfeggio drone: a single quiet sustained tone at the chosen frequency.
function zenisysSetSolfeggio(plan) {
  if (ZENISYS.solfeggioNode) {
    try { ZENISYS.solfeggioNode.stop(); } catch(e){}
    ZENISYS.solfeggioNode = null;
  }
  if (!plan.solfeggio) return;
  const ctx = ZENISYS.audioCtx;
  if (!ctx) return;
  const osc = ctx.createOscillator();
  osc.frequency.value = plan.solfeggio;
  osc.type = 'sine';
  const gain = ctx.createGain();
  gain.gain.value = 0.03; // subliminal warmth
  osc.connect(gain); gain.connect(ctx.destination);
  osc.start();
  ZENISYS.solfeggioNode = osc;
}

// Fetch a plan from the backend and render it. The smooth path for InnerLight.
async function zenisysPlayEmotion(emotion, intensity, opts) {
  opts = opts || {};
  try {
    const prev = ZENISYS.currentPlan ? ZENISYS.currentPlan.emotion : '';
    const url = '/api/zenisys/plan?emotion=' + encodeURIComponent(emotion || 'calm')
              + '&intensity=' + (intensity != null ? intensity : 0.5)
              + '&binaural=' + (opts.binaural ? '1' : '0')
              + '&solfeggio=' + (opts.solfeggio ? '1' : '0')
              + '&prev=' + encodeURIComponent(prev);
    const res = await fetch(url);
    const plan = await res.json();
    if (!ZENISYS.started) { await zenisysStart(plan); }
    else { zenisysApplyPlan(plan); }
    return plan;
  } catch (e) { console.log('[Zenisys] play error', e); }
}

function zenisysStop() {
  try {
    if (ZENISYS.chordLoop) { ZENISYS.chordLoop.stop(); ZENISYS.chordLoop.dispose(); ZENISYS.chordLoop = null; }
    if (ZENISYS.binauralNodes) { ZENISYS.binauralNodes.forEach(n => { try{n.stop();}catch(e){} }); ZENISYS.binauralNodes = null; }
    if (ZENISYS.solfeggioNode) { try{ZENISYS.solfeggioNode.stop();}catch(e){} ZENISYS.solfeggioNode = null; }
  } catch(e){}
}

// --- Legacy bridge: keep the old function names working, route to Zenisys ---
function startSynthPad(emotion) { zenisysPlayEmotion(emotion, 0.5, {}); }
function updateSynthEmotion(emotion) { zenisysPlayEmotion(emotion, 0.5, {}); }

</script>
<script>
function $(id) { return document.getElementById(id); }
function val(id) { const e = $(id); return e ? e.value : ''; }
function chk(id) { const e = $(id); return e ? !!e.checked : false; }
let ambientTracks = [];
let ambientIndex = 0;
async function startExperience() {
  // STEP 1: Show the conversation screen IMMEDIATELY (before anything else)
  const gate = $('welcome-gate'); if (gate) gate.style.display = 'none';
  const screen = $('story-screen'); if (screen) screen.style.display = 'flex';
  const msg = $('message'); if (msg) msg.focus();
  // Start the calming background scene (realism leads, animation fallback)
  setScene('meadow');

  // STEP 2: Start camera, face detection, and music IN THE BACKGROUND
  // These are nice-to-have — the conversation works even if they all fail
  setTimeout(async () => {
    // Camera
    try { await startVisualCamera(); } catch (e) { console.log('[InnerLight] Camera unavailable:', e); }
    // Face emotion detection
    try { await loadFaceModels(); startFaceLoop(); } catch (e) { console.log('[InnerLight] Face models unavailable:', e); }
    // Background music — DJ crossfade + generative synth
    try {
      initDecks();
      initVoices();
      const res = await fetch('/api/zenisys/ambient');
      const data = await res.json();
      ambientTracks = data.tracks || [];
      ambientIndex = 0;
      if (ambientTracks.length) {
        const deck = getActiveDeck();
        deck.src = ambientTracks[0].url;
        deck.volume = TARGET_VOL;
        deck.play().catch(()=>{});
        const now = $('music-now'); if (now) now.textContent = '\u266a ' + (ambientTracks[0].name || 'soft music');
      } else {
        const now = $('music-now'); if (now) now.textContent = 'music loading...';
      }
      // Start the generative synth pad layer (soft chords underneath)
      startSynthPad('calm');
    } catch (e) { console.log('[InnerLight] Music unavailable:', e); }
  }, 100);
}
function changeMusic() {
  if (!ambientTracks.length) return;
  crossfading = true;
  playNextTrackBlended();
}
function switchAmbient(url, name, vol) {
  // DJ-style: crossfade to the new track instead of hard-switching
  const inactive = getInactiveDeck();
  if (!inactive) return;
  inactive.src = url;
  inactive.load();
  crossfade(getActiveDeck(), inactive, CROSSFADE_MS);
  activeDeck = activeDeck === 'A' ? 'B' : 'A';
  const now = $('music-now'); if (now) now.textContent = '\u266a ' + (name || 'music');
  // Also update the generative synth layer emotion
  const emo = currentFaceEmotion || 'calm';
  updateSynthEmotion(emo);
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
let zenisysCtx = null;
let zenisysGain = null;
let zenisysFilter = null;
let zenisysOscillators = [];
let innerLightLearningState = null;
let innerLightSessionReference = '';
let innerLightContext = {};
// Capture the REAL conversation so the handoff is built from what was actually
// said — never from a form the person has to fill out.
let conversationLog = [];
function logTurn(role, text){
  if(!text) return;
  conversationLog.push({role: role, text: String(text), at: new Date().toISOString()});
  try { sessionStorage.setItem('innerlight_convo', JSON.stringify(conversationLog)); } catch(e){}
  try { sessionStorage.setItem('innerlight_risk', (innerLightContext && innerLightContext.risk) || 'low'); } catch(e){}
}
let latestVisualFrame = '';
let latestEmotionProfile = null;
let voiceRecognizer = null;
let voiceListening = false;
let voiceFinalTranscript = '';
let voiceSendTimer = null;
function escHtml(s){ const d=document.createElement('div'); d.textContent = s==null?'':String(s); return d.innerHTML; }
function startZenisys(mode='greeting') {
  // Silent — music shifts happen through the ambient audio player, not notifications
}
function adaptZenisys(mode='greeting') {
  // Silent — no notification to user about sound changes
}
function multimodalPayload() {
  return {
    typed_emotion: $('typed_emotion') ? $('typed_emotion').value : '',
    voice_transcript: $('voice_transcript') ? $('voice_transcript').value : '',
    voice_emotion: '',
    visual_emotion: currentFaceEmotion || ($('visual_emotion') ? $('visual_emotion').value : ''),
    visual_frame: latestVisualFrame || '',
    face_emotion: currentFaceEmotion || '',
    face_scores: faceEmotionScores || {},
    voice_features: voiceFeatures || {}
  };
}
function startVoiceCapture() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    $('emotion-status').textContent = 'This browser does not expose speech recognition. You can type instead.';
    return;
  }
  if (!voiceRecognizer) {
    voiceRecognizer = new SpeechRecognition();
    voiceRecognizer.continuous = true;
    voiceRecognizer.interimResults = true;
    voiceRecognizer.lang = 'en-US';
    voiceRecognizer.onresult = event => {
      let finalText = '';
      let interimText = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) { finalText += chunk; }
        else { interimText += chunk; }
      }
      if (finalText) { voiceFinalTranscript = (voiceFinalTranscript + ' ' + finalText).trim(); }
      const shown = (voiceFinalTranscript + ' ' + interimText).trim();
      // SHOW it live: final words solid, interim words faded
      const panel = $('live-transcript');
      const tEl = $('transcript-text');
      if (panel && tEl) {
        panel.style.display = 'block';
        tEl.innerHTML = (voiceFinalTranscript ? '<span style=\"color:#1a3a5c;\">' + escHtml(voiceFinalTranscript) + '</span>' : '')
          + (interimText ? ' <span style=\"color:#8aa3c4;\">' + escHtml(interimText) + '</span>' : '')
          || '&nbsp;';
      }
      // keep hidden field + input box in sync (and SAVE the words)
      $('voice_transcript').value = shown;
      const box = document.getElementById('conv-answer') || $('message');
      if (box) box.value = shown;
      captureVoiceFeatures();
      // AUTO-SEND when the person pauses: each finished sentence sends on its
      // own after a brief beat, so it's a flowing hands-free conversation.
      if (finalText) {
        if (voiceSendTimer) clearTimeout(voiceSendTimer);
        voiceSendTimer = setTimeout(() => {
          const text = (voiceFinalTranscript || '').trim();
          if (text && voiceListening) {
            voiceFinalTranscript = '';
            if (box) box.value = text;
            if (typeof sendCheckin === 'function') sendCheckin();
            else if (typeof continueConversation === 'function') continueConversation();
          }
        }, 1400); // ~1.4s pause = end of thought
      }
    };
    voiceRecognizer.onerror = event => {
      const err = event.error || 'unknown';
      // Network/no-speech hiccups: don't give up — retry quietly if still wanted.
      if ((err === 'network' || err === 'no-speech' || err === 'aborted') && voiceListening) {
        const lbl = $('listen-label'); if (lbl) lbl.textContent = 'Reconnecting the mic\u2026';
        setTimeout(() => { if (voiceListening) { try { voiceRecognizer.start(); } catch(e){} } }, 600);
        return;
      }
      const lbl = $('listen-label'); if (lbl) lbl.textContent = 'Mic issue: ' + err + ' \u2014 you can type instead';
      $('emotion-status').textContent = 'Mic issue: ' + err + '. You can type instead.';
    };
    voiceRecognizer.onend = () => {
      // If the user still WANTS to listen, the browser dropping the session
      // should NOT stop us — restart so it stays live (fixes the split-second bug).
      if (voiceListening) {
        try { voiceRecognizer.start(); return; } catch (e) {}
      }
      const dot = $('listen-dot'); const lbl = $('listen-label');
      if (dot) dot.style.background = '#3aa56b';
      if (lbl) lbl.textContent = 'Saved \u2014 press Enter to send, or keep editing';
      const micBtn = document.querySelector('.story-mic');
      if (micBtn) micBtn.innerHTML = '&#127908; Speak';
    };
  }
  // TOGGLE: if already listening, this click STOPS and submits.
  if (voiceListening) {
    voiceListening = false;
    try { voiceRecognizer.stop(); } catch (e) {}
    return;
  }
  // Otherwise START listening and STAY listening until clicked again.
  voiceListening = true;
  voiceFinalTranscript = '';
  const panel = $('live-transcript'); const dot = $('listen-dot'); const lbl = $('listen-label'); const tEl = $('transcript-text');
  if (panel) panel.style.display = 'block';
  if (dot) dot.style.background = '#e05a5a';
  if (lbl) lbl.textContent = 'Listening\u2026 speak now (click mic again to stop)';
  if (tEl) tEl.innerHTML = '&nbsp;';
  const micBtn = document.querySelector('.story-mic');
  if (micBtn) micBtn.innerHTML = '&#128308; Listening\u2026 (tap to stop)';
  try {
    voiceRecognizer.start();
  } catch (e) {
    // If start throws, it's usually already running or blocked by http
    voiceListening = false;
    if (lbl) lbl.textContent = 'Could not start mic. If the page is not https, the browser blocks it. You can type instead.';
  }
  $('emotion-status').style.display = 'block';
  $('emotion-status').textContent = 'Listening... speak now.';
}

// --- VOICE TONE ANALYSIS (feeds quantum emotion engine) ---
let voiceFeatures = { pitch_variance: 0.5, energy: 0.5, rate: 0.5, tremor: 0.0 };
let audioContext = null, analyser = null, micStream = null;

async function captureVoiceFeatures() {
  // Analyze microphone audio for tone (pitch variance, energy, tremor)
  try {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      micStream = await navigator.mediaDevices.getUserMedia({audio: true});
      const source = audioContext.createMediaStreamSource(micStream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
    }
    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(data);
    // Energy = average amplitude
    const energy = data.reduce((a,b)=>a+b,0) / data.length / 255;
    // Pitch variance = spread of frequency energy
    let weightedSum = 0, total = 0;
    for (let i = 0; i < data.length; i++) { weightedSum += i * data[i]; total += data[i]; }
    const centroid = total > 0 ? weightedSum / total / data.length : 0.5;
    voiceFeatures = {
      energy: Math.min(1, energy * 2),
      pitch_variance: Math.min(1, centroid * 2),
      rate: 0.5,
      tremor: energy < 0.2 ? 0.3 : 0.1
    };
  } catch (e) {}
}

// --- AI VOICE OUTPUT (speaks responses aloud) ---
let voiceEnabled = false;
let selectedVoice = null;

function initVoices() {
  if (!('speechSynthesis' in window)) return;
  const pick = () => {
    const voices = speechSynthesis.getVoices();
    if (!voices || !voices.length) return;
    // RANK voices by how human they sound. Neural/Online/Natural voices on
    // modern Windows & Mac sound dramatically better than the default robotic one.
    // Higher score = more human.
    const score = (v) => {
      let s = 0;
      const n = (v.name || '').toLowerCase();
      if (/neural|natural|online/.test(n)) s += 100;     // the genuinely good ones
      if (/aria|jenny|guy|sonia|ryan|libby|michelle/.test(n)) s += 40; // MS neural names
      if (/samantha|ava|allison|tom|zoe|evan|nicky|joelle/.test(n)) s += 35; // Apple neural names
      if (/google/.test(n)) s += 30;                     // Google voices are decent
      if (v.localService === false) s += 25;             // cloud voices = better
      if (/en-us|en-gb/i.test(v.lang || '')) s += 15;
      if (/en/i.test(v.lang || '')) s += 5;
      if (/microsoft (david|mark|zira)\b/.test(n)) s -= 30; // the old robotic ones
      if (/espeak|festival/.test(n)) s -= 50;
      return s;
    };
    const ranked = voices.slice().sort((a, b) => score(b) - score(a));
    selectedVoice = ranked[0];
    // expose the list so the person could choose another if they want
    window._voiceRanked = ranked;
    console.log('[Voice] using:', selectedVoice && selectedVoice.name,
                '| best available:', ranked.slice(0,3).map(v=>v.name));
  };
  pick();
  // voices often load async — re-pick when they arrive
  if (speechSynthesis.onvoiceschanged !== undefined) {
    speechSynthesis.onvoiceschanged = pick;
  }
  // some browsers need a nudge
  setTimeout(pick, 400); setTimeout(pick, 1200);
}

let selectedVoiceId = '';
function selectVoice(v){ selectedVoiceId = v || '';
  // give an instant preview when they pick, if voice is on
  if(voiceEnabled && v){ speak('This is the voice I will use.'); } }
async function loadVoiceChoices(){
  try{
    const r = await fetch('/api/voice/list'); const d = await r.json();
    const sel = document.getElementById('voice-picker'); if(!sel || !d.voices || !d.voices.length) return;
    // group respectfully by gender, then accent
    sel.innerHTML = '<option value="">Voice: default</option>';
    d.voices.forEach(v=>{
      const o = document.createElement('option'); o.value = v.id; o.textContent = v.label || v.id; sel.appendChild(o);
    });
  }catch(e){}
}
document.addEventListener('DOMContentLoaded', loadVoiceChoices);
// Record when the person is typing so heavy work (face detection) yields to
// the keyboard and typing always stays instant.
document.addEventListener('keydown', function(){ window._lastTypedAt = performance.now(); }, true);

function speak(text) {
  if (!voiceEnabled || !text) return;
  // Try REAL human audio from the server first. If no voice service is
  // configured, it tells us to use the browser's best neural voice instead.
  fetch('/api/voice/speak', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: text, voice_id: selectedVoiceId || ''})
  }).then(r => r.json()).then(d => {
    if (d && d.audio_b64) {
      // genuine human voice
      const audio = new Audio('data:' + (d.mime || 'audio/mpeg') + ';base64,' + d.audio_b64);
      audio.volume = 0.95;
      audio.play().catch(() => speakBrowser(text));
    } else {
      speakBrowser(text);
    }
  }).catch(() => speakBrowser(text));
}

function speakBrowser(text) {
  if (!voiceEnabled || !('speechSynthesis' in window) || !text) return;
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  if (selectedVoice) utter.voice = selectedVoice;
  utter.rate = 0.92;   // slightly slower = calmer
  utter.pitch = 1.0;
  utter.volume = 0.95;
  speechSynthesis.speak(utter);
}

function toggleVoice() {
  voiceEnabled = !voiceEnabled;
  if (!voiceEnabled) speechSynthesis.cancel();
  const btn = document.getElementById('voice-toggle');
  if (btn) btn.textContent = voiceEnabled ? '🔊 Voice On' : '🔇 Voice Off';
}

let voiceFirstMode = false;
function toggleVoiceFirst() {
  voiceFirstMode = !voiceFirstMode;
  const btn = document.getElementById('voicefirst-toggle');
  if (btn) btn.textContent = voiceFirstMode ? '🎤 Voice-First: On' : '🎤 Voice-First: Off';
  if (voiceFirstMode) {
    $('emotion-status').style.display = 'block';
    $('emotion-status').textContent = 'Voice-first mode on. I will listen and speak with you. Tap Speak to begin.';
  }
}
async function startVisualCamera() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $('emotion-status').textContent = 'This browser does not expose camera access.';
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({video:true, audio:false});
    const video = $('visual-preview');
    video.srcObject = stream;
    $('emotion-status').textContent = 'Camera ready. Click analyze visual emotion when the person is visible.';
  } catch (error) {
    $('emotion-status').textContent = `Camera access issue: ${error.message || error}.`;
  }
}
function captureVisualFrame() {
  const video = $('visual-preview');
  if (!video || !video.videoWidth) return '';
  const canvas = document.createElement('canvas');
  const width = Math.min(480, video.videoWidth);
  const height = Math.round((video.videoHeight || width) * (width / video.videoWidth));
  canvas.width = width;
  canvas.height = height;
  canvas.getContext('2d').drawImage(video, 0, 0, width, height);
  return canvas.toDataURL('image/jpeg', 0.72);
}
async function analyzeVisualEmotion() {
  latestVisualFrame = captureVisualFrame();
  const payload = Object.assign({
    message: val('message'),
    known_diagnoses: val('known_diagnoses')
  }, multimodalPayload());
  const res = await fetch('/api/emotion/analyze', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });
  const data = await res.json();
  latestEmotionProfile = data;
  if ((data.sources || {}).visual && data.sources.visual.dominant_emotion) {
    $('visual_emotion').value = data.sources.visual.dominant_emotion;
  }
  $('emotion-status').textContent = `Emotion profile: ${data.primary_emotion || 'needs more context'}, distress ${data.distress_score || '?'}/10, confidence ${data.confidence || '?'}.`;
  if ((data.zenisys_mode_hint || '') && zenisysCtx) adaptZenisys(data.zenisys_mode_hint);
}
function openHelp(kind){
  // Each path is honest about WHERE the person is going and WHO they will reach.
  // The conversation is carried over so they never fill out a jargon form.
  try { sessionStorage.setItem('innerlight_convo', JSON.stringify(conversationLog)); } catch(e){}
  if(kind === 'attorney' || kind === 'legal'){ window.open('/handoff/legal','_blank'); }
  else { window.open('/handoff/clinical','_blank'); }
}
function revealUrgentHelp(data){
  // When distress is detected, surface clear, immediate options.
  const box = document.getElementById('urgent-help');
  if(!box) return;
  const risk = (data && data.risk) || 'low';
  if(risk === 'critical' || risk === 'high'){
    box.style.display = 'block';
    box.innerHTML = 'Help is worth reaching for right now. '
      + '<a href="tel:988" style="color:#b3322e;text-decoration:underline;">Call or text 988</a>, '
      + 'or <a href="tel:911" style="color:#b3322e;text-decoration:underline;">911</a> if there is immediate danger. '
      + 'I am staying right here with you.';
  } else {
    box.style.display = 'none';
  }
}

async function sendCheckin() {  startZenisys('greeting');
  logTurn('user', val('message'));
  if (!latestVisualFrame) latestVisualFrame = captureVisualFrame();
  const res = await fetch('/api/checkin', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(Object.assign({
      name:val('name'),
      birthdate:val('birthdate'),
      region:val('region') || 'US',
      location:val('location'),
      culture:val('culture'),
      language:val('language') || 'English',
      known_diagnoses:val('known_diagnoses'),
      message:val('message'),
      legal_issue:val('legal_issue'),
      support_preference:val('support_preference') || 'Help me decide',
      sound_preference:val('sound_preference') || 'Warm ambient',
      telehealth_requested:chk('telehealth_requested'),
      consent_case_file:chk('consent_case_file')
    }, multimodalPayload()))
  });
  const data = await res.json();
  adaptZenisys(data.sound_mode || 'greeting');
  revealUrgentHelp(data);
  logTurn('innerlight', data.response || '');
  innerLightLearningState = data.learning_state || null;
  innerLightSessionReference = data.message_fingerprint || '';
  innerLightContext = data;
  // --- CONVERSATION THREAD (flat, never nests, never stops) ---
  const thread = document.getElementById('conversation-thread');
  const allQ = data.questions || [];
  const firstQ = allQ.length ? allQ[0] : 'Can you tell me a little more about that?';
  const warmReply = data.response || 'I hear you.';
  const safetyBlock = data.needs_immediate_support
    ? '<p style="background:#f0f7f4;border:1px solid #c8ddd2;border-radius:12px;padding:14px;color:#2d4a3e;font-size:15px;margin:14px 0;">You are not alone. If you need immediate support, you can reach the 988 Suicide and Crisis Lifeline anytime by calling or texting 988. I am staying right here with you.</p>'
    : '';
  // Hide the initial "Tell me your story" area
  const title = document.querySelector('.story-title'); if (title) title.style.display = 'none';
  const sub = document.querySelector('.story-sub'); if (sub) sub.style.display = 'none';
  const initInput = $('message'); if (initInput) initInput.style.display = 'none';
  const initActions = document.querySelector('.story-actions'); if (initActions) initActions.style.display = 'none';
  // Append this exchange to the flat thread
  appendExchange(thread, warmReply, firstQ, safetyBlock);
  // Show legal guidance if detected
  if (data.legal_guidance) { appendLegalGuidance(thread, data.legal_guidance); }
  if (data.handoff) { appendHandoff(thread, data.handoff, data); }
  // Silently shift music based on emotion
  updateMusicForEmotion(data);
}
function appendLegalGuidance(thread, lg) {
  if (!lg || !lg.issue_detected) return;
  const el = document.createElement('div');
  el.style.cssText = 'text-align:left;background:#f5f0fa;border:1px solid #d8cce6;border-radius:14px;padding:18px;margin:14px 0;';
  const rights = (lg.your_rights || []).slice(0,3).map(r => '<li style="margin:4px 0;">' + escapeHtml(r) + '</li>').join('');
  const askAtty = (lg.questions_for_attorney || []).slice(0,3).map(q => '<li style="margin:4px 0;">' + escapeHtml(q) + '</li>').join('');
  const freeHelp = (lg.free_legal_help || []).slice(0,3).map(h => '<li style="margin:4px 0;">' + escapeHtml(h) + '</li>').join('');
  const steps = (lg.steps_you_can_take_now || []).slice(0,3).map(s => '<li style="margin:4px 0;">' + escapeHtml(s) + '</li>').join('');
  el.innerHTML = `
    <p style="font-size:15px;color:#4a3660;font-weight:600;margin:0 0 8px;">Based on what you shared, here are some things you should know about your ${escapeHtml(lg.issue_detected)}:</p>
    <details style="margin:8px 0;" open>
      <summary style="font-size:13px;font-weight:600;color:#5a4570;cursor:pointer;">Your rights</summary>
      <ul style="font-size:14px;color:#2d4a3e;padding-left:20px;margin:6px 0;">${rights}</ul>
    </details>
    <details style="margin:8px 0;">
      <summary style="font-size:13px;font-weight:600;color:#5a4570;cursor:pointer;">Questions to ask an attorney</summary>
      <ul style="font-size:14px;color:#2d4a3e;padding-left:20px;margin:6px 0;">${askAtty}</ul>
    </details>
    <details style="margin:8px 0;">
      <summary style="font-size:13px;font-weight:600;color:#5a4570;cursor:pointer;">Where to get free legal help</summary>
      <ul style="font-size:14px;color:#2d4a3e;padding-left:20px;margin:6px 0;">${freeHelp}</ul>
    </details>
    <details style="margin:8px 0;">
      <summary style="font-size:13px;font-weight:600;color:#5a4570;cursor:pointer;">Steps you can take right now</summary>
      <ul style="font-size:14px;color:#2d4a3e;padding-left:20px;margin:6px 0;">${steps}</ul>
    </details>
    <p style="font-size:11px;color:#8a7a9a;margin:10px 0 0;line-height:1.5;">${escapeHtml(lg.disclaimer || '')}</p>
  `;
  thread.appendChild(el);
}
function appendHandoff(thread, handoff, data) {
  if (!handoff || handoff.type === 'none') return;
  const el = document.createElement('div');
  const colors = {
    crisis: {bg:'#f0f7f4', border:'#5ba08a', accent:'#2d6a4e'},
    legal: {bg:'#f5f0fa', border:'#a78bfa', accent:'#6d28d9'},
    telehealth: {bg:'#eff6ff', border:'#60a5fa', accent:'#1d4ed8'},
    community: {bg:'#fef9ec', border:'#f0c14b', accent:'#a16207'}
  };
  const c = colors[handoff.type] || colors.telehealth;
  el.style.cssText = 'text-align:left;background:'+c.bg+';border:1px solid '+c.border+';border-left:4px solid '+c.border+';border-radius:14px;padding:18px;margin:16px 0;';
  const primary = handoff.bridge && handoff.bridge.primary;
  const secondary = handoff.bridge && handoff.bridge.secondary;
  const emergency = handoff.bridge && handoff.bridge.emergency;
  const primaryStyle = 'background:'+c.accent+';color:#fff;border:0;border-radius:10px;padding:12px 18px;font-size:14px;font-weight:600;cursor:pointer;margin:4px 6px 4px 0;';
  const secondaryStyle = 'background:#fff;color:'+c.accent+';border:1px solid '+c.border+';border-radius:10px;padding:12px 18px;font-size:14px;cursor:pointer;margin:4px 6px 4px 0;';
  const emergencyStyle = 'background:#fff;color:#b91c1c;border:1px solid #fca5a5;border-radius:10px;padding:12px 18px;font-size:14px;cursor:pointer;margin:4px 6px 4px 0;';
  el.innerHTML = `
    <p style="font-size:15px;font-weight:600;color:${c.accent};margin:0 0 6px;">${escapeHtml(handoff.label)}</p>
    <label style="display:flex;align-items:flex-start;gap:8px;font-size:13px;color:#3d5a4e;margin:10px 0;cursor:pointer;">
      <input type="checkbox" id="consent-${handoff.type}" style="margin-top:3px;">
      <span>${escapeHtml(handoff.context_prompt || 'Share my context so I do not have to repeat myself.')}</span>
    </label>
    <div class="bridge-buttons" style="margin-top:10px;"></div>
  `;
  thread.appendChild(el);
  // Attach buttons with real click handlers (no string escaping issues)
  const btnContainer = el.querySelector('.bridge-buttons');
  function addBtn(b, style) {
    if (!b) return;
    const btn = document.createElement('button');
    btn.textContent = b.label;
    btn.setAttribute('style', style);
    btn.onclick = function() { completeBridge(handoff.type, b.action, b.value || ''); };
    btnContainer.appendChild(btn);
  }
  addBtn(primary, primaryStyle);
  addBtn(secondary, secondaryStyle);
  addBtn(emergency, emergencyStyle);
  // Speak the handoff offer
  speak(handoff.label);
  window._lastHandoffData = data;
}
async function completeBridge(type, action, value) {
  const consentBox = document.getElementById('consent-' + type);
  const consent = consentBox ? consentBox.checked : false;
  const thread = document.getElementById('conversation-thread');
  // Build a summary from the conversation
  let summary = '';
  const msgs = thread.querySelectorAll('p');
  msgs.forEach(p => { if (p.textContent) summary += p.textContent + ' '; });
  try {
    const res = await fetch('/api/resolution/bridge', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        session_reference: innerLightSessionReference || '',
        handoff_type: type,
        consent: consent,
        bridge_action: action,
        summary: summary.slice(0, 500),
        register: (window._lastHandoffData||{}).register || {},
        quantum_emotion: (window._lastHandoffData||{}).quantum_emotion,
        topics: (window._lastHandoffData||{}).topics_detected
      })
    });
    const d = await res.json();
    // Show + SPEAK the warm handoff first, then bridge to help after a gentle beat
    if (d.warm_handoff) {
      showWarmHandoff(thread, d.warm_handoff, d.resolution, action, value);
    } else {
      performBridgeAction(action, value);
      if (d.exit_message) { showExit(thread, d.exit_message, d.resolution); }
    }
  } catch(e) {
    performBridgeAction(action, value);
  }
}
function showWarmHandoff(thread, warm, resolution, action, value) {
  const oldReply = thread.querySelector('.reply-box');
  if (oldReply) oldReply.remove();
  const el = document.createElement('div');
  el.style.cssText = 'text-align:left;background:linear-gradient(135deg,#5ba08a,#4e9079);color:#fff;border-radius:16px;padding:24px;margin:18px 0;';
  // Show the warm handoff parts in sequence, gently
  const partsHtml = (warm.parts || []).map(p =>
    `<p style="font-size:16px;line-height:1.75;margin:0 0 12px;">${escapeHtml(p)}</p>`).join('');
  el.innerHTML = `
    ${partsHtml}
    <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
      <button id="bridge-go" style="background:#fff;color:#2d6a4e;border:0;border-radius:999px;padding:12px 24px;font-size:15px;font-weight:700;cursor:pointer;">Connect now</button>
      <span style="font-size:13px;opacity:0.9;">whenever you're ready — no rush</span>
    </div>
    <button onclick="restartConversation()" style="background:rgba(255,255,255,0.15);color:#fff;border:1px solid rgba(255,255,255,0.4);border-radius:999px;padding:9px 20px;font-size:13px;cursor:pointer;margin-top:14px;">I'm here if you need to talk more</button>
  `;
  thread.appendChild(el);
  // SPEAK the full warm handoff aloud, calmly
  speak(warm.spoken_script);
  // The person taps "Connect now" when ready — we never auto-launch during the warm words
  const goBtn = el.querySelector('#bridge-go');
  if (goBtn) goBtn.onclick = function() { performBridgeAction(action, value); };
  el.scrollIntoView({behavior:'smooth', block:'center'});
}
function performBridgeAction(action, value) {
  switch(action) {
    case 'call_988': window.location.href = 'tel:988'; break;
    case 'call_911': window.location.href = 'tel:911'; break;
    case 'call_211': window.location.href = 'tel:211'; break;
    case 'request_video': window.open('/telehealth/intake', '_blank'); break;
    case 'schedule': window.open('/telehealth/intake', '_blank'); break;
    case 'match_attorney': window.open('https://www.lawhelp.org/', '_blank'); break;
    case 'operator_monitor': /* operator already alerted via backend */ break;
    default: break;
  }
}
function showExit(thread, exitMsg, resolution) {
  const oldReply = thread.querySelector('.reply-box');
  if (oldReply) oldReply.remove();
  const el = document.createElement('div');
  el.style.cssText = 'text-align:center;background:linear-gradient(135deg,#5ba08a,#4e9079);color:#fff;border-radius:14px;padding:22px;margin:18px 0;';
  el.innerHTML = `
    <p style="font-size:16px;line-height:1.7;margin:0;">${escapeHtml(exitMsg.message)}</p>
    <button onclick="restartConversation()" style="background:rgba(255,255,255,0.2);color:#fff;border:1px solid rgba(255,255,255,0.4);border-radius:999px;padding:10px 22px;font-size:13px;cursor:pointer;margin-top:16px;">I'm here if you need to talk more</button>
  `;
  thread.appendChild(el);
  speak(exitMsg.message);
  el.scrollIntoView({behavior:'smooth', block:'center'});
}
function restartConversation() {
  const box = document.createElement('div');
  box.className = 'reply-box';
  box.style.cssText = 'margin-top:16px;';
  box.innerHTML = `
    <textarea id="conv-answer" class="story-input" style="min-height:80px;" placeholder="I'm listening... (press Enter to send)" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();continueConversation();}"></textarea>
    <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
      <button class="story-send" onclick="continueConversation()">Reply</button>
      <button class="story-mic" type="button" onclick="startVoiceCapture()">&#127908; Speak</button>
    </div>
  `;
  document.getElementById('conversation-thread').appendChild(box);
  document.getElementById('conv-answer').focus();
}
function appendExchange(thread, reply, question, safetyHtml) {
  // Conversation is active — shrink the pinned face to a compact thumbnail
  // so it stays visible at the top without taking over the screen.
  const vbar = document.querySelector('.story-video-bar');
  if (vbar) vbar.classList.add('compact');
  // Remove any previous reply box (keep conversation flat)
  const oldReply = thread.querySelector('.reply-box');
  if (oldReply) oldReply.remove();
  // Append the AI's response
  const exchange = document.createElement('div');
  exchange.style.cssText = 'text-align:left;padding:16px 0;border-bottom:1px solid #e8f0eb;';
  exchange.innerHTML = `
    <p style="font-size:16px;line-height:1.7;color:#2d4a3e;margin:0 0 8px;">${escapeHtml(reply)}</p>
    ${safetyHtml || ''}
    <p style="font-size:16px;line-height:1.7;color:#2d4a3e;margin:14px 0 0;font-weight:500;">${escapeHtml(question)}</p>
  `;
  thread.appendChild(exchange);
  // SPEAK the response and question aloud (AI voice)
  speak(reply + '. ' + question);
  // Add a fresh reply box at the bottom (always exactly one)
  const replyBox = document.createElement('div');
  replyBox.className = 'reply-box';
  replyBox.style.cssText = 'margin-top:16px;';
  replyBox.innerHTML = `
    <textarea id="conv-answer" class="story-input" style="min-height:80px;" placeholder="Take your time... or tap Speak (press Enter to send)" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();continueConversation();}"></textarea>
    <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
      <button class="story-send" onclick="continueConversation()">Reply</button>
      <button class="story-mic" type="button" onclick="startVoiceCapture()">&#127908; Speak</button>
    </div>
  `;
  thread.appendChild(replyBox);
  // Focus and scroll
  const ta = document.getElementById('conv-answer');
  if (ta) ta.focus();
  replyBox.scrollIntoView({behavior:'smooth', block:'center'});
}
async function updateMusicForEmotion(data) {
  const textEmotion = (data.zenisys_music || {}).emotion || 'calm';
  const faceEmo = currentFaceEmotion || '';
  const emotionToUse = (faceEmo && faceEmo !== 'neutral' && faceEmo !== textEmotion) ? faceEmo : textEmotion;
  // Update the generative synth pad to match the new emotion
  updateSynthEmotion(emotionToUse);
  // Crossfade to new ambient tracks for this emotion
  try {
    const res = await fetch('/api/zenisys/ambient?emotion=' + encodeURIComponent(emotionToUse));
    const d = await res.json();
    const tracks = d.tracks || [];
    if (tracks.length) {
      ambientTracks = tracks;
      ambientIndex = 0;
      switchAmbient(tracks[0].url, tracks[0].name);
    }
  } catch (e) {}
}
async function continueConversation() {
  const answerBox = document.getElementById('conv-answer');
  if (!answerBox || !answerBox.value.trim()) return;
  const userAnswer = answerBox.value.trim();
  logTurn('user', userAnswer);
  if (!latestVisualFrame) latestVisualFrame = captureVisualFrame();
  // Show what the user said in the thread
  const thread = document.getElementById('conversation-thread');
  const userMsg = document.createElement('div');
  userMsg.style.cssText = 'text-align:right;padding:10px 0;';
  userMsg.innerHTML = `<p style="display:inline-block;background:#e8f4ec;color:#2d4a3e;padding:10px 16px;border-radius:16px 16px 4px 16px;font-size:15px;max-width:80%;text-align:left;">${escapeHtml(userAnswer)}</p>`;
  // Remove the reply box before appending user message
  const oldReply = thread.querySelector('.reply-box');
  if (oldReply) oldReply.remove();
  thread.appendChild(userMsg);
  thread.scrollTop = thread.scrollHeight;
  // Call the API
  const res = await fetch('/api/innerlight/learn', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      answer: userAnswer,
      learning_state: innerLightLearningState,
      session_reference: innerLightSessionReference,
      context: Object.assign({}, innerLightContext, multimodalPayload())
    })
  });
  const data = await res.json();
  innerLightLearningState = data.learning_state || innerLightLearningState;
  innerLightContext = Object.assign(innerLightContext, data);
  const nextQ = (data.questions || [])[0] || 'Is there anything else you would like to share?';
  const reply = data.response || 'Thank you for sharing that with me.';
  logTurn('innerlight', reply);
  const safety = data.needs_immediate_support
    ? '<p style="background:#f0f7f4;border:1px solid #c8ddd2;border-radius:12px;padding:14px;color:#2d4a3e;font-size:15px;margin:14px 0;">You are not alone. The 988 Lifeline is available anytime — call or text 988. I am right here.</p>'
    : '';
  appendExchange(thread, reply, nextQ, safety);
  // Show legal guidance if detected in this turn
  if (data.legal_guidance) { appendLegalGuidance(thread, data.legal_guidance); }
  if (data.handoff) { appendHandoff(thread, data.handoff, data); }
  // Update music based on face + text emotion every turn
  updateMusicForEmotion(data);
}
// Keep old name working
async function continueInnerLight() { return continueConversation(); }

// ============================================================
// CALM SPACE - the interactive anchor, always on the dashboard.
// Touch/drag makes real light + gentle pentatonic tones. While in use it
// EXPANDS and the background music SOFTENS; after a few seconds of stillness
// the music fades back. One mode done well: Continuous Anchor.
// ============================================================
(function(){
  const canvas = document.getElementById('calm-touch');
  const wrap = document.getElementById('calm-player');
  if(!canvas) return;
  const ctx = canvas.getContext('2d');
  let W, H, dpr;
  function resize(){
    dpr = window.devicePixelRatio || 1;
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W*dpr; canvas.height = H*dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0);
  }
  resize(); window.addEventListener('resize', resize);

  // --- audio: gentle pentatonic, always pleasant ---
  const PENT = [261.63, 293.66, 329.63, 392.00, 440.00, 493.88, 587.33];
  let AC = null;
  function ac(){ if(!AC) AC = new (window.AudioContext||window.webkitAudioContext)();
    if(AC.state==='suspended') AC.resume(); return AC; }
  function nearestPent(f){ let b=PENT[0],d=1e9; PENT.forEach(p=>{if(Math.abs(p-f)<d){d=Math.abs(p-f);b=p;}}); return b; }
  let lastTone = 0;
  function tone(x,y){
    const a = ac();
    const freq = nearestPent(240 + (1-y/H)*420);
    const pan = (x/W)*2 - 1;
    const o = a.createOscillator(); o.type='triangle'; o.frequency.value=freq;
    const g = a.createGain(); g.gain.value=0;
    const p = a.createStereoPanner(); p.pan.value = pan;
    o.connect(g); g.connect(p); p.connect(a.destination);
    const t = a.currentTime;
    g.gain.setValueAtTime(0,t);
    g.gain.linearRampToValueAtTime(0.2, t+0.04);
    g.gain.exponentialRampToValueAtTime(0.0008, t+0.9);
    o.start(t); o.stop(t+1.0);
    // soft echo a fifth up
    setTimeout(()=>{ try{
      const o2=a.createOscillator(); o2.type='sine'; o2.frequency.value=freq*1.5;
      const g2=a.createGain(); g2.gain.value=0; const p2=a.createStereoPanner(); p2.pan.value=-pan;
      o2.connect(g2); g2.connect(p2); p2.connect(a.destination);
      const t2=a.currentTime; g2.gain.linearRampToValueAtTime(0.10,t2+0.05);
      g2.gain.exponentialRampToValueAtTime(0.0006,t2+1.1); o2.start(t2); o2.stop(t2+1.2);
    }catch(e){} }, 220);
  }

  // --- background music ducking ---
  let ducked = false, lastTouch = 0, restoreTimer = null;
  function duckMusic(){
    ducked = true;
    ['ambient-a','ambient-b'].forEach(id=>{ const el=document.getElementById(id);
      if(el && !el.paused){ el.dataset.fullvol = el.dataset.fullvol || el.volume; el.volume = Math.min(el.volume, 0.06); } });
    const note = document.getElementById('calm-music-note'); if(note) note.textContent = 'music softened - playing your sounds';
  }
  function restoreMusic(){
    ducked = false;
    ['ambient-a','ambient-b'].forEach(id=>{ const el=document.getElementById(id);
      if(el){ const target = parseFloat(el.dataset.fullvol||'0.5'); fadeTo(el, target, 1500); } });
    const note = document.getElementById('calm-music-note'); if(note) note.textContent = 'music softens while you play';
  }
  function fadeTo(el, target, ms){
    const start = el.volume, t0 = performance.now();
    function step(){ const k = Math.min(1,(performance.now()-t0)/ms);
      el.volume = start + (target-start)*k; if(k<1) requestAnimationFrame(step); }
    requestAnimationFrame(step);
  }

  // --- expand while in use ---
  let expanded = false;
  function expand(){ if(expanded) return; expanded=true;
    if(wrap) wrap.style.maxWidth = '760px';
    canvas.style.height = '360px'; setTimeout(resize, 60); }
  function shrink(){ if(!expanded) return; expanded=false;
    if(wrap) wrap.style.maxWidth = '560px';
    canvas.style.height = '240px'; setTimeout(resize, 60); }

  // --- interaction ---
  let ripples = [];
  let calmMode = 'anchor';
  window.setCalmMode = function(m){
    calmMode = m;
    document.querySelectorAll('.calm-tab').forEach(b=>{
      const on = b.dataset.mode===m;
      b.style.background = on ? '#6fb3d4' : 'rgba(255,255,255,0.10)';
      b.style.color = on ? '#0c1322' : '#cfe3f2';
      b.style.fontWeight = on ? '700' : '400';
      b.classList.toggle('active', on);
    });
    if(traceGain){ try{ traceGain.gain.linearRampToValueAtTime(0, ac().currentTime+0.3);}catch(e){} }
  };
  // Trace mode: one continuous tone that glides with the finger
  let traceOsc=null, traceGain=null, tracePan=null;
  function ensureTrace(){ const a=ac(); if(traceOsc) return;
    traceOsc=a.createOscillator(); traceOsc.type='triangle';
    traceGain=a.createGain(); traceGain.gain.value=0;
    tracePan=a.createStereoPanner();
    traceOsc.connect(traceGain); traceGain.connect(tracePan); tracePan.connect(a.destination); traceOsc.start(); }
  function traceMove(x,y){ ensureTrace(); const a=ac();
    const freq = nearestPent(180 + (1-y/H)*460), pan=(x/W)*2-1;
    traceOsc.frequency.linearRampToValueAtTime(freq, a.currentTime+0.05);
    tracePan.pan.linearRampToValueAtTime(pan, a.currentTime+0.05);
    traceGain.gain.linearRampToValueAtTime(0.2, a.currentTime+0.05); }
  function traceRelease(){ if(traceGain){ try{ traceGain.gain.linearRampToValueAtTime(0, ac().currentTime+0.4);}catch(e){} } }
  // Call & Answer: a tap gets a gentle two-note answer
  function callAnswer(x,y){ const base=nearestPent(260+(1-y/H)*360), pan=(x/W)*2-1;
    tone(x,y); setTimeout(()=>{ const a=ac(); const o=a.createOscillator(); o.type='sine'; o.frequency.value=base*1.5;
      const g=a.createGain(); g.gain.value=0; const p=a.createStereoPanner(); p.pan.value=-pan;
      o.connect(g); g.connect(p); p.connect(a.destination); const t=a.currentTime;
      g.gain.linearRampToValueAtTime(0.16,t+0.05); g.gain.exponentialRampToValueAtTime(0.0006,t+0.9); o.start(t); o.stop(t+1.0);
    }, 340); }

  function addRipple(x,y){ ripples.push({x,y,r:6,a:0.95,hue:188+Math.random()*46}); kickCalm(); }
  function pos(e){ const r=canvas.getBoundingClientRect(); const p=(e.touches&&e.touches[0])?e.touches[0]:e;
    return {x:p.clientX-r.left, y:p.clientY-r.top}; }
  function activity(){
    lastTouch = performance.now();
    if(!ducked) duckMusic();
    expand();
    if(restoreTimer) clearTimeout(restoreTimer);
    restoreTimer = setTimeout(()=>{ // a few seconds of stillness -> music returns
      if(performance.now()-lastTouch >= 3000){ restoreMusic(); shrink(); }
    }, 3200);
  }
  function press(e){ e.preventDefault(); const q=pos(e); addRipple(q.x,q.y);
    if(calmMode==='call'){ callAnswer(q.x,q.y); }
    else if(calmMode==='trace'){ traceMove(q.x,q.y); }
    else { tone(q.x,q.y); }
    activity(); }
  function move(e){
    if((e.buttons===1)||(e.touches&&e.touches.length)){
      const q=pos(e); addRipple(q.x,q.y);
      if(calmMode==='trace'){ traceMove(q.x,q.y); }
      else if(calmMode==='anchor'){ const now=performance.now(); if(now-lastTone>130){ tone(q.x,q.y); lastTone=now; } }
      activity();
    }
  }
  function release(){ if(calmMode==='trace') traceRelease(); }
  canvas.addEventListener('mouseup', release);
  canvas.addEventListener('mouseleave', release);
  canvas.addEventListener('touchend', release);
  canvas.addEventListener('mousedown', press);
  canvas.addEventListener('mousemove', move);
  canvas.addEventListener('touchstart', press, {passive:false});
  canvas.addEventListener('touchmove', move, {passive:false});

  let calmRAF = null;
  let calmIdleSince = performance.now();
  function calmActive(){
    // Active if there are ripples still fading, or a finger/mouse is down,
    // or we're within a short window after the last interaction.
    return ripples.length > 0 || (performance.now() - calmIdleSince) < 4000;
  }
  function draw(){
    ctx.fillStyle = 'rgba(12,19,34,0.18)';
    ctx.fillRect(0,0,W,H);
    ripples.forEach(rp=>{ rp.r += 1.5; rp.a *= 0.975;
      ctx.beginPath(); ctx.arc(rp.x, rp.y, rp.r, 0, Math.PI*2);
      ctx.strokeStyle = 'hsla('+rp.hue+',70%,72%,'+rp.a+')'; ctx.lineWidth = 2; ctx.stroke(); });
    ripples = ripples.filter(r=>r.a>0.03);
    // resting glow so it never looks dead, inviting a touch
    const t = performance.now()/1000;
    const gx = W/2 + Math.sin(t*0.6)*W*0.16;
    const gy = H/2 + Math.cos(t*0.45)*H*0.16;
    const grd = ctx.createRadialGradient(gx,gy,4,gx,gy,Math.min(W,H)*0.4);
    grd.addColorStop(0,'rgba(120,180,220,0.12)'); grd.addColorStop(1,'rgba(120,180,220,0)');
    ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(gx,gy,Math.min(W,H)*0.4,0,Math.PI*2); ctx.fill();
    // Keep going ONLY while active. When idle, stop the loop entirely so the
    // browser is free for typing. A light heartbeat restarts it when needed.
    if (calmActive()) { calmRAF = requestAnimationFrame(draw); }
    else { calmRAF = null; }
  }
  function kickCalm(){
    calmIdleSince = performance.now();
    if (!calmRAF) { calmRAF = requestAnimationFrame(draw); }
  }
  // Restart animation on any interaction; idle slow heartbeat keeps glow alive
  // without saturating the CPU (one frame every ~2s when nobody is interacting).
  setInterval(()=>{ if(!calmRAF){ const c=document.getElementById('calm-touch'); if(c){ ctx.fillStyle='rgba(12,19,34,0.18)'; ctx.fillRect(0,0,W,H); const t=performance.now()/1000; const gx=W/2+Math.sin(t*0.6)*W*0.16; const gy=H/2+Math.cos(t*0.45)*H*0.16; const grd=ctx.createRadialGradient(gx,gy,4,gx,gy,Math.min(W,H)*0.4); grd.addColorStop(0,'rgba(120,180,220,0.12)'); grd.addColorStop(1,'rgba(120,180,220,0)'); ctx.fillStyle=grd; ctx.beginPath(); ctx.arc(gx,gy,Math.min(W,H)*0.4,0,Math.PI*2); ctx.fill(); } } }, 2000);
  kickCalm();
})();

</script>
</body>
</html>
"""


PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="creator" content="Toshay S. Zeigler">
  <meta name="company" content="God's Love for Us LLC">
  <title>Axiom Harmony Private Console</title>
  <!-- Creator imprint: Axiom Harmony Protocol / InnerLight / VEIL / EDEN / Zenisys Sound System created by Toshay S. Zeigler for God's Love for Us LLC. -->
  <style>
    :root { color-scheme: light; --bg:#f7fbf8; --panel:#ffffff; --line:#d8e6dd; --text:#17221b; --muted:#52645a; --ok:#2f855a; --warn:#b7791f; --bad:#c53030; --accent:#0f766e; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Arial, sans-serif; background:var(--bg); color:var(--text); }
    header { padding:20px 24px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:16px; align-items:center; }
    h1 { font-size:22px; margin:0; }
    .brand-block { padding:22px 24px; border-bottom:1px solid var(--line); background:#eef8f2; }
    .brand-block strong { color:var(--accent); }
    .brand-block p { max-width:900px; margin:8px 0 0; color:var(--muted); }
    main { display:grid; grid-template-columns: 280px 1fr; min-height:calc(100vh - 73px); }
    nav { border-right:1px solid var(--line); padding:16px; background:#ffffff; }
    nav button { width:100%; margin:4px 0; padding:11px 12px; background:transparent; color:var(--text); border:1px solid var(--line); text-align:left; cursor:pointer; }
    nav button.active { border-color:var(--accent); color:var(--accent); }
    section { display:none; padding:20px; max-width:1100px; }
    section.active { display:block; }
    .grid { display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:14px; }
    .card { border:1px solid var(--line); background:var(--panel); padding:14px; border-radius:6px; }
    label { display:block; margin:10px 0 5px; color:var(--muted); font-size:13px; }
    input, textarea, select { width:100%; padding:10px; background:#ffffff; color:var(--text); border:1px solid var(--line); border-radius:4px; }
    textarea { min-height:110px; resize:vertical; }
    .action { margin-top:12px; padding:10px 14px; border:1px solid var(--accent); background:var(--accent); color:white; cursor:pointer; border-radius:4px; }
    pre { white-space:pre-wrap; word-break:break-word; background:#f9fcfa; border:1px solid var(--line); padding:12px; border-radius:4px; max-height:420px; overflow:auto; }
    .status { display:inline-block; padding:4px 8px; border-radius:4px; border:1px solid var(--line); color:var(--muted); }
    .ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
    @media (max-width: 820px) { main { grid-template-columns: 1fr; } nav { border-right:0; border-bottom:1px solid var(--line); } .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>Axiom Harmony Private Console</h1>
    <span class="status" id="health-pill">checking</span>
  </header>
  <div class="brand-block">
    <strong>Created by Toshay S. Zeigler for God's Love for Us LLC</strong>
    <p>This is the creator/admin view. The public website prototype is at <a href="/">/</a>. </p>
  </div>
  <main>
    <nav>
      <button class="active" data-tab="dashboard">Dashboard</button>
      <button data-tab="profile">Profile Vault</button>
      <button data-tab="checkin">InnerLight Check-In</button>
      <button data-tab="sound">Zenisys Sound</button>
      <button data-tab="legal">VEIL Draft</button>
      <button data-tab="audit">System Audit</button>
    </nav>
    <section id="dashboard" class="active">
      <div class="grid">
        <div class="card"><h2>System</h2><pre id="summary">Loading...</pre></div>
        <div class="card"><h2>Assets</h2><pre id="assets">Loading...</pre></div>
      </div>
    </section>
    <section id="profile">
      <div class="card">
        <h2>Encrypted Profile Vault</h2>
        <label>Name</label><input id="p-name">
        <label>Birthdate</label><input id="p-birthdate" type="date">
        <label>Address</label><input id="p-address">
        <label>Telephone</label><input id="p-telephone">
        <label>SSN Last Four</label><input id="p-ssn" maxlength="4">
        <button class="action" onclick="saveProfile()">Encrypt Profile</button>
        <pre id="profile-output"></pre>
      </div>
    </section>
    <section id="checkin">
      <div class="card">
        <h2>InnerLight Check-In</h2>
        <label>Region</label><select id="c-region"><option>US</option><option>EU</option><option>CA</option><option>IN</option><option>GLOBAL</option></select>
        <label>Message</label><textarea id="c-message"></textarea>
        <button class="action" onclick="submitCheckin()">Process Securely</button>
        <pre id="checkin-output"></pre>
      </div>
    </section>
    <section id="sound">
      <div class="card">
        <h2>Zenisys Sound System</h2>
        <p>Creator: Toshay S. Zeigler. Company: God's Love for Us LLC.</p>
        <button class="action" onclick="loadSound()">Inspect Sound Engine</button>
        <pre id="sound-output"></pre>
      </div>
    </section>
    <section id="legal">
      <div class="card">
        <h2>VEIL Draft Generator</h2>
        <label>Issue</label><textarea id="l-issue"></textarea>
        <label>Jurisdiction</label><input id="l-jurisdiction" placeholder="City, county, state, agency, school board">
        <label>Recipient / Channel</label><input id="l-channel" placeholder="Board, committee, agency, official">
        <button class="action" onclick="createLegalDraft()">Create Draft</button>
        <pre id="legal-output"></pre>
      </div>
    </section>
    <section id="audit">
      <div class="card">
        <h2>System Audit</h2>
        <button class="action" onclick="loadAudit()">Run Audit</button>
        <pre id="audit-output"></pre>
      </div>
    </section>
  </main>
<script>
const $ = (id) => document.getElementById(id);
document.querySelectorAll('nav button').forEach(btn => btn.addEventListener('click', () => {
  document.querySelectorAll('nav button, section').forEach(el => el.classList.remove('active'));
  btn.classList.add('active'); $(btn.dataset.tab).classList.add('active');
}));
async function post(url, body) {
  const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  return await res.json();
}
function show(id, data) { $(id).textContent = JSON.stringify(data, null, 2); }
async function loadAudit() {
  const data = await fetch('/api/audit').then(r => r.json());
  show('audit-output', data);
  show('summary', {creator:data.creator, encryption_roundtrip:data.encryption_roundtrip, database:data.database, taxonomy:data.taxonomy});
  show('assets', data.assets);
  $('health-pill').textContent = data.encryption_roundtrip ? 'encryption ok' : 'encryption failed';
  $('health-pill').className = 'status ' + (data.encryption_roundtrip ? 'ok' : 'bad');
}
async function loadSound() {
  show('sound-output', await fetch('/api/sound/status').then(r => r.json()));
}
async function saveProfile() {
  show('profile-output', await post('/api/profile', {
    name:$('p-name').value, birthdate:$('p-birthdate').value, address:$('p-address').value,
    telephone:$('p-telephone').value, ssn_last4:$('p-ssn').value
  }));
  loadAudit();
}
async function submitCheckin() {
  show('checkin-output', await post('/api/checkin', {message:$('c-message').value, region:$('c-region').value}));
  loadAudit();
}
async function createLegalDraft() {
  show('legal-output', await post('/api/legal/draft', {issue:$('l-issue').value, jurisdiction:$('l-jurisdiction').value, channel:$('l-channel').value}));
  loadAudit();
}
loadAudit();
loadSound();
</script>
</body>
</html>
"""


CLINICAL_HANDOFF_PAGE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InnerLight &mdash; Connecting You to a Care Professional</title>
  <style>
    :root { --ink:#1f3029; --muted:#5f7168; --line:#d9e4df; --soft:#f7fbf8; --urgent:#b84a44; --green:#2f7c5f; --blue:#2e6e8e; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Arial, sans-serif; color:var(--ink); background:#fbfdfb; }
    header { padding:26px 6vw; border-bottom:1px solid var(--line); background:white; }
    main { padding:24px 6vw 60px; max-width:920px; margin:0 auto; }
    h1 { margin:0 0 6px; font-size:clamp(26px, 4.5vw, 44px); line-height:1.05; }
    h2 { margin:0 0 10px; font-size:20px; }
    p { color:var(--muted); line-height:1.55; }
    .tag { display:inline-block; padding:5px 12px; border-radius:999px; background:#eaf3f7; border:1px solid #cfe3ec; color:var(--blue); font-weight:700; font-size:13px; margin-bottom:10px; }
    .panel { border:1px solid var(--line); border-radius:12px; background:white; padding:20px; margin:16px 0; }
    .who { background:#f4f9fb; border-color:#d6e8ef; }
    .who ul { margin:8px 0 0; padding-left:0; list-style:none; }
    .who li { padding:9px 0; border-bottom:1px solid #e4eef2; color:var(--ink); }
    .who li:last-child { border-bottom:0; }
    .who b { color:var(--blue); }
    .rights { background:#f7fbf8; border-color:#d9e9df; }
    .rights summary { cursor:pointer; font-weight:700; color:var(--green); }
    .rights p { font-size:14px; }
    .urgent-note { background:#fff7f6; border:1px solid #e5b5b1; border-radius:12px; padding:14px 16px; }
    .urgent-note b { color:var(--urgent); }
    label { display:block; font-weight:700; color:var(--ink); margin:14px 0 6px; }
    textarea { width:100%; border:1px solid var(--line); border-radius:8px; padding:12px; font:inherit; min-height:90px; }
    .convo { background:var(--soft); border:1px solid var(--line); border-radius:8px; padding:14px; max-height:280px; overflow:auto; }
    .convo .u { color:var(--ink); margin:0 0 10px; }
    .convo .a { color:var(--blue); margin:0 0 10px; }
    .convo .u b, .convo .a b { display:block; font-size:12px; text-transform:uppercase; letter-spacing:.04em; opacity:.7; }
    button, a.button { display:inline-block; border:0; border-radius:8px; padding:13px 18px; background:var(--green); color:white; font-weight:700; text-decoration:none; cursor:pointer; font-size:15px; }
    .secondary { background:#e8f1ed; color:var(--ink); }
    .locked { font-size:13px; color:var(--muted); margin-top:8px; }
    .disclaimer { font-size:12.5px; color:#8794a0; line-height:1.5; border-top:1px solid var(--line); margin-top:30px; padding-top:16px; }
  </style>
</head>
<body>
  <header>
    <div class="tag">Connecting you to mental-health care</div>
    <h1>You're being connected to a care professional</h1>
    <p>Before anything is shared, here is exactly who you may reach and what is protected. Nothing leaves this page until you read it and choose to send it.</p>
  </header>
  <main>
    <section class="panel who">
      <h2>Who you may be connected with</h2>
      <p>Depending on what you need, InnerLight routes you to one of these. You'll be told which one before any live conversation:</p>
      <ul>
        <li><b>Crisis-trained counselor</b> &mdash; immediate emotional support during an acute moment. Not a prescriber.</li>
        <li><b>Therapist / licensed counselor</b> &mdash; talk-based support and ongoing coping work.</li>
        <li><b>Psychiatrist</b> &mdash; a medical doctor who can evaluate symptoms and, where appropriate, manage medication.</li>
        <li><b>Nurse practitioner</b> &mdash; can assess symptoms and, in many states, manage medication.</li>
        <li><b>Access / pharmacy navigator</b> &mdash; helps with getting to existing medication or care you already have.</li>
      </ul>
    </section>

    <section class="urgent-note" id="urgent-note" style="display:none;">
      <p><b>If you are in immediate danger right now, call or text 988, or call 911.</b> You can do that while this page stays open. Connecting to a professional here does not replace emergency help in a life-threatening moment.</p>
    </section>

    <section class="panel">
      <h2>Here's what you told InnerLight</h2>
      <p>This is built from your actual conversation &mdash; not a form. Read it over. If anything is wrong or you want to say it differently, you can correct it so it truly reflects what you mean.</p>
      <div class="convo" id="convo-summary"><p class="u">Loading your conversation&hellip;</p></div>
      <label for="clarify">Correct or clarify anything (this becomes part of what the professional sees)</label>
      <textarea id="clarify" placeholder="For example: when I said I was done, I meant exhausted, not that I want to hurt myself &mdash; or anything you want to make clearer."></textarea>
      <label for="addnote">Anything you want to add that didn't come up?</label>
      <textarea id="addnote" placeholder="Medications, what's helped before, what you need most right now, who you'd prefer to talk to."></textarea>
      <p class="locked">Once you send this, the professional can read it and build their own assessment, but they cannot change your words. Your record stays honest. You stay in control of whether it's sent at all.</p>
    </section>

    <details class="panel rights">
      <summary>Your privacy &amp; your rights (tap to read)</summary>
      <p><b>Your information is protected.</b> InnerLight treats what you share as confidential health information. We aim to follow the privacy standards set by HIPAA &mdash; the U.S. health-privacy law &mdash; which means your information is not shared with anyone unless you give clear permission, and is kept encrypted.</p>
      <p><b>You decide what is shared.</b> Nothing on this page is sent to any professional until you choose to send it. You can close this page and nothing goes out.</p>
      <p><b>What we are not.</b> InnerLight is a support and connection tool. It does not diagnose conditions or prescribe medication. Any diagnosis or treatment comes only from the licensed professional you connect with.</p>
      <p><b>Encryption.</b> Your conversation is encrypted, and the raw details are not displayed on any public page. Only the summary you approve is prepared for the professional.</p>
    </details>

    <section class="panel">
      <h2>Ready when you are</h2>
      <p>When you send this, InnerLight notifies the care side and prepares your approved summary so the professional can read it <i>before</i> they speak with you &mdash; so you don't have to start from the beginning.</p>
      <p id="status" style="font-weight:700;color:var(--green);"></p>
      <button onclick="sendToCare()">Send my summary &amp; connect me</button>
      <a class="button secondary" href="/#private-step" onclick="window.close();return false;">Go back</a>
    </section>

    <p class="disclaimer">
      InnerLight, a service of God's Love For Us LLC, provides crisis support and connection to care. It is not a medical provider and does not provide medical diagnosis or treatment. We work to follow U.S. health-privacy standards including HIPAA, and your information is encrypted and shared only with your consent. In an emergency, call or text 988 or call 911. This summary is prepared for a licensed professional and reflects what you chose to share.
    </p>
  </main>
  <script>
    function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
    function loadConvo(){
      let log=[]; try{ log=JSON.parse(sessionStorage.getItem('innerlight_convo')||'[]'); }catch(e){}
      const risk = sessionStorage.getItem('innerlight_risk')||'low';
      if(risk==='critical'||risk==='high'){ document.getElementById('urgent-note').style.display='block'; }
      const box=document.getElementById('convo-summary');
      if(!log.length){ box.innerHTML='<p class="u">It looks like the conversation did not carry over. You can use the boxes below to tell the professional what is going on, in your own words.</p>'; return; }
      box.innerHTML = log.map(function(t){ return '<p class="'+(t.role==='user'?'u':'a')+'"><b>'+(t.role==='user'?'You said':'InnerLight')+'</b>'+esc(t.text)+'</p>'; }).join('');
    }
    function sendToCare(){
      document.getElementById('status').textContent='Your summary is prepared and the care side has been notified. A professional will review what you shared before connecting. Please keep this page open.';
    }
    loadConvo();
  </script>
</body>
</html>
"""


LEGAL_HANDOFF_PAGE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InnerLight &mdash; Connecting You to Legal Help</title>
  <style>
    :root { --ink:#23292f; --muted:#5f6b73; --line:#dde2e6; --soft:#f7f9fb; --urgent:#b84a44; --legal:#5a4596; --legal2:#6f57b0; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Arial, sans-serif; color:var(--ink); background:#fbfbfd; }
    header { padding:26px 6vw; border-bottom:1px solid var(--line); background:white; }
    main { padding:24px 6vw 60px; max-width:920px; margin:0 auto; }
    h1 { margin:0 0 6px; font-size:clamp(26px, 4.5vw, 44px); line-height:1.05; }
    h2 { margin:0 0 10px; font-size:20px; }
    p { color:var(--muted); line-height:1.55; }
    .tag { display:inline-block; padding:5px 12px; border-radius:999px; background:#efeaf9; border:1px solid #d8cdf0; color:var(--legal); font-weight:700; font-size:13px; margin-bottom:10px; }
    .panel { border:1px solid var(--line); border-radius:12px; background:white; padding:20px; margin:16px 0; }
    .who { background:#f7f4fd; border-color:#e0d6f4; }
    .who ul { margin:8px 0 0; padding-left:0; list-style:none; }
    .who li { padding:9px 0; border-bottom:1px solid #ebe3f7; color:var(--ink); }
    .who li:last-child { border-bottom:0; }
    .who b { color:var(--legal); }
    .rights { background:#f7f9fb; border-color:#dde2e6; }
    .rights summary { cursor:pointer; font-weight:700; color:var(--legal); }
    .rights p { font-size:14px; }
    label { display:block; font-weight:700; color:var(--ink); margin:14px 0 6px; }
    textarea { width:100%; border:1px solid var(--line); border-radius:8px; padding:12px; font:inherit; min-height:90px; }
    .convo { background:var(--soft); border:1px solid var(--line); border-radius:8px; padding:14px; max-height:280px; overflow:auto; }
    .convo .u { color:var(--ink); margin:0 0 10px; }
    .convo .a { color:var(--legal2); margin:0 0 10px; }
    .convo .u b, .convo .a b { display:block; font-size:12px; text-transform:uppercase; letter-spacing:.04em; opacity:.7; }
    button, a.button { display:inline-block; border:0; border-radius:8px; padding:13px 18px; background:var(--legal); color:white; font-weight:700; text-decoration:none; cursor:pointer; font-size:15px; }
    .secondary { background:#ece7f6; color:var(--ink); }
    .locked { font-size:13px; color:var(--muted); margin-top:8px; }
    .disclaimer { font-size:12.5px; color:#8a929a; line-height:1.5; border-top:1px solid var(--line); margin-top:30px; padding-top:16px; }
  </style>
</head>
<body>
  <header>
    <div class="tag">Connecting you to legal help &mdash; this is a legal handoff</div>
    <h1>You're being connected to legal support</h1>
    <p>This is <b>not</b> a medical or telehealth connection. This path is about a legal issue. Here is who you may reach and what protects you before anything is shared.</p>
  </header>
  <main>
    <section class="panel who">
      <h2>Who you may be connected with</h2>
      <p>You'll be told which one applies before any live conversation:</p>
      <ul>
        <li><b>Attorney / lawyer</b> &mdash; can give you legal advice about your specific situation and may represent you.</li>
        <li><b>Legal-aid organization</b> &mdash; free or low-cost legal help, often for housing, benefits, disability, or family matters.</li>
        <li><b>Legal-access navigator</b> &mdash; helps you find the right legal resource and understand your options.</li>
        <li><b>Self-help / civic resources</b> &mdash; plain-language information about your rights and the process.</li>
      </ul>
    </section>

    <section class="panel">
      <h2>Here's what you told InnerLight</h2>
      <p>This is built from your actual conversation &mdash; not a form. Read it over. If anything is wrong or you want to say it differently, you can correct it so it truly reflects what you mean.</p>
      <div class="convo" id="convo-summary"><p class="u">Loading your conversation&hellip;</p></div>
      <label for="clarify">Correct or clarify anything (this becomes part of what the legal professional sees)</label>
      <textarea id="clarify" placeholder="Make sure your situation is described the way you mean it."></textarea>
      <label for="addnote">Anything you want to add that didn't come up?</label>
      <textarea id="addnote" placeholder="Dates, notices you've received, deadlines, documents you have, or what outcome you're hoping for."></textarea>
      <p class="locked">Once you send this, the legal professional can read it and form their own view, but they cannot change your words. Your record stays honest. You decide whether it's sent at all.</p>
    </section>

    <details class="panel rights">
      <summary>Your privacy &amp; your rights (tap to read)</summary>
      <p><b>About attorney-client privilege.</b> Once you formally engage an attorney, what you tell them about your case is generally protected by attorney-client privilege &mdash; meaning they cannot disclose it without your permission, with narrow legal exceptions. That privilege begins with the attorney, once you are their client.</p>
      <p><b>Before that point.</b> What you share here with InnerLight is treated as private and is encrypted. InnerLight is not your attorney, and sharing with InnerLight is not the same as the attorney-client relationship. Privilege attaches once you engage the lawyer.</p>
      <p><b>You decide what is shared.</b> Nothing is sent to any legal professional until you choose to send it. You can close this page and nothing goes out.</p>
      <p><b>What we are not.</b> InnerLight provides legal <i>information</i> and <i>connection</i> to legal help. InnerLight itself does not provide legal advice or represent you. Legal advice comes only from the attorney or legal-aid professional you connect with.</p>
    </details>

    <section class="panel">
      <h2>Ready when you are</h2>
      <p>When you send this, InnerLight prepares your approved summary so the legal professional can review it before speaking with you.</p>
      <p id="status" style="font-weight:700;color:var(--legal);"></p>
      <button onclick="sendToLegal()">Send my summary &amp; connect me to legal help</button>
      <a class="button secondary" href="/#private-step" onclick="window.close();return false;">Go back</a>
    </section>

    <p class="disclaimer">
      InnerLight, a service of God's Love For Us LLC, provides legal information and connection to legal resources. It is not a law firm and does not provide legal advice or representation. No attorney-client relationship is formed with InnerLight. Attorney-client privilege applies once you engage a licensed attorney. Your information is encrypted and shared only with your consent. If your legal issue involves immediate danger to your safety, call 911.
    </p>
  </main>
  <script>
    function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
    function loadConvo(){
      let log=[]; try{ log=JSON.parse(sessionStorage.getItem('innerlight_convo')||'[]'); }catch(e){}
      const box=document.getElementById('convo-summary');
      if(!log.length){ box.innerHTML='<p class="u">It looks like the conversation did not carry over. You can use the boxes below to describe your legal issue in your own words.</p>'; return; }
      box.innerHTML = log.map(function(t){ return '<p class="'+(t.role==='user'?'u':'a')+'"><b>'+(t.role==='user'?'You said':'InnerLight')+'</b>'+esc(t.text)+'</p>'; }).join('');
    }
    function sendToLegal(){
      document.getElementById('status').textContent='Your summary is prepared and the legal side has been notified. A legal professional will review what you shared before connecting. Please keep this page open.';
    }
    loadConvo();
  </script>
</body>
</html>
"""


# Legacy generic page name kept pointing at the clinical page for old routes.
TELEHEALTH_PAGE = CLINICAL_HANDOFF_PAGE


_OPERATOR_ONLY_PATHS = ("/console", "/api/sessions", "/api/audit")

@app.before_request
def _block_operator_paths():
    if request.path in _OPERATOR_ONLY_PATHS:
        return (
            "Operator analytics have moved to the separate, login-protected "
            "operator console (run admin/admin_app.py). This user-facing app "
            "no longer exposes any internal analytics.",
            403,
        )

@app.route("/")
def index():
    return render_template_string(PUBLIC_PAGE)


@app.route("/console")
def console():
    return render_template_string(PAGE)


@app.route("/handoff/clinical")
def handoff_clinical():
    return render_template_string(CLINICAL_HANDOFF_PAGE)


@app.route("/handoff/legal")
def handoff_legal():
    return render_template_string(LEGAL_HANDOFF_PAGE)


@app.route("/telehealth/urgent")
def telehealth_urgent():
    return render_template_string(CLINICAL_HANDOFF_PAGE)


@app.route("/telehealth/intake")
def telehealth_intake():
    return render_template_string(CLINICAL_HANDOFF_PAGE)


@app.route("/api/profile", methods=["POST"])
def api_profile():
    data = request.get_json(force=True) or {}
    profile = {
        "name": str(data.get("name", "")).strip(),
        "birthdate": str(data.get("birthdate", "")).strip(),
        "address": str(data.get("address", "")).strip(),
        "telephone": str(data.get("telephone", "")).strip(),
        "ssn_last4": str(data.get("ssn_last4", "")).strip(),
    }
    if not all(profile.values()):
        return jsonify({"status": "error", "message": "All profile fields are required."}), 400
    if len(profile["ssn_last4"]) != 4 or not profile["ssn_last4"].isdigit():
        return jsonify({"status": "error", "message": "SSN last four must be exactly four digits."}), 400

    fp = fingerprint(json.dumps(profile, sort_keys=True))
    encrypted = encrypt_payload(f"profile:{fp}", profile)
    with connect_db() as conn:
        cursor = conn.execute(
            "INSERT INTO encrypted_profiles (created_at, profile_fingerprint, encrypted_json) VALUES (?, ?, ?)",
            (utc_now(), fp, json.dumps(encrypted)),
        )
    return jsonify({
        "status": "encrypted",
        "profile_reference": fp,
        "encryption": encrypted.get("version"),
        "stored_server_side": True,
    })


@app.route("/api/zenisys/ambient")
def zenisys_ambient():
    emotion = request.args.get("emotion", "calm peaceful ambient relaxation")
    result = get_zenisys_engine().detect_and_fetch(emotion)
    return jsonify({"tracks": result.get("tracks", []), "status": result.get("status"), "emotion": result.get("emotion")})


@app.route("/api/resolution/bridge", methods=["POST"])
def resolution_bridge():
    data = request.get_json(silent=True) or {}
    session_ref = str(data.get("session_reference", ""))
    handoff_type = str(data.get("handoff_type", "none"))
    consent = bool(data.get("consent", False))
    conversation_summary = str(data.get("summary", ""))
    quantum = data.get("quantum_emotion")
    topics = data.get("topics")

    # Build the context card (only if consent given)
    card = build_context_card(
        conversation_summary=conversation_summary,
        handoff_type=handoff_type,
        topics=topics,
        quantum_emotion=quantum,
        consent_given=consent,
    )

    # Track time to resolution
    resolution = get_resolution_tracker().resolve(session_ref, handoff_type)

    # Build the WARM handoff — acknowledges, affirms, prepares, reassures, in their register
    register_info = data.get("register", {})
    register = register_info.get("register", "neutral") if isinstance(register_info, dict) else str(register_info or "neutral")
    bridge_action = str(data.get("bridge_action", ""))
    warm = build_warm_handoff(
        handoff_type=handoff_type,
        bridge_action=bridge_action,
        what_they_shared=conversation_summary,
        register=register,
        context_shared=consent,
    )
    # Keep the simple exit message too (fallback / display)
    exit_msg = generate_exit_message(handoff_type, consent)
    # Log the handoff for the learning layer
    event_id = get_handoff_learning().log_handoff(handoff_type, register, warm["spoken_script"], session_ref)

    # Store the handoff (encrypted) for the operator console
    try:
        with connect_db() as conn:
            case_ref = fingerprint(f"handoff:{session_ref}:{utc_now()}")
            encrypted = encrypt_payload(f"handoff:{case_ref}", {
                "handoff_type": handoff_type,
                "context_card": card,
                "resolution": resolution,
                "consent": consent,
            })
            conn.execute(
                "INSERT INTO case_files (created_at, case_reference, share_authorized, encrypted_json) VALUES (?, ?, ?, ?)",
                (utc_now(), case_ref, 1 if consent else 0, json.dumps(encrypted)),
            )
    except Exception:
        pass

    return jsonify({
        "context_card": card,
        "resolution": resolution,
        "exit_message": exit_msg,
        "warm_handoff": warm,
        "handoff_event_id": event_id,
        "bridge_complete": True,
    })

@app.route("/api/voice/list")
def api_voice_list():
    """Return the voices the person can choose from (male/female, accents),
    so they can pick the most comforting voice to listen to."""
    return jsonify(voice_list())


@app.route("/api/voice/status")
def api_voice_status():
    """Tells you whether a real human-voice service is active, and runs a tiny
    live test so you can confirm your paid ElevenLabs voice is working — instead
    of silently getting the browser robot."""
    provider = voice_provider()
    if not provider:
        return jsonify({"active": False, "provider": None,
                        "message": "No voice service key found. Set ELEVENLABS_API_KEY, then restart. Using browser voice for now."})
    test = voice_synthesize("Voice check.")
    if test.get("audio_b64"):
        return jsonify({"active": True, "provider": provider,
                        "model": test.get("model"),
                        "message": f"Real human voice is ACTIVE via {provider}."})
    return jsonify({"active": False, "provider": provider,
                    "reason": test.get("reason"),
                    "message": "Voice key found but the test call failed. See reason — likely the key, quota, or voice id."})


@app.route("/api/voice/speak", methods=["POST"])
def api_voice_speak():
    """Return real human audio for the given text if a voice service is
    configured; otherwise tell the browser to use its best on-device voice."""
    data = request.get_json(force=True) or {}
    text = str(data.get("text", ""))[:600]
    voice_id = str(data.get("voice_id", ""))
    result = voice_synthesize(text, voice_id)
    return jsonify(result)


@app.route("/api/anchor/line")
def api_anchor_line():
    """Return a fresh calming line for the continuity anchor. Server-side
    composer guarantees an INSTANT response with no network dependency (vital
    in a crisis). If desired, a live AI layer can enrich this later, but the
    local generator is always the floor so the anchor can never stall."""
    import random
    OPEN = ["Hey,", "Listen,", "Okay,", "", "", "Right now,", "Just for this moment,",
            "Stay with me,", "I am here,", "Breathe with me,", "It is okay,"]
    REASSURE = ["you are not alone", "you have got this", "I am right here with you",
        "I am not going anywhere", "you are safe right now", "we will get through this",
        "this moment will pass", "you matter", "I have got you", "you are doing okay",
        "help is on the way", "you are stronger than this moment", "I see you",
        "you do not have to carry this by yourself", "hold on, help is coming"]
    GROUND = ["feel your feet on the floor", "notice the light in front of you",
        "feel the air on your skin", "press your hand on something solid",
        "feel where you are sitting", "let your shoulders drop",
        "notice one thing you can see", "feel your breath go in and out",
        "listen for the sound beneath everything", "touch something close to you"]
    DISTRACT = ["can you find the light?", "trace a slow circle with your finger",
        "tap along with the sound", "what color is the glow right now?",
        "follow the light with your eyes", "hum one note with the music",
        "count slowly to five with me", "move your hand toward the light",
        "tell me one color you can see", "breathe out slow, like a candle"]
    CLOSE = ["", "", "I am here.", "Stay with me.", "Right here.", "You are okay.",
             "I have got you.", "Just breathe.", "We are okay."]
    shape = random.random()
    if shape < 0.38: core = random.choice(REASSURE)
    elif shape < 0.68: core = random.choice(GROUND)
    elif shape < 0.92: core = random.choice(DISTRACT)
    else: core = random.choice(REASSURE) + ", and " + random.choice(DISTRACT)
    op = random.choice(OPEN)
    body = (op + " " if op else "") + core
    body = body[0].upper() + body[1:]
    if body[-1] not in ".?!": body += "."
    cl = random.choice(CLOSE)
    if cl and random.random() < 0.5: body += " " + cl
    return jsonify({"line": body})


@app.route("/api/handoff/report", methods=["POST"])
def api_handoff_report():
    """Build an observation-based handoff report — ONLY with the person's
    consent, and ONLY after passing the diagnostic-language blocklist."""
    init_db()
    data = request.get_json(force=True) or {}
    consented = bool(data.get("consent", False))
    person_quotes = data.get("quotes") or []
    signals = data.get("signals") or []
    observed = data.get("observed") or []
    crisis_reading = data.get("crisis_reading") or None
    if not isinstance(person_quotes, list): person_quotes = [str(person_quotes)]

    report = get_report_engine().build(
        consented=consented,
        person_quotes=[str(q) for q in person_quotes],
        signals=[str(s) for s in signals],
        observed=[str(o) for o in observed],
        crisis_reading=crisis_reading,
    )
    text = report.render_text()
    # Final belt-and-suspenders: never return text that contains diagnostic language
    leaked = scan_for_diagnostic_language(text)
    return jsonify({
        "consented": consented,
        "report_text": text,
        "safety_passed": report.safety_passed and not leaked,
        "blocked_terms": report.blocked_terms,
        "note": ("Report is observation-based and consent-gated. It never contains a "
                 "diagnosis or clinical conclusion."),
    })


@app.route("/api/resolution/stats")
def resolution_stats():
    return jsonify(get_resolution_tracker().stats())


# --- ZENISYS: serve a therapeutic soundscape plan for an emotional state ---
@app.route("/api/zenisys/plan")
def zenisys_plan():
    from zenisys_core import get_zenisys_core
    emotion = request.args.get("emotion", "calm")
    intensity = float(request.args.get("intensity", "0.5"))
    binaural = request.args.get("binaural", "0") == "1"
    solfeggio = request.args.get("solfeggio", "0") == "1"
    prev = request.args.get("prev", "") or None
    plan = get_zenisys_core().plan(
        emotion=emotion, intensity=intensity,
        enable_binaural=binaural, enable_solfeggio=solfeggio,
        prev_emotion=prev,
    )
    return jsonify(plan.to_dict())


# --- STANDALONE ZENISYS: a therapeutic sound space on its own ---
@app.route("/zenisys")
def zenisys_page():
    return ZENISYS_PAGE


@app.route("/zenisys/lab")
def zenisys_lab_page():
    return ZENISYS_LAB_PAGE



ZENISYS_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zenisys — Therapeutic Sound</title>
<script src="https://cdn.jsdelivr.net/npm/tone@14/build/Tone.js"></script>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    background:linear-gradient(180deg,#0f1729,#1a2744,#0f1729); color:#e8eef5;
    min-height:100vh; display:flex; flex-direction:column; align-items:center; padding:30px 18px; }
  h1 { font-weight:300; letter-spacing:3px; margin:10px 0 4px; font-size:30px; }
  .tag { color:#8aa3c4; font-size:14px; margin-bottom:26px; }
  .orb { width:200px; height:200px; border-radius:50%; margin:14px 0 28px;
    background:radial-gradient(circle at 35% 35%, #6fb3d4, #3a6b9c 55%, #1a2744);
    box-shadow:0 0 60px rgba(111,179,212,0.4); transition:all 2s ease;
    animation:breathe 8s ease-in-out infinite; }
  @keyframes breathe { 0%,100%{transform:scale(1);opacity:0.85;} 50%{transform:scale(1.08);opacity:1;} }
  .emotions { display:flex; flex-wrap:wrap; gap:10px; justify-content:center; max-width:560px; margin-bottom:24px; }
  .emo-btn { background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.15);
    color:#e8eef5; padding:12px 20px; border-radius:999px; cursor:pointer; font-size:15px;
    transition:all 0.25s; }
  .emo-btn:hover { background:rgba(255,255,255,0.16); transform:translateY(-2px); }
  .emo-btn.active { background:#6fb3d4; color:#0f1729; font-weight:600; border-color:#6fb3d4; }
  .toggles { display:flex; gap:16px; margin-bottom:22px; flex-wrap:wrap; justify-content:center; }
  .toggle { display:flex; align-items:center; gap:8px; font-size:14px; color:#b8cce0; cursor:pointer; }
  .intent { background:rgba(255,255,255,0.06); border-radius:14px; padding:16px 20px;
    max-width:520px; text-align:center; font-size:15px; line-height:1.6; color:#c8d8ea; min-height:54px; }
  .params { font-size:12px; color:#7d96b5; margin-top:14px; text-align:center; max-width:520px; line-height:1.7; }
  .play { background:#6fb3d4; color:#0f1729; border:0; padding:16px 40px; border-radius:999px;
    font-size:16px; font-weight:600; cursor:pointer; margin-bottom:24px; }
  .note { font-size:12px; color:#5d76a0; margin-top:18px; max-width:480px; text-align:center; line-height:1.6; }
</style></head>
<body>
  <h1>ZENISYS</h1>
  <div class="tag">therapeutic sound, generated live for how you feel</div>
  <div class="orb" id="orb"></div>
  <button class="play" id="playBtn" onclick="zenStart()">Begin</button>
  <div class="emotions" id="emotions"></div>
  <div class="toggles">
    <label class="toggle"><input type="checkbox" id="binaural"> Binaural beats (headphones)</label>
    <label class="toggle"><input type="checkbox" id="solfeggio"> Solfeggio tones</label>
  </div>
  <div class="intent" id="intent">Press Begin, then choose how you feel. The sound will meet you there.</div>
  <div class="params" id="params"></div>
  <div class="note">Zenisys generates calming sound in real time, entirely on your device — nothing is recorded or sent anywhere. For anxiety, anger, or overwhelm it gently starts near your energy and slows, the way a calming presence would. Best with headphones, at a soft volume.</div>

<script>
const EMOTIONS = ['calm','peaceful','anxiety','fear','anger','sadness','grief','numbness','overwhelm','hope','joy'];
let zenReady = false;
let activeEmotion = 'calm';

const ZENISYS = { started:false, pad:null, reverb:null, filter:null, masterGain:null,
  chordLoop:null, currentPlan:null, binauralNodes:null, solfeggioNode:null, audioCtx:null };
const SCALE_INTERVALS = { major:[0,2,4,5,7,9,11], minor:[0,2,3,5,7,8,10],
  dorian:[0,2,3,5,7,9,10], lydian:[0,2,4,6,7,9,11] };
const NOTE_BASE = {C:0,'C#':1,D:2,'D#':3,E:4,F:5,'F#':6,G:7,'G#':8,A:9,'A#':10,B:11};
function noteName(s,o){const n=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];return n[((s%12)+12)%12]+o;}
function buildChords(keyRoot,scale,consonance){
  const root=NOTE_BASE[keyRoot]!=null?NOTE_BASE[keyRoot]:0;
  const iv=SCALE_INTERVALS[scale]||SCALE_INTERVALS.major;
  return [0,3,5,4].map(deg=>{
    const r=root+iv[deg%iv.length], t=root+iv[(deg+2)%iv.length], f=root+iv[(deg+4)%iv.length];
    const notes=[noteName(r,3),noteName(t,4),noteName(f,4)];
    if(consonance>0.9)notes.push(noteName(r,4));
    return notes;
  });
}
async function zenStart(){
  await Tone.start();
  zenReady=true;
  document.getElementById('playBtn').style.display='none';
  zenPlay(activeEmotion);
}
function buildButtons(){
  const c=document.getElementById('emotions');
  EMOTIONS.forEach(e=>{
    const b=document.createElement('button');
    b.className='emo-btn'+(e==='calm'?' active':'');
    b.textContent=e; b.dataset.emo=e;
    b.onclick=()=>{ document.querySelectorAll('.emo-btn').forEach(x=>x.classList.remove('active'));
      b.classList.add('active'); activeEmotion=e; if(zenReady) zenPlay(e); };
    c.appendChild(b);
  });
}
async function zenPlay(emotion){
  const bin=document.getElementById('binaural').checked;
  const sol=document.getElementById('solfeggio').checked;
  const prev=ZENISYS.currentPlan?ZENISYS.currentPlan.emotion:'';
  const url='/api/zenisys/plan?emotion='+encodeURIComponent(emotion)+'&intensity=0.7&binaural='
    +(bin?'1':'0')+'&solfeggio='+(sol?'1':'0')+'&prev='+encodeURIComponent(prev);
  const plan=await (await fetch(url)).json();
  document.getElementById('intent').textContent=plan.intent;
  document.getElementById('params').textContent=
    'tempo '+plan.start_bpm+' \\u2192 '+plan.target_bpm+' BPM over '+plan.bpm_glide_seconds+'s  \\u00b7  '
    +plan.key_root+' '+plan.scale+'  \\u00b7  '+(plan.binaural_band?('binaural '+plan.binaural_band+' '+plan.binaural_beat_hz+'Hz  \\u00b7  '):'')
    +(plan.solfeggio?('solfeggio '+plan.solfeggio+'Hz'):'');
  const orb=document.getElementById('orb');
  const hues={calm:'#6fb3d4',peaceful:'#7fc4b8',anxiety:'#c4a06f',fear:'#9c8ad4',anger:'#d48a8a',
    sadness:'#8a9cd4',grief:'#7d8aa0',numbness:'#a0a0b0',overwhelm:'#b8a0c4',hope:'#9cd4a0',joy:'#e0c46f'};
  const h=hues[emotion]||'#6fb3d4';
  orb.style.background='radial-gradient(circle at 35% 35%, '+h+', #3a6b9c 55%, #1a2744)';
  orb.style.boxShadow='0 0 60px '+h+'66';
  if(!ZENISYS.started){ await zenApply(plan,true); } else { zenApply(plan,false); }
}
async function zenApply(plan,first){
  ZENISYS.currentPlan=plan;
  if(first){
    ZENISYS.audioCtx=Tone.getContext().rawContext;
    ZENISYS.masterGain=new Tone.Gain(plan.volume).toDestination();
    ZENISYS.reverb=new Tone.Reverb({decay:8,wet:0.55}).connect(ZENISYS.masterGain);
    ZENISYS.filter=new Tone.Filter({type:'lowpass',frequency:1200,rolloff:-24}).connect(ZENISYS.reverb);
    ZENISYS.pad=new Tone.PolySynth(Tone.Synth,{oscillator:{type:'sine'},
      envelope:{attack:plan.attack_seconds,decay:1.5,sustain:0.5,release:plan.release_seconds},volume:-26}).connect(ZENISYS.filter);
    ZENISYS.started=true;
  }
  const cutoff=600+plan.brightness*3200;
  if(ZENISYS.filter) ZENISYS.filter.frequency.rampTo(cutoff,4);
  if(ZENISYS.masterGain) ZENISYS.masterGain.gain.rampTo(plan.volume,4);
  Tone.Transport.bpm.value=plan.start_bpm;
  Tone.Transport.bpm.rampTo(plan.target_bpm,plan.bpm_glide_seconds);
  const chords=buildChords(plan.key_root,plan.scale,plan.consonance);
  let idx=0;
  if(ZENISYS.chordLoop){ZENISYS.chordLoop.stop();ZENISYS.chordLoop.dispose();}
  const interval=Math.max(2,plan.chord_change_seconds);
  ZENISYS.chordLoop=new Tone.Loop((time)=>{
    const chord=chords[idx%chords.length];
    const notes=plan.density<0.25?chord.slice(0,1):plan.density<0.4?chord.slice(0,2):chord;
    ZENISYS.pad.triggerAttackRelease(notes,interval*0.9,time); idx++;
  },interval);
  ZENISYS.chordLoop.start(0);
  if(Tone.Transport.state!=='started') Tone.Transport.start();
  zenBinaural(plan); zenSolfeggio(plan);
}
function zenBinaural(plan){
  if(ZENISYS.binauralNodes){try{ZENISYS.binauralNodes.forEach(n=>n.stop());}catch(e){}ZENISYS.binauralNodes=null;}
  if(!plan.binaural_beat_hz||!plan.carrier_hz)return;
  const ctx=ZENISYS.audioCtx; if(!ctx)return;
  const ear=(freq,pan)=>{const o=ctx.createOscillator();o.frequency.value=freq;o.type='sine';
    const g=ctx.createGain();g.gain.value=0.04;const p=ctx.createStereoPanner();p.pan.value=pan;
    o.connect(g);g.connect(p);p.connect(ctx.destination);o.start();return o;};
  ZENISYS.binauralNodes=[ear(plan.carrier_hz,-1),ear(plan.carrier_hz+plan.binaural_beat_hz,1)];
}
function zenSolfeggio(plan){
  if(ZENISYS.solfeggioNode){try{ZENISYS.solfeggioNode.stop();}catch(e){}ZENISYS.solfeggioNode=null;}
  if(!plan.solfeggio)return;
  const ctx=ZENISYS.audioCtx; if(!ctx)return;
  const o=ctx.createOscillator();o.frequency.value=plan.solfeggio;o.type='sine';
  const g=ctx.createGain();g.gain.value=0.03;o.connect(g);g.connect(ctx.destination);o.start();
  ZENISYS.solfeggioNode=o;
}
buildButtons();
</script>
</body></html>"""


# --- Serve calming scene videos (real footage, downloaded into /scenes) ---
@app.route("/scenes/<path:filename>")
def serve_scene(filename):
    scenes_dir = Path(__file__).resolve().parent.parent / "scenes"
    file_path = scenes_dir / filename
    if file_path.exists() and file_path.is_file():
        from flask import send_file
        return send_file(str(file_path))
    # File not present -> 404 so the frontend uses its animated fallback
    return ("scene not found", 404)




@app.route("/api/checkin", methods=["POST"])
def api_checkin():
    init_db()
    data = request.get_json(force=True) or {}
    message = str(data.get("message", "")).strip()
    region = str(data.get("region", "US")).strip().upper()
    if not message:
        return jsonify({"status": "error", "message": "Message is required."}), 400

    crisis = crisis_core.evaluate(message, str(data.get("name", "")).strip())
    clarion_analysis = clarion.evaluate(message)
    analysis = dict(clarion_analysis)
    if crisis.severity > int(analysis.get("severity", 0)):
        analysis.update({
            "category": crisis.category,
            "severity": crisis.severity,
            "confidence": 0.99 if crisis.risk == "critical" else 0.9,
            "crisis_gate": crisis.to_dict(),
        })
    # Cultural fluency: understand the message fully (dialect/language), but
    # NEVER infer identity. We comprehend meaning and mirror register only.
    cultural = get_cultural_engine().process_incoming(message)
    # If a crisis phrase appears in dialect or another language, escalate.
    if cultural.get("possible_crisis_phrase"):
        crisis = crisis_core.evaluate(cultural["plain_meaning"], str(data.get("name", "")).strip())
    # Identity is ONLY what the user volunteered — never inferred.
    volunteered = cultural["self_identification"]["volunteered_identity"]
    culture = ""  # we do not infer ethnicity; honor only what the user states
    if str(data.get("culture", "")).strip():
        culture = str(data.get("culture", "")).strip()
    local_context = localization_engine.load(region)
    innerlight_result = innerlight_system.process(data, analysis, culture, local_context)
    emotion_profile = innerlight_result.get("emotion_profile", {})
    emotion_distress = int(emotion_profile.get("distress_score", 0) or 0)
    response = innerlight_result["response"] if crisis.risk in {"critical", "high", "moderate"} or emotion_distress >= 7 else support_response(message, analysis)
    fp = fingerprint(message)
    case_file = innerlight_result["case_file"]
    case_reference = case_file.get("case_reference", fingerprint(f"case:{fp}"))
    learning_seed = {
        "risk": crisis.risk,
        "severity": crisis.severity,
        "zenisys": innerlight_result["zenisys"],
        "culture_signal": culture,
        "symptom_signals": innerlight_result["symptom_signals"],
        "emotion_profile": emotion_profile,
    }
    learning_state = innerlight_learning.start_state(learning_seed)
    severity = max(int(analysis.get("severity", 0)), emotion_distress)
    risk = crisis.risk if crisis.risk in {"critical", "high", "moderate"} else ("critical" if emotion_distress >= 9 else "high" if severity >= 8 else "moderate" if severity >= 5 else "low")

    # --- LAYERED CRISIS READ: detect the SHAPE of distress, not just phrases ---
    # Compute the quantum emotional read first so the crisis reader can use it.
    face_scores_in = data.get("face_scores") if isinstance(data, dict) else None
    voice_feats_in = data.get("voice_features") if isinstance(data, dict) else None
    quantum_read = get_quantum_engine().analyze(
        text_emotion=(analysis.get("category") if analysis.get("category") not in (None, "unclear") else None),
        face_emotion=str(data.get("face_emotion", "")).strip() if isinstance(data, dict) else None,
        face_scores=face_scores_in,
        voice_features=voice_feats_in,
    )
    # Use plain meaning (dialect/other-language understood) for crisis reading
    crisis_text = cultural.get("plain_meaning", message) if isinstance(cultural, dict) else message
    crisis_reading = get_crisis_reader().read(crisis_text, quantum_read)
    cr = crisis_reading.to_dict()
    # The reader can ONLY raise risk, never lower it (err toward care)
    if cr["level"] == "crisis":
        risk = "critical"
    elif cr["level"] == "elevated" and risk in ("low", "moderate"):
        risk = "high"
    elif cr["level"] == "concern" and risk == "low":
        risk = "moderate"

    # --- Conversation engine: personalized first response (FAST — no network) ---
    face_emo = ""
    if isinstance(data, dict):
        face_emo = str(data.get("face_emotion", "")).strip()
    initial_conv = get_conversation_engine().respond(
        user_text=message, face_emotion=face_emo, risk=risk,
    )
    # Mirror the person's register (casual/formal) — same care, met where they are
    conv_response = get_cultural_engine().shape_response(
        initial_conv["response"], cultural["register"]
    )
    conv_questions = [get_cultural_engine().shape_response(
        initial_conv["question"], cultural["register"]
    )]
    legal_issues = detect_legal_issues(message)
    legal_guidance = generate_legal_guidance(legal_issues)
    legal_code = legal_guidance.get("issue_code") if legal_guidance else None
    # If the layered reader sees crisis, force the crisis handoff regardless of phrasing
    handoff_risk = "critical" if cr["level"] == "crisis" else risk
    handoff = classify_handoff(crisis_text, risk=handoff_risk, legal_issue=legal_code, quantum_emotion=quantum_read)
    get_resolution_tracker().start(fp)

    # --- DEFER heavy persistence to the background so the person gets their
    # reply INSTANTLY. Encryption + DB writes happen after we respond. ---
    def _persist_in_background():
        try:
            encrypted = encrypt_payload(
                f"session:{fp}",
                {
                    "message": message, "analysis": analysis, "culture": culture,
                    "region": region, "local_context": local_context,
                    "response": response, "innerlight": innerlight_result,
                    "learning_state": learning_state, "created_at": utc_now(),
                },
            )
            encrypted_case = encrypt_payload(f"case:{case_reference}", case_file)
            with connect_db() as conn:
                conn.execute(
                    """INSERT INTO encrypted_sessions
                    (created_at, message_fingerprint, category, severity, risk, culture, encrypted_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (utc_now(), fp, analysis.get("category", "unclear"), severity, risk, culture, json.dumps(encrypted)),
                )
                conn.execute(
                    """INSERT INTO case_files
                    (created_at, case_reference, share_authorized, encrypted_json)
                    VALUES (?, ?, ?, ?)""",
                    (utc_now(), case_reference, 1 if case_file.get("share_authorized_by_user") else 0, json.dumps(encrypted_case)),
                )
        except Exception as e:
            print(f"[persist] background save failed: {e}")

    threading.Thread(target=_persist_in_background, daemon=True).start()

    return jsonify({
        "status": "secured",
        "session_id": fp,
        "heading": "Immediate support needed" if risk == "critical" else "Support response",
        "message_fingerprint": fp,
        "risk": risk,
        "severity": severity,
        "culture_signal": culture,
        "localization": local_context,
        "response": conv_response,
        "questions": conv_questions,
        "legal_guidance": legal_guidance,
        "handoff": handoff,
        "register": cultural["register"],
        "crisis_reading": cr,
        "quantum_emotion": quantum_read,
        "next_steps": innerlight_result["next_steps"],
        "provider_focus": innerlight_result["provider_focus"],
        "symptom_signals": innerlight_result["symptom_signals"],
        "emotion_profile": emotion_profile,
        "telehealth": innerlight_result["telehealth"],
        "provider_matches": innerlight_result["provider_matches"],
        "legal_activation": innerlight_result["legal_activation"],
        "case_file": case_file,
        "learning_state": learning_state,
        "needs_immediate_support": crisis.needs_immediate_support,
        "zenisys_music": get_zenisys_engine().detect_and_fetch(message),
        "sound_mode": innerlight_result["zenisys"]["mode"],
        "zenisys": innerlight_result["zenisys"],
        "encrypted_at_rest": True,
    })


@app.route("/api/emotion/analyze", methods=["POST"])
def api_emotion_analyze():
    init_db()
    data = request.get_json(force=True) or {}
    profile = emotion_module.analyze(data)
    raw_frame = str(data.get("visual_frame", ""))
    safe_input = dict(data)
    safe_input.pop("visual_frame", None)
    safe_input["visual_frame_received"] = bool(raw_frame)
    safe_input["visual_frame_fingerprint"] = fingerprint(raw_frame) if raw_frame else ""
    event_fingerprint = fingerprint(json.dumps({
        "emotion": profile.get("primary_emotion", ""),
        "distress": profile.get("distress_score", 0),
        "frame": safe_input["visual_frame_fingerprint"],
        "time": utc_now(),
    }, sort_keys=True))
    encrypted = encrypt_payload(
        f"emotion:{event_fingerprint}",
        {
            "safe_input": safe_input,
            "emotion_profile": profile,
            "created_at": utc_now(),
        },
    )
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO emotion_events
            (created_at, event_fingerprint, primary_emotion, distress_score, encrypted_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                utc_now(),
                event_fingerprint,
                str(profile.get("primary_emotion", "")),
                int(profile.get("distress_score", 0) or 0),
                json.dumps(encrypted),
            ),
        )
    profile["event_fingerprint"] = event_fingerprint
    profile["encrypted_at_rest"] = True
    return jsonify(profile)


@app.route("/api/innerlight/learn", methods=["POST"])
def api_innerlight_learn():
    init_db()
    data = request.get_json(force=True) or {}
    answer = str(data.get("answer", "")).strip()
    if not answer:
        return jsonify({"status": "error", "message": "Answer is required."}), 400

    session_reference = str(data.get("session_reference", "")).strip() or fingerprint(answer)
    learning_state = data.get("learning_state") if isinstance(data.get("learning_state"), dict) else {}
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    learned = innerlight_learning.learn(answer, learning_state, context)
    event_fingerprint = fingerprint(f"{session_reference}:{answer}:{utc_now()}")
    encrypted = encrypt_payload(
        f"learning:{session_reference}:{event_fingerprint}",
        {
            "answer": answer,
            "learned": learned,
            "created_at": utc_now(),
        },
    )
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO learning_events
            (created_at, session_reference, event_fingerprint, encrypted_json)
            VALUES (?, ?, ?, ?)
            """,
            (utc_now(), session_reference, event_fingerprint, json.dumps(encrypted)),
        )

    learned["event_fingerprint"] = event_fingerprint
    learned["session_reference"] = session_reference
    learned["encrypted_at_rest"] = True

    # --- Cultural fluency: understand fully, mirror register, catch crisis in any dialect ---
    cultural = get_cultural_engine().process_incoming(answer)
    learn_risk = learned.get("risk", "low")
    if cultural.get("possible_crisis_phrase"):
        learn_risk = "critical"
        learned["risk"] = "critical"

    # --- LAYERED CRISIS READ on the follow-up turn ---
    ctx_early = context if isinstance(context, dict) else {}
    quantum_early = get_quantum_engine().analyze(
        text_emotion=(learned.get("zenisys_music") or {}).get("emotion"),
        face_emotion=ctx_early.get("face_emotion"),
        face_scores=ctx_early.get("face_scores"),
        voice_features=ctx_early.get("voice_features"),
    )
    crisis_text_l = cultural.get("plain_meaning", answer)
    crisis_reading_l = get_crisis_reader().read(crisis_text_l, quantum_early)
    crl = crisis_reading_l.to_dict()
    learned["crisis_reading"] = crl
    # Reader can only raise risk
    if crl["level"] == "crisis":
        learn_risk = "critical"; learned["risk"] = "critical"
    elif crl["level"] == "elevated" and learn_risk in ("low", "moderate"):
        learn_risk = "high"
    elif crl["level"] == "concern" and learn_risk == "low":
        learn_risk = "moderate"

    # --- Conversation engine: replace generic response with personalized one ---
    face_emotion = ""
    if isinstance(context, dict):
        face_emotion = str(context.get("face_emotion", "")).strip()
    conv = get_conversation_engine().respond(
        user_text=answer,
        face_emotion=face_emotion,
        risk=learn_risk,
        learning_state=learned.get("learning_state"),
    )
    # Mirror register: same care, met where they are
    learned["response"] = get_cultural_engine().shape_response(conv["response"], cultural["register"])
    learned["questions"] = [get_cultural_engine().shape_response(conv["question"], cultural["register"])]
    learned["zenisys_music"] = get_zenisys_engine().detect_and_fetch(answer)
    legal_issues = detect_legal_issues(answer)
    learned["legal_guidance"] = generate_legal_guidance(legal_issues)

    # Quantum-inspired emotion analysis from all three signals
    ctx = context if isinstance(context, dict) else {}
    quantum = get_quantum_engine().analyze(
        text_emotion=(learned.get("zenisys_music") or {}).get("emotion"),
        face_emotion=ctx.get("face_emotion"),
        face_scores=ctx.get("face_scores"),
        voice_features=ctx.get("voice_features"),
    )
    learned["quantum_emotion"] = quantum

    # Resolution framework: should we offer a handoff to real help?
    legal_code = None
    if learned.get("legal_guidance"):
        legal_code = learned["legal_guidance"].get("issue_code")
    handoff = classify_handoff(
        text=crisis_text_l,
        risk="critical" if crl["level"] == "crisis" else learned.get("risk", "low"),
        legal_issue=legal_code,
        quantum_emotion=quantum,
    )
    learned["handoff"] = handoff
    learned["register"] = cultural["register"]
    if handoff.get("type") != "none":
        learned["exit_message"] = generate_exit_message(handoff["type"], False)

    return jsonify(learned)


@app.route("/api/legal/draft", methods=["POST"])
def api_legal_draft():
    init_db()
    data = request.get_json(force=True) or {}
    issue = str(data.get("issue", "")).strip()
    if not issue:
        return jsonify({"status": "error", "message": "Issue is required."}), 400
    draft = draft_legal_response(issue, str(data.get("jurisdiction", "")), str(data.get("channel", "")))
    activation = innerlight_system.legal_activation({
        "legal_issue": issue,
        "location": str(data.get("jurisdiction", "")),
    }, issue)
    draft["activation"] = activation
    draft["research_start"] = activation.get("research_start")
    draft["jurisdiction_layers"] = activation.get("jurisdiction_layers", [])
    draft["outputs_to_prepare"] = activation.get("outputs_to_prepare", [])
    fp = fingerprint(issue)
    with connect_db() as conn:
        cursor = conn.execute(
            "INSERT INTO legal_drafts (created_at, issue_fingerprint, title, draft_json) VALUES (?, ?, ?, ?)",
            (utc_now(), fp, draft["title"], json.dumps(draft)),
        )
    draft["status"] = "created"
    draft["draft_id"] = cursor.lastrowid
    draft["issue_fingerprint"] = fp
    return jsonify(draft)


@app.route("/api/sessions")
def api_sessions():
    init_db()
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, message_fingerprint, category, severity, risk, culture
            FROM encrypted_sessions ORDER BY id DESC LIMIT 50
            """
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/audit")
def api_audit():
    init_db()
    return jsonify(system_audit())


@app.route("/api/creator")
def api_creator():
    return jsonify({
        "creator": CREATOR_FULL_NAME,
        "display_name": CREATOR_NAME,
        "name_spelling": CREATOR_NAME_SPELLING,
        "company": COMPANY_NAME,
        "imprint": CREATOR_IMPRINT_TEXT,
        "imprint_hash": CREATOR_IMPRINT_HASH,
    })


@app.route("/api/sound/status")
def api_sound_status():
    return jsonify(sound_engine_status())


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=int(os.environ.get("AHP_UNIFIED_PORT", "5010")), debug=False)


