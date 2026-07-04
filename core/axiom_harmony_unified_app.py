from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template_string, request, session, redirect

from ahp_encryption import AxiomHarmonyProtocol
from clarion_engine import Clarion
from crisis_response_core import CrisisResponseCore
from cultural_detector import CulturalDetector
from zenisys_music_engine import get_zenisys_engine
from conversation_engine import get_conversation_engine
import comprehension_engine
from legal_guidance_engine import detect_legal_issues, generate_legal_guidance
from quantum_emotion_engine import get_quantum_engine
from crisis_risk_reader import get_crisis_reader
from handoff_report_engine import get_report_engine, scan_for_diagnostic_language
from handoff_queue import (
    submit_handoff, list_handoffs, get_handoff, set_status, diagnostics as handoff_diagnostics,
)
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
    .gate-links { margin-top:22px; font-size:13px; color:#8fa8a0; display:flex; gap:8px; justify-content:center; align-items:center; flex-wrap:wrap; }
    .gate-links a { color:#6d8f80; text-decoration:none; border-bottom:1px solid transparent; transition:border-color .2s; }
    .gate-links a:hover { border-bottom-color:#7eb8a0; }
    .gate-links span { color:#c8ddd2; }
    .gate-button { background:#5ba08a; color:#fff; border:0; border-radius:999px; padding:15px 38px;
      font-size:16px; font-weight:600; cursor:pointer; box-shadow:0 12px 30px rgba(91,160,138,.35); transition:transform .15s; }
    .gate-button:hover { transform:translateY(-2px); background:#4e9079; }
    .gate-sub { font-size:12px; color:#8fa8a0; margin-top:18px !important; }
    .story-screen { min-height:100vh; display:flex; flex-direction:column; align-items:center; padding:0 20px 40px;
      position:relative;
      background:transparent; }
    .story-screen > * { position:relative; z-index:1; }
    #scene-veil { position:fixed; inset:0; z-index:0; pointer-events:none;
      background:linear-gradient(180deg, rgba(255,255,255,0.55), rgba(255,255,255,0.35)); }
    .scene-picker { position:fixed; bottom:14px; right:14px; z-index:20; display:flex; gap:6px;
      background:rgba(255,255,255,0.7); backdrop-filter:blur(6px); border-radius:999px; padding:6px 10px; }
    .scene-btn { background:none; border:0; font-size:18px; cursor:pointer; opacity:0.6; padding:2px 4px; }
    .scene-btn.active { opacity:1; transform:scale(1.15); }
    /* FACE VIDEO — starts centered and calm. On scroll it gently floats to a
       small rounded thumbnail on the side; scrolling back to top returns it
       to the centered spot. Smooth, never growing, never taking over. */
    .story-video-bar { padding:18px 0 10px; width:100%; text-align:center;
      transition:all 0.4s ease; }
    .story-video-bar.floating { position:fixed; top:84px; right:20px; left:auto;
      width:auto; padding:0; z-index:40; text-align:right; }
    .story-wrap { width:100%; max-width:620px; text-align:center; padding-top:10px; }
    #conversation-thread { background:rgba(255,255,255,0.55); backdrop-filter:blur(3px);
      border-radius:18px; padding:4px 16px; scroll-behavior:smooth; }
    #conversation-thread:empty { background:none; padding:0; }
    .story-video { width:300px; height:300px; max-width:78vw; max-height:78vw; object-fit:cover; border-radius:28px; border:3px solid #c8ddd2;
      margin:0 auto 8px; display:block; background:#e8f0eb; box-shadow:0 8px 30px rgba(0,0,0,0.18);
      transition:width 0.4s ease, height 0.4s ease, border-radius 0.4s ease, box-shadow 0.4s ease, margin 0.4s ease; }
    .story-video-bar.floating .story-video { width:110px; height:110px; border-radius:50%;
      border-width:3px; margin:0; box-shadow:0 6px 22px rgba(0,0,0,0.28); }
    @media (max-width:640px){ .story-video-bar.floating .story-video { width:78px; height:78px; }
      .story-video-bar.floating { top:70px; right:12px; } }
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
    .help-rail-placeholder {}
    #help-rail { position:fixed; right:14px; top:50%; transform:translateY(-50%); z-index:90;
      display:flex; flex-direction:column; gap:8px; }
    #help-rail .rail-btn { background:rgba(255,255,255,0.95); color:#2e6e8e; border:1px solid #2e6e8e;
      border-radius:12px; padding:10px 12px; font-size:13px; font-weight:700; cursor:pointer; text-decoration:none;
      text-align:center; box-shadow:0 4px 14px rgba(20,40,60,0.14); min-width:76px; }
    #help-rail .rail-988 { background:#e8534e; color:#fff; border:0; }
    @media (max-width:760px){
      #help-rail { top:auto; bottom:0; left:0; right:0; transform:none; flex-direction:row;
        justify-content:space-around; background:#ffffff; padding:10px 6px; z-index:95;
        box-shadow:0 -3px 14px rgba(20,40,60,0.18); }
      #help-rail .rail-btn { flex:1; min-width:0; margin:0 3px; padding:12px 4px; font-size:13px; }
      /* Scene picker sits ABOVE the help bar, never overlapping it */
      .scene-picker { bottom:76px !important; right:10px !important; z-index:40 !important;
        background:rgba(255,255,255,0.85); border-radius:999px; padding:4px 8px; }
      /* Heart chip also lifts above the help bar */
      #heart-chip { bottom:80px !important; }
      /* Give the whole page room so nothing hides behind the fixed help bar */
      .story-screen { padding-bottom:150px; }
      body { padding-bottom:70px; }
    }
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
        <div class="gate-links">
          <a href="/about">About</a><span>&middot;</span>
          <a href="/how-it-works">How it works</a><span>&middot;</span>
          <a href="/privacy">Your privacy</a><span>&middot;</span>
          <a href="/contact">Contact</a>
        </div>
      </div>
    </div>

    <!-- CALM STORY SCREEN -->
    <section id="story-screen" class="story-screen" style="display:none;">
      <!-- REALISM LEADS: real video background plays first. Animated canvas is fallback only. -->
      <div id="calm-photo-a" style="position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none;opacity:0;transition:opacity 3s ease;overflow:hidden;">
        <div class="scene-fill" style="position:absolute;inset:-40px;background-size:cover;background-position:center;filter:blur(28px) brightness(0.9);"></div>
        <img class="scene-full" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;">
      </div>
      <div id="calm-photo-b" style="position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none;opacity:0;transition:opacity 3s ease;overflow:hidden;">
        <div class="scene-fill" style="position:absolute;inset:-40px;background-size:cover;background-position:center;filter:blur(28px) brightness(0.9);"></div>
        <img class="scene-full" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;">
      </div>
      <div id="scene-veil"></div>
      <div class="scene-picker" id="scene-picker">
        <button class="scene-btn active" data-scene="garden" onclick="setScene('garden')" title="Garden">&#127807;</button>
        <button class="scene-btn" data-scene="sunflower" onclick="setScene('sunflower')" title="Sunflower">&#127803;</button>
        <button class="scene-btn" data-scene="sunset" onclick="setScene('sunset')" title="Sunset trees">&#127749;</button>
        <button class="scene-btn" data-scene="horizon" onclick="setScene('horizon')" title="Golden horizon">&#127748;</button>
        <button class="scene-btn" data-scene="moon" onclick="setScene('moon')" title="Night moon">&#127765;</button>
        <button class="scene-btn" data-scene="daymoon" onclick="setScene('daymoon')" title="Day moon">&#127761;</button>
        <button class="scene-btn" data-scene="moonleaf" onclick="setScene('moonleaf')" title="Moon through leaves">&#127769;</button>
      </div>
      <div class="story-video-bar">
        <video id="visual-preview" class="story-video" autoplay muted playsinline></video>
              </div>
      <div class="story-wrap">
        <h2 class="story-title">Tell me your story.</h2>
        <p class="story-sub">Take your time. Say whatever feels true. I am listening.</p>
        <textarea id="message" class="story-input" placeholder="Start wherever you would like... (press Enter to send)" onkeydown="if((event.key==='Enter'||event.keyCode===13)&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendCheckin();}"></textarea>
        <div class="story-actions">
          <button class="story-send" onclick="sendCheckin()">Send</button>
          <button class="story-mic" type="button" onclick="startVoiceCapture()" title="Speak instead of typing">&#127908; Speak</button>
        </div>
        <div class="music-bar">
          <span id="music-now">&#9834; soft music playing</span>
          <button class="music-change" type="button" onclick="changeMusic()">Change music</button>
          <button class="music-change" type="button" id="entrain-toggle" onclick="toggleEntrainment()">&#10041; Calm pulse: on</button>
          <button class="music-change" type="button" id="voice-toggle" onclick="toggleVoiceCombined()">&#128263; Spoken voice: Off</button>
          <select id="voice-picker" onchange="selectVoice(this.value)" style="display:none;"><option value="">Voice: default</option></select>
        </div>
        <div id="calm-player" style="display:none; margin:18px auto 6px; max-width:560px; background:rgba(20,30,48,0.92); border-radius:20px; padding:14px 14px 12px; box-shadow:0 8px 30px rgba(0,0,0,0.22); transition:max-width 0.5s ease;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
            <span style="color:#cfe3f2;font-size:14px;font-weight:600;">&#10024; Calm space &mdash; touch and move to make light and sound</span>
            <span id="calm-music-note" style="color:#7fa9c9;font-size:12px;">music softens while you play</span>
          </div>
          <div id="calm-tabs" style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap;">
            <button type="button" class="calm-tab active" data-mode="anchor" onclick="setCalmMode('anchor')" style="background:#6fb3d4;color:#0c1322;border:0;border-radius:999px;padding:5px 12px;font-size:12px;font-weight:700;cursor:pointer;">Touch &amp; Calm</button>
            <button type="button" class="calm-tab" data-mode="trace" onclick="setCalmMode('trace')" style="background:rgba(255,255,255,0.10);color:#cfe3f2;border:1px solid rgba(255,255,255,0.2);border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer;">Trace</button>
            <button type="button" class="calm-tab" data-mode="call" onclick="setCalmMode('call')" style="background:rgba(255,255,255,0.10);color:#cfe3f2;border:1px solid rgba(255,255,255,0.2);border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer;">Call &amp; Answer</button>
            <button type="button" class="calm-tab" data-mode="words" onclick="setCalmMode('words')" style="background:rgba(255,255,255,0.10);color:#cfe3f2;border:1px solid rgba(255,255,255,0.2);border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer;">Word Play</button>
          </div>
          <canvas id="calm-touch" style="width:100%;height:240px;display:block;border-radius:14px;background:radial-gradient(circle at 50% 50%, #16314a, #0c1322);touch-action:none;cursor:pointer;transition:height 0.5s ease;"></canvas>
        </div>
        <div id="conversation-thread" style="margin-top:22px;"></div>
        <div id="help-rail">
          <a href="tel:988" class="rail-btn rail-988" title="Call 988 now">&#128222; 988</a>
          <button type="button" class="rail-btn" onclick="openHelp('telehealth')" title="Talk to a provider">Provider</button>
          <button type="button" class="rail-btn" onclick="openHelp('attorney')" title="Legal help">Legal</button>
          <button type="button" class="rail-btn" onclick="openActivities()" title="Calming activities">Activities</button>
          <button type="button" class="rail-btn" onclick="testMic()" title="Test my microphone">Test mic</button>
        </div>
        <div id="urgent-help" style="display:none;margin:6px auto;max-width:560px;text-align:center;padding:12px;background:rgba(232,83,78,0.1);border:1px solid rgba(232,83,78,0.4);border-radius:14px;color:#b3322e;font-weight:600;"></div>
        <div id="live-transcript" style="display:none;margin-top:14px;padding:14px 16px;background:rgba(111,179,212,0.12);border:1px solid rgba(111,179,212,0.4);border-radius:14px;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <span id="listen-dot" style="width:11px;height:11px;border-radius:50%;background:#e05a5a;display:inline-block;animation:listenpulse 1.1s ease-in-out infinite;"></span>
            <span id="listen-label" style="font-size:13px;color:#5a7a96;font-weight:600;">Listening\u2026</span>
          </div>
          <div id="transcript-text" style="font-size:17px;line-height:1.5;color:#1a3a5c;min-height:24px;">&nbsp;</div>
          <div style="margin-top:10px;">
            <div style="font-size:11px;color:#6e8ba3;margin-bottom:4px;">Microphone level</div>
            <div style="height:8px;background:rgba(90,130,160,0.18);border-radius:6px;overflow:hidden;">
              <div id="mic-level-fill" style="height:100%;width:0%;background:linear-gradient(90deg,#6fb3d4,#3aa56b);border-radius:6px;transition:width 0.06s linear;"></div>
            </div>
          </div>
        </div>
        <div id="mic-test-row" style="margin-top:8px;display:flex;flex-direction:column;gap:6px;">
          <span id="mic-test-status" style="font-size:12px;color:#6e8ba3;"></span>
          <audio id="mic-test-playback" controls style="display:none;width:100%;max-width:320px;"></audio>
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
const SCENE_PHOTOS = {
  // Real photographs, taken by the founder. No animation — realism grounds
  // the person in the actual world.
  garden:    '/scenes/photo_1_rosemary.jpg',
  sunflower: '/scenes/photo_5_sunflower.jpg',
  sunset:    '/scenes/photo_2_sunset_trees.jpg',
  horizon:   '/scenes/photo_6_golden_horizon.jpg',
  moon:      '/scenes/photo_3_moon_night.jpg',
  daymoon:   '/scenes/photo_4_moon_day.jpg',
  moonleaf:  '/scenes/photo_7_moon_leaves.jpg'
};
const SCENE_ORDER = ['garden','sunflower','sunset','horizon','moon','daymoon','moonleaf'];
let sceneAutoTimer = null, sceneUserChose = false;
let currentScene = 'garden';
let canvasAnim = null;

function setScene(scene, byUser=true) {
  currentScene = scene;
  if (byUser) { sceneUserChose = true; metric('scene_change'); }   // the person chose — stop auto-rotation
  document.querySelectorAll('.scene-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.scene === scene);
  });
  const frameA = document.getElementById('calm-photo-a');
  const frameB = document.getElementById('calm-photo-b');
  const src = SCENE_PHOTOS[scene];
  if (!frameA || !frameB || !src) return;
  // Crossfade: load into the hidden frame, then trade opacities slowly.
  // Each frame shows the WHOLE photo, with a soft blurred copy filling the
  // edges — no cropping deep into the picture, no blank bars.
  const showing = frameA.style.opacity !== '0' ? frameA : frameB;
  const hidden  = showing === frameA ? frameB : frameA;
  const img = hidden.querySelector('.scene-full');
  hidden.querySelector('.scene-fill').style.backgroundImage = "url('" + src + "')";
  img.onload = () => { hidden.style.opacity = '1'; showing.style.opacity = '0'; };
  img.src = src;
}

function startSceneRotation() {
  // Slow, gentle rotation through the real photographs — until the person
  // picks one themselves; their choice always wins.
  if (sceneAutoTimer) clearInterval(sceneAutoTimer);
  sceneAutoTimer = setInterval(() => {
    if (sceneUserChose) { clearInterval(sceneAutoTimer); sceneAutoTimer = null; return; }
    const i = SCENE_ORDER.indexOf(currentScene);
    setScene(SCENE_ORDER[(i + 1) % SCENE_ORDER.length], false);
  }, 90000); // a new scene every 90 calm seconds
}

// ========================================================
// ZENISYS SOUND ENGINE v3 — DJ Crossfade + Generative Layer
// ========================================================
const FACE_API_MODELS = 'https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@master/weights/';
let faceReady = false;
let currentFaceEmotion = null;
let faceEmotionScores = {};




// ================= CALMING ACTIVITIES — evidence-based, off the front screen =================
// Eight activities, each drawn from established calming research:
// paced breathing (parasympathetic activation), 5-4-3-2-1 grounding (attention
// re-anchoring), visuospatial matching (the "Tetris effect" channel), word
// focus, slow tracing, counting anchor, progressive muscle release, and a
// three-good-things gratitude micro-practice. After ~10 minutes of continuous
// play, a gentle check-in offers conversation — distraction is a bridge, not
// a destination.

// ===== THE CALM GARDEN: every success blooms. Your calm, growing something. =====
let gardenBlooms = 0;
const GARDEN_FLOWERS = ['🌼','🌸','🌷','🌻','🌹','🏵️','🌺','💐'];
function gardenBar(){
  let g = actOverlay && actOverlay.querySelector('#calm-garden');
  if (!g && actOverlay){
    g = document.createElement('div');
    g.id = 'calm-garden';
    g.style.cssText = 'min-height:44px;margin:6px 0 12px;padding:8px 12px;border-radius:14px;'
      + 'background:linear-gradient(180deg, rgba(40,70,50,0.35), rgba(20,40,30,0.5));'
      + 'border:1px solid rgba(125,211,168,0.25);font-size:24px;letter-spacing:4px;line-height:1.5;';
    g.innerHTML = '<span style="font-size:11.5px;color:#9fd4b4;display:block;letter-spacing:0.4px;">Your calm garden — each success grows it</span><span id="garden-row"></span>';
    const menu = actOverlay.querySelector('#act-menu');
    menu.parentNode.insertBefore(g, menu);
  }
  return g;
}
function bloom(){
  gardenBlooms++;
  metric('bloom');
  const g = gardenBar(); if (!g) return;
  const row = g.querySelector('#garden-row');
  const f = document.createElement('span');
  f.textContent = GARDEN_FLOWERS[gardenBlooms % GARDEN_FLOWERS.length];
  f.style.cssText = 'display:inline-block;transform:scale(0);transition:transform 0.8s cubic-bezier(0.34,1.56,0.64,1);';
  row.appendChild(f);
  requestAnimationFrame(()=>{ f.style.transform='scale(1)'; });
  softChime();
  burstAt(f);
}
// Soft two-note chime, very quiet, warm — success you can hear
let chimeCtx=null;
function softChime(){
  try{
    chimeCtx = chimeCtx || new (window.AudioContext||window.webkitAudioContext)();
    const t = chimeCtx.currentTime;
    [523.25, 659.25].forEach((f,i)=>{
      const o = chimeCtx.createOscillator(), g = chimeCtx.createGain();
      o.type='sine'; o.frequency.value=f;
      g.gain.setValueAtTime(0, t+i*0.12);
      g.gain.linearRampToValueAtTime(0.035, t+i*0.12+0.03);
      g.gain.exponentialRampToValueAtTime(0.0001, t+i*0.12+0.9);
      o.connect(g); g.connect(chimeCtx.destination);
      o.start(t+i*0.12); o.stop(t+i*0.12+1);
    });
  }catch(e){}
}
// Tiny particle burst of light at an element — the juice
function burstAt(el){
  try{
    const r = el.getBoundingClientRect();
    for (let i=0;i<7;i++){
      const p = document.createElement('div');
      const a = Math.random()*6.28, d = 26+Math.random()*30;
      p.style.cssText = 'position:fixed;width:6px;height:6px;border-radius:50%;z-index:90;pointer-events:none;'
        + 'background:#bfe8cf;box-shadow:0 0 8px #bfe8cf;left:'+(r.left+r.width/2)+'px;top:'+(r.top+r.height/2)+'px;'
        + 'transition:all 0.9s ease-out;opacity:1;';
      document.body.appendChild(p);
      requestAnimationFrame(()=>{ p.style.left=(r.left+r.width/2+Math.cos(a)*d)+'px';
        p.style.top=(r.top+r.height/2+Math.sin(a)*d)+'px'; p.style.opacity='0'; });
      setTimeout(()=>p.remove(), 1000);
    }
  }catch(e){}
}

