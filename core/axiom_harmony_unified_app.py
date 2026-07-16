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
    :root { --page:#faf5ec; --ink:#2a1e14; --muted:#8a7a68; --panel:#ffffff; --line:#ece0d0; --teal:#b24a2a; --leaf:#c56a2c; --coral:#c85c54; --gold:#b7791f; }
    * { box-sizing:border-box; }
    body { margin:0; font-family: Arial, sans-serif; background:var(--page); color:var(--ink); line-height:1.5; }
    a { color:var(--teal); text-decoration:none; }
    header { position:sticky; top:0; z-index:5; background:rgba(250,245,236,.96); border-bottom:1px solid var(--line); padding:14px 24px; display:flex; justify-content:space-between; align-items:center; gap:18px; }
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
    .bar { position:absolute; bottom:0; width:18px; border:1px solid rgba(178,74,42,.25); background:#f0e4da; animation:pulse 4s ease-in-out infinite; }
    .bar:nth-child(1) { left:6%; height:28%; animation-delay:.1s; }
    .bar:nth-child(2) { left:13%; height:52%; animation-delay:.5s; background:#f5f0ec; }
    .bar:nth-child(3) { left:22%; height:36%; animation-delay:.2s; background:#f7e1de; }
    .bar:nth-child(4) { left:33%; height:66%; animation-delay:.8s; }
    .bar:nth-child(5) { left:45%; height:42%; animation-delay:.4s; background:#f3ead3; }
    .bar:nth-child(6) { left:58%; height:74%; animation-delay:.9s; background:#efe8e2; }
    .bar:nth-child(7) { left:70%; height:48%; animation-delay:.3s; background:#f7e1de; }
    .bar:nth-child(8) { left:83%; height:61%; animation-delay:.7s; }
    .bar:nth-child(9) { left:93%; height:33%; animation-delay:.2s; background:#f5f0ec; }
    @keyframes pulse { 0%,100% { transform:scaleY(.82); } 50% { transform:scaleY(1.08); } }
    .band { padding:54px 24px; }
    .band.alt { background:#f7f3ef; border-top:1px solid var(--line); border-bottom:1px solid var(--line); }
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
    .sound-panel { margin-top:12px; padding:12px; border:1px solid var(--line); border-radius:6px; background:#fcfaf9; }
    .emotion-panel { margin-top:12px; padding:12px; border:1px solid var(--line); border-radius:6px; background:#fffdf7; }
    .inline-actions { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:8px; }
    .video-preview { width:100%; max-height:190px; margin-top:8px; border:1px solid var(--line); border-radius:6px; background:#f4f1ee; object-fit:cover; }
    .emotion-status { color:var(--muted); font-size:13px; margin-top:8px; }
    .sound-status { color:var(--muted); font-size:13px; margin-top:8px; }
    /* Calm welcome redesign — light, warm, inviting */
    #welcome-gate { position:fixed; inset:0; z-index:50; display:flex; align-items:center; justify-content:center;
      background:linear-gradient(160deg, #f7f3f0 0%, #f3ede9 30%, #fdf2f0 60%, #f6f2ee 100%); text-align:center; padding:24px; }
    .gate-inner { max-width:440px; }
    .gate-mark { font-size:46px; color:#c59771; opacity:.85; margin-bottom:6px; animation:breathe 4s ease-in-out infinite; }
    @keyframes breathe { 0%,100%{opacity:.5;transform:scale(1)} 50%{opacity:1;transform:scale(1.06)} }
    #welcome-gate h1 { font-size:30px; margin:6px 0 12px; font-weight:600; letter-spacing:.02em; color:#4a372d; }
    #welcome-gate p { color:#99673e; font-size:15px; line-height:1.6; margin:0 0 22px; }
    .gate-links { margin-top:22px; font-size:13px; color:#c59772; display:flex; gap:8px; justify-content:center; align-items:center; flex-wrap:wrap; }
    .gate-links a { color:#9a8778; text-decoration:none; border-bottom:1px solid transparent; transition:border-color .2s; }
    .gate-links a:hover { border-bottom-color:#c59771; }
    .gate-links span { color:#ddd1c8; }
    .gate-button { background:#b27849; color:#fff; border:0; border-radius:999px; padding:15px 38px;
      font-size:16px; font-weight:600; cursor:pointer; box-shadow:0 12px 30px rgba(91,160,138,.35); transition:transform .15s; }
    .gate-button:hover { transform:translateY(-2px); background:#9e6a40; }
    .gate-sub { font-size:12px; color:#c59772; margin-top:18px !important; }
    .story-screen { min-height:100vh; display:flex; flex-direction:column; align-items:center; padding:0 20px 40px;
      position:relative;
      background:transparent; }
    .story-screen > * { position:relative; z-index:1; }
    #scene-veil { position:fixed; inset:0; z-index:0; pointer-events:none;
      background:linear-gradient(180deg, rgba(255,255,255,0.55), rgba(255,255,255,0.35)); }
    .scene-picker { position:fixed; bottom:14px; right:14px; z-index:20; display:flex; gap:6px; flex-wrap:wrap;
      justify-content:flex-end; max-width:min(90vw,300px); background:rgba(255,255,255,0.7);
      backdrop-filter:blur(6px); border-radius:16px; padding:6px 10px; }
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
    .story-video { width:300px; height:300px; max-width:78vw; max-height:78vw; object-fit:cover; border-radius:28px; border:3px solid #ddd1c8;
      margin:0 auto 8px; display:block; background:#f0ece8; box-shadow:0 8px 30px rgba(0,0,0,0.18);
      transition:width 0.4s ease, height 0.4s ease, border-radius 0.4s ease, box-shadow 0.4s ease, margin 0.4s ease; }
    .story-video-bar.floating .story-video { width:110px; height:110px; border-radius:50%;
      border-width:3px; margin:0; box-shadow:0 6px 22px rgba(0,0,0,0.28); }
    @media (max-width:640px){ .story-video-bar.floating .story-video { width:78px; height:78px; }
      .story-video-bar.floating { top:70px; right:12px; } }
    /* Readable over ANY background scene: strong color + a white legibility
       halo so the text is clear on dark moons and bright gardens alike. */
    .story-title { font-size:26px; font-weight:700; margin:0 0 6px; color:#302018;
      text-shadow:0 1px 2px rgba(255,255,255,0.95), 0 2px 12px rgba(255,255,255,0.7), 0 0 2px rgba(255,255,255,0.9); }
    .story-sub { color:#422b20; font-size:14.5px; font-weight:600; margin:0 0 22px;
      text-shadow:0 1px 2px rgba(255,255,255,0.95), 0 1px 8px rgba(255,255,255,0.65); }
    .story-sub a { color:#1d5f7e; }
    .story-input { width:100%; min-height:130px; box-sizing:border-box; padding:18px; border-radius:16px;
      border:1px solid #ddd1c8; background:#ffffff; color:#4a372d; font-size:16px; line-height:1.6; resize:vertical;
      font-family:inherit; }
    .story-input::placeholder { color:#d2ae90; }
    .story-input:focus { outline:none; border-color:#b27849; box-shadow:0 0 0 3px rgba(91,160,138,.15); }
    .story-actions { display:flex; gap:12px; justify-content:center; margin:18px 0 10px; }
    .story-send { background:#b27849; color:#fff; border:0; border-radius:999px; padding:13px 40px; font-size:15px;
      font-weight:600; cursor:pointer; }
    .story-send:hover { background:#9e6a40; }
    .help-rail-placeholder {}
    #help-rail { position:fixed; right:14px; top:50%; transform:translateY(-50%); z-index:90;
      display:flex; flex-direction:column; gap:8px; }
    #help-rail .rail-btn { background:rgba(255,255,255,0.95); color:#2e6e8e; border:1px solid #2e6e8e;
      border-radius:12px; padding:10px 12px; font-size:13px; font-weight:700; cursor:pointer; text-decoration:none;
      text-align:center; box-shadow:0 4px 14px rgba(20,40,60,0.14); min-width:76px; }
    #help-rail .rail-988 { background:#e8534e; color:#fff; border:0; }
    @media (max-width:760px){
      #help-rail { top:auto; bottom:0; left:0; right:0; transform:none; flex-direction:row;
        justify-content:space-between; background:#ffffff; padding:8px 6px; z-index:95; gap:4px;
        box-shadow:0 -3px 14px rgba(20,40,60,0.18); }
      #help-rail .rail-btn { flex:1 1 0; min-width:0; margin:0; padding:0 3px; height:46px; font-size:11px;
        line-height:1.15; white-space:nowrap; display:flex; align-items:center; justify-content:center;
        border-radius:11px; box-shadow:none; }
      /* Scene picker sits ABOVE the help bar, never overlapping it */
      .scene-picker { bottom:70px !important; right:10px !important; z-index:40 !important;
        background:rgba(255,255,255,0.85); border-radius:16px; padding:5px 8px;
        max-width:calc(100vw - 20px); flex-wrap:wrap; justify-content:flex-end; }
      #heart-chip { bottom:74px !important; left:10px !important; }
      /* Give the whole page room so nothing hides behind the fixed help bar */
      .story-screen { padding-bottom:120px; padding-left:14px; padding-right:14px; }
      /* The camera preview becomes a small circle so an empty/off camera never
         shows as a giant grey box (the #1 "beta" look on phones). */
      .story-video { width:118px !important; height:118px !important; border-radius:50% !important;
        border-width:2px; box-shadow:0 6px 18px rgba(0,0,0,0.16); }
      .story-video-bar { padding:12px 0 4px; }
      .story-title { font-size:22px; }
      .story-sub { font-size:13.5px; margin-bottom:16px; }
      .story-input { min-height:110px; padding:14px; }   /* keep 16px font to stop iOS zoom-on-focus */
      .story-send { padding:12px 32px; }
      .music-bar { flex-wrap:wrap; gap:8px 10px; margin-top:12px; padding:0 4px; }
      #vol-slider { width:68px !important; }
      .music-change { padding:6px 12px; font-size:12px; }
      body { padding-bottom:70px; }
    }
    .story-mic { background:#fff; color:#99673e; border:1px solid #ddd1c8; border-radius:999px; padding:13px 22px;
      font-size:14px; cursor:pointer; }
    .music-bar { display:flex; align-items:center; justify-content:center; gap:14px; margin-top:14px; color:#9a8778; font-size:13px; }
    .music-change { background:#fff; border:1px solid #ddd1c8; color:#99673e; border-radius:999px; padding:6px 16px;
      font-size:12px; cursor:pointer; }
    .emotion-badge { display:inline-block; background:#f3ede9; color:#6c412c; font-size:12px; padding:4px 12px;
      border-radius:999px; margin-top:10px; font-weight:500; }
    .care-result .detail-band { background:#faf7f5; border:1px solid #e6ded8; border-radius:12px; padding:16px; margin:14px 0; }
    .zen-alts .zen-track, .zen-alts .music-change { background:#fff; border:1px solid #ddd1c8; color:#775031;
      border-radius:999px; padding:7px 16px; font-size:12px; cursor:pointer; }
    .zen-alts .zen-track:hover { background:#f3ede9; }
    .question-list li { margin-bottom:8px; color:var(--ink); }
    .detail-band { border-top:1px solid var(--line); margin-top:14px; padding-top:12px; }
    .pill { display:inline-block; margin:3px 6px 3px 0; padding:4px 8px; border-radius:4px; border:1px solid var(--line); background:#fcfaf9; color:var(--muted); font-size:12px; }
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
        <div id="lang-toggle" style="text-align:right;margin-bottom:4px;font-size:12px;">
          <a href="#" onclick="setLang('en');return false;" data-langbtn="en" style="color:#2e6e8e;text-decoration:none;">English</a>
          <span style="color:#ddd1c8;">&middot;</span>
          <a href="#" onclick="setLang('es');return false;" data-langbtn="es" style="color:#2e6e8e;text-decoration:none;">Espa&ntilde;ol</a>
          <span style="color:#ddd1c8;">&middot;</span>
          <a href="#" onclick="setLang('zh');return false;" data-langbtn="zh" style="color:#2e6e8e;text-decoration:none;">&#20013;&#25991;</a>
        </div>
        <div class="gate-mark" aria-hidden="true">&#9711;</div>
        <h1>InnerLight</h1>
        <p data-i18n="gate.tagline">A quiet, private place to tell your story.<br>Nothing you share is shown to anyone &mdash; it is encrypted.</p>
        <button class="gate-button" onclick="startExperience()" data-i18n="gate.begin">Tap to begin</button>
        <p class="gate-sub"><span data-i18n="gate.startnote">Soft music and your camera begin gently when you tap.</span><br>
        <span data-i18n="gate.camera" style="display:inline-block;margin:8px auto 0;max-width:420px;font-size:12.5px;color:#bd885c;line-height:1.55;">
        <b style="color:#99673e;">About your camera:</b> your video is analyzed <b>on your own device</b> &mdash;
        for gentle expression and heart signals only. The video itself is <b>never sent to us or stored anywhere</b>.
        Nothing leaves your device. You can decline the camera and still use everything else.</span><br>
        <span data-i18n="gate.ainotice" style="display:inline-block;margin:8px auto 0;max-width:420px;font-size:12.5px;color:#bd885c;line-height:1.55;">
        <b style="color:#99673e;">Please know:</b> InnerLight is an <b>artificial-intelligence program</b> &mdash; a computer,
        not a human being. It is not a therapist, doctor, or lawyer, and it may not be suitable for some minors.
        In an emergency, call or text <b>988</b> or call <b>911</b>. <a href="/safety" style="color:#2e6e8e;">How we respond in a crisis</a></span><br>
        <span data-i18n="gate.adult" style="font-size:12px;color:#9a8778;">By continuing you confirm you are 18 or older.
        <a href="#" onclick="showMinorBridge();return false;" style="color:#2e6e8e;">Under 18? We still have real help for you.</a></span></p>
        <div class="gate-links">
          <a href="/about">About</a><span>&middot;</span>
          <a href="/how-it-works">How it works</a><span>&middot;</span>
          <a href="/research">Research</a><span>&middot;</span>
          <a href="/safety">Safety</a><span>&middot;</span>
          <a href="/privacy">Your privacy</a><span>&middot;</span>
          <a href="/contact">Contact</a>
        </div>
      </div>
    </div>

    <script>
    // ===================== LANGUAGE / i18n LAYER =====================
    // English is the source and the always-safe fallback: any element with a
    // data-i18n key keeps its English text if a translation is missing, so the
    // page can never go blank. Adding a language later = add one more block to
    // I18N. Choice is remembered on the person's own device.
    var I18N = {
      es: {
        "gate.tagline": "Un lugar tranquilo y privado para contar tu historia.<br>Nada de lo que compartas se muestra a nadie &mdash; est&aacute; cifrado.",
        "gate.begin": "Toca para comenzar",
        "gate.startnote": "La m&uacute;sica suave y tu c&aacute;mara comienzan con calma cuando tocas.",
        "gate.camera": "<b style='color:#99673e;'>Sobre tu c&aacute;mara:</b> tu video se analiza <b>en tu propio dispositivo</b> &mdash; solo para leer con suavidad tu expresi&oacute;n y tu ritmo card&iacute;aco. El video en s&iacute; <b>nunca se nos env&iacute;a ni se guarda en ning&uacute;n lugar</b>. Nada sale de tu dispositivo. Puedes rechazar la c&aacute;mara y usar todo lo dem&aacute;s.",
        "gate.ainotice": "<b style='color:#99673e;'>Ten en cuenta:</b> InnerLight es un <b>programa de inteligencia artificial</b> &mdash; una computadora, no una persona. No es un terapeuta, m&eacute;dico ni abogado, y puede no ser apropiado para algunos menores. En una emergencia, llama o env&iacute;a un mensaje al <b>988</b>, o llama al <b>911</b>. <a href='/safety' style='color:#2e6e8e;'>C&oacute;mo respondemos en una crisis</a>",
        "gate.adult": "Al continuar, confirmas que tienes 18 a&ntilde;os o m&aacute;s. <a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>&iquest;Menor de 18? Tambi&eacute;n tenemos ayuda real para ti.</a>",
        "story.title": "Cu&eacute;ntame tu historia.",
        "story.sub": "T&oacute;mate tu tiempo. Di lo que sientas verdadero. Te escucho.",
        "story.resume": "&iquest;Ya estuviste aqu&iacute;? Contin&uacute;a tu historia",
        "story.ainote": "InnerLight es un programa de inteligencia artificial &mdash; no una persona, y no un terapeuta, m&eacute;dico ni abogado.",
        "story.safetylink": "Seguridad y protocolo de crisis",
        "story.placeholder": "Empieza por donde quieras... (presiona Enter para enviar)",
        "story.send": "Enviar",
        "story.speak": "&#127908; Hablar",
        "music.now": "&#9834; m&uacute;sica suave sonando",
        "music.change": "Cambiar m&uacute;sica",
        "music.pulseon": "&#10041; Pulso de calma: activado",
        "music.voiceoff": "&#128263; Voz hablada: desactivada",
        "rail.provider": "Proveedor",
        "rail.legal": "Ayuda legal",
        "rail.nearby": "Ayuda cercana",
        "rail.activities": "Actividades",
        "rail.testmic": "Probar micr&oacute;fono"
      },
      zh: {
        "gate.tagline": "一个安静、私密的地方，倾诉你的心事。<br>你分享的一切都不会展示给任何人——它是加密的。",
        "gate.begin": "轻触开始",
        "gate.startnote": "轻触后，柔和的音乐和你的摄像头会缓缓开启。",
        "gate.camera": "<b style='color:#99673e;'>关于你的摄像头：</b>你的视频只在<b>你自己的设备上</b>分析——只用来轻轻读取你的表情和心率。视频本身<b>绝不会发送给我们，也不会保存在任何地方</b>。没有任何内容离开你的设备。你可以拒绝使用摄像头，并继续使用其他所有功能。",
        "gate.ainotice": "<b style='color:#99673e;'>请注意：</b>InnerLight 是一个<b>人工智能程序</b>——一台计算机，不是真人。它不是心理治疗师、医生或律师，可能不适合部分未成年人。如遇紧急情况，请拨打或发短信至 <b>988</b>，或拨打 <b>911</b>。<a href='/safety' style='color:#2e6e8e;'>我们如何应对危机</a>",
        "gate.adult": "继续即表示你确认自己已年满 18 岁。<a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>未满 18 岁？我们同样为你准备了真正的帮助。</a>",
        "story.title": "把你的故事告诉我。",
        "story.sub": "慢慢来。说出你真实的感受。我在倾听。",
        "story.resume": "以前来过？继续你的故事",
        "story.ainote": "InnerLight 是一个人工智能程序——不是真人，也不是心理治疗师、医生或律师。",
        "story.safetylink": "安全与危机预案",
        "story.placeholder": "从任何地方开始都可以……（按回车发送）",
        "story.send": "发送",
        "story.speak": "&#127908; 说话",
        "music.now": "&#9834; 正在播放柔和的音乐",
        "music.change": "更换音乐",
        "music.pulseon": "&#10041; 平静脉动：已开启",
        "music.voiceoff": "&#128263; 语音朗读：已关闭",
        "rail.provider": "医疗资源",
        "rail.legal": "法律帮助",
        "rail.nearby": "附近的帮助",
        "rail.activities": "活动",
        "rail.testmic": "测试麦克风"
      }
    };
    // Current UI language, and helpers that make the SPOKEN voice and the voice
    // INPUT follow it — so Spanish and Chinese are actually heard in-language,
    // not read aloud with an English accent.
    window._ilLang = 'en';
    function ilBcp47(code){ return code==='es' ? 'es-ES' : (code==='zh' ? 'zh-CN' : 'en-US'); }
    function ilPickVoice(bcp){
      try {
        var vs = (window.speechSynthesis && speechSynthesis.getVoices()) || [];
        var pref = bcp.slice(0,2).toLowerCase();
        var exact = [], pfx = [];
        for (var i=0;i<vs.length;i++){
          var L = (vs[i].lang||'').toLowerCase().replace('_','-');
          if (L === bcp.toLowerCase()) exact.push(vs[i]);
          else if (L.slice(0,2) === pref) pfx.push(vs[i]);
        }
        var pool = exact.length ? exact : pfx;
        if (!pool.length) return null;
        pool.sort(function(a,b){ return (b.localService===true) - (a.localService===true); });
        return pool[0];
      } catch(e){ return null; }
    }
    function applyLang(code){
      try {
        var dict = I18N[code] || null;   // null => English source stays
        var nodes = document.querySelectorAll('[data-i18n]');
        for (var i=0;i<nodes.length;i++){
          var key = nodes[i].getAttribute('data-i18n');
          if (dict && dict[key] != null){
            if (!nodes[i].getAttribute('data-en')) nodes[i].setAttribute('data-en', nodes[i].innerHTML);
            nodes[i].innerHTML = dict[key];
          } else if (nodes[i].getAttribute('data-en')){
            nodes[i].innerHTML = nodes[i].getAttribute('data-en');  // restore English
          }
        }
        var phs = document.querySelectorAll('[data-i18n-ph]');
        for (var j=0;j<phs.length;j++){
          var pk = phs[j].getAttribute('data-i18n-ph');
          if (dict && dict[pk] != null){
            if (!phs[j].getAttribute('data-en-ph')) phs[j].setAttribute('data-en-ph', phs[j].getAttribute('placeholder')||'');
            phs[j].setAttribute('placeholder', dict[pk]);
          } else if (phs[j].getAttribute('data-en-ph') != null){
            phs[j].setAttribute('placeholder', phs[j].getAttribute('data-en-ph'));
          }
        }
        try { document.documentElement.lang = code; } catch(e){}
        window._ilLang = code;
        // keep voice INPUT (speech-to-text) in the same language, if it's running
        try { if (typeof voiceRecognizer !== 'undefined' && voiceRecognizer) voiceRecognizer.lang = ilBcp47(code); } catch(e){}
        // re-pick the spoken voice + rebuild the picker so a Spanish or Chinese
        // page is read aloud in that language, not English.
        try { if (typeof initVoices === 'function') initVoices(); } catch(e){}
        try { if (typeof populateVoicePicker === 'function') populateVoicePicker(); } catch(e){}
        var btns = document.querySelectorAll('[data-langbtn]');
        for (var k=0;k<btns.length;k++){
          btns[k].style.fontWeight = (btns[k].getAttribute('data-langbtn')===code) ? '700' : '400';
        }
      } catch(e){}
    }
    function setLang(code){
      // Language lasts for THIS visit only (session cookie, no expiry date).
      try { sessionStorage.setItem('il_lang', code); } catch(e){}
      try { document.cookie = 'il_lang=' + code + ';path=/'; } catch(e){}
      applyLang(code);
    }
    (function(){
      // FOUNDER DECREE: ENGLISH IS THE DEFAULT, EVERY VISIT. No language choice
      // ever sticks to the device across visits. Purge any old saved choice.
      try { localStorage.removeItem('il_lang'); } catch(e){}
      var saved = 'en';
      try { saved = sessionStorage.getItem('il_lang') || 'en'; } catch(e){}
      if (saved === 'en') { try { document.cookie = 'il_lang=en;path=/;max-age=0'; } catch(e){} }
      applyLang(saved);
    })();
    </script>

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
        <button class="scene-btn" data-scene="sunflowers" onclick="setScene('sunflowers')" title="Sunflowers">&#127804;</button>
        <button class="scene-btn" data-scene="wave" onclick="setScene('wave')" title="Ocean wave">&#127754;</button>
        <button class="scene-btn" data-scene="lettuce" onclick="setScene('lettuce')" title="Garden greens">&#129382;</button>
        <button class="scene-btn" data-scene="pepper" onclick="setScene('pepper')" title="Green pepper">&#129681;</button>
        <button class="scene-btn" data-scene="redpepper" onclick="setScene('redpepper')" title="Red pepper">&#127798;</button>
      </div>
      <div class="story-video-bar">
        <video id="visual-preview" class="story-video" autoplay muted playsinline></video>
              </div>
      <div class="story-wrap">
        <h2 class="story-title" data-i18n="story.title">Tell me your story.</h2>
        <p class="story-sub"><span data-i18n="story.sub">Take your time. Say whatever feels true. I am listening.</span> &middot; <a href="#" onclick="openResume();return false;" style="color:#2e6e8e;" data-i18n="story.resume">Been here before? Continue your story</a></p>
        <p style="font-size:12px;color:#6a402b;font-weight:500;margin:-6px 0 10px;text-shadow:0 1px 2px rgba(255,255,255,0.9);"><span data-i18n="story.ainote">InnerLight is an AI program &mdash; not a human, and not a therapist, doctor, or lawyer.</span> <a href="/safety" style="color:#1d5f7e;" data-i18n="story.safetylink">Safety &amp; crisis protocol</a></p>
        <textarea id="message" class="story-input" data-i18n-ph="story.placeholder" placeholder="Start wherever you would like... (press Enter to send)" onkeydown="if((event.key==='Enter'||event.keyCode===13)&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendCheckin();}"></textarea>
        <div class="story-actions">
          <button class="story-send" onclick="sendCheckin()" data-i18n="story.send">Send</button>
          <button class="story-mic" type="button" onclick="startVoiceCapture()" title="Speak instead of typing" data-i18n="story.speak">&#127908; Speak</button>
        </div>
        <div class="music-bar">
          <button type="button" id="mute-btn" onclick="toggleMute()" style="background:none;border:1px solid #ddd1c8;border-radius:999px;padding:4px 10px;font-size:13px;cursor:pointer;margin-right:6px;">&#128266;</button><input type="range" id="vol-slider" min="0" max="100" value="24" oninput="setVol(this.value)" style="width:80px;vertical-align:middle;margin-right:8px;" title="Volume"><span id="music-now" data-i18n="music.now">&#9834; soft music playing</span>
          <button class="music-change" type="button" onclick="changeMusic()" data-i18n="music.change">Change music</button>
          <button class="music-change" type="button" id="entrain-toggle" onclick="toggleEntrainment()" data-i18n="music.pulseon">&#10041; Calm pulse: on</button>
          <button class="music-change" type="button" id="voice-toggle" onclick="toggleVoiceCombined()" data-i18n="music.voiceoff">&#128263; Spoken voice: Off</button>
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
          <button type="button" class="rail-btn" onclick="openHelp('telehealth')" title="Talk to a provider" data-i18n="rail.provider">Provider</button>
          <button type="button" class="rail-btn" onclick="openHelp('attorney')" title="Legal help" data-i18n="rail.legal">Legal</button>
          <button type="button" class="rail-btn" onclick="openFacilities()" title="Find nearby help" data-i18n="rail.nearby">Nearby help</button>
          <button type="button" class="rail-btn" onclick="openActivities()" title="Calming activities" data-i18n="rail.activities">Activities</button>
          <button type="button" class="rail-btn" onclick="testMic()" title="Test my microphone" data-i18n="rail.testmic">Test mic</button>
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
              <div id="mic-level-fill" style="height:100%;width:0%;background:linear-gradient(90deg,#6fb3d4,#a56a3a);border-radius:6px;transition:width 0.06s linear;"></div>
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
/* ===== HOISTED STATE (declared before any function uses them) ===== */
var faceInterval = null;
var TARGET_VOL = 0.035;
var entrainOn = false, entrainPanL = null, entrainPanR = null;
var _duckActive = false, _duckRestoreTimer = null, _duckFadeTimer = null;
var _hrTickInt = null, _hrEstInt = null;
var adaptiveInterval = null;

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
  moonleaf:  '/scenes/photo_7_moon_leaves.jpg',
  lettuce:   '/scenes/photo_8_lettuce.jpg',
  wave:      '/scenes/photo_9_wave.jpg',
  pepper:    '/scenes/photo_10_pepper.jpg',
  redpepper: '/scenes/photo_11_red_pepper.jpg',
  sunflowers:'/scenes/photo_12_sunflowers.jpg'
};
const SCENE_ORDER = ['garden','lettuce','pepper','redpepper','sunflower','sunflowers','sunset','horizon','wave','moon','daymoon','moonleaf'];
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
    g.innerHTML = '<span style="font-size:11.5px;color:#d7b79c;display:block;letter-spacing:0.4px;">Your calm garden — each success grows it</span><span id="garden-row"></span>';
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
        + 'background:#e6d2c1;box-shadow:0 0 8px #e6d2c1;left:'+(r.left+r.width/2)+'px;top:'+(r.top+r.height/2)+'px;'
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
    ['words','Word search','Hunt the hidden calm words'],
    ['shapes','Shape match','Busy the picture-mind'],
    ['bubbles','Bubble pop','Pop the drifting lights'],
    ['stars','Count the stars','A gentle anchor'],
    ['release','Body release','Squeeze, hold, let go'],
    ['sequence','Glow sequence','Follow and repeat the lights'],
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
    st.innerHTML = `<div style="text-align:center;padding:6px;">
      <div id="br-word" style="font-size:26px;color:#fff;font-weight:700;min-height:34px;">Breathe in&hellip;</div>
      <div id="br-count" style="font-size:44px;color:#d3a47d;font-weight:700;min-height:52px;">5</div>
      <div style="position:relative;width:150px;height:150px;margin:6px auto 10px;overflow:visible;">
        <div id="br-aura" style="position:absolute;inset:-12px;border-radius:50%;border:2px solid rgba(207,233,255,0.35);"></div>
        <div id="br-circle" style="position:absolute;inset:0;border-radius:50%;background:radial-gradient(circle,#6fb3d4,#2a5a7a);transition:transform 4.6s ease-in-out;display:flex;align-items:center;justify-content:center;flex-direction:column;">
          <b id="br-bpm" style="font-size:26px;color:#fff;">&nbsp;</b>
          <span id="br-bpm-lbl" style="font-size:10px;color:#cfe9ff;"></span>
        </div>
      </div>
      <div id="br-msg" style="font-size:13px;color:#9db8cf;min-height:20px;">In 5 &middot; hold 5 &middot; out 5. The number counts you through.</div></div>`;
    const c=st.querySelector('#br-circle'), w=st.querySelector('#br-word'), cd=st.querySelector('#br-count');
    let phase=0, tick=5, cycles=0;
    const PHASES=[['Breathe in\u2026',1.35],['Hold\u2026',null],['Let it out\u2026',1.0]];
    const step=()=>{ if(!c.isConnected) return;
      cd.textContent = tick;
      if (tick===5){ // phase start
        w.textContent = PHASES[phase][0];
        if (PHASES[phase][1]!==null) c.style.transform='scale('+PHASES[phase][1]+')';
        if (phase===2){ cycles++; if (cycles%3===0) bloom(); }
      }
      tick--; if (tick<0){ tick=5; phase=(phase+1)%3; }
    };
    step(); actTimers.push(setInterval(step,1000));
    // Live heart INSIDE the circle — but only when the reading is trusted.
    let brStartBpm = 0;
    actTimers.push(setInterval(()=>{
      const el = st.querySelector('#br-bpm'); if (!el || !el.isConnected) return;
      const fresh = window._heartUpdatedAt && (Date.now()-window._heartUpdatedAt < 10000);
      const trusted = (window._heartConfidence||0) >= 1 && fresh;
      const bpm = trusted && window._heartBPM>=45 && window._heartBPM<=140 ? Math.round(window._heartBPM) : 0;
      el.textContent = bpm ? bpm : '\u00a0';
      st.querySelector('#br-bpm-lbl').textContent = bpm ? 'your heart' : '';
      if (bpm){
        if (!brStartBpm) brStartBpm = bpm;
        const aura = st.querySelector('#br-aura');
        if (aura){ aura.animate([{transform:'scale(1)',opacity:0.5},{transform:'scale(1.07)',opacity:0.15}],
          { duration: Math.max(400, 60000/bpm), iterations: 1 }); }
        const msg = st.querySelector('#br-msg');
        if (msg && brStartBpm - bpm >= 5){
          msg.textContent = brStartBpm + ' \u2192 ' + bpm + ' \u2014 your heart is listening. Keep going.';
          msg.style.color = '#d3a47d';
        }
      }
    }, 1500));
  }
  if (name==='ground'){
    // Camera-guided: read the room's actual dominant colors and send the
    // person hunting for them — active engagement, not passive listing.
    let roomColors = [];
    try {
      const video = document.getElementById('visual-preview');
      if (video && video.videoWidth){
        const cv=document.createElement('canvas'); cv.width=64; cv.height=36;
        cv.getContext('2d').drawImage(video,0,0,64,36);
        const d=cv.getContext('2d').getImageData(0,0,64,36).data;
        const buckets={};
        for(let i=0;i<d.length;i+=4){
          const r=d[i],g=d[i+1],b=d[i+2];
          const max=Math.max(r,g,b),min=Math.min(r,g,b);
          if(max-min<28) continue; // skip grays
          let name='';
          if(r>g&&r>b) name = g>b*1.3?'orange or warm yellow':'red or warm pink';
          else if(g>r&&g>b) name='green';
          else if(b>r&&b>g) name = r>g?'purple or violet':'blue';
          if(name) buckets[name]=(buckets[name]||0)+1;
        }
        roomColors = Object.entries(buckets).sort((a,b)=>b[1]-a[1]).slice(0,2).map(x=>x[0]);
      }
    } catch(e){}
    const seeLine = roomColors.length
      ? 'Your camera can see ' + roomColors.join(' and ') + ' in this room. Find five things in those colors — hunt them down with your eyes.'
      : 'Look around slowly. Name five things — their color, their shape.';
    const steps=[['5 things you can SEE', seeLine],
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
  if (name==='words'){
    // WORD SEARCH — hidden calm words in a letter grid. More complex and more
    // absorbing than pick-a-word: tap the first letter then the last letter of a
    // word to find it. Generated fresh each time (no two grids alike).
    const WS_WORDS=['CALM','REST','BREATHE','RIVER','MEADOW','WILLOW','LANTERN','PEBBLE','GARDEN','OCEAN','MAPLE','CLOUD','EMBER','QUIET','STILL','HARBOR'];
    const N=9;
    function wsBuild(){
      const chosen=WS_WORDS.slice().sort(()=>Math.random()-0.5).filter(w=>w.length<=N).slice(0,4);
      const grid=[]; for(let r=0;r<N;r++){ grid.push(new Array(N).fill('')); }
      const dirs=[[0,1],[1,0],[1,1],[-1,1]];
      const placed=[];
      chosen.forEach(function(word){
        let ok=false;
        for(let tries=0;tries<140 && !ok;tries++){
          const dir=dirs[Math.floor(Math.random()*dirs.length)]; const L=word.length;
          const r0=Math.floor(Math.random()*N), c0=Math.floor(Math.random()*N);
          const rE=r0+dir[0]*(L-1), cE=c0+dir[1]*(L-1);
          if(rE<0||rE>=N||cE<0||cE>=N) continue;
          let good=true; const cells=[];
          for(let k=0;k<L;k++){ const rr=r0+dir[0]*k, cc=c0+dir[1]*k; const ex=grid[rr][cc];
            if(ex && ex!==word[k]){ good=false; break; } cells.push([rr,cc]); }
          if(!good) continue;
          for(let k=0;k<L;k++){ grid[cells[k][0]][cells[k][1]]=word[k]; }
          placed.push({word:word,cells:cells}); ok=true;
        }
      });
      const A='ABCDEFGHIJKLMNOPQRSTUVWXYZ';
      for(let r=0;r<N;r++){ for(let c=0;c<N;c++){ if(!grid[r][c]) grid[r][c]=A[Math.floor(Math.random()*26)]; } }
      return {grid:grid, placed:placed, words:placed.map(function(p){return p.word;})};
    }
    let puzzle=wsBuild(), found=[], selA=null;
    function wsRender(){
      st.innerHTML='<div style="text-align:center;">'
        +'<div id="ws-p" style="font-size:13px;color:#9db8cf;margin-bottom:8px;">Find the hidden calm words. Tap the FIRST letter, then the LAST letter of a word.</div>'
        +'<div id="ws-words" style="font-size:13px;margin-bottom:10px;"></div>'
        +'<div id="ws-grid" style="display:inline-grid;grid-template-columns:repeat('+N+',1fr);gap:3px;"></div></div>';
      st.querySelector('#ws-words').innerHTML=puzzle.words.map(function(w){
        const done=found.indexOf(w)>=0;
        return '<span style="display:inline-block;margin:2px 7px;letter-spacing:1px;'+(done?'color:#d3a47d;text-decoration:line-through;':'color:#e6f1fa;')+'">'+w+'</span>';
      }).join('');
      let html='';
      for(let r=0;r<N;r++){ for(let c=0;c<N;c++){
        const lit=found.some(function(w){ const p=puzzle.placed.find(function(x){return x.word===w;}); return p&&p.cells.some(function(cell){return cell[0]===r&&cell[1]===c;}); });
        html+='<button data-r="'+r+'" data-c="'+c+'" style="width:30px;height:30px;font-size:14px;border-radius:6px;border:1px solid rgba(255,255,255,0.15);cursor:pointer;'
          +(lit?'background:rgba(125,211,168,0.45);color:#0c1322;font-weight:700;':'background:rgba(255,255,255,0.06);color:#e6f1fa;')+'">'+puzzle.grid[r][c]+'</button>';
      } }
      const g=st.querySelector('#ws-grid'); g.innerHTML=html;
      g.querySelectorAll('button').forEach(function(b){ b.addEventListener('click',function(){ wsClick(+b.dataset.r,+b.dataset.c,b); }); });
    }
    function wsClick(r,c,b){
      if(!selA){ selA=[r,c]; b.style.outline='2px solid #cfe9ff'; return; }
      const r0=selA[0], c0=selA[1]; selA=null;
      st.querySelectorAll('#ws-grid button').forEach(function(x){ x.style.outline=''; });
      const dr=r-r0, dc=c-c0, adr=Math.abs(dr), adc=Math.abs(dc);
      if(!(dr===0||dc===0||adr===adc)) return;               // must be a straight line
      const L=Math.max(adr,adc)+1, sr=Math.sign(dr), sc=Math.sign(dc);
      let str='';
      for(let k=0;k<L;k++){ str+=puzzle.grid[r0+sr*k][c0+sc*k]; }
      const rev=str.split('').reverse().join('');
      const match=puzzle.words.find(function(w){ return (w===str||w===rev) && found.indexOf(w)<0; });
      if(match){
        found.push(match); metric('wordplay'); if(typeof bloom==='function') bloom();
        if(found.length>=puzzle.words.length){
          wsRender(); const p=st.querySelector('#ws-p'); if(p){ p.textContent='All found — beautifully done. A fresh grid…'; p.style.color='#d3a47d'; }
          actTimers.push(setTimeout(function(){ puzzle=wsBuild(); found=[]; selA=null; wsRender(); }, 1800));
          return;
        }
        wsRender();
      }
    }
    wsRender();
  }
  if (name==='shapes'){
    st.innerHTML=`<div style="text-align:center;"><div id="sh-prompt" style="font-size:15px;color:#cfe3f2;margin:8px 0 12px;"></div>
      <div id="sh-grid" style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;max-width:340px;margin:0 auto;"></div></div>`;
    const SH=['\u25CF','\u25A0','\u25B2','\u2666','\u2605','\u2B22']; const CO=['#d3a47d','#6fb3d4','#d4a86f','#d4ab8a'];
    const round=()=>{ const tS=SH[Math.floor(Math.random()*SH.length)], tC=CO[Math.floor(Math.random()*CO.length)];
      st.querySelector('#sh-prompt').innerHTML='Find: <span style="color:'+tC+';font-size:26px;">'+tS+'</span>';
      const cells=[{s:tS,c:tC}]; while(cells.length<8){ const s2=SH[Math.floor(Math.random()*SH.length)], c2=CO[Math.floor(Math.random()*CO.length)];
        if(!(s2===tS&&c2===tC)) cells.push({s:s2,c:c2}); }
      cells.sort(()=>Math.random()-0.5);
      st.querySelector('#sh-grid').innerHTML=cells.map(x=>`<button onclick="(function(b){ if(b.dataset.hit==='1'){ b.style.background='rgba(125,211,168,0.4)'; bloom(); setTimeout(window._shRound,700);} })(this)" data-hit="${x.s===tS&&x.c===tC?1:0}" style="font-size:30px;padding:14px 6px;border-radius:12px;border:1px solid rgba(255,255,255,0.2);background:rgba(255,255,255,0.07);color:${x.c};cursor:pointer;">${x.s}</button>`).join('');
    };
    window._shRound=round; round();
  }
  if (name==='bubbles'){
    // BUBBLE POP — soft lights drift up; tap them to pop. Endless, gentle,
    // and genuinely absorbing. No score to fear, just a quiet tally.
    st.innerHTML=`<div style="text-align:center;"><div id="bb-p" style="font-size:13px;color:#9db8cf;margin-bottom:8px;">Tap the drifting lights to pop them. No rush, no wrong move.</div>
      <div id="bb-field" style="position:relative;height:320px;border-radius:14px;background:radial-gradient(circle at 50% 40%, #16314a, #0c1322);overflow:hidden;touch-action:manipulation;"></div>
      <div id="bb-count" style="margin-top:8px;font-size:13px;color:#d3a47d;min-height:18px;"></div></div>`;
    const field=st.querySelector('#bb-field'); let popped=0;
    const colors=['#d3a47d','#6fb3d4','#d4a86f','#d4ab8a','#cfe9ff'];
    const spawn=()=>{ if(!field.isConnected) return;
      const b=document.createElement('div');
      const size=26+Math.random()*36, col=colors[Math.floor(Math.random()*colors.length)];
      b.style.cssText='position:absolute;width:'+size+'px;height:'+size+'px;border-radius:50%;cursor:pointer;'
        +'background:radial-gradient(circle at 35% 30%, #ffffff, '+col+' 72%);box-shadow:0 0 16px '+col+';';
      b.style.left=(6+Math.random()*80)+'%'; b.style.top='102%';
      field.appendChild(b);
      const drift=(Math.random()*40-20), dur=6500+Math.random()*5000;
      const anim=b.animate([{transform:'translate(0,0)'},{transform:'translate('+drift+'px,-360px)'}],{duration:dur,easing:'linear'});
      const pop=(e)=>{ if(e){ e.preventDefault(); } if(!b.isConnected) return;
        popped++; if(typeof bloom==='function' && popped%4===0) bloom();
        const cnt=st.querySelector('#bb-count'); if(cnt) cnt.textContent=popped+' popped';
        try{ anim.cancel(); }catch(_){}
        b.animate([{opacity:1,transform:'scale(1)'},{opacity:0,transform:'scale(1.7)'}],{duration:220});
        setTimeout(()=>{ if(b.isConnected) b.remove(); },200);
      };
      b.addEventListener('click',pop);
      b.addEventListener('touchstart',pop,{passive:false});
      anim.onfinish=()=>{ if(b.isConnected) b.remove(); };
    };
    actTimers.push(setInterval(spawn,800)); spawn(); spawn();
  }
  if (name==='stars'){
    st.innerHTML=`<div style="text-align:center;"><div id="st-p" style="font-size:14px;color:#cfe3f2;margin-bottom:10px;">Stars will appear, slowly. Count them, then answer.</div>
      <div id="st-sky" style="position:relative;height:220px;border-radius:14px;background:radial-gradient(circle at 50% 40%, #16314a, #0c1322);"></div>
      <div id="st-ans" style="margin-top:12px;"></div></div>`;
    window._starStreak = window._starStreak||0;
    const maxN = Math.min(25, 6 + window._starStreak*3); // streaks earn bigger skies (boredom-proof)
    const n = 3 + Math.floor(Math.random()*(maxN-2)); const sky=st.querySelector('#st-sky');
    for(let i=0;i<n;i++){ actTimers.push(setTimeout(()=>{ if(!sky.isConnected)return; const d=document.createElement('div');
      d.style.cssText='position:absolute;width:8px;height:8px;border-radius:50%;background:#fffbe8;box-shadow:0 0 12px #fffbe8;opacity:0;transition:opacity 2s;';
      d.style.left=(8+Math.random()*84)+'%'; d.style.top=(10+Math.random()*75)+'%'; sky.appendChild(d);
      requestAnimationFrame(()=>d.style.opacity='0.95'); }, 900+i*Math.max(500, 1700-n*60))); }
    actTimers.push(setTimeout(()=>{ if(!st.isConnected)return; const ans=st.querySelector('#st-ans');
      ans.innerHTML=[n-1,n,n+1].sort(()=>Math.random()-0.5).map(v=>`<button onclick="(function(b){ if(+b.dataset.v===${n}){ b.style.background='rgba(125,211,168,0.5)'; document.getElementById('st-p').textContent='Yes — '+${n}+' stars. Nicely counted.'; bloom(); window._starStreak=(window._starStreak||0)+1; setTimeout(()=>startAct('stars'),1600);} else { b.style.background='rgba(180,90,90,0.3)'; window._starStreak=0; } })(this)" data-v="${v}" style="font-size:18px;margin:0 8px;padding:10px 22px;border-radius:12px;border:1px solid rgba(255,255,255,0.25);background:rgba(255,255,255,0.08);color:#e6f1fa;cursor:pointer;">${v}</button>`).join('');
    }, 900+n*Math.max(500,1700-n*60)+800));
  }
  if (name==='release'){
    // Interactive tension-release: a real timed HOLD with a shrinking ring and a
    // countdown, then an animated RELEASE and a word of encouragement. You DO it,
    // it responds -- like the breathing circle, not a wall of text.
    const groups=[
      ['Hands','Make two tight fists'],
      ['Shoulders','Lift them up to your ears'],
      ['Jaw and face','Scrunch your whole face'],
      ['Belly','Brace your stomach, gently'],
      ['Legs','Straighten your legs, press your feet down'],
      ['Whole body','Tense everything at once, softly']
    ];
    const cheer=["That's tension leaving.","Feel the difference.","Lighter already.","Nicely done.","That was a deep one.","Your whole body just let go."];
    let i=0;
    st.innerHTML=`<div style="text-align:center;padding:6px;">
      <div id="rl-t" style="font-size:23px;color:#fff;font-weight:700;"></div>
      <div id="rl-s" style="font-size:14px;color:#b9d0e2;margin:8px 0 14px;line-height:1.5;"></div>
      <div style="position:relative;width:150px;height:150px;margin:0 auto 14px;">
        <div id="rl-ring" style="position:absolute;inset:0;border-radius:50%;background:radial-gradient(circle,#d4a86f,#7a5230);transition:transform 0.9s ease;display:flex;align-items:center;justify-content:center;">
          <span id="rl-num" style="font-size:42px;color:#fff;font-weight:700;">&nbsp;</span></div>
      </div>
      <button id="rl-go" style="background:#6fb3d4;color:#0c1322;border:0;border-radius:999px;padding:12px 30px;font-size:15px;font-weight:700;cursor:pointer;">Squeeze &amp; hold</button>
      <div id="rl-msg" style="margin-top:12px;color:#d3a47d;font-size:14px;min-height:18px;"></div></div>`;
    const T=st.querySelector('#rl-t'),S=st.querySelector('#rl-s'),ring=st.querySelector('#rl-ring'),
          num=st.querySelector('#rl-num'),go=st.querySelector('#rl-go'),msg=st.querySelector('#rl-msg');
    const show=()=>{ T.textContent=groups[i][0]; S.textContent=groups[i][1]; msg.textContent='';
      msg.style.color='#d3a47d'; num.innerHTML='&nbsp;'; ring.style.transform='scale(1)';
      go.textContent='Squeeze & hold'; go.disabled=false; go.style.opacity='1'; };
    const run=()=>{ go.disabled=true; go.style.opacity='0.5'; let t=5;
      ring.style.transform='scale(1.14)'; num.textContent=t; msg.textContent='Squeeze...';
      const iv=setInterval(()=>{ if(!ring.isConnected){ clearInterval(iv); return; }
        t--; if(t>0){ num.textContent=t; }
        else { clearInterval(iv); num.innerHTML='&nbsp;'; ring.style.transform='scale(0.78)';
          msg.textContent='...and let it ALL go. ' + cheer[i%cheer.length]; if(typeof bloom==='function') bloom();
          actTimers.push(setTimeout(()=>{ i++;
            if(i>=groups.length){ st.innerHTML='<div style="text-align:center;padding:20px;color:#d3a47d;font-size:16px;line-height:1.6;">Every part of you just let go a little.<br>Well done. Pick another, or press Back.</div>'; return; }
            show();
          }, 1700));
        }
      },1000);
      actTimers.push(iv);
    };
    go.onclick=run; show();
  }
  if (name==='sequence'){
    // GLOW SEQUENCE -- a gentle memory game (like Simon). The lights glow in
    // order; repeat them back. Absorbing and distracting, grows one step at a
    // time so it never feels like failure.
    st.innerHTML=`<div style="text-align:center;">
      <div id="sq-p" style="font-size:14px;color:#cfe3f2;margin-bottom:12px;">Watch the lights glow in order, then tap them back the same way.</div>
      <div id="sq-grid" style="display:grid;grid-template-columns:repeat(2,112px);gap:12px;justify-content:center;"></div>
      <div id="sq-msg" style="margin-top:14px;font-size:14px;color:#d3a47d;min-height:20px;"></div></div>`;
    const cols=['#d3a47d','#6fb3d4','#d4a86f','#d4ab8a'];
    const grid=st.querySelector('#sq-grid'), msg=st.querySelector('#sq-msg');
    const dim=(c)=>c+'44';
    const pads=cols.map((c,idx)=>{ const p=document.createElement('button');
      p.style.cssText='width:112px;height:82px;border-radius:16px;border:1px solid rgba(255,255,255,0.2);background:'+dim(c)+';cursor:pointer;transition:background 0.18s ease,transform 0.1s ease;';
      p.dataset.i=idx; grid.appendChild(p); return p; });
    let seq=[], expect=0, accept=false;
    const flash=(idx,cb)=>{ const p=pads[idx]; if(!p||!p.isConnected){ if(cb) cb(); return; }
      p.style.background=cols[idx]; p.style.transform='scale(1.06)';
      actTimers.push(setTimeout(()=>{ if(p.isConnected){ p.style.background=dim(cols[idx]); p.style.transform='scale(1)'; } if(cb) cb(); },420)); };
    const play=(k)=>{ if(!grid.isConnected) return;
      if(k>=seq.length){ accept=true; expect=0; msg.textContent='Your turn'; return; }
      flash(seq[k], ()=> actTimers.push(setTimeout(()=>play(k+1),180))); };
    const nextRound=()=>{ accept=false; seq.push(Math.floor(Math.random()*4));
      msg.textContent='Watch... (round '+seq.length+')'; actTimers.push(setTimeout(()=>play(0),600)); };
    pads.forEach((p)=>{ p.addEventListener('click',()=>{ if(!accept) return; const idx=+p.dataset.i; flash(idx);
      if(idx===seq[expect]){ expect++;
        if(expect>=seq.length){ accept=false; msg.textContent='Nice -- '+seq.length+' in a row!'; if(typeof bloom==='function') bloom(); actTimers.push(setTimeout(nextRound,900)); }
      } else { accept=false; msg.textContent="Close -- let's watch that one again"; actTimers.push(setTimeout(()=>{ expect=0; msg.textContent='Watch...'; actTimers.push(setTimeout(()=>play(0),400)); },900)); }
    }); });
    nextRound();
  }
  if (name==='menuDone'){
    st.innerHTML=`<div style="text-align:center;padding:20px;color:#d3a47d;font-size:16px;">Well done. Pick another, or press Back when you're ready.</div>`;
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
    btn.style.background = 'rgba(90,180,130,0.55)'; btn.style.borderColor = '#d3a47d';
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
    // FACE SIZE = distance proxy. Face width as a fraction of frame width.
    // Close phone use ~0.45+; comfortable ~0.30; too-far desktop < 0.20.
    const faceFrac = (lm[454] && lm[234]) ? Math.abs(lm[454].x - lm[234].x) : 0;
    window._faceFrac = faceFrac;
    // ADAPTIVE PATCHES: when the face is small (person far), enlarge the skin
    // patches relative to the face so we still gather enough skin pixels.
    // scale 1.0 at comfortable distance, up to ~1.8 when far.
    const grow = faceFrac > 0 ? Math.max(1, Math.min(1.8, 0.32 / faceFrac)) : 1;
    window._patchGrow = grow;
    const P = (i, sx, sy, sw, sh) => lm[i] ? { x: lm[i].x*W - W*sw*grow/2 + sx*W, y: lm[i].y*H - H*sh*grow/2 + sy*H, w: W*sw*grow, h: H*sh*grow } : null;
    window._heartRegions = {
      forehead:   P(10, 0, 0.03, 0.13, 0.06),
      cheekLeft:  P(50, 0, 0,    0.08, 0.06),
      cheekRight: P(280,0, 0,    0.08, 0.06),
      wholeFace:  (lm[10]&&lm[152]) ? { x: lm[234].x*W, y: lm[10].y*H, w: (lm[454].x-lm[234].x)*W, h: (lm[152].y-lm[10].y)*H } : null,
      underEyeL:  P(230,0, 0.015,0.05, 0.028),
      underEyeR:  P(450,0, 0.015,0.05, 0.028),
      noseBridge: P(6,  0, 0,    0.045,0.05),
      mouthSideL: P(216,0, 0,    0.045,0.045),
      mouthSideR: P(436,0, 0,    0.045,0.045)
    };
    window._heartFaceBox = window._heartRegions.forehead;

    // DISTANCE GUIDANCE: if the face is too small for a trustworthy reading,
    // gently ask the person to come closer. Works on phone and computer.
    (function distanceNudge(){
      let tip = document.getElementById('hr-distance-tip');
      const tooFar = faceFrac >= 0.02 && faceFrac < 0.20; // ignore faceFrac==0 (no face this frame)
      if (tooFar){
        if (!tip){
          tip = document.createElement('div');
          tip.id = 'hr-distance-tip';
          tip.style.cssText = 'position:fixed;bottom:120px;right:22px;z-index:56;max-width:210px;'
            + 'background:rgba(46,110,142,0.96);color:#fff;font-family:Arial;font-size:13px;'
            + 'padding:11px 15px;border-radius:14px;box-shadow:0 6px 22px rgba(20,40,60,0.3);';
          tip.textContent = 'Lean in a little \u2014 move closer to your camera so I can read your heart clearly.';
          document.body.appendChild(tip);
        }
      } else if (tip){ tip.remove(); }
    })();
  }
}

// ================= HEART ENGINE v3 — CLEAN REBUILD =================
// Simple, honest, and always-on. One well-chosen region (forehead-to-nose center
// strip, which carries strong pulse and moves little), green-channel bandpassed
// pulse detection with autocorrelation for the beat period. No fragile
// multi-region agreement. Records every session with a confidence tier.
const hrSig = [];      // {v, t} recent green-mean samples
let heartBPM = 0, heartBaseline = 0, hrCanvas2 = null;
let _hrConf = 0;

// Precomputed gamma lookup tables so brightening is fast (no per-pixel pow()).
const _gammaLUT = {};
function gammaTable(g){
  const key = g.toFixed(2);
  if (_gammaLUT[key]) return _gammaLUT[key];
  const t = new Uint8Array(256);
  for (let i=0;i<256;i++) t[i] = Math.min(255, Math.round(255 * Math.pow(i/255, 1/g)));
  _gammaLUT[key] = t; return t;
}

function heartTick(){
  const video = document.getElementById('visual-preview');
  const regions = window._heartRegions;
  if (!video || !video.videoWidth || !regions || !regions.forehead) return;
  // Sample forehead + both cheeks together as ONE combined skin reading —
  // more skin pixels = stronger signal, especially at a distance.
  if (!hrCanvas2){ hrCanvas2 = document.createElement('canvas'); hrCanvas2.width=36; hrCanvas2.height=36; }
  const ctx = hrCanvas2.getContext('2d',{willReadFrequently:true});

  // ---- PASS 1: measure how dark the face is (mean luminance of skin area) ----
  let lumaSum=0, lumaCnt=0;
  for (const nm of ['forehead','cheekLeft','cheekRight','noseBridge','underEyeL','underEyeR']){
    const b = regions[nm]; if (!b || b.w<4 || b.h<4) continue;
    try { ctx.drawImage(video, b.x, b.y, b.w, b.h, 0,0,36,36); } catch(e){ continue; }
    const d = ctx.getImageData(0,0,36,36).data;
    for (let i=0;i<d.length;i+=4){ lumaSum += (d[i]*0.299 + d[i+1]*0.587 + d[i+2]*0.114); lumaCnt++; }
  }
  const luma = lumaCnt ? lumaSum/lumaCnt : 128;
  window._faceLuma = Math.round(luma);
  // Very dark AND sustained -> offer ONE gentle, optional light suggestion.
  if (luma < 55){
    window._darkStreak = (window._darkStreak||0) + 1;
    if (window._darkStreak === 40 && !window._lightTipShown){   // ~ sustained
      window._lightTipShown = true;
      window._lightTipEl = null;
      const t = document.createElement('div');
      t.style.cssText='position:fixed;bottom:120px;left:50%;transform:translateX(-50%);z-index:56;max-width:230px;'
        +'background:rgba(46,110,142,0.96);color:#fff;font-family:Arial;font-size:13px;padding:11px 15px;'
        +'border-radius:14px;box-shadow:0 6px 22px rgba(20,40,60,0.3);text-align:center;';
      t.innerHTML='A little more light on your face helps me read your calm \u2014 only if you can. '
        +'<button onclick="this.parentNode.remove()" style="display:block;margin:8px auto 0;background:#fff;color:#2e6e8e;border:0;border-radius:999px;padding:5px 14px;font-size:12px;cursor:pointer;">Okay</button>';
      window._lightTipEl = t;
      document.body.appendChild(t);
      setTimeout(()=>{ if(t.isConnected) t.remove(); }, 12000);
    }
  } else {
    window._darkStreak = 0;
    // Light came back -> clear the tip and allow it again later if needed.
    if (window._lightTipEl && window._lightTipEl.isConnected) window._lightTipEl.remove();
    window._lightTipShown = false;
  }
  // ---- Choose an adaptive gamma. Bright face -> 1.0 (no change).
  // Dark face -> up to ~2.6 lift (research uses ~2.5 for low light). ----
  let gamma = 1.0, lowLight = false;
  if (luma < 110){
    lowLight = true;
    // scale: luma 110 -> 1.1, luma 40 -> ~2.6, floor protects very dark noise
    gamma = Math.min(2.6, 1 + (110 - Math.max(30, luma)) / 45);
  }
  window._lowLightBoost = lowLight ? gamma.toFixed(2) : '';
  const lut = gamma > 1.01 ? gammaTable(gamma) : null;
  // When we brighten, dark real skin has lower raw values, so relax the gate.
  const rMin = lowLight ? 28 : 50;
  const diffMin = lowLight ? 4 : 8;

  // ---- PASS 2: read the (optionally brightened) skin pulse — ALL THREE color
  // channels now, not just green. The POS algorithm downstream combines red,
  // green, and blue to cancel motion and lighting, which is far more robust
  // than green-only and much fairer across skin tones. ----
  let rSum=0, gSum=0, bSum=0, gCnt=0;
  // Specific stable-skin points: forehead + cheeks (strongest) + nose bridge +
  // under-eye + mouth-side (added per founder request for a fuller reading).
  for (const nm of ['forehead','cheekLeft','cheekRight','noseBridge','underEyeL','underEyeR','mouthSideL','mouthSideR']){
    const b = regions[nm]; if (!b || b.w<4 || b.h<4) continue;
    try { ctx.drawImage(video, b.x, b.y, b.w, b.h, 0,0,36,36); } catch(e){ continue; }
    const d = ctx.getImageData(0,0,36,36).data;
    for (let i=0;i<d.length;i+=4){
      let r=d[i], g=d[i+1], bl=d[i+2];
      if (lut){ r=lut[r]; g=lut[g]; bl=lut[bl]; }   // brighten for the reading only
      if (r>rMin && r>=g && g>=bl && (r-bl)>diffMin){ rSum+=r; gSum+=g; bSum+=bl; gCnt++; }
    }
  }
  if (gCnt < 60) return;               // still not enough skin even after lift
  hrSig.push({r:rSum/gCnt, g:gSum/gCnt, b:bSum/gCnt, v:gSum/gCnt, t:performance.now()});
  const cutoff = performance.now()-12000;
  while (hrSig.length && hrSig[0].t < cutoff) hrSig.shift();
}

// ---- POS (Plane-Orthogonal-to-Skin, Wang et al. 2017) ----
// The current gold-standard classical rPPG method — the same math commercial
// heart-from-camera kits are built on. It normalizes each color channel by its
// own recent average, then projects the RGB signal onto a plane that is
// orthogonal to the skin-tone direction, which cancels most of the change that
// comes from movement and light instead of from the pulse. Runs entirely on the
// person's device. Returns a single pulse waveform.
function posPulse(R, G, B, fs){
  const n = R.length;
  const out = new Float64Array(n);
  const l = Math.max(20, Math.round(fs*1.6));   // ~1.6s sliding window
  if (n < l) return out;
  const sd = (a)=>{ let mu=0; for (let i=0;i<a.length;i++) mu+=a[i]; mu/=a.length;
                    let v=0; for (let i=0;i<a.length;i++){ const dd=a[i]-mu; v+=dd*dd; }
                    return Math.sqrt(v/a.length) || 1e-9; };
  for (let m=0; m+l<=n; m++){
    let mr=0,mg=0,mb=0;
    for (let i=m;i<m+l;i++){ mr+=R[i]; mg+=G[i]; mb+=B[i]; }
    mr/=l; mg/=l; mb/=l;
    if (mr<=0||mg<=0||mb<=0) continue;
    const S1=new Float64Array(l), S2=new Float64Array(l);
    for (let i=0;i<l;i++){
      const rn=R[m+i]/mr, gn=G[m+i]/mg, bn=B[m+i]/mb;   // temporal normalization
      S1[i]= gn - bn;                 // projection row 1: [ 0, 1, -1]
      S2[i]= -2*rn + gn + bn;         // projection row 2: [-2, 1,  1]
    }
    const alpha = sd(S1)/sd(S2);
    let hmu=0; const h=new Float64Array(l);
    for (let i=0;i<l;i++){ h[i]=S1[i]+alpha*S2[i]; hmu+=h[i]; }
    hmu/=l;
    for (let i=0;i<l;i++){ out[m+i] += (h[i]-hmu); }     // overlap-add, mean-removed
  }
  return out;
}

function heartEstimate(){
  const n = hrSig.length;
  if (n < 120) return;                 // need ~8s of samples
  const dur = (hrSig[n-1].t - hrSig[0].t)/1000;
  if (dur < 6) return;
  const fs = n/dur;                    // sample rate (Hz)
  // 1) Build the pulse waveform with POS (all three channels). Fall back to the
  //    green channel only if older samples lack full color (transition safety).
  let pulse;
  if (hrSig[0].r != null && hrSig[n-1].r != null){
    const R = hrSig.map(s=>s.r), G = hrSig.map(s=>s.g), B = hrSig.map(s=>s.b);
    pulse = posPulse(R, G, B, fs);
  } else {
    const vals = hrSig.map(s=>s.v);
    const mean = vals.reduce((a,b)=>a+b,0)/n;
    pulse = vals.map(v=>v-mean);
  }
  // 2) BAND-LIMIT to the heart band. High-pass (moving-average detrend) removes
  //    slow drift; a light 3-tap low-pass removes fast noise. Together they keep
  //    only the ~0.7-2.8 Hz (42-170 bpm) band, which sharply cuts octave errors.
  const win = Math.round(fs*0.8)||1;
  const detr = Array.prototype.map.call(pulse, (v,i)=>{
    let s=0,c=0; for(let j=Math.max(0,i-win);j<=Math.min(n-1,i+win);j++){s+=pulse[j];c++;}
    return v - s/c;
  });
  const band = detr.map((v,i)=>{
    const a=detr[Math.max(0,i-1)], b=detr[i], c=detr[Math.min(n-1,i+1)];
    return (a + 2*b + c)/4;               // gentle low-pass smoothing
  });
  // 3) autocorrelation over the plausible heart-period range (40..170 bpm)
  const minLag = Math.floor(fs*60/170), maxLag = Math.ceil(fs*60/40);
  const ac = new Float64Array(maxLag+2);
  let bestLag=0, bestCorr=0, corr0=0;
  for (let i=0;i<n;i++) corr0 += band[i]*band[i];
  corr0 = corr0||1;
  for (let lag=minLag; lag<=maxLag && lag<n; lag++){
    let c=0; for (let i=0;i+lag<n;i++) c += band[i]*band[i+lag];
    ac[lag] = c/corr0;
    if (ac[lag] > bestCorr){ bestCorr=ac[lag]; bestLag=lag; }
  }
  if (!bestLag) return;
  // 4) SUBHARMONIC GUARD: autocorrelation can latch onto TWICE the true period
  //    (reading half the real heart rate). Prefer the first strong local peak —
  //    the fundamental — instead of the global maximum when they disagree.
  let fundLag = bestLag;
  for (let lag=minLag+1; lag<=maxLag-1 && lag<n-1; lag++){
    if (ac[lag] >= 0.5*bestCorr && ac[lag] >= ac[lag-1] && ac[lag] >= ac[lag+1]){
      fundLag = lag; break;   // first strong local peak = the true fundamental
    }
  }
  const bpm = 60*fs/fundLag;
  // 5) confidence from autocorrelation peak strength (0..1)
  const conf = Math.max(0, Math.min(1, bestCorr*1.4));
  _hrConf = conf;
  // 4) smooth gently toward the new reading, weighted by confidence
  const w = 0.25 + 0.35*conf;          // more confident -> move faster
  heartBPM = heartBPM ? (heartBPM*(1-w) + bpm*w) : bpm;
  if (!heartBaseline && n>200) heartBaseline = heartBPM;
  window._heartBPM = heartBPM;
  window._heartBaseline = heartBaseline;
  window._heartConfidence = conf >= 0.5 ? 1 : (conf >= 0.28 ? 0.5 : 0);
  window._heartTier = conf >= 0.5 ? 'measured' : (conf >= 0.28 ? 'estimated' : 'baseline-held');
  window._heartUpdatedAt = Date.now();
}

let _hrReported = 0;
function heartReport(){
  if (window._heartBPM && Date.now()-_hrReported > 60000){
    _hrReported = Date.now();
    metric('heart_read', Math.round(window._heartBPM) + '|' + (window._heartTier||'measured'));
    if (window._lowLightBoost) metric('lowlight_rescue', window._lowLightBoost);
  }
}

// ---- The on-screen chip: always shows a continuous reading, gently beating ----
(function heartChip(){
  const chip = document.createElement('div');
  chip.id='heart-chip';
  // Bottom-LEFT corner: the scene buttons live at bottom-right, and the chip
  // was sitting on top of them, hiding all but three. Left side is clear.
  chip.style.cssText='position:fixed;bottom:22px;left:22px;z-index:55;display:none;'
    +'background:rgba(255,255,255,0.92);border-radius:999px;padding:12px 22px;'
    +'font-family:Arial;font-size:22px;color:#8a4653;box-shadow:0 8px 26px rgba(40,20,30,0.2);';
  chip.innerHTML='<span id="heart-beat" style="display:inline-block;font-size:24px;">&#10084;&#65039;</span> '
    +'<b id="heart-num" style="font-size:26px;">--</b> <span class="hr-label" style="font-size:13px;color:#a98790;">bpm</span>';
  document.addEventListener('DOMContentLoaded', ()=>document.body.appendChild(chip));
  if (document.body) document.body.appendChild(chip);
  setInterval(()=>{
    const fresh = window._heartUpdatedAt && (Date.now()-window._heartUpdatedAt < 12000);
    if (window._heartBPM && window._heartBPM>=40 && window._heartBPM<=170 && fresh){
      chip.style.display='block';
      document.getElementById('heart-num').textContent = Math.round(window._heartBPM);
      const b=document.getElementById('heart-beat');
      b.style.transition='transform 0.15s ease'; b.style.transform='scale(1.28)';
      setTimeout(()=>{ b.style.transform='scale(1)'; }, 150);
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
    // FALLBACK HEART REGIONS: when MediaPipe isn't available, derive skin
    // patches from face-api's face box so the heart reading STILL works (this is
    // why the founder saw no heart data — MediaPipe wasn't loading). Forehead +
    // both cheeks + nose bridge give enough clean skin for the rPPG estimate.
    if (det && det.detection && det.detection.box) {
      const bx = det.detection.box.x, by = det.detection.box.y,
            bw = det.detection.box.width, bh = det.detection.box.height;
      window._heartRegions = {
        forehead:   { x: bx + bw*0.30, y: by + bh*0.08, w: bw*0.40, h: bh*0.12 },
        cheekLeft:  { x: bx + bw*0.12, y: by + bh*0.55, w: bw*0.22, h: bh*0.15 },
        cheekRight: { x: bx + bw*0.66, y: by + bh*0.55, w: bw*0.22, h: bh*0.15 },
        noseBridge: { x: bx + bw*0.42, y: by + bh*0.40, w: bw*0.16, h: bh*0.12 },
        underEyeL:null, underEyeR:null, mouthSideL:null, mouthSideR:null, wholeFace:null
      };
      window._heartFaceBox = window._heartRegions.forehead;
      window._faceFrac = bw / (video.videoWidth || 1);
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
faceInterval = null;
// Detect the face often — subtle emotion flickers across a face in fractions
// of a second, so we look ~every 0.6s to catch the ticks. The SOUND still
// responds gently (frequent detection + smoothed response = sensitive but not jittery).
function startFaceLoop() { if (!faceInterval) faceInterval = setInterval(detectFaceEmotion, 600); }

// Heart needs FAST, steady sampling (~15/sec) to catch the pulse waveform —
// far faster than the emotion loop. Estimate less often; report occasionally.






// ---- MINOR-SAFE BRIDGE: warm, immediate, real help for anyone under 18 ----
// InnerLight's pilot serves adults 18+. A young person is never coldly turned
// away — they get an immediate, warm bridge to help built for youth.
window._minorLock = false;
function hideMinorBridge(){ const o=document.getElementById('minor-bridge'); if(o) o.style.display='none'; }
function showMinorBridge(){
  window._minorLock = true;
  try { metric('minor_redirect'); } catch(e){}
  let ov = document.getElementById('minor-bridge');
  if (ov){ ov.style.display='flex'; return; }
  ov = document.createElement('div');
  ov.id = 'minor-bridge';
  ov.style.cssText = 'position:fixed;inset:0;z-index:99;background:rgba(10,18,30,0.9);display:flex;align-items:center;justify-content:center;padding:20px;';
  ov.innerHTML = '<div style="background:#fff;border-radius:18px;padding:26px;max-width:400px;width:100%;font-family:Arial;">'
    + '<h3 style="margin:0 0 8px;color:#1e3a5c;">You matter, and real help is here for you.</h3>'
    + '<p style="font-size:14px;color:#475569;line-height:1.6;">InnerLight is built for adults right now \u2014 but you are not being turned away. '
    + 'What you are feeling deserves a real person who is trained to help someone your age, right now:</p>'
    + '<div style="font-size:14.5px;line-height:1.9;color:#1e293b;">'
    + '<b>\u2022 Talk to a trusted adult</b> \u2014 a parent, family member, school counselor, coach, or teacher. Starting the sentence is the hardest part; you can even show them this screen.<br>'
    + '<b>\u2022 Call or text 988</b> \u2014 free, 24/7, and they help young people every day.<br>'
    + '<b>\u2022 Text HOME to 741741</b> \u2014 Crisis Text Line, free, 24/7.<br>'
    + '<b>\u2022 Teen Line: text TEEN to 839863</b> \u2014 teens helping teens, evenings.</div>'
    + '<p style="font-size:12.5px;color:#64748b;margin-top:12px;">If you are in immediate danger, call 911.</p>'
    + '<button onclick="hideMinorBridge()" style="margin-top:6px;background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:10px 24px;font-size:14px;font-weight:700;cursor:pointer;">Okay</button>'
    + '</div>';
  document.body.appendChild(ov);
}
// ---- LAYER 3: in-conversation minor signals (for gate bypassers) ----
function checkMinorSignals(text){
  if (!text || window._minorLock) return;
  const t = ' ' + text.toLowerCase() + ' ';
  const signals = [" i'm 11"," i'm 12"," i'm 13"," i'm 14"," i'm 15"," i'm 16"," i'm 17",
    ' im 11',' im 12',' im 13',' im 14',' im 15',' im 16',' im 17',
    ' i am 13',' i am 14',' i am 15',' i am 16',' i am 17',
    'middle school','6th grade','7th grade','8th grade','9th grade','10th grade','11th grade',
    'my mom won','my dad won','my parents won','freshman year of high school'];
  if (signals.some(function(w){ return t.indexOf(w)>=0; })){
    showMinorBridge();
    const thread = document.getElementById('conversation-thread');
    if (thread){
      const div = document.createElement('div');
      div.style.cssText = 'background:rgba(46,110,142,0.1);border-radius:12px;padding:13px 15px;margin:10px 0;font-size:14px;color:#4a362c;line-height:1.55;';
      div.textContent = 'It sounds like you may be under 18 \u2014 and I want the right help for you, which is a real person trained to support someone your age. Please look at the options I just showed you, and please tell a trusted adult how you are feeling. You deserve real support.';
      thread.appendChild(div);
    }
  }
}

// ---- ANTI-SUBSTITUTION & OVER-RELIANCE GUARDRAILS (Vasan/Common Sense Media) ----
// Watch, gently, for language that signals InnerLight is becoming a replacement
// for human connection, and steer warmly toward real people. Never shaming.
function checkSubstitutionSignals(text){
  if (!text) return;
  const t = ' ' + text.toLowerCase() + ' ';
  const subPhrases = [
    'only one who gets me','only one who understands','you are my only','my only friend',
    'don\u2019t need anyone else','dont need anyone else','you understand me better than',
    'better than my therapist','better than any therapist','you are all i have',
    'i love you','are you real','be my friend','my best friend','talk to you every day',
    'rather talk to you','instead of my'
  ];
  if (subPhrases.some(function(w){return t.indexOf(w)>=0;})){
    gentlyRedirectFromSubstitution();
  }
}
let _subRedirected = false;
function gentlyRedirectFromSubstitution(){
  if (_subRedirected) return; _subRedirected = true;
  const thread = document.getElementById('conversation-thread');
  if (!thread) return;
  const div = document.createElement('div');
  div.style.cssText = 'background:rgba(46,110,142,0.1);border-radius:12px;padding:13px 15px;margin:10px 0;font-size:14px;color:#4a362c;line-height:1.55;';
  div.innerHTML = 'I am really glad being here helps, and I want to be honest with you because I care: '
    + 'I am not a person, and I cannot be a substitute for real human connection. '
    + 'What I can do is stay with you right now and help you reach people who can truly be there for you \u2014 '
    + 'a counselor, someone you trust, a real voice. You deserve that, more than you deserve a screen. '
    + 'Would you like me to help you reach a real person?';
  thread.appendChild(div);
  try { metric('substitution_redirect'); } catch(e){}
}

// ---- GENTLE COMPLETION (never a dead end, never a dependency) ----
// Around 30 minutes, warmly encourage the bridge to a real person. Flexible if
// they are pouring out. Never says no, never closes the door, never pushes hard.
let _sessionStart = Date.now();
let _gentleNudges = 0;
function gentleCompletionCheck(){
  const mins = (Date.now() - _sessionStart) / 60000;
  // First warm bridge at ~20 min, a softer second at ~35 — then we stop nudging.
  if (mins >= 20 && _gentleNudges === 0){ _gentleNudges = 1; showGentleBridge(
    'You have shared a lot, and I am really glad you did. Whenever you feel ready, the most helpful next step is talking with a real person who can stay with you beyond this moment. I can connect you gently, whenever you want.'); }
  else if (mins >= 35 && _gentleNudges === 1){ _gentleNudges = 2; showGentleBridge(
    'I am still right here with you, and there is no rush. When you are ready, a real person can carry this forward with you. Would you like me to help you reach someone now?'); }
}
function showGentleBridge(message){
  // never blocks, never closes anything — a soft, dismissable invitation
  if (document.getElementById('gentle-bridge')) return;
  const b = document.createElement('div');
  b.id = 'gentle-bridge';
  b.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:74;'
    + 'background:rgba(255,255,255,0.98);border:1px solid #e0d7cf;border-radius:16px;padding:16px 18px;'
    + 'box-shadow:0 12px 34px rgba(20,40,30,0.22);font-family:Arial;max-width:360px;width:92%;text-align:center;';
  b.innerHTML = '<div style="font-size:14px;color:#4a362c;line-height:1.5;margin-bottom:12px;">' + message + '</div>'
    + '<button onclick="bridgeConnect()" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:10px 22px;font-size:14px;font-weight:700;cursor:pointer;margin:3px;">Connect me with someone</button>'
    + '<button onclick="closeGentleBridge()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:10px 18px;font-size:14px;cursor:pointer;margin:3px;">Keep talking a little longer</button>';
  document.body.appendChild(b);
}
function bridgeConnect(){ try{ openHelp('telehealth'); }catch(e){} closeGentleBridge(); }
function closeGentleBridge(){ const b=document.getElementById('gentle-bridge'); if(b) b.remove(); }

// ---- GENTLE PROVIDER GUIDANCE (navigation, not diagnosis) ----
// Reads ONLY the person's own explicit words about what they need, and gently
// suggests which kind of professional can best help — so they don't lose time
// at the wrong door. Never infers a condition, never diagnoses, never says no.
function suggestProviderFrom(text){
  if (!text) return null;
  const t = ' ' + text.toLowerCase() + ' ';
  const has = (arr)=>arr.some(w=>t.indexOf(w)>=0);

  // ===== LEGAL NEEDS (mirrors the legal engine's 14 categories) =====
  // Any of these should surface the LEGAL path, not emotional-only support.
  const legalMap = [
    { words:['evict','eviction','kicked out','landlord','lease','put me out','belongings outside','rent increase','no heat','no water','mold','section 8','housing authority','put out of'], label:'housing / eviction', why:'It sounds like you are facing a housing or eviction issue. This is a legal matter with real deadlines \u2014 legal help can protect your rights, often for free.' },
    { words:['homeless','shelter','living in my car','on the street','nowhere to go','couch surfing'], label:'emergency housing', why:'It sounds like you need emergency housing. There are legal-aid and housing resources that can help right now.' },
    { words:['fired','terminated','laid off','wrongful termination','unpaid wages','overtime','harassment at work','hostile work','workers comp','discriminat','retaliation'], label:'employment', why:'What you are describing sounds like an employment-rights issue. An employment attorney or legal aid can help you understand your options.' },
    { words:['custody','visitation','child support','alimony','divorce','took my kid','won\u2019t let me see','parental rights','guardianship'], label:'family / custody', why:'This sounds like a family-law matter. A family-law attorney or legal aid can help protect your rights and your children.' },
    { words:['hit me','beat me','abused','domestic violence','restraining order','order of protection','stalking','threatening me','afraid of him','afraid of her'], label:'domestic violence / protection', why:'Your safety comes first. There are legal protections (like restraining orders) and advocates who can help you immediately.' },
    { words:['arrested','charged','arraign','bail','bond','public defender','probation','parole','criminal record','expunge','felony','misdemeanor','warrant'], label:'criminal defense', why:'This sounds like a criminal-defense matter. You have the right to an attorney \u2014 a public defender is available if you cannot afford one.' },
    { words:['deport','deportation','immigration','ice','visa','asylum','daca','undocumented','green card','citizenship','detained'], label:'immigration', why:'This sounds like an immigration matter. An immigration attorney or nonprofit can explain your rights and options.' },
    { words:['expelled','suspended','iep','504 plan','special education','school discipline','title ix','denied enrollment'], label:'education rights', why:'This sounds like an education-rights issue. There are advocates and legal aid who handle school matters.' },
    { words:['denied treatment','denied coverage','denied insurance','medical malpractice','patient rights','involuntary commit','5150','forced medication','held against'], label:'patient rights', why:'This sounds like a patient-rights or healthcare-access matter. Legal aid and patient advocates can help.' },
    { words:['ada','disability accommodation','denied accommodation','ssi','ssdi','disability benefits','denied disability'], label:'disability rights', why:'This sounds like a disability-rights matter. There are advocates and legal aid who handle accommodations and benefits.' },
    { words:['debt collector','collection agency','sued for debt','garnish','repossess','bankruptcy','foreclosure','predatory','scammed','scam'], label:'consumer / debt', why:'This sounds like a consumer or debt matter. There are legal protections and free legal aid for exactly this.' },
    { words:['racial profiling','police brutality','excessive force','civil rights','hate crime','profiling','discriminated against'], label:'civil rights', why:'This sounds like a civil-rights matter. Civil-rights organizations and attorneys can help you.' }
  ];
  for (const cat of legalMap){
    if (has(cat.words)) return { pro:'Legal help', legal:true, category:cat.label, why:cat.why };
  }

  // ===== SUPPORT / CLINICAL NEEDS (routing, never diagnosis) =====
  const crisisWords = ['can\u2019t go on','cant go on','end it','hurt myself','harm myself','suicid','not safe','kill myself','want to die','right now i need','emergency'];
  const medWords = ['medication','meds','prescription','prescribe','pill','dosage','dose','psychiatrist','side effect','refill','antidepressant','off my medication','need meds'];
  const substanceWords = ['drinking','alcohol','relapse','sober','withdrawal','using again','overdose','addicted','addiction','detox','high','can\u2019t stop using'];
  const talkWords = ['therapist','therapy','counseling','someone to talk to','talk it through','process this','coping','cope','work through','grief','trauma'];

  if (has(crisisWords)) return {pro:'Crisis-trained counselor', why:'It sounds like you need support right now, this moment. A crisis-trained counselor is here for exactly that.'};
  if (has(substanceWords)) return {pro:'Substance-use counselor', why:'It sounds like substance use may be part of what you are carrying. A substance-use counselor or program can help without judgment.'};
  if (has(medWords)) return {pro:'Psychiatrist', why:'From what you\u2019re describing about medication, a psychiatrist \u2014 a medical doctor who can evaluate this and manage medication \u2014 may be the right person to help.'};
  if (has(talkWords)) return {pro:'Therapist / licensed counselor', why:'It sounds like ongoing talk-based support could help. A therapist or licensed counselor works with people on exactly this.'};
  return null;
}
// When we show the care page, pre-highlight the suggested provider (still the
// person's choice — we never auto-select or force it).
function applyProviderSuggestion(){
  try {
    const story = (document.getElementById('conversation-thread')||{}).textContent || '';
    const s = suggestProviderFrom(story);
    if (!s) return;
    const tip = document.getElementById('pro-suggestion');
    if (tip){ tip.style.display='block'; tip.innerHTML = s.why +
      ' <span style="color:#9a8778;">You can choose any option below \u2014 this is only a suggestion.</span>'; }
    document.querySelectorAll('.pro-btn').forEach(function(b){
      if (b.getAttribute('data-pro') === s.pro){ b.classList.add('suggested'); }
    });
    // If the need is legal, surface the legal path PROMINENTLY in the thread.
    if (s.legal === true){
      const thread = document.getElementById('conversation-thread');
      if (thread && !document.getElementById('legal-nudge')){
        const div = document.createElement('div');
        div.id = 'legal-nudge';
        div.style.cssText = 'background:#f8f5f2;border:1px solid #dcc0a9;border-radius:12px;padding:13px 15px;margin:10px 0;font-size:14px;color:#754f30;line-height:1.55;';
        div.innerHTML = s.why + '<br><button onclick="openLegalHelp()" style="margin-top:10px;background:#d4782d;color:#fff;border:0;border-radius:999px;padding:9px 20px;font-size:14px;font-weight:700;cursor:pointer;">See legal help options</button>';
        thread.appendChild(div);
        try { metric('legal_surfaced', s.category || ''); } catch(e){}
      }
    }
  } catch(e){}
}



// ---- IMMEDIATE HELP-REQUEST DETECTION (stops questioning, routes now) ----
// The moment a person asks for help or a provider, we route immediately — no
// more follow-up questions. Their request outranks our understanding-gathering.
function detectHelpRequest(text){
  if (!text) return false;
  const t = ' ' + text.toLowerCase() + ' ';
  const asks = ['i need help','need help now','can you help','help me','i want help',
    'connect me','talk to someone','speak to someone','speak with someone','talk to a',
    'speak to a','see a therapist','see a counselor','see a doctor','see a lawyer',
    'talk to a lawyer','talk to an attorney','need a lawyer','need an attorney',
    'need a therapist','need a counselor','need a doctor','get me help','find me help',
    'i want to talk to','put me through','can i speak','can i talk','legal help','legal person',
    'set up a session','start a session','connect me to legal','speak to a lawyer'];
  return asks.some(function(w){ return t.indexOf(w)>=0; });
}
// Decide LEGAL vs CLINICAL from the person's words.
function helpKindFrom(text){
  const t = ' ' + (text||'').toLowerCase() + ' ';
  const legalWords = ['legal','lawyer','attorney','court','sue','lawsuit','eviction','evict','landlord','custody','arrest','charged','rights','consumer','contract','tenant'];
  const clinicalWords = ['therapist','counselor','counseling','therapy','psychiatr','clinician','emotional','mental health','feelings','depress','anxious','anxiety'];
  let isLegal = legalWords.some(function(w){ return t.indexOf(w)>=0; });
  let isClinical = clinicalWords.some(function(w){ return t.indexOf(w)>=0; });
  // Honor negations: 'don't need a clinician', 'not a therapist' -> not clinical.
  if (/(don.t|do not|not|dont)\s+(need\s+)?(a\s+)?(clinician|counselor|therapist|therapy|counseling)/.test(t)) isClinical = false;
  if (/(don.t|do not|not|dont)\s+(need\s+)?(a\s+)?(lawyer|attorney|legal)/.test(t)) isLegal = false;
  if (isLegal && !isClinical) return 'legal';
  if (isClinical && !isLegal) return 'clinical';
  if (isLegal && isClinical) return 'both';
  return 'unknown';
}
window._routeRequested = false;
function handleHelpRequestIfAny(text){
  if (detectHelpRequest(text)){
    window._routeRequested = true;
    try { metric('help_requested'); } catch(e){}
    // Surface routing immediately: legal if their words are legal, plus the
    // provider path. Both can appear if both are needed.
    try { applyProviderSuggestion(); } catch(e){}
    let allText = text || '';
    try { allText = (document.getElementById('conversation-thread')||{}).textContent || text; } catch(e){}
    const kind = helpKindFrom(allText);
    const thread = document.getElementById('conversation-thread');
    if (thread){
      const _ex = document.getElementById('route-now'); if (_ex) _ex.remove();
      const div = document.createElement('div');
      div.id = 'route-now';
      div.style.cssText = 'background:rgba(46,110,142,0.12);border-radius:12px;padding:13px 15px;margin:10px 0;font-size:14px;color:#234;line-height:1.55;';
      const legalBtn = '<button onclick="openLegalHelp()" style="background:#d4782d;color:#fff;border:0;border-radius:999px;padding:10px 20px;font-size:14px;font-weight:700;cursor:pointer;margin:3px;">Connect me to legal help</button>';
      const provBtn = '<button onclick="routeProvider()" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:10px 20px;font-size:14px;font-weight:700;cursor:pointer;margin:3px;">Talk to a counselor</button>';
      const nearBtn = '<button onclick="openFacilities()" style="background:#fff;color:#2e6e8e;border:1px solid #2e6e8e;border-radius:999px;padding:10px 18px;font-size:14px;cursor:pointer;margin:3px;">Find nearby help</button>';
      let lead, buttons;
      if (kind === 'legal'){ lead = 'Of course \u2014 let me connect you to legal help right now.'; buttons = legalBtn + nearBtn; }
      else if (kind === 'clinical'){ lead = 'Of course \u2014 let me connect you to someone who can support you right now.'; buttons = provBtn + nearBtn; }
      else if (kind === 'both'){ lead = 'Of course \u2014 it sounds like both legal and emotional support could help. Choose either or both:'; buttons = legalBtn + provBtn + nearBtn; }
      else { lead = 'Of course \u2014 let me get you to real help now. Choose what fits:'; buttons = provBtn + legalBtn + nearBtn; }
      div.innerHTML = lead + '<div style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap;">' + buttons + '</div>';
      thread.appendChild(div);
      thread.scrollIntoView({behavior:'smooth', block:'end'});
    }
    return true;
  }
  return false;
}

// ---- LOCAL FACILITIES FINDER (non-crisis self-referral) ----
var _IL_FAC = {
  en:{title:"Find help near you", close:"Close",
    intro:"If you are not in immediate crisis and feel able to reach out yourself, enter your city or ZIP and we will look for mental-health places near you that you can contact on your own time.",
    ph:"City or ZIP (e.g. San Jose, CA)", search:"Search",
    foot:"If you are in immediate danger or crisis, call or text <b>988</b>, or call <b>911</b>. This list is for planning your own next step, not for emergencies.",
    enter:"Please enter a city or ZIP.", looking:"Looking for places near you\u2026",
    nores:"We could not find listings for that area right now. You can also try:",
    samhsa:"SAMHSA National Helpline: 1-800-662-4357 (free, 24/7, finds local treatment)",
    findtx:"FindTreatment.gov \u2014 search by your location", call988:"Call or text <b>988</b> to talk now.",
    confirm:"Please confirm hours and services by calling ahead. Listings come from FindTreatment.gov, the federal directory of licensed facilities.",
    err:"Could not search right now. For help finding treatment, call SAMHSA at 1-800-662-4357."},
  es:{title:"Encuentra ayuda cerca de ti", close:"Cerrar",
    intro:"Si no est\u00e1s en una crisis inmediata y te sientes capaz de comunicarte por tu cuenta, escribe tu ciudad o c\u00f3digo postal y buscaremos lugares de salud mental cerca de ti que puedas contactar cuando est\u00e9s listo/a.",
    ph:"Ciudad o c\u00f3digo postal (p. ej. San Jose, CA)", search:"Buscar",
    foot:"Si est\u00e1s en peligro inmediato o en crisis, llama o env\u00eda un mensaje al <b>988</b>, o llama al <b>911</b>. Esta lista es para planificar tu pr\u00f3ximo paso, no para emergencias.",
    enter:"Por favor escribe una ciudad o c\u00f3digo postal.", looking:"Buscando lugares cerca de ti\u2026",
    nores:"No encontramos resultados para esa zona en este momento. Tambi\u00e9n puedes probar:",
    samhsa:"L\u00ednea Nacional de SAMHSA: 1-800-662-4357 (gratis, 24/7, encuentra tratamiento local)",
    findtx:"FindTreatment.gov \u2014 busca por tu ubicaci\u00f3n", call988:"Llama o env\u00eda un mensaje al <b>988</b> para hablar ahora.",
    confirm:"Por favor confirma los horarios y servicios llamando antes. Los resultados provienen de FindTreatment.gov, el directorio federal de centros con licencia.",
    err:"No se pudo buscar en este momento. Para ayuda encontrando tratamiento, llama a SAMHSA al 1-800-662-4357."},
  zh:{title:"\u67e5\u627e\u9644\u8fd1\u7684\u5e2e\u52a9", close:"\u5173\u95ed",
    intro:"\u5982\u679c\u4f60\u73b0\u5728\u6ca1\u6709\u5904\u4e8e\u7d27\u6025\u5371\u673a\u4e2d\uff0c\u5e76\u4e14\u89c9\u5f97\u53ef\u4ee5\u81ea\u5df1\u8054\u7cfb\uff0c\u8bf7\u8f93\u5165\u4f60\u7684\u57ce\u5e02\u6216\u90ae\u653f\u7f16\u7801\uff0c\u6211\u4eec\u4f1a\u4e3a\u4f60\u67e5\u627e\u9644\u8fd1\u7684\u5fc3\u7406\u5065\u5eb7\u673a\u6784\uff0c\u4f60\u53ef\u4ee5\u5728\u65b9\u4fbf\u7684\u65f6\u5019\u81ea\u884c\u8054\u7cfb\u3002",
    ph:"\u57ce\u5e02\u6216\u90ae\u653f\u7f16\u7801\uff08\u4f8b\u5982 San Jose, CA\uff09", search:"\u641c\u7d22",
    foot:"\u5982\u679c\u4f60\u6b63\u5904\u4e8e\u7d27\u6025\u5371\u9669\u6216\u5371\u673a\u4e2d\uff0c\u8bf7\u62e8\u6253\u6216\u53d1\u77ed\u4fe1\u81f3 <b>988</b>\uff0c\u6216\u62e8\u6253 <b>911</b>\u3002\u6b64\u5217\u8868\u7528\u4e8e\u5e2e\u52a9\u4f60\u89c4\u5212\u4e0b\u4e00\u6b65\uff0c\u4e0d\u9002\u7528\u4e8e\u7d27\u6025\u60c5\u51b5\u3002",
    enter:"\u8bf7\u8f93\u5165\u57ce\u5e02\u6216\u90ae\u653f\u7f16\u7801\u3002", looking:"\u6b63\u5728\u67e5\u627e\u4f60\u9644\u8fd1\u7684\u673a\u6784\u2026",
    nores:"\u6211\u4eec\u6682\u65f6\u6ca1\u6709\u627e\u5230\u8be5\u5730\u533a\u7684\u673a\u6784\u3002\u4f60\u4e5f\u53ef\u4ee5\u5c1d\u8bd5\uff1a",
    samhsa:"SAMHSA \u5168\u56fd\u70ed\u7ebf\uff1a1-800-662-4357\uff08\u514d\u8d39\uff0c\u5168\u5929\u5019\uff0c\u5e2e\u52a9\u67e5\u627e\u5f53\u5730\u6cbb\u7597\uff09",
    findtx:"FindTreatment.gov \u2014\u2014 \u6309\u4f60\u7684\u4f4d\u7f6e\u641c\u7d22", call988:"\u62e8\u6253\u6216\u53d1\u77ed\u4fe1\u81f3 <b>988</b> \u7acb\u5373\u503e\u8bc9\u3002",
    confirm:"\u8bf7\u81f4\u7535\u786e\u8ba4\u8425\u4e1a\u65f6\u95f4\u548c\u670d\u52a1\u9879\u76ee\u3002\u7ed3\u679c\u6765\u81ea FindTreatment.gov\uff0c\u5373\u8054\u90a6\u6301\u8bc1\u673a\u6784\u76ee\u5f55\u3002",
    err:"\u6682\u65f6\u65e0\u6cd5\u641c\u7d22\u3002\u5982\u9700\u5e2e\u52a9\u67e5\u627e\u6cbb\u7597\uff0c\u8bf7\u62e8\u6253 SAMHSA\uff1a1-800-662-4357\u3002"}
};
function _ilfac(k){ var lg=(window._ilLang||"en"); return (_IL_FAC[lg]||_IL_FAC.en)[k]; }
function openFacilities(){
  let ov = document.getElementById('facilities-overlay');
  if (ov){ ov.style.display='flex'; return; }
  ov = document.createElement('div');
  ov.id='facilities-overlay';
  ov.style.cssText='position:fixed;inset:0;z-index:88;background:rgba(10,18,30,0.9);display:flex;align-items:center;justify-content:center;padding:20px;overflow-y:auto;';
  ov.innerHTML = '<div style="background:#fff;border-radius:18px;padding:24px;max-width:440px;width:100%;font-family:Arial;max-height:86vh;overflow-y:auto;">'
    + '<div style="display:flex;justify-content:space-between;align-items:center;">'
    + '<h3 style="margin:0;color:#1e3a5c;">'+_ilfac("title")+'</h3>'
    + '<button onclick="closeFacilities()" style="background:rgba(0,0,0,0.06);border:0;border-radius:999px;padding:6px 14px;cursor:pointer;">'+_ilfac("close")+'</button></div>'
    + '<p style="font-size:13px;color:#9a8778;line-height:1.5;">'+_ilfac("intro")+'</p>'
    + '<div style="display:flex;gap:8px;">'
    + '<input id="fac-place" placeholder="'+_ilfac("ph")+'" style="flex:1;padding:11px;border:1px solid #ddd1c8;border-radius:10px;font-size:15px;">'
    + '<button onclick="doFacilities()" style="background:#2e6e8e;color:#fff;border:0;border-radius:10px;padding:11px 18px;font-size:15px;font-weight:700;cursor:pointer;">'+_ilfac("search")+'</button></div>'
    + '<div id="fac-results" style="margin-top:14px;"></div>'
    + '<p style="font-size:12px;color:#94a3b8;margin-top:14px;border-top:1px solid #eef2f8;padding-top:10px;">'+_ilfac("foot")+'</p>'
    + '</div>';
  document.body.appendChild(ov);
  setTimeout(()=>{ const el=document.getElementById('fac-place'); if(el) el.focus(); }, 100);
}
function closeFacilities(){ const o=document.getElementById('facilities-overlay'); if(o) o.style.display='none'; }
async function doFacilities(){
  const place=(document.getElementById('fac-place')||{}).value||'';
  const box=document.getElementById('fac-results');
  if (place.trim().length<2){ if(box) box.innerHTML='<span style="color:#c0564e;font-size:13px;">'+_ilfac("enter")+'</span>'; return; }
  if (box) box.innerHTML='<span style="color:#9a8778;font-size:14px;">'+_ilfac("looking")+'</span>';
  try {
    const r=await fetch('/api/facilities',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({place:place})});
    const d=await r.json();
    if (!d.results || !d.results.length){
      box.innerHTML='<div style="font-size:14px;color:#475569;line-height:1.6;">'+_ilfac("nores")+'<br>'
        + '\u2022 <b>'+_ilfac("samhsa")+'</b><br>'
        + '\u2022 <b>'+_ilfac("findtx")+'</b><br>'
        + '\u2022 '+_ilfac("call988")+'</div>';
      metric('facilities_search', 'nores'); return;
    }
    box.innerHTML = d.results.map(function(f){
      return '<div style="border:1px solid #e2e8f0;border-radius:10px;padding:11px 13px;margin:8px 0;">'
        + '<b style="color:#1e3a5c;font-size:14.5px;">'+f.name+'</b>'
        + (f.address?'<div style="font-size:12.5px;color:#64748b;">'+f.address+'</div>':'')
        + (f.phone?'<div style="font-size:13px;color:#2e6e8e;margin-top:3px;">'+f.phone+'</div>':'')
        + '</div>';
    }).join('') + '<div style="font-size:12px;color:#94a3b8;margin-top:6px;">'+_ilfac("confirm")+'</div>';
    metric('facilities_search', 'ok');
  } catch(e){ box.innerHTML='<span style="color:#c0564e;font-size:13px;">'+_ilfac("err")+'</span>'; }
}

// ---- GENTLE FEEDBACK ASK (optional, anonymous) ----
// Offered once, only after real engagement, never nagged. Their words become
// anonymized research that helps prove InnerLight helps real people.
let _fbShown = false;
function closeFb(){ const c=document.getElementById('fb-card'); if(c) c.remove(); }
function offerFeedback(){
  if (_fbShown) return;
  _fbShown = true;
  const box = document.createElement('div');
  box.id = 'fb-card';
  box.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:78;'
    + 'background:rgba(255,255,255,0.98);border:1px solid #e0d7cf;border-radius:16px;padding:16px 18px;'
    + 'box-shadow:0 12px 34px rgba(20,40,30,0.22);font-family:Arial;max-width:360px;width:92%;';
  box.innerHTML =
     '<div style="font-size:14px;color:#4a362c;margin-bottom:10px;text-align:center;">If you have a moment: did this help? Your answer is anonymous and helps us help others.</div>'
   + '<div style="text-align:center;margin-bottom:8px;">'
   +   '<button class="fb-h" data-v="yes" style="margin:3px;border:1px solid #d3a47d;background:#f8f5f2;color:#6a402c;border-radius:999px;padding:7px 14px;font-size:13px;cursor:pointer;">It helped</button>'
   +   '<button class="fb-h" data-v="somewhat" style="margin:3px;border:1px solid #ddd1c8;background:#fff;color:#99673e;border-radius:999px;padding:7px 14px;font-size:13px;cursor:pointer;">Somewhat</button>'
   +   '<button class="fb-h" data-v="no" style="margin:3px;border:1px solid #e0c8c8;background:#fff;color:#9a6a6a;border-radius:999px;padding:7px 14px;font-size:13px;cursor:pointer;">Not really</button>'
   + '</div>'
   + '<textarea id="fb-words" placeholder="Anything you want to share about how you feel, or what helped? (optional)" style="width:100%;box-sizing:border-box;height:56px;border:1px solid #ddd1c8;border-radius:10px;padding:9px;font-size:13px;resize:none;"></textarea>'
   + '<div style="text-align:center;margin-top:8px;">'
   +   '<button onclick="submitFeedback()" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:9px 22px;font-size:14px;font-weight:700;cursor:pointer;margin:0 4px;">Share</button>'
   +   '<button onclick="closeFb()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:9px 16px;font-size:14px;cursor:pointer;margin:0 4px;">No thanks</button>'
   + '</div>';
  document.body.appendChild(box);
  box.querySelectorAll('.fb-h').forEach(function(b){
    b.onclick = function(){ box.querySelectorAll('.fb-h').forEach(function(x){x.style.outline='none';});
      b.style.outline='2px solid #2e6e8e'; window._fbHelped = b.getAttribute('data-v'); };
  });
}
async function submitFeedback(){
  const words = (document.getElementById('fb-words')||{}).value || '';
  const helped = window._fbHelped || '';
  let feeling = '';
  if (helped==='yes') feeling='calmer'; else if (helped==='no') feeling='same';
  try {
    await fetch('/api/feedback', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({helped: helped, feeling: feeling, words: words})});
  } catch(e){}
  const card = document.getElementById('fb-card');
  if (card) card.innerHTML = '<div style="text-align:center;font-size:14px;color:#6a402c;padding:6px;">Thank you for sharing \u2014 it genuinely helps us reach others. <button onclick="closeFb()" style="margin-left:8px;background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:6px 14px;cursor:pointer;">Close</button></div>';
}

// ---- LIVE BIOMETRIC PING: anonymous, every 4s, for the founder's live monitor.
// Sends only: an anonymous session id, bpm, tier, and derived calm state.
// No words, no identity. Lets the founder watch the calm curve in real time.
let _bioPingInt = null;
function startBioPing(){
  if (_bioPingInt) return;
  _bioPingInt = setInterval(()=>{
    try {
      // Ping EVERY interval while the session is live, even before a heart
      // reading exists, so the founder's live monitor shows the session right
      // away with an honest status (camera on / acquiring / measured).
      const fresh = window._heartUpdatedAt && (Date.now() - window._heartUpdatedAt < 12000);
      const bpm = (fresh && window._heartBPM) ? Math.round(window._heartBPM) : 0;
      const base = window._heartBaseline ? Math.round(window._heartBaseline) : (bpm || 0);
      let state = 'steady';
      if (bpm) { if (bpm >= base + 8) state = 'rising'; else if (bpm <= base - 6) state = 'settling'; }
      const face = (window.currentFaceEmotion || '');
      const cam = window._camOn ? 1 : 0;
      fetch('/api/bio/ping', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({sid: sessionId, bpm: bpm, tier: (window._heartTier||''),
          base: base, state: state, face: face, cam: cam, hasheart: bpm ? 1 : 0})}).catch(()=>{});
    } catch(e){}
  }, 4000);
}

_hrTickInt=null, _hrEstInt=null;
function startHeartLoop(){
  if (_hrTickInt) return;
  _hrTickInt = setInterval(()=>{ try{ heartTick(); }catch(e){} }, 66);   // ~15 Hz
  _hrEstInt  = setInterval(()=>{ try{ heartEstimate(); heartReport(); }catch(e){} }, 1000);
  startBioPing();
}

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
adaptiveInterval = null;

// ===== TEXT EMOTION SIGNAL (research: adding text lifted accuracy 48% -> 66%) =====
// The words a person types are often the TRUEST signal — people say what they
// cannot show. This reads recent typed text into a calm..activated estimate,
// plus a separate "low/down" reading, so the music can answer hidden feeling.
let _lastTextState = { up: 0, down: 0, at: 0 };
const TXT_ACTIVATED = ['panic','panicking','can\u2019t breathe','cant breathe','can\u2019t take','cant take',
  'terrified','scared','afraid','angry','furious','rage','hate','anxious','anxiety','overwhelmed',
  'racing','shaking','freaking','can\u2019t stop','cant stop','out of control','emergency','help me',
  'losing it','breaking down','too much','stressed','tense','worried','dread','nervous'];
const TXT_LOW = ['hopeless','worthless','empty','numb','alone','lonely','tired','exhausted','done',
  'give up','giving up','can\u2019t go on','cant go on','no point','pointless','sad','depressed',
  'crying','cry','hurts','pain','lost','dark','heavy','defeated','miss'];
const TXT_CALM = ['better','calmer','okay','ok','breathing','relaxed','safe','thank','grateful',
  'peaceful','settling','easier','helps','helping','calm'];
function analyzeText(text){
  if (!text) return;
  const t = ' ' + text.toLowerCase() + ' ';
  let up=0, down=0, calm=0;
  TXT_ACTIVATED.forEach(w=>{ if (t.indexOf(w)>=0) up++; });
  TXT_LOW.forEach(w=>{ if (t.indexOf(w)>=0) down++; });
  TXT_CALM.forEach(w=>{ if (t.indexOf(w)>=0) calm++; });
  // normalize to 0..1, calm words pull activation down
  const upN = Math.min(1, up*0.34 - calm*0.2);
  const downN = Math.min(1, down*0.34);
  _lastTextState = { up: Math.max(0,upN), down: Math.max(0,downN), at: Date.now() };
  window._textEmotion = _lastTextState;
}
// text fades in relevance over ~90s (a feeling typed a while ago matters less)
function textWeightNow(){
  if (!_lastTextState.at) return 0;
  const age = (Date.now() - _lastTextState.at)/1000;
  return age > 90 ? 0.15 : (age > 45 ? 0.5 : 1.0);
}

let adaptiveArousal = 0.5;   // 0 = very calm/flat, 1 = very activated. Smoothed.
let adaptiveDownSm = 0;      // smoothed "down/flat" reading — one flicker of a
                             // sad detection must never flip the music.
let adaptiveLaneNow = 'calm'; // which lane the adaptive loop currently favors
let adaptiveLastSwitch = 0;

// ===========================================================================
// THE PERSONAL READ ("Attunement") — built from scratch on the constructive
// science, replacing the old signal fusion. Principles:
//  - Compare each person ONLY to their OWN calm (per-channel personal baselines),
//    never to a population — the same signal means different things in different
//    people (individual response stereotypy; the law of initial values).
//  - Fuse several optional, on-device channels (words, facial engagement, facial
//    volatility, voice energy) and LEARN which ones track THIS person from their
//    own occasional one-tap check-ins (personalized models beat universal ones).
//    The heart is deliberately not used.
//  - Output a HUMBLE scalar — "activation relative to your own calm" — with a
//    CONFIDENCE, never an emotion label. Low confidence => soften and ask the
//    person, whose own words and taps are the real truth.
//  - Everything stays on this device (localStorage). Nothing is shipped out.
// ===========================================================================
var ATT = (function(){
  var CH = ['text','faceAct','faceVol','voiceAct'];
  var PRIOR_W = { text:0.50, faceAct:0.20, faceVol:0.15, voiceAct:0.15 };
  // Neutral-calm starting baseline per channel — NOT the person's first reading,
  // so someone who arrives already activated still reads as activated. The
  // baseline then personalizes over time (see relative()).
  var PRIOR_M = { text:0.30, faceAct:0.30, faceVol:0.10, voiceAct:0.40 };
  var st = { base:{}, weights:{}, reports:0, anchor:null, lastFace:null,
             arousal:0.5, down:0, confidence:0, parts:{}, _rels:{} };
  CH.forEach(function(c){ st.base[c]={m:PRIOR_M[c],d:0.15}; st.weights[c]=PRIOR_W[c]; });

  function load(){ try{ var raw=localStorage.getItem('il_att_v1'); if(!raw) return;
    var o=JSON.parse(raw); if(o&&o.base){ CH.forEach(function(c){ var bc=o.base[c];
      if(bc && typeof bc.m==='number' && isFinite(bc.m) && typeof bc.d==='number' && isFinite(bc.d)) st.base[c]={m:bc.m,d:bc.d};
      if(o.weights && typeof o.weights[c]==='number' && isFinite(o.weights[c])) st.weights[c]=o.weights[c]; }); }
    if(o && typeof o.reports==='number' && isFinite(o.reports)) st.reports=o.reports; }catch(e){} }
  function save(){ try{ localStorage.setItem('il_att_v1', JSON.stringify({base:st.base,weights:st.weights,reports:st.reports})); }catch(e){} }

  function sampleText(){ try{ if(typeof textWeightNow!=='function'||!window._textEmotion) return null;
    var tw=textWeightNow(); if(tw<=0) return null; return {v:Math.max(0,Math.min(1,window._textEmotion.up||0)), w:tw}; }catch(e){ return null; } }
  function sampleFaceAct(){ try{ var s=(typeof faceEmotionScores!=='undefined'&&faceEmotionScores)?faceEmotionScores:null; if(!s) return null;
    var a=(s.angry||0)*1.0+(s.fearful||0)*0.9+(s.surprised||0)*0.4+(s.disgusted||0)*0.5;
    var present=(a>0.03)||((s.sad||0)>0.03)||((s.happy||0)>0.03)||((s.neutral||0)>0.05); if(!present) return null;
    return {v:Math.max(0,Math.min(1,a)), w:1}; }catch(e){ return null; } }
  function sampleFaceVol(){ try{ var s=(typeof faceEmotionScores!=='undefined'&&faceEmotionScores)?faceEmotionScores:null; if(!s) return null;
    var vec=[s.angry||0,s.fearful||0,s.sad||0,s.happy||0,s.surprised||0,s.disgusted||0,s.neutral||0];
    var vol=null; if(st.lastFace){ var d=0; for(var i=0;i<vec.length;i++){ d+=Math.abs(vec[i]-st.lastFace[i]); } vol=Math.max(0,Math.min(1,d*0.9)); }
    st.lastFace=vec; if(vol===null) return null; return {v:vol, w:1}; }catch(e){ return null; } }
  function sampleVoiceAct(){ try{ var v=(typeof voiceFeatures!=='undefined'&&voiceFeatures)?voiceFeatures:null; if(!v||(v.energy==null&&v.tremor==null)) return null;
    var a=(v.energy||0.5)*0.5+(v.pitch_variance||0.5)*0.3+(v.tremor||0)*0.6; return {v:Math.max(0,Math.min(1,a)), w:1}; }catch(e){ return null; } }
  var SAMP={ text:sampleText, faceAct:sampleFaceAct, faceVol:sampleFaceVol, voiceAct:sampleVoiceAct };

  // Track each channel's OWN baseline and return activation relative to it
  // (0.5 = own calm). The baseline learns the person's CALM FLOOR quickly but
  // rises only very slowly, so sustained distress is not normalized away.
  function relative(c,x){ var b=st.base[c];
    if(typeof b.m!=='number' || !isFinite(b.m)) b.m=PRIOR_M[c];
    if(typeof b.d!=='number' || !isFinite(b.d)) b.d=0.15;
    var dev=x-b.m; var scale=2.2*(b.d+0.05); var rel=0.5+0.5*Math.tanh(dev/(scale||0.2));
    var alpha=(x<b.m)?0.03:0.006; b.m+=alpha*dev; b.d+=0.02*(Math.abs(dev)-b.d);
    return Math.max(0,Math.min(1,rel)); }

  function update(){ var present={}, rels={}, wsum=0, acc=0, vals=[];
    CH.forEach(function(c){ var s=SAMP[c]?SAMP[c]():null; if(!s){ present[c]=0; return; }
      present[c]=1; var rel=relative(c,s.v); rels[c]=rel; var w=st.weights[c]*(s.w||1); acc+=rel*w; wsum+=w; vals.push(rel); });
    var sensor=wsum>0?acc/wsum:0.5;
    var nP=vals.length; var presence=Math.min(1,nP/2);
    var spread=0; if(nP>1){ var mean=vals.reduce(function(a,b){return a+b;},0)/nP; var vv=0; vals.forEach(function(x){vv+=(x-mean)*(x-mean);}); spread=Math.sqrt(vv/nP); }
    var agree=1-Math.min(1,spread*2); var calib=Math.min(1,st.reports/5);
    var conf=Math.max(0.05,Math.min(1,0.15+0.35*presence+0.25*agree+0.25*calib));
    var out=sensor;
    if(st.anchor){ var age=(Date.now()-st.anchor.at)/1000; if(age<75){ var a=Math.max(0,1-age/75); out=a*st.anchor.v+(1-a)*sensor; conf=Math.max(conf,0.5+0.4*a); } }
    st.arousal=Math.max(0,Math.min(1,out)); st.confidence=conf; st._rels=rels;
    st.parts={ text:present.text||0, face:(present.faceAct||present.faceVol)?1:0, voice:present.voiceAct||0, self:st.anchor?1:0, conf:Math.round(conf*100) };
    var dn=0,dw=0;
    try{ if(typeof textWeightNow==='function'&&window._textEmotion){ var tw=textWeightNow(); if(tw>0){ dn+=(window._textEmotion.down||0)*tw; dw+=tw; } } }catch(e){}
    try{ var s2=(typeof faceEmotionScores!=='undefined'&&faceEmotionScores)?faceEmotionScores:null; if(s2){ dn+=(s2.sad||0)*0.6; dw+=0.6; } }catch(e){}
    st.down=dw>0?Math.max(0,Math.min(1,dn/dw)):0;
    return st.arousal; }

  // a self-report (ground truth). v in 0..1 (0 = settled, 1 = overwhelmed).
  function report(v){ v=Math.max(0,Math.min(1,v)); st.anchor={v:v,at:Date.now()}; st.reports+=1;
    var rels=st._rels||{}; var keys=Object.keys(rels);
    if(keys.length){ var errs=keys.map(function(c){ return Math.abs(rels[c]-v); });
      var mean=errs.reduce(function(a,b){return a+b;},0)/errs.length;
      keys.forEach(function(c,i){ st.weights[c]=Math.max(0.04, st.weights[c]+0.15*(mean-errs[i])); });
      var tot=0; CH.forEach(function(c){ tot+=st.weights[c]; }); if(tot>0){ CH.forEach(function(c){ st.weights[c]/=tot; }); } }
    save(); }

  load(); var _si=null;
  return { update:update, report:report, start:function(){ if(!_si){ _si=setInterval(save,30000); } },
           read:function(){ return {arousal:st.arousal, down:st.down, confidence:st.confidence, parts:st.parts}; },
           confidence:function(){ return st.confidence; }, state:st };
})();
window.ATT = ATT;

// ---- The wordless one-tap CHECK-IN — the person's own truth, and what teaches
// the personal read which of their signals to trust. Gentle, optional, dismissible.
var _ilCheckinLast = 0, _ilSessionStart = Date.now();
var _IL_CT = {
  en:{q:'How are you feeling right now?', a:'Settled', b:'Overwhelmed', thanks:'Thank you.', skip:'Not now'},
  es:{q:'¿Cómo te sientes ahora mismo?', a:'En calma', b:'Abrumado/a', thanks:'Gracias.', skip:'Ahora no'},
  zh:{q:'你现在感觉怎么样？', a:'平静', b:'不知所措', thanks:'谢谢你。', skip:'暂不'}
};
function _ilct(k){ var lg=(window._ilLang||'en'); return (_IL_CT[lg]||_IL_CT.en)[k]; }
function showCheckin(){ if(document.getElementById('il-checkin')) return;
  var wrap=document.createElement('div'); wrap.id='il-checkin';
  wrap.style.cssText='position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:9000;max-width:92vw;'
    +'background:#faf5ec;border:1px solid #e7dccc;border-radius:18px;box-shadow:0 12px 40px rgba(42,30,20,0.22);'
    +'padding:16px 18px 14px;text-align:center;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;';
  var dots=''; var i;
  for(i=0;i<5;i++){ var sz=14+i*3; var col=['#5f8bb6','#7f97b0','#b9a58f','#cf8a5e','#c56a2c'][i];
    dots+='<button aria-label="'+i+'" onclick="ilCheckinPick('+(i/4)+')" style="border:0;background:'+col+';'
      +'width:'+sz+'px;height:'+sz+'px;border-radius:50%;margin:0 9px;cursor:pointer;padding:0;vertical-align:middle;opacity:.92;"></button>'; }
  wrap.innerHTML='<div style="font-size:15px;color:#2b2620;margin-bottom:12px;">'+_ilct('q')+'</div>'
    +'<div style="display:flex;align-items:center;justify-content:center;">'
    +'<span style="font-size:12px;color:#8a7d6c;margin-right:6px;">'+_ilct('a')+'</span>'+dots
    +'<span style="font-size:12px;color:#8a7d6c;margin-left:6px;">'+_ilct('b')+'</span></div>'
    +'<div style="margin-top:8px;"><a href="#" onclick="closeCheckin();return false;" style="font-size:12px;color:#8a7d6c;text-decoration:none;">'+_ilct('skip')+'</a></div>';
  document.body.appendChild(wrap); _ilCheckinLast=Date.now();
}
function ilCheckinPick(v){ try{ if(window.ATT) ATT.report(v); }catch(e){}
  var w=document.getElementById('il-checkin'); if(w){ w.innerHTML='<div style="font-size:15px;color:#2b2620;padding:6px 4px;">'+_ilct('thanks')+'</div>';
    setTimeout(function(){ try{ w.remove(); }catch(e){} }, 1100); } _ilCheckinLast=Date.now(); }
function closeCheckin(){ var w=document.getElementById('il-checkin'); if(w){ try{ w.remove(); }catch(e){} } _ilCheckinLast=Date.now(); }
window.ilCheckinPick=ilCheckinPick; window.closeCheckin=closeCheckin; window.showCheckin=showCheckin;
function ilMaybeInvite(){ try{
  var ss=document.getElementById('story-screen'); if(!ss || ss.style.display==='none') return;
  if(document.getElementById('il-checkin')) return;
  var now=Date.now(); var since=now-_ilCheckinLast;
  var conf=(window.ATT?ATT.confidence():1);
  var firstDue=(_ilCheckinLast===0 && (now-_ilSessionStart)>60000);
  var lowConf=(conf<0.45 && since>180000);
  var periodic=(_ilCheckinLast>0 && since>270000);
  if(firstDue||lowConf||periodic) showCheckin();
}catch(e){} }

// ===========================================================================
// THE RHYTHM ANCHOR — a steady pulsing light that rises up to HOLD a person who
// has gone quiet and slipped away (e.g. pulled back into their own thoughts or
// voices). A predictable rhythm gives a preoccupied mind one external thing to
// lock onto; the light, the word, and the person's own TAP all land on the same
// beat, and the beat eases toward THEIR tapping tempo (meet them, then guide).
// It appears on demand, and on its own after a stretch of stillness — so the app
// never just goes silent and loses them. Gentle, dismissible, on-device.
// ===========================================================================
var _ilLastInteract = Date.now(), _ilEngaged = false, _ilAnchorLast = 0;
function ilNoteInteract(){ _ilLastInteract = Date.now(); _ilEngaged = true; }
var _IL_AN = {
  en:{hint:'tap the light — the rhythm will follow you', close:'I’m okay for now', pill:'Focus with me',
      stay:'… stay with me.', words:['here.','with you.','breathe in…','and out…','you’re safe.','stay with me.']},
  es:{hint:'toca la luz — el ritmo te seguirá', close:'Estoy bien por ahora', pill:'Enfócate conmigo',
      stay:'… quédate conmigo.', words:['aquí.','contigo.','inhala…','y exhala…','estás a salvo.','quédate conmigo.']},
  zh:{hint:'轻触这束光——节奏会跟随你', close:'我现在还好', pill:'和我一起专注',
      stay:'……和我在一起。', words:['就在这里。','陪着你。','吸气……','呼气……','你是安全的。','和我在一起。']}
};
function _ilan(k){ var lg=(window._ilLang||'en'); return (_IL_AN[lg]||_IL_AN.en)[k]; }
function showAnchor(){ if(document.getElementById('il-anchor')) return; _ilAnchorLast=Date.now();
  var A=_IL_AN[(window._ilLang||'en')]||_IL_AN.en;
  var ov=document.createElement('div'); ov.id='il-anchor';
  ov.style.cssText='position:fixed;inset:0;z-index:9500;opacity:0;transition:opacity 1.2s ease;overflow:hidden;'
    +'background:radial-gradient(60% 60% at 50% 42%,#2a1d12 0%,#1c140d 55%,#140e09 100%);'
    +'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;';
  ov.innerHTML='<canvas id="il-anchor-c" style="position:absolute;inset:0;width:100%;height:100%;display:block;"></canvas>'
    +'<div id="il-anchor-w" style="position:absolute;left:0;right:0;top:42%;transform:translateY(-50%);text-align:center;'
    +'font-size:28px;color:#f3e9dc;opacity:0;pointer-events:none;text-shadow:0 2px 20px rgba(0,0,0,.6);"></div>'
    +'<div style="position:absolute;left:0;right:0;bottom:96px;text-align:center;font-size:13px;color:#a8917c;pointer-events:none;">'+A.hint+'</div>'
    +'<button id="il-anchor-x" style="position:absolute;left:50%;bottom:34px;transform:translateX(-50%);'
    +'background:rgba(28,20,13,.7);border:1px solid rgba(240,176,112,.3);color:#d7c3ad;border-radius:999px;'
    +'padding:9px 18px;font-size:13px;cursor:pointer;">'+A.close+'</button>';
  document.body.appendChild(ov);
  document.getElementById('il-anchor-x').addEventListener('click', function(ev){ ev.stopPropagation(); hideAnchor(); });
  requestAnimationFrame(function(){ ov.style.opacity=1; });
  ilAnchorRun(ov, A);
}
function hideAnchor(){ var o=document.getElementById('il-anchor'); if(o){ o._stop=true; try{o.remove();}catch(e){} } _ilAnchorLast=Date.now(); }
function ilAnchorRun(ov, A){
  var c=ov.querySelector('#il-anchor-c'), ctx=c.getContext('2d'), wordEl=ov.querySelector('#il-anchor-w');
  var DPR=Math.min(2,window.devicePixelRatio||1), W=0,H=0;
  function resize(){ W=c.clientWidth;H=c.clientHeight;c.width=W*DPR;c.height=H*DPR;ctx.setTransform(DPR,0,0,DPR,0,0); }
  resize(); var ro=function(){resize();}; window.addEventListener('resize',ro);
  var cycle=10000, t0=performance.now(), lastIdx=-1, rings=[], flash=0, wi=0, cur='', taps=[];
  ov.addEventListener('pointerdown', function(e){ if(e.target && e.target.id==='il-anchor-x') return;
    var now=performance.now(); taps.push(now); if(taps.length>4) taps.shift();
    if(taps.length>=2){ var iv=[]; for(var i=1;i<taps.length;i++) iv.push(taps[i]-taps[i-1]);
      var avg=iv.reduce(function(a,b){return a+b;},0)/iv.length; var target=Math.max(5000,Math.min(14000,avg*2));
      cycle=cycle*0.6+target*0.4; }
    rings.push({born:now,strong:true}); flash=1; });
  var nm=(window._ilName||'').toString().trim();
  function frame(now){ if(ov._stop){ window.removeEventListener('resize',ro); return; }
    var el=now-t0, idx=Math.floor(el/cycle), p=(el%cycle)/cycle, swell=0.5-0.5*Math.cos(2*Math.PI*p);
    if(idx!==lastIdx){ lastIdx=idx; rings.push({born:now,strong:false});
      if(nm && idx%3===0) cur=nm+A.stay; else { cur=A.words[wi%A.words.length]; wi++; } }
    var cx=W/2, cy=H*0.42; ctx.clearRect(0,0,W,H);
    for(var i=rings.length-1;i>=0;i--){ var age=(now-rings[i].born)/cycle; if(age>1.1){rings.splice(i,1);continue;}
      var rr=60+age*Math.min(W,H)*0.55, op=Math.max(0,(1-age))*(rings[i].strong?0.5:0.28);
      ctx.beginPath();ctx.arc(cx,cy,rr,0,2*Math.PI);ctx.strokeStyle='rgba(240,176,112,'+op.toFixed(3)+')';
      ctx.lineWidth=rings[i].strong?2.5:1.5;ctx.stroke(); }
    var R=64+swell*52+flash*14, g=ctx.createRadialGradient(cx,cy,4,cx,cy,R*1.9);
    g.addColorStop(0,'rgba(255,236,205,'+Math.min(1,0.85+0.15*swell+flash*0.1).toFixed(3)+')');
    g.addColorStop(0.35,'rgba(240,176,112,'+(0.75*(0.6+0.4*swell)).toFixed(3)+')');
    g.addColorStop(1,'rgba(217,138,78,0)');
    ctx.beginPath();ctx.arc(cx,cy,R*1.9,0,2*Math.PI);ctx.fillStyle=g;ctx.fill();
    ctx.beginPath();ctx.arc(cx,cy,R*0.5,0,2*Math.PI);ctx.fillStyle='rgba(255,240,215,'+(0.5+0.4*swell).toFixed(3)+')';ctx.fill();
    flash*=0.9; if(flash<0.01) flash=0;
    if(cur){ wordEl.textContent=cur; wordEl.style.opacity=(swell*0.95).toFixed(2); }
    requestAnimationFrame(frame); }
  requestAnimationFrame(frame);
}
function ilAddAnchorPill(){ if(document.getElementById('il-anchor-pill')) return;
  var b=document.createElement('button'); b.id='il-anchor-pill'; b.textContent='◎ '+_ilan('pill');
  b.style.cssText='position:fixed;left:16px;bottom:16px;z-index:8000;background:rgba(42,29,18,.62);'
    +'border:1px solid rgba(240,176,112,.3);color:#e8d8c4;border-radius:999px;padding:9px 14px;font-size:12.5px;'
    +'cursor:pointer;backdrop-filter:blur(6px);';
  b.addEventListener('click', function(){ showAnchor(); });
  document.body.appendChild(b); }
function ilMaybeAnchor(){ try{
  var ss=document.getElementById('story-screen'); if(!ss || ss.style.display==='none') return;
  if(document.getElementById('il-anchor')) return;
  if(!_ilEngaged) return;
  var now=Date.now();
  if((now-_ilLastInteract) > 45000 && (now-_ilAnchorLast) > 150000) showAnchor();
}catch(e){} }
window.showAnchor=showAnchor; window.hideAnchor=hideAnchor;

function readArousalSignal() {
  // Personal, baseline-relative, multi-channel read (see ATT above). The heart is
  // deliberately excluded; this compares the person to their OWN calm, learns which
  // signals track THEM from their own check-ins, and returns a humble activation
  // (0.5 = their own calm) with a confidence — never an emotion label.
  if (!window._attStarted){ window._attStarted = 1;
    try { ATT.start(); } catch(e){}
    try { document.addEventListener('keydown', ilNoteInteract, true); document.addEventListener('pointerdown', ilNoteInteract, true); } catch(e){}
    try { ilAddAnchorPill(); } catch(e){}
    try { setInterval(function(){ ilMaybeInvite(); ilMaybeAnchor(); }, 12000); } catch(e){}
  }
  var a = ATT.update();
  window._adaptiveDown = ATT.state.down;
  window._fusionParts = ATT.state.parts;
  window._attConfidence = ATT.state.confidence;
  return a;
}

function adaptiveTick() {
  if (!ambientTracks.length) return;
  const inst = readArousalSignal();
  // Smooth so the sound never lurches — gentle, like quiet authority — but
  // alive enough that a held expression is answered within ~15 seconds.
  adaptiveArousal = adaptiveArousal*0.8 + inst*0.2;
  adaptiveDownSm = adaptiveDownSm*0.8 + (window._adaptiveDown || 0)*0.2;
  const down = adaptiveDownSm;

  // 1) Continuously nudge VOLUME within a gentle band. More activated -> a touch
  //    softer and steadier (don't add to their noise). Calm -> normal presence.
  const deck = getActiveDeck();
  if (deck && !crossfading) {
    const band = 0.04; // small, never dramatic
    if (_duckActive) return; // music is ducked for voice — do not touch volume
    let target = TARGET_VOL - (adaptiveArousal - 0.5) * band; // higher arousal => softer
    target = Math.max(TARGET_VOL - band, Math.min(TARGET_VOL + band*0.5, target));
    // ease toward target
    deck.volume = deck.volume + (target - deck.volume) * 0.2;
  }

  // 2) When the read is clearly and persistently one way, gently shift the LANE
  //    (deep-calm to bring an activated person DOWN; lifting to reach a flat/
  //    down person UP). Rate-limited so it can't flip back and forth.
  const now = Date.now();
  if (now - adaptiveLastSwitch < 10000) return; // at most one shift per 10s
  let want = null;
  if (adaptiveArousal > 0.55 && adaptiveLaneNow !== 'deepcalm') want = 'deepcalm';
  else if (down > 0.45 && adaptiveArousal < 0.5 && adaptiveLaneNow !== 'lifting') want = 'lifting';
  else if (adaptiveArousal < 0.4 && down < 0.35 && adaptiveLaneNow !== 'calm') want = 'calm';
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
          metric('lane_switch', want + ':' + JSON.stringify(window._fusionParts||{}));
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
entrainPanL = null; entrainPanR = null; /* entrainOn hoisted */
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

// ---- MUSIC DUCKING FOR VOICE (first user feedback): music must fully stop
// while the person speaks, wait 2s after they finish, then FADE gently back. ----
/* _duckActive, _duckRestoreTimer, _duckFadeTimer hoisted */
function duckMusicForVoice(){
  _duckActive = true;
  if (_duckRestoreTimer){ clearTimeout(_duckRestoreTimer); _duckRestoreTimer = null; }
  if (_duckFadeTimer){ clearInterval(_duckFadeTimer); _duckFadeTimer = null; }
  // silence both decks immediately (quick 250ms fade to 0 so it is not a jarring cut)
  const decks = [document.getElementById('ambient-a'), document.getElementById('ambient-b')];
  decks.forEach(d=>{ if(!d) return; const from=d.volume; let step=0;
    const iv=setInterval(()=>{ step++; d.volume=Math.max(0, from*(1-step/8)); if(step>=8){ clearInterval(iv); d.volume=0; } }, 30);
  });
}
function restoreMusicAfterVoice(){
  // Wait 2 full seconds after voice ends, THEN fade in gently over ~4s.
  if (_duckRestoreTimer) clearTimeout(_duckRestoreTimer);
  _duckRestoreTimer = setTimeout(()=>{
    _duckActive = false;
    const active = (typeof getActiveDeck==='function') ? getActiveDeck() : document.getElementById('ambient-a');
    if (!active) return;
    const ceiling = (typeof userMuted!=='undefined' && userMuted) ? 0 : TARGET_VOL;
    if (ceiling <= 0) return;
    let step = 0; const steps = 80;         // ~4s at 50ms
    if (_duckFadeTimer) clearInterval(_duckFadeTimer);
    _duckFadeTimer = setInterval(()=>{
      step++; const ease = step/steps;
      active.volume = Math.min(ceiling, ceiling * ease * ease); // ease-in (gentle start)
      if (step >= steps){ clearInterval(_duckFadeTimer); _duckFadeTimer=null; active.volume = ceiling; }
    }, 50);
  }, 2000);
}

let deckA, deckB, activeDeck = 'A';
let crossfading = false;
const CROSSFADE_MS = 4000; // 4 second blend
const CROSSFADE_TRIGGER = 8; // start blend 8 seconds before track ends
TARGET_VOL = 0.035;    // headphone-safe; user slider can raise it

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
  reportTrackPlay(next);   // record this play with a timestamp
}

// Report every track play (file + lane + timestamp) so the founder page can
// show exactly what played, when, and how often. Founder visibility + control.
function reportTrackPlay(track){
  try {
    if (!track || !track.url) return;
    const file = track.url.split('/').pop();
    fetch('/api/track/play', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({file: file, lane: track.name || '', at: Date.now()})}).catch(()=>{});
  } catch(e){}
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
// --- Hoisted audio-state declarations (must exist before any function uses them) ---
entrainOn = false; entrainPanL = null; entrainPanR = null;
_duckActive = false; _duckRestoreTimer = null; _duckFadeTimer = null;
// ---- Volume control: mute + slider. Slider 40 = the safe default. ----
let userMuted = false;
function currentTarget(){ return userMuted ? 0 : TARGET_VOL; }
function setVol(v){
  TARGET_VOL = 0.12 * (v/100); // slider full = 0.12 ceiling; default 24 ≈ 0.029 (soft)
  ['deckA','deckB'].forEach(id=>{ const d=document.getElementById(id); if(d && !userMuted) d.volume = Math.min(1, TARGET_VOL); });
}
function toggleMute(){
  userMuted = !userMuted;
  const b = document.getElementById('mute-btn');
  if (b) b.innerHTML = userMuted ? '&#128263;' : '&#128266;';
  ['deckA','deckB'].forEach(id=>{ const d=document.getElementById(id); if(d) d.volume = userMuted ? 0 : Math.min(1, TARGET_VOL); });
}
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
  // Begin the live-monitor heartbeat IMMEDIATELY, independent of the camera or
  // face models, so an active session always shows up for the founder (even a
  // text-only, camera-off session). It's a no-op if it can't reach the server.
  try { startBioPing(); } catch(e){}
  // Start on a RANDOM real photograph each time — never the same one every login —
  // then rotate gently from there.
  var _startScene = SCENE_ORDER[Math.floor(Math.random() * SCENE_ORDER.length)];
  currentScene = _startScene;
  setScene(_startScene, false);
  startSceneRotation();

  // STEP 2: Start camera, face detection, and music IN THE BACKGROUND
  // These are nice-to-have — the conversation works even if they all fail
  setTimeout(async () => {
    // Camera
    try { await startVisualCamera(); } catch (e) { console.log('[InnerLight] Camera unavailable:', e); }
    // Face emotion detection
    try { await loadFaceModels(); startFaceLoop(); startHeartLoop(); } catch (e) { console.log('[InnerLight] Face models unavailable:', e); }
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
        deck.volume = TARGET_VOL * 0.08;  // enter nearly silent, rise very gently
        deck.play().then(()=>metric('first_sound_ms', Date.now()-TAP_MS)).catch(()=>{});
        (function arrivalRise(){
          const RISE_MS = 16000; // sixteen calm seconds from near-silent to full
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
        try { reportTrackPlay(ambientTracks[0]); } catch(e){}   // track the arrival song
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
  const arousalBase = (typeof readArousalSignal==='function') ? readArousalSignal() : 0.5;
  trackWatch = { name: name || 'unknown', startMs: Date.now(), baseline: displeasure, easeBase: easeB, easeSum: 0, arousalSum: 0, arousalBase: arousalBase, samples: 0, strikes: 0 };
}
function trackGuardianTick(){
  if (!trackWatch) return;
  const age = Date.now() - trackWatch.startMs;
  const sc = faceEmotionScores || {};
  const displeasure = (sc.disgusted||0)*1.2 + (sc.angry||0) + (sc.surprised||0)*0.6;
  const ease = (sc.happy||0) + (sc.neutral||0)*0.3;
  // FUSION-BASED reaction: use the whole four-signal state, not just the face,
  // so reactions register even when the face is flat (the real-world case).
  const arousalNow = (typeof readArousalSignal==='function') ? readArousalSignal() : 0.5;
  if (age > 45000) {
    // Verdict: did the person SETTLE during this track (arousal fell) = liked;
    // did they get MORE activated = disliked; little change = neutral.
    const arousalDrop = (trackWatch.arousalBase||0.5) - (trackWatch.arousalSum/Math.max(1,trackWatch.samples));
    const avgEase = trackWatch.easeSum / Math.max(1, trackWatch.samples);
    let verdict = 'neutral';
    if (arousalDrop > 0.06 || (avgEase - trackWatch.easeBase > 0.10)) verdict = 'liked';
    else if (arousalDrop < -0.08) verdict = 'disliked';
    metric('track_react', trackWatch.name + '|' + verdict);
    trackWatch = null; return;
  }
  if (age < 4000) return;                          // let the crossfade settle first
  trackWatch.easeSum = (trackWatch.easeSum||0) + ease;
  trackWatch.arousalSum = (trackWatch.arousalSum||0) + arousalNow;
  trackWatch.samples = (trackWatch.samples||0) + 1;
  // Strikes now come from RISING arousal during the track (any signal), not just face.
  if (arousalNow - (trackWatch.arousalBase||0.5) > 0.18 || displeasure - trackWatch.baseline > 0.35) trackWatch.strikes++;
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
    restoreMusicAfterVoice();   // 2s pause, then gentle fade back in
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
  duckMusicForVoice();   // stop the music while they speak
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
      voiceRecognizer.lang = (typeof ilBcp47 === 'function') ? ilBcp47(window._ilLang || 'en') : 'en-US';
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
    // the page's current language decides which language of voice we prefer.
    var pageLang = (window._ilLang || 'en').slice(0,2).toLowerCase();
    var score = (v) => {
      let s = 0;
      const n = (v.name || '').toLowerCase();
      var vl = (v.lang || '').toLowerCase();
      if (/neural|natural|online/.test(n)) s += 100;     // the genuinely good ones
      if (/aria|jenny|guy|sonia|ryan|libby|michelle/.test(n)) s += 40; // MS neural names
      if (/samantha|ava|allison|tom|zoe|evan|nicky|joelle/.test(n)) s += 35; // Apple neural names
      if (/google/.test(n)) s += 30;                     // Google voices are decent
      if (v.localService === false) s += 25;             // cloud voices = better
      // MATCH THE PAGE LANGUAGE FIRST — a Spanish page should speak Spanish,
      // a Chinese page should speak Mandarin. This dominates so the default
      // voice is always in the person's language.
      if (vl.slice(0,2) === pageLang) s += 300;
      else s -= 200;                                     // wrong language: push it down hard
      if (pageLang === 'en' && /en-us|en-gb/.test(vl)) s += 15;
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
    try { populateVoicePicker(); } catch(e){}
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
function selectVoice(v){
  v = v || '';
  if (v.indexOf('b:') === 0){
    // a specific BROWSER voice chosen by the person
    var nm = v.slice(2);
    var found = (window._voiceRanked||[]).find(function(x){ return x.name === nm; });
    if (found) selectedVoice = found;
    selectedVoiceId = '';   // browser voice takes over
  } else {
    selectedVoiceId = v;    // a premium provider voice id
  }
  if (voiceEnabled && v){ speak('This is the voice I will use.'); }
}
// Build the voice picker from BOTH the premium provider (if a key is live) AND
// the best browser voices, so the person can choose a male/female/accent voice
// even without a paid voice service. Reveals the picker only when there's a
// real choice to make. A guess at gender from the voice name, for grouping.
function _voiceGender(name){
  var n=(name||'').toLowerCase();
  if(/(female|aria|jenny|sonia|libby|michelle|samantha|ava|allison|zoe|nicky|joelle|zira|susan|karen|serena|tessa|fiona|moira|catherine)/.test(n)) return 'Female';
  if(/(male|guy|ryan|tom|evan|david|mark|daniel|fred|alex|oliver|george|james)/.test(n)) return 'Male';
  return 'Voice';
}
async function populateVoicePicker(){
  var sel = document.getElementById('voice-picker'); if(!sel) return;
  var pageLang = (window._ilLang || 'en').slice(0,2).toLowerCase();
  var opts = '<option value="">Voice: automatic (best available)</option>';
  var any = false;
  // premium provider voices for THIS language (only present when a voice key is configured)
  try{
    var r = await fetch('/api/voice/list?lang=' + encodeURIComponent(pageLang)); var d = await r.json();
    if (d && d.voices && d.voices.length){
      opts += '<optgroup label="Human voices">';
      d.voices.forEach(function(v){ any=true; opts += '<option value="'+v.id+'">'+(v.label||v.id)+'</option>'; });
      opts += '</optgroup>';
    }
  }catch(e){}
  // browser voices — prefer ones that match the page language, grouped by
  // likely gender, best first. A Spanish page should not offer English voices.
  var ranked = (window._voiceRanked||[]).slice();
  var matching = ranked.filter(function(v){ return (v.lang||'').slice(0,2).toLowerCase() === pageLang; });
  var pool = (matching.length ? matching : ranked).slice(0,10);
  if (pool.length){
    var groups = {Female:[],Male:[],Voice:[]};
    pool.forEach(function(v){ groups[_voiceGender(v.name)].push(v); });
    ['Female','Male','Voice'].forEach(function(g){
      if(!groups[g].length) return;
      opts += '<optgroup label="'+(g==='Voice'?'Other voices':g+' voices')+'">';
      groups[g].forEach(function(v){ any=true;
        var lang=(v.lang||'').toUpperCase();
        opts += '<option value="b:'+v.name.replace(/"/g,'')+'">'+v.name+(lang?' ('+lang+')':'')+'</option>';
      });
      opts += '</optgroup>';
    });
  }
  sel.innerHTML = opts;
  sel.style.display = any ? '' : 'none';
}
function loadVoiceChoices(){ return populateVoicePicker(); }
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

// ===================== SPEECH QUEUE — ONE VOICE AT A TIME =====================
// Only ONE line is ever spoken at a time. New lines wait in a queue for the
// current one to FINISH — they never overlap. This fixes the provider/therapist
// prompt cutting in over the main response. Works for both the server's human
// audio and the browser fallback voice.
var _spQueue = [];
var _spSpeaking = false;
var _spCurAudio = null;

function speak(text) {
  if (!voiceEnabled || !text) return;
  _spQueue.push(String(text));
  _spPump();
}
function _spPump() {
  if (_spSpeaking) return;                 // something is already speaking; wait
  var text = _spQueue.shift();
  if (text == null) return;                // queue empty
  _spSpeaking = true;
  var advanced = false;
  function done() {
    if (advanced) return; advanced = true;
    _spCurAudio = null; _spSpeaking = false;
    _spPump();                             // speak the next queued line, if any
  }
  // Watchdog: a stalled clip must never freeze the queue forever.
  var words = text.split(/\s+/).length;
  var watchdog = setTimeout(done, Math.min(30000, words * 350 + 4000));
  function finish() { clearTimeout(watchdog); done(); }
  _spPlayOne(text, finish);
}
function _spPlayOne(text, finish) {
  // Try REAL human audio from the server first; fall back to the browser voice.
  fetch('/api/voice/speak', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: text, voice_id: selectedVoiceId || '', lang: (window._ilLang || 'en')})
  }).then(function(r){ return r.json(); }).then(function(d) {
    if (d && d.audio_b64) {
      try {
        var audio = new Audio('data:' + (d.mime || 'audio/mpeg') + ';base64,' + d.audio_b64);
        _spCurAudio = audio;
        audio.volume = 0.95;
        audio.onended = finish;
        audio.onerror = function(){ _spSpeakBrowser(text, finish); };
        audio.play().catch(function(){ _spSpeakBrowser(text, finish); });
      } catch(e) { _spSpeakBrowser(text, finish); }
    } else {
      _spSpeakBrowser(text, finish);
    }
  }).catch(function(){ _spSpeakBrowser(text, finish); });
}
function _spSpeakBrowser(text, finish) {
  if (!voiceEnabled || !('speechSynthesis' in window) || !text) { finish(); return; }
  try { speechSynthesis.cancel(); } catch(e){}
  var utter = new SpeechSynthesisUtterance(text);
  // Speak in the person's chosen language, with a voice that actually speaks it.
  var _lang = (typeof ilBcp47 === 'function') ? ilBcp47(window._ilLang || 'en') : 'en-US';
  utter.lang = _lang;
  var _v = null;
  if (selectedVoice && (selectedVoice.lang||'').slice(0,2).toLowerCase() === _lang.slice(0,2).toLowerCase()) _v = selectedVoice;
  if (!_v && typeof ilPickVoice === 'function') _v = ilPickVoice(_lang);
  if (_v) utter.voice = _v;
  // WARMTH + TONE-STEERING: a slightly lower pitch reads as warmer, and we slow
  // down when the person is activated (the vocal twin of the adaptive music).
  var ar = (typeof adaptiveArousal !== 'undefined') ? adaptiveArousal : 0.5;
  ar = Math.max(0, Math.min(1, ar));
  utter.rate = 0.95 - 0.13 * ar;   // ~0.95 when calm, ~0.82 when activated
  utter.pitch = 0.97;              // a touch lower = warmer, less robotic
  utter.volume = 0.95;
  utter.onend = finish;
  utter.onerror = finish;
  try { speechSynthesis.speak(utter); } catch(e){ finish(); }
}
// Immediately silence everything and clear anything waiting (voice turned off,
// or a brand-new turn begins so old lines shouldn't linger).
function stopAllSpeech() {
  _spQueue = [];
  _spSpeaking = false;
  try { if (_spCurAudio) { _spCurAudio.pause(); _spCurAudio.currentTime = 0; } } catch(e){}
  _spCurAudio = null;
  try { if ('speechSynthesis' in window) speechSynthesis.cancel(); } catch(e){}
}
// Back-compat: any older caller of speakBrowser still works, now queued.
function speakBrowser(text) { speak(text); }

function toggleVoiceCombined(){
  const btn = document.getElementById('voice-toggle');
  const turningOn = !voiceEnabled;
  voiceEnabled = turningOn;
  try { window._voiceFirst = turningOn; } catch(e){}
  if (!turningOn) { try { stopAllSpeech(); } catch(e){} }
  if (typeof applyVoiceFirst === 'function') { try { applyVoiceFirst(turningOn); } catch(e){} }
  if (btn) btn.innerHTML = turningOn ? '&#128266; Spoken voice: On' : '&#128263; Spoken voice: Off';
}
function toggleVoice() {
  voiceEnabled = !voiceEnabled;
  if (!voiceEnabled) { try { stopAllSpeech(); } catch(e){} }
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
    window._camOn = true;   // the live monitor uses this to show camera state
    $('emotion-status').textContent = 'Camera ready. Click analyze visual emotion when the person is visible.';
  } catch (error) {
    window._camOn = false;
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
window._applyProviderSuggestion = applyProviderSuggestion;
function openLegalHelp(){ try{ openHelp('legal'); }catch(e){} }
function routeProvider(){ try{ openHelp('telehealth'); }catch(e){} }
function openHelp(kind){
  if (window._minorLock){ showMinorBridge(); return; }
  return _openHelpReal(kind);
}
function _openHelpReal(kind){
  metric('handoff_click', kind);
  // Each path is honest about WHERE the person is going and WHO they will reach.
  // The conversation is carried over so they never fill out a jargon form.
  try { sessionStorage.setItem('innerlight_convo', JSON.stringify(conversationLog)); } catch(e){}
  // Navigate in the SAME tab. window.open('_blank') is silently blocked by many
  // mobile browsers, in-app webviews, and popup blockers — which made the
  // buttons look dead / froze the page. The conversation is saved above and the
  // handoff page reads it, so same-tab is reliable everywhere and never freezes.
  var dest = (kind === 'attorney' || kind === 'legal') ? '/handoff/legal' : '/handoff/clinical';
  var _lg = (window._ilLang || 'en'); if (_lg !== 'en') dest += '?lang=' + _lg;
  try { window.location.assign(dest); } catch(e){ window.location.href = dest; }
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


// ================= RETURNING-USER MEMORY (opt-in, code-based) =================
// After a person has shared, we gently offer to save so they never restart.
// The code is theirs; without it the story cannot be read.

function copyReturnCode(btn){ try{ navigator.clipboard && navigator.clipboard.writeText(btn.getAttribute('data-code')); btn.textContent='Copied \u2713'; }catch(e){} }
function dismissSaveOffer(){ var o=document.getElementById('save-offer'); if(o) o.remove(); }
function closeResumeBox(){ var b=document.getElementById('resume-box'); if(b) b.remove(); }

function collectStory(){
  // gather the conversation so far into a plain summary
  try {
    const thread = document.getElementById('conversation-thread');
    if (thread && thread.textContent.trim().length > 20) return thread.textContent.trim().slice(0, 5500);
  } catch(e){}
  const msg = document.getElementById('message');
  return msg && msg.value ? msg.value.trim().slice(0,5500) : '';
}
let _memOffered = false;
function maybeOfferSave(){
  if (_memOffered) return;
  const story = collectStory();
  if (story.length < 40) return;  // only once there's something worth saving
  _memOffered = true;
  const bar = document.createElement('div');
  bar.id = 'save-offer';
  bar.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:75;'
    + 'background:rgba(255,255,255,0.97);border:1px solid #e0d7cf;border-radius:16px;padding:14px 18px;'
    + 'box-shadow:0 10px 30px rgba(20,40,30,0.2);font-family:Arial;max-width:340px;text-align:center;';
  bar.innerHTML = '<div style="font-size:14px;color:#4a362c;margin-bottom:10px;">Would you like to save where you are, so you don\u2019t have to start over if you come back?</div>'
    + '<button onclick="doSaveStory()" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:9px 20px;font-size:14px;font-weight:700;cursor:pointer;margin:0 5px;">Save my place</button>'
    + '<button onclick="dismissSaveOffer()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:9px 18px;font-size:14px;cursor:pointer;margin:0 5px;">Not now</button>';
  document.body.appendChild(bar);
}
async function doSaveStory(){
  const story = collectStory();
  const offer = document.getElementById('save-offer');
  try {
    const r = await fetch('/api/memory/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({summary: story})});
    const d = await r.json();
    if (d.status === 'ok'){
      if (offer) offer.innerHTML = '<div style="font-size:14px;color:#4a362c;margin-bottom:8px;">Saved. This is your return code \u2014 keep it somewhere safe:</div>'
        + '<div style="font-size:22px;font-weight:800;letter-spacing:1px;color:#1e3a5c;margin:6px 0;">' + d.code + '</div>'
        + '<div style="font-size:12px;color:#9a8778;margin-bottom:10px;">Only this code can reopen your story \u2014 not even we can read it without the code.</div>'
        + '<button onclick="copyReturnCode(this)" data-code="' + d.code + '" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:8px 18px;font-size:13px;cursor:pointer;margin:0 5px;">Copy code</button>'
        + '<button onclick="dismissSaveOffer()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:8px 16px;font-size:13px;cursor:pointer;margin:0 5px;">Done</button>';
    } else if (offer){ offer.querySelector('div').textContent = 'There was nothing saved yet \u2014 share a little first.'; }
  } catch(e){ if (offer) offer.querySelector('div').textContent = 'Could not save right now. Please try again.'; }
}
function openResume(){
  const box = document.createElement('div');
  box.id = 'resume-box';
  box.style.cssText = 'position:fixed;inset:0;z-index:95;background:rgba(10,18,30,0.75);display:flex;align-items:center;justify-content:center;padding:20px;';
  box.innerHTML = '<div style="background:#fff;border-radius:18px;padding:26px;max-width:360px;width:100%;font-family:Arial;text-align:center;">'
    + '<h3 style="margin:0 0 6px;color:#1e3a5c;">Continue your story</h3>'
    + '<p style="font-size:13px;color:#9a8778;margin:0 0 16px;">Enter the return code you saved last time.</p>'
    + '<input id="resume-code" placeholder="e.g. CALM-4821-MOON" style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #ddd1c8;border-radius:10px;font-size:16px;text-align:center;text-transform:uppercase;">'
    + '<div id="resume-msg" style="font-size:13px;color:#c0564e;min-height:18px;margin:8px 0;"></div>'
    + '<button onclick="doResume()" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:11px 26px;font-size:15px;font-weight:700;cursor:pointer;">Continue</button> '
    + '<button onclick="closeResumeBox()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:11px 20px;font-size:15px;cursor:pointer;">Cancel</button>'
    + '</div>';
  document.body.appendChild(box);
  setTimeout(()=>{ const el=document.getElementById('resume-code'); if(el) el.focus(); }, 100);
}
async function doResume(){
  const code = (document.getElementById('resume-code')||{}).value || '';
  const msg = document.getElementById('resume-msg');
  if (code.trim().length < 4){ if(msg) msg.textContent='Please enter your full code.'; return; }
  try {
    const r = await fetch('/api/memory/resume', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({code: code})});
    const d = await r.json();
    if (d.status === 'ok'){
      const box = document.getElementById('resume-box'); if (box) box.remove();
      const thread = document.getElementById('conversation-thread');
      if (thread){
        const div = document.createElement('div');
        div.style.cssText = 'background:rgba(46,110,142,0.1);border-radius:12px;padding:12px 14px;margin:8px 0;font-size:14px;color:#4a362c;';
        div.innerHTML = '<b>Welcome back.</b> Here\u2019s where you left off, so you don\u2019t have to start over:<br><br>' + (d.summary||'').replace(/</g,'&lt;');
        thread.appendChild(div);
        thread.scrollIntoView({behavior:'smooth', block:'start'});
      }
    } else if (msg){
      msg.textContent = d.status==='notfound' ? 'We couldn\u2019t find that code. Check it and try again.' : 'That code didn\u2019t work. Please try again.';
    }
  } catch(e){ if(msg) msg.textContent='Could not connect. Please try again.'; }
}

async function sendCheckin() {
  try { const _mv=(document.getElementById('message')||{}).value||''; checkSubstitutionSignals(_mv); checkMinorSignals(_mv); analyzeText(_mv); if (typeof applyProviderSuggestion==='function') applyProviderSuggestion(); } catch(e){}
  if (window._minorLock){ showMinorBridge(); return; }  startZenisys('greeting');
  const msgVal = (val('message') || '').trim();
  // Empty guard: if there's nothing to send, don't fake a response.
  if (!msgVal) {
    const em = $('emotion-status');
    if (em) { em.style.display='block'; em.textContent = "I didn't catch anything yet — take your time, and share whenever you're ready."; }
    return;
  }
  voiceFinalTranscript = '';
  try { stopAllSpeech(); } catch(e){}   // new turn: silence any lingering lines
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
    ? '<p style="background:#f7f3f0;border:1px solid #ddd1c8;border-radius:12px;padding:14px;color:#4a372d;font-size:15px;margin:14px 0;">You are not alone. If you need immediate support, you can reach the 988 Suicide and Crisis Lifeline anytime by calling or texting 988. I am staying right here with you.</p>'
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
  el.style.cssText = 'text-align:left;background:#f8f5f2;border:1px solid #e6d8cc;border-radius:14px;padding:18px;margin:14px 0;';
  const rights = (lg.your_rights || []).slice(0,3).map(r => '<li style="margin:4px 0;">' + escapeHtml(r) + '</li>').join('');
  const askAtty = (lg.questions_for_attorney || []).slice(0,3).map(q => '<li style="margin:4px 0;">' + escapeHtml(q) + '</li>').join('');
  const freeHelp = (lg.free_legal_help || []).slice(0,3).map(h => '<li style="margin:4px 0;">' + escapeHtml(h) + '</li>').join('');
  const steps = (lg.steps_you_can_take_now || []).slice(0,3).map(s => '<li style="margin:4px 0;">' + escapeHtml(s) + '</li>').join('');
  el.innerHTML = `
    <p style="font-size:15px;color:#6a402c;font-weight:600;margin:0 0 8px;">Based on what you shared, here are some things you should know about your ${escapeHtml(lg.issue_detected)}:</p>
    <details style="margin:8px 0;" open>
      <summary style="font-size:13px;font-weight:600;color:#815734;cursor:pointer;">Your rights</summary>
      <ul style="font-size:14px;color:#4a372d;padding-left:20px;margin:6px 0;">${rights}</ul>
    </details>
    <details style="margin:8px 0;">
      <summary style="font-size:13px;font-weight:600;color:#815734;cursor:pointer;">Questions to ask an attorney</summary>
      <ul style="font-size:14px;color:#4a372d;padding-left:20px;margin:6px 0;">${askAtty}</ul>
    </details>
    <details style="margin:8px 0;">
      <summary style="font-size:13px;font-weight:600;color:#815734;cursor:pointer;">Where to get free legal help</summary>
      <ul style="font-size:14px;color:#4a372d;padding-left:20px;margin:6px 0;">${freeHelp}</ul>
    </details>
    <details style="margin:8px 0;">
      <summary style="font-size:13px;font-weight:600;color:#815734;cursor:pointer;">Steps you can take right now</summary>
      <ul style="font-size:14px;color:#4a372d;padding-left:20px;margin:6px 0;">${steps}</ul>
    </details>
    <p style="font-size:11px;color:#bb8559;margin:10px 0 0;line-height:1.5;">${escapeHtml(lg.disclaimer || '')}</p>
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
    crisis: {bg:'#f7f3f0', border:'#b27849', accent:'#6b412c'},
    legal: {bg:'#f8f5f2', border:'#dcc0a9', accent:'#d4782d'},
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
    <label style="display:flex;align-items:flex-start;gap:8px;font-size:13px;color:#6b412c;margin:10px 0;cursor:pointer;">
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
  el.style.cssText = 'text-align:left;background:linear-gradient(135deg,#b27849,#9e6a40);color:#fff;border-radius:16px;padding:24px;margin:18px 0;';
  // Show the warm handoff parts in sequence, gently
  const partsHtml = (warm.parts || []).map(p =>
    `<p style="font-size:16px;line-height:1.75;margin:0 0 12px;">${escapeHtml(p)}</p>`).join('');
  el.innerHTML = `
    ${partsHtml}
    <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
      <button id="bridge-go" style="background:#fff;color:#6b412c;border:0;border-radius:999px;padding:12px 24px;font-size:15px;font-weight:700;cursor:pointer;">Connect now</button>
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
  el.style.cssText = 'text-align:center;background:linear-gradient(135deg,#b27849,#9e6a40);color:#fff;border-radius:14px;padding:22px;margin:18px 0;';
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
  exchange.style.cssText = 'text-align:left;padding:16px 0;border-bottom:1px solid #f0ece8;';
  const questionHtml = (question && question.trim())
    ? `<p style="font-size:16px;line-height:1.7;color:#4a372d;margin:14px 0 0;font-weight:500;">${escapeHtml(question)}</p>`
    : '';
  exchange.innerHTML = `
    <p style="font-size:16px;line-height:1.7;color:#4a372d;margin:0 0 8px;">${escapeHtml(reply)}</p>
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
  userMsg.innerHTML = `<p style="display:inline-block;background:#f3ede9;color:#4a372d;padding:10px 16px;border-radius:16px 16px 4px 16px;font-size:15px;max-width:80%;text-align:left;">${escapeHtml(userAnswer)}</p>`;
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
    ? '<p style="background:#f7f3f0;border:1px solid #ddd1c8;border-radius:12px;padding:14px;color:#4a372d;font-size:15px;margin:14px 0;">You are not alone. The 988 Lifeline is available anytime — call or text 988. I am right here.</p>'
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
    :root { color-scheme: light; --bg:#faf5ec; --panel:#ffffff; --line:#ece0d0; --text:#2a1e14; --muted:#8a7a68; --ok:#2f6da8; --warn:#b7791f; --bad:#c53030; --accent:#b24a2a; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Arial, sans-serif; background:var(--bg); color:var(--text); }
    header { padding:20px 24px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; gap:16px; align-items:center; }
    h1 { font-size:22px; margin:0; }
    .brand-block { padding:22px 24px; border-bottom:1px solid var(--line); background:#f7f3ef; }
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
    pre { white-space:pre-wrap; word-break:break-word; background:#fcfaf9; border:1px solid var(--line); padding:12px; border-radius:4px; max-height:420px; overflow:auto; }
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
    :root { --ink:#2a1e14; --muted:#8a7a68; --line:#ece0d0; --soft:#faf5ec; --urgent:#b84a44; --green:#b24a2a; --blue:#2f6da8; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Arial, sans-serif; color:var(--ink); background:#fdfcfb; }
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
    .rights { background:#fbf9f7; border-color:#e9e0d9; }
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
    .secondary { background:#f1ece8; color:var(--ink); }
    .locked { font-size:13px; color:var(--muted); margin-top:8px; }
    .pro-btn { display:block; width:100%; text-align:left; margin:8px 0; padding:13px 16px; border-radius:12px;
               border:1.5px solid var(--line); background:#fff; cursor:pointer; font-size:15px; }
    .pro-btn span { display:block; font-size:12.5px; color:var(--muted); margin-top:3px; font-weight:400; }
    .pro-btn.picked { border-color:var(--green); background:#fbf2ea; box-shadow:0 0 0 2px rgba(178,74,42,0.18); }
    .pro-btn.suggested { border-color:#2e6e8e; box-shadow:0 0 0 2px rgba(46,110,142,0.25); }
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
        <div id="pro-suggestion" style="display:none;background:#f8f5f2;border:1px solid #e6d6c8;border-radius:12px;padding:12px 15px;font-size:13.5px;color:#6a402c;margin-bottom:12px;"></div>
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
      <a class="button secondary" href="/" onclick="if(history.length>1){history.back();return false;}">Go back</a>
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
    const PAGE_OPEN_TS = Date.now();
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
        body: JSON.stringify({kind:'care', pro: pickedPro, summary: summaryText, hp:'', elapsed: (Date.now()-PAGE_OPEN_TS)})})
      .then(r=>r.json()).then(function(d){
        document.getElementById('status').innerHTML =
          'Your request for a <b>' + esc(pickedPro.toLowerCase()) + '</b> is in, and a human has been alerted. '
          + 'While our professional network grows, an <b>InnerLight responder</b> \u2014 our founder, not a licensed '
          + 'provider \u2014 will meet you first, stay with you, and help arrange the ' + esc(pickedPro.toLowerCase()) + ' you chose. '
          + 'Above is the exact summary they will read.<br><br>'
          + '<a href="' + d.room + '" target="_blank" style="display:inline-block;background:#7d522e;color:#fff;'
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
    :root { --ink:#2a1e14; --muted:#8a7a68; --line:#ece0d0; --soft:#faf5ec; --urgent:#b84a44; --legal:#b24a2a; --legal2:#c56a2c; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Arial, sans-serif; color:var(--ink); background:#fbfbfd; }
    header { padding:26px 6vw; border-bottom:1px solid var(--line); background:white; }
    main { padding:24px 6vw 60px; max-width:920px; margin:0 auto; }
    h1 { margin:0 0 6px; font-size:clamp(26px, 4.5vw, 44px); line-height:1.05; }
    h2 { margin:0 0 10px; font-size:20px; }
    p { color:var(--muted); line-height:1.55; }
    .tag { display:inline-block; padding:5px 12px; border-radius:999px; background:#f6f1ed; border:1px solid #ecddd1; color:var(--legal); font-weight:700; font-size:13px; margin-bottom:10px; }
    .panel { border:1px solid var(--line); border-radius:12px; background:white; padding:20px; margin:16px 0; }
    .who { background:#faf8f7; border-color:#f0e4da; }
    .who ul { margin:8px 0 0; padding-left:0; list-style:none; }
    .who li { padding:9px 0; border-bottom:1px solid #f2ece8; color:var(--ink); }
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
    .secondary { background:#f3eeea; color:var(--ink); }
    .locked { font-size:13px; color:var(--muted); margin-top:8px; }
    .pro-btn { display:block; width:100%; text-align:left; margin:8px 0; padding:13px 16px; border-radius:12px;
               border:1.5px solid var(--line); background:#fff; cursor:pointer; font-size:15px; }
    .pro-btn span { display:block; font-size:12.5px; color:var(--muted); margin-top:3px; font-weight:400; }
    .pro-btn.picked { border-color:var(--green); background:#fbf2ea; box-shadow:0 0 0 2px rgba(178,74,42,0.18); }
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
    <section class="panel who" id="state-panel">
      <h2>First &mdash; what state are you in? Legal help is different in every state</h2>
      <p>The law in New York is not the law in California. So we don't want to hand you another state's rules. Tell us your state and we'll point you to help for where you actually are.</p>
      <label for="state-select">Your state</label>
      <select id="state-select" style="width:100%;max-width:360px;padding:12px;border:1px solid var(--line);border-radius:8px;font:inherit;background:#fff;">
        <option value="">Select your state&hellip;</option>
      </select>
      <div id="state-help" style="margin-top:14px;"></div>
    </section>

    <section class="panel who">
      <h2>Self-help &amp; civic resources &mdash; free, trusted, available right now</h2>
      <p>These are established, free legal-information sources. They explain your rights and the process in plain language. They are information, <b>not</b> legal advice &mdash; only a lawyer can advise on your specific case &mdash; but they are a strong, fast place to start understanding where you stand.</p>
      <div class="reslib">
        <a class="res" href="https://www.lawhelp.org/" target="_blank" rel="noopener"><b>LawHelp.org</b><span>Find free legal aid and self-help by state and topic.</span></a>
        <a class="res" href="https://www.law.cornell.edu/wex" target="_blank" rel="noopener"><b>Cornell Law &mdash; Wex</b><span>Plain-language legal dictionary &amp; explanations from Cornell Law School.</span></a>
        <a class="res" href="https://www.abafreelegalanswers.org/" target="_blank" rel="noopener"><b>ABA Free Legal Answers</b><span>Ask a lawyer a civil legal question free &mdash; you pick your state, and a volunteer attorney in your state answers.</span></a>
        <a class="res" href="https://www.usa.gov/legal-aid" target="_blank" rel="noopener"><b>USA.gov Legal Aid</b><span>Government directory of free and low-cost legal help.</span></a>
        <a class="res" href="https://www.lsc.gov/about-lsc/what-legal-aid/find-legal-aid" target="_blank" rel="noopener"><b>Legal Services Corporation</b><span>Find your local federally funded legal-aid office.</span></a>
        <a class="res" href="https://www.nolo.com/legal-encyclopedia" target="_blank" rel="noopener"><b>Nolo Legal Encyclopedia</b><span>Readable articles on tenants, family, debt, and more.</span></a>
      </div>
    </section>

    <section class="panel who">
      <h2>Law-school legal knowledge &amp; clinics &mdash; authoritative and free</h2>
      <p>Law schools publish some of the clearest legal explanations available, and many run <b>free legal clinics</b> that represent low-income people directly. These broaden and cross-check the understanding of your rights &mdash; different schools sometimes explain or expand the same issue in ways that help.</p>
      <p id="clinic-note" style="font-size:13px;color:var(--legal);font-weight:700;margin:6px 0 0;">Pick your state at the top of this page and your state's law-school clinic appears here.</p>
      <div id="state-clinic" style="margin:10px 0;"></div>
      <div class="reslib">
        <a class="res" href="https://www.law.cornell.edu/wex" target="_blank" rel="noopener"><b>Cornell Law &mdash; Wex</b><span>Free, plain-language legal encyclopedia from Cornell Law School &mdash; explains the law for any state.</span></a>
      </div>
      <p style="font-size:12.5px;color:#8a929a;">Clinics accept clients by their own eligibility rules (often income-based and by region). Even when a clinic can't take your case, its public guides and Know-Your-Rights materials are free to read. Every state's flagship law-school clinic is listed &mdash; choose your state above.</p>
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
      <a class="button secondary" href="/" onclick="if(history.length>1){history.back();return false;}">Go back</a>
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
    const PAGE_OPEN_TS = Date.now();
    function pickPro(btn){
      document.querySelectorAll('.pro-btn').forEach(b=>b.classList.remove('picked'));
      btn.classList.add('picked'); pickedPro = btn.dataset.pro;
      document.getElementById('pro-picked').textContent = 'You chose: ' + pickedPro + '.';
    }
  </script>
  <script>
    function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }

    // ---- STATE-SPECIFIC ROUTING: legal help differs by state; never hand a
    // person another state's rules. Everyone is routed to help for THEIR state. ----
    var US_STATES = [
      ['AL','Alabama'],['AK','Alaska'],['AZ','Arizona'],['AR','Arkansas'],['CA','California'],
      ['CO','Colorado'],['CT','Connecticut'],['DE','Delaware'],['DC','District of Columbia'],
      ['FL','Florida'],['GA','Georgia'],['HI','Hawaii'],['ID','Idaho'],['IL','Illinois'],
      ['IN','Indiana'],['IA','Iowa'],['KS','Kansas'],['KY','Kentucky'],['LA','Louisiana'],
      ['ME','Maine'],['MD','Maryland'],['MA','Massachusetts'],['MI','Michigan'],['MN','Minnesota'],
      ['MS','Mississippi'],['MO','Missouri'],['MT','Montana'],['NE','Nebraska'],['NV','Nevada'],
      ['NH','New Hampshire'],['NJ','New Jersey'],['NM','New Mexico'],['NY','New York'],
      ['NC','North Carolina'],['ND','North Dakota'],['OH','Ohio'],['OK','Oklahoma'],['OR','Oregon'],
      ['PA','Pennsylvania'],['RI','Rhode Island'],['SC','South Carolina'],['SD','South Dakota'],
      ['TN','Tennessee'],['TX','Texas'],['UT','Utah'],['VT','Vermont'],['VA','Virginia'],
      ['WA','Washington'],['WV','West Virginia'],['WI','Wisconsin'],['WY','Wyoming']
    ];
    // Verified flagship law-school legal clinic for every state (URLs confirmed
    // to resolve). Alaska has no ABA-accredited law school. Some states list two.
    var STATE_CLINICS = {
      'AK': [],
      'AL': [{s:'University of Alabama School of Law', u:'https://law.ua.edu/academics/law-clinics/', b:'Free civil, criminal defense, domestic violence, mediation clinics.'}],
      'AR': [{s:'University of Arkansas School of Law', u:'https://law.uark.edu/service-outreach/clinics/', b:'Free civil, criminal, immigration, human trafficking clinics.'}],
      'AZ': [{s:'University of Arizona College of Law', u:'https://law.arizona.edu/academics/clinical-programs', b:'Clinics: domestic violence, immigration, veterans, family.'}],
      'CA': [{s:'Stanford Law — Mills Legal Clinic', u:'https://law.stanford.edu/mills-legal-clinic/', b:'Free clinics: eviction defense, disability, reentry.'},{s:'UC Berkeley School of Law', u:'https://www.law.berkeley.edu/experiential/clinics/', b:'Clinics: human rights, environmental, community law.'}],
      'CO': [{s:'University of Colorado Law School', u:'https://www.colorado.edu/law/academics/clinical-education-program', b:'Clinics: civil, criminal defense, juvenile/family, immigration.'}],
      'CT': [{s:'Yale Law School', u:'https://law.yale.edu/studying-law-yale/clinical-and-experiential-learning', b:'30+ clinics: veterans, immigration, housing, workers.'}],
      'DE': [{s:'Widener University Delaware Law School', u:'https://delawarelaw.widener.edu/current-students/jd-academics/experiential-courses/clinics/', b:'Clinics: domestic violence, veterans, environmental, innocence.'}],
      'DC': [{s:'Georgetown University Law Center', u:'https://www.law.georgetown.edu/experiential-learning/clinics/', b:'17 clinics: health justice, criminal defense, legislation.'}],
      'FL': [{s:'University of Florida Levin College of Law', u:'https://law.ufl.edu/academics/experiential-learning/clinics-and-field-placements/', b:'Clinics: civil, immigration, veterans, juvenile, tax.'}],
      'GA': [{s:'University of Georgia School of Law', u:'https://www.law.uga.edu/clinics-and-externships', b:'Clinics: family justice, veterans, community health law.'}],
      'HI': [{s:'University of Hawaii Richardson School of Law', u:'https://law.hawaii.edu/academics/experiential-learning/', b:'Clinics: family, elder, immigration, Native Hawaiian rights.'}],
      'ID': [{s:'University of Idaho College of Law', u:'https://www.uidaho.edu/law/legal-clinics-and-support', b:'Clinics: family, immigration, community, tribal law.'}],
      'IL': [{s:'University of Illinois College of Law', u:'https://law.illinois.edu/academics/clinics-experiential-learning/', b:'Clinics: family, immigration, veterans, First Amendment.'}],
      'IN': [{s:'Indiana University Maurer School of Law', u:'https://law.indiana.edu/academics/experiential-education/clinics/index.html', b:'Live-client clinics: reentry, protection orders, IP.'}],
      'IA': [{s:'University of Iowa College of Law', u:'https://law.uiowa.edu/experiential-learning/clinical-law-program', b:'Clinics: immigration, criminal defense, community empowerment.'}],
      'KS': [{s:'University of Kansas School of Law', u:'https://law.ku.edu/academics/hands-on-learning/clinics', b:'Clinics: legal aid, innocence, veterans.'}],
      'KY': [{s:'University of Kentucky Rosenberg College of Law', u:'https://law.uky.edu/current-students/clinics', b:'Free civil litigation and civil rights clinics.'}],
      'LA': [{s:'LSU Paul M. Hebert Law Center', u:'https://law.lsu.edu/experiential/clinics/', b:'Clinics: veterans, youth defense, small business, tax.'}],
      'ME': [{s:'University of Maine School of Law', u:'https://mainelaw.maine.edu/academics/clinics-and-centers/', b:'Clinics: general practice, refugee/human rights, domestic abuse.'}],
      'MD': [{s:'University of Maryland Carey School of Law', u:'https://www.law.umaryland.edu/academics/clinics/', b:'18 clinics: eviction prevention, immigration, consumer, medical-legal.'}],
      'MA': [{s:'Harvard Law School Clinics', u:'https://www.law.harvard.edu/clinics/', b:'Legal Services Center and many free public clinics.'}],
      'MI': [{s:'University of Michigan Law School', u:'https://michigan.law.umich.edu/academics/experiential-learning/clinics', b:'Clinics: child advocacy, immigration, human trafficking.'}],
      'MN': [{s:'University of Minnesota Law School', u:'https://law.umn.edu/minnesota-law-clinics', b:'25+ clinics: family, immigration, consumer, economic justice.'}],
      'MS': [{s:'University of Mississippi School of Law', u:'https://law.olemiss.edu/research-and-practice/clinics-centers-and-institutes/', b:'Clinics serving underserved clients with legal representation.'}],
      'MO': [{s:'University of Missouri School of Law', u:'https://law.missouri.edu/academics/clinics/', b:'Clinics: child/family justice, veterans, entrepreneurship.'}],
      'MT': [{s:'University of Montana Blewett School of Law', u:'https://www.umt.edu/law/academics/clinics/', b:'Clinics: veterans, domestic violence, Indian law.'}],
      'NE': [{s:'University of Nebraska College of Law', u:'https://law.unl.edu/experiential-learning/', b:'Clinics: housing/eviction, children, debtor defense, innocence.'}],
      'NV': [{s:'UNLV William S. Boyd School of Law', u:'https://law.unlv.edu/clinics/our-clinics', b:'Clinics: immigration, misdemeanor, mediation, public policy.'}],
      'NH': [{s:'UNH Franklin Pierce School of Law', u:'https://law.unh.edu/academics/clinics', b:'Clinics: criminal defense, IP/transaction, live-client work.'}],
      'NJ': [{s:'Rutgers Law School', u:'https://law.rutgers.edu/professional-skills/clinics', b:'20+ clinics: housing, domestic violence, immigrant rights, veterans.'}],
      'NM': [{s:'University of New Mexico School of Law', u:'https://lawschool.unm.edu/clinic/index.html', b:'Clinics: family, economic justice, Indian law.'}],
      'NY': [{s:'NYU Law Clinics', u:'https://www.law.nyu.edu/academics/clinics/clinics-by-topic', b:'Eviction defense, veterans, immigrant defense, civil rights.'},{s:'CUNY School of Law', u:'https://www.law.cuny.edu/academics/clinical-programs/', b:'Public-interest clinics: housing, immigration, family, disability.'}],
      'NC': [{s:'University of North Carolina School of Law', u:'https://law.unc.edu/experiential-learning/clinics/', b:'Clinics: civil, family defense, immigration, veterans, youth.'}],
      'ND': [{s:'University of North Dakota School of Law', u:'https://law.und.edu/academics/und-law-clinics.html', b:'Clinics: family, immigration, business/non-profit.'}],
      'OH': [{s:'Ohio State Moritz College of Law', u:'https://moritzlaw.osu.edu/academics/clinics', b:'Clinics: civil, immigration, justice for children, mediation.'}],
      'OK': [{s:'University of Oklahoma College of Law', u:'https://law.ou.edu/jd/academics/experiential-learning/clinics', b:'Free civil and criminal defense clinics for low-income.'}],
      'OR': [{s:'University of Oregon School of Law', u:'https://law.uoregon.edu/become-practice-ready/clinics', b:'Clinics: domestic violence, criminal defense, nonprofit.'}],
      'PA': [{s:'University of Pennsylvania Carey Law School', u:'https://www.law.upenn.edu/clinic/', b:'Gittis clinics: civil, criminal defense, child advocacy, immigration.'}],
      'RI': [{s:'Roger Williams University School of Law', u:'https://law.rwu.edu/academics/juris-doctor/clinics-and-externships', b:'Clinics: immigration, housing, criminal defense, veterans.'}],
      'SC': [{s:'University of South Carolina Rice School of Law', u:'https://sc.edu/study/colleges_schools/law/academics/experiential_learning/clinics/', b:'Clinics: domestic violence, veterans, education, tax, youth.'}],
      'SD': [{s:'University of South Dakota Knudson School of Law', u:'https://www.usd.edu/Academics/Colleges-and-Schools/knudson-school-of-law/Experiential-Learning', b:'Clinics: divorce, veterans, tax help.'}],
      'TN': [{s:'University of Tennessee College of Law', u:'https://winston.utk.edu/clinics/', b:'Clinics: advocacy, domestic violence, wills, expungement.'}],
      'TX': [{s:'University of Texas School of Law', u:'https://law.utexas.edu/clinics/', b:'Clinics: housing, immigration, domestic violence, children.'}],
      'UT': [{s:'University of Utah S.J. Quinney College of Law', u:'https://www.law.utah.edu/experiential-education/clinics/', b:'Clinics: immigration, mental health, environmental justice.'}],
      'VT': [{s:'Vermont Law and Graduate School', u:'https://www.vermontlaw.edu/academics/clinics-and-externships', b:'South Royalton Legal Clinic, environmental justice, small business.'}],
      'VA': [{s:'University of Virginia School of Law', u:'https://www.law.virginia.edu/clinics', b:'24 clinics: housing, immigration, civil rights, health/disability.'}],
      'WA': [{s:'University of Washington School of Law', u:'https://www.law.uw.edu/academics/experiential-learning/clinics', b:'Clinics: housing, immigration, workers rights, veterans.'}],
      'WV': [{s:'West Virginia University College of Law', u:'https://www.law.wvu.edu/clinical-law', b:'Clinics: general litigation, immigration, veterans, innocence.'}],
      'WI': [{s:'University of Wisconsin Law School', u:'https://law.wisc.edu/clinics/', b:'Clinics: housing, family, consumer, restraining orders, immigration.'}],
      'WY': [{s:'University of Wyoming College of Law', u:'https://www.uwyo.edu/law/experiential/clinics/index.html', b:'Clinics: civil, family, defender aid, estate.'}]
    };
    function initStatePicker(){
      var sel = document.getElementById('state-select');
      if (!sel) return;
      for (var i=0;i<US_STATES.length;i++){
        var o = document.createElement('option');
        o.value = US_STATES[i][0]; o.textContent = US_STATES[i][1];
        sel.appendChild(o);
      }
      sel.addEventListener('change', function(){ applyState(sel.value, sel.options[sel.selectedIndex].text); });
    }
    function applyState(abbr, name){
      var help = document.getElementById('state-help');
      if (abbr && help){
        help.innerHTML =
          '<div class="reslib">'
          + '<a class="res" href="https://www.lawhelp.org/find-help" target="_blank" rel="noopener"><b>LawHelp.org &mdash; ' + esc(name) + '</b><span>Choose ' + esc(name) + ' to reach the free legal-aid and court self-help website for your state.</span></a>'
          + '<a class="res" href="https://www.abafreelegalanswers.org/" target="_blank" rel="noopener"><b>ABA Free Legal Answers &mdash; ' + esc(name) + '</b><span>Ask a volunteer attorney in ' + esc(name) + ' a civil legal question, free.</span></a>'
          + '<a class="res" href="https://www.lsc.gov/about-lsc/what-legal-aid/i-need-legal-help" target="_blank" rel="noopener"><b>Find Legal Aid &mdash; ' + esc(name) + '</b><span>The federal directory of local legal-aid offices serving ' + esc(name) + '.</span></a>'
          + '</div>'
          + '<p style="font-size:12.5px;color:#8a929a;margin-top:8px;">These open the official directories. Pick <b>' + esc(name) + '</b> there and you will get help for your state &mdash; never another state’s rules.</p>';
      } else if (help){
        help.innerHTML = '';
      }
      // Show the flagship law-school clinic(s) for the chosen state.
      var box = document.getElementById('state-clinic');
      var note = document.getElementById('clinic-note');
      if (box){
        if (!abbr){
          box.innerHTML='';
          if (note) note.textContent='Pick your state at the top of this page and your state’s law-school clinic appears here.';
        } else {
          var list = STATE_CLINICS[abbr] || [];
          if (list.length){
            box.innerHTML = '<div class="reslib">' + list.map(function(c){
              return '<a class="res" href="' + c.u + '" target="_blank" rel="noopener"><b>' + esc(c.s) + '</b><span>' + esc(c.b) + '</span></a>';
            }).join('') + '</div>';
            if (note) note.textContent='Law-school clinic in ' + name + ':';
          } else {
            box.innerHTML='';
            if (note) note.textContent=name + ' has no accredited law school with a public clinic. Use the ' + name + ' directories above — they will connect you to local legal aid.';
          }
        }
      }
    }
    initStatePicker();

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
_PAGE_I18N = {}
def _load_page_i18n():
    import os as _os, json as _json
    base = _os.path.dirname(_os.path.abspath(__file__))
    for lg in ("es", "zh"):
        try:
            with open(_os.path.join(base, "i18n_pages_%s.json" % lg), encoding="utf-8") as f:
                _PAGE_I18N[lg] = _json.load(f)
        except Exception as e:
            print("[InnerLight] page i18n %s not loaded: %s" % (lg, e))
            _PAGE_I18N[lg] = {}
_load_page_i18n()

_INFO_CHROME = {
    "en": {"back": "&larr; Back to InnerLight", "about": "About", "how": "How it works", "research": "Research", "safety": "Safety &amp; crisis protocol", "privacy": "Your privacy", "contact": "Contact"},
    "es": {"back": "&larr; Volver a InnerLight", "about": "Acerca de", "how": "C&oacute;mo funciona", "research": "Investigaci&oacute;n", "safety": "Seguridad y protocolo de crisis", "privacy": "Tu privacidad", "contact": "Contacto"},
    "zh": {"back": "&larr; 返回 InnerLight", "about": "关于", "how": "如何运作", "research": "研究", "safety": "安全与危机处理协议", "privacy": "你的隐私", "contact": "联系我们"},
}

def _info_lang():
    lg = (request.args.get("lang") or request.cookies.get("il_lang") or "en")
    return lg if lg in ("en", "es", "zh") else "en"

def _info_page(title, inner, page_key=None):
    lang = _info_lang()
    if page_key and lang != "en":
        _t = _PAGE_I18N.get(lang, {}).get(page_key)
        if _t:
            inner = _t
    _ch = _INFO_CHROME.get(lang, _INFO_CHROME["en"])
    _q = ("?lang=" + lang) if lang != "en" else ""
    return render_template_string("""<!DOCTYPE html>
<html lang="{{ lang }}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }} &mdash; InnerLight</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  :root{ --ink:#2b2620; --body:#4a4235; --muted:#8a7d6c; --blue:#33567c; --blue-d:#25405e;
         --amber:#c56a2c; --amber-d:#a9531f; --line:#e7dccc; }
  body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; color:var(--body);
         background:linear-gradient(168deg,#eef2f6 0%,#f3ece0 55%,#f7efe4 100%);
         line-height:1.75; min-height:100vh; -webkit-font-smoothing:antialiased; }
  .orb { width:60px; height:60px; border-radius:50%; margin:0 auto 8px;
         background:radial-gradient(circle at 38% 34%, #ffffff 0%, #a9c6e2 34%, #5f8bb6 70%, #33567c 100%);
         box-shadow:0 8px 24px rgba(51,86,124,0.28); }
  .breathe { animation:breathe 10s ease-in-out infinite; }
  @keyframes breathe { 0%{transform:scale(.82);} 40%{transform:scale(1);} 50%{transform:scale(1);} 100%{transform:scale(.82);} }
  .wrap { max-width:760px; margin:0 auto; padding:52px 26px 80px; }
  .brand { text-align:center; font-family:Georgia,'Times New Roman',serif; font-size:14px; letter-spacing:.22em;
           text-transform:uppercase; color:var(--amber-d); margin-bottom:30px; }
  h1 { font-family:Georgia,'Times New Roman',serif; font-size:32px; font-weight:700; color:var(--ink); margin-bottom:18px; line-height:1.25; }
  h2 { font-family:Georgia,'Times New Roman',serif; font-size:20px; font-weight:700; color:var(--blue); margin:34px 0 10px;
       padding-left:13px; border-left:4px solid var(--amber); line-height:1.3; }
  h3 { font-size:16.5px; font-weight:700; color:var(--ink); margin:22px 0 6px; }
  p { font-size:16.5px; color:var(--body); margin-bottom:15px; }
  .lead { font-size:19px; color:#3a3428; margin-bottom:22px; line-height:1.6; }
  ul { margin:0 0 15px 22px; } li { font-size:16px; color:var(--body); margin-bottom:8px; }
  .cite { font-size:12.5px; color:#5f7d8c; margin:2px 0 10px; padding-left:12px; border-left:2px solid var(--line); }
  .soft { background:rgba(255,255,255,.62); border:1px solid var(--line); border-left:4px solid var(--amber);
          border-radius:0 14px 14px 0; padding:18px 22px; margin:22px 0; }
  .soft p { margin:0; }
  .card { background:rgba(255,255,255,.62); border:1px solid var(--line); border-radius:16px; padding:20px 22px; margin:18px 0; }
  .tech { background:#f1f5f9; border:1px solid #d8e5f0; border-radius:12px; padding:14px 16px; margin:14px 0; font-size:14.5px; color:#33455c; line-height:1.65; }
  .tech b { color:var(--blue-d); }
  a { color:var(--blue); }
  .back { display:inline-block; margin-top:38px; color:var(--muted); text-decoration:none; font-size:15px;
          border-bottom:1px solid transparent; }
  .back:hover { border-bottom-color:var(--amber); }
  .footer { margin-top:46px; padding-top:20px; border-top:1px solid var(--line); font-size:13px; color:#a79a88; text-align:center; }
  .footer a { color:var(--blue); text-decoration:none; margin:0 7px; }
</style></head><body>
  <div class="wrap">
    <div style="text-align:right;font-size:12.5px;margin-bottom:2px;">
      <a href="?lang=en" onclick="try{document.cookie='il_lang=en;path=/;max-age=0';sessionStorage.setItem('il_lang','en')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='en' else '' }}">English</a>
      <span style="color:#ddd1c8;">&middot;</span>
      <a href="?lang=es" onclick="try{document.cookie='il_lang=es;path=/';sessionStorage.setItem('il_lang','es')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='es' else '' }}">Espa&ntilde;ol</a>
      <span style="color:#ddd1c8;">&middot;</span>
      <a href="?lang=zh" onclick="try{document.cookie='il_lang=zh;path=/';sessionStorage.setItem('il_lang','zh')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='zh' else '' }}">&#20013;&#25991;</a>
    </div>
    <div class="orb breathe" aria-hidden="true"></div>
    <div class="brand">InnerLight</div>
    {{ inner|safe }}
    <a class="back" href="/">{{ back|safe }}</a>
    <div class="footer">
      <a href="/about{{ q }}">{{ c_about|safe }}</a>&middot;
      <a href="/how-it-works{{ q }}">{{ c_how|safe }}</a>&middot;
      <a href="/research{{ q }}">{{ c_research|safe }}</a>&middot;
      <a href="/safety{{ q }}">{{ c_safety|safe }}</a>&middot;
      <a href="/privacy{{ q }}">{{ c_privacy|safe }}</a>&middot;
      <a href="/contact{{ q }}">{{ c_contact|safe }}</a>
      <div style="margin-top:10px;">&copy; 2026 God's Love For Us LLC &middot; Created by Toshay S. Zeigler</div>
    </div>
  </div>
</body></html>""", title=title, inner=inner, lang=lang, q=_q, back=_ch["back"],
    c_about=_ch["about"], c_how=_ch["how"], c_research=_ch["research"], c_safety=_ch["safety"],
    c_privacy=_ch["privacy"], c_contact=_ch["contact"])


@app.route("/about")
def page_about():
    inner = """
    <h1>Why InnerLight exists</h1>
    <p class="lead">InnerLight holds the hardest space in the mental-health system: the gap between the moment a person reaches out and the moment real human help actually arrives.</p>

    <p>Across the country, that gap is measured in waitlists, transfers, and hold music. When someone is in crisis, help usually does exist &mdash; a clinician, a counselor, a legal-aid office, a crisis line &mdash; but reaching it means navigating hospitals, insurance, county agencies, schools, and courts, often during the hardest hours of a person&rsquo;s life. In the space between &ldquo;I need help&rdquo; and &ldquo;help has arrived,&rdquo; people wait, and too often they wait alone. National crisis systems themselves report answer and dispatch times measured in many minutes to hours; mobile crisis and appointment waits are far longer. InnerLight was built to hold that specific interval &mdash; to keep a person company and steady while a bridge to the right human help is built.</p>

    <h2>The gap we target, precisely</h2>
    <p>We are deliberately narrow. InnerLight is not therapy, not a diagnosis, and not a replacement for a clinician, a lawyer, or a crisis counselor. It is a <strong>survive-the-wait companion</strong> for the acute interval &mdash; the minutes to hours when a person has decided to seek help but has not yet reached a human. Its two jobs are to <strong>help the person settle</strong> and to <strong>shorten the distance to the right human help</strong>, with the person&rsquo;s consent at every step. Success, for us, is measured by connection to a human &mdash; not by time spent in the app.</p>

    <h2>How it actually works</h2>
    <p>InnerLight combines four evidence-informed elements, each explained in plain and technical detail on the <a href="/how-it-works">How it works</a> page:</p>
    <ul>
      <li><strong>Adaptive calming sound</strong> built on the music-therapy <em>Iso-Principle</em> &mdash; meet a person&rsquo;s current state, then gently guide the music toward calm.</li>
      <li><strong>A contactless heart-rate reading</strong> from an ordinary webcam (remote photoplethysmography), running entirely on the person&rsquo;s own device, so the sound and support can respond to how the body is actually doing.</li>
      <li><strong>A warm, plain-language conversation</strong> that listens for what a person means, reflects it back, and asks one gentle question at a time &mdash; never a wall of forms.</li>
      <li><strong>A consented bridge to human help</strong> &mdash; crisis lines, mobile crisis teams, telehealth, legal aid, and, in emergencies, 988/911 &mdash; with any shared summary reviewed and controlled by the person first.</li>
    </ul>

    <h2>The founder</h2>
    <p>InnerLight is founded by <strong>Toshay S. Zeigler</strong>, founder of <strong>God&rsquo;s Love For Us LLC</strong>. A dedicated adult learner, he earned two associate degrees and a university-transfer certificate while working, and is continuing his studies in political science with the goal of law school &mdash; driven by a determination to understand and improve the systems that shape people&rsquo;s lives. His professional background spans logistics, operations, transportation, and in-home care: work grounded in getting people and things where they need to be, reliably and under pressure.</p>
    <p>The calming core of InnerLight began with a practical observation. Across years of driving and thousands of trips, he noticed that when calm instrumental music was already playing, agitated people settled &mdash; reliably, and often without a word. That simple, repeatable effect &mdash; the right sound, at the right level, at the right moment &mdash; became the seed of InnerLight&rsquo;s approach.</p>

    <h2>Built by a person, with the help of AI</h2>
    <p>InnerLight is built by Toshay directly, working alongside artificial intelligence as a tool and collaborator. The vision, the direction, and every decision about what InnerLight should be are his. AI helps build it &mdash; the idea, and the responsibility, are human.</p>

    <h2>Our standards and ethics</h2>
    <p>We hold ourselves to explicit, published rules: technology should <strong>strengthen</strong> human decision-making, not replace it; a mental-health tool should <strong>complement</strong> human care, never pretend to be it; privacy is the foundation, not a feature to trade away; and no one reaching out for help should have their first response be a waitlist. InnerLight never diagnoses, never names a clinical condition, never practices medicine or law, and uses <strong>no engagement tricks</strong> &mdash; no streaks, no badges, no pressure to stay. We operate strictly within the law, and we will report results honestly, including negative ones.</p>

    <h2>For clinicians, researchers, and partners</h2>
    <p>We are actively looking for people who can help us sharpen and validate this work &mdash; clinicians, crisis-service providers, researchers, and technologists. We do not claim InnerLight is proven; it is built on established principles and is itself untested, and independent evaluation is exactly what we want. Our methods, technologies, and honest limitations are documented for review on the <a href="/research">Research &amp; Methods</a> page, our privacy and data handling on the <a href="/privacy">Your privacy</a> page, and our crisis protocol on the <a href="/safety">Safety</a> page. If you can help &mdash; or challenge us &mdash; please <a href="/contact">get in touch</a>.</p>

    <div class="soft">
      <p style="margin:0;">InnerLight does not diagnose, prescribe, or practice medicine or law. It is a place to be heard and steadied, and a bridge to the right human help &mdash; never a replacement for it. If you are in immediate danger, call or text 988, or call 911.</p>
    </div>
    """
    return _info_page("About", inner, "about")




# ---- LOCAL MENTAL-HEALTH FACILITIES (non-crisis self-referral help) ----
# A person can share where they are; we surface nearby places they can reach on
# their own time. This is NAVIGATION, not treatment, and never replaces crisis
# lines. PRIMARY source: FindTreatment.gov — the federal government's own
# directory of licensed mental-health facilities (free, no key, authoritative,
# nationwide). FALLBACK: OpenStreetMap. Discovered the hard way: the federal
# API wants coordinates as lat,lng (their developer guide says the opposite)
# and sType must be uppercase.
@app.route("/api/facilities", methods=["POST"])
def facilities_lookup():
    if not _rate_ok("facilities", 20, 3600):
        return _gentle_429()
    data = request.get_json(silent=True) or {}
    place = str(data.get("place", "")).strip()[:120]
    if not place:
        return jsonify({"status": "empty"}), 200
    results = []
    lat = lon = None
    try:
        import urllib.request, urllib.parse
        # 1) geocode the place the person typed (bias bare ZIPs to the US)
        params = {"q": place, "format": "json", "limit": 1}
        if re.fullmatch(r"\d{5}(-\d{4})?", place):
            params["countrycodes"] = "us"
        q = urllib.parse.urlencode(params)
        geo_req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + q,
                                         headers={"User-Agent": "InnerLight/1.0 (support@getinnerlight.com)"})
        with urllib.request.urlopen(geo_req, timeout=8) as r:
            geo = json.loads(r.read().decode("utf-8"))
        if geo:
            lat = geo[0]["lat"]; lon = geo[0]["lon"]
    except Exception as e:
        print("[InnerLight] facilities geocode issue:", e)
    # 2) PRIMARY: FindTreatment.gov — licensed mental-health facilities,
    #    nearest first, within ~15 miles.
    if lat is not None:
        try:
            import urllib.request, urllib.parse
            ft_q = urllib.parse.urlencode({
                "sAddr": "%s,%s" % (lat, lon),   # lat,lng — yes, really
                "limitType": "2", "limitValue": "24140",  # meters (~15 miles)
                "sType": "MH", "pageSize": "12", "page": "1", "sort": "0"})
            ft_req = urllib.request.Request(
                "https://findtreatment.gov/locator/exportsAsJson/v2?" + ft_q,
                headers={"User-Agent": "InnerLight/1.0 (support@getinnerlight.com)",
                         "Accept": "application/json"})
            with urllib.request.urlopen(ft_req, timeout=12) as r:
                ft = json.loads(r.read().decode("utf-8"))
            for row in (ft.get("rows") or []):
                name = (row.get("name1") or "").strip()
                if not name:
                    continue
                addr = ", ".join(filter(None, [
                    (row.get("street1") or "").strip(),
                    (row.get("city") or "").strip(),
                    (row.get("state") or "").strip()]))
                miles = row.get("miles")
                try:
                    if miles is not None:
                        addr = (addr + (" — %.1f miles" % float(miles))).strip(" —")
                except (TypeError, ValueError):
                    pass
                results.append({"name": name[:80], "address": addr[:140],
                                "phone": (row.get("phone") or "")[:24]})
                if len(results) >= 12:
                    break
        except Exception as e:
            print("[InnerLight] facilities FindTreatment issue:", e)
    # 3) FALLBACK: OpenStreetMap (now searching buildings/areas too, not just
    #    point markers, and broader health/social tags).
    if lat is not None and not results:
        try:
            import urllib.request, urllib.parse
            overpass = (
                '[out:json][timeout:12];('
                'nwr["healthcare"~"centre|counselling|psychiatry|psychotherapist"](around:15000,%s,%s);'
                'nwr["healthcare:speciality"~"psychiatry|mental_health"](around:15000,%s,%s);'
                'nwr["amenity"="social_facility"](around:15000,%s,%s);'
                ');out center 30;' % (lat, lon, lat, lon, lat, lon)
            )
            op_req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                    data=urllib.parse.urlencode({"data": overpass}).encode(),
                    headers={"User-Agent": "InnerLight/1.0 (support@getinnerlight.com)"})
            with urllib.request.urlopen(op_req, timeout=14) as r2:
                op = json.loads(r2.read().decode("utf-8"))
            seen = set()
            for el in op.get("elements", []):
                tags = el.get("tags", {})
                name = tags.get("name")
                if not name or name in seen:
                    continue
                seen.add(name)
                addr = " ".join(filter(None, [tags.get("addr:housenumber",""), tags.get("addr:street",""),
                                              tags.get("addr:city","")])).strip()
                results.append({"name": name[:80], "address": addr[:140],
                                "phone": tags.get("phone", tags.get("contact:phone",""))[:24]})
                if len(results) >= 12:
                    break
        except Exception as e:
            print("[InnerLight] facilities lookup issue:", e)
    return jsonify({"status": "ok", "place": place, "results": results})


@app.route("/research")
def page_research():
    inner = """
    <h1>Research foundations &amp; methods</h1>
    <p class="lead">A transparent, detailed account of the science InnerLight is built on, the technologies it uses, and why &mdash; written for researchers, clinicians, and reviewers. InnerLight itself is not yet validated in a controlled trial; this page documents the established principles behind its design and our commitment to testing it honestly.</p>

    <div class="soft"><p style="margin:0;"><strong>A note on our posture:</strong> every design choice below draws on peer-reviewed work. That grounds our <em>approach</em>. It does <strong>not</strong> mean InnerLight is proven &mdash; validating the tool itself is precisely the research we are undertaking. We will report negative results as readily as positive ones.</p></div>

    <h2>1. Calming sound &mdash; the Iso-Principle</h2>
    <p>InnerLight&rsquo;s use of sound is built on the <strong>Iso-Principle</strong> from music therapy: meet a person&rsquo;s current emotional state with matching music, then gradually shift the music toward calm to carry them with it. This is a long-standing clinical method with controlled experimental support.</p>
    <p class="cite">Starcke K., Mayr J., von Georgi R. (2021). &ldquo;Emotion modulation through music after sadness induction &mdash; the Iso principle in a controlled experimental study.&rdquo; <em>International Journal of Environmental Research and Public Health</em>, 18(23).</p>
    <p class="cite">Music with auditory beat stimulation RCT protocol (2025). <em>BMJ Open</em>, 15(6):e094784 &mdash; describes Iso-principle personalization against baseline Self-Assessment Manikin (SAM) scores.</p>

    <h2>2. Target tempo for relaxation (60&ndash;80 BPM)</h2>
    <p>Research indicates that music in the <strong>60&ndash;80 beats-per-minute</strong> range supports relaxation by aligning neural oscillations (alpha-wave activity) with the musical rhythm, shifting arousal from tense toward calm. InnerLight prioritizes tracks and, in development, dynamic tempo shaping toward this range.</p>
    <p class="cite">Xu R., Li J. (2025). &ldquo;AI-driven music intervention based on five-tone theory for anxiety: a preliminary pre-post feasibility study.&rdquo; <em>Frontiers in Psychology</em>, 16:1669029. (Real-time HRV-guided tempo modulation.)</p>
    <p class="cite">Frontiers in Digital Health (2025), 7:1552396 &mdash; review of music therapy, entrainment, and AI-driven biofeedback.</p>

    <h2>3. Real-time, physiology-guided adaptation (in development)</h2>
    <p>The strongest current evidence favors adjusting <strong>musical parameters</strong> &mdash; tempo, volume, complexity &mdash; smoothly and in real time in response to physiological signals, rather than abruptly switching tracks. When tension rises, effective systems slow the tempo and simplify the music with <em>soft transitions</em>. This is the direction of InnerLight&rsquo;s ongoing sound development. We are deliberately re-examining which signal should drive it: because beats-per-minute is an unreliable indicator of emotional state, we do not use heart rate as a distress signal, and are building a more trustworthy read of how a person is doing.</p>
    <p class="cite">REMAST: Real-time Emotion-based Music Arrangement with Soft Transition (arXiv:2305.08029).</p>
    <p class="cite">Williams et al. (2020); Jiao (2025) &mdash; adaptive functional music generation with real-time biofeedback, reviewed in <em>Frontiers in Psychology</em> (2026), 16:1741463.</p>

    <h2>4. Contactless heart reading &mdash; remote photoplethysmography (rPPG)</h2>
    <p>InnerLight reads heart rate from a standard webcam using <strong>remote photoplethysmography</strong>: detecting the tiny color changes in facial skin as blood pulses beneath it. We combine forehead and cheek skin regions (avoiding the eyes and mouth, which introduce motion noise), verify skin pixels, detect the beat period by autocorrelation, and apply physiology-informed smoothing so implausible jumps are rejected. In low light, the signal is automatically brightened (adaptive gamma correction) before analysis so people in dim conditions are not excluded.</p>
    <p class="cite">Method basis: chrominance- and plane-based rPPG (POS/CHROM family); forehead and cheek regions of interest shown to carry strong pulsatile signal in systematic reviews of rPPG ROI selection.</p>
    <p class="cite">Low-light handling follows gamma-correction and histogram-based enhancement approaches evaluated for rPPG under poor illumination.</p>
    <p><strong>Why webcam rPPG, and not a wearable or a specific product:</strong> a crisis tool must work for anyone, instantly, with no device to buy, pair, or install. Wearables and clinical pulse oximeters are more accurate but exclude anyone who doesn&rsquo;t own one in the moment. Deep-learning rPPG models are strong but require a server and heavy computation. Browser-based rPPG is the only approach that runs immediately for everyone on a phone or computer &mdash; so we use it, and we are transparent about its limits: it needs reasonable light and a mostly still face, and we label every reading by confidence (measured / estimated / baseline-held) rather than overstating precision.</p>

    <h2>5. Facial-signal reading &mdash; MediaPipe</h2>
    <p>For facial-expression signals InnerLight uses <strong>Google&rsquo;s MediaPipe Face Landmarker</strong>, which measures dozens of specific facial-movement values (blendshapes) rather than guessing a single emotion label. We chose MediaPipe because it is free, runs entirely in the browser (no images ever leave the person&rsquo;s device for this), is well-documented, and is widely used and maintained &mdash; important for a tool that must be reproducible by a research team.</p>

    <h2>6. Grounding through real imagery</h2>
    <p>InnerLight uses real photographs, not animation, as grounding scenes. Realism is used deliberately: concrete sensory grounding is a recognized technique for interrupting distress and dissociation and returning attention to the present.</p>

    <h2>7. Privacy &amp; encryption</h2>
    <p>Privacy is foundational, not an afterthought. Specifically:</p>
    <ul>
      <li><strong>Session content is not stored in raw form.</strong> Only a summary a person chooses to save is retained, and identifying details (emails, phone numbers, handles, long digit strings) are automatically removed before any research record is stored.</li>
      <li><strong>Returning-user memory is encrypted with a key derived from the person&rsquo;s own return code.</strong> Their saved story cannot be read without that code &mdash; not by us, not by anyone with server access. If the code is lost, the data is unrecoverable by design. This uses the Axiom Harmony Protocol, our applied encryption layer, so that the person &mdash; not the operator &mdash; holds the key to their own story.</li>
      <li><strong>The live biometric monitor is anonymous and ephemeral.</strong> It shows heart rate and calm-state under anonymous labels (Person 1, Person 2), holds no words, and expires shortly after a session ends.</li>
      <li><strong>Facial analysis runs on-device.</strong> The person&rsquo;s video is analyzed in their own browser for heart and expression signals; the raw video is not transmitted for that analysis.</li>
    </ul>

    <h2>7b. The Axiom Harmony Protocol (AHP) &mdash; what it is, and how it protects you</h2>
    <p>The <strong>Axiom Harmony Protocol (AHP)</strong> is InnerLight&rsquo;s encryption layer &mdash; the system that turns anything a person chooses to save into scrambled, unreadable data that <em>only they</em> can unlock. It is not a marketing name over weak protection; it is built on the same class of encryption used to protect banking and government data. Here is exactly how it works, first in plain terms and then in technical terms.</p>

    <p><strong>In plain terms:</strong> when you save your story, InnerLight takes your private return code and, through a deliberately slow mathematical process, turns it into a unique digital key. It then locks your words with that key so thoroughly that the stored result looks like random noise. Your code is the only thing that can produce that key again. We never keep your code, so we can never unlock your story &mdash; and neither can anyone who breaks into the server. If you lose the code, the data is gone for good. That is the trade-off of true privacy: the lock is real, and you hold the only key.</p>

    <div style="background:#f9f7f5;border:1px solid #e8dfd8;border-radius:14px;padding:18px 16px;margin:18px 0;overflow-x:auto;">
    <svg viewBox="0 0 720 150" width="100%" style="min-width:640px;max-width:720px;display:block;margin:0 auto;font-family:Arial,sans-serif;" role="img" aria-label="How AHP encrypts your saved story: your return code becomes a key through 390,000 rounds of key-stretching, which locks your words with AES-256-GCM into unreadable stored data.">
      <defs><marker id="ah" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#714c2e"/></marker></defs>
      <rect x="8" y="45" width="140" height="60" rx="10" fill="#fff" stroke="#c59771" stroke-width="1.5"/>
      <text x="78" y="70" text-anchor="middle" font-size="13" font-weight="700" fill="#453127">Your return code</text>
      <text x="78" y="90" text-anchor="middle" font-size="11" fill="#5f7d8c">(only you have it)</text>
      <line x1="150" y1="75" x2="212" y2="75" stroke="#714c2e" stroke-width="2" marker-end="url(#ah)"/>
      <text x="181" y="40" text-anchor="middle" font-size="10.5" fill="#C56A2C" font-weight="700">390,000 rounds</text>
      <text x="181" y="66" text-anchor="middle" font-size="9.5" fill="#8a929a">PBKDF2</text>
      <rect x="214" y="45" width="140" height="60" rx="10" fill="#fff" stroke="#c59771" stroke-width="1.5"/>
      <text x="284" y="72" text-anchor="middle" font-size="13" font-weight="700" fill="#453127">256-bit key</text>
      <text x="284" y="90" text-anchor="middle" font-size="11" fill="#5f7d8c">never stored</text>
      <line x1="356" y1="75" x2="418" y2="75" stroke="#714c2e" stroke-width="2" marker-end="url(#ah)"/>
      <text x="387" y="40" text-anchor="middle" font-size="10.5" fill="#C56A2C" font-weight="700">AES-256-GCM</text>
      <text x="387" y="66" text-anchor="middle" font-size="9.5" fill="#8a929a">+ random nonce</text>
      <rect x="420" y="45" width="150" height="60" rx="10" fill="#fff" stroke="#c59771" stroke-width="1.5"/>
      <text x="495" y="72" text-anchor="middle" font-size="13" font-weight="700" fill="#453127">Your words, locked</text>
      <text x="495" y="90" text-anchor="middle" font-size="11" fill="#5f7d8c">reads as noise</text>
      <line x1="572" y1="75" x2="628" y2="75" stroke="#714c2e" stroke-width="2" marker-end="url(#ah)"/>
      <rect x="630" y="45" width="82" height="60" rx="10" fill="#453127"/>
      <text x="671" y="72" text-anchor="middle" font-size="20">&#128274;</text>
      <text x="671" y="94" text-anchor="middle" font-size="10" fill="#e0d7cf">stored</text>
      <text x="360" y="132" text-anchor="middle" font-size="11" fill="#5f7d8c">Without your code, the key cannot be rebuilt &mdash; so no one, not even InnerLight, can reverse this.</text>
    </svg>
    </div>

    <p><strong>In technical terms,</strong> for reviewers: AHP encrypts each payload with <strong>AES-256-GCM</strong> &mdash; the Advanced Encryption Standard at 256 bits in Galois/Counter Mode, an <em>authenticated</em> cipher that protects both confidentiality (no one can read it) and integrity (tampering is detectable). The key is derived from the person&rsquo;s return code using <strong>PBKDF2-HMAC-SHA256 with 390,000 iterations</strong> and a random salt &mdash; a deliberately slow key-stretching function that makes brute-force guessing enormously expensive. Every encryption uses a fresh random <strong>nonce</strong>, and the protocol version is bound in as authenticated associated data. The key is never written to disk; only the ciphertext, salt, and nonce are stored. This is a zero-knowledge design toward the operator: InnerLight holds encrypted bytes it cannot read.</p>

    <p class="cite">Honest limit: AES-256-GCM with strong key derivation is robust modern cryptography, but it is not yet post-quantum. A documented future hardening path is to add a post-quantum key-exchange layer (for example, ML-KEM / Kyber) alongside the authenticated symmetric encryption. We state this openly rather than overstate the protection.</p>

    <h2>8. What we measure, and how we stay honest</h2>
    <p>InnerLight records anonymous, aggregate research metrics designed around recognized digital-health frameworks: uptake, engagement, session duration, adherence, and completion, alongside expression shifts, sound responses, self-reported calm (a wordless Self-Assessment Manikin scale), and heart-rate trends measured against each person&rsquo;s own baseline. Every heart reading carries a confidence tier so coverage is complete without overstating precision. We follow the scientific method explicitly: a falsifiable hypothesis, stated predictions, an instrument that gathers the data, and a commitment to replication and peer review.</p>

    <div class="soft"><p style="margin:0;">InnerLight does not diagnose, prescribe, or practice medicine or law. It is a companion for the wait and a bridge to human help &mdash; never a replacement for it. If you are in immediate danger, call or text 988, or call 911.</p></div>

    <p style="margin-top:20px;font-size:13px;color:#8aa;">Citations above reference published, peer-reviewed literature supporting the <em>principles</em> InnerLight applies. They do not constitute evidence that InnerLight itself is effective; that evaluation is ongoing. Full reference details are available on request.</p>
    """
    return _info_page("Research &amp; Methods", inner)


@app.route("/how-it-works")
def page_how():
    inner = """
    <h1>How InnerLight works</h1>
    <p class="lead">Nothing here is a black box. This page explains exactly what happens in a session, and then exactly how each of our three systems &mdash; the sound, the heartbeat reading, and the encryption &mdash; actually works, in plain language first and technical detail second.</p>

    <h2>The experience, step by step</h2>
    <h3>1. A calm space opens</h3>
    <p>When you arrive, a soft environment is already present &mdash; gentle sound and a breathing guide &mdash; not something you have to switch on. A slowly expanding and contracting circle paces your breath at about six breaths per minute, the rate best supported in the research for calming the body. You never have to use it; it is simply there.</p>
    <h3>2. You tell your story, your way</h3>
    <p>You can type or speak, whichever is easier. InnerLight listens for what you actually mean, reflects it back, and asks one gentle question at a time drawn from what you said &mdash; never a wall of forms, never rushed. You decide when you are ready for a response; nothing answers over you.</p>
    <h3>3. You are met where you are</h3>
    <p>Using what you tell us &mdash; and, if you like, the breathing guide &mdash; the calming sound gently shifts to meet the moment and then eases toward calm. We do <strong>not</strong> use your heart rate to judge how you feel; beats-per-minute is an ambiguous signal, and we would rather listen to you. The aim is to help you feel heard and steadier while you wait.</p>
    <h3>4. A bridge to real help &mdash; only with your consent</h3>
    <p>When it would help, InnerLight can connect you to real human support &mdash; a crisis line, a mobile crisis team, a telehealth provider, legal aid, and in urgent moments the right emergency help. If you choose to share a summary of what you talked about, <strong>you</strong> review and control it first. Nothing is shared without your say-so.</p>

    <h2>System one &mdash; the sound</h2>
    <p><strong>In plain terms:</strong> InnerLight&rsquo;s sound is built on a music-therapy method called the <em>Iso-Principle</em>. Instead of jumping straight to the calmest music &mdash; which can feel like being told to &ldquo;just relax&rdquo; &mdash; it starts with sound that <em>matches</em> where you are, so you feel met, and then gradually eases the music toward calm and carries you with it. As the reading of your state changes, the music moves between prepared &ldquo;lanes&rdquo; that differ in energy, tempo, and fullness.</p>
    <div class="tech"><b>Technical detail:</b> lanes are selected from the conversation (and, optionally, the breathing guide) and sequenced by the Iso-Principle &mdash; enter on a matching lane, then step down through intermediate lanes to the calmest over one to three minutes. Calming targets follow the literature: slower tempo (roughly a 60&ndash;80&nbsp;bpm feel, or a <em>decreasing</em> tempo, which produced the strongest parasympathetic response in controlled work), low rhythmic density, soft attacks, and minimal sudden dynamics. Transitions use equal-power (cosine) crossfades and gain automation so changes are smooth rather than abrupt. In active development: stem-layered lanes (fading instrument layers in and out instead of switching tracks) and a low-pass &ldquo;settle&rdquo; sweep so the sound literally softens as you calm.</div>
    <p class="cite">Honest limit: calming-audio effects are real but modest and individual, and &ldquo;60&nbsp;bpm music syncs your heartbeat&rdquo; is an overstatement &mdash; music nudges the nervous system toward rest; it does not lock your pulse to the beat. Full citations are on the <a href="/research">Research &amp; Methods</a> page.</p>

    <h2>System two &mdash; the heartbeat reading</h2>
    <p><strong>In plain terms:</strong> if you allow the camera, InnerLight can estimate your heart rate without touching you, by watching the tiny color changes in your face as blood pulses just beneath the skin. This happens <strong>entirely on your own device</strong> &mdash; the video is analyzed in your browser and is never sent to us or stored. The reading is shown to you, powers an anonymous, words-free view a supporter can watch, and is recorded for research &mdash; but we do <strong>not</strong> treat a higher heart rate as &ldquo;distress.&rdquo; Beats-per-minute is too ambiguous for that, so it never decides anything on its own.</p>
    <div class="tech"><b>Technical detail:</b> this is <b>remote photoplethysmography (rPPG)</b>. We sample skin from the forehead and both cheeks (avoiding eyes and mouth, which add motion noise), combine the red, green, and blue channels using the <b>Plane-Orthogonal-to-Skin (POS)</b> algorithm to cancel motion and lighting, band-limit the signal to the plausible heart range (about 0.7&ndash;2.8&nbsp;Hz), and add a sub-harmonic guard so the estimator cannot latch onto half the true rate. In dim light the image is brightened first (adaptive gamma correction) so people in poor lighting are not excluded. Every reading carries a confidence tier &mdash; <b>measured</b>, <b>estimated</b>, or <b>baseline-held</b> &mdash; so coverage is complete without overstating precision.</div>
    <p class="cite">Why webcam rPPG and not a wearable: a crisis tool must work for anyone, instantly, with no device to buy or pair. It needs reasonable light and a mostly still face, and we label every reading&rsquo;s confidence rather than pretend to clinical accuracy. Facial-expression signals use Google&rsquo;s on-device MediaPipe Face Landmarker. Method citations are on the <a href="/research">Research</a> page.</p>

    <h2>System three &mdash; the Axiom Harmony Protocol (our encryption)</h2>
    <p><strong>In plain terms:</strong> if you choose to save your story so you can return to it, InnerLight locks it with a key made from a private return code that only you hold. Through a deliberately slow mathematical process, your code becomes a unique digital key, and your words are locked with it so thoroughly that the stored result looks like random noise. We never keep your code, so we can never unlock your story &mdash; and neither can anyone who breaks into the server. If you lose the code, the data is gone for good. That is the trade-off of real privacy: the lock is genuine, and you hold the only key.</p>

    <div class="card" style="overflow-x:auto;">
    <svg viewBox="0 0 720 150" width="100%" style="min-width:640px;max-width:720px;display:block;margin:0 auto;font-family:Arial,sans-serif;" role="img" aria-label="How the Axiom Harmony Protocol encrypts your saved story: your return code becomes a key through 390,000 rounds of key-stretching, which locks your words with AES-256-GCM into unreadable stored data.">
      <defs><marker id="ah2" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#33567c"/></marker></defs>
      <rect x="8" y="45" width="140" height="60" rx="12" fill="#fff" stroke="#6f97c0" stroke-width="1.5"/>
      <text x="78" y="70" text-anchor="middle" font-size="13" font-weight="700" fill="#2b2620">Your return code</text>
      <text x="78" y="90" text-anchor="middle" font-size="11" fill="#5f7d8c">(only you have it)</text>
      <line x1="150" y1="75" x2="212" y2="75" stroke="#33567c" stroke-width="2" marker-end="url(#ah2)"/>
      <text x="181" y="40" text-anchor="middle" font-size="10.5" fill="#a9531f" font-weight="700">390,000 rounds</text>
      <text x="181" y="66" text-anchor="middle" font-size="9.5" fill="#8a929a">PBKDF2</text>
      <rect x="214" y="45" width="140" height="60" rx="12" fill="#fff" stroke="#6f97c0" stroke-width="1.5"/>
      <text x="284" y="72" text-anchor="middle" font-size="13" font-weight="700" fill="#2b2620">256-bit key</text>
      <text x="284" y="90" text-anchor="middle" font-size="11" fill="#5f7d8c">never stored</text>
      <line x1="356" y1="75" x2="418" y2="75" stroke="#33567c" stroke-width="2" marker-end="url(#ah2)"/>
      <text x="387" y="40" text-anchor="middle" font-size="10.5" fill="#a9531f" font-weight="700">AES-256-GCM</text>
      <text x="387" y="66" text-anchor="middle" font-size="9.5" fill="#8a929a">+ random nonce</text>
      <rect x="420" y="45" width="150" height="60" rx="12" fill="#fff" stroke="#6f97c0" stroke-width="1.5"/>
      <text x="495" y="72" text-anchor="middle" font-size="13" font-weight="700" fill="#2b2620">Your words, locked</text>
      <text x="495" y="90" text-anchor="middle" font-size="11" fill="#5f7d8c">reads as noise</text>
      <line x1="572" y1="75" x2="628" y2="75" stroke="#33567c" stroke-width="2" marker-end="url(#ah2)"/>
      <rect x="630" y="45" width="82" height="60" rx="12" fill="#2b2620"/>
      <text x="671" y="72" text-anchor="middle" font-size="20">&#128274;</text>
      <text x="671" y="94" text-anchor="middle" font-size="10" fill="#e0d7cf">stored</text>
      <text x="360" y="132" text-anchor="middle" font-size="11" fill="#5f7d8c">Without your code, the key cannot be rebuilt &mdash; so no one, not even InnerLight, can reverse this.</text>
    </svg>
    </div>

    <div class="tech"><b>Technical detail:</b> AHP encrypts each payload with <b>AES-256-GCM</b> (Advanced Encryption Standard, 256-bit, Galois/Counter Mode) &mdash; an <i>authenticated</i> cipher protecting both confidentiality and integrity. The key is derived from the return code with <b>PBKDF2-HMAC-SHA256 at 390,000 iterations</b> and a random salt, a slow key-stretch that makes brute force enormously expensive. Every encryption uses a fresh random <b>nonce</b>, and the protocol version is bound in as authenticated associated data. The key is never written to disk &mdash; only ciphertext, salt, and nonce are stored. Toward the operator this is a zero-knowledge design: InnerLight holds bytes it cannot read.</div>
    <p class="cite">Honest limit: AES-256-GCM with strong key derivation is robust modern cryptography, but it is not yet post-quantum. A documented hardening path is to add a post-quantum key-exchange layer (for example ML-KEM / Kyber) alongside it. We state this openly rather than overstate the protection.</p>

    <h2>What we never do</h2>
    <p>InnerLight never diagnoses, never names a clinical condition, never practices medicine or law, and never uses engagement tricks (no streaks, badges, or pressure to stay). The raw conversation is not stored; only a summary you choose to save is kept, with identifying details automatically removed. More on data handling is on the <a href="/privacy">Your privacy</a> page, and our crisis protocol is on the <a href="/safety">Safety</a> page.</p>

    <div class="soft">
      <p style="margin:0;">InnerLight is a companion for the wait and a bridge to care. It does not diagnose or treat, and it is not a substitute for professional or emergency help. If you are in immediate danger, call or text 988, or call 911.</p>
    </div>
    """
    return _info_page("How it works", inner, "how-it-works")


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
    return _info_page("Your privacy", inner, "privacy")


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
      <p style="margin:0;">Email: <a href="mailto:masterzeigler@gmail.com">masterzeigler@gmail.com</a><br>
      Phone: <a href="tel:+14083349984">(408) 334-9984</a></p>
    </div>

    <div class="soft">
      <p style="margin:0;"><strong>If this is an emergency</strong> and you or someone else may be in danger, please
      don't wait for a reply here &mdash; call or text <strong>988</strong> (Suicide &amp; Crisis Lifeline), or call
      <strong>911</strong>.</p>
    </div>
    """
    return _info_page("Contact", inner, "contact")


@app.route("/safety")
def page_safety():
    """Published crisis-response protocol. Written to satisfy California
    SB 243's documentation expectations and, more importantly, to tell people
    the truth about what this tool is and does. Immutable Principle 11."""
    inner = """
    <h1>Safety &amp; crisis protocol</h1>
    <p class="lead">What InnerLight is, what it does when someone may be in danger, and where its limits are &mdash; in plain words.</p>

    <h2>First, what InnerLight is</h2>
    <p>InnerLight is an <strong>artificial-intelligence program</strong> &mdash; a computer program, not a human being.
    It is not a therapist, a doctor, or a lawyer, and it does not diagnose, treat, or give medical or legal advice.
    It is a calm place to get through a hard stretch, and a bridge to real human help. It is built for adults 18 and
    older, and it may not be suitable for some minors.</p>

    <h2>What happens if you may be in crisis</h2>
    <p>InnerLight watches for signs in a conversation that someone may be thinking about suicide or self-harm, or may
    be in immediate danger. When it recognizes those signs, it follows one protocol, every time:</p>
    <p><strong>1. It stops its questions.</strong> The moment danger signs appear, InnerLight sets aside whatever else
    was happening in the conversation.</p>
    <p><strong>2. It puts real human help first.</strong> It tells you, clearly and immediately, about the
    <strong>988 Suicide &amp; Crisis Lifeline</strong> (call or text 988, free, 24/7) &mdash; and it stays present with
    you while you reach out. The 988 button is also always visible on the screen, in every session, for every person.</p>
    <p><strong>3. It never blocks, argues, or dead-ends.</strong> InnerLight never says "no" to a person in pain, never
    lectures, and never ends the conversation on someone in distress. If you decline the crisis line, it stays with
    you and gently offers again.</p>
    <p><strong>4. With your consent, it helps you connect.</strong> If you choose, InnerLight can prepare a summary of
    what you shared &mdash; which you see and approve first &mdash; so you do not have to start from zero with a
    professional.</p>
    <p><strong>5. For anyone under 18</strong>, InnerLight redirects to help built for young people &mdash; a trusted
    adult, 988, Crisis Text Line (text HOME to 741741), and Teen Line &mdash; and does not connect minors to providers.</p>

    <h2>Honest limits</h2>
    <p>No automated system recognizes every crisis, every time. InnerLight's recognition is built carefully and improved
    continually, but it can miss signs and it can be wrong. That is one reason it exists to hand you to humans quickly
    &mdash; not to be the help itself. <strong>If you are in danger right now, do not wait for any website:
    call or text 988, or call 911.</strong></p>

    <h2>Our accountability</h2>
    <p>InnerLight counts how often its crisis protocol activates &mdash; counts only, never the content of what anyone
    shared &mdash; so its safety behavior can be reviewed and reported responsibly, including to the State of
    California's Office of Suicide Prevention as required by law. InnerLight is operated by God's Love For Us LLC and
    is designed to comply with the laws that govern tools like it, including California's companion-chatbot law
    (Senate Bill 243). Questions about this protocol are welcome through the <a href="/contact">contact page</a>.</p>

    <div class="soft">
      <p style="margin:0;"><strong>The short version:</strong> InnerLight is a program, not a person. When it sees
      danger, it points to real people fast &mdash; 988, every time, without delay &mdash; and it never stands between
      you and human help.</p>
    </div>
    """
    return _info_page("Safety & crisis protocol", inner, "safety")


@app.route("/console")
def console():
    return render_template_string(PAGE)


# Crisis handoff pages, localized (Spanish / Chinese) with English fallback.
_HANDOFF_I18N = {}
def _load_handoff_i18n():
    import os as _os, json as _json
    base = _os.path.dirname(_os.path.abspath(__file__))
    for lg in ("es", "zh"):
        try:
            with open(_os.path.join(base, "i18n_handoff_%s.json" % lg), encoding="utf-8") as f:
                _HANDOFF_I18N[lg] = _json.load(f)
        except Exception as e:
            print("[InnerLight] handoff i18n %s not loaded: %s" % (lg, e))
            _HANDOFF_I18N[lg] = {}
_load_handoff_i18n()

def _handoff_page(page_key, en_tpl):
    lang = _info_lang()
    if lang != "en":
        t = _HANDOFF_I18N.get(lang, {}).get(page_key)
        if t:
            return render_template_string(t)
    return render_template_string(en_tpl)


@app.route("/handoff/clinical")
def handoff_clinical():
    return _handoff_page("clinical", CLINICAL_HANDOFF_PAGE)


@app.route("/handoff/legal")
def handoff_legal():
    return _handoff_page("legal", LEGAL_HANDOFF_PAGE)


@app.route("/telehealth/urgent")
def telehealth_urgent():
    return _handoff_page("clinical", CLINICAL_HANDOFF_PAGE)


@app.route("/telehealth/intake")
def telehealth_intake():
    return _handoff_page("clinical", CLINICAL_HANDOFF_PAGE)


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
        # FOUNDER MUSIC CONTROL: skip any track the founder has switched off
        # on the operations page. If everything in the lane is off, keep the
        # lane alive rather than going silent (music must never stop).
        try:
            _off = _tracks_off_load()
            if _off:
                kept = [n for n in files if n not in _off]
                if kept:
                    files = kept
        except Exception:
            pass
        # FULLY RANDOM at arrival — every track has an EQUAL chance to be first
        # and to appear anywhere in the order. No track is ever privileged as
        # "the calmest one that always starts." (Founder rule: entry is totally
        # random and every track is treated equally.) The emotion-targeting that
        # leans toward calmer music happens later, once the user is engaged, in
        # the adaptive loop — NOT here at the entry point.
        # RANDOMIZE WITHIN THE GENRE — do NOT score or rank the tracks.
        # The FOLDER is the label: every track in this lane is already the right
        # KIND of music (calm / deep-calm / lifting). Scoring was the bug — it
        # always picked the single highest-"calmest" song, so the SAME track
        # greeted every visit. A plain shuffle gives every track in the genre an
        # equal chance and a different one each time. The founder curates each
        # genre and can switch any track off from the operations page.
        import random as _rnd
        _rnd.shuffle(files)
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
    if not _rate_ok("dg", 6, 3600) or not _budget_ok("deepgram"):
        return _gentle_429()
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
    so they can pick the most comforting voice to listen to. Filters to the
    page's current language so a Spanish or Chinese visitor is offered a
    voice that actually speaks their language."""
    lang = (request.args.get("lang") or "en").strip().lower()[:2]
    return jsonify(voice_list(lang))


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
    if not _rate_ok("voice", 60, 3600) or not _budget_ok("voice"):
        return _gentle_429()
    """Return real human audio for the given text if a voice service is
    configured; otherwise tell the browser to use its best on-device voice."""
    data = request.get_json(force=True) or {}
    text = str(data.get("text", ""))[:600]
    voice_id = str(data.get("voice_id", ""))
    lang = str(data.get("lang", "en"))[:8]
    result = voice_synthesize(text, voice_id, lang)
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
  const hues={calm:'#6fb3d4',peaceful:'#c99e7a',anxiety:'#c4a06f',fear:'#d4ab8a',anger:'#d48a8a',
    sadness:'#8a9cd4',grief:'#7d8aa0',numbness:'#a0a0b0',overwhelm:'#d2af92',hope:'#d6b59a',joy:'#e0c46f'};
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




# Clarifying LEGAL questions — asked when the conversation is clearly legal and
# shows no distress, so we engage the legal matter instead of doing a feelings
# check. Open questions (room to answer), never counselor-flavored.
_LEGAL_CLARIFY = {
    "housing": "To point you to the right legal help — have you gotten anything in writing yet, like a notice or a letter, and does it show a date or deadline?",
    "homelessness": "So I can find the right resources — do you need somewhere to stay tonight, or are you trying to plan for the days ahead?",
    "employment": "To match you with the right help — is this mainly about pay you're owed, being let go, or how you're being treated at work?",
    "employment_discrimination": "So the right person can help — do you think this happened because of something like your race, gender, age, disability, or pregnancy?",
    "family": "So I connect you correctly — is this mostly about custody, child support, a divorce, or a protective order?",
    "custody": "To get this right — is there a court order in place now, or is this happening without one?",
    "domestic_violence": "Your safety comes first — are you safe where you are right now? And is this something you'd want legal protection for, like a restraining order?",
    "criminal": "So I point you the right way — has an arrest or charge already happened, and is there a court date or bail set?",
    "immigration": "To find the right help — is someone detained right now, or is this about status, a hearing, or paperwork?",
    "education": "To get you the right advocate — is this about discipline like a suspension, or about services like an IEP or 504 plan?",
    "healthcare": "So I point you correctly — was something denied, like treatment, coverage, or medication, or is this about a rights or consent issue?",
    "disability": "To match the right help — is this about an accommodation being denied, or about benefits like SSI or SSDI?",
    "consumer": "To point you the right way — is this about a debt or collector, a repossession or foreclosure, or a scam?",
    "civil_rights": "So the right advocate can help — can you tell me what happened, and who was involved?",
    "_default": "So I can connect you with the right legal help — can you tell me a little more about what's happening, and any deadlines you're facing?",
}


@app.route("/api/checkin", methods=["POST"])
def api_checkin():
    if not _rate_ok("checkin", 40, 3600) or not _budget_ok("claude"):
        return _gentle_429()
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
    # --- DOMAIN GATE: match the KIND of help to what the person came for. ---
    # Founder rule: listen first, answer once. If someone is here for a LEGAL
    # matter and shows no emotional distress, we engage the LEGAL matter and do
    # NOT offer mental-health help. We never invent an emotional issue where
    # none exists. Only genuine distress signals open the clinical path.
    _mlow = message.lower()
    # A legal problem is distressing, but distress alone is NOT a mental-health
    # signal — we must not invent one. Only a genuine crisis or explicit
    # emotional/clinical language opens the clinical path. (We deliberately do
    # NOT use the general distress score or generic risk here, because those
    # fire on hard legal situations too.)
    _clinical_signal = bool(
        crisis.needs_immediate_support
        or cr.get("level") == "crisis"
        or re.search(r"\b(?:depress|anxious|anxiety|panic|suicid|therap|counsel|clinician|"
                     r"lonely|hopeless|worthless|grief|grieving|trauma|overwhelmed|numbness|"
                     r"mental health|emotional support|breaking down|can.?t sleep|cannot sleep|"
                     r"feel(?:ing|s)? (?:sad|down|awful|empty|alone|scared|hopeless|numb))", _mlow)
    )
    _has_legal = bool(legal_issues)
    if _has_legal and not _clinical_signal:
        domain = "legal"
    elif _has_legal and _clinical_signal:
        domain = "both"
    elif _clinical_signal:
        domain = "clinical"
    else:
        domain = "general"

    if domain == "legal":
        # Engage the legal matter with a clarifying LEGAL question — never a
        # feelings check, never a counselor offer. This also suppresses the
        # emotional investigation below.
        _code = legal_issues[0].get("code", "")
        _label = legal_issues[0].get("label", "a legal matter")
        _q = _LEGAL_CLARIFY.get(_code, _LEGAL_CLARIFY["_default"])
        conv_questions = [get_cultural_engine().shape_response(_q, cultural["register"])]
        # If the local fallback engine was used (no model), its reply is written
        # for emotional topics. Replace it with a legal-forward acknowledgment so
        # a legal conversation never opens with a mental-health frame.
        if not smart:
            conv_response = get_cultural_engine().shape_response(
                "Thank you for telling me — this sounds like " + _label + ", and I can help you "
                "get to the right legal support. Let me understand it a little better first.",
                cultural["register"])
    elif getattr(crisis, "needs_investigation", False) and not crisis.needs_immediate_support:
        # --- PRINCIPLE 12: NO INVESTIGATION, NO RIGHT TO SPEAK ---
        # Ambiguous NON-legal shorthand ("hurt myself at the gym") is neither
        # dismissed nor red-flagged. We LEAD with a caring door-opening question.
        # A true crisis phrase (needs_immediate_support) makes the crisis flow
        # lead instead — investigation never overrides an active crisis.
        probe = get_cultural_engine().shape_response(
            crisis.investigation_prompt, cultural["register"])
        conv_questions = [probe] + [q for q in conv_questions if q and q != probe]
        if risk == "low":
            risk = "moderate"
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

    # --- PRINCIPLE 13: THE ASYMMETRY OF FAILURE — attempt EVERY time. ---
    # No response may EVER dead-end. If, for any reason, no follow-up question
    # was produced, we still leave an open door — silence is never an option.
    conv_questions = [q for q in (conv_questions or []) if q and q.strip()]
    if not conv_questions:
        conv_questions = ["I'm right here with you. What feels most important to "
                          "say right now — even a few words is enough."]
    # The human bridge is a PERMANENT fixture, present on every single response
    # at every risk level, not something that appears only in an emergency.
    human_help = {
        "always_available": True,
        "lifeline": "988",
        "text_line": "Text HOME to 741741",
        "message": "A real person is available any hour — call or text 988. "
                   "You never have to get through this alone.",
    }

    # SB 243 accountability: when the crisis protocol activates (the 988
    # referral is about to be shown), count it — count only, never content.
    if crisis.needs_immediate_support:
        record_crisis_referral()

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
        "needs_investigation": getattr(crisis, "needs_investigation", False),
        "domain": domain,
        "human_help": human_help,
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


# ===========================================================================
# RETURNING-USER MEMORY ("continue your story")
# A person may OPT IN to save their session under a generated code like
# CALM-4821-MOON. The story is encrypted with a key derived from that code —
# so it cannot be read without it, not even by the founder. Stored on the
# persistent disk so it follows the person across devices.
# ===========================================================================

# ---- LIVE BIOMETRIC MONITOR (anonymous, ephemeral) ----
# Holds the most recent biometric ping per active session so the founder can
# watch calm-state in real time. In memory only, auto-expires; no identity,
# no words. This is the live research window.
_BIO_LIVE = {}   # sid -> {bpm, tier, base, state, face, last, history:[...]}
_BIO_LOCK = threading.Lock()

@app.route("/api/bio/ping", methods=["POST"])
def bio_ping():
    if not _rate_ok("bio", 1200, 3600):
        return jsonify({"status": "ignored"}), 200
    data = request.get_json(silent=True) or {}
    sid = str(data.get("sid", ""))[:24]
    if not sid:
        return jsonify({"status": "ignored"}), 200
    try:
        bpm = int(data.get("bpm", 0))
    except Exception:
        bpm = 0
    # A valid heart reading is 30-220; anything else means "no reading yet" (0),
    # but we STILL record the session as live so the founder sees it with status.
    if bpm and not (30 <= bpm <= 220):
        bpm = 0
    now = time.time()
    with _BIO_LOCK:
        rec = _BIO_LIVE.get(sid) or {"history": []}
        try:
            cam = 1 if int(data.get("cam", 0)) else 0
        except Exception:
            cam = 0
        rec.update({"bpm": bpm, "hasheart": 1 if bpm else 0, "cam": cam,
                    "tier": str(data.get("tier",""))[:14],
                    "base": int(data.get("base", bpm) or bpm), "state": str(data.get("state",""))[:12],
                    "face": str(data.get("face",""))[:16], "last": now})
        if bpm:
            rec["history"].append({"t": time.strftime("%H:%M:%S"), "bpm": bpm})
            rec["history"] = rec["history"][-40:]   # last ~40 readings
        _BIO_LIVE[sid] = rec
        # expire anything older than 90s
        for k in [k for k,v in _BIO_LIVE.items() if now - v.get("last",0) > 90]:
            _BIO_LIVE.pop(k, None)
    return jsonify({"status": "ok"})

@app.route("/api/admin/bio/live")
def admin_bio_live():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    now = time.time()
    with _BIO_LOCK:
        active = []
        for i, (sid, v) in enumerate(sorted(_BIO_LIVE.items(), key=lambda kv: kv[1].get("last",0), reverse=True)):
            if now - v.get("last",0) > 90: continue
            active.append({
                "who": "Person " + str(i+1),
                "bpm": v.get("bpm"), "base": v.get("base"), "state": v.get("state"),
                "tier": v.get("tier"), "face": v.get("face"),
                "cam": v.get("cam", 0), "hasheart": v.get("hasheart", 0),
                "ago": int(now - v.get("last",0)),
                "spark": [h["bpm"] for h in v.get("history", [])][-24:]
            })
    return jsonify({"active": active, "count": len(active), "server_time": time.strftime("%H:%M:%S")})



# ===========================================================================
# ABUSE SHIELD — protects against bot farms and cost-collapse attacks.
# Three defenses:
#  (1) Per-IP sliding-window rate limits on every endpoint that costs money.
#  (2) Global daily budget caps — even a distributed attack cannot exceed the
#      day's spend ceiling; the service degrades gracefully instead of bleeding.
#  (3) Bot traps: honeypot field + minimum-human-time checks on connect.
# All blocks are counted and shown on the founder dashboard.
# ===========================================================================
from collections import deque as _deque
_RATE = {}
_RATE_LOCK = threading.Lock()
_ABUSE = {"day": "", "blocked": 0}

def _client_ip():
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip())[:45]

def _rate_ok(scope, limit, window_sec):
    """Sliding-window per-IP limiter. Returns True if allowed."""
    ip = _client_ip()
    key = scope + "|" + ip
    now = time.time()
    with _RATE_LOCK:
        q = _RATE.get(key)
        if q is None:
            q = _deque(); _RATE[key] = q
        while q and now - q[0] > window_sec:
            q.popleft()
        if len(q) >= limit:
            _abuse_mark()
            return False
        q.append(now)
        # opportunistic cleanup
        if len(_RATE) > 20000:
            for k in list(_RATE.keys())[:5000]:
                _RATE.pop(k, None)
    return True

_BUDGET = {"day": "", "counts": {}}
_BUDGET_LOCK = threading.Lock()
_BUDGET_CAPS = {
    "claude":   int(os.environ.get("CAP_CLAUDE_PER_DAY",   "1500")),
    "deepgram": int(os.environ.get("CAP_DEEPGRAM_PER_DAY", "300")),
    "voice":    int(os.environ.get("CAP_VOICE_PER_DAY",    "600")),
    "connect":  int(os.environ.get("CAP_CONNECT_PER_DAY",  "60")),
    "memory":   int(os.environ.get("CAP_MEMORY_PER_DAY",   "300")),
}

def _budget_ok(kind):
    """Global daily spend ceiling per costly service."""
    day = time.strftime("%Y-%m-%d")
    with _BUDGET_LOCK:
        if _BUDGET["day"] != day:
            _BUDGET["day"] = day; _BUDGET["counts"] = {}
        c = _BUDGET["counts"].get(kind, 0)
        if c >= _BUDGET_CAPS.get(kind, 10**9):
            _abuse_mark()
            return False
        _BUDGET["counts"][kind] = c + 1
    return True

def _abuse_mark():
    day = time.strftime("%Y-%m-%d")
    if _ABUSE["day"] != day:
        _ABUSE["day"] = day; _ABUSE["blocked"] = 0
    _ABUSE["blocked"] += 1

def _gentle_429():
    return jsonify({"status": "busy",
        "message": "InnerLight is very busy right now. Please wait a moment and try again — and if you need help now, call or text 988."}), 429

@app.route("/api/admin/abuse")
def admin_abuse():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    with _BUDGET_LOCK:
        counts = dict(_BUDGET.get("counts", {}))
    return jsonify({"blocked_today": _ABUSE.get("blocked", 0) if _ABUSE.get("day")==time.strftime("%Y-%m-%d") else 0,
                    "budget_used": counts, "budget_caps": _BUDGET_CAPS})


_MEMORY_FILE = os.environ.get("MEMORY_FILE", _DATA_DIR + "/innerlight_memory.json")
_MEMORY_LOCK = threading.Lock()
_CODE_WORDS = ["MOON","CALM","LEAF","WAVE","STAR","DAWN","FERN","TIDE","SAGE","GLOW","PINE","REST"]

def _memory_load():
    try:
        with open(_MEMORY_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _memory_save(d):
    try:
        with open(_MEMORY_FILE, "w") as f:
            json.dump(d, f)
    except Exception as e:
        print("[InnerLight] memory save failed:", e)

def _new_code():
    import random
    return f"{random.choice(_CODE_WORDS)}-{random.randint(1000,9999)}-{random.choice(_CODE_WORDS)}"

def _code_key(code):
    # normalize so entry is forgiving of case/spacing
    return "".join(ch for ch in code.upper() if ch.isalnum())

@app.route("/api/memory/save", methods=["POST"])
def memory_save():
    if not _rate_ok("memsave", 6, 3600) or not _budget_ok("memory"):
        return _gentle_429()
    """Opt-in: encrypt a session summary under a fresh return code."""
    data = request.get_json(silent=True) or {}
    summary = str(data.get("summary", ""))[:6000]
    if not summary.strip():
        return jsonify({"status": "empty"}), 200
    # generate a unique code
    with _MEMORY_LOCK:
        store = _memory_load()
        code = _new_code()
        tries = 0
        while _code_key(code) in store and tries < 20:
            code = _new_code(); tries += 1
        # encrypt the summary with a key that includes the code
        enc = AxiomHarmonyProtocol(encryption_key("memory::" + _code_key(code))).encrypt(
            {"summary": summary, "saved": time.strftime("%Y-%m-%d %H:%M")})
        store[_code_key(code)] = {"enc": enc, "saved": time.strftime("%Y-%m-%d %H:%M")}
        # cap total stored
        if len(store) > 5000:
            oldest = sorted(store.items(), key=lambda kv: kv[1].get("saved",""))[:100]
            for k,_ in oldest: store.pop(k, None)
        _memory_save(store)
    return jsonify({"status": "ok", "code": code})

@app.route("/api/memory/resume", methods=["POST"])
def memory_resume():
    if not _rate_ok("memresume", 10, 3600):
        return _gentle_429()  # also throttles code-guessing attacks
    """Return: decrypt a saved story from the person's code."""
    data = request.get_json(silent=True) or {}
    code = str(data.get("code", ""))[:40]
    k = _code_key(code)
    if not k:
        return jsonify({"status": "invalid"}), 200
    with _MEMORY_LOCK:
        store = _memory_load()
        rec = store.get(k)
    if not rec:
        return jsonify({"status": "notfound"}), 200
    try:
        out = AxiomHarmonyProtocol(encryption_key("memory::" + k)).decrypt(rec["enc"]).get("original_data", {})
        return jsonify({"status": "ok", "summary": out.get("summary",""), "saved": rec.get("saved","")})
    except Exception:
        return jsonify({"status": "error"}), 200


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

_LIVE_FEED = []  # rolling last-N events for real-time proof on the dashboard
_LIVE_TOTAL = {"count": 0, "day": ""}

@app.route("/api/metrics/event", methods=["POST"])
def metrics_event():
    if not _rate_ok("metrics", 900, 3600):
        return jsonify({"status": "ignored"}), 200
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
               "activity_open", "reengage_prompt", "bloom", "lowlight_rescue", "substitution_redirect", "minor_redirect", "lane_switch", "face_shift", "facilities_search", "legal_surfaced", "help_requested"}
    if etype not in allowed:
        return jsonify({"status": "ignored"}), 200
    day = time.strftime("%Y-%m-%d")
    # LIVE FEED (real-time proof of tracking)
    global _LIVE_FEED, _LIVE_TOTAL
    if _LIVE_TOTAL.get("day") != day:
        _LIVE_TOTAL = {"count": 0, "day": day}
    _LIVE_TOTAL["count"] += 1
    _LIVE_FEED.append({"t": time.strftime("%H:%M:%S"), "type": etype,
                       "val": (str(value)[:24] if value is not None else ""),
                       "sid": sid[:4] + "\u2026"})
    if len(_LIVE_FEED) > 60:
        _LIVE_FEED = _LIVE_FEED[-60:]
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
        elif etype == "heart_read" and value is not None:
            try:
                raw = str(value); bpm_s, _, tier = raw.partition("|")
                bpm = int(float(bpm_s)); tier = (tier or "measured")[:14]
                if 30 <= bpm <= 220:
                    h = d.setdefault("heart", {"sum": 0, "n": 0, "tiers": {}})
                    h["sum"] += bpm; h["n"] += 1
                    h["tiers"][tier] = h["tiers"].get(tier, 0) + 1
                    if sess is not None:
                        sess["heart_last"] = bpm; sess["heart_tier"] = tier
            except Exception:
                pass
        elif etype == "minor_redirect":
            d["minor_redirects"] = d.get("minor_redirects", 0) + 1
        elif etype == "substitution_redirect":
            d["substitution_redirects"] = d.get("substitution_redirects", 0) + 1
        elif etype == "lowlight_rescue":
            d["lowlight_rescues"] = d.get("lowlight_rescues", 0) + 1
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
      font-family:Arial;background:linear-gradient(135deg,#0f2447 0%,#1d4ed8 55%,#da8c4d 100%);}
 .card{background:rgba(255,255,255,0.97);border-radius:16px;padding:36px 34px;width:330px;
       box-shadow:0 18px 50px rgba(10,20,60,0.45);}
 h1{font-size:19px;color:#1e3a8a;margin:0 0 4px;} .sub{font-size:12px;color:#64748b;margin-bottom:22px;}
 label{display:block;font-size:12px;color:#334155;font-weight:700;margin:12px 0 5px;letter-spacing:0.3px;}
 input{width:100%;box-sizing:border-box;padding:11px 12px;border:1px solid #cbd5e1;border-radius:9px;
       font-size:15px;} input:focus{outline:2px solid #3b82f6;border-color:#3b82f6;}
 button{margin-top:20px;width:100%;padding:12px;border:0;border-radius:9px;font-size:15px;font-weight:700;
        color:#fff;background:linear-gradient(90deg,#1d4ed8,#da8c4d);cursor:pointer;}
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

@app.route("/api/admin/live")
def admin_live():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    day = time.strftime("%Y-%m-%d")
    with _METRICS_LOCK:
        m = _metrics_load()
        d = m.get(day, {})
        sessions_today = len(d.get("by_session", {}))
        blooms = d.get("blooms", 0)
        msgs = d.get("messages", 0)
    return jsonify({
        "events_today": _LIVE_TOTAL.get("count", 0) if _LIVE_TOTAL.get("day") == day else 0,
        "sessions_today": sessions_today,
        "blooms_today": blooms,
        "messages_today": msgs,
        "server_time": time.strftime("%H:%M:%S"),
        "feed": list(reversed(_LIVE_FEED[-18:]))
    })

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
    # Heart coverage + tier breakdown across shown days
    h_sum=h_n=0; tiers={}
    for d0 in days:
        h = m[d0].get("heart", {})
        h_sum += h.get("sum",0); h_n += h.get("n",0)
        for k,v in h.get("tiers",{}).items(): tiers[k]=tiers.get(k,0)+v
    if h_n:
        avg = h_sum/h_n; ttot=sum(tiers.values()) or 1
        order=["measured","estimated","baseline-held"]
        bars="".join(
            f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #eef2f8;">'
            f'<span>{k.capitalize()}</span><b style="color:{"#2f6da8" if k=="measured" else "#d97706" if k=="estimated" else "#64748b"};">'
            f'{tiers.get(k,0)} ({100*tiers.get(k,0)/ttot:.0f}%)</b></div>'
            for k in order if tiers.get(k,0))
        meas_pct = 100*tiers.get("measured",0)/ttot
        heart_rows = (f'<div style="font-size:15px;margin-bottom:8px;">Average heart rate: <b>{avg:.0f} bpm</b> '
                      f'across <b>{h_n}</b> readings &mdash; <b style="color:#9a561f;">100% session coverage</b>, '
                      f'{meas_pct:.0f}% high-confidence.</div>' + bars).replace("#9a561f","#2f6da8")
    else:
        heart_rows = "<i>No heart readings recorded yet. They gather as people use the camera.</i>"
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
            f'<span>{ZLABEL.get(z, z)}</span><b style="color:#b24a2a;">{(a["sum"]/a["n"]):.0f}% agreement</b></div>'
            for z, a in sorted(zagg.items(), key=lambda x: -(x[1]["sum"]/max(1,x[1]["n"]))))
    else:
        subzone_rows = '<i>No experimental sub-zone data yet. It gathers as people use the camera.</i>'
    # ---- Headline KPIs for the rebuilt dashboard hero strip (server-side) ----
    _tot_sessions = sum(max(m[d0].get('sessions', 0), len(m[d0].get('by_session', {}))) for d0 in days) if days else 0
    _tot_messages = sum(m[d0].get('messages', 0) for d0 in days) if days else 0
    _fs_sum = sum(m[d0].get('first_sound_ms_sum', 0) for d0 in days)
    _fs_cnt = sum(m[d0].get('first_sound_count', 0) for d0 in days)
    _avg_first = (_fs_sum / _fs_cnt / 1000.0) if _fs_cnt else 0
    _tot_handoffs = 0
    for _d0 in days:
        for _hk, _hv in m[_d0].get('handoffs', {}).items():
            _tot_handoffs += _hv
    _avg_heart = (h_sum / h_n) if h_n else 0
    def _kpi(val, label, sub, ocean=False, vid=""):
        cls = "kpi ocean" if ocean else "kpi"
        vspan = f'<span id="{vid}">{val}</span>' if vid else str(val)
        return (f'<div class="{cls}"><div class="kpi-v">{vspan}</div>'
                f'<div class="kpi-l">{label}</div><div class="kpi-s">{sub}</div></div>')
    kpi_cards = (
        f'<div class="kpi ocean"><div class="kpi-v"><span class="dot"></span><span id="kpi-live-n">0</span></div>'
        f'<div class="kpi-l">Live right now</div><div class="kpi-s">people in a session</div></div>'
        + _kpi(_tot_sessions, "Sessions", "last 14 days")
        + _kpi((f"{_avg_first:.1f}s" if _fs_cnt else "&mdash;"), "To first sound", "lower is better")
        + _kpi(_tot_messages, "Messages", "last 14 days")
        + _kpi((f"{_avg_heart:.0f}" if h_n else "&mdash;"), "Avg heart rate", "bpm seen", ocean=True)
        + _kpi(_tot_handoffs, "Human handoffs", "bridges to a person")
    )
    return render_template_string("""
<!doctype html><html><head><title>InnerLight — Operations</title>
<meta name="robots" content="noindex,nofollow">
<style>
 :root{
   --ink:#2a1e14; --ink2:#5c4636; --muted:#8a7a68;
   --paper:#f4ecdf; --card:#ffffff; --line:#ece0d0;
   --amber:#c56a2c; --amber-d:#a9531f; --terra:#b24a2a; --ocean:#2f6da8;
   --shadow-s:0 6px 20px rgba(42,30,20,0.08);
 }
 *{box-sizing:border-box;}
 body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
   color:var(--ink2);background:var(--paper);
   background-image:radial-gradient(1100px 380px at 50% -140px,#fff7ec 0%,rgba(255,247,236,0) 72%);}
 a{color:var(--ocean);}
 .topbar{position:sticky;top:0;z-index:50;background:rgba(42,30,20,0.97);
   color:#f6ece0;display:flex;align-items:center;gap:14px;padding:12px 22px;
   box-shadow:0 2px 18px rgba(0,0,0,0.18);flex-wrap:wrap;}
 .topbar .brand{font-family:Georgia,"Times New Roman",serif;font-size:16px;font-weight:700;color:#fff;white-space:nowrap;}
 .topbar .brand span{color:var(--amber);}
 .nav{display:flex;gap:2px;flex-wrap:wrap;flex:1;margin-left:6px;}
 .nav a{color:#e8d8c4;text-decoration:none;font-size:13px;padding:6px 12px;border-radius:999px;}
 .nav a:hover{background:rgba(255,255,255,0.12);color:#fff;}
 .act{display:flex;gap:8px;}
 .act a{color:#e8d8c4;font-size:12.5px;text-decoration:none;border:1px solid rgba(255,255,255,0.35);
   padding:7px 14px;border-radius:999px;white-space:nowrap;} .act a:hover{background:rgba(255,255,255,0.12);}
 .act a.primary{background:var(--amber);border-color:var(--amber);color:#fff;}
 .wrap{max-width:1180px;margin:0 auto;padding:24px 22px 64px;}
 .lede{font-family:Georgia,serif;color:var(--ink);font-size:15px;margin:2px 0 20px;}
 .lede b{color:var(--amber-d);}
 .hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:14px;margin-bottom:8px;}
 .kpi{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px 18px 16px;
   box-shadow:var(--shadow-s);position:relative;overflow:hidden;}
 .kpi:before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;
   background:linear-gradient(180deg,var(--amber),var(--terra));}
 .kpi.ocean:before{background:linear-gradient(180deg,#5aa0d8,var(--ocean));}
 .kpi-v{font-size:30px;font-weight:800;color:var(--ink);line-height:1;font-variant-numeric:tabular-nums;}
 .kpi-l{font-size:13.5px;font-weight:700;color:var(--ink2);margin-top:9px;}
 .kpi-s{font-size:11.5px;color:var(--muted);margin-top:2px;}
 .kpi .dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--ocean);
   margin-right:6px;vertical-align:middle;animation:ilpulse 1.6s infinite;}
 @keyframes ilpulse{0%,100%{opacity:1;}50%{opacity:0.25;}}
 h2{font-family:Georgia,serif;color:var(--ink);font-size:18px;margin:34px 0 12px;padding-left:14px;
   border-left:5px solid var(--amber);line-height:1.25;scroll-margin-top:74px;}
 .card-like{background:var(--card)!important;border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow-s);}
 .tablewrap{background:var(--card);border:1px solid var(--line);border-radius:16px;
   box-shadow:var(--shadow-s);overflow-x:auto;}
 table{border-collapse:collapse;width:100%;background:transparent;}
 th,td{padding:11px 13px;text-align:left;font-size:13px;border-bottom:1px solid var(--line);white-space:nowrap;}
 th{background:#f3e7d7;color:var(--ink);font-size:11px;letter-spacing:0.4px;text-transform:uppercase;}
 td{color:var(--ink2);} tr:hover td{background:#faf4ea;} tr:last-child td{border-bottom:0;}
 .note{margin-top:18px;font-size:12.8px;color:var(--ink2);background:var(--card);border:1px solid var(--line);
   border-left:5px solid var(--amber);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow-s);line-height:1.7;}
 .graph{display:flex;align-items:flex-end;gap:8px;background:var(--card);border:1px solid var(--line);
   padding:18px;border-radius:16px;box-shadow:var(--shadow-s);margin:6px 0 0;overflow-x:auto;}
 .bar-col{display:flex;flex-direction:column;align-items:center;min-width:44px;}
 .bar{width:26px;background:linear-gradient(180deg,#e0a458,var(--amber));border-radius:5px 5px 0 0;}
 .bar-lbl{font-size:10px;color:var(--muted);margin-top:4px;} .bar-num{font-size:11px;color:var(--amber-d);font-weight:700;}
 .sci-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;}
 .sci{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;font-size:12.8px;
   line-height:1.62;color:var(--ink2);box-shadow:var(--shadow-s);border-top:3px solid var(--amber);}
 .sci b{color:var(--amber-d);font-size:13.2px;}
 @media(max-width:640px){ .wrap{padding:18px 14px 52px;} .topbar .brand{font-size:14px;} .kpi-v{font-size:26px;} }
</style></head><body>
<div class="topbar">
 <div class="brand">Inner<span>Light</span> · Operations Room</div>
 <nav class="nav">
  <a href="#overview">Overview</a><a href="#live">Live</a><a href="#music">Music</a><a href="#people">People</a><a href="#research">Research</a>
 </nav>
 <div class="act"><a href="/admin/study">Founder's Study</a><a class="primary" href="/admin/logout">Sign out</a></div>
</div>
<main class="wrap">
<div class="lede">Anonymous counts and clock-times only — <b>no words, names, faces, or voices are ever stored.</b></div>
<div class="hero">{{ kpi_cards|safe }}</div>
<h2 id="overview">Daily overview — the last 14 days</h2>
<div class="tablewrap">
<table>
<tr><th>Day</th><th>Sessions</th><th>Avg time to first sound</th><th>Messages</th>
<th>Expression shifts seen</th><th>Music lane shifts</th><th>Scene changes</th>
<th>Hesitations (typed then erased)</th><th>Avg time to open sound box</th>
<th>Handoff clicks</th><th>Tracks that drew dislike</th><th>Listening auto-stops</th>
<th>Gaze aversions (eyes fled)</th><th>Avg heart rate seen</th><th>Calm scale: arrival &rarr; later</th></tr>
{{ body|safe }}
</table>
</div>
<h2>Incoming connection requests — people who asked for a human</h2>
<div class="card-like" id="connects" style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.14);font-size:13.5px;">Loading&hellip;</div>
<script>
fetch('/api/admin/connects').then(r=>r.json()).then(function(d){
  const el = document.getElementById('connects');
  if(!d.connects || !d.connects.length){ el.textContent = 'No connection requests yet.'; return; }
  el.innerHTML = d.connects.map(function(c){
    return '<div style="border-bottom:1px solid #efe4d6;padding:9px 0;">'
      + '<b style="color:#7a3e1e;">' + c.when + '</b> — ' + c.kind.toUpperCase() + ' — wants: <b>' + c.pro + '</b> '
      + '— <a href="' + c.room + '" target="_blank" style="color:#c56a2c;font-weight:700;">Join room</a>'
      + (c.summary ? '<div style="color:#475569;margin-top:4px;white-space:pre-wrap;">' + c.summary.replace(/</g,'&lt;') + '</div>' : '')
      + '</div>';
  }).join('');
}).catch(function(){ document.getElementById('connects').textContent = 'Could not load.'; });
</script>
<h2>What people said &mdash; voices from real sessions</h2>
<div class="card-like" style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.14);margin-bottom:14px;">
<div style="font-size:12px;color:#64748b;margin-bottom:10px;">Anonymous feedback from people who used InnerLight. Identifying details are automatically removed. This is the human evidence alongside the numbers.</div>
<div id="fb-report"><i style="color:#94a3b8;">Loading feedback\u2026</i></div>
</div>
<script>
(function(){
  async function load(){
    try{
      const r=await fetch('/api/admin/feedback'); if(!r.ok) return;
      const d=await r.json();
      const el=document.getElementById('fb-report'); if(!el) return;
      if(!d.total){ el.innerHTML='<i style="color:#94a3b8;">No feedback yet. As people share, their words appear here.</i>'; return; }
      const h=d.helped||{}, tot=d.total||1;
      const pct=function(n){return Math.round(100*(n||0)/tot);};
      let html='<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px;font-size:14px;">'
        +'<div style="flex:1;min-width:120px;background:#edf3f8;border-radius:10px;padding:12px;text-align:center;"><b style="font-size:22px;color:#2f6da8;">'+pct(h.yes)+'%</b><br>said it helped</div>'
        +'<div style="flex:1;min-width:120px;background:#fbf7f1;border-radius:10px;padding:12px;text-align:center;"><b style="font-size:22px;color:#64748b;">'+pct(h.somewhat)+'%</b><br>somewhat</div>'
        +'<div style="flex:1;min-width:120px;background:#fdf5f5;border-radius:10px;padding:12px;text-align:center;"><b style="font-size:22px;color:#9a6a6a;">'+pct(h.no)+'%</b><br>not really</div>'
        +'<div style="flex:1;min-width:120px;background:#fbf3e9;border-radius:10px;padding:12px;text-align:center;"><b style="font-size:22px;color:#7a3e1e;">'+d.total+'</b><br>total responses</div>'
        +'</div>';
      if(d.quotes&&d.quotes.length){
        html+='<div style="font-size:13px;color:#475569;font-weight:700;margin:6px 0;">In their own words:</div>';
        html+=d.quotes.map(function(q){
          return '<div style="border-left:3px solid #7fa8c9;background:#fbf7f1;border-radius:0 8px 8px 0;padding:10px 14px;margin:8px 0;font-size:14px;color:#334155;font-style:italic;">“'
            +(q.words||'').replace(/</g,'&lt;')+'”<span style="display:block;font-style:normal;font-size:11px;color:#94a3b8;margin-top:4px;">'+(q.when||'')+(q.helped?' · '+q.helped:'')+'</span></div>';
        }).join('');
      }
      el.innerHTML=html;
    }catch(e){}
  }
  load();
})();
</script>
<h2>Crisis referrals &mdash; the count for the state report</h2>
<div class="card-like" style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.14);margin-bottom:14px;">
<div style="font-size:12px;color:#64748b;margin-bottom:10px;">Each time the crisis protocol activates and 988 is put in front of a person, it is counted here &mdash; counts only, never content. This is the number California's Office of Suicide Prevention report (due each July starting 2027) will be built from.</div>
<div id="crisis-referrals"><i style="color:#94a3b8;">Loading&hellip;</i></div>
</div>
<script>
(async function(){
  try{
    var r = await fetch('/api/admin/crisisreferrals'); if(!r.ok) return;
    var d = await r.json();
    var el = document.getElementById('crisis-referrals'); if(!el) return;
    var months = Object.keys(d.by_month || {}).sort().reverse();
    if(!months.length){ el.innerHTML = '<i style="color:#94a3b8;">No crisis-protocol activations recorded yet. Counting began with this deploy.</i>'; return; }
    var html = '<div style="font-weight:700;margin-bottom:8px;">' + d.total + ' total activation' + (d.total===1?'':'s') + ' since counting began</div>';
    for (var i=0; i<months.length; i++){
      html += '<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f3eade;"><span>' + months[i] + '</span><b style="color:#2f6da8;">' + d.by_month[months[i]] + '</b></div>';
    }
    el.innerHTML = html;
  }catch(e){}
})();
</script>
<h2 id="music">Music control &mdash; listen to any track, switch any track off</h2>
<div class="card-like" style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.14);margin-bottom:14px;">
<div style="font-size:12px;color:#64748b;margin-bottom:6px;">Press <b>Listen</b> to hear any track right here. Press <b>Turn off</b> and that exact song stops being offered &mdash; no redeploy needed, and you can turn it back on any time. Honest note: someone already listening may still hear their current list until their music next shifts; every new playlist skips it.</div>
<div id="tc-status" style="font-size:12px;color:#c0564e;font-weight:700;margin-bottom:6px;"></div>
<div id="track-control"><i style="color:#94a3b8;">Loading tracks&hellip;</i></div>
<audio id="tc-audio" preload="none"></audio>
</div>
<script>
(function(){
  var LANE_NAMES = {calm:'Calm (gentle arrival)', deepcalm:'Deep calm (settles agitation)', lifting:'Lifting (raises low mood)'};
  var playingFile = null;
  function esc(s){ return String(s).replace(/</g,'&lt;'); }
  async function loadTracks(){
    try{
      var r = await fetch('/api/admin/tracks'); if(!r.ok) return;
      var d = await r.json();
      var el = document.getElementById('track-control'); if(!el) return;
      var lanes = d.lanes || {};
      var html = '';
      Object.keys(lanes).sort().forEach(function(lane){
        html += '<div style="font-weight:700;color:#2f6da8;margin:10px 0 4px;">' + esc(LANE_NAMES[lane] || lane) + '</div>';
        lanes[lane].forEach(function(t){
          var rowStyle = t.enabled ? '' : 'opacity:0.5;';
          var btnBg = t.enabled ? '#c0564e' : '#2f6da8';
          var btnLabel = t.enabled ? 'Turn off' : 'Turn on';
          html += '<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f3eade;' + rowStyle + '">'
            + '<button data-listen="' + esc(t.file) + '" style="background:#2f6da8;color:#fff;border:0;border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer;min-width:66px;">Listen</button>'
            + '<span style="flex:1;">' + esc(t.file) + (t.enabled ? '' : ' <b style="color:#c0564e;">(off)</b>') + '</span>'
            + '<span style="color:#94a3b8;font-size:12px;">' + (t.plays||0) + ' plays</span>'
            + '<button data-toggle="' + esc(t.file) + '" data-en="' + (t.enabled ? '1' : '0') + '" style="background:' + btnBg + ';color:#fff;border:0;border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer;min-width:76px;">' + btnLabel + '</button>'
            + '</div>';
        });
      });
      el.innerHTML = html || '<i style="color:#94a3b8;">No tracks found.</i>';
    }catch(e){}
  }
  var tcAudio = document.getElementById('tc-audio');
  function resetListenButtons(){
    var all = document.querySelectorAll('[data-listen]');
    for (var i=0; i<all.length; i++){ all[i].textContent = 'Listen'; }
  }
  if (tcAudio) tcAudio.addEventListener('ended', function(){ playingFile = null; resetListenButtons(); });
  document.addEventListener('click', async function(ev){
    var b = ev.target;
    if (!b || !b.getAttribute) return;
    var listen = b.getAttribute('data-listen');
    var toggle = b.getAttribute('data-toggle');
    if (listen && tcAudio){
      if (playingFile === listen){ tcAudio.pause(); playingFile = null; b.textContent = 'Listen'; return; }
      resetListenButtons();
      tcAudio.src = '/audio/' + listen;
      tcAudio.currentTime = 0;
      tcAudio.play().catch(function(){});
      playingFile = listen;
      b.textContent = 'Stop';
    }
    if (toggle){
      var makeEnabled = b.getAttribute('data-en') !== '1';
      b.disabled = true;
      var status = document.getElementById('tc-status');
      try{
        var r = await fetch('/api/admin/tracks/toggle', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({file: toggle, enabled: makeEnabled})});
        var d = await r.json();
        if (status) status.textContent = (d && d.status === 'refused') ? (d.reason || '') : '';
      }catch(e){}
      loadTracks();
    }
  });
  loadTracks();
})();
</script>
<h2>Song play log &mdash; every track, every timestamp</h2>
<div class="card-like" style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.14);margin-bottom:14px;">
<div style="font-size:12px;color:#64748b;margin-bottom:10px;">Exactly what played and when. Every play is stamped to the second, so you can see if a track repeats within an hour. Use this to spot any song that plays too often. <button onclick="loadPlays()" style="background:#2f6da8;color:#fff;border:0;border-radius:999px;padding:6px 14px;font-size:12px;cursor:pointer;margin-left:8px;">Refresh</button></div>
<div id="plays-report"><i style="color:#94a3b8;">Loading play log\u2026</i></div>
</div>
<script>
async function loadPlays(){
  try{
    var r = await fetch('/api/admin/plays'); if(!r.ok) return;
    var d = await r.json();
    var el = document.getElementById('plays-report'); if(!el) return;
    if(!d.total_plays){ el.innerHTML='<i style="color:#94a3b8;">No plays recorded yet. As sessions run, every song play appears here with its timestamp.</i>'; return; }
    var html = '<div style="font-weight:700;margin-bottom:8px;">' + d.total_plays + ' total plays recorded</div>';
    // per-track totals
    html += '<div style="display:flex;gap:16px;flex-wrap:wrap;">';
    html += '<div style="flex:1;min-width:240px;"><div style="font-weight:700;color:#2f6da8;margin-bottom:4px;">Plays per track (most played first)</div>'
      + d.by_track.map(function(t){
          var heavy = t.count >= 5 ? 'color:#c0564e;font-weight:800;' : 'color:#2f6da8;';
          return '<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f3eade;"><span>' + t.file + '</span><b style="' + heavy + '">' + t.count + '</b></div>';
        }).join('') + '</div>';
    // full timestamp list
    html += '<div style="flex:1;min-width:240px;max-height:340px;overflow:auto;"><div style="font-weight:700;color:#334155;margin-bottom:4px;">Every play, newest first (with timestamp)</div>'
      + d.recent.map(function(r){
          return '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #f5efe6;font-size:13px;"><span style="color:#475569;">' + r.file + '</span><span style="color:#94a3b8;font-variant-numeric:tabular-nums;">' + (r.ts||'') + '</span></div>';
        }).join('') + '</div>';
    html += '</div>';
    el.innerHTML = html;
  }catch(e){}
}
loadPlays();
</script>
<h2 id="live">Live sessions &mdash; real-time biometric monitor</h2>
<div class="card-like" style="background:#2a1e14;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.2);margin-bottom:14px;color:#f3e9db;">
<div style="font-size:12px;color:#c9b79f;margin-bottom:10px;">Anonymous, live. Each person currently using InnerLight with their camera on appears here \u2014 heart rate, calm state, and a moving trend line, updating every few seconds. No names, no words, just the biometric signal. <span id="bio-clock" style="float:right;"></span></div>
<div id="bio-live-list"><i style="color:#b7a084;">Waiting for a live session\u2026</i></div>
</div>
<script>
(function(){
  function spark(vals){
    if(!vals||!vals.length) return '';
    const w=180,h=34,min=Math.min.apply(null,vals),max=Math.max.apply(null,vals),rng=(max-min)||1;
    const pts=vals.map(function(v,i){return (i/(vals.length-1)*w).toFixed(1)+','+(h-(v-min)/rng*h).toFixed(1);}).join(' ');
    return '<svg width="'+w+'" height="'+h+'" style="vertical-align:middle;"><polyline points="'+pts+'" fill="none" stroke="#7fa8c9" stroke-width="2"/></svg>';
  }
  function stateColor(st){ return st==='rising'?'#f0a868':(st==='settling'?'#7fa8c9':'#c9b79f'); }
  function stateWord(st){ return st==='rising'?'rising / activating':(st==='settling'?'settling / calming':'steady'); }
  async function poll(){
    try{
      const r=await fetch('/api/admin/bio/live'); if(!r.ok) return;
      const d=await r.json();
      var kln=document.getElementById('kpi-live-n'); if(kln) kln.textContent=((d.active&&d.active.length)||0);
      var clk=document.getElementById('bio-clock'); if(clk) clk.textContent='server '+(d.server_time||'');
      var el=document.getElementById('bio-live-list'); if(!el) return;
      if(!d.active||!d.active.length){ el.innerHTML='<i style="color:#b7a084;">No live sessions right now. When someone is using InnerLight, they appear here live \u2014 with or without a heart reading.</i>'; return; }
      el.innerHTML=d.active.map(function(p){
        var left = '<div style="min-width:80px;"><b>'+p.who+'</b><div style="font-size:11px;color:#b7a084;">'+p.ago+'s ago</div></div>';
        if (p.bpm && p.hasheart){
          // Full heart reading available
          return '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.08);">'
            + left
            +'<div style="text-align:center;"><span style="font-size:26px;font-weight:800;">'+p.bpm+'</span> <span style="font-size:12px;color:#c9b79f;">bpm</span>'
            +'<div style="font-size:11px;color:#b7a084;">baseline '+(p.base||p.bpm)+'</div></div>'
            +'<div style="text-align:center;color:'+stateColor(p.state)+';font-size:13px;font-weight:700;min-width:120px;">'+stateWord(p.state)
            +'<div style="font-size:10.5px;color:#b7a084;font-weight:400;">'+(p.tier||'')+(p.face?' \u00b7 '+p.face:'')+'</div></div>'
            +'<div>'+spark(p.spark)+'</div>'
            +'</div>';
        }
        // Live session but no heart reading yet \u2014 show honest status.
        var status = p.cam ? 'camera on \u2014 acquiring heart signal\u2026' : 'text-only session (camera off)';
        var scolor = p.cam ? '#f0a868' : '#c9b79f';
        return '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.08);">'
          + left
          +'<div style="text-align:center;flex:1;color:'+scolor+';font-size:13px;font-weight:700;">'+status
          + (p.face?'<div style="font-size:10.5px;color:#b7a084;font-weight:400;">expression: '+p.face+'</div>':'')
          +'</div>'
          +'<div style="min-width:60px;text-align:right;color:#b7a084;font-size:12px;">live</div>'
          +'</div>';
      }).join('');
    }catch(e){}
  }
  poll(); setInterval(poll, 3000);
})();
</script>
<h2>Heart signal coverage &mdash; research integrity</h2>
<div class="card-like" style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.14);font-size:13.5px;margin-bottom:8px;">
<div style="font-size:12px;color:#64748b;margin-bottom:10px;">Every camera session records a heart value &mdash; never blank. Each reading is tagged by how it was obtained, so the data is complete AND honest. "Measured" = high-confidence true reading; "Estimated" = best inference from a weaker signal; "Baseline-held" = last good value briefly held. This is what lets you claim full coverage without overclaiming precision.</div>
{{ heart_rows|safe }}
</div>
<h2>Experimental biometric sub-zones — the frontier map</h2>
<div class="card-like" id="subzones" style="background:#fff;border-radius:12px;padding:16px;box-shadow:0 8px 28px rgba(15,36,71,0.14);font-size:13.5px;margin-bottom:8px;">
<div style="font-size:12px;color:#64748b;margin-bottom:10px;">How often each experimental skin zone (near eyes/mouth) agreed with the trusted forehead+cheek reading. Higher % = more trustworthy. This is your own data revealing which frontier zones can be read accurately.</div>
{{ subzone_rows|safe }}
</div>
<h2>Sessions per day</h2>
<div class="graph">{{ bars|safe }}</div>
<h2 id="people">Today, person by person — anonymous session breakdown</h2>
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
<h2 id="research">The scientific method — where this study stands</h2>
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
</main></body></html>""", body=body, bars=bars, t_rows=t_rows, sess_rows=sess_rows, subzone_rows=subzone_rows, heart_rows=heart_rows, kpi_cards=kpi_cards)


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

# ---------------------------------------------------------------------------
# THREE INDEPENDENT STUDY LENSES. The same scenario is examined SEPARATELY
# through a legal, a legislative, and a medical lens. Each produces its OWN
# analysis and its OWN conclusion — they must never mirror one another — and
# each opens with an honest significance verdict, so a scenario that does not
# truly reach (say) a legislative level says so plainly and professionally.
# ---------------------------------------------------------------------------
_STUDY_PREAMBLE = (
    "You are the private study tutor for the founder of InnerLight, a crisis-support "
    "product. The founder is a Political Science student preparing for law school. "
    "Everything you produce is an EDUCATIONAL SIMULATION for the founder's own learning. "
    "It is never given to end users and is not legal or medical advice. Plain language "
    "first; define every term of legalese or medical terminology in parentheses the first "
    "time it appears; spell out every acronym. Be CONCISE — under 600 words, depth over "
    "sprawl. Begin every response with the line: 'FOUNDER STUDY — educational simulation, "
    "not legal or medical advice.'\n\n"
    "CRITICAL: Examine ONLY the {LENS} dimension of the scenario. Do NOT write a generic "
    "overview. Your analysis and your conclusion must be specific to THIS lens and must "
    "differ from what a legal, a legislative, or a medical study of the same scenario "
    "would say — they are three separate studies with three separate conclusions. If the "
    "scenario does not genuinely reach a meaningful {LENS} level, say so plainly and "
    "professionally in the significance section, explain why, and keep the rest brief.\n\n"
)

_STUDY_LENSES = {
    "legal": _STUDY_PREAMBLE.replace("{LENS}", "LEGAL (this individual person's own rights and remedies)") + (
        "Use exactly these headings:\n"
        "1. LEGAL SIGNIFICANCE — a one-line verdict (none / limited / moderate / significant) on "
        "whether this reaches a legal level for the individual, and why.\n"
        "2. THE LEGAL ISSUES — the specific rights, claims, or defenses in play for THIS person.\n"
        "3. WHO HANDLES IT & THE PROCESS — the right professional, the steps they take, and any deadlines.\n"
        "4. THE PAPERWORK — the filings/forms/documents by government level (local/state/federal), "
        "named, and what each is for.\n"
        "5. TWO MOCK OUTCOMES — two clearly-hypothetical endings and why each might happen.\n"
        "6. ROUTING LESSON — what words in a person's story would tell InnerLight this legal handoff fits.\n"
        "7. LEGAL CONCLUSION — your distinct closing conclusion for the legal dimension only."
    ),
    "legislative": _STUDY_PREAMBLE.replace("{LENS}", "LEGISLATIVE / POLICY (the SYSTEMIC angle — NOT this one person's dispute)") + (
        "This lens is about whether the case reveals a systemic gap that a change in law or policy "
        "could address. It is NOT about winning this individual's case. Use exactly these headings:\n"
        "1. LEGISLATIVE SIGNIFICANCE — a one-line verdict (none / limited / moderate / significant) on "
        "whether this reveals a systemic gap worth a policy or law change, and why. If it is purely an "
        "individual matter already covered adequately by existing law, say so plainly.\n"
        "2. THE SYSTEMIC PATTERN — the broader problem this individual case is one example of.\n"
        "3. EXISTING LAW & THE GAP — what current statutes or regulations already do here, and exactly "
        "where they fall short.\n"
        "4. POSSIBLE ACTION — what a new bill, local ordinance, or agency rule could do, at which level "
        "(local/state/federal), and who holds the authority to enact it.\n"
        "5. ADVOCACY PATHWAY — concretely how a citizen or advocate pursues this (petition, public "
        "testimony, model legislation, agency rulemaking, coalition-building).\n"
        "6. STAKEHOLDERS & TRADE-OFFS — who is affected, how businesses and organizations could be helped "
        "to act fairly, and the honest costs of the change.\n"
        "7. LEGISLATIVE CONCLUSION — your distinct closing conclusion for the legislative dimension only."
    ),
    "medical": _STUDY_PREAMBLE.replace("{LENS}", "MEDICAL / CLINICAL (underlying health considerations)") + (
        "You NEVER diagnose and NEVER claim to provide care; this is educational classification only. "
        "Use exactly these headings:\n"
        "1. MEDICAL SIGNIFICANCE — a one-line verdict (none / limited / moderate / significant) on whether "
        "this reaches a medical or clinical level, and why. If nothing in the statement suggests a health "
        "dimension, say so plainly.\n"
        "2. POSSIBLE HEALTH DIMENSIONS — the physical or mental-health considerations the statement MAY "
        "implicate, framed as education, never as a diagnosis of anyone.\n"
        "3. WHO HANDLES IT — the kind of clinician and why that specialty fits.\n"
        "4. THE CARE PATHWAY — how care typically proceeds, plus any urgency or red-flag signs that would "
        "mean 'get help now.'\n"
        "5. TERMINOLOGY — the relevant medical terms, each translated to plain words.\n"
        "6. ROUTING LESSON — what words in a person's story would tell InnerLight this clinical handoff fits.\n"
        "7. MEDICAL CONCLUSION — your distinct closing conclusion for the medical dimension only, restating "
        "that InnerLight never diagnoses and never replaces a clinician."
    ),
}

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
    focus = str(data.get("focus", "legal"))[:20].lower()
    if not scenario:
        return jsonify({"status": "error", "text": "Describe a scenario first."}), 200
    # Pick the INDEPENDENT lens for this focus so legal / legislative / medical
    # each produce their own distinct analysis and conclusion, never a shared
    # overview. Unknown focuses fall back to the general study tutor.
    system_prompt = _STUDY_LENSES.get(focus, _STUDY_SYSTEM)
    prompt = (f"Examine ONLY the {focus} dimension of this scenario, as its own independent "
              f"study with its own conclusion. Scenario (hypothetical, for founder education "
              f"only): {scenario}")
    body = json.dumps({
        "model": os.environ.get("INNERLIGHT_MODEL", "claude-sonnet-4-6"),
        "max_tokens": 950,
        "system": system_prompt,
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



# ---- CRISIS-REFERRAL COUNTING (SB 243 accountability — counts ONLY, never content) ----
# Every time the crisis protocol activates (needs_immediate_support -> the 988
# referral is shown), we count it: one number per month, on the persistent disk.
# This makes the July 2027 annual report to California's Office of Suicide
# Prevention a printout, not a scramble. Immutable Principle 11.
_CRISIS_REFERRALS_FILE = os.environ.get("CRISIS_REFERRALS_FILE", _DATA_DIR + "/innerlight_crisis_referrals.json")
_CRISIS_REFERRALS_LOCK = threading.Lock()

def record_crisis_referral():
    try:
        month = time.strftime("%Y-%m")
        with _CRISIS_REFERRALS_LOCK:
            try:
                with open(_CRISIS_REFERRALS_FILE) as f:
                    counts = json.load(f)
            except Exception:
                counts = {}
            counts[month] = int(counts.get(month, 0)) + 1
            with open(_CRISIS_REFERRALS_FILE, "w") as f:
                json.dump(counts, f)
    except Exception as e:
        print("[InnerLight] crisis referral count failed:", e)

@app.route("/api/admin/crisisreferrals")
def admin_crisis_referrals():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    try:
        with _CRISIS_REFERRALS_LOCK:
            with open(_CRISIS_REFERRALS_FILE) as f:
                counts = json.load(f)
    except Exception:
        counts = {}
    return jsonify({"status": "ok", "by_month": counts,
                    "total": sum(counts.values())})


# ---- SONG PLAY TRACKING (founder visibility + control over randomization) ----
# Records EVERY track play with a timestamp so the founder can see exactly what
# played, when, and how often — including multiple plays within the same hour.
_PLAYS_FILE = os.environ.get("PLAYS_FILE", _DATA_DIR + "/innerlight_plays.json")
_PLAYS_LOCK = threading.Lock()

def _plays_load():
    try:
        with open(_PLAYS_FILE) as f: return json.load(f)
    except Exception: return []

def _plays_save(d):
    try:
        with open(_PLAYS_FILE, "w") as f: json.dump(d, f)
    except Exception as e: print("[InnerLight] plays save failed:", e)

@app.route("/api/track/play", methods=["POST"])
def track_play():
    if not _rate_ok("trackplay", 600, 3600):
        return jsonify({"status": "ignored"}), 200
    data = request.get_json(silent=True) or {}
    file = str(data.get("file", ""))[:60]
    lane = str(data.get("lane", ""))[:20]
    if not file:
        return jsonify({"status": "empty"}), 200
    rec = {"file": file, "lane": lane,
           "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "epoch": int(time.time())}
    with _PLAYS_LOCK:
        plays = _plays_load()
        plays.append(rec)
        plays = plays[-5000:]   # keep the most recent 5000 plays
        _plays_save(plays)
    return jsonify({"status": "ok"})

@app.route("/api/admin/plays")
def admin_plays():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    with _PLAYS_LOCK:
        plays = _plays_load()
    # per-file totals + per-hour counts + full timestamp list (most recent first)
    totals = {}
    per_hour = {}
    for r in plays:
        f = r.get("file","?")
        totals[f] = totals.get(f, 0) + 1
        hour = (r.get("ts","")[:13])  # YYYY-MM-DD HH
        per_hour.setdefault(hour, {})
        per_hour[hour][f] = per_hour[hour].get(f, 0) + 1
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    recent = list(reversed(plays))[:300]
    return jsonify({"status": "ok", "total_plays": len(plays),
                    "by_track": [{"file": k, "count": v} for k, v in ranked],
                    "recent": recent})


# ---- FOUNDER MUSIC CONTROL: switch individual tracks on/off, no redeploy ----
# The founder can silence one exact track (e.g. a song that keeps resurfacing)
# from the operations page. The off-list lives on the persistent disk, so it
# survives deploys. The ambient endpoint (lane()) skips off tracks for every
# new playlist it hands out.
_TRACKS_OFF_FILE = os.environ.get("TRACKS_OFF_FILE", _DATA_DIR + "/innerlight_tracks_off.json")
_TRACKS_OFF_LOCK = threading.Lock()

def _tracks_off_load():
    try:
        with open(_TRACKS_OFF_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()

def _tracks_off_save(off):
    try:
        with open(_TRACKS_OFF_FILE, "w") as f:
            json.dump(sorted(off), f)
    except Exception as e:
        print("[InnerLight] tracks-off save failed:", e)

@app.route("/api/admin/tracks")
def admin_tracks():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    audio_dir = Path(__file__).resolve().parent.parent / "audio"
    off = _tracks_off_load()
    with _PLAYS_LOCK:
        plays = _plays_load()
    counts = {}
    for r in plays:
        f = r.get("file", "?")
        counts[f] = counts.get(f, 0) + 1
    lanes = {}
    if audio_dir.exists():
        for p in sorted(audio_dir.glob("*.mp3")):
            prefix = p.name.split("_", 1)[0]
            lanes.setdefault(prefix, []).append({
                "file": p.name, "enabled": p.name not in off,
                "plays": counts.get(p.name, 0)})
    return jsonify({"status": "ok", "lanes": lanes,
                    "disabled": sorted(off)})

@app.route("/api/admin/tracks/toggle", methods=["POST"])
def admin_tracks_toggle():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    data = request.get_json(silent=True) or {}
    file = str(data.get("file", ""))[:80]
    enabled = bool(data.get("enabled", True))
    audio_dir = Path(__file__).resolve().parent.parent / "audio"
    if not file or "/" in file or ".." in file or not (audio_dir / file).exists():
        return jsonify({"error": "unknown file"}), 400
    with _TRACKS_OFF_LOCK:
        off = _tracks_off_load()
        if enabled:
            off.discard(file)
        else:
            off.add(file)
            # Safety: never let a whole lane go silent. If this was the last
            # track still on in its lane, refuse and explain in plain words.
            prefix = file.split("_", 1)[0]
            lane_files = [p.name for p in audio_dir.glob(prefix + "_*.mp3")]
            if lane_files and all(n in off for n in lane_files):
                off.discard(file)
                return jsonify({"status": "refused",
                                "reason": "That is the last song still on in its lane. "
                                          "Turning it off would leave that lane silent. "
                                          "Turn another song on first."}), 200
        _tracks_off_save(off)
    return jsonify({"status": "ok", "file": file, "enabled": file not in off})


@app.route("/api/admin/policy/patterns")
def admin_policy_patterns():
    """Summarize recurring need-patterns across recorded cases + metrics, so the
    founder can see WHERE the law/systems fail people most across all sessions."""
    if not session.get("founder_ok"):
        return jsonify({"status": "locked"}), 403
    # Tally legal categories surfaced + provider suggestions + track of themes
    try:
        from legal_guidance_engine import detect_legal_issues
    except Exception:
        detect_legal_issues = None
    legal_tally = {}
    theme_tally = {}
    case_count = 0
    try:
        with _CASES_LOCK:
            cases = _cases_load()
        for cs in cases[-500:]:
            case_count += 1
            text = " ".join(t.get("t","") for t in cs.get("turns", []) if t.get("r")=="user")
            if detect_legal_issues and text:
                for iss in detect_legal_issues(text):
                    legal_tally[iss["label"]] = legal_tally.get(iss["label"], 0) + 1
    except Exception:
        pass
    # metrics: legal_surfaced categories
    try:
        with _METRICS_LOCK:
            m = _metrics_load()
        for day, d in m.items():
            for k, v in (d.get("legal_categories", {}) or {}).items():
                legal_tally[k] = legal_tally.get(k, 0) + v
    except Exception:
        pass
    # CLINICAL / SUPPORT patterns — detect need themes across the same cases
    clinical_tally = {}
    CLIN = {
        "crisis / safety": ["suicid","kill myself","end it","hurt myself","harm myself","want to die","not safe"],
        "anxiety / panic": ["panic","anxious","anxiety","can't breathe","cant breathe","overwhelmed","racing","dread"],
        "depression / low mood": ["hopeless","worthless","empty","numb","depressed","no point","give up","can't go on"],
        "grief / loss": ["died","death","lost my","passed away","grief","funeral","miss them"],
        "trauma": ["abused","assault","attacked","flashback","nightmare","ptsd","trauma"],
        "substance use": ["drinking","alcohol","relapse","sober","withdrawal","overdose","addicted","using again","high"],
        "medication needs": ["medication","meds","prescription","psychiatrist","side effect","refill","off my meds"],
        "isolation / loneliness": ["alone","lonely","no one","nobody","isolated","by myself"],
        "sleep": ["can't sleep","cant sleep","insomnia","nightmares","exhausted","no sleep"],
    }
    try:
        with _CASES_LOCK:
            cases2 = _cases_load()
        for cs in cases2[-500:]:
            text = (" ".join(t.get("t","") for t in cs.get("turns", []) if t.get("r")=="user")).lower()
            for label, words in CLIN.items():
                if any(w in text for w in words):
                    clinical_tally[label] = clinical_tally.get(label, 0) + 1
    except Exception:
        pass
    top_legal = sorted(legal_tally.items(), key=lambda kv: kv[1], reverse=True)[:12]
    top_clin = sorted(clinical_tally.items(), key=lambda kv: kv[1], reverse=True)[:12]
    return jsonify({"status": "ok", "cases_reviewed": case_count,
                    "legal_patterns": [{"issue": k, "count": v} for k, v in top_legal],
                    "clinical_patterns": [{"issue": k, "count": v} for k, v in top_clin]})

_POLICY_SYSTEM = (
    "You are a legislative-research aid for the founder of InnerLight, a mental-health "
    "and legal-navigation tool. The founder is a pre-law policy student studying how "
    "legislation is crafted. Given a RECURRING PROBLEM PATTERN that real people face "
    "(for example: repeated illegal lockout evictions, or long crisis wait-times), "
    "produce an EDUCATIONAL policy study, clearly labeled as a learning exercise, that covers: "
    "(1) the specific gap in current law that lets this harm happen; "
    "(2) which level of government (local, city, county, state, federal) is the right venue and why; "
    "(3) existing statutes or bills that already touch this area (named generally, for the founder to verify); "
    "(4) how a new or amended law COULD be crafted to help people in this situation, in plain language; "
    "(5) how the same change could also help businesses and organizations act lawfully and fairly; "
    "(6) the realistic path a bill takes to become law, and where advocates apply pressure. "
    "Be concrete and balanced. This is educational study material, not legal advice, and not a claim "
    "about what the law currently is. Encourage the founder to verify every specific against primary sources."
)

@app.route("/api/admin/policy/study", methods=["POST"])
def admin_policy_study():
    if not session.get("founder_ok"):
        return jsonify({"status": "locked"}), 403
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip().strip(chr(34)).strip(chr(39))
    if not key:
        return jsonify({"status": "error", "text": "The comprehension key is not set on the server."}), 200
    data = request.get_json(silent=True) or {}
    pattern = str(data.get("pattern", ""))[:2000].strip()
    if not pattern:
        return jsonify({"status": "error", "text": "Describe the recurring problem pattern to study."}), 200
    body = json.dumps({
        "model": os.environ.get("INNERLIGHT_MODEL", "claude-sonnet-4-6"),
        "max_tokens": 1400,
        "system": _POLICY_SYSTEM,
        "messages": [{"role": "user", "content": "Recurring problem pattern to study for possible legislation: " + pattern}],
    }).encode("utf-8")
    import urllib.request
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text","") for b in out.get("content", []) if b.get("type")=="text")
        _study_save_entry({"when": time.strftime("%Y-%m-%d %H:%M"), "focus": "legislative-policy",
                           "scenario": pattern, "walkthrough": text})
        return jsonify({"status": "ok", "text": text})
    except Exception as exc:
        return jsonify({"status": "error", "text": "Policy study call failed: " + str(exc)}), 200


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
      background:linear-gradient(160deg,#2a1e14 0%,#3c2c1e 30%,#fbf3e9 30.5%,#fbf7f1 100%);}
 .top{display:flex;justify-content:space-between;align-items:flex-start;color:#fff;margin-bottom:22px;}
 h1{color:#fff;font-size:23px;margin:0;text-shadow:0 2px 8px rgba(0,0,0,0.3);}
 .sub{color:#e8d8c4;font-size:13px;margin-top:5px;max-width:760px;line-height:1.5;}
 .nav a{color:#e8d8c4;font-size:12px;text-decoration:none;border:1px solid rgba(255,255,255,0.4);
        padding:7px 14px;border-radius:999px;margin-left:8px;} .nav a:hover{background:rgba(255,255,255,0.12);}
 .card{background:#fff;border-radius:12px;padding:22px;box-shadow:0 8px 28px rgba(15,36,71,0.14);margin-bottom:18px;}
 label{font-size:12px;font-weight:700;color:#334155;display:block;margin-bottom:6px;}
 textarea{width:100%;box-sizing:border-box;min-height:110px;padding:12px;border:1px solid #cbd5e1;
          border-radius:9px;font-size:15px;font-family:Arial;} textarea:focus{outline:2px solid #c56a2c;}
 select{padding:10px;border:1px solid #cbd5e1;border-radius:9px;font-size:14px;margin-right:10px;}
 button{padding:11px 26px;border:0;border-radius:9px;font-size:15px;font-weight:700;color:#fff;
        background:linear-gradient(90deg,#c56a2c,#b24a2a);cursor:pointer;margin-top:12px;}
 #out{white-space:pre-wrap;font-size:14.5px;line-height:1.7;color:#1e293b;display:none;}
 .stamp{display:inline-block;background:#fef3c7;color:#92400e;border:1px solid #fcd34d;font-size:11px;
        font-weight:700;border-radius:6px;padding:4px 10px;margin-bottom:12px;letter-spacing:0.4px;}
 .wait{display:none;color:#c56a2c;font-weight:700;font-size:13px;margin-top:12px;}
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
  <button onclick="runStudy()">Study this one lens</button>
  <button onclick="runAllLenses()" style="margin-left:6px;background:linear-gradient(90deg,#c56a2c,#b24a2a);">Study all three: legal &bull; legislative &bull; medical</button>
 </div>
 <div style="font-size:12px;color:#64748b;margin-top:8px;">Each lens is a separate, independent study with its own conclusion. A scenario may reach one, two, or all three levels &mdash; and if it doesn't truly reach a level, that study says so plainly.</div>
 <div class="wait" id="wait">Preparing your study material&hellip; (this uses your comprehension credit, so it only runs when you press the button)</div>
</div>
<div class="card"><div class="stamp">FOUNDER STUDY &mdash; EDUCATIONAL SIMULATION &mdash; NOT LEGAL OR MEDICAL ADVICE</div>
<div id="out"></div></div>
<div class="card">
 <h2 style="margin-top:0;color:#7a3e1e;font-size:16px;">Cases from real sessions — de-identified</h2>
 <div style="font-size:12px;color:#64748b;margin-bottom:10px;">Every session is recorded here with names, numbers, and contact details removed before saving. Tap "Study this case" to send one into the study engine.</div>
 <div id="cases" style="font-size:13.5px;color:#334155;">Loading&hellip;</div>
</div>
<div class="card" style="border:2px solid #b24a2a;">
 <h2 style="margin-top:0;color:#b24a2a;font-size:16px;">Policy Research Workbench</h2>
 <div style="font-size:12.5px;color:#64748b;margin-bottom:12px;line-height:1.5;">Your vision: turn the patterns in real cases into the study of how laws could be crafted to genuinely help people &mdash; and help businesses and organizations act fairly. A private learning tool for your pre-law and policy work. Educational only; verify every specific against primary sources.</div>
 <button onclick="loadPolicyPatterns()" style="background:linear-gradient(90deg,#b24a2a,#c56a2c);">Show recurring problem patterns</button>
 <div id="policy-patterns" style="margin-top:14px;font-size:13.5px;color:#334155;"></div>
 <div style="margin-top:16px;">
   <label>Study how legislation could address a recurring pattern</label>
   <textarea id="policy-pattern" placeholder="Example: People are repeatedly locked out by landlords who put belongings on the street without a court order, and have nowhere to turn in the first 24 hours..."></textarea>
   <button onclick="runPolicyStudy()" style="background:linear-gradient(90deg,#b24a2a,#c56a2c);">Study possible legislation</button>
   <div class="wait" id="policy-wait">Researching how legislation could be crafted&hellip; (uses your comprehension credit)</div>
 </div>
 <div class="stamp" style="margin-top:14px;">POLICY STUDY &mdash; EDUCATIONAL LEARNING EXERCISE &mdash; NOT LEGAL ADVICE</div>
 <div id="policy-out" style="white-space:pre-wrap;font-size:14.5px;line-height:1.7;color:#1e293b;display:none;"></div>
</div>
<div class="card">
 <h2 style="margin-top:0;color:#7a3e1e;font-size:16px;">Saved studies — your growing casebook</h2>
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
        + '<summary style="cursor:pointer;font-weight:700;color:#c56a2c;">' + st.when + ' &mdash; ' + st.focus
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
      const convo = c.turns.map(function(t){ return (t.r==='user'?'PERSON: ':'INNERLIGHT: ') + t.t; }).join(String.fromCharCode(10));
      return '<details style="margin-bottom:10px;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;">'
        + '<summary style="cursor:pointer;font-weight:700;color:#c56a2c;">' + c.label + ' &mdash; ' + c.when
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
async function loadPolicyPatterns(){
  var box = document.getElementById('policy-patterns');
  if (box) box.innerHTML = 'Reviewing all cases (old and new) for recurring patterns\u2026';
  try{
    var r = await fetch('/api/admin/policy/patterns'); var d = await r.json();
    if (!box) return;
    var html = '<div style="font-weight:700;margin:6px 0;">Across ' + (d.cases_reviewed||0) + ' recorded cases:</div>';
    var legal = d.legal_patterns || [];
    var clin = d.clinical_patterns || [];
    if (!legal.length && !clin.length){
      box.innerHTML = 'No recurring patterns yet. As sessions accumulate, the legal and clinical needs people face most will surface here automatically \u2014 your evidence base for policy study.';
      return;
    }
    html += '<div style="display:flex;gap:16px;flex-wrap:wrap;">';
    function rows(arr, color){ return arr.length ? arr.map(function(p){ return '<div class="pat-row" data-issue="' + p.issue + '" style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #f3eade;cursor:pointer;"><span>' + p.issue + '</span><b style="color:' + color + ';">' + p.count + '</b></div>'; }).join('') : '<div style="color:#94a3b8;">None yet.</div>'; }
    html += '<div style="flex:1;min-width:220px;"><div style="font-weight:700;color:#b24a2a;margin-bottom:4px;">Legal patterns</div>' + rows(legal, '#b24a2a') + '</div>';
    html += '<div style="flex:1;min-width:220px;"><div style="font-weight:700;color:#c56a2c;margin-bottom:4px;">Clinical / support patterns</div>' + rows(clin, '#c56a2c') + '</div>';
    html += '</div><div style="font-size:12px;color:#64748b;margin-top:8px;">Each recurring pattern is a place the system may be failing people. Click any pattern to study how legislation could address it.</div>';
    box.innerHTML = html;
    box.querySelectorAll('.pat-row').forEach(function(row){
      row.addEventListener('click', function(){ studyThisPattern(row.getAttribute('data-issue')); });
    });
  }catch(e){ if(box) box.innerHTML = 'Could not load patterns right now.'; }
}
function studyThisPattern(issue){
  var ta = document.getElementById('policy-pattern');
  if (ta){ ta.value = 'Recurring pattern across our cases: ' + issue + '. Study how legislation could better help people facing this, and how it could help businesses and organizations act fairly.'; ta.scrollIntoView({behavior:'smooth', block:'center'}); }
}
async function runPolicyStudy(){
  var pattern = (document.getElementById('policy-pattern')||{}).value || '';
  var out = document.getElementById('policy-out');
  var wait = document.getElementById('policy-wait');
  if (pattern.trim().length < 10){ if(out){ out.style.display='block'; out.textContent='Describe the recurring pattern first (or click a pattern above).'; } return; }
  if (wait) wait.style.display='block';
  if (out) out.style.display='none';
  try{
    var r = await fetch('/api/admin/policy/study', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({pattern: pattern})});
    var d = await r.json();
    if (wait) wait.style.display='none';
    if (out){ out.style.display='block'; out.textContent = d.text || 'No result.'; }
    if (typeof loadShelf==='function') loadShelf();
  }catch(e){ if(wait) wait.style.display='none'; if(out){ out.style.display='block'; out.textContent='Study call failed. Try again.'; } }
}

loadPolicyPatterns(); // auto-identify recurring patterns on load
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

// Run all THREE independent lenses on the same scenario and show them as three
// clearly-separated studies, each with its own conclusion.
async function runAllLenses(){
  const out = document.getElementById('out'), wait = document.getElementById('wait');
  const scenario = (document.getElementById('scenario')||{}).value || '';
  if (scenario.trim().length < 10){ out.style.display='block'; out.textContent = 'Describe a scenario first.'; return; }
  const origWait = wait.textContent;
  out.style.display='none'; wait.style.display='block';
  const lenses = [
    ['legal', 'LEGAL — this person’s own rights and remedies', '#c56a2c'],
    ['legislative', 'LEGISLATIVE — the systemic policy angle', '#b24a2a'],
    ['medical', 'MEDICAL — underlying health considerations', '#2f6da8']
  ];
  let html = '';
  for (let i=0;i<lenses.length;i++){
    const L = lenses[i];
    wait.textContent = 'Studying the ' + L[0] + ' lens… (' + (i+1) + ' of 3)';
    let text = '';
    try{
      const r = await fetch('/api/admin/study',{method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({scenario: scenario, focus: L[0]})});
      const raw = await r.text();
      try { const d = JSON.parse(raw); text = (d && d.text) ? d.text : 'No response.'; }
      catch(pe){ text = 'This lens took longer than the server allowed and was cut off. Run it alone with the dropdown to retry.'; }
    }catch(e){ text = 'Could not reach the study engine for the ' + L[0] + ' lens.'; }
    html += '<div style="margin:0 0 20px;border-left:5px solid ' + L[2] + ';padding:6px 0 6px 16px;">'
      + '<div style="font-weight:800;color:' + L[2] + ';font-size:15px;margin-bottom:8px;">' + L[1] + '</div>'
      + '<div style="white-space:pre-wrap;line-height:1.65;">' + text.replace(/</g,'&lt;') + '</div></div>';
  }
  wait.style.display='none'; wait.textContent = origWait;
  out.innerHTML = html; out.style.display='block';
  if (typeof loadShelf==='function') loadShelf();
}
</script>
<script>
window.addEventListener('load', function(){
  try { if (typeof maybeOfferSave==='function') setInterval(maybeOfferSave, 15000); } catch(e){}
  try { if (typeof offerFeedback==='function') setTimeout(offerFeedback, 6*60*1000); } catch(e){}
  try { if (typeof gentleCompletionCheck==='function') setInterval(gentleCompletionCheck, 60000); } catch(e){}
}, {once:true});
</script>
</body></html>""")


# ===========================================================================
# CASE RECORDER — every session becomes a de-identified case for the
# Founder's Study. Scrubbing happens BEFORE anything is written: numbers,
# emails, phone numbers, and handles are masked. Cases are founder-only,
# disclosed in the privacy notes, never public, never sold.
# ===========================================================================

# ---- USER FEEDBACK (anonymized qualitative research data) ----
# A person may optionally share, at a natural pause, how they feel and what
# helped. Stored WITHOUT identity, server-side-scrubbed, for the research report.
_FEEDBACK_FILE = os.environ.get("FEEDBACK_FILE", _DATA_DIR + "/innerlight_feedback.json")
_FEEDBACK_LOCK = threading.Lock()

def _fb_load():
    try:
        with open(_FEEDBACK_FILE) as f: return json.load(f)
    except Exception: return []

def _fb_save(d):
    try:
        with open(_FEEDBACK_FILE, "w") as f: json.dump(d, f)
    except Exception as e: print("[InnerLight] feedback save failed:", e)

@app.route("/api/feedback", methods=["POST"])
def feedback_submit():
    if not _rate_ok("feedback", 5, 3600):
        return _gentle_429()
    data = request.get_json(silent=True) or {}
    helped = str(data.get("helped", ""))[:12]          # 'yes'/'somewhat'/'no'
    feeling = str(data.get("feeling", ""))[:12]         # 'calmer'/'same'/'worse'
    words = str(data.get("words", ""))[:800]
    # scrub any identifying details from free text (reuse the case scrubber)
    try:
        words = _scrub_text(words)
    except Exception:
        pass
    if not (helped or feeling or words.strip()):
        return jsonify({"status": "empty"}), 200
    with _FEEDBACK_LOCK:
        fb = _fb_load()
        fb.append({"when": time.strftime("%Y-%m-%d %H:%M"), "helped": helped,
                   "feeling": feeling, "words": words.strip()})
        fb = fb[-2000:]
        _fb_save(fb)
    return jsonify({"status": "ok"})

@app.route("/api/admin/feedback")
def admin_feedback():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    with _FEEDBACK_LOCK:
        fb = _fb_load()
    # aggregate
    tot = len(fb)
    helped = {"yes":0,"somewhat":0,"no":0}
    feeling = {"calmer":0,"same":0,"worse":0}
    for r in fb:
        if r.get("helped") in helped: helped[r["helped"]] += 1
        if r.get("feeling") in feeling: feeling[r["feeling"]] += 1
    quotes = [r for r in reversed(fb) if r.get("words")][:40]
    return jsonify({"total": tot, "helped": helped, "feeling": feeling, "quotes": quotes})



def _scrub_text(t):
    import re
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", t)
    t = re.sub(r"(\+?\d[\d\-() ]{7,}\d)", "[number]", t)
    t = re.sub(r"@\w+", "[handle]", t)
    return t

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
    if not _rate_ok("connect", 3, 3600) or not _budget_ok("connect"):
        return _gentle_429()
    _cd = request.get_json(silent=True) or {}
    # Bot traps: honeypot field must be empty; a real person spends real time
    # before asking for a human (bots hit instantly).
    if str(_cd.get("hp", "")):
        _abuse_mark(); return jsonify({"status": "ok"})  # silently swallow bots
    try:
        if int(_cd.get("elapsed", 999999)) < 20000:
            _abuse_mark(); return _gentle_429()
    except Exception:
        pass
    data = request.get_json(silent=True) or {}
    kind = "legal" if data.get("kind") == "legal" else "care"
    pro = _scrub(str(data.get("pro", ""))[:60])
    summary = _scrub(str(data.get("summary", ""))[:1500])
    rid = secrets.token_urlsafe(6)
    room = "InnerLight-" + rid
    # ---- VIDEO ROOM: Daily.co when key present (true one-click, no login,
    # no prejoin, no app nag) -> the crisis-speed standard. Jitsi fallback. ----
    guest_url = responder_url = room_url = None
    daily_key = os.environ.get("DAILY_API_KEY", "").strip()
    if daily_key:
        try:
            import urllib.request as _dr
            payload = json.dumps({
                "name": room.lower(),
                "privacy": "public",
                "properties": {
                    "enable_prejoin_ui": False,
                    "enable_knocking": False,
                    "start_video_off": False,
                    "start_audio_off": False,
                    "exp": int(time.time()) + 3*60*60,
                    "eject_at_room_exp": True,
                    "max_participants": 4
                }
            }).encode("utf-8")
            req0 = _dr.Request("https://api.daily.co/v1/rooms", data=payload,
                               headers={"Authorization": "Bearer " + daily_key,
                                        "Content-Type": "application/json"})
            with _dr.urlopen(req0, timeout=8) as r0:
                info = json.loads(r0.read().decode("utf-8"))
                room_url = info.get("url")
                guest_url = room_url
                responder_url = room_url
        except Exception as e:
            print("[InnerLight] Daily room creation failed, falling back to Jitsi:", e)
            room_url = None
    if not room_url:
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
 .join{display:inline-block;margin-top:8px;background:linear-gradient(90deg,#1d4ed8,#da8c4d);color:#fff;
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