let actOverlay=null, actOpenedAt=0, actReengaged=false, actTimers=[];
function actClearTimers(){ actTimers.forEach(t=>{clearInterval(t);clearTimeout(t);}); actTimers=[]; }
function openActivities(){
  metric('activity_open','overlay');
  if (actOverlay){ actOverlay.style.display='block'; actOpenedAt=Date.now(); actReengaged=false; return; }
  actOpenedAt = Date.now(); actReengaged=false;
  actOverlay = document.createElement('div');
  actOverlay.id='activities-overlay';
  actOverlay.style.cssText='position:fixed;inset:0;z-index:80;background:rgba(10,18,30,0.96);overflow-y:auto;padding:22px 16px 90px;';
  actOverlay.innerHTML = `
   <div style="max-width:640px;margin:0 auto;font-family:Arial;color:#e6f1fa;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
      <h2 style="margin:0;font-size:20px;color:#fff;">Calming activities</h2>
      <button onclick="closeActivities()" style="background:rgba(255,255,255,0.12);color:#cfe3f2;border:1px solid rgba(255,255,255,0.25);border-radius:999px;padding:8px 18px;font-size:14px;cursor:pointer;">Back</button>
    </div>
    <div style="font-size:12.5px;color:#9db8cf;margin-bottom:14px;">Small things that help a racing mind. Your music keeps playing. Pick anything.</div>
    <div id="act-menu" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;"></div>
    <div id="act-stage" style="margin-top:16px;"></div>
   </div>`;
  document.body.appendChild(actOverlay);
  gardenBar();
  const acts=[
    ['breathe','Breathing circle','Slow the body directly'],
    ['ground','5-4-3-2-1 senses','Come back to the room'],
    ['words','Word Play','Find the calm word'],
    ['shapes','Shape match','Busy the picture-mind'],
    ['trace','Slow trace','Follow the drifting light'],
    ['stars','Count the stars','A gentle anchor'],
    ['release','Body release','Unclench, head to toe'],
    ['good','Three good things','Small true lights'],
  ];
  const menu = actOverlay.querySelector('#act-menu');
  menu.innerHTML = acts.map(a=>`<button onclick="startAct('${a[0]}')" style="text-align:left;background:rgba(255,255,255,0.07);border:1px solid rgba(255,255,255,0.18);border-radius:14px;padding:13px;cursor:pointer;color:#e6f1fa;">
     <b style="font-size:14.5px;">${a[1]}</b><span style="display:block;font-size:11.5px;color:#9db8cf;margin-top:3px;">${a[2]}</span></button>`).join('');
  // gentle re-engagement after 10 minutes of play
  actTimers.push(setInterval(()=>{
    if (!actOverlay || actOverlay.style.display==='none' || actReengaged) return;
    if (Date.now()-actOpenedAt > 10*60*1000){
      actReengaged = true; metric('reengage_prompt');
      const bar = document.createElement('div');
      bar.style.cssText='position:sticky;bottom:0;margin-top:18px;background:rgba(111,179,212,0.95);color:#0c1322;border-radius:14px;padding:14px 16px;font-size:14px;text-align:center;';
      bar.innerHTML = (gardenBlooms>0 ? 'Look at what you grew \u2014 '+gardenBlooms+' blooms. ' : '') + `I'm still right here with you. Want to talk for a moment?
        <div style="margin-top:10px;"><button onclick="closeActivities();document.getElementById('message')&&document.getElementById('message').focus({preventScroll:true});" style="background:#0c1322;color:#fff;border:0;border-radius:999px;padding:9px 20px;margin:0 6px;cursor:pointer;">Let's talk</button>
        <button onclick="this.closest('div').parentNode.remove();actOpenedAt=Date.now();actReengaged=false;" style="background:rgba(12,19,34,0.15);color:#0c1322;border:1px solid #0c1322;border-radius:999px;padding:9px 20px;margin:0 6px;cursor:pointer;">Keep playing</button></div>`;
      actOverlay.firstElementChild.appendChild(bar);
    }
  },20000));
}
function closeActivities(){ if(actOverlay) actOverlay.style.display='none'; actClearTimers(); }
function actStage(){ const st=actOverlay.querySelector('#act-stage'); st.innerHTML=''; return st; }
function startAct(name){
  metric('activity_open', name); actClearTimers();
  // re-add re-engagement timer since actClearTimers wiped it
  const st = actStage();
  if (name==='breathe'){
    st.innerHTML = `<div style="text-align:center;padding:10px;">
      <div style="position:relative;width:180px;height:180px;margin:14px auto;">
        <div id="br-aura" style="position:absolute;inset:-14px;border-radius:50%;border:2px solid rgba(207,233,255,0.35);"></div>
        <div id="br-circle" style="position:absolute;inset:0;border-radius:50%;background:radial-gradient(circle,#6fb3d4,#2a5a7a);transition:transform 5s ease-in-out;display:flex;align-items:center;justify-content:center;flex-direction:column;">
          <b id="br-bpm" style="font-size:30px;color:#fff;">--</b>
          <span style="font-size:10.5px;color:#cfe9ff;">your heart</span>
        </div>
      </div>
      <div id="br-word" style="font-size:22px;color:#fff;">Breathe in&hellip;</div>
      <div id="br-msg" style="font-size:12.5px;color:#9db8cf;margin-top:6px;min-height:18px;">In for 5 &middot; hold for 5 &middot; out for 5. Watch your own heart answer.</div></div>`;
    const c=st.querySelector('#br-circle'), w=st.querySelector('#br-word');
    let phase=0, cycles=0; const run=()=>{ if(!c.isConnected) return;
      if(phase===0){ w.textContent='Breathe in\u2026'; c.style.transform='scale(1.45)'; }
      if(phase===1){ w.textContent='Hold\u2026'; }
      if(phase===2){ w.textContent='Let it out\u2026'; c.style.transform='scale(1)';
        cycles++; if (cycles % 3 === 0) bloom(); }
      phase=(phase+1)%3; };
    run(); actTimers.push(setInterval(run,5000));
    // TRUE BIOFEEDBACK: the person's live heart rate inside the circle, the
    // aura pulsing at their actual rhythm, drops celebrated as they happen.
    let brStartBpm = 0;
    actTimers.push(setInterval(()=>{
      const el = st.querySelector('#br-bpm'); if (!el || !el.isConnected) return;
      const bpm = window._heartBPM && window._heartBPM > 40 ? Math.round(window._heartBPM) : 0;
      el.textContent = bpm || '--';
      if (bpm){
        if (!brStartBpm) brStartBpm = bpm;
        const aura = st.querySelector('#br-aura');
        if (aura){ aura.animate([{transform:'scale(1)',opacity:0.5},{transform:'scale(1.08)',opacity:0.15}],
          { duration: Math.max(350, 60000/bpm), iterations: 1 }); }
        const msg = st.querySelector('#br-msg');
        if (msg && brStartBpm - bpm >= 5){
          msg.textContent = brStartBpm + ' \u2192 ' + bpm + ' \u2014 your heart is listening. Keep going.';
          msg.style.color = '#7dd3a8';
        }
      }
    }, 1500));
  }
  if (name==='ground'){
    const steps=[['5 things you can SEE','Look around slowly. Name five things — their color, their shape.'],
      ['4 things you can TOUCH','The chair. Your sleeve. The floor under your feet. Really feel four.'],
      ['3 things you can HEAR','The room. The music. Something far away.'],
      ['2 things you can SMELL','Or two smells you like remembering.'],
      ['1 thing you can TASTE','Even just the inside of your own breath.'],
      ['One slow breath','You are here. This moment is safe enough to stand in.']];
    let i=0; st.innerHTML=`<div style="text-align:center;padding:16px;"><div id="g-title" style="font-size:22px;color:#fff;"></div>
      <div id="g-sub" style="font-size:14px;color:#b9d0e2;margin:12px 0 18px;line-height:1.6;"></div>
      <button id="g-next" style="background:#6fb3d4;color:#0c1322;border:0;border-radius:999px;padding:11px 28px;font-size:15px;font-weight:700;cursor:pointer;">Done &mdash; next</button></div>`;
    const show=()=>{ st.querySelector('#g-title').textContent=steps[i][0]; st.querySelector('#g-sub').textContent=steps[i][1];
      if(i===steps.length-1) st.querySelector('#g-next').textContent='Finish'; };
    st.querySelector('#g-next').onclick=()=>{ bloom(); i++; if(i>=steps.length){ startAct('menuDone'); return;} show(); };
    show();
  }
  if (name==='words'){ if(!wordsPanel) buildWordsPanel(); wordsPanel.style.display='block'; st.appendChild(wordsPanel); wordsRound(); }
  if (name==='shapes'){
    st.innerHTML=`<div style="text-align:center;"><div id="sh-prompt" style="font-size:15px;color:#cfe3f2;margin:8px 0 12px;"></div>
      <div id="sh-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;max-width:340px;margin:0 auto;"></div></div>`;
    const SH=['\u25CF','\u25A0','\u25B2','\u2666','\u2605','\u2B22']; const CO=['#7dd3a8','#6fb3d4','#d4a86f','#c78ad4'];
    const round=()=>{ const tS=SH[Math.floor(Math.random()*SH.length)], tC=CO[Math.floor(Math.random()*CO.length)];
      st.querySelector('#sh-prompt').innerHTML='Find: <span style="color:'+tC+';font-size:26px;">'+tS+'</span>';
      const cells=[{s:tS,c:tC}]; while(cells.length<8){ const s2=SH[Math.floor(Math.random()*SH.length)], c2=CO[Math.floor(Math.random()*CO.length)];
        if(!(s2===tS&&c2===tC)) cells.push({s:s2,c:c2}); }
      cells.sort(()=>Math.random()-0.5);
      st.querySelector('#sh-grid').innerHTML=cells.map(x=>`<button onclick="(function(b){ if(b.dataset.hit==='1'){ b.style.background='rgba(125,211,168,0.4)'; bloom(); setTimeout(window._shRound,700);} })(this)" data-hit="${x.s===tS&&x.c===tC?1:0}" style="font-size:30px;padding:14px 6px;border-radius:12px;border:1px solid rgba(255,255,255,0.2);background:rgba(255,255,255,0.07);color:${x.c};cursor:pointer;">${x.s}</button>`).join('');
    };
    window._shRound=round; round();
  }
  if (name==='trace'){
    st.innerHTML=`<div style="text-align:center;"><div style="font-size:13px;color:#9db8cf;margin-bottom:8px;">Rest your finger or cursor on the light, and drift with it.</div>
    <canvas id="tr-cv" width="600" height="300" style="width:100%;max-width:600px;border-radius:14px;background:radial-gradient(circle at 50% 50%, #16314a, #0c1322);touch-action:none;"></canvas></div>`;
    const cv=st.querySelector('#tr-cv'), ctx=cv.getContext('2d'); let t0=performance.now();
    const draw=()=>{ if(!cv.isConnected) return; const t=(performance.now()-t0)/1000;
      ctx.fillStyle='rgba(12,19,34,0.18)'; ctx.fillRect(0,0,600,300);
      const x=300+220*Math.sin(t*0.28), y=150+90*Math.sin(t*0.19+1.3);
      const g=ctx.createRadialGradient(x,y,2,x,y,26); g.addColorStop(0,'#cfe9ff'); g.addColorStop(1,'rgba(111,179,212,0)');
      ctx.fillStyle=g; ctx.beginPath(); ctx.arc(x,y,26,0,7); ctx.fill(); requestAnimationFrame(draw); };
    draw();
  }
  if (name==='stars'){
    st.innerHTML=`<div style="text-align:center;"><div id="st-p" style="font-size:14px;color:#cfe3f2;margin-bottom:10px;">Stars will appear, slowly. Count them, then answer.</div>
      <div id="st-sky" style="position:relative;height:220px;border-radius:14px;background:radial-gradient(circle at 50% 40%, #16314a, #0c1322);"></div>
      <div id="st-ans" style="margin-top:12px;"></div></div>`;
    const n=4+Math.floor(Math.random()*5); const sky=st.querySelector('#st-sky');
    for(let i=0;i<n;i++){ actTimers.push(setTimeout(()=>{ if(!sky.isConnected)return; const d=document.createElement('div');
      d.style.cssText='position:absolute;width:8px;height:8px;border-radius:50%;background:#fffbe8;box-shadow:0 0 12px #fffbe8;opacity:0;transition:opacity 2s;';
      d.style.left=(8+Math.random()*84)+'%'; d.style.top=(10+Math.random()*75)+'%'; sky.appendChild(d);
      requestAnimationFrame(()=>d.style.opacity='0.95'); }, 1200+i*1700)); }
    actTimers.push(setTimeout(()=>{ if(!st.isConnected)return; const ans=st.querySelector('#st-ans');
      ans.innerHTML=[n-1,n,n+1].sort(()=>Math.random()-0.5).map(v=>`<button onclick="(function(b){ if(+b.dataset.v===${n}){ b.style.background='rgba(125,211,168,0.5)'; document.getElementById('st-p').textContent='Yes — '+${n}+' stars. Nicely counted.'; bloom(); setTimeout(()=>startAct('stars'),1600);} else { b.style.background='rgba(180,90,90,0.3)'; } })(this)" data-v="${v}" style="font-size:18px;margin:0 8px;padding:10px 22px;border-radius:12px;border:1px solid rgba(255,255,255,0.25);background:rgba(255,255,255,0.08);color:#e6f1fa;cursor:pointer;">${v}</button>`).join('');
    }, 1200+n*1700+800));
  }
  if (name==='release'){
    const steps=[['Your hands','Make gentle fists\u2026 hold\u2026 and let them fall open.'],
      ['Your shoulders','Lift them toward your ears\u2026 hold\u2026 and let them drop.'],
      ['Your jaw','Press lips together lightly\u2026 and let the jaw hang loose.'],
      ['Your brow','Raise your eyebrows\u2026 hold\u2026 and smooth them down.'],
      ['Your stomach','Tighten gently\u2026 hold\u2026 and soften.'],
      ['Your legs','Press your feet into the floor\u2026 and release.'],
      ['All of you','One slow breath. Notice what feels 5% looser than before.']];
    let i=0; st.innerHTML=`<div style="text-align:center;padding:16px;"><div id="r-t" style="font-size:22px;color:#fff;"></div>
      <div id="r-s" style="font-size:14px;color:#b9d0e2;margin:12px 0 18px;line-height:1.6;"></div>
      <button id="r-n" style="background:#6fb3d4;color:#0c1322;border:0;border-radius:999px;padding:11px 28px;font-size:15px;font-weight:700;cursor:pointer;">Released &mdash; next</button></div>`;
    const show=()=>{ st.querySelector('#r-t').textContent=steps[i][0]; st.querySelector('#r-s').textContent=steps[i][1];
      if(i===steps.length-1) st.querySelector('#r-n').textContent='Finish'; };
    st.querySelector('#r-n').onclick=()=>{ bloom(); i++; if(i>=steps.length){ startAct('menuDone'); return;} show(); };
    show();
  }
  if (name==='good'){
    st.innerHTML=`<div style="max-width:420px;margin:0 auto;text-align:center;">
      <div style="font-size:14px;color:#cfe3f2;margin-bottom:12px;">Three small true things that are good — today, this week, ever. Nothing you write here is saved or sent anywhere.</div>
      ${[1,2,3].map(i=>`<input id="tg-${i}" placeholder="Good thing ${i}" style="width:100%;box-sizing:border-box;margin:6px 0;padding:12px;border-radius:10px;border:1px solid rgba(255,255,255,0.25);background:rgba(255,255,255,0.08);color:#fff;font-size:15px;">`).join('')}
      <button onclick="(function(){ const v=[1,2,3].map(i=>document.getElementById('tg-'+i).value.trim()).filter(Boolean); const m=document.getElementById('tg-msg'); m.textContent = v.length ? 'Those are real. Carry them with you \u2014 they came from you.' : 'Even one small thing counts. Try one.'; if (v.length) bloom(); })()" style="margin-top:10px;background:#6fb3d4;color:#0c1322;border:0;border-radius:999px;padding:11px 28px;font-size:15px;font-weight:700;cursor:pointer;">Hold onto these</button>
      <div id="tg-msg" style="margin-top:12px;color:#7dd3a8;font-size:14px;"></div></div>`;
  }
  if (name==='menuDone'){
    st.innerHTML=`<div style="text-align:center;padding:20px;color:#7dd3a8;font-size:16px;">Well done. Pick another, or press Back when you're ready.</div>`;
  }
}

// ================= WORD PLAY — gentle focus game =================
// A calm word appears; find it among eight. Right answer glows soft green,
// a new round follows. Occupies a racing mind without stressing it.
const WORD_BANK = ['RIVER','MEADOW','CANDLE','HARBOR','WILLOW','LANTERN','BREEZE','GARDEN',
                   'PEBBLE','FEATHER','MOON','SUNRISE','OCEAN','MAPLE','VALLEY','CLOUD',
                   'EMBER','ORCHARD','STARLIGHT','RAIN'];
let wordsPanel = null, wordsTarget = '';
function buildWordsPanel(){
  const anchorEl = document.querySelector('.calm-tab');
  const host = (anchorEl && anchorEl.closest('div') && anchorEl.closest('div').parentNode) || document.body;
  wordsPanel = document.createElement('div');
  wordsPanel.id = 'words-panel';
  wordsPanel.style.cssText = 'padding:14px;text-align:center;';
  wordsPanel.innerHTML = '<div id="words-prompt" style="font-size:14px;color:#cfe3f2;margin-bottom:12px;"></div>'
    + '<div id="words-grid" style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;max-width:340px;margin:0 auto;"></div>';
  host.appendChild(wordsPanel);
  wordsRound();
}
function wordsRound(){
  if (!wordsPanel) return;
  const pool = WORD_BANK.slice().sort(()=>Math.random()-0.5).slice(0,8);
  wordsTarget = pool[Math.floor(Math.random()*pool.length)];
  document.getElementById('words-prompt').innerHTML = 'Find: <b style="font-size:19px;letter-spacing:2px;color:#fff;">' + wordsTarget + '</b>';
  const grid = document.getElementById('words-grid');
  grid.innerHTML = pool.slice().sort(()=>Math.random()-0.5).map(w =>
    '<button onclick="wordsPick(this)" data-w="'+w+'" style="padding:13px 6px;border-radius:12px;border:1px solid rgba(255,255,255,0.25);'
    + 'background:rgba(255,255,255,0.08);color:#e6f1fa;font-size:15px;letter-spacing:1px;cursor:pointer;transition:all 0.25s ease;">'+w+'</button>'
  ).join('');
}
function wordsPick(btn){
  if (btn.dataset.w === wordsTarget){
    btn.style.background = 'rgba(90,180,130,0.55)'; btn.style.borderColor = '#7dd3a8';
    metric('wordplay'); if (typeof bloom==='function') bloom();
    setTimeout(wordsRound, 900);
  } else {
    btn.style.background = 'rgba(180,90,90,0.25)';
    setTimeout(()=>{ btn.style.background = 'rgba(255,255,255,0.08)'; }, 450);
  }
}

// ================= MEDIAPIPE 52-MOVEMENT READER (with iris/gaze) =================
let mpLandmarker = null, mpActive = false, mpGazeAwayRun = 0;
(async function loadMediaPipe(){
  try {
    const vision = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14');
    const files = await vision.FilesetResolver.forVisionTasks(
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm');
    mpLandmarker = await vision.FaceLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath:
        'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task' },
      outputFaceBlendshapes: true, runningMode: 'VIDEO', numFaces: 1 });
    mpActive = true;
    console.log('[Face] MediaPipe 52-movement reader active');
    setInterval(mpTick, 500);
  } catch (e) { console.log('[Face] MediaPipe unavailable, staying on fallback reader:', e); }
})();

function mpTick(){
  if (!mpActive || !mpLandmarker) return;
  if (window._lastTypedAt && (performance.now() - window._lastTypedAt) < 700) return;
  const video = document.getElementById('visual-preview');
  if (!video || !video.videoWidth) return;
  let res;
  try { res = mpLandmarker.detectForVideo(video, performance.now()); } catch(e){ return; }
  const shapes = (res && res.faceBlendshapes && res.faceBlendshapes[0]) ? res.faceBlendshapes[0].categories : null;
  if (!shapes){
    if (window._faceWasPresent){
      window._faceLostRun = (window._faceLostRun||0) + 1;
      if (window._faceLostRun === 3) metric('distraction');
    }
    window._heartFaceBox = null;
    window._heartRegions = null;
    // Face gone -> let the reading re-acquire instead of holding a stale number.
    window._heartStale = (window._heartStale||0) + 1;
    if (window._heartStale > 20){ heartBPM = 0; window._heartBPM = 0; }
    return;
  }
  const b = {}; shapes.forEach(c => b[c.categoryName] = c.score);
  // --- Movements -> the score keys the whole system already speaks ---
  const angry = Math.min(1, (b.browDownLeft + b.browDownRight)/2 * 1.4 + (b.jawClench||0)*0.6 + (b.mouthPressLeft + b.mouthPressRight)/2*0.5);
  const happy = Math.min(1, (b.mouthSmileLeft + b.mouthSmileRight)/2 * 1.3 + (b.cheekSquintLeft + b.cheekSquintRight)/2*0.4);
  const sad = Math.min(1, (b.browInnerUp||0)*0.9 + (b.mouthFrownLeft + b.mouthFrownRight)/2 * 1.1);
  const surprised = Math.min(1, (b.eyeWideLeft + b.eyeWideRight)/2 * 1.1 + (b.jawOpen||0)*0.7 + (b.browOuterUpLeft + b.browOuterUpRight)/2*0.5);
  const disgusted = Math.min(1, (b.noseSneerLeft + b.noseSneerRight)/2 * 1.5 + (b.mouthUpperUpLeft + b.mouthUpperUpRight)/2*0.4);
  const fearful = Math.min(1, ((b.eyeWideLeft + b.eyeWideRight)/2 * 0.6 + (b.browInnerUp||0)*0.5));
  const activity = angry + happy + sad + surprised + disgusted;
  const neutral = Math.max(0, 1 - Math.min(1, activity));
  faceEmotionScores = { angry, happy, sad, surprised, disgusted, fearful, neutral };
  let top = 'neutral', tv = neutral;
  for (const [k,v] of Object.entries(faceEmotionScores)) if (v > tv){ top = k; tv = v; }
  if (top !== currentFaceEmotion) metric('face_shift');
  currentFaceEmotion = top;
  window._faceWasPresent = true; window._faceLostRun = 0;
  // --- IRIS / GAZE: eyes fleeing while the face stays = avoidance ---
  const gazeAway = Math.max((b.eyeLookOutLeft||0)+(b.eyeLookInRight||0), (b.eyeLookOutRight||0)+(b.eyeLookInLeft||0),
                            ((b.eyeLookDownLeft||0)+(b.eyeLookDownRight||0)));
  if (gazeAway > 0.9){ mpGazeAwayRun++; if (mpGazeAwayRun === 4) metric('gaze_aversion'); }
  else mpGazeAwayRun = 0;
  window._eyesClosed = ((b.eyeBlinkLeft||0)+(b.eyeBlinkRight||0))/2 > 0.6;
  // --- Heart regions from landmarks: forehead + both cheeks (proven, reliable),
  //     plus experimental sub-zones of stable skin NEAR eyes/mouth (research). ---
  const lm = res.faceLandmarks && res.faceLandmarks[0];
  if (lm){
    const W = video.videoWidth, H = video.videoHeight;
    const P = (i, sx, sy, sw, sh) => lm[i] ? { x: lm[i].x*W - W*sw/2 + sx*W, y: lm[i].y*H - H*sh/2 + sy*H, w: W*sw, h: H*sh } : null;
    window._heartRegions = {
      // RELIABLE trio — eyes and mouth excluded
      forehead:   P(10, 0, 0.03, 0.13, 0.06),
      cheekLeft:  P(50, 0, 0,    0.08, 0.06),
      cheekRight: P(280,0, 0,    0.08, 0.06),
      // EXPERIMENTAL — stable skin beside the noisy zones (your frontier idea)
      underEyeL:  P(230,0, 0.015,0.05, 0.028),
      underEyeR:  P(450,0, 0.015,0.05, 0.028),
      noseBridge: P(6,  0, 0,    0.045,0.05),
      mouthSideL: P(216,0, 0,    0.045,0.045),
      mouthSideR: P(436,0, 0,    0.045,0.045)
    };
    // keep the legacy single box pointing at the forehead for safety
    window._heartFaceBox = window._heartRegions.forehead;
  }
}

// ================= HEART ENGINE v2 — MULTI-REGION (webcam pulse) =================
// Reads THREE reliable skin regions (forehead + both cheeks), runs POS on each,
// and only trusts the number when the regions AGREE. Also samples experimental
// sub-zones near the eyes/mouth and logs how well each agrees with the reliable
// signal — so your own data reveals which sub-zones are trustworthy over time.
const HR_REGIONS = ['forehead','cheekLeft','cheekRight'];
const HR_EXPERIMENTAL = ['underEyeL','underEyeR','noseBridge','mouthSideL','mouthSideR'];
const hrData = {}; // name -> {R:[],G:[],B:[],t:[]}
let heartBPM = 0, heartBaseline = 0, hrCanvas = null;
let _regionAgreement = 0, _expScores = {};

function sampleRegion(video, box){
  if (!box || box.w < 4 || box.h < 4) return null;
  if (!hrCanvas){ hrCanvas = document.createElement('canvas'); hrCanvas.width = 40; hrCanvas.height = 20; }
  const ctx = hrCanvas.getContext('2d', { willReadFrequently: true });
  try { ctx.drawImage(video, box.x, box.y, box.w, box.h, 0, 0, 40, 20); } catch(e){ return null; }
  const d = ctx.getImageData(0,0,40,20).data;
  let r=0,g=0,b=0,skin=0,cnt=0;
  for (let i=0;i<d.length;i+=4){
    const R=d[i],G=d[i+1],B=d[i+2];
    // simple skin test: R>G>B and R high enough — rejects hair/shadow/cloth
    if (R>60 && R>G && G>B && (R-B)>12){ r+=R; g+=G; b+=B; skin++; }
    cnt++;
  }
  if (skin < cnt*0.35) return null; // patch isn't mostly skin -> discard
  return { r:r/skin, g:g/skin, b:b/skin };
}

function heartTick(){
  const video = document.getElementById('visual-preview');
  const regions = window._heartRegions;
  if (!video || !video.videoWidth || !regions) return;
  const now = performance.now();
  window._heartStale = 0;
  const all = HR_REGIONS.concat(HR_EXPERIMENTAL);
  for (const name of all){
    const s = sampleRegion(video, regions[name]);
    if (!s) continue;
    const D = hrData[name] || (hrData[name] = {R:[],G:[],B:[],t:[]});
    D.R.push(s.r); D.G.push(s.g); D.B.push(s.b); D.t.push(now);
    // Rolling ~14s window (fresh data only) — prevents freezing on stale samples.
    const CUTOFF = now - 14000;
    while (D.t.length && D.t[0] < CUTOFF){ D.R.shift(); D.G.shift(); D.B.shift(); D.t.shift(); }
    if (D.R.length > 320){ D.R.shift(); D.G.shift(); D.B.shift(); D.t.shift(); }
  }
}

// POS on one region's buffers -> {bpm, power}
function posEstimate(D){
  const n = D.R.length;
  if (n < 150) return null;
  const dur = (D.t[n-1]-D.t[0])/1000; if (dur < 10) return null;
  const fs = n/dur;
  const mean = a => a.reduce((x,y)=>x+y,0)/a.length;
  const mR=mean(D.R), mG=mean(D.G), mB=mean(D.B);
  if (mR<=0||mG<=0||mB<=0) return null;
  const Rn=D.R.map(v=>v/mR-1), Gn=D.G.map(v=>v/mG-1), Bn=D.B.map(v=>v/mB-1);
  const S1=[],S2=[];
  for (let i=0;i<n;i++){ S1.push(Gn[i]-Bn[i]); S2.push(Gn[i]+Bn[i]-2*Rn[i]); }
  const std=a=>{const m=mean(a);return Math.sqrt(a.reduce((x,y)=>x+(y-m)*(y-m),0)/a.length)||1e-6;};
  const alpha=std(S1)/std(S2);
  let sig=S1.map((v,i)=>v+alpha*S2[i]);
  const ms=mean(sig); sig=sig.map(v=>v-ms);
  for (let i=1;i<n;i++) sig[i]=sig[i]-0.92*sig[i-1];
  let bestBpm=0,bestPow=0;
  for (let bpm=42;bpm<=170;bpm+=1){
    const f=bpm/60; let re=0,im=0;
    for (let i=0;i<n;i++){ const ph=2*Math.PI*f*(i/fs); re+=sig[i]*Math.cos(ph); im+=sig[i]*Math.sin(ph); }
    const pow=re*re+im*im; if (pow>bestPow){bestPow=pow;bestBpm=bpm;}
  }
  return bestBpm ? { bpm:bestBpm, power:bestPow } : null;
}

function heartEstimate(){
  // Reliable trio
  const est = {};
  for (const name of HR_REGIONS){ if (hrData[name]){ const e = posEstimate(hrData[name]); if (e) est[name]=e; } }
  const bpms = Object.values(est).map(e=>e.bpm);
  if (bpms.length === 0) return;
  if (bpms.length === 1){
    // single region: accept but mark low confidence, and keep it moving
    heartBPM = heartBPM ? (heartBPM*0.5 + bpms[0]*0.5) : bpms[0];
    window._heartBPM = heartBPM; window._heartConfidence = 0.5; window._heartUpdatedAt = Date.now();
    if (!heartBaseline && hrData.forehead && hrData.forehead.t.length > 150) heartBaseline = heartBPM;
    return;
  }
  // agreement: how tight are the regions? (median + spread)
  bpms.sort((a,b)=>a-b);
  const median = bpms[Math.floor(bpms.length/2)];
  const spread = Math.max(...bpms) - Math.min(...bpms);
  _regionAgreement = spread <= 10 ? 1 : (spread <= 20 ? 0.5 : 0);
  if (_regionAgreement === 0){
    // regions disagree -> the current number is unreliable. Count strikes;
    // after sustained disagreement, CLEAR so it re-acquires (never freeze).
    window._hrDisagree = (window._hrDisagree||0) + 1;
    if (window._hrDisagree > 6){ heartBPM = 0; window._heartBPM = 0; window._hrDisagree = 0;
      for (const k in hrData){ hrData[k] = {R:[],G:[],B:[],t:[]}; } }
    return;
  }
  window._hrDisagree = 0;
  // If the new median is wildly higher than a settled reading, trust it less
  // (prevents a noise spike from locking at 150).
  let blend = 0.5;
  if (heartBPM && median > heartBPM + 30) blend = 0.2;
  heartBPM = heartBPM ? (heartBPM*(1-blend) + median*blend) : median;
  if (!heartBaseline && (hrData.forehead && hrData.forehead.t.length > 150)) heartBaseline = heartBPM;
  window._heartBPM = heartBPM; window._heartBaseline = heartBaseline; window._heartConfidence = _regionAgreement;
  window._heartUpdatedAt = Date.now();
  // EXPERIMENTAL sub-zones: how close is each to the trusted median? (learning)
  for (const name of HR_EXPERIMENTAL){
    if (hrData[name]){ const e = posEstimate(hrData[name]); if (e){
      const err = Math.abs(e.bpm - median);
      _expScores[name] = _expScores[name] || {n:0, close:0};
      _expScores[name].n++;
      if (err <= 6) _expScores[name].close++;
    }}
  }
  window._expScores = _expScores;
}
let _hrReported = 0;
function heartReport(){
  if (heartBPM > 40 && Date.now() - _hrReported > 60000){
    _hrReported = Date.now();
    metric('heart_read', Math.round(heartBPM));
    // Log which experimental sub-zones tracked the truth (research learning)
    if (window._expScores){
      for (const [zone, sc] of Object.entries(window._expScores)){
        if (sc.n >= 5){ metric('subzone', zone + '|' + Math.round(100*sc.close/sc.n)); }
      }
    }
  }
}
setInterval(heartTick, 66);       // ~15 samples per second
setInterval(heartEstimate, 3000); // re-estimate every 3s — fresher readings
setInterval(heartReport, 15000);
// Show the person their own rhythm — watching a number ease downward is a
// proven calming aid (biofeedback). Appears only once the reading is stable.
(function heartChip(){
  const chip = document.createElement('div');
  chip.id = 'heart-chip';
  chip.style.cssText = 'position:fixed;bottom:22px;right:22px;z-index:55;display:none;'
    + 'background:rgba(255,255,255,0.92);border-radius:999px;padding:12px 22px;'
    + 'font-family:Arial;font-size:22px;color:#8a4653;box-shadow:0 8px 26px rgba(40,20,30,0.2);';
  chip.innerHTML = '<span id="heart-beat" style="display:inline-block;font-size:24px;">&#10084;&#65039;</span> <b id="heart-num" style="font-size:26px;">--</b> <span class="hr-label" style="font-size:13px;color:#a98790;">bpm</span>';
  document.body.appendChild(chip);
  setInterval(()=>{
    if (window._heartBPM && window._heartBPM > 40){
      chip.style.display = 'block';
      document.getElementById('heart-num').textContent = Math.round(window._heartBPM);
      const b = document.getElementById('heart-beat');
      // pulse the heart gently so it feels alive — no words, just the number
      b.style.transition = 'transform 0.15s ease'; b.style.transform = 'scale(1.28)';
      setTimeout(()=>{ b.style.transform = 'scale(1)'; }, 150);
    }
  }, 1500);
})();

// --- Face detection ---
async function loadFaceModels() {
  try {
    await faceapi.nets.tinyFaceDetector.loadFromUri(FACE_API_MODELS);
    await faceapi.nets.faceExpressionNet.loadFromUri(FACE_API_MODELS);
    faceReady = true;
  } catch (e) { console.log('[Face] Models unavailable:', e); }
}
async function detectFaceEmotion() {
  if (mpActive) return; // the 52-movement reader has the watch
  if (!faceReady) return;
  if (window._faceBusy) return;  // don't let detections pile up on slower phones
  // Don't compete with the keyboard: if the person typed very recently, skip
  // this cycle so typing stays instant (short window so we still catch changes).
  if (window._lastTypedAt && (performance.now() - window._lastTypedAt) < 700) return;
  const video = document.getElementById('visual-preview');
  if (!video || !video.videoWidth) return;
  window._faceBusy = true;
  try {
    const det = await faceapi.detectSingleFace(video, new faceapi.TinyFaceDetectorOptions()).withFaceExpressions();
    if (!det && window._faceWasPresent){
      // Face was engaged, now it's gone: looked away, turned the head, left.
      window._faceLostRun = (window._faceLostRun||0) + 1;
      if (window._faceLostRun === 3) metric('distraction'); // ~2s of looking away
    }
    if (det && det.expressions) {
      faceEmotionScores = det.expressions;
      let top = 'neutral', topVal = 0;
      for (const [k, v] of Object.entries(det.expressions)) { if (v > topVal) { top = k; topVal = v; } }
      window._faceWasPresent = true;
      window._faceLostRun = 0;
      if (top !== currentFaceEmotion) metric('face_shift');
      currentFaceEmotion = top;
      // The reading stays SILENT — it steers the sound in the background, but
      // no label is ever shown to the person. A wrong label ("you look angry")
      // can inflame someone in crisis. Readings will surface only in the
      // founder's private admin log (coming with the admin dashboard).
    }
  } catch (e) {}
  finally { window._faceBusy = false; }
}
let faceInterval = null;
// Detect the face often — subtle emotion flickers across a face in fractions
// of a second, so we look ~every 0.6s to catch the ticks. The SOUND still
// responds gently (frequent detection + smoothed response = sensitive but not jittery).
function startFaceLoop() { if (!faceInterval) faceInterval = setInterval(detectFaceEmotion, 600); }

// ---------------------------------------------------------------------------
// THE ADAPTIVE LOOP (free version) — the sound RESPONDS to the person in real
// time, using the face + voice signals we already capture. No wearable, no API,
// no cost. This is the first working version of the responsive-sound idea:
// like the quiet authority in the car, it responds continuously and gently,
// never in jarring jumps.
//
// It reads how activated the person seems (agitation vs. flat/down vs. calm),
// smooths it over time so it never lurches, and nudges the music: a touch
// softer and steadier for agitation (settle them), a touch warmer/present for
// flatness (reach them), easing back toward gentle calm as they settle.
// ---------------------------------------------------------------------------
let adaptiveInterval = null;
let adaptiveArousal = 0.5;   // 0 = very calm/flat, 1 = very activated. Smoothed.
let adaptiveLaneNow = 'calm'; // which lane the adaptive loop currently favors
let adaptiveLastSwitch = 0;

function readArousalSignal() {
  // Heart above its own resting baseline = the body's testimony of activation.
  let heartPush = 0;
  if (window._heartBPM && window._heartBaseline){
    heartPush = Math.max(0, Math.min(0.3, (window._heartBPM - window._heartBaseline) / 45));
  }
  // Combine face + voice into a single 0..1 "activation" estimate.
  // Face: anger/fear/disgust push UP; sad pushes DOWN-but-present; happy/neutral calm.
  let faceUp = 0, faceDown = 0;
  const s = faceEmotionScores || {};
  faceUp = (s.angry||0)*1.0 + (s.fearful||0)*0.9 + (s.disgusted||0)*0.6 + (s.surprised||0)*0.4;
  faceDown = (s.sad||0)*1.0;
  // Voice: high energy + high pitch variance + tremor => more activated.
  const v = voiceFeatures || {};
  const voiceUp = ((v.energy||0.5)*0.5 + (v.pitch_variance||0.5)*0.3 + (v.tremor||0)*0.6);
  // Blend into an instantaneous arousal estimate.
  let inst = Math.min(1, Math.max(0, faceUp*0.6 + voiceUp*0.5));
  // "Down/flat" is low arousal but still needs reaching — track it separately.
  window._adaptiveDown = faceDown;
  return Math.min(1, (inst) + heartPush);
}

function adaptiveTick() {
  if (!ambientTracks.length) return;
  const inst = readArousalSignal();
  // Smooth heavily so the sound never lurches — gentle, like quiet authority.
  adaptiveArousal = adaptiveArousal*0.85 + inst*0.15;
  const down = (window._adaptiveDown || 0);

  // 1) Continuously nudge VOLUME within a gentle band. More activated -> a touch
  //    softer and steadier (don't add to their noise). Calm -> normal presence.
  const deck = getActiveDeck();
  if (deck && !crossfading) {
    const band = 0.04; // small, never dramatic
    let target = TARGET_VOL - (adaptiveArousal - 0.5) * band; // higher arousal => softer
    target = Math.max(TARGET_VOL - band, Math.min(TARGET_VOL + band*0.5, target));
    // ease toward target
    deck.volume = deck.volume + (target - deck.volume) * 0.2;
  }

  // 2) When the read is clearly and persistently one way, gently shift the LANE
  //    (deep-calm to bring an activated person DOWN; lifting to reach a flat/
  //    down person UP). Rate-limited so it can't flip back and forth.
  const now = Date.now();
  if (now - adaptiveLastSwitch < 15000) return; // at most one shift per 15s
  let want = null;
  if (adaptiveArousal > 0.60 && adaptiveLaneNow !== 'deepcalm') want = 'deepcalm';
  else if (down > 0.55 && adaptiveArousal < 0.45 && adaptiveLaneNow !== 'lifting') want = 'lifting';
  else if (adaptiveArousal < 0.35 && down < 0.3 && adaptiveLaneNow !== 'calm') want = 'calm';
  if (want) {
    adaptiveLaneNow = want;
    adaptiveLastSwitch = now;
    const emo = want === 'deepcalm' ? 'angry' : (want === 'lifting' ? 'sad' : 'calm');
    fetch('/api/zenisys/ambient?emotion=' + encodeURIComponent(emo))
      .then(r => r.json())
      .then(d => {
        const tracks = d.tracks || [];
        if (tracks.length) {
          ambientTracks = tracks; ambientIndex = 0;
          switchAmbient(tracks[0].url, tracks[0].name);
          metric('lane_switch');
          // The view answers too: agitated -> stillness (moons); low -> warmth (sun).
          if (!sceneUserChose){
            const sceneFor = { deepcalm: ['moon','moonleaf','horizon'],
                               lifting: ['sunflower','sunset','garden'],
                               calm: ['garden','horizon','daymoon'] };
            const opts = sceneFor[want] || SCENE_ORDER;
            setScene(opts[Math.floor(Math.random()*opts.length)], false);
          }
        }
      }).catch(()=>{});
  }
  // 3) Gently steer the entrainment pulse: a slightly slower, deeper pulse for
  //    an activated person (calming), easing toward a neutral rate as they settle.
  if (entrainOn) {
    // more arousal -> slower pulse (~3.5 Hz, calming); calm -> ~5 Hz resting
    const targetHz = 3.5 + (1 - Math.min(1, adaptiveArousal)) * 1.5;
    setEntrainmentBeat(targetHz);
  }
}

function startAdaptiveLoop() {
  if (adaptiveInterval) return;
  adaptiveInterval = setInterval(adaptiveTick, 2500); // gentle, every 2.5s
}
function stopAdaptiveLoop() {
  if (adaptiveInterval) { clearInterval(adaptiveInterval); adaptiveInterval = null; }
}

// ---------------------------------------------------------------------------
// THE ENTRAINMENT LAYER (free, generated) — a subtle, steady calming pulse
// layered gently UNDER the warm music. Research links a slow pulse in the
// ~6-10 Hz range (and low carrier tones) to easing anxiety. This is felt more
// than heard: two soft low tones a few Hz apart create a gentle "beat" the
// nervous system can settle toward (the science word: entrainment).
//
// It NEVER replaces the warm music — it sits beneath it, very quiet. It uses
// its own tiny Web Audio graph so it's independent of the music decks. And it
// gently follows the adaptive loop: a slightly slower, deeper pulse to calm an
// activated person; eased off as they settle.
// ---------------------------------------------------------------------------
let entrainCtx = null, entrainOscL = null, entrainOscR = null, entrainGain = null;
let entrainPanL = null, entrainPanR = null, entrainOn = false;
const ENTRAIN_CARRIER = 120;   // low, warm carrier tone (Hz) — felt, not piercing
let entrainBeatHz = 4.5;       // slower, deeper pulse (lowered per Toshay)
const ENTRAIN_VOL = 0.018;     // barely-there — felt more than heard (lowered per Toshay)

function startEntrainment() {
  if (entrainOn) return;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    entrainCtx = entrainCtx || new AC();
    if (entrainCtx.state === 'suspended') { entrainCtx.resume().catch(()=>{}); }
    entrainGain = entrainCtx.createGain();
    entrainGain.gain.value = 0;           // fade in gently
    entrainGain.connect(entrainCtx.destination);
    // Two oscillators, one per ear, a few Hz apart => a soft binaural pulse.
    entrainOscL = entrainCtx.createOscillator();
    entrainOscR = entrainCtx.createOscillator();
    entrainOscL.type = 'sine'; entrainOscR.type = 'sine';
    entrainOscL.frequency.value = ENTRAIN_CARRIER;
    entrainOscR.frequency.value = ENTRAIN_CARRIER + entrainBeatHz;
    // Pan each to one ear (headphones make the pulse clearest; still soothing on speakers).
    entrainPanL = entrainCtx.createStereoPanner ? entrainCtx.createStereoPanner() : null;
    entrainPanR = entrainCtx.createStereoPanner ? entrainCtx.createStereoPanner() : null;
    if (entrainPanL && entrainPanR) {
      entrainPanL.pan.value = -1; entrainPanR.pan.value = 1;
      entrainOscL.connect(entrainPanL).connect(entrainGain);
      entrainOscR.connect(entrainPanR).connect(entrainGain);
    } else {
      entrainOscL.connect(entrainGain);
      entrainOscR.connect(entrainGain);
    }
    entrainOscL.start(); entrainOscR.start();
    // gentle fade-in so it's never a sudden tone
    entrainGain.gain.linearRampToValueAtTime(ENTRAIN_VOL, entrainCtx.currentTime + 8.0);
    entrainOn = true;
  } catch (e) { /* if unavailable, the warm music still plays fine */ }
}

function setEntrainmentBeat(hz) {
  // Gently move the pulse rate (e.g., slower/deeper to calm an activated person).
  entrainBeatHz = Math.max(4, Math.min(10, hz));
  if (entrainOn && entrainOscR && entrainCtx) {
    entrainOscR.frequency.linearRampToValueAtTime(ENTRAIN_CARRIER + entrainBeatHz, entrainCtx.currentTime + 3.0);
  }
}

function stopEntrainment() {
  if (!entrainOn) return;
  try {
    entrainGain.gain.linearRampToValueAtTime(0, entrainCtx.currentTime + 2.0);
    setTimeout(() => { try { entrainOscL.stop(); entrainOscR.stop(); } catch(e){} entrainOn = false; }, 2200);
  } catch (e) { entrainOn = false; }
}

function toggleEntrainment() {
  const btn = document.getElementById('entrain-toggle');
  if (entrainOn) {
    window._entrainEnabled = false;
    stopEntrainment();
    if (btn) btn.innerHTML = '&#10041; Calm pulse: off';
  } else {
    window._entrainEnabled = true;
    startEntrainment();
    if (btn) btn.innerHTML = '&#10041; Calm pulse: on';
  }
}

// --- DJ CROSSFADE ENGINE ---
let deckA, deckB, activeDeck = 'A';
let crossfading = false;
const CROSSFADE_MS = 4000; // 4 second blend
const CROSSFADE_TRIGGER = 8; // start blend 8 seconds before track ends
const TARGET_VOL = 0.09;   // sweet spot: present but never in-your-ear

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
  return; // binaural layer disabled — real tracks only
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
  return; // solfeggio drone disabled — real tracks only
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
  // DISABLED: synthetic pad/chords/binaural/solfeggio produce an electronic
  // sound. Only the real, loved music tracks play now. This is a hard no-op.
  return null;
}

function zenisysStop() {
  try {
    if (ZENISYS.chordLoop) { ZENISYS.chordLoop.stop(); ZENISYS.chordLoop.dispose(); ZENISYS.chordLoop = null; }
    if (ZENISYS.binauralNodes) { ZENISYS.binauralNodes.forEach(n => { try{n.stop();}catch(e){} }); ZENISYS.binauralNodes = null; }
    if (ZENISYS.solfeggioNode) { try{ZENISYS.solfeggioNode.stop();}catch(e){} ZENISYS.solfeggioNode = null; }
  } catch(e){}
}

// --- Legacy bridge: keep the old function names working, route to Zenisys ---
// Synthetic layers OFF by founder decision: only the real, loved music tracks
// play. These are kept as no-ops so any caller is harmless.
function startSynthPad(emotion) { /* disabled — real tracks only */ }
function updateSynthEmotion(emotion) { /* disabled — real tracks only */ }

</script>
<script>
function $(id) { return document.getElementById(id); }
function val(id) { const e = $(id); return e ? e.value : ''; }
function chk(id) { const e = $(id); return e ? !!e.checked : false; }
let ambientTracks = [];
let ambientIndex = 0;

// Anonymous metric ping — counts only, never content.
const SESSION_ID = 's' + Math.random().toString(16).slice(2,8);
function metric(type, value){ try { fetch('/api/metrics/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:type,value:value,sid:SESSION_ID})}); } catch(e){} }
const PAGE_OPEN_MS = Date.now();
// ================= READINESS CHECK — tests the device, installs nothing =================
// Runs quietly at start; if something could hurt the experience, it offers a
// plain-language recommendation. It never changes the person's computer.
function runReadinessCheck(){
  const notes = [];
  // 1) Reduced-motion / heavy load hint via frame timing
  let frames = 0; const t0 = performance.now();
  function countFrame(){ frames++; if (performance.now() - t0 < 1000) requestAnimationFrame(countFrame); else finishFps(); }
  function finishFps(){
    const fps = frames;
    if (fps > 0 && fps < 30) notes.push('Your screen is updating slowly (about ' + fps + ' frames per second). Closing other browser tabs and programs usually makes scrolling smooth again.');
    // 2) Memory pressure (Chrome exposes this)
    if (performance.memory && performance.memory.usedJSHeapSize / performance.memory.jsHeapSizeLimit > 0.8){
      notes.push('This browser tab is using a lot of memory. Refreshing the page, or closing other tabs, will help it run smoothly.');
    }
    // 3) Camera/mic presence
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices){
      navigator.mediaDevices.enumerateDevices().then(function(list){
        const hasCam = list.some(d=>d.kind==='videoinput');
        const hasMic = list.some(d=>d.kind==='audioinput');
        if (!hasCam) notes.push('No camera was found, so the calming heart reading and gentle scene response will not run. A webcam enables the full experience.');
        if (!hasMic) notes.push('No microphone was found. You can still type, but speaking aloud will not be available.');
        showReadiness(notes);
      }).catch(function(){ showReadiness(notes); });
    } else { showReadiness(notes); }
  }
  requestAnimationFrame(countFrame);
}
function showReadiness(notes){
  if (!notes.length) return; // all good, stay silent
  const bar = document.createElement('div');
  bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:70;background:#fffbeb;border-bottom:1px solid #fcd34d;'
    + 'color:#92400e;font-family:Arial;font-size:13px;padding:10px 16px;text-align:center;';
  bar.innerHTML = 'For the smoothest experience: ' + notes.join(' &nbsp;•&nbsp; ')
    + ' <button onclick="this.parentNode.remove()" style="margin-left:10px;background:#92400e;color:#fff;border:0;border-radius:6px;padding:4px 12px;cursor:pointer;">Got it</button>';
  document.body.appendChild(bar);
}
setTimeout(runReadinessCheck, 2500);

// Guarantee the page can always scroll — nothing may lock the body.
(function ensureScrollable(){
  function unlock(){
    try {
      document.documentElement.style.overflowY = 'auto';
      document.body.style.overflowY = 'auto';
      document.body.style.position = 'static';
      document.body.style.touchAction = 'auto';
      document.documentElement.style.height = 'auto';
      document.body.style.height = 'auto';
      document.documentElement.style.minHeight = '100%';
      // make sure the app container never traps height
      const scr = document.querySelector('.story-screen');
      if (scr){ scr.style.overflow = 'visible'; scr.style.height = 'auto'; }
    } catch(e){}
  }
  unlock();
  window.addEventListener('resize', unlock);
  window.addEventListener('orientationchange', unlock);
  setInterval(unlock, 3000); // keep it unlocked no matter what re-locks it
})();
// Your hand wins: auto-scroll is allowed ONLY when you're already near the
// bottom. The moment you scroll up to read, nothing drags you back down.
function nearBottom(el){
  if (!el || el === document.body) {
    return (window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 160);
  }
  return (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 160);
}
function politeScrollIntoView(el){
  if (nearBottom(document.body)) politeScrollIntoView(el);
}

// ---- LENS THREE: wordless calm scale (tap a face, or ignore it) ----
function showCalmScale(phase){
  if (document.getElementById('sam-card')) return;
  const card = document.createElement('div');
  card.id = 'sam-card';
  card.style.cssText = 'position:fixed;top:80px;right:18px;z-index:60;max-width:200px;'
    + 'background:rgba(255,255,255,0.96);border-radius:16px;padding:14px 16px;'
    + 'box-shadow:0 10px 36px rgba(20,40,80,0.25);text-align:center;transition:opacity 1s ease;';
  card.innerHTML = '<div style="font-size:13px;color:#41607d;margin-bottom:8px;">How are you feeling right now? (tap one, or ignore me)</div>'
    + '<div style="font-size:30px;letter-spacing:14px;cursor:pointer;">'
    + ['&#128551;','&#128533;','&#128528;','&#128578;','&#128522;'].map(function(f,i){
        return '<span data-v="'+(i+1)+'" style="cursor:pointer;">'+f+'</span>';
      }).join('')
    + '</div>';
  card.addEventListener('click', function(ev){
    const v = ev.target && ev.target.dataset && ev.target.dataset.v;
    if (v) metric('selfreport', phase + '|' + v);
    card.style.opacity = '0'; setTimeout(()=>card.remove(), 1000);
  });
  document.body.appendChild(card);
  setTimeout(()=>{ if (card.parentNode){ card.style.opacity='0'; setTimeout(()=>card.remove(),1000);} }, 25000);
}

let TAP_MS = Date.now();
// PRELOAD: fetch the calm lane and warm up the first track before the tap,
// so sound begins the instant the person enters.
(function preloadFirstSound(){
  fetch('/api/zenisys/ambient').then(r=>r.json()).then(d=>{
    if (d.tracks && d.tracks.length){
      window._preloadedTracks = d.tracks;
      const deck = document.getElementById('deckA') || document.querySelector('audio');
      if (deck){ deck.src = d.tracks[0].url; deck.preload='auto'; deck.load(); }
    }
  }).catch(()=>{});
})();
// --- HESITATION SENSOR: they almost said something, then erased it. ---
(function(){
  let deepest = 0;
  document.addEventListener('input', function(ev){
    const el = ev.target;
    if (!el || el.id !== 'message') return;
    const len = (el.value || '').length;
    if (len > deepest) deepest = len;
    if (len === 0 && deepest > 12) { metric('hesitation'); deepest = 0; }
    if (len < 3) deepest = Math.max(deepest, len);
  });
  document.addEventListener('claude-message-sent', function(){ deepest = 0; });
})();

async function startExperience() {
  TAP_MS = Date.now();
  // Warm the sound engine at the tap so the sound box answers instantly later.
  try { if (typeof ensureZenisysContext === 'function') ensureZenisysContext(); } catch(e){}
  try { const ac = new (window.AudioContext||window.webkitAudioContext)(); if (ac.state==='suspended') ac.resume(); window._warmCtx = ac; } catch(e){}
  setTimeout(()=>showCalmScale('arrival'), 9000);      // after the music has risen
  setTimeout(()=>showCalmScale('later'), 4*60*1000);   // the change measurement
  // STEP 1: Show the conversation screen IMMEDIATELY (before anything else)
  const gate = $('welcome-gate'); if (gate) gate.style.display = 'none';
  const screen = $('story-screen'); if (screen) screen.style.display = 'flex';
  const msg = $('message'); if (msg) msg.focus({preventScroll:true});
  metric('session_start');
  // Start on a real photograph (the founder's garden) and rotate slowly
  setScene('garden', false);
  startSceneRotation();

  // STEP 2: Start camera, face detection, and music IN THE BACKGROUND
  // These are nice-to-have — the conversation works even if they all fail
  setTimeout(async () => {
    // Camera
    try { await startVisualCamera(); } catch (e) { console.log('[InnerLight] Camera unavailable:', e); }
    // Face emotion detection
    try { await loadFaceModels(); startFaceLoop(); } catch (e) { console.log('[InnerLight] Face models unavailable:', e); }
    // Start the free adaptive loop — sound responds to face + voice in real time
    startAdaptiveLoop();
    // Start the subtle entrainment pulse gently under the music (can be toggled off)
    // Entrainment pulse disabled — it caused a warble on speakers. Off until real audio.
    // if (window._entrainEnabled !== false) startEntrainment();
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
        if (window._preloadedTracks && !ambientTracks.length) ambientTracks = window._preloadedTracks;
        if (deck.src !== ambientTracks[0].url) deck.src = ambientTracks[0].url;
        // GENTLE ARRIVAL: enter soft, then rise smoothly into full rich volume —
        // never an abrupt hit of sound in the ear.
        deck.volume = TARGET_VOL * 0.22;  // enter very soft, rise gently
        deck.play().then(()=>metric('first_sound_ms', Date.now()-TAP_MS)).catch(()=>{});
        (function arrivalRise(){
          const RISE_MS = 10000; // ten calm seconds from soft to full
          const start = performance.now(), from = deck.volume, to = TARGET_VOL;
          function step(t){
            const p = Math.min(1, (t - start) / RISE_MS);
            const ease = p*p*(3-2*p); // smooth, no lurch
            deck.volume = from + (to - from) * ease;
            if (p < 1) requestAnimationFrame(step);
          }
          requestAnimationFrame(step);
        })();
        const now = $('music-now'); if (now) now.textContent = '\u266a ' + (ambientTracks[0].name || 'soft music');
        // If this arrival started on the SYMPHONY lane (person very upset),
        // ease down into SPA after the proven ~3-minute attention window.
        if (data.lane === 'symphony_to_spa' && data.then && data.then.length) {
          scheduleSpaTransition(data.then, (data.transition_after_seconds || 180) * 1000);
        }
      } else {
        const now = $('music-now'); if (now) now.textContent = 'music loading...';
      }
      // NOTE: the thin synth-tone layer is intentionally OFF now that real
      // calming instrumental audio is playing — real music leads, not tones.
      // startSynthPad('calm');  // (disabled by design)
    } catch (e) { console.log('[InnerLight] Music unavailable:', e); }
  }, 100);
}
function changeMusic() {
  if (!ambientTracks.length) return;
  crossfading = true;
  playNextTrackBlended();
}

// Proven car method: when someone arrives very upset, symphony plays first to
// catch and hold their attention, then we GENTLY ease down into spa to calm
// them. This schedules that transition after the attention window.
let spaTransitionTimer = null;
function scheduleSpaTransition(spaTracks, delayMs) {
  if (spaTransitionTimer) clearTimeout(spaTransitionTimer);
  spaTransitionTimer = setTimeout(() => {
    if (!spaTracks || !spaTracks.length) return;
    // Swap the playlist over to spa and crossfade into it softly.
    ambientTracks = spaTracks;
    ambientIndex = 0;
    const inactive = getInactiveDeck();
    if (!inactive) return;
    inactive.src = spaTracks[0].url;
    inactive.load();
    crossfade(getActiveDeck(), inactive, CROSSFADE_MS);
    activeDeck = activeDeck === 'A' ? 'B' : 'A';
    const now = $('music-now'); if (now) now.textContent = '\u266a ' + (spaTracks[0].name || 'Spa');
  }, delayMs);
}

// --- TRACK GUARDIAN: is the person reacting against THIS track? ---
// Watches displeasure (disgust/anger/surprise mix) during a track's first
// minute, compared to the person's own level before the track began.
let trackWatch = null; // {name, startMs, baseline, strikes}
function beginTrackWatch(name){
  const sc = faceEmotionScores || {};
  const displeasure = (sc.disgusted||0)*1.2 + (sc.angry||0) + (sc.surprised||0)*0.6;
  const easeB = ((sc.happy||0) + (sc.neutral||0)*0.3);
  trackWatch = { name: name || 'unknown', startMs: Date.now(), baseline: displeasure, easeBase: easeB, easeSum: 0, samples: 0, strikes: 0 };
}
function trackGuardianTick(){
  if (!trackWatch) return;
  const age = Date.now() - trackWatch.startMs;
  const sc = faceEmotionScores || {};
  const displeasure = (sc.disgusted||0)*1.2 + (sc.angry||0) + (sc.surprised||0)*0.6;
  const ease = (sc.happy||0) + (sc.neutral||0)*0.3;
  if (age > 60000) {
    // Opening minute complete: render the verdict — liked, or neutral.
    const avgEase = trackWatch.easeSum / Math.max(1, trackWatch.samples);
    const verdict = (avgEase - trackWatch.easeBase > 0.12) ? 'liked' : 'neutral';
    metric('track_react', trackWatch.name + '|' + verdict);
    trackWatch = null; return;
  }
  if (age < 4000) return;                          // let the crossfade settle first
  trackWatch.easeSum = (trackWatch.easeSum||0) + ease;
  trackWatch.samples = (trackWatch.samples||0) + 1;
  if (displeasure - trackWatch.baseline > 0.35) trackWatch.strikes++;
  else if (trackWatch.strikes > 0) trackWatch.strikes--;
  if (trackWatch.strikes >= 4) {
    // A held reaction against this track: change the song, not the lane.
    const disliked = trackWatch.name;
    trackWatch = null;
    metric('track_skip', disliked);
    metric('track_react', disliked + '|disliked');
    if (ambientTracks.length > 1) {
      ambientIndex = (ambientIndex + 1) % ambientTracks.length;
      const t = ambientTracks[ambientIndex];
      switchAmbient(t.url, t.name);
    }
  }
}
setInterval(trackGuardianTick, 1500);

function switchAmbient(url, name, vol) {
  // DJ-style: crossfade to the new track instead of hard-switching
  const inactive = getInactiveDeck();
  if (!inactive) return;
  inactive.src = url;
  inactive.load();
  crossfade(getActiveDeck(), inactive, CROSSFADE_MS);
  activeDeck = activeDeck === 'A' ? 'B' : 'A';
  const now = $('music-now'); if (now) now.textContent = '\u266a ' + (name || 'music');
  beginTrackWatch(name);
  // (Synthetic layers disabled — only the real music tracks play.)
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
function caseRecord(role, text){
  try { fetch('/api/case/record', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({sid: SESSION_ID, role: role, text: String(text||'').slice(0,1200)})}); } catch(e){}
}
function logTurn(role, text){
  caseRecord(role, text);
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
let micStreamLive = null;
let micAudioCtx = null;
let micAnalyser = null;
let micMeterRAF = null;
let micRecorder = null;
let micTestChunks = [];
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
async function ensureMicStream() {
  if (micStreamLive) return micStreamLive;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { throw new Error('no-getusermedia'); }
  micStreamLive = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
  });
  const AC = window.AudioContext || window.webkitAudioContext;
  micAudioCtx = micAudioCtx || new AC();
  if (micAudioCtx.state === 'suspended') { try { await micAudioCtx.resume(); } catch(e){} }
  const source = micAudioCtx.createMediaStreamSource(micStreamLive);
  micAnalyser = micAudioCtx.createAnalyser();
  micAnalyser.fftSize = 512;
  source.connect(micAnalyser);
  runMicMeter();
  return micStreamLive;
}
function runMicMeter() {
  const data = new Uint8Array(micAnalyser.frequencyBinCount);
  const bar = document.getElementById('mic-level-fill');
  function tick() {
    if (!micAnalyser) return;
    micAnalyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) { const v = (data[i]-128)/128; sum += v*v; }
    const rms = Math.sqrt(sum / data.length);
    const pct = Math.min(100, Math.round(rms * 240));
    if (bar) bar.style.width = pct + '%';
    micMeterRAF = requestAnimationFrame(tick);
  }
  if (micMeterRAF) cancelAnimationFrame(micMeterRAF);
  tick();
}
function stopMicStream() {
  if (micMeterRAF) { cancelAnimationFrame(micMeterRAF); micMeterRAF = null; }
  const bar = document.getElementById('mic-level-fill'); if (bar) bar.style.width = '0%';
  if (micStreamLive) { micStreamLive.getTracks().forEach(t => t.stop()); micStreamLive = null; }
  micAnalyser = null;
}
async function testMic() {
  const status = document.getElementById('mic-test-status');
  try {
    await ensureMicStream();
    if (status) status.textContent = 'Recording 3 seconds \u2014 say anything\u2026';
    micTestChunks = [];
    micRecorder = new MediaRecorder(micStreamLive);
    micRecorder.ondataavailable = e => { if (e.data.size) micTestChunks.push(e.data); };
    micRecorder.onstop = () => {
      const blob = new Blob(micTestChunks, { type: micRecorder.mimeType || 'audio/webm' });
      const url = URL.createObjectURL(blob);
      const player = document.getElementById('mic-test-playback');
      if (player) { player.src = url; player.style.display = 'block'; player.play().catch(()=>{}); }
      if (status) status.textContent = 'That is what your mic picked up \u2014 if you can hear yourself, it works.';
    };
    micRecorder.start();
    setTimeout(() => { try { micRecorder.stop(); } catch(e){} }, 3000);
  } catch (e) {
    if (status) status.textContent = 'Could not open the microphone. Please allow mic access in your browser, then try again.';
  }
}
async function startVoiceCapture() {
  if (voiceListening) {
    voiceListening = false;
    if (voiceRecognizer) { try { voiceRecognizer.stop(); } catch (e) {} }
    stopDeepgramStream();
    stopMicStream();
    const micBtn = document.querySelector('.story-mic');
    if (micBtn) micBtn.innerHTML = '&#127908; Speak';
    const lbl = $('listen-label'); if (lbl) lbl.textContent = 'Saved \u2014 press Enter to send, or keep editing';
    return;
  }
  try {
    await ensureMicStream();
  } catch (e) {
    const lbl = $('listen-label');
    if (lbl) lbl.textContent = 'Could not open the microphone. Please allow mic access in your browser. You can also type.';
    const panel = $('live-transcript'); if (panel) panel.style.display = 'block';
    return;
  }
  voiceListening = true;
  voiceFinalTranscript = '';
  const panel = $('live-transcript'); const dot = $('listen-dot'); const lbl = $('listen-label'); const tEl = $('transcript-text');
  if (panel) panel.style.display = 'block';
  if (dot) dot.style.background = '#e05a5a';
  if (lbl) lbl.textContent = 'Listening\u2026 speak now (tap mic again to stop)';
  if (tEl) tEl.innerHTML = '&nbsp;';
  const micBtn = document.querySelector('.story-mic');
  if (micBtn) micBtn.innerHTML = '&#128308; Listening\u2026 (tap to stop)';

  // PRIMARY transcription: Deepgram live streaming (the Zoom way) — reliable on
  // every browser and phone. Falls back to the browser's built-in speech-to-text
  // only if Deepgram isn't configured. The MIC itself already works regardless.
  let usingDeepgram = false;
  try {
    const tk = await fetch('/api/transcribe/token').then(r => r.json());
    if (tk && tk.ok && tk.token) {
      usingDeepgram = true;
      startDeepgramStream(tk.token);
    }
  } catch (e) { /* fall through to browser STT */ }

  if (usingDeepgram) return;

  // FALLBACK: browser built-in speech-to-text (optional layer).
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SR) {
    if (!voiceRecognizer) {
      voiceRecognizer = new SR();
      voiceRecognizer.continuous = true;
      voiceRecognizer.interimResults = true;
      voiceRecognizer.lang = 'en-US';
      voiceRecognizer.onresult = event => {
        let finalText = '', interimText = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const chunk = event.results[i][0].transcript;
          if (event.results[i].isFinal) finalText += chunk; else interimText += chunk;
        }
        if (finalText) voiceFinalTranscript = (voiceFinalTranscript + ' ' + finalText).trim();
        const shown = (voiceFinalTranscript + ' ' + interimText).trim();
        const tp = $('transcript-text');
        if (tp) tp.innerHTML = (voiceFinalTranscript ? '<span style="color:#1a3a5c;">'+escHtml(voiceFinalTranscript)+'</span>' : '')
          + (interimText ? ' <span style="color:#8aa3c4;">'+escHtml(interimText)+'</span>' : '') || '&nbsp;';
        if ($('voice_transcript')) $('voice_transcript').value = shown;
        const box = document.getElementById('conv-answer') || $('message');
        if (box) box.value = shown;
        if (typeof captureVoiceFeatures === 'function') captureVoiceFeatures();
        // Words BUILD in the box. Nothing sends on its own — the person sends
        // when they are ready (Enter or send button), even with the mic on.
      };
      voiceRecognizer.onerror = event => {
        const err = event.error || 'unknown';
        if ((err === 'network' || err === 'no-speech' || err === 'aborted') && voiceListening) {
          setTimeout(() => { if (voiceListening) { try { voiceRecognizer.start(); } catch(e){} } }, 500);
        }
      };
      voiceRecognizer.onend = () => {
        if (voiceListening) { try { voiceRecognizer.start(); return; } catch (e) {} }
      };
    }
    try { voiceRecognizer.start(); } catch (e) {}
  } else {
    if (lbl) lbl.textContent = 'Listening\u2026 (your words will not auto-type in this browser, but the mic is working \u2014 you can type too)';
  }
}

// Stream live mic audio to Deepgram and show words on screen as they're spoken.
let dgSocket = null;
let dgRecorder = null;
function startDeepgramStream(tempToken){
  try {
    // Open Deepgram's live streaming endpoint with the short-lived JWT token.
    // JWT tokens from /auth/grant use the 'bearer' subprotocol.
    dgSocket = new WebSocket(
      'wss://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&interim_results=true&punctuate=true',
      ['bearer', tempToken]
    );
    dgSocket.onopen = () => {
      // Send mic audio in small chunks as it's captured.
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
      dgRecorder = new MediaRecorder(micStreamLive, { mimeType: mime });
      dgTouchActivity(); // arm the budget guard the moment listening begins
      dgRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0 && dgSocket && dgSocket.readyState === 1) dgSocket.send(e.data);
      };
      dgRecorder.start(250); // send every 250ms for low-latency live text
    };
    dgSocket.onmessage = (msg) => {
      dgTouchActivity(); // every received word resets the 60s quiet timer
      let data; try { data = JSON.parse(msg.data); } catch(e){ return; }
      const alt = data && data.channel && data.channel.alternatives && data.channel.alternatives[0];
      if (!alt) return;
      const text = alt.transcript || '';
      if (!text) return;
      const tp = document.getElementById('transcript-text');
      const box = document.getElementById('conv-answer') || $('message');
      if (data.is_final) {
        voiceFinalTranscript = (voiceFinalTranscript + ' ' + text).trim();
        if (tp) tp.innerHTML = '<span style="color:#1a3a5c;">' + escHtml(voiceFinalTranscript) + '</span>';
        if ($('voice_transcript')) $('voice_transcript').value = voiceFinalTranscript;
        // Words keep BUILDING in the box as one growing message. Nothing sends
        // on its own — the person edits freely and sends only when THEY choose
        // (Enter or the send button), even with the mic still on.
        if (box) box.value = voiceFinalTranscript;
      } else {
        // interim: show final solid + this faded (also mirror into the box live)
        if (tp) tp.innerHTML = (voiceFinalTranscript ? '<span style="color:#1a3a5c;">'+escHtml(voiceFinalTranscript)+'</span> ' : '')
          + '<span style="color:#8aa3c4;">' + escHtml(text) + '</span>';
        if (box) box.value = (voiceFinalTranscript + ' ' + text).trim();
      }
    };
    dgSocket.onerror = () => {
      const lbl = $('listen-label'); if (lbl) lbl.textContent = 'Listening\u2026 (mic working; reconnecting transcription\u2026)';
    };
    dgSocket.onclose = () => {
      try { if (dgRecorder && dgRecorder.state !== 'inactive') dgRecorder.stop(); } catch(e){}
    };
  } catch (e) {
    // If Deepgram can't open, the mic still works and the meter still moves.
  }
}
function stopDeepgramStream(){
  try { if (dgRecorder && dgRecorder.state !== 'inactive') dgRecorder.stop(); } catch(e){}
  try { if (dgSocket) { dgSocket.send(JSON.stringify({type:'CloseStream'})); dgSocket.close(); } } catch(e){}
  dgRecorder = null; dgSocket = null;
  if (dgIdleTimer) { clearTimeout(dgIdleTimer); dgIdleTimer = null; }
}

// --- BUDGET GUARD: live transcription costs money per minute, so it never
// runs unattended. Any time 60s pass with no new words, listening fully stops
// (socket, recorder, and mic all closed) and the person can tap to resume.
let dgIdleTimer = null;
function dgTouchActivity(){
  if (dgIdleTimer) clearTimeout(dgIdleTimer);
  dgIdleTimer = setTimeout(() => {
    if (!voiceListening) return;
    voiceListening = false;
    if (voiceRecognizer) { try { voiceRecognizer.stop(); } catch(e){} }
    stopDeepgramStream();
    stopMicStream();
    const micBtn = document.querySelector('.story-mic');
    if (micBtn) micBtn.innerHTML = '&#127908; Speak';
    const lbl = $('listen-label');
    if (lbl) lbl.textContent = 'Listening paused (quiet for a while) \u2014 tap the mic to continue';
    metric('listen_autostop');
    const dot = $('listen-dot'); if (dot) dot.style.background = '#9ab0c4';
  }, 60000);
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
// FACE VIDEO floats to the side when you scroll down, and returns to its
// centered spot when you scroll back to the top. Smooth and calm.
(function(){
  let ticking = false;
  function onScroll(){
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function(){
      const bar = document.querySelector('.story-video-bar');
      if (bar) {
        // Float once the page is scrolled past a gentle threshold; return to
        // center when near the top.
        if (window.scrollY > 140) bar.classList.add('floating');
        else bar.classList.remove('floating');
      }
      ticking = false;
    });
  }
  window.addEventListener('scroll', onScroll, {passive:true});
})();

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

function toggleVoiceCombined(){
  const btn = document.getElementById('voice-toggle');
  const turningOn = !voiceEnabled;
  voiceEnabled = turningOn;
  try { window._voiceFirst = turningOn; } catch(e){}
  if (typeof applyVoiceFirst === 'function') { try { applyVoiceFirst(turningOn); } catch(e){} }
  if (btn) btn.innerHTML = turningOn ? '&#128266; Spoken voice: On' : '&#128263; Spoken voice: Off';
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
  metric('handoff_click', kind);
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
  const msgVal = (val('message') || '').trim();
  // Empty guard: if there's nothing to send, don't fake a response.
  if (!msgVal) {
    const em = $('emotion-status');
    if (em) { em.style.display='block'; em.textContent = "I didn't catch anything yet — take your time, and share whenever you're ready."; }
    return;
  }
  voiceFinalTranscript = '';
  logTurn('user', msgVal);
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
      consent_case_file:chk('consent_case_file'),
      conversation: conversationLog
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
  // Don't push "talk to a specialist" prematurely. Let the person be understood
  // first. Only show a handoff after enough real exchange — UNLESS it's an
  // urgent safety situation, which should always surface immediately.
  const userTurns = (typeof conversationLog !== 'undefined')
    ? conversationLog.filter(t => t.role === 'user').length : 0;
  const urgent = (data && (data.risk === 'critical' || data.risk === 'high')) || handoff.type === 'crisis';
  if (!urgent && userTurns < 4) return;
  // Don't show the same handoff twice in a row.
  if (thread.querySelector('.handoff-card')) { const old = thread.querySelector('.handoff-card'); if (old) old.remove(); }
  const el = document.createElement('div');
  el.className = 'handoff-card';
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
  politeScrollIntoView(el);
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
  politeScrollIntoView(el);
}
function restartConversation() {
  const box = document.createElement('div');
  box.className = 'reply-box';
  box.style.cssText = 'margin-top:16px;';
  box.innerHTML = `
    <textarea id="conv-answer" class="story-input" style="min-height:80px;" placeholder="I'm listening... (press Enter to send)" onkeydown="if((event.key==='Enter'||event.keyCode===13)&&!event.shiftKey&&!event.isComposing){event.preventDefault();continueConversation();}"></textarea>
    <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
      <button class="story-send" onclick="continueConversation()">Reply</button>
      <button class="story-mic" type="button" onclick="startVoiceCapture()">&#127908; Speak</button>
    </div>
  `;
  document.getElementById('conversation-thread').appendChild(box);
  document.getElementById('conv-answer').focus({preventScroll:true});
}
function appendExchange(thread, reply, question, safetyHtml) {
  // Remove any previous reply box (keep conversation flat)
  const oldReply = thread.querySelector('.reply-box');
  if (oldReply) oldReply.remove();
  // Append the AI's response
  const exchange = document.createElement('div');
  exchange.style.cssText = 'text-align:left;padding:16px 0;border-bottom:1px solid #e8f0eb;';
  const questionHtml = (question && question.trim())
    ? `<p style="font-size:16px;line-height:1.7;color:#2d4a3e;margin:14px 0 0;font-weight:500;">${escapeHtml(question)}</p>`
    : '';
  exchange.innerHTML = `
    <p style="font-size:16px;line-height:1.7;color:#2d4a3e;margin:0 0 8px;">${escapeHtml(reply)}</p>
    ${safetyHtml || ''}
    ${questionHtml}
  `;
  thread.appendChild(exchange);
  // SPEAK the response aloud (AI voice) — include question only if present
  speak(question && question.trim() ? (reply + '. ' + question) : reply);
  // Add a fresh reply box at the bottom (always exactly one)
  const replyBox = document.createElement('div');
  replyBox.className = 'reply-box';
  replyBox.style.cssText = 'margin-top:16px;';
  replyBox.innerHTML = `
    <textarea id="conv-answer" class="story-input" style="min-height:80px;" placeholder="Take your time... or tap Speak (press Enter to send)" onkeydown="if((event.key==='Enter'||event.keyCode===13)&&!event.shiftKey&&!event.isComposing){event.preventDefault();continueConversation();}"></textarea>
    <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
      <button class="story-send" onclick="continueConversation()">Reply</button>
      <button class="story-mic" type="button" onclick="startVoiceCapture()">&#127908; Speak</button>
    </div>
  `;
  thread.appendChild(replyBox);
  // Focus and scroll
  const ta = document.getElementById('conv-answer');
  if (ta) ta.focus({preventScroll:true});
  politeScrollIntoView(replyBox);
}
async function updateMusicForEmotion(data) {
  const textEmotion = (data.zenisys_music || {}).emotion || 'calm';
  const faceEmo = currentFaceEmotion || '';
  const emotionToUse = (faceEmo && faceEmo !== 'neutral' && faceEmo !== textEmotion) ? faceEmo : textEmotion;
  const risk = (data.risk || '') ;
  // Crossfade to the lane that MEETS this person: deep-calm to bring an
  // agitated person down, lifting to bring a flat/depressed person up, then
  // gently ease toward spa. The person picks the door by how they are.
  try {
    const res = await fetch('/api/zenisys/ambient?emotion=' + encodeURIComponent(emotionToUse)
                            + '&risk=' + encodeURIComponent(risk));
    const d = await res.json();
    const tracks = d.tracks || [];
    if (tracks.length) {
      ambientTracks = tracks;
      ambientIndex = 0;
      switchAmbient(tracks[0].url, tracks[0].name);
      // After the proven window, ease toward the calmer "then" lane.
      if (d.then && d.then.length && (d.transition_after_seconds || 0) > 0) {
        scheduleSpaTransition(d.then, d.transition_after_seconds * 1000);
      }
    }
  } catch (e) {}
}
async function continueConversation() {
  const answerBox = document.getElementById('conv-answer');
  if (!answerBox || !answerBox.value.trim()) return;
  const userAnswer = answerBox.value.trim();
  // They chose to send. Clear the mic's running buffer so the NEXT thing they
  // say starts fresh (mic can stay on). Their sent words are safe below.
  voiceFinalTranscript = '';
  answerBox.value = '';
  const tpanel = document.getElementById('transcript-text'); if (tpanel) tpanel.innerHTML = '&nbsp;';
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
  if (nearBottom(document.body)) window.scrollTo({top: document.body.scrollHeight, behavior:'smooth'});
  // Call the API
  const res = await fetch('/api/innerlight/learn', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      answer: userAnswer,
      learning_state: innerLightLearningState,
      session_reference: innerLightSessionReference,
      context: Object.assign({}, innerLightContext, multimodalPayload(), {conversation: conversationLog})
    })
  });
  const data = await res.json();
  innerLightLearningState = data.learning_state || innerLightLearningState;
  innerLightContext = Object.assign(innerLightContext, data);
  // When comprehension (Claude) is active, its ONE deeper question is already
  // inside the reply — so we do NOT tack on a separate canned question.
  const rawQ = (data.questions || [])[0] || '';
  const nextQ = rawQ && rawQ.trim() ? rawQ : '';
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
    if (m === 'words'){
      if (!wordsPanel) buildWordsPanel();
      wordsPanel.style.display = 'block';
      try { metric('soundbox_open_ms', Date.now() - TAP_MS); } catch(e){}
    } else if (wordsPanel){ wordsPanel.style.display = 'none'; }
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
    .pro-btn { display:block; width:100%; text-align:left; margin:8px 0; padding:13px 16px; border-radius:12px;
               border:1.5px solid var(--line); background:#fff; cursor:pointer; font-size:15px; }
    .pro-btn span { display:block; font-size:12.5px; color:var(--muted); margin-top:3px; font-weight:400; }
    .pro-btn.picked { border-color:var(--green); background:#f0faf5; box-shadow:0 0 0 2px rgba(46,125,90,0.18); }
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
      <h2>Choose who you want to reach</h2>
      <p>You pick. Tap the kind of professional you want &mdash; your summary goes to them, and only when you say send.</p>
      <div id="pro-choices">
        <button type="button" class="pro-btn" data-pro="Crisis-trained counselor" onclick="pickPro(this)"><b>Crisis-trained counselor</b><span>Immediate emotional support for this moment. Not a prescriber.</span></button>
        <button type="button" class="pro-btn" data-pro="Therapist / licensed counselor" onclick="pickPro(this)"><b>Therapist / licensed counselor</b><span>Talk-based support and ongoing coping work.</span></button>
        <button type="button" class="pro-btn" data-pro="Psychiatrist" onclick="pickPro(this)"><b>Psychiatrist</b><span>A medical doctor who can evaluate symptoms and, where appropriate, manage medication.</span></button>
        <button type="button" class="pro-btn" data-pro="Nurse practitioner" onclick="pickPro(this)"><b>Nurse practitioner</b><span>Can assess symptoms and, in many states, manage medication.</span></button>
      </div>
      <p id="pro-picked" style="font-weight:700;color:var(--green);"></p>
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
      <p><b>Quality review.</b> De-identified notes about conversations &mdash; with names, numbers, and contact details removed &mdash; may be reviewed by InnerLight's founder to improve how people are routed to help. These notes are never sold, never advertised with, and never shown publicly.</p>
    </details>

    <section class="panel">
      <h2>Ready when you are</h2>
      <p>When you send this, InnerLight notifies the care side and prepares your approved summary so the professional can read it <i>before</i> they speak with you &mdash; so you don't have to start from the beginning.</p>
      <p id="status" style="font-weight:700;color:var(--green);"></p>
      <button id="send-btn" onclick="sendToCare()">Send my summary &amp; connect me</button>
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
    let pickedPro = '';
    function pickPro(btn){
      document.querySelectorAll('.pro-btn').forEach(b=>b.classList.remove('picked'));
      btn.classList.add('picked');
      pickedPro = btn.dataset.pro;
      document.getElementById('pro-picked').textContent = 'You chose: ' + pickedPro + '. Your summary will go to a ' + pickedPro.toLowerCase() + ' \u2014 nobody else.';
      const send = document.getElementById('send-btn');
      if (send) send.textContent = 'Send my summary & connect me to a ' + pickedPro.toLowerCase();
    }
    function sendToCare(){
      if (!pickedPro){
        document.getElementById('status').textContent = 'First, tap who you want to reach above \u2014 you choose, always.';
        return;
      }
      const clarify = document.getElementById('clarify').value.trim();
      const add = document.getElementById('addnote').value.trim();
      let log=[]; try{ log=JSON.parse(sessionStorage.getItem('innerlight_convo')||'[]'); }catch(e){}
      const said = log.filter(t=>t.role==='user').map(t=>t.text).join(' \u2022 ');
      const summaryText = ['WHO THIS GOES TO: ' + pickedPro,
        said ? 'IN THEIR OWN WORDS: ' + said : '',
        clarify ? 'THEY CLARIFIED: ' + clarify : '',
        add ? 'THEY ADDED: ' + add : ''].filter(Boolean).join('\n\n');
      const box = document.getElementById('convo-summary');
      box.innerHTML = '<p class="a"><b>The exact summary that goes to your ' + esc(pickedPro.toLowerCase()) + '</b></p>'
        + '<p class="u" style="white-space:pre-wrap;">' + esc(summaryText) + '</p>';
      document.getElementById('status').innerHTML = 'Reaching a human for you\u2026';
      fetch('/api/connect/request', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({kind:'care', pro: pickedPro, summary: summaryText})})
      .then(r=>r.json()).then(function(d){
        document.getElementById('status').innerHTML =
          'Your request for a <b>' + esc(pickedPro.toLowerCase()) + '</b> is in, and a human has been alerted. '
          + 'While our professional network grows, an <b>InnerLight responder</b> \u2014 our founder, not a licensed '
          + 'provider \u2014 will meet you first, stay with you, and help arrange the ' + esc(pickedPro.toLowerCase()) + ' you chose. '
          + 'Above is the exact summary they will read.<br><br>'
          + '<a href="' + d.room + '" target="_blank" style="display:inline-block;background:#2e7d5a;color:#fff;'
          + 'padding:13px 26px;border-radius:999px;font-weight:700;text-decoration:none;">Join your private video room</a>'
          + '<br><span style="font-size:12.5px;color:#8794a0;">The room is private to this request. If no one joins within a few minutes, '
          + 'call or text 988 anytime \u2014 you never have to wait alone.</span>';
      }).catch(function(){
        document.getElementById('status').textContent = 'The connection request could not go through. If you need someone now, call or text 988.';
      });
      try{ fetch('/api/metrics/event',{method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({type:'handoff_click', value:'care:'+pickedPro, sid: sessionStorage.getItem('innerlight_sid')||'page'})}); }catch(e){}
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
    .pro-btn { display:block; width:100%; text-align:left; margin:8px 0; padding:13px 16px; border-radius:12px;
               border:1.5px solid var(--line); background:#fff; cursor:pointer; font-size:15px; }
    .pro-btn span { display:block; font-size:12.5px; color:var(--muted); margin-top:3px; font-weight:400; }
    .pro-btn.picked { border-color:var(--green); background:#f0faf5; box-shadow:0 0 0 2px rgba(46,125,90,0.18); }
    .disclaimer { font-size:12.5px; color:#8a929a; line-height:1.5; border-top:1px solid var(--line); margin-top:30px; padding-top:16px; }
  </style>
</head>
<body>
  <header>
    <div class="tag">Connecting you to legal help &mdash; this is a legal handoff</div>
    <h1>You're being connected to legal support</h1>
    <p>This is <b>not</b> a medical or telehealth connection. This path is about a legal issue. Tap the kind of legal help you want &mdash; your summary goes there only when you say send.</p>
    <div id="pro-choices">
      <button type="button" class="pro-btn" data-pro="Housing / tenant attorney" onclick="pickPro(this)"><b>Housing / tenant attorney</b><span>Evictions, landlord disputes, unsafe conditions.</span></button>
      <button type="button" class="pro-btn" data-pro="Family law attorney" onclick="pickPro(this)"><b>Family law attorney</b><span>Custody, divorce, protective orders.</span></button>
      <button type="button" class="pro-btn" data-pro="Criminal defense attorney" onclick="pickPro(this)"><b>Criminal defense attorney</b><span>Charges, warrants, court dates.</span></button>
      <button type="button" class="pro-btn" data-pro="Consumer / civil attorney" onclick="pickPro(this)"><b>Consumer / civil attorney</b><span>Debt, fraud claims, insurance disputes, benefits denials.</span></button>
      <button type="button" class="pro-btn" data-pro="Legal aid office" onclick="pickPro(this)"><b>Legal aid office</b><span>Free or low-cost help when money is tight.</span></button>
    </div>
    <p id="pro-picked" style="font-weight:700;color:#2e6e8e;"></p>
  </header>
  <main>
    <section class="panel who">
      <h2>Self-help &amp; civic resources &mdash; free, trusted, available right now</h2>
      <p>These are established, free legal-information sources. They explain your rights and the process in plain language. They are information, <b>not</b> legal advice &mdash; only a lawyer can advise on your specific case &mdash; but they are a strong, fast place to start understanding where you stand.</p>
      <div class="reslib">
        <a class="res" href="https://www.lawhelp.org/" target="_blank" rel="noopener"><b>LawHelp.org</b><span>Find free legal aid and self-help by state and topic.</span></a>
        <a class="res" href="https://www.law.cornell.edu/wex" target="_blank" rel="noopener"><b>Cornell Law &mdash; Wex</b><span>Plain-language legal dictionary &amp; explanations from Cornell Law School.</span></a>
        <a class="res" href="https://www.courts.ca.gov/selfhelp.htm" target="_blank" rel="noopener"><b>California Courts Self-Help</b><span>Official step-by-step guides for common court matters.</span></a>
        <a class="res" href="https://www.usa.gov/legal-aid" target="_blank" rel="noopener"><b>USA.gov Legal Aid</b><span>Government directory of free and low-cost legal help.</span></a>
        <a class="res" href="https://www.lsc.gov/about-lsc/what-legal-aid/find-legal-aid" target="_blank" rel="noopener"><b>Legal Services Corporation</b><span>Find your local federally funded legal-aid office.</span></a>
        <a class="res" href="https://www.nolo.com/legal-encyclopedia" target="_blank" rel="noopener"><b>Nolo Legal Encyclopedia</b><span>Readable articles on tenants, family, debt, and more.</span></a>
      </div>
    </section>

    <section class="panel who">
      <h2>Choose who you want to reach</h2>
      <p>When you're ready for a person, you pick. Your summary goes only where you choose, only when you press send.</p>
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
  <style>
    .pro-btn { display:block; width:100%; text-align:left; margin:8px 0; padding:13px 16px; border-radius:12px;
               border:1.5px solid #d5e2ec; background:#fff; cursor:pointer; font-size:15px; }
    .pro-btn span { display:block; font-size:12.5px; color:#7b8b99; margin-top:3px; font-weight:400; }
    .pro-btn.picked { border-color:#2e6e8e; background:#f0f7fb; box-shadow:0 0 0 2px rgba(46,110,142,0.18); }
    .reslib { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:10px; margin-top:12px; }
    .res { display:block; text-decoration:none; border:1px solid #d5e2ec; border-radius:12px; padding:13px 15px;
           background:#fff; color:#1e3a5c; transition:all 0.2s ease; }
    .res:hover { border-color:#2e6e8e; box-shadow:0 4px 14px rgba(46,110,142,0.15); transform:translateY(-1px); }
    .res span { display:block; font-size:12.5px; color:#7b8b99; margin-top:4px; }
  </style>
  <script>
    let pickedPro = '';
    function pickPro(btn){
      document.querySelectorAll('.pro-btn').forEach(b=>b.classList.remove('picked'));
      btn.classList.add('picked'); pickedPro = btn.dataset.pro;
      document.getElementById('pro-picked').textContent = 'You chose: ' + pickedPro + '.';
    }
  </script>
  <script>
    function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
    function loadConvo(){
      let log=[]; try{ log=JSON.parse(sessionStorage.getItem('innerlight_convo')||'[]'); }catch(e){}
      const box=document.getElementById('convo-summary');
      if(!log.length){ box.innerHTML='<p class="u">It looks like the conversation did not carry over. You can use the boxes below to describe your legal issue in your own words.</p>'; return; }
      box.innerHTML = log.map(function(t){ return '<p class="'+(t.role==='user'?'u':'a')+'"><b>'+(t.role==='user'?'You said':'InnerLight')+'</b>'+esc(t.text)+'</p>'; }).join('');
    }
    function sendToLegal(){
      if (typeof pickedPro !== 'undefined' && !pickedPro){
        document.getElementById('status').textContent='First, tap the kind of legal help you want above \u2014 you choose, always.';
        return;
      }
      document.getElementById('status').innerHTML='Reaching a human for you\u2026';
      fetch('/api/connect/request', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({kind:'legal', pro: pickedPro||'legal help', summary: ''})})
      .then(r=>r.json()).then(function(d){
        document.getElementById('status').innerHTML =
          'Your request for a <b>' + (pickedPro||'legal professional').toLowerCase() + '</b> is in, and a human has been alerted. '
          + 'While our network grows, an <b>InnerLight responder</b> \u2014 our founder, not an attorney \u2014 will meet you first '
          + 'and help arrange the right legal help.<br><br>'
          + '<a href="' + d.room + '" target="_blank" style="display:inline-block;background:#2e6e8e;color:#fff;'
          + 'padding:13px 26px;border-radius:999px;font-weight:700;text-decoration:none;">Join your private video room</a>';
      }).catch(function(){
        document.getElementById('status').textContent='The connection request could not go through right now.';
      });
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


# ---------------------------------------------------------------------------
# INFORMATION PAGES — About, How It Works, Privacy, Contact.
# For a mental-health product, people won't trust it without knowing who is
# behind it and how their words are handled. These build that trust. Styled
# "calm but alive" to match the rest of InnerLight.
# ---------------------------------------------------------------------------
def _info_page(title, inner):
    return render_template_string("""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }} &mdash; InnerLight</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:'Segoe UI', system-ui, -apple-system, sans-serif; color:#2d4a3e;
         background:linear-gradient(160deg,#f4faf7 0%,#eef6f2 55%,#f0f5fa 100%);
         line-height:1.7; min-height:100vh; }
  .breathe { animation:breathe 5s ease-in-out infinite; }
  @keyframes breathe { 0%,100%{opacity:.85;transform:scale(1);} 50%{opacity:1;transform:scale(1.04);} }
  .wrap { max-width:720px; margin:0 auto; padding:54px 26px 80px; }
  .mark { font-size:40px; color:#7eb8a0; text-align:center; margin-bottom:6px; }
  .brand { text-align:center; font-size:15px; letter-spacing:.16em; text-transform:uppercase;
           color:#7fa595; margin-bottom:30px; }
  h1 { font-size:29px; font-weight:600; color:#274539; margin-bottom:18px; letter-spacing:.01em; }
  h2 { font-size:18px; font-weight:600; color:#3a6553; margin:30px 0 10px; }
  p { font-size:16px; color:#40564d; margin-bottom:15px; }
  .lead { font-size:18px; color:#35544a; margin-bottom:22px; }
  .soft { background:rgba(255,255,255,.6); border:1px solid #d8e8e0; border-left:4px solid #7eb8a0;
          border-radius:0 14px 14px 0; padding:18px 22px; margin:22px 0; }
  a { color:#3a8f74; }
  .back { display:inline-block; margin-top:38px; color:#6d8f80; text-decoration:none; font-size:15px;
          border-bottom:1px solid transparent; }
  .back:hover { border-bottom-color:#7eb8a0; }
  .footer { margin-top:46px; padding-top:20px; border-top:1px solid #dcebe4; font-size:13px; color:#9bb3aa; text-align:center; }
  .footer a { color:#7d9f91; text-decoration:none; margin:0 7px; }
</style></head><body>
  <div class="wrap">
    <div class="mark breathe" aria-hidden="true">&#9711;</div>
    <div class="brand">InnerLight</div>
    {{ inner|safe }}
    <a class="back" href="/">&larr; Back to InnerLight</a>
    <div class="footer">
      <a href="/about">About</a>&middot;
      <a href="/how-it-works">How it works</a>&middot;
      <a href="/privacy">Your privacy</a>&middot;
      <a href="/contact">Contact</a>
      <div style="margin-top:10px;">&copy; 2026 God's Love For Us LLC &middot; Created by Toshay S. Zeigler</div>
    </div>
  </div>
</body></html>""", title=title, inner=inner)


@app.route("/about")
def page_about():
    inner = """
    <h1>Why InnerLight exists</h1>
    <p class="lead">InnerLight was built by a father who lived the wait &mdash; and decided no family should face it alone.</p>

    <p>Toshay S. Zeigler was born two months after a family tragedy that shaped generations of mental-health
    struggle in his family. He entered foster care at nineteen months old and stayed until he was six. From six to
    thirteen he lived with his mother, stepfather, and siblings on 36th Street in Coney Island, Brooklyn &mdash; years
    when poverty, addiction, and violence were commonplace around him.</p>

    <p>Then, on November 7, 1987, at thirteen years old, Toshay and his older brother made a decision few adults could
    make: with the help of a family friend, they walked into the Staten Island Police Station and asked to be placed
    somewhere else. He advocated for himself before he knew the word. The system he asked for protection &mdash;
    foster care and group homes until eighteen &mdash; proved, in many ways, worse than what he had fled. He has
    lived every seat in the room: the baby the system took, the child returned to an unsafe home, the teenager who
    sought help voluntarily, and the one the help failed anyway. No one has to explain fragmented systems to him.
    He was the child inside the fragments.</p>

    <p>As an adult he built careers in logistics, dispatching, transportation, and in-home care, and &mdash; decades
    after a difficult first attempt at college &mdash; earned two associate degrees and a university-transfer
    certificate while caregiving and working. But the greatest education of his life came from being a father. Toshay is the primary caregiver for his daughters, both of whom
    have faced significant mental-health challenges. One has gone through repeated psychiatric crises. Every crisis
    meant navigating hospitals, psychiatrists, medications, school systems, insurance, county agencies, disability
    services, and community programs &mdash; while trying to keep a family together.</p>

    <div class="soft">
      <p style="margin:0;">Those years revealed a painful truth: help exists, but it is fragmented. Families are
      expected to become experts in medicine, law, education, housing, and government during the worst moments of
      their lives &mdash; and in the gap between "we need help" and "help has arrived," they wait, often 45 minutes
      to two hours, alone. InnerLight was built to hold that space.</p>
    </div>

    <p>The calming heart of InnerLight was proven in an unexpected place. During years of rideshare driving, Toshay
    noticed that when calm instrumental music was already playing, agitated passengers settled &mdash; reliably,
    across thousands of rides. It worked on strangers. It worked on his own family, in his own car, in their hardest
    moments. That observation didn't create the mission &mdash; his daughters did &mdash; but it revealed the method:
    the right sound, at the right level, at the right moment, can hold a person until human help arrives.</p>

    <h2>Who is behind it</h2>
    <p>InnerLight is created by <strong>Toshay S. Zeigler</strong>, founder of <strong>God's Love For Us LLC</strong>
    &mdash; a caregiver father, a student of law and public policy at San Jos&eacute; State University with the
    long-term goal of law school, and the holder of two associate degrees earned while caregiving and working.
    He did not begin designing with AI because he wanted to build technology. He began because he wanted to build
    something that would help families like his: systems that organize knowledge, explain complex subjects in plain
    language, protect privacy, and help people understand their options &mdash; without ever replacing doctors,
    therapists, attorneys, or other professionals.</p>

    <h2>Built by a person, with the help of AI</h2>
    <p>InnerLight is built by Toshay directly, working alongside artificial intelligence as a collaborator and tool. The
    vision, the direction, and every decision about what InnerLight should be are his. AI helps build it &mdash; but the
    idea, and the responsibility, are human.</p>

    <h2>What InnerLight believes</h2>
    <p>Technology should <strong>strengthen</strong> human decision-making, not replace it. Mental-health tools should
    <strong>complement</strong> human care, never pretend to be it. Your privacy is not a feature to trade away &mdash;
    it is the foundation. And no one reaching out for help should have their first response be a waitlist.</p>

    <div class="soft">
      <p style="margin:0;">If InnerLight succeeds, it will mean another father or mother spends less time searching
      for answers and more time caring for the people they love. InnerLight does not diagnose, prescribe, or practice
      medicine or law. It is a place to be heard and steadied, and a bridge to the right human help &mdash; never a
      replacement for it.</p>
    </div>
    """
    return _info_page("About", inner)


@app.route("/how-it-works")
def page_how():
    inner = """
    <h1>How InnerLight works</h1>
    <p class="lead">Simple, private, and built for the moment you can't wait.</p>

    <h2>1. A calm space opens</h2>
    <p>When you arrive, a soft, calming environment is already there &mdash; gentle sound and a peaceful scene, present
    from the first moment, not something you have to switch on. It's designed to help your body settle before anything
    else happens.</p>

    <h2>2. You tell your story, your way</h2>
    <p>You can type or speak &mdash; whatever feels easier. InnerLight listens to what you actually mean, reflects it
    back, and asks one gentle question at a time, drawn from what you said. Never a wall of forms. Never rushed. You
    decide when you're finished and ready for a response &mdash; nothing answers over you.</p>

    <h2>3. You are met where you are</h2>
    <p>The calming sound can gently shift to match and soothe how you're feeling, helping bring intensity down. The goal
    is to help you feel heard and steadier &mdash; to hold the space with you while you wait.</p>

    <h2>4. A bridge to real help &mdash; only with your consent</h2>
    <p>When it would help, InnerLight can connect you to real human support &mdash; a crisis line, a mobile crisis team,
    a telehealth provider, and in urgent moments the right emergency help. If you choose to share a summary of what you
    talked about, <strong>you</strong> review and control it first. Nothing is shared without your say-so.</p>

    <div class="soft">
      <p style="margin:0;">InnerLight is a companion for the wait and a bridge to care. It does not diagnose or treat,
      and it is not a substitute for professional or emergency help. If you are in immediate danger, call or text 988,
      or call 911.</p>
    </div>
    """
    return _info_page("How it works", inner)


@app.route("/privacy")
def page_privacy():
    inner = """
    <h1>Your privacy</h1>
    <p class="lead">Your story is yours. That is the whole point.</p>

    <p>InnerLight was born from an idea about protecting people's private information. That principle still sits at its
    center. What you share here is treated with care and encryption, and it is not put on display for anyone.</p>

    <h2>What you share, you control</h2>
    <p>If InnerLight ever helps connect you to a provider or crisis resource, and you choose to send a summary of your
    conversation, <strong>you see and approve it first</strong>. You can edit it. It is never sent without your consent,
    and the person receiving it cannot change your words.</p>

    <h2>Nothing is shown to you that could unsettle you</h2>
    <p>InnerLight is designed to be calming. It does not display clinical labels, diagnoses, or scores to you. It is a
    place to be heard, not measured.</p>

    <h2>Honest limits</h2>
    <p>InnerLight is a supportive companion and a bridge to human help. It is not a clinical or diagnostic service, and
    it does not replace professional care or licensed legal counsel. In an emergency, please reach real human help
    right away &mdash; call or text 988, or call 911.</p>

    <div class="soft">
      <p style="margin:0;">If you have questions about privacy, you can reach God's Love For Us LLC through the
      <a href="/contact">contact page</a>.</p>
    </div>
    """
    return _info_page("Your privacy", inner)


@app.route("/contact")
def page_contact():
    inner = """
    <h1>Contact</h1>
    <p class="lead">InnerLight is built by a person who wants to hear from you.</p>

    <p>InnerLight is created and maintained by <strong>Toshay S. Zeigler</strong>, founder of
    <strong>God's Love For Us LLC</strong>. Whether you're a person who used InnerLight, a provider or organization
    interested in a pilot, or someone who simply wants to share a thought &mdash; your message is welcome.</p>

    <div class="soft">
      <p style="margin:0 0 6px;"><strong>God's Love For Us LLC</strong></p>
      <p style="margin:0 0 6px;">Founder: Toshay S. Zeigler</p>
      <p style="margin:0;">Email: <a href="mailto:[your email]">[your email]</a><br>
      Phone: [your phone]</p>
    </div>

    <p style="font-size:14px;color:#7d9f91;">You can add your real email and phone here whenever you're ready &mdash;
    right now these are placeholders so the page is live and ready.</p>

    <div class="soft">
      <p style="margin:0;"><strong>If this is an emergency</strong> and you or someone else may be in danger, please
      don't wait for a reply here &mdash; call or text <strong>988</strong> (Suicide &amp; Crisis Lifeline), or call
      <strong>911</strong>.</p>
    </div>
    """
    return _info_page("Contact", inner)


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
    """Return the calming instrumental tracks to play — real bundled audio,
    reliable on every device. The person picks the door by how they arrive:

      * SPA — gentle arrival state. Everyone starts here (already playing).
      * DEEPCALM — warm, low, breathing groove to bring an AGITATED / angry
        person DOWN into the quiet (Barry White warmth).
      * LIFTING — buoyant, gently rising warm groove to bring a DEPRESSED /
        flat person UP out of the dark (September warmth).
      * SYMPHONY — fuller, to catch attention of someone very upset, then
        transition down to spa.

    This mirrors the proven car method: read the person, meet them where they
    are, then guide the sound to move them toward calm.
    """
    emotion = (request.args.get("emotion", "") or "").lower()
    risk = (request.args.get("risk", "") or "").lower()
    audio_dir = Path(__file__).resolve().parent.parent / "audio"

    # LEARNED CALM DNA: fingerprints analyzed from the real tracks (tempo, key,
    # brightness, busyness -> a 0-1 calm score). Lets us order by measured calm,
    # not just filename. This is the analysis half of generative sound.
    global _FINGERPRINTS
    try:
        _FINGERPRINTS
    except NameError:
        try:
            with open(Path(__file__).resolve().parent / "track_fingerprints.json") as fpf:
                _FINGERPRINTS = json.load(fpf)
        except Exception:
            _FINGERPRINTS = {}

    def lane(prefix, label, calmest_first=None):
        if not audio_dir.exists():
            return []
        def track_number(name):
            try:
                return int(name.rsplit("_", 1)[1].split(".")[0])
            except (IndexError, ValueError):
                return 0
        files = [p.name for p in audio_dir.glob(f"{prefix}_*.mp3")]
        if calmest_first is not None and _FINGERPRINTS:
            def calm_of(n):
                fp = _FINGERPRINTS.get(n, {})
                return fp.get("calm_score", 0.5)
            files.sort(key=calm_of, reverse=calmest_first)  # True: calmest first
        else:
            files.sort(key=track_number)
        return [{"url": f"/audio/{n}", "name": label,
                 "fp": _FINGERPRINTS.get(n, {})} for n in files]

    calm = lane("calm", "Calm", calmest_first=True)   # gentlest measured track greets arrival
    deepcalm = lane("deepcalm", "Deep calm", calmest_first=True)   # calmest first to settle agitation
    lifting = lane("lifting", "Lifting", calmest_first=False)      # brightest first to lift low mood

    agitated_markers = ("anger", "angry", "agitat", "panic", "fear", "rage", "upset",
                        "anxious", "anxiety", "frustrat", "furious", "tense")
    down_markers = ("sad", "depress", "hopeless", "empty", "numb", "flat", "down",
                    "worthless", "tired", "exhausted", "alone", "lonely", "grief")

    is_agitated = risk in ("high", "critical") or any(m in emotion for m in agitated_markers)
    is_down = any(m in emotion for m in down_markers)

    # Agitated / very upset -> deep-calm to bring them DOWN, then ease to calm.
    if is_agitated and deepcalm:
        return jsonify({"tracks": deepcalm, "then": calm,
                        "transition_after_seconds": 240, "lane": "deepcalm",
                        "status": "ok"})
    # Depressed / flat -> lifting to bring them UP, then ease to calm.
    if is_down and lifting:
        return jsonify({"tracks": lifting, "then": calm,
                        "transition_after_seconds": 300, "lane": "lifting",
                        "status": "ok"})
    # Default / arrival -> gentle calm, already present.
    return jsonify({"tracks": calm or deepcalm, "then": [],
                    "transition_after_seconds": 0, "lane": "calm", "status": "ok"})


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

@app.route("/api/transcribe/token")
def api_transcribe_token():
    """Provide the browser a SHORT-LIVED Deepgram token so it can stream live
    microphone audio for transcription (the Zoom way). The real DEEPGRAM_API_KEY
    stays on the server and is never sent to the page. Uses Deepgram's modern
    /auth/grant endpoint, which is purpose-built for short-lived client tokens.
    """
    import urllib.request
    import urllib.error
    main_key = os.environ.get("DEEPGRAM_API_KEY", "").strip().strip('"').strip("'")
    if not main_key:
        return jsonify({"ok": False, "reason": "no_key",
                        "message": "Transcription key not set. Add DEEPGRAM_API_KEY in the host settings."}), 200
    try:
        body = json.dumps({"ttl_seconds": 60}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.deepgram.com/v1/auth/grant",
            data=body, method="POST",
            headers={"Authorization": f"Token {main_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            grant = json.loads(r.read().decode("utf-8"))
        token = grant.get("access_token") or grant.get("token") or grant.get("key")
        if not token:
            return jsonify({"ok": False, "reason": "no_token",
                            "message": "Deepgram did not return a token."}), 200
        return jsonify({"ok": True, "token": token, "expires_in": grant.get("expires_in", 60)})
    except urllib.error.HTTPError as e:
        detail = ""
        try: detail = e.read().decode("utf-8")[:160]
        except Exception: pass
        return jsonify({"ok": False, "reason": "deepgram_http",
                        "message": f"Deepgram responded {e.code}. {detail}"}), 200
    except Exception as e:
        return jsonify({"ok": False, "reason": "error", "message": str(e)[:160]}), 200


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


@app.route("/audio/<path:filename>")
def serve_audio(filename):
    """Serve the bundled, calming instrumental tracks (spa / symphony lanes).
    Real audio files streamed from the app itself — reliable on every device,
    no external service, no stutter."""
    audio_dir = Path(__file__).resolve().parent.parent / "audio"
    file_path = audio_dir / filename
    if file_path.exists() and file_path.is_file():
        from flask import send_file
        return send_file(str(file_path), mimetype="audio/mpeg")
    return ("audio not found", 404)




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

    # --- Comprehension: understand what the person MEANS (Claude), with the
    # local engine as a reliable fallback if the model isn't set or is slow. ---
    face_emo = ""
    if isinstance(data, dict):
        face_emo = str(data.get("face_emotion", "")).strip()
    history = data.get("conversation") if isinstance(data, dict) else None
    smart = comprehension_engine.respond(
        user_text=message, history=history, risk=risk, face_emotion=face_emo,
    )
    if smart:
        initial_conv = {"response": smart["response"], "question": smart.get("question", "")}
    else:
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

    # --- Comprehension: understand the follow-up (Claude), fall back locally ---
    face_emotion = ""
    if isinstance(context, dict):
        face_emotion = str(context.get("face_emotion", "")).strip()
    history_l = context.get("conversation") if isinstance(context, dict) else None
    smart_l = comprehension_engine.respond(
        user_text=answer, history=history_l, risk=learn_risk, face_emotion=face_emotion,
    )
    if smart_l:
        conv = {"response": smart_l["response"], "question": smart_l.get("question", "")}
    else:
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




# ===========================================================================
# FOUNDER'S ADMIN DASHBOARD — anonymous operational metrics ONLY.
# Never stores names, words, voices, faces, or anything a person said.
# Counts and clock-times: sessions, time-to-first-sound, lane shifts, handoffs.
# Protected by the ADMIN_KEY environment variable set on Render.
# ===========================================================================
_METRICS_LOCK = threading.Lock()

# ===========================================================================
# RESEARCH DATA HOME — persistent storage selection.
# If a Render persistent disk is mounted at /var/data, all research data
# (metrics, cases, studies, connect requests) lives there and survives every
# deploy. Without the disk, data falls back to /tmp and WILL be lost on
# deploy — a loud warning is printed so this is never silent again.
# ===========================================================================
_DATA_DIR = "/var/data" if os.path.isdir("/var/data") else "/tmp"
if _DATA_DIR == "/tmp":
    print("[InnerLight] WARNING: no persistent disk at /var/data — research data "
          "will NOT survive deploys. Add a Render disk mounted at /var/data.")
else:
    print("[InnerLight] Research data home: /var/data (persistent — survives deploys)")

_METRICS_FILE = os.environ.get("METRICS_FILE", _DATA_DIR + "/innerlight_metrics.json")

def _metrics_load():
    try:
        with open(_METRICS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _metrics_save(m):
    try:
        with open(_METRICS_FILE, "w") as f:
            json.dump(m, f)
    except Exception:
        pass

app.secret_key = hashlib.sha256(
    ("innerlight-founder-session::" + os.environ.get("ADMIN_KEY", "unset")).encode()
).hexdigest()

@app.route("/api/metrics/event", methods=["POST"])
def metrics_event():
    """Receive one anonymous counter event from the app."""
    data = request.get_json(silent=True) or {}
    etype = str(data.get("type", ""))[:40]
    value = data.get("value")
    sid = str(data.get("sid", ""))[:12] or "anon"
    allowed = {"session_start", "first_sound_ms", "message_sent",
               "lane_switch", "handoff_click", "listen_autostop",
               "face_shift", "scene_change", "hesitation",
               "soundbox_open_ms", "track_skip", "track_react", "distraction",
               "gaze_aversion", "heart_read", "selfreport", "wordplay", "subzone",
               "activity_open", "reengage_prompt", "bloom"}
    if etype not in allowed:
        return jsonify({"status": "ignored"}), 200
    day = time.strftime("%Y-%m-%d")
    with _METRICS_LOCK:
        m = _metrics_load()
        d = m.setdefault(day, {"sessions": 0, "messages": 0, "lane_switches": 0,
                               "autostops": 0, "first_sound_ms_sum": 0,
                               "first_sound_count": 0, "handoffs": {},
                               "face_shifts": 0, "scene_changes": 0,
                               "hesitations": 0, "track_skips": 0,
                               "soundbox_ms_sum": 0, "soundbox_count": 0})
        by = d.setdefault("by_session", {})
        if len(by) < 300 or sid in by:
            sess = by.setdefault(sid, {"shifts": 0, "messages": 0, "hesitations": 0,
                                       "scenes": 0, "distractions": 0, "lanes": 0})
        else:
            sess = None
        if etype == "session_start":
            d["sessions"] += 1
        elif etype == "message_sent":
            d["messages"] += 1
            if sess: sess["messages"] += 1
        elif etype == "lane_switch":
            d["lane_switches"] += 1
            if sess: sess["lanes"] += 1
        elif etype == "listen_autostop":
            d["autostops"] += 1
        elif etype == "first_sound_ms" and isinstance(value, (int, float)) and 0 <= value < 600000:
            d["first_sound_ms_sum"] += int(value)
            d["first_sound_count"] += 1
        elif etype == "face_shift":
            d["face_shifts"] = d.get("face_shifts", 0) + 1
            if sess: sess["shifts"] += 1
        elif etype == "scene_change":
            d["scene_changes"] = d.get("scene_changes", 0) + 1
            if sess: sess["scenes"] += 1
        elif etype == "hesitation":
            d["hesitations"] = d.get("hesitations", 0) + 1
            if sess: sess["hesitations"] += 1
        elif etype == "track_skip":
            d["track_skips"] = d.get("track_skips", 0) + 1
            tname = str(value)[:40] if value else "unknown"
            td = d.setdefault("track_dislikes", {})
            td[tname] = td.get(tname, 0) + 1
        elif etype == "soundbox_open_ms" and isinstance(value, (int, float)) and 0 <= value < 3600000:
            d["soundbox_ms_sum"] = d.get("soundbox_ms_sum", 0) + int(value)
            d["soundbox_count"] = d.get("soundbox_count", 0) + 1
        elif etype == "track_react" and value:
            try:
                tname, verdict = str(value).rsplit("|", 1)
                tname = tname[:40]
                if verdict in ("liked", "neutral", "disliked"):
                    tr = d.setdefault("track_reactions", {})
                    entry = tr.setdefault(tname, {"liked": 0, "neutral": 0, "disliked": 0})
                    entry[verdict] += 1
            except Exception:
                pass
        elif etype == "distraction":
            d["distractions"] = d.get("distractions", 0) + 1
            if sess: sess["distractions"] += 1
        elif etype == "subzone" and value:
            try:
                zone, pct = str(value).split("|", 1)
                pct = int(pct); zone = zone[:20]
                if 0 <= pct <= 100:
                    z = d.setdefault("subzones", {})
                    e2 = z.setdefault(zone, {"sum": 0, "n": 0})
                    e2["sum"] += pct; e2["n"] += 1
            except Exception:
                pass
        elif etype == "activity_open" and value:
            a = d.setdefault("activities", {})
            nm = str(value)[:20]
            a[nm] = a.get(nm, 0) + 1
        elif etype == "bloom":
            d["blooms"] = d.get("blooms", 0) + 1
            if sess: sess["blooms"] = sess.get("blooms", 0) + 1
        elif etype == "reengage_prompt":
            d["reengage_prompts"] = d.get("reengage_prompts", 0) + 1
        elif etype == "wordplay":
            d["wordplay_rounds"] = d.get("wordplay_rounds", 0) + 1
            if sess: sess["wordplay"] = sess.get("wordplay", 0) + 1
        elif etype == "gaze_aversion":
            d["gaze_aversions"] = d.get("gaze_aversions", 0) + 1
            if sess: sess["gaze"] = sess.get("gaze", 0) + 1
        elif etype == "heart_read" and isinstance(value, (int, float)) and 40 <= value <= 180:
            d["heart_sum"] = d.get("heart_sum", 0) + int(value)
            d["heart_count"] = d.get("heart_count", 0) + 1
        elif etype == "selfreport" and value:
            try:
                phase, score = str(value).split("|", 1)
                score = int(score)
                if phase in ("arrival", "later") and 1 <= score <= 5:
                    key = f"sam_{phase}"
                    d[key + "_sum"] = d.get(key + "_sum", 0) + score
                    d[key + "_count"] = d.get(key + "_count", 0) + 1
            except Exception:
                pass
        elif etype == "handoff_click":
            dest = str(value)[:24] if value else "unknown"
            d["handoffs"][dest] = d["handoffs"].get(dest, 0) + 1
        _metrics_save(m)
    return jsonify({"status": "ok"})


LOGIN_PAGE = """
<!doctype html><html><head><title>InnerLight — Founder Sign In</title>
<meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
      font-family:Arial;background:linear-gradient(135deg,#0f2447 0%,#1d4ed8 55%,#7c3aed 100%);}
 .card{background:rgba(255,255,255,0.97);border-radius:16px;padding:36px 34px;width:330px;
       box-shadow:0 18px 50px rgba(10,20,60,0.45);}
 h1{font-size:19px;color:#1e3a8a;margin:0 0 4px;} .sub{font-size:12px;color:#64748b;margin-bottom:22px;}
 label{display:block;font-size:12px;color:#334155;font-weight:700;margin:12px 0 5px;letter-spacing:0.3px;}
 input{width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid #cbd5e1;border-radius:9px;
       font-size:15px;} input:focus{outline:2px solid #3b82f6;border-color:#3b82f6;}
 button{margin-top:20px;width:100%;padding:12px;border:0;border-radius:9px;font-size:15px;font-weight:700;
        color:#fff;background:linear-gradient(90deg,#1d4ed8,#7c3aed);cursor:pointer;}
 .err{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;border-radius:8px;padding:9px 12px;
      font-size:13px;margin-bottom:6px;display:{{ 'block' if err else 'none' }};}
</style></head><body>
<form class="card" method="POST" action="/admin/login">
  <h1>Founder's Operations Room</h1>
  <div class="sub">InnerLight &mdash; God's Love For Us LLC</div>
  <div class="err">{{ err or '' }}</div>
  <label>Username</label>
  <input name="username" autocomplete="username" autofocus>
  <label>Password</label>
  <input name="password" type="password" autocomplete="current-password">
  <button type="submit">Enter</button>
</form></body></html>
"""

@app.route("/admin/login", methods=["POST"])
def admin_login():
    admin_key = os.environ.get("ADMIN_KEY", "")
    admin_user = os.environ.get("ADMIN_USER", "founder")
    u = request.form.get("username", "")
    p = request.form.get("password", "")
    if admin_key and secrets.compare_digest(p, admin_key) and secrets.compare_digest(u, admin_user):
        session["founder_ok"] = True
        session.permanent = False
        return redirect("/admin")
    return render_template_string(LOGIN_PAGE, err="That username or password is not right."), 401

@app.route("/admin/logout")
def admin_logout():
    session.pop("founder_ok", None)
    return redirect("/admin")

@app.route("/admin")
def admin_dashboard():
    """Founder-only operations room. Open /admin?key=YOUR_ADMIN_KEY"""
    admin_key = os.environ.get("ADMIN_KEY", "")
    if not admin_key:
        return ("<h2 style='font-family:Arial;padding:40px;'>Admin key not set yet.</h2>"
                "<p style='font-family:Arial;padding:0 40px;'>On Render: Environment &rarr; "
                "Add Environment Variable &rarr; name <b>ADMIN_KEY</b>, value = a password only "
                "you know &rarr; Save &amp; redeploy. Then sign in at /admin</p>"), 200
    if not session.get("founder_ok"):
        return render_template_string(LOGIN_PAGE), 200
    with _METRICS_LOCK:
        m = _metrics_load()
    days = sorted(m.keys(), reverse=True)[:14]
    rows = []
    for day in days:
        d = m[day]
        avg_ms = (d["first_sound_ms_sum"] / d["first_sound_count"]) if d.get("first_sound_count") else 0
        avg_box = (d.get("soundbox_ms_sum",0) / d["soundbox_count"]) if d.get("soundbox_count") else 0
        handoffs = ", ".join(f"{k}: {v}" for k, v in sorted(d.get("handoffs", {}).items())) or "—"
        dislikes = ", ".join(f"{k}: {v}" for k, v in sorted(d.get("track_dislikes", {}).items(), key=lambda x: -x[1])[:5]) or "—"
        true_sessions = max(d.get('sessions', 0), len(d.get('by_session', {})))
        rows.append(f"<tr><td>{day}</td><td>{true_sessions}</td>"
                    f"<td>{avg_ms/1000:.1f}s</td><td>{d.get('messages',0)}</td>"
                    f"<td>{d.get('face_shifts',0)}</td><td>{d.get('lane_switches',0)}</td>"
                    f"<td>{d.get('scene_changes',0)}</td><td>{d.get('hesitations',0)}</td>"
                    f"<td>{avg_box/1000:.0f}s</td><td>{handoffs}</td>"
                    f"<td>{dislikes}</td><td>{d.get('autostops',0)}</td>"
                    f"<td>{d.get('gaze_aversions',0)}</td>"
                    f"<td>{(d.get('heart_sum',0)/d.get('heart_count',1)):.0f} bpm</td>"
                    f"<td>{(d.get('sam_arrival_sum',0)/max(1,d.get('sam_arrival_count',0))):.1f} &rarr; "
                    f"{(d.get('sam_later_sum',0)/max(1,d.get('sam_later_count',0))):.1f}</td></tr>")
    body = "".join(rows) or "<tr><td colspan=11>No activity recorded yet.</td></tr>"
    # Bar graph of sessions per day (oldest -> newest)
    graph_days = list(reversed(days))
    max_sess = max([m[d0].get("sessions", 0) for d0 in graph_days] + [1])
    bars = "".join(
        f"<div class='bar-col'><div class='bar' style='height:{max(3, int(120 * m[d0].get('sessions',0) / max_sess))}px'"
        f" title='{m[d0].get('sessions',0)} sessions'></div><div class='bar-lbl'>{d0[5:]}</div>"
        f"<div class='bar-num'>{m[d0].get('sessions',0)}</div></div>"
        for d0 in graph_days) or "<i>No sessions yet.</i>"
    # Aggregate track reactions across shown days
    agg = {}
    for d0 in days:
        for tname, e in m[d0].get("track_reactions", {}).items():
            a = agg.setdefault(tname, {"liked": 0, "neutral": 0, "disliked": 0})
            for k in a: a[k] += e.get(k, 0)
    t_rows = "".join(
        f"<tr><td>{t}</td><td>{e['liked']}</td><td>{e['neutral']}</td><td>{e['disliked']}</td></tr>"
        for t, e in sorted(agg.items(), key=lambda x: -(x[1]['liked'] + x[1]['neutral'] + x[1]['disliked'])))
    t_rows = t_rows or "<tr><td colspan=4>No track reactions recorded yet.</td></tr>"
    # Per-session breakdown for the most recent day shown
    sess_rows = ""
    if days:
        latest = days[0]
        by = m[latest].get("by_session", {})
        for i, (sid0, e) in enumerate(sorted(by.items()), 1):
            sess_rows += (f"<tr><td>Person {i}</td><td>{e.get('shifts',0)}</td>"
                          f"<td>{e.get('messages',0)}</td><td>{e.get('hesitations',0)}</td>"
                          f"<td>{e.get('scenes',0)}</td><td>{e.get('distractions',0)}</td>"
                          f"<td>{e.get('wordplay',0)}</td><td>{e.get('lanes',0)}</td></tr>")
    sess_rows = sess_rows or "<tr><td colspan=7>No sessions recorded yet today.</td></tr>"
    # Experimental sub-zone accuracy across all shown days
    zagg = {}
    for d0 in days:
        for zone, e in m[d0].get("subzones", {}).items():
            a = zagg.setdefault(zone, {"sum": 0, "n": 0})
            a["sum"] += e.get("sum", 0); a["n"] += e.get("n", 0)
    ZLABEL = {"underEyeL":"Under left eye","underEyeR":"Under right eye","noseBridge":"Nose bridge",
              "mouthSideL":"Left of mouth","mouthSideR":"Right of mouth"}
    if zagg:
        subzone_rows = "".join(
            f'<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #eef2f8;">'
            f'<span>{ZLABEL.get(z, z)}</span><b style="color:#4f46e5;">{(a["sum"]/a["n"]):.0f}% agreement</b></div>'
            for z, a in sorted(zagg.items(), key=lambda x: -(x[1]["sum"]/max(1,x[1]["n"]))))
    else:
        subzone_rows = '<i>No experimental sub-zone data yet. It gathers as people use the camera.</i>'
    return render_template_string("""
<!doctype html><html><head><title>InnerLight — Operations</title>
<meta name="robots" content="noindex,nofollow">
<style>
 body{font-family:Arial;margin:0;padding:28px;color:#1e293b;
      background:linear-gradient(160deg,#0f2447 0%,#14346b 30%,#eef2ff 30.5%,#f8fafc 100%);}
 .top{display:flex;justify-content:space-between;align-items:flex-start;color:#fff;margin-bottom:24px;}
 h1{color:#fff;font-size:23px;margin:0;text-shadow:0 2px 8px rgba(0,0,0,0.3);}
 .sub{color:#c7d6f5;font-size:13px;margin-top:5px;}
 .logout{color:#c7d6f5;font-size:12px;text-decoration:none;border:1px solid rgba(255,255,255,0.4);
         padding:7px 14px;border-radius:999px;} .logout:hover{background:rgba(255,255,255,0.12);}
 table{border-collapse:collapse;width:100%;background:#fff;border-radius:12px;overflow:hidden;
       box-shadow:0 8px 28px rgba(15,36,71,0.14);}
 th,td{padding:10px 12px;text-align:left;font-size:13.5px;border-bottom:1px solid #e6ecf8;}
 th{background:linear-gradient(90deg,#1d4ed8,#4f46e5,#7c3aed);color:#fff;font-size:11.5px;letter-spacing:0.5px;}
 tr:hover td{background:#f4f7ff;}
 .note{margin-top:16px;font-size:12.5px;color:#475569;background:#fff;border-left:4px solid #4f46e5;
       border-radius:8px;padding:14px 16px;box-shadow:0 4px 16px rgba(15,36,71,0.08);line-height:1.65;}
 .graph{display:flex;align-items:flex-end;gap:8px;background:#fff;padding:18px;border-radius:12px;
        box-shadow:0 8px 28px rgba(15,36,71,0.14);margin:18px 0;overflow-x:auto;}
 .bar-col{display:flex;flex-direction:column;align-items:center;min-width:44px;}
 .bar{width:26px;background:linear-gradient(180deg,#60a5fa,#4f46e5);border-radius:4px 4px 0 0;}
 .bar-lbl{font-size:10px;color:#64748b;margin-top:4px;} .bar-num{font-size:11px;color:#4f46e5;font-weight:700;}
 h2{color:#1e3a8a;font-size:16px;margin-top:26px;}
 .sci-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px;}
 .sci{background:#fff;border-radius:10px;padding:14px 16px;font-size:12.8px;line-height:1.6;color:#334155;
      box-shadow:0 4px 16px rgba(15,36,71,0.08);border-top:3px solid #4f46e5;}
 .sci b{color:#1e3a8a;font-size:13.2px;}
</style></head><body>
<div class="top"><div>
<h1>InnerLight — Founder's Operations Room</h1>
<div class="sub">Anonymous counts and clock-times only. No words, names, faces, or voices are ever stored.</div>
</div><div><a class="logout" href="/admin/study" style="margin-right:8px;">Founder's Study</a><a class="logout" href="/admin/logout">Sign out</a></div></div>
<table>
<tr><th>Day</th><th>Sessions</th><th>Avg time to first sound</th><th>Messages</th>
<th>Expression shifts seen</th><th>Music lane shifts</th><th>Scene changes</th>
<th>Hesitations (typed then erased)</th><th>Avg time to open sound box</th>
<th>Handoff clicks</th><th>Tracks that drew dislike</th><th>Listening auto-stops</th>
<th>Gaze aversions (eyes fled)</th><th>Avg heart rate seen</th><th>Calm scale: arrival &rarr; later</th></tr>
{{ body|safe }}
</table>
<h2>Incoming connection requests — people who asked for a human</h2>
<div class="card-like" id="connects" style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.14);font-size:13.5px;">Loading&hellip;</div>
<script>
fetch('/api/admin/connects').then(r=>r.json()).then(function(d){
  const el = document.getElementById('connects');
  if(!d.connects || !d.connects.length){ el.textContent = 'No connection requests yet.'; return; }
  el.innerHTML = d.connects.map(function(c){
    return '<div style="border-bottom:1px solid #e6ecf8;padding:9px 0;">'
      + '<b style="color:#1e3a8a;">' + c.when + '</b> — ' + c.kind.toUpperCase() + ' — wants: <b>' + c.pro + '</b> '
      + '— <a href="' + c.room + '" target="_blank" style="color:#4f46e5;font-weight:700;">Join room</a>'
      + (c.summary ? '<div style="color:#475569;margin-top:4px;white-space:pre-wrap;">' + c.summary.replace(/</g,'&lt;') + '</div>' : '')
      + '</div>';
  }).join('');
}).catch(function(){ document.getElementById('connects').textContent = 'Could not load.'; });
</script>
<h2>Experimental biometric sub-zones — the frontier map</h2>
<div class="card-like" id="subzones" style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.14);font-size:13.5px;margin-bottom:8px;">
<div style="font-size:12px;color:#64748b;margin-bottom:10px;">How often each experimental skin zone (near eyes/mouth) agreed with the trusted forehead+cheek reading. Higher % = more trustworthy. This is your own data revealing which frontier zones can be read accurately.</div>
{{ subzone_rows|safe }}
</div>
<h2>Sessions per day</h2>
<div class="graph">{{ bars|safe }}</div>
<h2>Today, person by person — anonymous session breakdown</h2>
<table>
<tr><th>Session</th><th>Expression shifts</th><th>Messages</th><th>Hesitations</th>
<th>Scene changes</th><th>Distractions (looked away)</th><th>Word plays</th><th>Music lane shifts</th></tr>
{{ sess_rows|safe }}
</table>
<h2>Track reactions — the research core (all days shown)</h2>
<table>
<tr><th>Track</th><th>Liked (face eased)</th><th>Neutral</th><th>Disliked (face turned)</th></tr>
{{ t_rows|safe }}
</table>
<h2>The scientific method — where this study stands</h2>
<div class="sci-grid">
 <div class="sci"><b>1. Observation (complete)</b><br>Across ~2,500 rideshare trips, agitated passengers reliably settled when calm instrumental music was already playing on entry. Repeated, real-world, years-long observation.</div>
 <div class="sci"><b>2. Question (framed)</b><br>Can adaptive calming sound, delivered during the crisis wait-gap, measurably reduce acute distress?</div>
 <div class="sci"><b>3. Hypothesis (stated, falsifiable)</b><br>People using InnerLight will show measurably lower distress at the end of a session than at arrival — in heart rate, self-reported calm, and facial-expression volatility. If the numbers do not move, the hypothesis is rejected. We accept that outcome in advance.</div>
 <div class="sci"><b>4. Predictions (specific)</b><br>(a) Heart rate drifts toward the person's own baseline during a session. (b) The wordless calm scale improves arrival &rarr; later. (c) Expression-shift frequency declines after music-lane responses. (d) Track "liked" verdicts exceed "disliked" as lanes adapt.</div>
 <div class="sci"><b>5. Test (this instrument, now collecting)</b><br>Every column on this board is a measurement in service of the predictions above, recorded anonymously per session against each person's own baseline, on durable storage.</div>
 <div class="sci"><b>6&ndash;7. Analysis &amp; conclusion (pending pilot)</b><br>No conclusion is claimed yet. InnerLight is unvalidated until a controlled pilot analyzes these measures. This board reports; it does not yet prove.</div>
 <div class="sci"><b>8. Retest / replication (planned)</b><br>Pilot results, positive or negative, will be re-run before any claim is made. One result is an anecdote; a repeated result is evidence.</div>
 <div class="sci"><b>9. Peer review (sought)</b><br>University research partnership in progress — independent eyes on the method, the data, and the conclusions.</div>
</div>
<h2>The research basis for every number</h2>
<div class="sci-grid">
 <div class="sci"><b>Sessions &amp; uptake</b><br>
 Meta-analytic reviews of digital mental-health trials converged on five reportable engagement checkpoints:
 uptake, level of use, duration, adherence, and completion. "Sessions" is our uptake measure — the entry
 point every published engagement framework requires. Without it, no other number can be interpreted.</div>
 <div class="sci"><b>Time to first sound</b><br>
 Music-medicine research on the Iso-Principle (meeting a person's state with sound, then guiding it) treats
 stimulus onset timing as part of the intervention itself. InnerLight's clinical premise is sound arriving
 during the crisis wait-gap — so seconds-to-sound is our fidelity measure: is the intervention actually
 being delivered at the moment of need?</div>
 <div class="sci"><b>Expression shifts</b><br>
 Observational affect coding — a researcher watching and logging visible reactions — is a standard lens in
 music-intervention studies. Automated expression tracking is our continuous version of that observer.
 Shift frequency indicates emotional lability (rapid state change), a recognized marker of distress and of
 responsiveness to stimulus change.</div>
 <div class="sci"><b>Music lane shifts vs expression shifts</b><br>
 The core hypothesis under test: adaptive sound answers the observed state (stimulus-response coupling).
 Comparing these two columns is our first-order evidence of whether the system is responding — the
 adherence checkpoint, in engagement-framework terms.</div>
 <div class="sci"><b>Track reactions (liked / neutral / disliked)</b><br>
 Published music-and-stress protocols log per-song participant reactions because affective response to
 music is highly individual; preference moderates outcome. Our Track Guardian automates per-track reaction
 logging against each person's own baseline — measured musical reception, per stimulus.</div>
 <div class="sci"><b>Hesitations (typed, then erased)</b><br>
 Behavioral research on help-seeking treats approach-avoidance behavior as a disclosure-readiness marker.
 A composed-then-deleted message is an observable approach that stopped short — evidence of wanting to
 speak without yet feeling safe. High hesitation with low messaging signals a trust barrier to fix.</div>
 <div class="sci"><b>Distractions (looked away)</b><br>
 Attention-orienting research uses gaze departure and head turning as disengagement markers. In our
 grounding-based design (real scenes pulling a distressed mind back), sustained visual engagement is part
 of the mechanism — so looking away is a mechanism-level measure, not housekeeping.</div>
 <div class="sci"><b>Scene changes</b><br>
 Perceived control and choice are established moderators of stress response. A person choosing their own
 view is exercising agency; which realities people reach for (garden, moon, horizon) is itself preference
 data for grounding-scene design.</div>
 <div class="sci"><b>Handoff clicks</b><br>
 The outcome that defines InnerLight: connection to human help (the completion checkpoint). Time-to-
 resolution, not engagement time, is our success philosophy — this column is the bridge working, counted.</div>
 <div class="sci"><b>Per-person session rows</b><br>
 Aggregates hide individuals; research standards require unit-of-analysis clarity. The person-by-person
 table preserves anonymous within-session structure so 149 shifts by one person is never mistaken for
 74 by two — the difference between anecdote and data.</div>
 <div class="sci"><b>Coming next, per the measurement model</b><br>
 The strongest published protocols triangulate three lenses: physiological (heart rate and heart-rate
 variability — the autonomic markers used across music-anxiety trials), observational (our camera), and
 self-report (wordless calm scales like the Self-Assessment Manikin). InnerLight has lens two running,
 lens one in build (webcam pulse reading), lens three queued — full triangulation is the destination.</div>
</div>
<div class="note"><b>Plain reading guide:</b> Sessions = entries that day. Avg time to first sound = tap until
music (lower is better; phones cannot legally start sound before a tap). Expression shifts = changes in the
silent face reading. Hesitations = typed a real thought, erased it unsent. Distractions = an engaged face
turned away for a couple of seconds. Track verdicts come from each song's opening minute judged against that
person's own baseline. All counts are anonymous — no words, names, faces, or voices are ever stored.</div>
</body></html>""", body=body, bars=bars, t_rows=t_rows, sess_rows=sess_rows, subzone_rows=subzone_rows)


# ===========================================================================
# FOUNDER'S STUDY — private educational wing of the operations room.
# Purpose: the founder's own learning (legalese, medical terminology, process,
# legislative drafting) AND training ground for specialty routing. Everything
# produced here is a clearly-labeled educational SIMULATION for the founder
# only. It is never shown to users and is never legal or medical advice.
# ===========================================================================
_STUDY_SYSTEM = (
    "You are the private study tutor for the founder of InnerLight, a crisis-support "
    "product. The founder is a Political Science student preparing for law school. "
    "Everything you produce is an EDUCATIONAL SIMULATION for the founder's own learning "
    "and for designing better handoff routing. It is never given to end users and is "
    "not legal or medical advice. Plain language first; define every term of legalese "
    "or medical terminology in parentheses the first time it appears; spell out every "
    "acronym. Structure every answer in exactly these sections with these headings:\n"
    "1. WHAT THIS IS — classify the scenario (area of law or care, e.g. contract law, "
    "family law, telehealth psychiatry) and why it fits there.\n"
    "2. WHO HANDLES IT — the right kind of professional, and what makes that specialty "
    "the right routing target.\n"
    "3. THE PROCESS — what that professional would typically do, step by step.\n"
    "4. THE PAPERWORK — what filings/forms/documents typically exist at the relevant "
    "level (local, state, or federal), by their common names, and what each is for.\n"
    "5. WHAT IS NORMALLY SAID — the typical language/phrases used in this process, "
    "each translated to plain words.\n"
    "6. TWO MOCK OUTCOMES — two plausible, clearly-hypothetical endings and why each "
    "might happen.\n"
    "7. ROUTING LESSON — one paragraph: what words in a person's story would tell "
    "InnerLight this specialty is the right handoff.\n"
    "Be CONCISE: the whole walk-through under 600 words — depth over sprawl.\n"
    "Begin every response with the line: 'FOUNDER STUDY — educational simulation, "
    "not legal or medical advice.'"
)

@app.route("/api/admin/study", methods=["POST"])
def admin_study_api():
    if not session.get("founder_ok"):
        return jsonify({"status": "locked"}), 403
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip().strip('"').strip("'")
    if not key:
        return jsonify({"status": "error",
                        "text": "The comprehension key is not set on the server."}), 200
    data = request.get_json(silent=True) or {}
    scenario = str(data.get("scenario", ""))[:4000].strip()
    focus = str(data.get("focus", "legal"))[:20]
    if not scenario:
        return jsonify({"status": "error", "text": "Describe a scenario first."}), 200
    prompt = (f"Study focus: {focus}. Scenario to study (hypothetical, for founder "
              f"education only): {scenario}")
    body = json.dumps({
        "model": os.environ.get("INNERLIGHT_MODEL", "claude-sonnet-4-6"),
        "max_tokens": 950,
        "system": _STUDY_SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    import urllib.request
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"Content-Type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in out.get("content", [])
                       if b.get("type") == "text")
        _study_save_entry({"when": time.strftime("%Y-%m-%d %H:%M"),
                           "focus": focus, "scenario": scenario, "walkthrough": text})
        return jsonify({"status": "ok", "text": text})
    except Exception as exc:
        return jsonify({"status": "error", "text": f"Study call failed: {exc}"}), 200

_STUDY_FILE = os.environ.get("STUDY_FILE", _DATA_DIR + "/innerlight_study_log.json")
_STUDY_LOCK = threading.Lock()

def _study_load():
    try:
        with open(_STUDY_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def _study_save_entry(entry):
    with _STUDY_LOCK:
        log = _study_load()
        log.append(entry)
        log = log[-200:]  # keep the most recent 200 studies
        try:
            with open(_STUDY_FILE, "w") as f:
                json.dump(log, f)
        except Exception:
            pass

@app.route("/api/admin/study/history")
def admin_study_history():
    if not session.get("founder_ok"):
        return jsonify({"status": "locked"}), 403
    log = _study_load()
    return jsonify({"status": "ok", "studies": list(reversed(log))})

@app.route("/admin/study")
def admin_study_page():
    if not session.get("founder_ok"):
        return render_template_string(LOGIN_PAGE), 200
    return render_template_string("""
<!doctype html><html><head><title>Founder's Study — InnerLight</title>
<meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:Arial;margin:0;padding:28px;color:#1e293b;
      background:linear-gradient(160deg,#0f2447 0%,#14346b 30%,#eef2ff 30.5%,#f8fafc 100%);}
 .top{display:flex;justify-content:space-between;align-items:flex-start;color:#fff;margin-bottom:22px;}
 h1{color:#fff;font-size:23px;margin:0;text-shadow:0 2px 8px rgba(0,0,0,0.3);}
 .sub{color:#c7d6f5;font-size:13px;margin-top:5px;max-width:760px;line-height:1.5;}
 .nav a{color:#c7d6f5;font-size:12px;text-decoration:none;border:1px solid rgba(255,255,255,0.4);
        padding:7px 14px;border-radius:999px;margin-left:8px;} .nav a:hover{background:rgba(255,255,255,0.12);}
 .card{background:#fff;border-radius:12px;padding:22px;box-shadow:0 8px 28px rgba(15,36,71,0.14);margin-bottom:18px;}
 label{font-size:12px;font-weight:700;color:#334155;display:block;margin-bottom:6px;}
 textarea{width:100%;box-sizing:border-box;min-height:110px;padding:12px;border:1px solid #cbd5e1;
          border-radius:9px;font-size:15px;font-family:Arial;} textarea:focus{outline:2px solid #3b82f6;}
 select{padding:10px;border:1px solid #cbd5e1;border-radius:9px;font-size:14px;margin-right:10px;}
 button{padding:11px 26px;border:0;border-radius:9px;font-size:15px;font-weight:700;color:#fff;
        background:linear-gradient(90deg,#1d4ed8,#7c3aed);cursor:pointer;margin-top:12px;}
 #out{white-space:pre-wrap;font-size:14.5px;line-height:1.7;color:#1e293b;display:none;}
 .stamp{display:inline-block;background:#fef3c7;color:#92400e;border:1px solid #fcd34d;font-size:11px;
        font-weight:700;border-radius:6px;padding:4px 10px;margin-bottom:12px;letter-spacing:0.4px;}
 .wait{display:none;color:#4f46e5;font-weight:700;font-size:13px;margin-top:12px;}
</style></head><body>
<div class="top"><div>
<h1>Founder's Study</h1>
<div class="sub">Your private learning wing. Describe any hypothetical scenario and receive an educational
walk-through: the area of law or care, who handles it, the process, the paperwork by government level,
the language used (translated), two mock outcomes, and the routing lesson for InnerLight.
Nothing here is ever shown to users. Nothing here is legal or medical advice.</div>
</div><div class="nav"><a href="/admin">Operations Room</a><a href="/admin/logout">Sign out</a></div></div>
<div class="card">
 <label>Scenario to study (hypothetical)</label>
 <textarea id="scenario" placeholder="Example: A renter in San Jose gets a 3-day notice from their landlord after complaining about mold..."></textarea>
 <div style="margin-top:12px;">
  <label>Study focus</label>
  <select id="focus">
    <option value="legal">Legal — area of law, filings, courtroom language</option>
    <option value="medical">Medical/telehealth — care pathway, terminology</option>
    <option value="legislative">Legislative — how a bill/policy change would work</option>
  </select>
  <button onclick="runStudy()">Study it</button>
 </div>
 <div class="wait" id="wait">Preparing your study material&hellip; (this uses your comprehension credit, so it only runs when you press the button)</div>
</div>
<div class="card"><div class="stamp">FOUNDER STUDY &mdash; EDUCATIONAL SIMULATION &mdash; NOT LEGAL OR MEDICAL ADVICE</div>
<div id="out"></div></div>
<div class="card">
 <h2 style="margin-top:0;color:#1e3a8a;font-size:16px;">Cases from real sessions — de-identified</h2>
 <div style="font-size:12px;color:#64748b;margin-bottom:10px;">Every session is recorded here with names, numbers, and contact details removed before saving. Tap "Study this case" to send one into the study engine.</div>
 <div id="cases" style="font-size:13.5px;color:#334155;">Loading&hellip;</div>
</div>
<div class="card">
 <h2 style="margin-top:0;color:#1e3a8a;font-size:16px;">Saved studies — your growing casebook</h2>
 <div id="shelf" style="font-size:13.5px;color:#334155;">Loading&hellip;</div>
</div>
<script>
async function loadShelf(){
  try{
    const r = await fetch('/api/admin/study/history'); const d = await r.json();
    const shelf = document.getElementById('shelf');
    if (!d.studies || !d.studies.length){ shelf.textContent = 'No studies saved yet. Every study you run is kept here.'; return; }
    shelf.innerHTML = d.studies.map(function(st, i){
      return '<details style="margin-bottom:10px;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">'
        + '<summary style="cursor:pointer;font-weight:700;color:#1d4ed8;">' + st.when + ' &mdash; ' + st.focus
        + ' &mdash; ' + (st.scenario||'').slice(0,90).replace(/</g,'&lt;') + '&hellip;</summary>'
        + '<div style="white-space:pre-wrap;margin-top:10px;line-height:1.65;">' + (st.walkthrough||'').replace(/</g,'&lt;') + '</div></details>';
    }).join('');
  }catch(e){ document.getElementById('shelf').textContent = 'Could not load saved studies.'; }
}
loadShelf();
async function loadCases(){
  try{
    const r = await fetch('/api/admin/cases'); const d = await r.json();
    const el = document.getElementById('cases');
    if (!d.cases || !d.cases.length){ el.textContent = 'No session cases recorded yet.'; return; }
    el.innerHTML = d.cases.map(function(c){
      const convo = c.turns.map(function(t){ return (t.r==='user'?'PERSON: ':'INNERLIGHT: ') + t.t; }).join('\n');
      return '<details style="margin-bottom:10px;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">'
        + '<summary style="cursor:pointer;font-weight:700;color:#1d4ed8;">' + c.label + ' &mdash; ' + c.when
        + (c.tags.length ? ' &mdash; <span style="color:#b45309;">' + c.tags.join(', ') + '</span>' : '') + '</summary>'
        + '<div style="white-space:pre-wrap;margin-top:10px;line-height:1.6;">' + convo.replace(/</g,'&lt;') + '</div>'
        + '<button style="margin-top:10px;padding:8px 18px;" onclick="studyCase(this)" data-convo="' + convo.replace(/"/g,'&quot;').replace(/</g,'&lt;') + '">Study this case</button>'
        + '</details>';
    }).join('');
  }catch(e){ document.getElementById('cases').textContent = 'Could not load cases.'; }
}
function studyCase(btn){
  document.getElementById('scenario').value = 'De-identified real session (names/numbers removed): ' + btn.dataset.convo.slice(0, 2500);
  window.scrollTo({top:0, behavior:'smooth'});
}
loadCases();
</script>
<script>
async function runStudy(){
  const out = document.getElementById('out'), wait = document.getElementById('wait');
  out.style.display='none'; wait.style.display='block';
  try{
    const r = await fetch('/api/admin/study',{method:'POST',headers:{'Content-Type':'application/json'},
      body: JSON.stringify({scenario: document.getElementById('scenario').value,
                            focus: document.getElementById('focus').value})});
    const raw = await r.text();
    let d = null;
    try { d = JSON.parse(raw); } catch(parseErr){
      out.textContent = 'The study took longer than the server was allowed to think, so the answer was cut off mid-work. '
        + 'Press "Study it" once more — a retry usually lands. If this keeps happening, the server patience setting needs raising (Render > Settings > Start Command).';
      wait.style.display='none'; out.style.display='block'; return;
    }
    out.textContent = (d && d.text) ? d.text : 'No response.';
  }catch(e){ out.textContent = 'Could not reach the study engine. Check the connection and press "Study it" again.'; }
  wait.style.display='none'; out.style.display='block';
  if (typeof loadShelf==='function') loadShelf();
}
</script></body></html>""")


# ===========================================================================
# CASE RECORDER — every session becomes a de-identified case for the
# Founder's Study. Scrubbing happens BEFORE anything is written: numbers,
# emails, phone numbers, and handles are masked. Cases are founder-only,
# disclosed in the privacy notes, never public, never sold.
# ===========================================================================
_CASES_FILE = os.environ.get("CASES_FILE", _DATA_DIR + "/innerlight_cases.json")
_CASES_LOCK = threading.Lock()
_SCRUB_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email removed]"),
    (re.compile(r"(\+?\d[\d\-\s().]{6,}\d)"), "[number removed]"),
    (re.compile(r"@\w{2,}"), "[handle removed]"),
    (re.compile(r"\b\d{3,}\b"), "[number removed]"),
]
_LEGAL_WORDS = ("court", "lawyer", "attorney", "evict", "landlord", "custody", "police",
                "arrest", "charge", "warrant", "lawsuit", "sue", "fraud", "insurance",
                "immigration", "visa", "deport")
_MEDICAL_WORDS = ("medication", "meds", "prescription", "doctor", "psychiatr", "diagnos",
                  "hospital", "therapy", "therapist", "pharmacy", "insulin", "dose", "pain")

def _scrub(text):
    out = str(text or "")
    for pat, repl in _SCRUB_PATTERNS:
        out = pat.sub(repl, out)
    return out[:1200]

@app.route("/api/case/record", methods=["POST"])
def case_record():
    data = request.get_json(silent=True) or {}
    sid = str(data.get("sid", ""))[:12] or "anon"
    role = "user" if data.get("role") == "user" else "innerlight"
    text = _scrub(data.get("text", ""))
    if not text.strip():
        return jsonify({"status": "ok"})
    low = text.lower()
    tags = set()
    if any(w in low for w in _LEGAL_WORDS): tags.add("legal")
    if any(w in low for w in _MEDICAL_WORDS): tags.add("medical")
    with _CASES_LOCK:
        try:
            with open(_CASES_FILE) as f:
                cases = json.load(f)
        except Exception:
            cases = {}
        c = cases.setdefault(sid, {"when": time.strftime("%Y-%m-%d %H:%M"),
                                   "turns": [], "tags": []})
        c["turns"] = (c["turns"] + [{"r": role, "t": text}])[-40:]
        c["tags"] = sorted(set(c["tags"]) | tags)
        if len(cases) > 200:
            for k in sorted(cases.keys(), key=lambda k: cases[k].get("when", ""))[:len(cases)-200]:
                cases.pop(k, None)
        try:
            with open(_CASES_FILE, "w") as f:
                json.dump(cases, f)
        except Exception:
            pass
    return jsonify({"status": "ok"})

@app.route("/api/admin/cases")
def admin_cases():
    if not session.get("founder_ok"):
        return jsonify({"status": "locked"}), 403
    try:
        with open(_CASES_FILE) as f:
            cases = json.load(f)
    except Exception:
        cases = {}
    listing = []
    for i, (sid, c) in enumerate(sorted(cases.items(), key=lambda x: x[1].get("when", ""), reverse=True), 1):
        listing.append({"label": f"Case {i}", "when": c.get("when", ""), "tags": c.get("tags", []),
                        "turns": c.get("turns", [])})
    return jsonify({"status": "ok", "cases": listing})


# ===========================================================================
# LIVE CONNECT — temporary founder-responder model.
# When a person asks to connect, this: (1) creates a private video room,
# (2) fires an instant push alert to the founder's phone (ntfy), and
# (3) logs the request for the operations room. The person is told honestly
# that an InnerLight responder meets them first while the professional
# network grows. Set NTFY_TOPIC on Render to your secret topic name.
# ===========================================================================
_CONNECT_FILE = os.environ.get("CONNECT_FILE", _DATA_DIR + "/innerlight_connects.json")
_CONNECT_LOCK = threading.Lock()

@app.route("/api/connect/request", methods=["POST"])
def connect_request():
    data = request.get_json(silent=True) or {}
    kind = "legal" if data.get("kind") == "legal" else "care"
    pro = _scrub(str(data.get("pro", ""))[:60])
    summary = _scrub(str(data.get("summary", ""))[:1500])
    rid = secrets.token_urlsafe(6)
    room = "InnerLight-" + rid
    fast = ("#config.prejoinPageEnabled=false"
            "&config.prejoinConfig.enabled=false"
            "&config.disableDeepLinking=true")
    room_url = "https://meet.jit.si/" + room
    guest_url = room_url + fast + '&userInfo.displayName=%22Guest%22'
    responder_url = room_url + fast + '&userInfo.displayName=%22InnerLight%20Responder%22'
    entry = {"id": rid, "when": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind,
             "pro": pro or "unspecified", "room": room_url,
             "guest_room": guest_url, "responder_room": responder_url,
             "summary": summary}
    with _CONNECT_LOCK:
        try:
            with open(_CONNECT_FILE) as f:
                log = json.load(f)
        except Exception:
            log = []
        log = (log + [entry])[-100:]
        try:
            with open(_CONNECT_FILE, "w") as f:
                json.dump(log, f)
        except Exception:
            pass
    # Ring the founder's phone via ntfy push
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    notified = False
    if topic:
        try:
            import urllib.request as _ur
            preview = (summary[:300] + "…") if summary else "No summary text was provided."
            base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
            brief_link = (base + "/responder/" + rid) if base else responder_url
            req = _ur.Request(
                "https://ntfy.sh/" + topic,
                data=(f"Wants: {pro or 'help'} ({kind})\n\n"
                      f"WHY: {preview}\n\n"
                      f"JOIN VIDEO NOW (one tap, no login): {responder_url}\n\n"
                      f"Full briefing: {brief_link}").encode("utf-8"),
                headers={"Title": f"InnerLight: {pro or 'someone'} is waiting",
                         "Priority": "urgent", "Tags": "rotating_light",
                         "Click": responder_url})
            _ur.urlopen(req, timeout=8)
            notified = True
        except Exception:
            notified = False
    return jsonify({"status": "ok", "room": guest_url, "notified": notified})

@app.route("/responder/<rid>")
def responder_brief(rid):
    if not session.get("founder_ok"):
        return render_template_string(LOGIN_PAGE), 200
    try:
        with open(_CONNECT_FILE) as f:
            log = json.load(f)
    except Exception:
        log = []
    match = next((c for c in log if c.get("id") == rid), None)
    if not match:
        return "<h2 style='font-family:Arial;padding:40px;'>That request was not found.</h2>", 404
    summary_html = (match.get("summary") or "No summary was captured for this request.").replace("<", "&lt;").replace("\n", "<br>")
    return render_template_string("""
<!doctype html><html><head><title>Responder Briefing — InnerLight</title>
<meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{font-family:Arial;margin:0;padding:22px;color:#1e293b;
      background:linear-gradient(160deg,#0f2447,#14346b 40%,#f8fafc 40.5%);}
 h1{color:#fff;font-size:20px;margin:0 0 4px;} .sub{color:#c7d6f5;font-size:13px;margin-bottom:18px;}
 .card{background:#fff;border-radius:14px;padding:20px;box-shadow:0 10px 30px rgba(15,36,71,0.18);margin-bottom:16px;}
 .badge{display:inline-block;background:#eef2ff;color:#4338ca;border:1px solid #c7d2fe;border-radius:999px;
        padding:5px 14px;font-size:13px;font-weight:700;margin-bottom:6px;}
 .why{font-size:16px;line-height:1.7;color:#1e293b;white-space:pre-wrap;}
 .join{display:inline-block;margin-top:8px;background:linear-gradient(90deg,#1d4ed8,#7c3aed);color:#fff;
       padding:16px 34px;border-radius:999px;font-size:17px;font-weight:700;text-decoration:none;}
 .meta{font-size:12.5px;color:#64748b;margin-top:10px;}
</style></head><body>
<h1>Someone is waiting for you</h1>
<div class="sub">Read this first — then join. They should never have to explain from zero.</div>
<div class="card">
 <div class="badge">Wants: {{ pro }} &middot; {{ kind }} &middot; {{ when }}</div>
 <h2 style="font-size:15px;color:#1e3a8a;margin:10px 0 6px;">Why they reached out</h2>
 <div class="why">{{ summary_html|safe }}</div>
</div>
<div class="card" style="text-align:center;">
 <a class="join" href="{{ room }}" target="_blank">Join the video now</a>
 <div class="meta">Private room for this person only. You already know why they're here.</div>
</div>
</body></html>""", pro=match.get("pro"), kind=match.get("kind"), when=match.get("when"),
    room=match.get("responder_room", match.get("room")), summary_html=summary_html)

@app.route("/api/admin/connects")
def admin_connects():
    if not session.get("founder_ok"):
        return jsonify({"status": "locked"}), 403
    try:
        with open(_CONNECT_FILE) as f:
            log = json.load(f)
    except Exception:
        log = []
    return jsonify({"status": "ok", "connects": list(reversed(log))})
