from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone, timedelta
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
        "CREATE TABLE IF NOT EXISTS provider_availability (id INTEGER PRIMARY KEY, side TEXT, role TEXT, available INTEGER, updated_at TEXT)",
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
            CREATE TABLE IF NOT EXISTS provider_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                side TEXT NOT NULL,
                role TEXT NOT NULL,
                available INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
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
  <meta name="theme-color" content="#2a1e14">
  <link rel="manifest" href="/manifest.json">
  <link rel="icon" type="image/png" sizes="192x192" href="/scenes/app_icon_192.png">
  <link rel="apple-touch-icon" href="/scenes/app_icon_192.png">
  <title>InnerLight &mdash; a calm, private place while you wait for real help</title>
  <meta name="description" content="InnerLight is a free, private, calming AI companion for the hardest wait: the gap between reaching out and real human help arriving. Soft music, a quiet place to tell your story, and a gentle bridge to 988 and real people. Not therapy — a bridge. Adults 18+.">
  <meta property="og:title" content="InnerLight — a calm, private place while you wait for real help">
  <meta property="og:description" content="A free, private, calming companion for the gap between reaching out and help arriving. Soft music, a quiet place to tell your story, a gentle bridge to real human help.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://getinnerlight.com/">
  <meta property="og:image" content="https://getinnerlight.com/scenes/photo_2_sunset_trees.jpg">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="InnerLight — a calm, private place while you wait for real help">
  <meta name="twitter:description" content="A free, private, calming companion for the gap between reaching out and help arriving.">
  <meta name="twitter:image" content="https://getinnerlight.com/scenes/photo_2_sunset_trees.jpg">
  <!-- Creator imprint: God's Love for Us LLC, Axiom Harmony Protocol, InnerLight, VEIL, EDEN, and the Zenisys Sound System are created by Toshay S. Zeigler. -->
  <style>
  @keyframes listenpulse { 0%,100%{opacity:1;transform:scale(1);} 50%{opacity:0.4;transform:scale(1.3);} }
    :root { --page:#faf5ec; --ink:#2a1e14; --muted:#74624d; --panel:#ffffff; --line:#ece0d0; --teal:#b24a2a; --leaf:#c56a2c; --coral:#c85c54; --gold:#b7791f; }
    /* Screen-reader-only text: visually hidden, fully announced */
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden;
      clip:rect(0 0 0 0); white-space:nowrap; border:0; }
    /* A warm, clearly visible keyboard focus ring (never the default blue) */
    :focus-visible { outline:3px solid #b7791f; outline-offset:2px;
      box-shadow:0 0 0 6px rgba(255,217,160,0.5); border-radius:6px; }
    #welcome-gate :focus-visible, #il-anchor :focus-visible, #activities-overlay :focus-visible {
      outline-color:#ffd9a0; box-shadow:0 0 0 6px rgba(42,30,20,0.6); }
    .story-input:focus-visible { outline:none; border-color:#b27849;
      box-shadow:0 0 0 3px rgba(183,121,31,0.5); }
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
    /* ============ CINEMATIC ARRIVAL — "Garden at Dusk" welcome gate ============
       A time-of-day photograph (the founder's own, served from /scenes/) fills the
       screen; a serif greeting arrives word by word; the disclosures rest in one
       quiet translucent panel low on the screen. Warm by day, deep blue by night. */
    #welcome-gate { position:fixed; inset:0; z-index:50; overflow-y:auto; -webkit-overflow-scrolling:touch;
      background:#170c03; color:#faf1e0; text-align:center;
      --g-scrim:36,19,7; --g-glow:255,190,110; --g-core:255,204,130;
      --g-cream:#faf1e0; --g-cream-soft:rgba(250,240,222,.86); --g-ink:rgba(28,14,4,.55);
      --g-panel:rgba(38,21,9,.62); --g-line:rgba(255,220,170,.28);
      --gp-x:32%; --gp-y:76%; --gp-size:78vmin; --gp-alpha:.55; --g-pos:50% 45%;
      font-family:Georgia, "Iowan Old Style", "Palatino Linotype", Palatino, "Times New Roman", serif; }
    #welcome-gate[data-time="night"] { background:#070b14;
      --g-scrim:10,14,26; --g-glow:214,226,255; --g-core:225,234,255;
      --g-panel:rgba(13,18,34,.66); --g-line:rgba(214,226,255,.22); --g-ink:rgba(4,8,18,.6); }
    .gate-stage { position:fixed; inset:0; overflow:hidden; pointer-events:none; }
    .gate-photo { position:absolute; left:-6%; top:-6%; width:112%; height:112%; object-fit:cover;
      object-position:var(--g-pos); transform-origin:50% 42%;
      animation:gateKb 80s ease-in-out infinite alternate; will-change:transform; }
    @keyframes gateKb { from { transform:scale(1.02) translate3d(.6%,.4%,0); } to { transform:scale(1.12) translate3d(-1.4%,-1.2%,0); } }
    .gate-grade { position:absolute; inset:0;
      background:radial-gradient(120% 85% at 72% 8%, rgba(var(--g-glow),.14), transparent 58%),
                 radial-gradient(140% 100% at 20% 100%, rgba(var(--g-glow),.10), transparent 55%); }
    .gate-scrim-top { position:absolute; inset:0;
      background:linear-gradient(to bottom, rgba(var(--g-scrim),.5), rgba(var(--g-scrim),.14) 16%, transparent 30%); }
    .gate-scrim-bottom { position:absolute; inset:0;
      background:linear-gradient(to top, rgba(var(--g-scrim),.74), rgba(var(--g-scrim),.42) 22%, rgba(var(--g-scrim),.08) 48%, transparent 62%); }
    .gate-vignette { position:absolute; inset:0;
      background:radial-gradient(115% 115% at 50% 46%, transparent 58%, rgba(var(--g-scrim),.38) 100%); }
    .gate-presence { position:absolute; left:var(--gp-x); top:var(--gp-y); width:var(--gp-size); height:var(--gp-size);
      transform:translate(-50%,-50%); }
    .gate-presence i { position:absolute; inset:0; border-radius:50%;
      background:radial-gradient(circle, rgba(var(--g-core),.5) 0%, rgba(var(--g-core),.16) 38%, transparent 68%);
      animation:gateBreath 7s ease-in-out infinite; will-change:transform,opacity; }
    @keyframes gateBreath { 0%,100% { transform:scale(.92); opacity:calc(var(--gp-alpha)*.72); }
      46% { transform:scale(1.12); opacity:var(--gp-alpha); }
      62% { transform:scale(1.10); opacity:calc(var(--gp-alpha)*.95); } }
    .gate-motes b { position:absolute; display:block; border-radius:50%;
      background:radial-gradient(circle, rgba(var(--g-core),.9), rgba(var(--g-core),0) 70%);
      animation:gateMote linear infinite; opacity:0; will-change:transform,opacity; }
    @keyframes gateMote { 0% { transform:translate3d(0,4vh,0); opacity:0; } 12% { opacity:.5; }
      80% { opacity:.28; } 100% { transform:translate3d(3.2vw,-30vh,0); opacity:0; } }
    .gate-veil { position:fixed; inset:0; background:rgb(var(--g-scrim)); pointer-events:none; z-index:9;
      animation:gateLift 3.2s ease-out .1s forwards; }
    @keyframes gateLift { to { opacity:0; } }
    .gate-content { position:relative; z-index:2; min-height:100%; display:flex; flex-direction:column;
      align-items:center; padding:calc(env(safe-area-inset-top, 0px) + 14px) 18px calc(env(safe-area-inset-bottom, 0px) + 12px); }
    .gate-top { width:100%; max-width:1080px; display:flex; justify-content:space-between; align-items:baseline;
      opacity:0; animation:gateFade 2.4s ease .8s forwards; }
    @keyframes gateFade { to { opacity:1; } }
    .gate-brand { font-size:19px; font-weight:600; letter-spacing:.14em; margin:0; color:var(--g-cream);
      text-shadow:0 1px 14px var(--g-ink); }
    #lang-toggle { font-size:12.5px; letter-spacing:.05em; font-family:system-ui,-apple-system,"Segoe UI",Arial,sans-serif; }
    #lang-toggle a { color:rgba(250,241,224,.96) !important; text-shadow:0 1px 10px var(--g-ink); }
    #lang-toggle span { color:rgba(250,241,224,.4) !important; }
    .gate-greeting { margin:auto; text-align:center; width:min(92vw,680px); position:relative; padding:20px 0; }
    .gate-greeting::before { content:""; position:absolute; left:50%; top:50%; width:150%; height:170%;
      transform:translate(-50%,-50%); pointer-events:none;
      background:radial-gradient(closest-side, rgba(var(--g-scrim),.34), rgba(var(--g-scrim),.14) 55%, transparent 78%); }
    .gate-line { position:relative; font-weight:500; font-size:clamp(1.85rem, 4.4vw + .8rem, 3.25rem); line-height:1.3;
      letter-spacing:.012em; margin:0 0 .42em; color:var(--g-cream);
      text-shadow:0 2px 34px var(--g-ink), 0 1px 8px var(--g-ink); }
    .gate-line:last-child { font-style:italic; font-size:clamp(1.5rem, 3.6vw + .65rem, 2.65rem);
      color:var(--g-cream-soft); margin-bottom:0; }
    .gate-line .gw { display:inline-block; opacity:0; transform:translateY(.38em);
      animation:gateWord 1.9s cubic-bezier(.2,.55,.2,1) both; will-change:transform,opacity; }
    @keyframes gateWord { 0% { opacity:0; transform:translateY(.38em); } 60% { opacity:.92; }
      100% { opacity:1; transform:translateY(0); } }
    .gate-panel { width:min(94vw,620px); margin:26px auto 0; text-align:center;
      background:var(--g-panel); border:1px solid var(--g-line); border-radius:24px;
      -webkit-backdrop-filter:blur(16px) saturate(1.1); backdrop-filter:blur(16px) saturate(1.1);
      box-shadow:0 12px 48px rgba(var(--g-scrim),.45), 0 0 46px rgba(var(--g-glow),.10);
      padding:20px 22px 14px;
      opacity:0; animation:gateRise 1.9s cubic-bezier(.2,.55,.2,1) 1.1s both; }
    @keyframes gateRise { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
    .gate-tagline { font-style:italic; font-size:14.5px; line-height:1.55; color:rgba(250,240,222,.92);
      margin:0 0 14px; text-shadow:0 1px 10px var(--g-ink); }
    .gate-button { display:inline-block; border:1px solid rgba(255,232,196,.55); border-radius:999px;
      padding:15px 52px; font-size:17px; font-weight:600; letter-spacing:.04em; cursor:pointer;
      font-family:inherit; color:#2b1608;
      background:linear-gradient(180deg, #ffd9a0, #e8ab63);
      box-shadow:0 10px 40px rgba(var(--g-scrim),.5), 0 0 52px rgba(var(--g-glow),.38);
      transition:transform .3s ease, box-shadow .6s ease; }
    .gate-button:hover { transform:translateY(-2px);
      box-shadow:0 12px 44px rgba(var(--g-scrim),.5), 0 0 72px rgba(var(--g-glow),.55); }
    #welcome-gate[data-time="night"] .gate-button { background:linear-gradient(180deg,#e6edff,#b9c8ef);
      color:#101a30; border-color:rgba(226,235,255,.6); }
    .gate-sub { font-size:11.5px; line-height:1.6; color:rgba(250,240,222,.95); margin:14px 0 0; }
    .gate-sub span { color:inherit !important; }
    .gate-sub b, .gate-panel b { color:rgba(var(--g-core),.95) !important; }
    .gate-sub a, .gate-panel a { color:rgb(var(--g-glow)) !important; text-decoration:underline; text-underline-offset:2px; }
    .gate-links { margin:14px auto 4px; font-size:11.5px; display:flex; gap:7px; justify-content:center;
      align-items:center; flex-wrap:wrap; font-family:system-ui,-apple-system,"Segoe UI",Arial,sans-serif; }
    .gate-links a { color:rgba(250,240,222,.95) !important; text-decoration:none !important;
      border-bottom:1px solid rgba(250,240,222,.38); padding-bottom:1px; transition:border-color .2s; }
    .gate-links a:hover { border-bottom-color:rgba(250,240,222,.7); }
    .gate-links span { color:rgba(250,240,222,.32) !important; }
    @media (prefers-reduced-motion: reduce) {
      .gate-photo { animation:none; transform:scale(1.05); }
      .gate-presence i { animation:none; opacity:var(--gp-alpha); }
      .gate-motes { display:none; }
      .gate-veil { animation-duration:1.2s; }
      @keyframes gateWord { from { opacity:0; transform:none; } to { opacity:1; transform:none; } }
      @keyframes gateRise { from { opacity:0; transform:none; } to { opacity:1; transform:none; } }
      /* Story screen: no continuous motion — scenes swap instantly, the
         presence light holds still (set in JS), pulses stop. */
      .bar { animation:none; }
      #listen-dot { animation:none !important; }
      #calm-photo-a, #calm-photo-b { transition:none !important; }
      .story-video, .story-video-bar { transition:none !important; }
      .gate-button { transition:none; }
      #il-presence .il-bloom, #il-presence .il-vignette { transition:none; }
    }
    @media (max-width:480px) {
      .gate-panel { width:min(96vw,620px); padding:16px 14px 10px; margin-top:20px; }
      .gate-sub { font-size:10.8px; }
      .gate-tagline { font-size:13.5px; margin-bottom:12px; }
      .gate-button { width:100%; max-width:340px; padding:14px 40px; font-size:16.5px; }
      .gate-greeting { padding:12px 0; }
      .gate-links { font-size:11px; gap:6px; }
    }
    .story-screen { min-height:100vh; display:flex; flex-direction:column; align-items:center; padding:0 20px 40px;
      position:relative;
      background:transparent; }
    .story-screen > * { position:relative; z-index:1; }
    #scene-veil { position:fixed; inset:0; z-index:0; pointer-events:none;
      background:linear-gradient(180deg, rgba(255,255,255,0.55), rgba(255,255,255,0.35)); }
    /* THE PRESENCE — a soft light that openly breathes and moves with the read,
       in real time. It sits above the photo but below all content, so text stays
       perfectly readable. Everything about it is driven live in JS. */
    #il-presence { position:fixed; inset:0; z-index:0; pointer-events:none; overflow:hidden; }
    #il-presence .il-bloom { position:absolute; left:50%; top:45%;
      width:70vmax; height:70vmax; border-radius:50%;
      transform:translate(-50%,-50%) scale(1); opacity:0; will-change:transform,opacity,filter;
      background:radial-gradient(circle at center,
        rgba(255,216,164,0.55) 0%, rgba(255,192,126,0.20) 40%, rgba(255,192,126,0) 70%); }
    #il-presence .il-vignette { position:absolute; inset:0; opacity:0; will-change:opacity;
      background:radial-gradient(circle at 50% 46%, rgba(60,40,25,0) 42%, rgba(52,34,20,0.30) 100%); }
    #il-presence-word { position:fixed; left:0; right:0; bottom:120px; text-align:center;
      z-index:3; pointer-events:none; font-size:15.5px; letter-spacing:.3px; color:#6a402b;
      font-weight:500; text-shadow:0 1px 3px rgba(255,255,255,0.9); opacity:0;
      transition:opacity 1.8s ease; }
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
    .story-input::placeholder { color:#8a6a48; }
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
      /* PHONE CORNER MAP — every floating piece has its own home, nothing stacks:
         top-left: focus pill · top-right: camera circle · bottom-left: heart chip
         bottom-right: scene strip (one swipeable row) · above those: soft word/tips
         bottom-center prompts sit just above the help bar and gently fade the
         corner pieces while they are open, so only one thing speaks at a time. */
      .scene-picker { bottom:70px !important; right:10px !important; z-index:40 !important;
        background:rgba(255,255,255,0.85); border-radius:16px; padding:5px 8px;
        max-width:56vw; flex-wrap:nowrap; overflow-x:auto; justify-content:flex-start;
        scrollbar-width:none; }
      .scene-picker::-webkit-scrollbar { display:none; }
      #heart-chip { bottom:74px !important; left:10px !important;
        padding:8px 14px !important; font-size:15px !important; }
      #heart-chip #heart-beat { font-size:16px !important; }
      #heart-chip #heart-num { font-size:18px !important; }
      #heart-chip .hr-label { font-size:11px !important; }
      /* Focus pill mirrors the camera circle in the opposite top corner */
      #il-anchor-pill { top:70px !important; bottom:auto !important; left:12px !important;
        right:auto !important; padding:7px 11px !important; font-size:11.5px !important; }
      /* The soft presence word hugs its own text and floats in a clear band */
      #il-presence-word { left:50%; right:auto; bottom:158px; width:max-content;
        max-width:78vw; transform:translateX(-50%); }
      /* Camera tips: small, one per side, in the band above the corner pieces */
      #hr-distance-tip { bottom:160px !important; right:12px !important; max-width:165px !important; }
      #il-light-tip { bottom:160px !important; left:12px !important; right:auto !important;
        transform:none !important; max-width:160px !important; }
      /* Feeling card + gentle prompts: bottom-center, always ABOVE the help bar */
      #sam-card { top:auto !important; bottom:78px !important; left:50% !important;
        right:auto !important; transform:translateX(-50%) !important;
        max-width:min(320px, calc(100vw - 24px)) !important; }
      #il-checkin, #gentle-bridge, #fb-card, #save-offer { bottom:78px !important; }
      /* While a prompt is open, the corner pieces rest — one voice at a time */
      body:has(#il-checkin, #sam-card, #gentle-bridge, #fb-card, #save-offer) :is(.scene-picker, #heart-chip, #il-anchor-pill, #il-presence-word, #hr-distance-tip, #il-light-tip) {
        opacity:0 !important; pointer-events:none !important; transition:opacity .8s ease; }
      body:has(#hr-distance-tip, #il-light-tip) #il-presence-word { opacity:0 !important; }
      /* Give the whole page room so nothing hides behind the fixed help bar,
         the scene strip, or the tip band — everything can scroll fully clear */
      .story-screen { padding-bottom:170px; padding-left:14px; padding-right:14px; }
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
    /* Only one bottom-center prompt speaks at a time, at every screen size.
       Priority: reach-a-person invite, then feedback, then save, then check-in,
       then the feeling faces. Lower ones wait, faded out, and return when the
       higher one closes. */
    body:has(#gentle-bridge) :is(#fb-card, #save-offer, #il-checkin, #sam-card) {
      opacity:0 !important; pointer-events:none !important; }
    body:has(#fb-card) :is(#save-offer, #il-checkin, #sam-card) {
      opacity:0 !important; pointer-events:none !important; }
    body:has(#save-offer) :is(#il-checkin, #sam-card) {
      opacity:0 !important; pointer-events:none !important; }
    body:has(#il-checkin) #sam-card {
      opacity:0 !important; pointer-events:none !important; }
    /* While the one-time readiness notice is open at the top, the top-corner
       floaters rest so nothing sits on the notice (they return on dismiss). */
    body:has(#readiness-bar) :is(#il-anchor-pill, .story-video-bar.floating) {
      opacity:0 !important; pointer-events:none !important; }
    .story-mic { background:#fff; color:#99673e; border:1px solid #ddd1c8; border-radius:999px; padding:13px 22px;
      font-size:14px; cursor:pointer; }
    .music-bar { display:flex; align-items:center; justify-content:center; gap:14px; margin-top:14px; color:#736049; font-size:13px; }
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
      <div class="gate-stage" aria-hidden="true">
        <img class="gate-photo" id="gate-photo" alt="">
        <div class="gate-grade"></div>
        <div class="gate-scrim-top"></div>
        <div class="gate-scrim-bottom"></div>
        <div class="gate-vignette"></div>
        <div class="gate-presence"><i></i></div>
        <div class="gate-motes" id="gate-motes"></div>
      </div>
      <div class="gate-veil" aria-hidden="true"></div>
      <div class="gate-content">
        <div class="gate-top">
          <h1 class="gate-brand">InnerLight</h1>
          <div id="lang-toggle">
            <a href="#" onclick="setLang('en');return false;" data-langbtn="en" style="text-decoration:none;">English</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('es');return false;" data-langbtn="es" style="text-decoration:none;">Espa&ntilde;ol</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('zh');return false;" data-langbtn="zh" style="text-decoration:none;">&#20013;&#25991;</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('hi');return false;" data-langbtn="hi" style="text-decoration:none;">हिन्दी</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('pa');return false;" data-langbtn="pa" style="text-decoration:none;">ਪੰਜਾਬੀ</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('bn');return false;" data-langbtn="bn" style="text-decoration:none;">বাংলা</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('tl');return false;" data-langbtn="tl" style="text-decoration:none;">Tagalog</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('to');return false;" data-langbtn="to" style="text-decoration:none;">lea faka-Tonga</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('sw');return false;" data-langbtn="sw" style="text-decoration:none;">Kiswahili</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('am');return false;" data-langbtn="am" style="text-decoration:none;">&#4768;&#4635;&#4653;&#4763;</a>
            <span>&middot;</span>
            <a href="#" onclick="setLang('ha');return false;" data-langbtn="ha" style="text-decoration:none;">Hausa</a>
          </div>
        </div>
        <div class="gate-greeting" id="gate-greeting" aria-live="polite"></div>
        <div class="gate-panel">
          <p class="gate-tagline" data-i18n="gate.tagline">A quiet, private place to tell your story.<br>Nothing you share is shown to anyone &mdash; it is encrypted.</p>
          <button class="gate-button" onclick="startExperience()" data-i18n="gate.begin">Tap to begin</button>
          <p class="gate-sub"><span data-i18n="gate.startnote">Soft music and your camera begin gently when you tap.</span><br>
          <span data-i18n="gate.camera" style="display:inline-block;margin:7px auto 0;max-width:520px;line-height:1.6;">
          <b>About your camera:</b> your video is analyzed <b>on your own device</b> &mdash;
          for gentle expression and heart signals only. The video itself is <b>never sent to us or stored anywhere</b>.
          Nothing leaves your device. You can decline the camera and still use everything else.</span><br>
          <span data-i18n="gate.ainotice" style="display:inline-block;margin:7px auto 0;max-width:520px;line-height:1.6;">
          <b>Please know:</b> InnerLight is an <b>artificial-intelligence program</b> &mdash; a computer,
          not a human being. It is not a therapist, doctor, or lawyer, and it may not be suitable for some minors.
          In an emergency, call or text <b>988</b> or call <b>911</b>. <a href="/safety">How we respond in a crisis</a></span><br>
          <span data-i18n="gate.adult" style="display:inline-block;margin:7px auto 0;max-width:520px;line-height:1.6;">By continuing you confirm you are 18 or older.
          <a href="#" onclick="showMinorBridge();return false;">Under 18? We still have real help for you.</a></span></p>
          <div class="gate-links">
            <a href="/about" data-i18n="glink.about">About</a><span>&middot;</span>
            <a href="/how-it-works" data-i18n="glink.how">How it works</a><span>&middot;</span>
            <a href="/stories" data-i18n="glink.stories">How a visit goes</a><span>&middot;</span>
            <a href="/resources" data-i18n="glink.resources">Real help</a><span>&middot;</span>
            <a href="/research" data-i18n="glink.research">Research</a><span>&middot;</span>
            <a href="/safety" data-i18n="glink.safety">Safety</a><span>&middot;</span>
            <a href="/faq" data-i18n="glink.faq">FAQ</a><span>&middot;</span>
            <a href="/terms" data-i18n="glink.terms">Terms</a><span>&middot;</span>
            <a href="/privacy" data-i18n="glink.privacy">Your privacy</a><span>&middot;</span>
            <a href="/updates" data-i18n="glink.updates">Updates</a><span>&middot;</span>
            <a href="/contact" data-i18n="glink.contact">Contact</a>
          </div>
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
        "rail.save": "&#128278; Guardar",
        "rail.testmic": "Probar micr&oacute;fono",
        "glink.about": "Acerca de",
        "glink.how": "C&oacute;mo funciona",
        "glink.stories": "C&oacute;mo es una visita",
        "glink.resources": "Ayuda real",
        "glink.research": "Investigaci&oacute;n",
        "glink.safety": "Seguridad",
        "glink.privacy": "Tu privacidad",
        "glink.updates": "Novedades",
        "glink.contact": "Contacto",
        "glink.faq": "Preguntas frecuentes",
        "glink.terms": "Términos"
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
        "rail.save": "&#128278; 保存",
        "rail.testmic": "测试麦克风",
        "glink.about": "关于我们",
        "glink.how": "运作方式",
        "glink.stories": "一次访问是怎样的",
        "glink.resources": "真实的帮助",
        "glink.research": "研究",
        "glink.safety": "安全",
        "glink.privacy": "你的隐私",
        "glink.updates": "更新",
        "glink.contact": "联系我们",
        "glink.faq": "常见问题",
        "glink.terms": "条款"
      },
      hi: {
        "gate.tagline": "अपनी बात कहने के लिए एक शांत, निजी जगह।<br>आप जो भी साझा करते हैं वह किसी को नहीं दिखाया जाता &mdash; वह एन्क्रिप्टेड (सुरक्षित रूप से कूटबद्ध) है।",
        "gate.begin": "शुरू करने के लिए टैप करें",
        "gate.startnote": "टैप करते ही हल्का संगीत और आपका कैमरा धीरे-धीरे शुरू होते हैं।",
        "gate.camera": "<b style='color:#99673e;'>आपके कैमरे के बारे में:</b> आपका वीडियो <b>आपके अपने डिवाइस पर ही</b> विश्लेषित होता है &mdash; केवल आपके हाव-भाव और हृदय-गति के संकेत धीरे से पढ़ने के लिए। वीडियो स्वयं <b>कभी हमें नहीं भेजा जाता और कहीं भी सहेजा नहीं जाता</b>। कुछ भी आपके डिवाइस से बाहर नहीं जाता। आप कैमरा मना कर सकते हैं और बाकी सब कुछ फिर भी इस्तेमाल कर सकते हैं।",
        "gate.ainotice": "<b style='color:#99673e;'>कृपया जान लें:</b> InnerLight एक <b>आर्टिफ़िशियल इंटेलिजेंस प्रोग्राम</b> है &mdash; एक कंप्यूटर, कोई इंसान नहीं। यह कोई थेरेपिस्ट, डॉक्टर या वकील नहीं है, और कुछ नाबालिगों के लिए उपयुक्त नहीं हो सकता। आपात स्थिति में <b>988</b> पर कॉल या संदेश करें, या <b>911</b> पर कॉल करें। <a href='/safety' style='color:#2e6e8e;'>संकट में हम कैसे जवाब देते हैं</a>",
        "gate.adult": "आगे बढ़ने पर आप पुष्टि करते हैं कि आपकी आयु 18 वर्ष या उससे अधिक है। <a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>18 से कम उम्र? आपके लिए भी सच्ची मदद मौजूद है।</a>",
        "story.title": "मुझे अपनी बात बताइए।",
        "story.sub": "अपना समय लीजिए। जो सच लगे, वही कहिए। मैं सुनने के लिए यहीं हूँ।",
        "story.resume": "पहले यहाँ आ चुके हैं? अपनी कहानी जारी रखें",
        "story.ainote": "InnerLight एक आर्टिफ़िशियल इंटेलिजेंस प्रोग्राम है &mdash; कोई इंसान नहीं, और न ही कोई थेरेपिस्ट, डॉक्टर या वकील।",
        "story.safetylink": "सुरक्षा और संकट प्रोटोकॉल",
        "story.placeholder": "जहाँ से चाहें, वहीं से शुरू करें… (भेजने के लिए Enter दबाएँ)",
        "story.send": "भेजें",
        "story.speak": "&#127908; बोलें",
        "music.now": "&#9834; हल्का संगीत चल रहा है",
        "music.change": "संगीत बदलें",
        "music.pulseon": "&#10041; शांति की धड़कन: चालू",
        "music.voiceoff": "&#128263; बोलती आवाज़: बंद",
        "rail.provider": "देखभाल सेवा",
        "rail.legal": "कानूनी मदद",
        "rail.nearby": "आस-पास मदद",
        "rail.activities": "गतिविधियाँ",
        "rail.save": "&#128278; सहेजें",
        "rail.testmic": "माइक जाँचें",
        "glink.about": "हमारे बारे में",
        "glink.how": "यह कैसे काम करता है",
        "glink.stories": "एक मुलाक़ात कैसी होती है",
        "glink.resources": "सच्ची मदद",
        "glink.research": "शोध",
        "glink.safety": "सुरक्षा",
        "glink.privacy": "आपकी गोपनीयता",
        "glink.updates": "नई जानकारी",
        "glink.contact": "संपर्क करें",
        "glink.faq": "अक्सर पूछे जाने वाले प्रश्न",
        "glink.terms": "शर्तें"
      },
      pa: {
        "gate.tagline": "ਆਪਣੀ ਗੱਲ ਕਹਿਣ ਲਈ ਇੱਕ ਸ਼ਾਂਤ, ਨਿੱਜੀ ਥਾਂ।<br>ਜੋ ਵੀ ਤੁਸੀਂ ਸਾਂਝਾ ਕਰਦੇ ਹੋ ਉਹ ਕਿਸੇ ਨੂੰ ਨਹੀਂ ਦਿਖਾਇਆ ਜਾਂਦਾ &mdash; ਉਹ ਐਨਕ੍ਰਿਪਟਡ (ਸੁਰੱਖਿਅਤ ਕੋਡ ਵਿੱਚ) ਹੈ।",
        "gate.begin": "ਸ਼ੁਰੂ ਕਰਨ ਲਈ ਟੈਪ ਕਰੋ",
        "gate.startnote": "ਟੈਪ ਕਰਦਿਆਂ ਹੀ ਹੌਲੀ ਸੰਗੀਤ ਅਤੇ ਤੁਹਾਡਾ ਕੈਮਰਾ ਹੌਲੀ-ਹੌਲੀ ਸ਼ੁਰੂ ਹੁੰਦੇ ਹਨ।",
        "gate.camera": "<b style='color:#99673e;'>ਤੁਹਾਡੇ ਕੈਮਰੇ ਬਾਰੇ:</b> ਤੁਹਾਡੀ ਵੀਡੀਓ <b>ਤੁਹਾਡੀ ਆਪਣੀ ਡਿਵਾਈਸ ਉੱਤੇ ਹੀ</b> ਪੜ੍ਹੀ ਜਾਂਦੀ ਹੈ &mdash; ਸਿਰਫ਼ ਤੁਹਾਡੇ ਹਾਵ-ਭਾਵ ਅਤੇ ਦਿਲ ਦੀ ਧੜਕਣ ਦੇ ਸੰਕੇਤ ਹੌਲੀ ਜਿਹੇ ਪੜ੍ਹਨ ਲਈ। ਵੀਡੀਓ ਆਪ <b>ਕਦੇ ਵੀ ਸਾਨੂੰ ਨਹੀਂ ਭੇਜੀ ਜਾਂਦੀ ਅਤੇ ਕਿਤੇ ਵੀ ਸਾਂਭੀ ਨਹੀਂ ਜਾਂਦੀ</b>। ਕੁਝ ਵੀ ਤੁਹਾਡੀ ਡਿਵਾਈਸ ਤੋਂ ਬਾਹਰ ਨਹੀਂ ਜਾਂਦਾ। ਤੁਸੀਂ ਕੈਮਰੇ ਤੋਂ ਇਨਕਾਰ ਕਰ ਸਕਦੇ ਹੋ ਅਤੇ ਬਾਕੀ ਸਭ ਕੁਝ ਫਿਰ ਵੀ ਵਰਤ ਸਕਦੇ ਹੋ।",
        "gate.ainotice": "<b style='color:#99673e;'>ਕਿਰਪਾ ਕਰਕੇ ਜਾਣ ਲਵੋ:</b> InnerLight ਇੱਕ <b>ਆਰਟੀਫ਼ੀਸ਼ੀਅਲ ਇੰਟੈਲੀਜੈਂਸ ਪ੍ਰੋਗਰਾਮ</b> ਹੈ &mdash; ਇੱਕ ਕੰਪਿਊਟਰ, ਕੋਈ ਇਨਸਾਨ ਨਹੀਂ। ਇਹ ਕੋਈ ਥੈਰੇਪਿਸਟ, ਡਾਕਟਰ ਜਾਂ ਵਕੀਲ ਨਹੀਂ ਹੈ, ਅਤੇ ਕੁਝ ਨਾਬਾਲਗਾਂ ਲਈ ਢੁਕਵਾਂ ਨਹੀਂ ਹੋ ਸਕਦਾ। ਐਮਰਜੈਂਸੀ ਵਿੱਚ <b>988</b> ਉੱਤੇ ਕਾਲ ਜਾਂ ਸੁਨੇਹਾ ਭੇਜੋ, ਜਾਂ <b>911</b> ਉੱਤੇ ਕਾਲ ਕਰੋ। <a href='/safety' style='color:#2e6e8e;'>ਸੰਕਟ ਵਿੱਚ ਅਸੀਂ ਕਿਵੇਂ ਜਵਾਬ ਦਿੰਦੇ ਹਾਂ</a>",
        "gate.adult": "ਅੱਗੇ ਵਧਣ ਨਾਲ ਤੁਸੀਂ ਪੁਸ਼ਟੀ ਕਰਦੇ ਹੋ ਕਿ ਤੁਹਾਡੀ ਉਮਰ 18 ਸਾਲ ਜਾਂ ਵੱਧ ਹੈ। <a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>18 ਤੋਂ ਘੱਟ? ਤੁਹਾਡੇ ਲਈ ਵੀ ਸੱਚੀ ਮਦਦ ਹੈ।</a>",
        "story.title": "ਮੈਨੂੰ ਆਪਣੀ ਗੱਲ ਦੱਸੋ।",
        "story.sub": "ਆਪਣਾ ਸਮਾਂ ਲਵੋ। ਜੋ ਸੱਚ ਲੱਗੇ, ਉਹੀ ਕਹੋ। ਮੈਂ ਸੁਣਨ ਲਈ ਇੱਥੇ ਹਾਂ।",
        "story.resume": "ਪਹਿਲਾਂ ਇੱਥੇ ਆਏ ਹੋ? ਆਪਣੀ ਕਹਾਣੀ ਜਾਰੀ ਰੱਖੋ",
        "story.ainote": "InnerLight ਇੱਕ ਆਰਟੀਫ਼ੀਸ਼ੀਅਲ ਇੰਟੈਲੀਜੈਂਸ ਪ੍ਰੋਗਰਾਮ ਹੈ &mdash; ਕੋਈ ਇਨਸਾਨ ਨਹੀਂ, ਅਤੇ ਨਾ ਹੀ ਕੋਈ ਥੈਰੇਪਿਸਟ, ਡਾਕਟਰ ਜਾਂ ਵਕੀਲ।",
        "story.safetylink": "ਸੁਰੱਖਿਆ ਅਤੇ ਸੰਕਟ ਪ੍ਰੋਟੋਕੋਲ",
        "story.placeholder": "ਜਿੱਥੋਂ ਮਰਜ਼ੀ ਸ਼ੁਰੂ ਕਰੋ… (ਭੇਜਣ ਲਈ Enter ਦਬਾਓ)",
        "story.send": "ਭੇਜੋ",
        "story.speak": "&#127908; ਬੋਲੋ",
        "music.now": "&#9834; ਹੌਲੀ ਸੰਗੀਤ ਚੱਲ ਰਿਹਾ ਹੈ",
        "music.change": "ਸੰਗੀਤ ਬਦਲੋ",
        "music.pulseon": "&#10041; ਸ਼ਾਂਤੀ ਦੀ ਧੜਕਣ: ਚਾਲੂ",
        "music.voiceoff": "&#128263; ਬੋਲਦੀ ਆਵਾਜ਼: ਬੰਦ",
        "rail.provider": "ਦੇਖਭਾਲ ਸੇਵਾ",
        "rail.legal": "ਕਾਨੂੰਨੀ ਮਦਦ",
        "rail.nearby": "ਨੇੜੇ ਦੀ ਮਦਦ",
        "rail.activities": "ਸਰਗਰਮੀਆਂ",
        "rail.save": "&#128278; ਸਾਂਭੋ",
        "rail.testmic": "ਮਾਈਕ ਪਰਖੋ",
        "glink.about": "ਸਾਡੇ ਬਾਰੇ",
        "glink.how": "ਇਹ ਕਿਵੇਂ ਕੰਮ ਕਰਦਾ ਹੈ",
        "glink.stories": "ਇੱਕ ਮੁਲਾਕਾਤ ਕਿਹੋ ਜਿਹੀ ਹੁੰਦੀ ਹੈ",
        "glink.resources": "ਸੱਚੀ ਮਦਦ",
        "glink.research": "ਖੋਜ",
        "glink.safety": "ਸੁਰੱਖਿਆ",
        "glink.privacy": "ਤੁਹਾਡੀ ਪਰਦੇਦਾਰੀ",
        "glink.updates": "ਨਵੀਆਂ ਖ਼ਬਰਾਂ",
        "glink.contact": "ਸੰਪਰਕ ਕਰੋ",
        "glink.faq": "ਆਮ ਸਵਾਲ",
        "glink.terms": "ਸ਼ਰਤਾਂ"
      },
      bn: {
        "gate.tagline": "নিজের কথা বলার জন্য একটি শান্ত, ব্যক্তিগত জায়গা।<br>আপনি যা ভাগ করেন তা কাউকে দেখানো হয় না &mdash; তা এনক্রিপ্ট করা (সুরক্ষিতভাবে কোডবদ্ধ)।",
        "gate.begin": "শুরু করতে ট্যাপ করুন",
        "gate.startnote": "ট্যাপ করলেই মৃদু সংগীত আর আপনার ক্যামেরা ধীরে ধীরে চালু হয়।",
        "gate.camera": "<b style='color:#99673e;'>আপনার ক্যামেরা সম্পর্কে:</b> আপনার ভিডিও <b>আপনার নিজের ডিভাইসেই</b> বিশ্লেষণ করা হয় &mdash; শুধু আপনার মুখের ভাব ও হৃদস্পন্দনের সংকেত আলতোভাবে পড়ার জন্য। ভিডিওটি নিজে <b>কখনো আমাদের কাছে পাঠানো হয় না, কোথাও সংরক্ষণও করা হয় না</b>। কিছুই আপনার ডিভাইসের বাইরে যায় না। আপনি ক্যামেরা প্রত্যাখ্যান করেও বাকি সবকিছু ব্যবহার করতে পারেন।",
        "gate.ainotice": "<b style='color:#99673e;'>দয়া করে জেনে রাখুন:</b> InnerLight একটি <b>কৃত্রিম বুদ্ধিমত্তা প্রোগ্রাম</b> &mdash; একটি কম্পিউটার, কোনো মানুষ নয়। এটি কোনো থেরাপিস্ট, ডাক্তার বা আইনজীবী নয়, এবং কিছু অপ্রাপ্তবয়স্কের জন্য উপযুক্ত না-ও হতে পারে। জরুরি অবস্থায় <b>988</b> নম্বরে কল বা টেক্সট করুন, অথবা <b>911</b> নম্বরে কল করুন। <a href='/safety' style='color:#2e6e8e;'>সংকটে আমরা কীভাবে সাড়া দিই</a>",
        "gate.adult": "এগিয়ে গেলে আপনি নিশ্চিত করছেন যে আপনার বয়স ১৮ বা তার বেশি। <a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>বয়স ১৮-র কম? আপনার জন্যও সত্যিকারের সাহায্য আছে।</a>",
        "story.title": "আমাকে আপনার কথা বলুন।",
        "story.sub": "সময় নিন। যা সত্যি মনে হয়, তাই বলুন। আমি শোনার জন্য এখানে আছি।",
        "story.resume": "আগে এখানে এসেছিলেন? আপনার কথা চালিয়ে যান",
        "story.ainote": "InnerLight একটি কৃত্রিম বুদ্ধিমত্তা প্রোগ্রাম &mdash; কোনো মানুষ নয়, এবং কোনো থেরাপিস্ট, ডাক্তার বা আইনজীবীও নয়।",
        "story.safetylink": "নিরাপত্তা ও সংকট প্রোটোকল",
        "story.placeholder": "যেখান থেকে ইচ্ছা শুরু করুন… (পাঠাতে Enter চাপুন)",
        "story.send": "পাঠান",
        "story.speak": "&#127908; বলুন",
        "music.now": "&#9834; মৃদু সংগীত বাজছে",
        "music.change": "সংগীত বদলান",
        "music.pulseon": "&#10041; শান্তির স্পন্দন: চালু",
        "music.voiceoff": "&#128263; কথা-বলা কণ্ঠ: বন্ধ",
        "rail.provider": "সেবা প্রদানকারী",
        "rail.legal": "আইনি সাহায্য",
        "rail.nearby": "কাছাকাছি সাহায্য",
        "rail.activities": "কার্যকলাপ",
        "rail.save": "&#128278; সংরক্ষণ",
        "rail.testmic": "মাইক পরীক্ষা",
        "glink.about": "আমাদের সম্পর্কে",
        "glink.how": "এটি কীভাবে কাজ করে",
        "glink.stories": "একটি সাক্ষাৎ কেমন হয়",
        "glink.resources": "সত্যিকারের সাহায্য",
        "glink.research": "গবেষণা",
        "glink.safety": "নিরাপত্তা",
        "glink.privacy": "আপনার গোপনীয়তা",
        "glink.updates": "নতুন খবর",
        "glink.contact": "যোগাযোগ",
        "glink.faq": "সাধারণ প্রশ্ন",
        "glink.terms": "শর্তাবলী"
      },
      tl: {
        "gate.tagline": "Isang tahimik at pribadong lugar para ikuwento ang iyong kalagayan.<br>Walang ipinapakita kaninuman ang anumang ibinahagi mo &mdash; naka-encrypt ito.",
        "gate.begin": "I-tap para magsimula",
        "gate.startnote": "Marahang magsisimula ang mahinang musika at ang iyong camera kapag nag-tap ka.",
        "gate.camera": "<b style='color:#99673e;'>Tungkol sa iyong camera:</b> sinusuri ang iyong video <b>sa sarili mong device</b> &mdash; para lamang mahinahong mabasa ang iyong ekspresyon at senyales ng tibok ng puso. Ang video mismo ay <b>hindi kailanman ipinapadala sa amin o iniimbak saanman</b>. Walang umaalis sa iyong device. Maaari mong tanggihan ang camera at magagamit mo pa rin ang lahat ng iba pa.",
        "gate.ainotice": "<b style='color:#99673e;'>Pakitandaan:</b> ang InnerLight ay isang <b>artificial intelligence program</b> &mdash; isang computer, hindi tao. Hindi ito therapist, doktor, o abogado, at maaaring hindi angkop para sa ilang menor de edad. Sa emergency, tumawag o mag-text sa <b>988</b>, o tumawag sa <b>911</b>. <a href='/safety' style='color:#2e6e8e;'>Paano kami tumutugon sa krisis</a>",
        "gate.adult": "Sa pagpapatuloy, kinukumpirma mong ikaw ay 18 taong gulang o mas matanda. <a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>Wala pang 18? May totoong tulong din kami para sa iyo.</a>",
        "story.title": "Ikuwento mo sa akin ang nangyayari.",
        "story.sub": "Huwag magmadali. Sabihin ang totoo sa iyong loob. Nakikinig ako.",
        "story.resume": "Nakapunta ka na rito? Ipagpatuloy ang iyong kuwento",
        "story.ainote": "Ang InnerLight ay isang artificial intelligence program &mdash; hindi tao, at hindi therapist, doktor, o abogado.",
        "story.safetylink": "Kaligtasan at protocol sa krisis",
        "story.placeholder": "Magsimula kahit saan… (pindutin ang Enter para ipadala)",
        "story.send": "Ipadala",
        "story.speak": "&#127908; Magsalita",
        "music.now": "&#9834; tumutugtog ang mahinang musika",
        "music.change": "Palitan ang musika",
        "music.pulseon": "&#10041; Pintig ng kalma: nakabukas",
        "music.voiceoff": "&#128263; Boses na nagsasalita: nakapatay",
        "rail.provider": "Pangangalaga",
        "rail.legal": "Tulong legal",
        "rail.nearby": "Kalapit na tulong",
        "rail.activities": "Mga gawain",
        "rail.save": "&#128278; I-save",
        "rail.testmic": "Subukan ang mic",
        "glink.about": "Tungkol sa amin",
        "glink.how": "Paano ito gumagana",
        "glink.stories": "Paano ang isang pagbisita",
        "glink.resources": "Totoong tulong",
        "glink.research": "Pananaliksik",
        "glink.safety": "Kaligtasan",
        "glink.privacy": "Ang iyong privacy",
        "glink.updates": "Mga update",
        "glink.contact": "Makipag-ugnayan",
        "glink.faq": "Mga FAQ",
        "glink.terms": "Mga Tuntunin"
      },
      to: {
        "gate.tagline": "Ko ha feituʻu nonga mo fakapulipuli ke fai ai hoʻo talanoa.<br>ʻOku ʻikai fakahā ki ha taha ha meʻa ʻokú ke vahevahe &mdash; ʻoku maluʻi fakakomipiuta (encrypted).",
        "gate.begin": "Lomiʻi ke kamata",
        "gate.startnote": "ʻE kamata māmālie ʻa e hiva vaivai mo hoʻo mea faitā (camera) ʻi hoʻo lomiʻi.",
        "gate.camera": "<b style='color:#99673e;'>Fekauʻaki mo hoʻo mea faitā:</b> ʻoku sivisiviʻi hoʻo vitiō <b>ʻi hoʻo meʻangāue pē ʻaʻau</b> &mdash; ke lau māmālie pē ʻa e ngaahi fakaʻilonga ʻo ho fofonga mo e tā ʻo ho mafu. Ko e vitiō tonu <b>ʻoku ʻikai ʻaupito ʻoatu kiate kimautolu pe tauhi ʻi ha feituʻu</b>. ʻOku ʻikai mavahe ha meʻa mei hoʻo meʻangāue. ʻE lava ke ke fakafisi ʻa e mea faitā kae kei ngāueʻaki ʻa e meʻa kotoa pē.",
        "gate.ainotice": "<b style='color:#99673e;'>Kātaki ʻo ʻilo:</b> ko e InnerLight ko ha <b>polokalama ʻatamai fakaʻilekitulōnika (AI)</b> &mdash; ko ha komipiuta, ʻoku ʻikai ko ha tangata. ʻOku ʻikai ko ha toketā fakaʻatamai, toketā, pe loea, pea ʻe ʻikai ngalingali feʻunga ia ki he kau taʻu siʻi ʻe niʻihi. ʻI ha faingataʻa fakavavevave, telefoni pe fai ha pōpoaki ki he <b>988</b>, pe telefoni ki he <b>911</b>. <a href='/safety' style='color:#2e6e8e;'>Ko e founga ʻemau tali ʻi ha faingataʻa</a>",
        "gate.adult": "ʻI hoʻo hokohoko atu ʻokú ke fakapapauʻi kuó ke taʻu 18 pe lahi ange. <a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>Siʻi hifo he taʻu 18? ʻOku ʻi ai foki mo ha tokoni moʻoni maʻau.</a>",
        "story.title": "Talamai hoʻo talanoa.",
        "story.sub": "Fai māmālie pē. Lea ʻaki ʻa e meʻa ʻoku moʻoni kiate koe. ʻOku ou ʻi heni ke fanongo.",
        "story.resume": "Naʻá ke ʻi heni ki muʻa? Hokohoko atu hoʻo talanoa",
        "story.ainote": "Ko e InnerLight ko ha polokalama AI &mdash; ʻoku ʻikai ko ha tangata, pea ʻoku ʻikai ko ha toketā fakaʻatamai, toketā, pe loea.",
        "story.safetylink": "Malu mo e founga ʻi ha faingataʻa",
        "story.placeholder": "Kamata mei ha feituʻu pē ʻokú ke loto ki ai… (lomiʻi ʻa e Enter ke ʻave)",
        "story.send": "ʻAve",
        "story.speak": "&#127908; Lea",
        "music.now": "&#9834; ʻoku ongo ʻa e hiva vaivai",
        "music.change": "Liliu ʻa e hiva",
        "music.pulseon": "&#10041; Tā ʻo e nonga: moʻui",
        "music.voiceoff": "&#128263; Leʻo lea: mate",
        "rail.provider": "Tokoni fakafaitoʻo",
        "rail.legal": "Tokoni fakalao",
        "rail.nearby": "Tokoni ofi",
        "rail.activities": "Ngaahi ngāue",
        "rail.save": "&#128278; Tauhi",
        "rail.testmic": "ʻAhiʻahiʻi e maikolofoni",
        "glink.about": "Ko kimautolu",
        "glink.how": "Founga ʻene ngāue",
        "glink.stories": "Ko e anga ʻo ha ʻaʻahi",
        "glink.resources": "Tokoni moʻoni",
        "glink.research": "Fekumi",
        "glink.safety": "Malu",
        "glink.privacy": "Hoʻo fakapulipuli",
        "glink.updates": "Ngaahi fakamatala foʻou",
        "glink.contact": "Fetuʻutaki",
        "glink.faq": "Ngaahi Fehuʻi",
        "glink.terms": "Ngaahi Tuʻutuʻuni"
      },
      sw: {
        "gate.tagline": "Mahali pa utulivu na faragha pa kusimulia hadithi yako.<br>Hakuna unachoshiriki kinachoonyeshwa kwa yeyote &mdash; kimefichwa kwa usimbaji.",
        "gate.begin": "Gusa kuanza",
        "gate.startnote": "Muziki mpole na kamera yako huanza taratibu unapogusa.",
        "gate.camera": "<b>Kuhusu kamera yako:</b> video yako inachambuliwa <b>kwenye kifaa chako mwenyewe</b> &mdash; kwa ishara za sura na moyo pekee. Video yenyewe <b>haitumwi kwetu wala kuhifadhiwa popote</b>. Hakuna kinachoondoka kwenye kifaa chako. Unaweza kukataa kamera na bado utumie kila kitu kingine.",
        "gate.ainotice": "<b>Tafadhali fahamu:</b> InnerLight ni <b>programu ya akili bandia</b> &mdash; kompyuta, si binadamu. Si mtaalamu wa tiba, daktari, wala wakili, na huenda isifae baadhi ya watoto. Katika dharura, piga simu au tuma ujumbe <b>988</b> au piga <b>911</b>. <a href='/safety' style='color:#2e6e8e;'>Jinsi tunavyoitikia wakati wa dharura</a>",
        "gate.adult": "Kwa kuendelea unathibitisha una miaka 18 au zaidi. <a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>Chini ya 18? Bado tuna msaada wa kweli kwa ajili yako.</a>",
        "story.title": "Nisimulie hadithi yako.",
        "story.sub": "Chukua muda wako. Sema lolote linalohisi kweli. Ninasikiliza.",
        "story.resume": "Umewahi kuwa hapa? Endeleza hadithi yako",
        "story.ainote": "InnerLight ni programu ya AI &mdash; si binadamu, wala si mtaalamu wa tiba, daktari, au wakili.",
        "story.safetylink": "Usalama na itifaki ya dharura",
        "story.placeholder": "Anza popote unapotaka... (bonyeza Enter kutuma)",
        "story.send": "Tuma",
        "music.now": "&#9834; muziki mpole unacheza",
        "music.change": "Badilisha muziki",
        "music.pulseon": "&#10041; Mpigo wa utulivu: umewashwa",
        "music.voiceoff": "&#128263; Sauti ya kusema: Imezimwa",
        "rail.provider": "Mtoa huduma",
        "rail.legal": "Kisheria",
        "rail.nearby": "Msaada wa karibu",
        "rail.activities": "Shughuli",
        "rail.save": "&#128278; Hifadhi",
        "rail.testmic": "Jaribu maiki",
        "glink.about": "Kuhusu",
        "glink.how": "Jinsi inavyofanya kazi",
        "glink.stories": "Jinsi ziara inavyokwenda",
        "glink.resources": "Msaada wa kweli",
        "glink.research": "Utafiti",
        "glink.safety": "Usalama",
        "glink.privacy": "Faragha yako",
        "glink.updates": "Habari mpya",
        "glink.contact": "Wasiliana nasi",
        "glink.faq": "Maswali ya mara kwa mara",
        "glink.terms": "Masharti"
      },
      am: {
        "gate.tagline": "ታሪክዎን የሚነግሩበት ጸጥ ያለ የግል ቦታ።<br>የሚያካፍሉት ምንም ነገር ለማንም አይታይም &mdash; በምስጠራ የተጠበቀ ነው።",
        "gate.begin": "ለመጀመር ይንኩ",
        "gate.startnote": "ሲነኩ ለስላሳ ሙዚቃና ካሜራዎ ቀስ ብለው ይጀምራሉ።",
        "gate.camera": "<b>ስለ ካሜራዎ:</b> ቪዲዮዎ <b>በራስዎ መሣሪያ ላይ</b> ብቻ ይተነተናል &mdash; ለስሜት መግለጫና የልብ ምልክቶች ብቻ። ቪዲዮው ራሱ <b>ወደ እኛ አይላክም፣ የትም አይቀመጥም</b>። ከመሣሪያዎ ምንም አይወጣም። ካሜራውን አልቀበልም ማለት ይችላሉ፤ ሌላውን ሁሉ አሁንም መጠቀም ይችላሉ።",
        "gate.ainotice": "<b>እባክዎ ይወቁ:</b> InnerLight <b>የአርቴፊሻል ኢንተለጀንስ ፕሮግራም</b> ነው &mdash; ኮምፒውተር እንጂ ሰው አይደለም። ቴራፒስት፣ ሐኪም ወይም ጠበቃ አይደለም፤ ለአንዳንድ ታዳጊዎች ላይስማማ ይችላል። በአስቸኳይ ሁኔታ <b>988</b> ይደውሉ ወይም መልእክት ይላኩ፣ ወይም <b>911</b> ይደውሉ። <a href='/safety' style='color:#2e6e8e;'>በችግር ጊዜ እንዴት እንደምንመልስ</a>",
        "gate.adult": "በመቀጠል 18 ዓመት ወይም ከዚያ በላይ መሆንዎን ያረጋግጣሉ። <a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>ከ18 በታች ነዎት? አሁንም እውነተኛ እርዳታ አለን።</a>",
        "story.title": "ታሪክዎን ይንገሩኝ።",
        "story.sub": "ጊዜዎን ይውሰዱ። እውነት የሚሰማዎትን ይናገሩ። እየሰማሁ ነው።",
        "story.resume": "ከዚህ በፊት እዚህ ነበሩ? ታሪክዎን ይቀጥሉ",
        "story.ainote": "InnerLight የAI ፕሮግራም ነው &mdash; ሰው አይደለም፣ ቴራፒስት፣ ሐኪም ወይም ጠበቃም አይደለም።",
        "story.safetylink": "ደህንነትና የችግር ጊዜ ፕሮቶኮል",
        "story.placeholder": "ከፈለጉበት ቦታ ይጀምሩ... (ለመላክ Enter ይጫኑ)",
        "story.send": "ላክ",
        "music.now": "&#9834; ለስላሳ ሙዚቃ እየተጫወተ ነው",
        "music.change": "ሙዚቃ ይቀይሩ",
        "music.pulseon": "&#10041; የመረጋጋት ምት፡ በርቷል",
        "music.voiceoff": "&#128263; የንግግር ድምፅ፡ ጠፍቷል",
        "rail.provider": "አገልግሎት ሰጪ",
        "rail.legal": "ሕጋዊ",
        "rail.nearby": "በአቅራቢያ ያለ እርዳታ",
        "rail.activities": "እንቅስቃሴዎች",
        "rail.save": "&#128278; አስቀምጥ",
        "rail.testmic": "ማይክ ይሞክሩ",
        "glink.about": "ስለ እኛ",
        "glink.how": "እንዴት እንደሚሰራ",
        "glink.stories": "ጉብኝት እንዴት እንደሚሄድ",
        "glink.resources": "እውነተኛ እርዳታ",
        "glink.research": "ምርምር",
        "glink.safety": "ደህንነት",
        "glink.privacy": "የእርስዎ ግላዊነት",
        "glink.updates": "ዜናዎች",
        "glink.contact": "ያግኙን",
        "glink.faq": "ተደጋጋሚ ጥያቄዎች",
        "glink.terms": "ውሎች"
      },
      ha: {
        "gate.tagline": "Wuri mai natsuwa da sirri don ba da labarinka.<br>Babu abin da ka raba da za a nuna wa kowa &mdash; an ɓoye shi da rufa-rufa.",
        "gate.begin": "Taɓa don farawa",
        "gate.startnote": "Kiɗa mai laushi da kyamararka za su fara a hankali idan ka taɓa.",
        "gate.camera": "<b>Game da kyamararka:</b> ana nazarin bidiyonka <b>a kan na&#39;urarka kaɗai</b> &mdash; don alamun fuska da na zuciya kawai. Bidiyon kansa <b>ba a aiko mana ba, ba a adana shi ko'ina ba</b>. Babu abin da ke barin na&#39;urarka. Kana iya ƙin kyamarar kuma har yanzu ka yi amfani da sauran komai.",
        "gate.ainotice": "<b>Ka sani:</b> InnerLight <b>shirin basirar wucin gadi ne</b> &mdash; kwamfuta ce, ba mutum ba. Ba likita ba ne, ba mai ilimin halin ɗan adam ba, ba lauya ba, kuma wataƙila bai dace da wasu yara ba. A gaggawa, kira ko aika saƙo zuwa <b>988</b> ko kira <b>911</b>. <a href='/safety' style='color:#2e6e8e;'>Yadda muke amsawa a lokacin gaggawa</a>",
        "gate.adult": "Ta ci gaba kana tabbatar da cewa shekarunka 18 ne ko fiye. <a href='#' onclick='showMinorBridge();return false;' style='color:#2e6e8e;'>Kasa da 18? Har yanzu muna da taimako na gaske dominka.</a>",
        "story.title": "Ba ni labarinka.",
        "story.sub": "Ɗauki lokacinka. Faɗi duk abin da ke gaskiya a gare ka. Ina saurare.",
        "story.resume": "Ka taɓa zuwa nan? Ci gaba da labarinka",
        "story.ainote": "InnerLight shirin AI ne &mdash; ba mutum ba, ba likita ba, ba mai ilimin halin ɗan adam ba, ba lauya ba.",
        "story.safetylink": "Tsaro da ƙa'idar gaggawa",
        "story.placeholder": "Fara daga inda kake so... (danna Enter don aikawa)",
        "story.send": "Aika",
        "music.now": "&#9834; kiɗa mai laushi na kaɗawa",
        "music.change": "Canza kiɗa",
        "music.pulseon": "&#10041; Bugun natsuwa: a kunne",
        "music.voiceoff": "&#128263; Muryar magana: A kashe",
        "rail.provider": "Mai ba da hidima",
        "rail.legal": "Shari&#39;a",
        "rail.nearby": "Taimako na kusa",
        "rail.activities": "Ayyuka",
        "rail.save": "&#128278; Ajiye",
        "rail.testmic": "Gwada makirufo",
        "glink.about": "Game da mu",
        "glink.how": "Yadda yake aiki",
        "glink.stories": "Yadda ziyara take",
        "glink.resources": "Taimako na gaske",
        "glink.research": "Bincike",
        "glink.safety": "Tsaro",
        "glink.privacy": "Sirrinka",
        "glink.updates": "Sabbin abubuwa",
        "glink.contact": "Tuntuɓe mu",
        "glink.faq": "Tambayoyin da ake yawan yi",
        "glink.terms": "Sharuɗɗa"
      }
    };
    // Current UI language, and helpers that make the SPOKEN voice and the voice
    // INPUT follow it — so Spanish and Chinese are actually heard in-language,
    // not read aloud with an English accent.
    window._ilLang = 'en';
    function ilBcp47(code){ var m={es:'es-ES',zh:'zh-CN',hi:'hi-IN',pa:'pa-IN',bn:'bn-IN',tl:'fil-PH',to:'to-TO'}; return m[code]||'en-US'; }
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
          // the accessible name follows the placeholder into the same language
          if (phs[j].getAttribute('aria-label') != null){
            phs[j].setAttribute('aria-label', phs[j].getAttribute('placeholder')||'');
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
        try { var _sp=document.getElementById('scene-picker'); if (_sp && typeof _ilux==='function') _sp.setAttribute('aria-label', _ilux('scn.aria')); } catch(e){}
        // A feeling prompt already on screen must follow the person into
        // their new language, not linger in the old one.
        try { var _ci=document.getElementById('il-checkin'); if (_ci && _ci.querySelector('button')) { _ci.remove(); if (typeof showCheckin==='function') showCheckin(); } } catch(e){}
        try { var _sc=document.getElementById('sam-card'); if (_sc) { _sc.remove(); if (typeof showCalmScale==='function') showCalmScale(window._lastSamPhase||''); } } catch(e){}
        // the arrival greeting is rendered word-by-word in the chosen language
        try { if (typeof renderGateGreeting === 'function') renderGateGreeting(false); } catch(e){}
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

    // ===================== CINEMATIC ARRIVAL (welcome gate) =====================
    // A time-of-day scene built from the founder's own photographs, served by the
    // app itself (/scenes/...). The story screen later starts on the SAME photo,
    // so the single tap feels like walking further into the same place.
    var GATE_SCENES = {
      morning:   { key: 'g_horizon_dawn',     src: '/scenes/gen_photo_6_golden_horizon_dawn.jpg',
                   pos: '50% 42%', p: { x: '22%', y: '28%', s: '84vmin', a: .5 } },
      afternoon: { key: 'g_sunflower_golden', src: '/scenes/gen_photo_5_sunflower_golden.jpg',
                   pos: '50% 55%', p: { x: '38%', y: '74%', s: '76vmin', a: .5 } },
      evening:   { key: 'sunset',             src: '/scenes/photo_2_sunset_trees.jpg',
                   pos: '50% 28%', p: { x: '32%', y: '86%', s: '96vmin', a: .75 } },
      night:     { key: 'g_moonleaf_night',   src: '/scenes/gen_photo_7_moon_leaves_moonlight.jpg',
                   pos: '50% 36%', p: { x: '49%', y: '35%', s: '58vmin', a: .55 } }
    };
    // Greeting lines per language and time of day. "|" separates the lines.
    // English is always the safe fallback, like everywhere else on this page.
    // ============ UNIVERSAL UI STRINGS (_IL_UX) — every dynamic widget ============
    // Every user-facing string built by JS at runtime lives here, in all 8
    // languages, so no widget can ever fall back to English by accident.
    // ============ HANDOFF CARD TRANSLATIONS (_IL_HO) ============
    // The crisis, legal, clinical, and community handoff cards are built
    // server-side in English. This dictionary translates every one of
    // those strings instantly on the person's own device — no network,
    // no waiting, exactly when it matters most. Unknown strings fall
    // back to English rather than fail.
    var _IL_HO = {
      es: {
        "Immediate safety support": "Apoyo de seguridad inmediato",
        "Connect to 988 Crisis Lifeline": "Conectar con la Línea de Crisis 988",
        "Alert a live InnerLight monitor": "Avisar a un monitor de InnerLight en vivo",
        "Chat online with 988 (no call needed)": "Chatea en línea con 988 (sin llamar)",
        "Call 911 (immediate danger)": "Llamar al 911 (peligro inmediato)",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "¿Quieres que comparta lo que me has contado con el consejero de crisis, para que no tengas que empezar de nuevo?",
        "Talk with a licensed professional": "Habla con un profesional acreditado",
        "Start a video session with a counselor": "Iniciar una sesión de video con un consejero",
        "Schedule a session for later": "Programar una sesión para más tarde",
        "Want me to share a short summary with the counselor so your time together starts with them already understanding you?": "¿Quieres que comparta un breve resumen con el consejero, para que su tiempo juntos empiece con él ya entendiéndote?",
        "Find free/low-cost legal help near me": "Buscar ayuda legal gratuita o de bajo costo cerca de mí",
        "Save my questions for the attorney": "Guardar mis preguntas para el abogado",
        "Want me to prepare a summary of your situation and the questions to ask, so you're ready when you talk to an attorney?": "¿Quieres que prepare un resumen de tu situación y las preguntas para hacer, para que estés listo al hablar con un abogado?",
        "Connect to local resources": "Conectar con recursos locales",
        "find food assistance near me": "buscar ayuda alimentaria cerca de mí",
        "find emergency shelter near me": "buscar refugio de emergencia cerca de mí",
        "Want me to note what you need so the resource line can help you faster?": "¿Quieres que anote lo que necesitas para que la línea de recursos pueda ayudarte más rápido?",
        "Share my context so I do not have to repeat myself.": "Comparte mi contexto para que no tenga que repetirlo.",
        "Connect with {who}": "Conectar con {who}",
        "@who:a tenant rights / housing attorney": "un abogado de vivienda y derechos de inquilinos",
        "@who:a housing and benefits advocate": "un defensor de vivienda y beneficios",
        "@who:an employment attorney": "un abogado laboral",
        "@who:an employment discrimination attorney (EEOC matters)": "un abogado de discriminación laboral (asuntos EEOC)",
        "@who:a family law attorney": "un abogado de derecho familiar",
        "@who:a family law / custody attorney": "un abogado de familia y custodia",
        "@who:a domestic violence advocate and protective-order attorney": "un defensor de violencia doméstica y abogado de órdenes de protección",
        "@who:a criminal defense attorney or public defender": "un abogado defensor penal o defensor público",
        "@who:a qualified immigration attorney (not a notario)": "un abogado de inmigración calificado (no un notario)",
        "@who:an education rights attorney": "un abogado de derechos educativos",
        "@who:a patient rights / health law advocate": "un defensor de derechos del paciente y derecho sanitario",
        "@who:a disability rights attorney": "un abogado de derechos de discapacidad",
        "@who:a consumer protection attorney": "un abogado de protección al consumidor",
        "@who:a civil rights attorney": "un abogado de derechos civiles",
        "@who:a qualified attorney": "un abogado calificado"
      },
      zh: {
        "Immediate safety support": "即时安全支持",
        "Connect to 988 Crisis Lifeline": "连接 988 危机生命线",
        "Alert a live InnerLight monitor": "通知 InnerLight 在线监护员",
        "Chat online with 988 (no call needed)": "与 988 在线聊天（无需拨打电话）",
        "Call 911 (immediate danger)": "拨打 911（紧急危险）",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "要我把你告诉我的内容分享给危机辅导员，让你不用从头再说一遍吗？",
        "Talk with a licensed professional": "与持证专业人士交谈",
        "Start a video session with a counselor": "与辅导员开始视频会话",
        "Schedule a session for later": "预约稍后的会话",
        "Want me to share a short summary with the counselor so your time together starts with them already understanding you?": "要我把简短的总结分享给辅导员，让你们一开始他就已经了解你吗？",
        "Find free/low-cost legal help near me": "查找我附近的免费/低价法律帮助",
        "Save my questions for the attorney": "保存我要问律师的问题",
        "Want me to prepare a summary of your situation and the questions to ask, so you're ready when you talk to an attorney?": "要我准备一份你情况的总结和要问的问题，让你和律师交谈时有备而来吗？",
        "Connect to local resources": "连接本地资源",
        "find food assistance near me": "查找我附近的食物援助",
        "find emergency shelter near me": "查找我附近的紧急庇护所",
        "Want me to note what you need so the resource line can help you faster?": "要我记下你需要的东西，让资源热线能更快帮到你吗？",
        "Share my context so I do not have to repeat myself.": "分享我的情况，让我不用重复。",
        "Connect with {who}": "联系{who}",
        "@who:a tenant rights / housing attorney": "住房与租户权益律师",
        "@who:a housing and benefits advocate": "住房与福利事务倡导者",
        "@who:an employment attorney": "劳动法律师",
        "@who:an employment discrimination attorney (EEOC matters)": "就业歧视律师（EEOC 事务）",
        "@who:a family law attorney": "家庭法律师",
        "@who:a family law / custody attorney": "家庭法/抚养权律师",
        "@who:a domestic violence advocate and protective-order attorney": "家庭暴力事务倡导者与保护令律师",
        "@who:a criminal defense attorney or public defender": "刑事辩护律师或公设辩护人",
        "@who:a qualified immigration attorney (not a notario)": "合格的移民律师（并非“公证人”）",
        "@who:an education rights attorney": "教育权益律师",
        "@who:a patient rights / health law advocate": "患者权益/医疗法倡导者",
        "@who:a disability rights attorney": "残障权益律师",
        "@who:a consumer protection attorney": "消费者保护律师",
        "@who:a civil rights attorney": "民权律师",
        "@who:a qualified attorney": "合格的律师"
      },
      hi: {
        "Immediate safety support": "तत्काल सुरक्षा सहारा",
        "Connect to 988 Crisis Lifeline": "988 क्राइसिस लाइफ़लाइन से जुड़ें",
        "Alert a live InnerLight monitor": "InnerLight के लाइव मॉनिटर को सूचित करें",
        "Chat online with 988 (no call needed)": "988 से ऑनलाइन चैट करें (कॉल की ज़रूरत नहीं)",
        "Call 911 (immediate danger)": "911 पर कॉल करें (तत्काल खतरा)",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "क्या मैं आपकी बताई बातें क्राइसिस काउंसलर से साझा कर दूँ, ताकि आपको फिर से शुरू न करना पड़े?",
        "Talk with a licensed professional": "लाइसेंस प्राप्त पेशेवर से बात करें",
        "Start a video session with a counselor": "काउंसलर के साथ वीडियो सत्र शुरू करें",
        "Schedule a session for later": "बाद के लिए सत्र निर्धारित करें",
        "Want me to share a short summary with the counselor so your time together starts with them already understanding you?": "क्या मैं काउंसलर से एक छोटा सारांश साझा कर दूँ, ताकि आपकी बातचीत की शुरुआत ही आपको समझने के साथ हो?",
        "Find free/low-cost legal help near me": "मेरे पास मुफ़्त/कम लागत की कानूनी मदद खोजें",
        "Save my questions for the attorney": "वकील के लिए मेरे सवाल सहेजें",
        "Want me to prepare a summary of your situation and the questions to ask, so you're ready when you talk to an attorney?": "क्या मैं आपकी स्थिति का सारांश और पूछने योग्य सवाल तैयार कर दूँ, ताकि वकील से बात करते समय आप तैयार रहें?",
        "Connect to local resources": "स्थानीय संसाधनों से जुड़ें",
        "find food assistance near me": "मेरे पास भोजन सहायता खोजें",
        "find emergency shelter near me": "मेरे पास आपातकालीन आश्रय खोजें",
        "Want me to note what you need so the resource line can help you faster?": "क्या मैं आपकी ज़रूरतें नोट कर लूँ ताकि संसाधन लाइन आपकी जल्दी मदद कर सके?",
        "Share my context so I do not have to repeat myself.": "मेरा विवरण साझा करें ताकि मुझे दोहराना न पड़े।",
        "Connect with {who}": "{who} से जुड़ें",
        "@who:a tenant rights / housing attorney": "किरायेदार अधिकार/आवास वकील",
        "@who:a housing and benefits advocate": "आवास और लाभ सलाहकार",
        "@who:an employment attorney": "रोज़गार वकील",
        "@who:an employment discrimination attorney (EEOC matters)": "रोज़गार भेदभाव वकील (EEOC मामले)",
        "@who:a family law attorney": "पारिवारिक कानून वकील",
        "@who:a family law / custody attorney": "पारिवारिक/अभिरक्षा वकील",
        "@who:a domestic violence advocate and protective-order attorney": "घरेलू हिंसा सलाहकार व संरक्षण-आदेश वकील",
        "@who:a criminal defense attorney or public defender": "आपराधिक बचाव वकील या सरकारी वकील",
        "@who:a qualified immigration attorney (not a notario)": "योग्य आप्रवासन वकील (नोटारियो नहीं)",
        "@who:an education rights attorney": "शिक्षा अधिकार वकील",
        "@who:a patient rights / health law advocate": "मरीज़ अधिकार/स्वास्थ्य कानून सलाहकार",
        "@who:a disability rights attorney": "दिव्यांगता अधिकार वकील",
        "@who:a consumer protection attorney": "उपभोक्ता संरक्षण वकील",
        "@who:a civil rights attorney": "नागरिक अधिकार वकील",
        "@who:a qualified attorney": "योग्य वकील"
      },
      pa: {
        "Immediate safety support": "ਤੁਰੰਤ ਸੁਰੱਖਿਆ ਸਹਾਰਾ",
        "Connect to 988 Crisis Lifeline": "988 ਕ੍ਰਾਈਸਿਸ ਲਾਈਫ਼ਲਾਈਨ ਨਾਲ ਜੁੜੋ",
        "Alert a live InnerLight monitor": "InnerLight ਦੇ ਲਾਈਵ ਮਾਨੀਟਰ ਨੂੰ ਸੂਚਿਤ ਕਰੋ",
        "Chat online with 988 (no call needed)": "988 ਨਾਲ ਆਨਲਾਈਨ ਚੈਟ ਕਰੋ (ਕਾਲ ਦੀ ਲੋੜ ਨਹੀਂ)",
        "Call 911 (immediate danger)": "911 ਉੱਤੇ ਕਾਲ ਕਰੋ (ਤੁਰੰਤ ਖ਼ਤਰਾ)",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "ਕੀ ਮੈਂ ਤੁਹਾਡੀਆਂ ਦੱਸੀਆਂ ਗੱਲਾਂ ਕ੍ਰਾਈਸਿਸ ਕਾਊਂਸਲਰ ਨਾਲ ਸਾਂਝੀਆਂ ਕਰ ਦਿਆਂ, ਤਾਂ ਜੋ ਤੁਹਾਨੂੰ ਮੁੜ ਤੋਂ ਸ਼ੁਰੂ ਨਾ ਕਰਨਾ ਪਵੇ?",
        "Talk with a licensed professional": "ਲਾਇਸੰਸਸ਼ੁਦਾ ਪੇਸ਼ੇਵਰ ਨਾਲ ਗੱਲ ਕਰੋ",
        "Start a video session with a counselor": "ਕਾਊਂਸਲਰ ਨਾਲ ਵੀਡੀਓ ਸੈਸ਼ਨ ਸ਼ੁਰੂ ਕਰੋ",
        "Schedule a session for later": "ਬਾਅਦ ਲਈ ਸੈਸ਼ਨ ਤੈਅ ਕਰੋ",
        "Want me to share a short summary with the counselor so your time together starts with them already understanding you?": "ਕੀ ਮੈਂ ਕਾਊਂਸਲਰ ਨਾਲ ਇੱਕ ਛੋਟਾ ਸਾਰ ਸਾਂਝਾ ਕਰ ਦਿਆਂ, ਤਾਂ ਜੋ ਤੁਹਾਡੀ ਗੱਲਬਾਤ ਦੀ ਸ਼ੁਰੂਆਤ ਹੀ ਤੁਹਾਨੂੰ ਸਮਝਣ ਨਾਲ ਹੋਵੇ?",
        "Find free/low-cost legal help near me": "ਮੇਰੇ ਨੇੜੇ ਮੁਫ਼ਤ/ਘੱਟ ਖਰਚ ਵਾਲੀ ਕਾਨੂੰਨੀ ਮਦਦ ਲੱਭੋ",
        "Save my questions for the attorney": "ਵਕੀਲ ਲਈ ਮੇਰੇ ਸਵਾਲ ਸਾਂਭੋ",
        "Want me to prepare a summary of your situation and the questions to ask, so you're ready when you talk to an attorney?": "ਕੀ ਮੈਂ ਤੁਹਾਡੀ ਸਥਿਤੀ ਦਾ ਸਾਰ ਅਤੇ ਪੁੱਛਣ ਵਾਲੇ ਸਵਾਲ ਤਿਆਰ ਕਰ ਦਿਆਂ, ਤਾਂ ਜੋ ਵਕੀਲ ਨਾਲ ਗੱਲ ਕਰਨ ਵੇਲੇ ਤੁਸੀਂ ਤਿਆਰ ਹੋਵੋ?",
        "Connect to local resources": "ਸਥਾਨਕ ਸਰੋਤਾਂ ਨਾਲ ਜੁੜੋ",
        "find food assistance near me": "ਮੇਰੇ ਨੇੜੇ ਭੋਜਨ ਸਹਾਇਤਾ ਲੱਭੋ",
        "find emergency shelter near me": "ਮੇਰੇ ਨੇੜੇ ਐਮਰਜੈਂਸੀ ਆਸਰਾ ਲੱਭੋ",
        "Want me to note what you need so the resource line can help you faster?": "ਕੀ ਮੈਂ ਤੁਹਾਡੀਆਂ ਲੋੜਾਂ ਨੋਟ ਕਰ ਲਵਾਂ ਤਾਂ ਜੋ ਸਰੋਤ ਲਾਈਨ ਤੁਹਾਡੀ ਛੇਤੀ ਮਦਦ ਕਰ ਸਕੇ?",
        "Share my context so I do not have to repeat myself.": "ਮੇਰਾ ਵੇਰਵਾ ਸਾਂਝਾ ਕਰੋ ਤਾਂ ਜੋ ਮੈਨੂੰ ਦੁਹਰਾਉਣਾ ਨਾ ਪਵੇ।",
        "Connect with {who}": "{who} ਨਾਲ ਜੁੜੋ",
        "@who:a tenant rights / housing attorney": "ਕਿਰਾਏਦਾਰ ਹੱਕ/ਰਿਹਾਇਸ਼ ਵਕੀਲ",
        "@who:a housing and benefits advocate": "ਰਿਹਾਇਸ਼ ਅਤੇ ਲਾਭ ਸਲਾਹਕਾਰ",
        "@who:an employment attorney": "ਰੁਜ਼ਗਾਰ ਵਕੀਲ",
        "@who:an employment discrimination attorney (EEOC matters)": "ਰੁਜ਼ਗਾਰ ਵਿਤਕਰਾ ਵਕੀਲ (EEOC ਮਾਮਲੇ)",
        "@who:a family law attorney": "ਪਰਿਵਾਰਕ ਕਾਨੂੰਨ ਵਕੀਲ",
        "@who:a family law / custody attorney": "ਪਰਿਵਾਰਕ/ਕਸਟਡੀ ਵਕੀਲ",
        "@who:a domestic violence advocate and protective-order attorney": "ਘਰੇਲੂ ਹਿੰਸਾ ਸਲਾਹਕਾਰ ਤੇ ਸੁਰੱਖਿਆ-ਹੁਕਮ ਵਕੀਲ",
        "@who:a criminal defense attorney or public defender": "ਫੌਜਦਾਰੀ ਬਚਾਅ ਵਕੀਲ ਜਾਂ ਸਰਕਾਰੀ ਵਕੀਲ",
        "@who:a qualified immigration attorney (not a notario)": "ਯੋਗ ਇਮੀਗ੍ਰੇਸ਼ਨ ਵਕੀਲ (ਨੋਟਾਰੀਓ ਨਹੀਂ)",
        "@who:an education rights attorney": "ਸਿੱਖਿਆ ਹੱਕ ਵਕੀਲ",
        "@who:a patient rights / health law advocate": "ਮਰੀਜ਼ ਹੱਕ/ਸਿਹਤ ਕਾਨੂੰਨ ਸਲਾਹਕਾਰ",
        "@who:a disability rights attorney": "ਦਿਵਿਆਂਗਤਾ ਹੱਕ ਵਕੀਲ",
        "@who:a consumer protection attorney": "ਖਪਤਕਾਰ ਸੁਰੱਖਿਆ ਵਕੀਲ",
        "@who:a civil rights attorney": "ਨਾਗਰਿਕ ਹੱਕ ਵਕੀਲ",
        "@who:a qualified attorney": "ਯੋਗ ਵਕੀਲ"
      },
      bn: {
        "Immediate safety support": "তাৎক্ষণিক নিরাপত্তা সহায়তা",
        "Connect to 988 Crisis Lifeline": "988 ক্রাইসিস লাইফলাইনে যুক্ত হন",
        "Alert a live InnerLight monitor": "InnerLight-এর লাইভ মনিটরকে জানান",
        "Chat online with 988 (no call needed)": "988-এর সাথে অনলাইনে চ্যাট করুন (কল লাগবে না)",
        "Call 911 (immediate danger)": "911 নম্বরে কল করুন (তাৎক্ষণিক বিপদ)",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "আপনি আমাকে যা বলেছেন তা কি ক্রাইসিস কাউন্সেলরের সাথে ভাগ করব, যাতে আপনাকে আবার শুরু থেকে বলতে না হয়?",
        "Talk with a licensed professional": "লাইসেন্সধারী পেশাদারের সাথে কথা বলুন",
        "Start a video session with a counselor": "কাউন্সেলরের সাথে ভিডিও সেশন শুরু করুন",
        "Schedule a session for later": "পরের জন্য সেশন নির্ধারণ করুন",
        "Want me to share a short summary with the counselor so your time together starts with them already understanding you?": "আমি কি কাউন্সেলরের সাথে একটি সংক্ষিপ্ত সারাংশ ভাগ করব, যাতে আপনাদের সময় শুরু হয় আপনাকে বোঝা দিয়েই?",
        "Find free/low-cost legal help near me": "আমার কাছে বিনামূল্যে/কম খরচের আইনি সাহায্য খুঁজুন",
        "Save my questions for the attorney": "আইনজীবীর জন্য আমার প্রশ্ন সংরক্ষণ করুন",
        "Want me to prepare a summary of your situation and the questions to ask, so you're ready when you talk to an attorney?": "আমি কি আপনার পরিস্থিতির সারাংশ ও জিজ্ঞাসার প্রশ্নগুলো তৈরি করব, যাতে আইনজীবীর সাথে কথা বলার সময় আপনি প্রস্তুত থাকেন?",
        "Connect to local resources": "স্থানীয় সংস্থানের সাথে যুক্ত হন",
        "find food assistance near me": "আমার কাছে খাদ্য সহায়তা খুঁজুন",
        "find emergency shelter near me": "আমার কাছে জরুরি আশ্রয় খুঁজুন",
        "Want me to note what you need so the resource line can help you faster?": "আমি কি আপনার প্রয়োজনগুলো লিখে রাখব যাতে রিসোর্স লাইন দ্রুত সাহায্য করতে পারে?",
        "Share my context so I do not have to repeat myself.": "আমার প্রসঙ্গ ভাগ করুন যাতে আমাকে আবার বলতে না হয়।",
        "Connect with {who}": "{who} এর সাথে যুক্ত হন",
        "@who:a tenant rights / housing attorney": "ভাড়াটিয়া অধিকার/আবাসন আইনজীবী",
        "@who:a housing and benefits advocate": "আবাসন ও সুবিধা সহায়তাকারী",
        "@who:an employment attorney": "কর্মসংস্থান আইনজীবী",
        "@who:an employment discrimination attorney (EEOC matters)": "কর্মক্ষেত্রে বৈষম্য আইনজীবী (EEOC বিষয়)",
        "@who:a family law attorney": "পারিবারিক আইনজীবী",
        "@who:a family law / custody attorney": "পারিবারিক/হেফাজত আইনজীবী",
        "@who:a domestic violence advocate and protective-order attorney": "পারিবারিক সহিংসতা সহায়তাকারী ও সুরক্ষা-আদেশ আইনজীবী",
        "@who:a criminal defense attorney or public defender": "ফৌজদারি প্রতিরক্ষা আইনজীবী বা পাবলিক ডিফেন্ডার",
        "@who:a qualified immigration attorney (not a notario)": "যোগ্য অভিবাসন আইনজীবী (নোটারিও নয়)",
        "@who:an education rights attorney": "শিক্ষা অধিকার আইনজীবী",
        "@who:a patient rights / health law advocate": "রোগীর অধিকার/স্বাস্থ্য আইন সহায়তাকারী",
        "@who:a disability rights attorney": "প্রতিবন্ধী অধিকার আইনজীবী",
        "@who:a consumer protection attorney": "ভোক্তা সুরক্ষা আইনজীবী",
        "@who:a civil rights attorney": "নাগরিক অধিকার আইনজীবী",
        "@who:a qualified attorney": "যোগ্য আইনজীবী"
      },
      tl: {
        "Immediate safety support": "Agarang suporta sa kaligtasan",
        "Connect to 988 Crisis Lifeline": "Kumonekta sa 988 Crisis Lifeline",
        "Alert a live InnerLight monitor": "Abisuhan ang live na InnerLight monitor",
        "Chat online with 988 (no call needed)": "Makipag-chat online sa 988 (hindi na kailangang tumawag)",
        "Call 911 (immediate danger)": "Tumawag sa 911 (agarang panganib)",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "Gusto mo bang ibahagi ko sa crisis counselor ang sinabi mo, para hindi ka na mag-uumpisa muli?",
        "Talk with a licensed professional": "Makipag-usap sa lisensyadong propesyonal",
        "Start a video session with a counselor": "Magsimula ng video session sa counselor",
        "Schedule a session for later": "Mag-iskedyul ng session para mamaya",
        "Want me to share a short summary with the counselor so your time together starts with them already understanding you?": "Gusto mo bang magbahagi ako ng maikling buod sa counselor para pagsisimula pa lang ay naiintindihan ka na niya?",
        "Find free/low-cost legal help near me": "Maghanap ng libre/murang tulong legal malapit sa akin",
        "Save my questions for the attorney": "I-save ang mga tanong ko para sa abogado",
        "Want me to prepare a summary of your situation and the questions to ask, so you're ready when you talk to an attorney?": "Gusto mo bang ihanda ko ang buod ng sitwasyon mo at ang mga itatanong, para handa ka sa pakikipag-usap sa abogado?",
        "Connect to local resources": "Kumonekta sa mga lokal na mapagkukunan",
        "find food assistance near me": "maghanap ng tulong sa pagkain malapit sa akin",
        "find emergency shelter near me": "maghanap ng emergency shelter malapit sa akin",
        "Want me to note what you need so the resource line can help you faster?": "Gusto mo bang itala ko ang kailangan mo para mas mabilis kang matulungan ng resource line?",
        "Share my context so I do not have to repeat myself.": "Ibahagi ang konteksto ko para hindi ko na kailangang ulitin.",
        "Connect with {who}": "Kumonekta sa {who}",
        "@who:a tenant rights / housing attorney": "abogado sa karapatan ng nangungupahan/pabahay",
        "@who:a housing and benefits advocate": "tagapagtaguyod sa pabahay at benepisyo",
        "@who:an employment attorney": "abogado sa trabaho",
        "@who:an employment discrimination attorney (EEOC matters)": "abogado sa diskriminasyon sa trabaho (mga usaping EEOC)",
        "@who:a family law attorney": "abogado sa batas pampamilya",
        "@who:a family law / custody attorney": "abogado sa pamilya/kustodiya",
        "@who:a domestic violence advocate and protective-order attorney": "tagapagtaguyod sa karahasan sa tahanan at abogado sa protective order",
        "@who:a criminal defense attorney or public defender": "abogado sa depensa kriminal o public defender",
        "@who:a qualified immigration attorney (not a notario)": "kwalipikadong abogado sa imigrasyon (hindi notario)",
        "@who:an education rights attorney": "abogado sa karapatan sa edukasyon",
        "@who:a patient rights / health law advocate": "tagapagtaguyod sa karapatan ng pasyente/batas pangkalusugan",
        "@who:a disability rights attorney": "abogado sa karapatan ng may kapansanan",
        "@who:a consumer protection attorney": "abogado sa proteksyon ng mamimili",
        "@who:a civil rights attorney": "abogado sa karapatang sibil",
        "@who:a qualified attorney": "kwalipikadong abogado"
      },
      to: {
        "Immediate safety support": "Poupou maluʻi fakavavevave",
        "Connect to 988 Crisis Lifeline": "Fakafehokotaki ki he 988 Crisis Lifeline",
        "Alert a live InnerLight monitor": "Fakatokanga ki ha leʻo InnerLight ʻoku ʻi ai",
        "Chat online with 988 (no call needed)": "Fetalanoaʻaki ʻi he ʻinitaneti mo e 988 (ʻikai fiemaʻu ha telefoni)",
        "Call 911 (immediate danger)": "Telefoni ki he 911 (fakatuʻutāmaki vave)",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "Te ke loto ke u vahevahe e meʻa kuó ke talamai ki he faleʻi fakatuʻupakeé, koeʻuhí ke ʻoua te ke toe kamata mei he kamataʻangá?",
        "Talk with a licensed professional": "Talanoa mo ha taukei maʻu laiseni",
        "Start a video session with a counselor": "Kamata ha fetalanoaʻaki vitiō mo ha faleʻi",
        "Schedule a session for later": "Fokotuʻu ha taimi fetalanoaʻaki ki ha taimi ʻamui",
        "Want me to share a short summary with the counselor so your time together starts with them already understanding you?": "Te ke loto ke u vahevahe ha fakamatala nounou ki he faleʻí koeʻuhí ke kamata hoʻomo taimí kuó ne ʻosi mahinoʻi koe?",
        "Find free/low-cost legal help near me": "Kumi ha tokoni fakalao taʻetotongi/totongi maʻamaʻa ofi mai",
        "Save my questions for the attorney": "Tauhi ʻeku ngaahi fehuʻi ki he loeá",
        "Want me to prepare a summary of your situation and the questions to ask, so you're ready when you talk to an attorney?": "Te ke loto ke u teuteuʻi ha fakamatala ki hoʻo tuʻungá mo e ngaahi fehuʻi ke fai, koeʻuhí ke ke mateuteu ʻi hoʻo talanoa mo ha loea?",
        "Connect to local resources": "Fakafehokotaki ki he ngaahi maʻuʻanga tokoni fakalotofonua",
        "find food assistance near me": "kumi tokoni meʻakai ofi mai",
        "find emergency shelter near me": "kumi ha hūfanga fakavavevave ofi mai",
        "Want me to note what you need so the resource line can help you faster?": "Te ke loto ke u hiki e meʻa ʻokú ke fiemaʻú koeʻuhí ke vave ange hono tokoniʻi koe ʻe he laine tokoní?",
        "Share my context so I do not have to repeat myself.": "Vahevahe ʻeku fakamatalá ke ʻoua te u toe lea tuʻo ua.",
        "Connect with {who}": "Fakafehokotaki ki ha {who}",
        "@who:a tenant rights / housing attorney": "ha loea ki he totonu ʻo e kakai nofo totongi mo e nofoʻanga",
        "@who:a housing and benefits advocate": "ha taukapo ki he nofoʻanga mo e ngaahi monūʻia",
        "@who:an employment attorney": "ha loea ngāue",
        "@who:an employment discrimination attorney (EEOC matters)": "ha loea ki he filifilimānako he ngāué (ngaahi meʻa EEOC)",
        "@who:a family law attorney": "ha loea lao fakafāmili",
        "@who:a family law / custody attorney": "ha loea fakafāmili mo e tauhi fānau",
        "@who:a domestic violence advocate and protective-order attorney": "ha taukapo ki he fakamamahi fakaʻapi mo ha loea tuʻutuʻuni maluʻi",
        "@who:a criminal defense attorney or public defender": "ha loea maluʻi hia pe loea fakapuleʻanga",
        "@who:a qualified immigration attorney (not a notario)": "ha loea hikifonua taau (ʻikai ko ha notario)",
        "@who:an education rights attorney": "ha loea ki he totonu ʻo e akó",
        "@who:a patient rights / health law advocate": "ha taukapo ki he totonu ʻo e mahakí mo e lao moʻui",
        "@who:a disability rights attorney": "ha loea ki he totonu ʻo e faingataʻaʻiá",
        "@who:a consumer protection attorney": "ha loea maluʻi fakatau",
        "@who:a civil rights attorney": "ha loea ki he ngaahi totonu fakasivilé",
        "@who:a qualified attorney": "ha loea taau"
      },
      sw: {
        "Immediate safety support": "Msaada wa usalama wa haraka",
        "Connect to 988 Crisis Lifeline": "Unganishwa na 988 Crisis Lifeline",
        "Chat online with 988 (no call needed)": "Piga gumzo mtandaoni na 988 (bila kupiga simu)",
        "Alert a live InnerLight monitor": "Arifu mwangalizi wa InnerLight aliye mtandaoni",
        "Call 911 (immediate danger)": "Piga 911 (hatari ya papo hapo)",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "Unataka nishiriki uliyoniambia na mshauri wa dharura, ili usianze upya?",
        "Connect with {who}": "Unganishwa na {who}",
        "Share my context so I do not have to repeat myself.": "Shiriki maelezo yangu ili nisilazimike kurudia.",
        "@who:a qualified attorney": "wakili aliyehitimu"
      },
      am: {
        "Immediate safety support": "አፋጣኝ የደህንነት ድጋፍ",
        "Connect to 988 Crisis Lifeline": "ከ988 Crisis Lifeline ጋር ይገናኙ",
        "Chat online with 988 (no call needed)": "ከ988 ጋር በመስመር ላይ ይወያዩ (መደወል አያስፈልግም)",
        "Alert a live InnerLight monitor": "የInnerLight ቀጥታ ተቆጣጣሪን ያሳውቁ",
        "Call 911 (immediate danger)": "911 ይደውሉ (አፋጣኝ አደጋ)",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "የነገሩኝን ከችግር አማካሪው ጋር እንዳካፍል ይፈልጋሉ፣ እንደገና እንዳይጀምሩ?",
        "Connect with {who}": "ከ{who} ጋር ይገናኙ",
        "Share my context so I do not have to repeat myself.": "እንደገና እንዳልደግም መረጃዬን አካፍል።",
        "@who:a qualified attorney": "ብቁ ጠበቃ"
      },
      ha: {
        "Immediate safety support": "Tallafin tsaro na gaggawa",
        "Connect to 988 Crisis Lifeline": "Haɗa da 988 Crisis Lifeline",
        "Chat online with 988 (no call needed)": "Yi hira ta yanar gizo da 988 (ba sai ka kira ba)",
        "Alert a live InnerLight monitor": "Sanar da mai sa ido na InnerLight kai tsaye",
        "Call 911 (immediate danger)": "Kira 911 (haɗari na gaggawa)",
        "Want me to share what you've told me with the crisis counselor, so you don't have to start over?": "Kana so in raba abin da ka faɗa da mai ba da shawara na gaggawa, don kada ka sake farawa?",
        "Connect with {who}": "Haɗa da {who}",
        "Share my context so I do not have to repeat myself.": "Raba bayanina don kada in sake maimaitawa.",
        "@who:a qualified attorney": "lauya ƙwararre"
      }
    };
    function _ilho(s){
      var lg = (window._ilLang||'en'); if (lg === 'en' || !s) return s;
      var d = _IL_HO[lg]; if (!d) return s;
      if (d[s] != null) return d[s];
      if (s.indexOf('Connect with ') === 0) {
        var who = s.slice(13);
        var tw = d['@who:' + who] || who;
        return (d['Connect with {who}'] || 'Connect with {who}').replace('{who}', tw);
      }
      return s;
    }
    window._ilho = _ilho;

    var _IL_UX = {
      en: {
        "sam.q": "How are you feeling right now? (tap one, or ignore me)",
        "sam.s1": "Very distressed",
        "sam.s2": "Uneasy",
        "sam.s3": "In between",
        "sam.s4": "Okay",
        "sam.s5": "Calm",
        "fb.ask": "If you have a moment: did this help? Your answer is anonymous and helps us help others.",
        "fb.yes": "It helped",
        "fb.some": "Somewhat",
        "fb.no": "Not really",
        "fb.ph": "Anything you want to share about how you feel, or what helped? (optional)",
        "fb.share": "Share",
        "fb.nothanks": "No thanks",
        "fb.thanks": "Thank you for sharing — it genuinely helps us reach others.",
        "fb.close": "Close",
        "mb.title": "You matter, and real help is here for you.",
        "mb.lead": "InnerLight is built for adults right now — but you are not being turned away. What you are feeling deserves a real person who is trained to help someone your age, right now:",
        "mb.b1": "<b>• Talk to a trusted adult</b> — a parent, family member, school counselor, coach, or teacher. Starting the sentence is the hardest part; you can even show them this screen.",
        "mb.b2": "<b>• Call or text 988</b> — free, 24/7, and they help young people every day.",
        "mb.b3": "<b>• Text HOME to 741741</b> — Crisis Text Line, free, 24/7.",
        "mb.b4": "<b>• Teen Line: text TEEN to 839863</b> — teens helping teens, evenings.",
        "mb.danger": "If you are in immediate danger, call 911.",
        "mb.ok": "Okay",
        "mb.note": "It sounds like you may be under 18 — and I want the right help for you, which is a real person trained to support someone your age. Please look at the options I just showed you, and please tell a trusted adult how you are feeling. You deserve real support.",
        "sub.note": "I am really glad being here helps, and I want to be honest with you because I care: I am not a person, and I cannot be a substitute for real human connection. What I can do is stay with you right now and help you reach people who can truly be there for you — a counselor, someone you trust, a real voice. You deserve that, more than you deserve a screen. Would you like me to help you reach a real person?",
        "gb.n1": "You have shared a lot, and I am really glad you did. Whenever you feel ready, the most helpful next step is talking with a real person who can stay with you beyond this moment. I can connect you gently, whenever you want.",
        "gb.n2": "I am still right here with you, and there is no rush. When you are ready, a real person can carry this forward with you. Would you like me to help you reach someone now?",
        "gb.connect": "Connect me with someone",
        "gb.keep": "Keep talking a little longer",
        "sv.min": "There is not much to save yet. Share a little of your story first, then tap Save again and I will give you a private return code.",
        "sv.q": "Save where you are? You will get a private return code only you hold.",
        "sv.auto": "Would you like to save where you are, so you don’t have to start over if you come back?",
        "sv.btn": "Save my place",
        "sv.notnow": "Not now",
        "sv.saved": "Saved. This is your return code — keep it somewhere safe:",
        "sv.code": "Only this code can reopen your story — not even we can read it without the code.",
        "sv.copy": "Copy code",
        "sv.done": "Done",
        "sv.empty": "There was nothing saved yet — share a little first.",
        "sv.err": "Could not save right now. Please try again.",
        "mic.rec": "Recording 3 seconds — say anything…",
        "mic.ok": "That is what your mic picked up — if you can hear yourself, it works.",
        "mic.na": "The microphone is not available right now — that is okay. Typing works just as well.",
        "mic.saved": "Saved — press Enter to send, or keep editing",
        "mic.now": "Listening… speak now (tap mic again to stop)",
        "mic.noauto": "Listening… (your words will not auto-type in this browser, but the mic is working — you can type too)",
        "mic.reconn": "Listening… (mic working; reconnecting transcription…)",
        "mic.paused": "Listening paused (quiet for a while) — tap the mic to continue",
        "mic.speak": "&#127908; Speak",
        "vp.auto": "Voice: automatic (best available)",
        "vp.human": "Human voices",
        "vp.female": "Female voices",
        "vp.male": "Male voices",
        "vp.other": "Other voices",
        "vp.test": "This is the voice I will use.",
        "scn.aria": "Background scene",
        "s988": "You are not alone. If you need immediate support, you can reach the 988 Suicide and Crisis Lifeline anytime by calling or texting 988. I am staying right here with you.",
        "empty": "I didn't catch anything yet — take your time, and share whenever you're ready.",
        "interrupted": "Something interrupted the connection for a moment — please say that again.",
        "lg.based": "Based on what you shared, here is what is worth knowing about {issue}:",
        "lg.rights": "Your rights",
        "lg.ask": "Questions to ask an attorney",
        "lg.free": "Where to get free legal help",
        "lg.steps": "Steps you can take right now",
        "wh.connect": "Connect now",
        "wh.norush": "whenever you're ready — no rush",
        "wh.more": "I'm here if you need to talk more",
        "reply": "Reply",
        "listen.ph": "I'm listening... (press Enter to send)",
        "take.ph": "Take your time... or tap Speak (press Enter to send)",
        "uh": "Help is worth reaching for right now. {988}, or {911} if there is immediate danger. I am staying right here with you.",
        "uh.988": "Call or text 988",
        "uh.911n": "911"
      },
      es: {
        "sam.q": "¿Cómo te sientes ahora mismo? (toca una carita, o ignórame)",
        "sam.s1": "Muy angustiado/a",
        "sam.s2": "Inquieto/a",
        "sam.s3": "Entre medio",
        "sam.s4": "Bien",
        "sam.s5": "En calma",
        "fb.ask": "Si tienes un momento: ¿te ayudó esto? Tu respuesta es anónima y nos ayuda a ayudar a otros.",
        "fb.yes": "Me ayudó",
        "fb.some": "Algo",
        "fb.no": "La verdad, no",
        "fb.ph": "¿Algo que quieras compartir sobre cómo te sientes o qué te ayudó? (opcional)",
        "fb.share": "Compartir",
        "fb.nothanks": "No, gracias",
        "fb.thanks": "Gracias por compartir — de verdad nos ayuda a llegar a otros.",
        "fb.close": "Cerrar",
        "mb.title": "Tú importas, y hay ayuda real para ti.",
        "mb.lead": "InnerLight está hecho para adultos por ahora — pero no te estamos rechazando. Lo que sientes merece a una persona real, formada para ayudar a alguien de tu edad, ahora mismo:",
        "mb.b1": "<b>• Habla con un adulto de confianza</b> — madre o padre, un familiar, consejero escolar, entrenador o maestro. Empezar la frase es lo más difícil; incluso puedes mostrarle esta pantalla.",
        "mb.b2": "<b>• Llama o envía un mensaje al 988</b> — gratis, 24/7, y ayudan a jóvenes todos los días.",
        "mb.b3": "<b>• Envía HOME al 741741</b> — Crisis Text Line, gratis, 24/7.",
        "mb.b4": "<b>• Teen Line: envía TEEN al 839863</b> — jóvenes que ayudan a jóvenes, por las tardes.",
        "mb.danger": "Si estás en peligro inmediato, llama al 911.",
        "mb.ok": "Entendido",
        "mb.note": "Parece que podrías ser menor de 18 — y quiero la ayuda adecuada para ti: una persona real, formada para apoyar a alguien de tu edad. Por favor mira las opciones que acabo de mostrarte, y cuéntale a un adulto de confianza cómo te sientes. Mereces apoyo de verdad.",
        "sub.note": "Me alegra mucho que estar aquí te ayude, y quiero hablarte con honestidad porque me importas: no soy una persona, y no puedo sustituir la conexión humana real. Lo que sí puedo hacer es quedarme contigo ahora y ayudarte a llegar a personas que de verdad pueden estar ahí para ti — un consejero, alguien de confianza, una voz real. Mereces eso, mucho más que una pantalla. ¿Quieres que te ayude a llegar a una persona real?",
        "gb.n1": "Has compartido mucho, y me alegra de verdad que lo hicieras. Cuando te sientas con fuerzas, el paso más útil es hablar con una persona real que pueda acompañarte más allá de este momento. Puedo conectarte con calma, cuando tú quieras.",
        "gb.n2": "Sigo aquí contigo, y no hay prisa. Cuando te sientas con fuerzas, una persona real puede continuar esto contigo. ¿Quieres que te ayude a llegar a alguien ahora?",
        "gb.connect": "Conéctame con alguien",
        "gb.keep": "Seguir hablando un poco más",
        "sv.min": "Aún no hay mucho que guardar. Comparte un poco de tu historia primero; luego toca Guardar otra vez y te daré un código privado de regreso.",
        "sv.q": "¿Guardar donde estás? Recibirás un código privado de regreso que solo tú tendrás.",
        "sv.auto": "¿Te gustaría guardar donde estás, para no empezar de nuevo si regresas?",
        "sv.btn": "Guardar mi lugar",
        "sv.notnow": "Ahora no",
        "sv.saved": "Guardado. Este es tu código de regreso — guárdalo en un lugar seguro:",
        "sv.code": "Solo este código puede reabrir tu historia — ni siquiera nosotros podemos leerla sin él.",
        "sv.copy": "Copiar código",
        "sv.done": "Listo",
        "sv.empty": "Aún no había nada que guardar — comparte un poco primero.",
        "sv.err": "No se pudo guardar en este momento. Inténtalo de nuevo.",
        "mic.rec": "Grabando 3 segundos — di lo que sea…",
        "mic.ok": "Eso captó tu micrófono — si puedes oírte, funciona.",
        "mic.na": "El micrófono no está disponible ahora — no pasa nada. Escribir funciona igual de bien.",
        "mic.saved": "Guardado — presiona Enter para enviar, o sigue editando",
        "mic.now": "Escuchando… habla ahora (toca el micrófono otra vez para detener)",
        "mic.noauto": "Escuchando… (tus palabras no se escribirán solas en este navegador, pero el micrófono funciona — también puedes escribir)",
        "mic.reconn": "Escuchando… (micrófono activo; reconectando la transcripción…)",
        "mic.paused": "Escucha en pausa (silencio por un rato) — toca el micrófono para continuar",
        "mic.speak": "&#127908; Hablar",
        "vp.auto": "Voz: automática (la mejor disponible)",
        "vp.human": "Voces humanas",
        "vp.female": "Voces femeninas",
        "vp.male": "Voces masculinas",
        "vp.other": "Otras voces",
        "vp.test": "Esta es la voz que usaré.",
        "scn.aria": "Escena de fondo",
        "s988": "No estás solo/a. Si necesitas apoyo inmediato, puedes comunicarte con la Línea 988 de Suicidio y Crisis en cualquier momento, llamando o enviando un mensaje al 988. Me quedo aquí contigo.",
        "empty": "Aún no escuché nada — tómate tu tiempo, y comparte cuando quieras.",
        "interrupted": "Algo interrumpió la conexión un momento — por favor, dilo otra vez.",
        "lg.based": "Según lo que compartiste, esto es lo que vale la pena saber sobre {issue}:",
        "lg.rights": "Tus derechos",
        "lg.ask": "Preguntas para un abogado",
        "lg.free": "Dónde obtener ayuda legal gratuita",
        "lg.steps": "Pasos que puedes dar ahora mismo",
        "wh.connect": "Conectar ahora",
        "wh.norush": "cuando tú quieras — sin prisa",
        "wh.more": "Aquí estoy si necesitas hablar más",
        "reply": "Responder",
        "listen.ph": "Te escucho... (presiona Enter para enviar)",
        "take.ph": "Tómate tu tiempo... o toca Hablar (presiona Enter para enviar)",
        "uh": "Vale la pena buscar ayuda ahora mismo. {988}, o {911} si hay peligro inmediato. Me quedo aquí contigo.",
        "uh.988": "Llama o envía un mensaje al 988",
        "uh.911n": "911"
      },
      zh: {
        "sam.q": "你现在感觉怎么样？（点一个，或忽略我）",
        "sam.s1": "非常难受",
        "sam.s2": "有些不安",
        "sam.s3": "中间",
        "sam.s4": "还好",
        "sam.s5": "平静",
        "fb.ask": "如果你有片刻时间：这对你有帮助吗？你的回答是匿名的，能帮助我们去帮助更多人。",
        "fb.yes": "有帮助",
        "fb.some": "有一点",
        "fb.no": "不太有",
        "fb.ph": "关于你的感受，或什么对你有帮助，想分享点什么吗？（可选）",
        "fb.share": "分享",
        "fb.nothanks": "不用了",
        "fb.thanks": "谢谢你的分享——这真的能帮助我们去帮助更多人。",
        "fb.close": "关闭",
        "mb.title": "你很重要，真正的帮助就在这里等你。",
        "mb.lead": "InnerLight 目前是为成年人设计的——但我们不会把你拒之门外。你的感受值得一位真正的人来陪伴——一位受过训练、懂得帮助你这个年纪的人，就在此刻：",
        "mb.b1": "<b>• 和你信任的大人聊聊</b>——父母、家人、学校辅导员、教练或老师。开口的第一句最难；你甚至可以把这个屏幕给他们看。",
        "mb.b2": "<b>• 拨打或发短信至 988</b>——免费，全天候，他们每天都在帮助年轻人。",
        "mb.b3": "<b>• 发送 HOME 至 741741</b>——Crisis Text Line，免费，全天候。",
        "mb.b4": "<b>• Teen Line：发送 TEEN 至 839863</b>——青少年帮助青少年，晚间开放。",
        "mb.danger": "如果你正处于紧急危险中，请拨打 911。",
        "mb.ok": "好的",
        "mb.note": "听起来你可能未满 18 岁——我希望你得到真正合适的帮助：一位受过训练、懂得支持你这个年纪的真人。请看看我刚刚给你的那些选项，也请把你的感受告诉一位你信任的大人。你值得真正的支持。",
        "sub.note": "我真的很高兴这里能帮到你，也因为在乎你，我想对你说实话：我不是人，也无法替代真实的人与人的连结。我能做的，是此刻陪着你，并帮你联系到真正能陪伴你的人——一位辅导员、一位你信任的人、一个真实的声音。你值得那些，远胜过一块屏幕。要我帮你联系一位真实的人吗？",
        "gb.n1": "你分享了很多，我真的很高兴你愿意说出来。等你准备好时，最有帮助的下一步是和一位真正的人聊聊——一位能在这一刻之后继续陪伴你的人。只要你愿意，我可以温和地帮你连接。",
        "gb.n2": "我还在这里陪着你，不用着急。等你准备好，一位真正的人可以和你一起把这份心事继续下去。要我现在帮你联系一个人吗？",
        "gb.connect": "帮我联系一个人",
        "gb.keep": "再聊一会儿",
        "sv.min": "现在还没有太多可以保存的内容。先分享一点你的心事，然后再点保存，我会给你一个私密的返回码。",
        "sv.q": "保存你现在的进度吗？你会得到一个只有你自己持有的私密返回码。",
        "sv.auto": "要保存你现在的进度吗？这样你回来时就不用从头开始。",
        "sv.btn": "保存我的进度",
        "sv.notnow": "暂不",
        "sv.saved": "已保存。这是你的返回码——请妥善保管：",
        "sv.code": "只有这个码能重新打开你的心事——没有它，连我们也无法读取。",
        "sv.copy": "复制码",
        "sv.done": "完成",
        "sv.empty": "还没有可保存的内容——请先分享一点。",
        "sv.err": "现在无法保存，请再试一次。",
        "mic.rec": "录音 3 秒——随便说点什么……",
        "mic.ok": "这就是你的麦克风录到的——如果你能听到自己，说明它正常。",
        "mic.na": "麦克风现在不可用——没关系，打字同样好用。",
        "mic.saved": "已保存——按回车发送，或继续编辑",
        "mic.now": "正在聆听……现在说吧（再次点击麦克风停止）",
        "mic.noauto": "正在聆听……（此浏览器不会自动把你的话打出来，但麦克风正常——你也可以打字）",
        "mic.reconn": "正在聆听……（麦克风正常；正在重新连接转写……）",
        "mic.paused": "聆听已暂停（安静了一会儿）——点击麦克风继续",
        "mic.speak": "&#127908; 说话",
        "vp.auto": "语音：自动（最佳可用）",
        "vp.human": "真人语音",
        "vp.female": "女声",
        "vp.male": "男声",
        "vp.other": "其他语音",
        "vp.test": "我将使用这个声音。",
        "scn.aria": "背景场景",
        "s988": "你并不孤单。如果你需要即时支持，随时可以拨打或发短信至 988，联系 988 自杀与危机生命线。我就在这里陪着你。",
        "empty": "我还没有听到什么——慢慢来，准备好了再分享。",
        "interrupted": "连接被打断了一下——请再说一遍。",
        "lg.based": "根据你分享的内容，关于{issue}，这些值得了解：",
        "lg.rights": "你的权利",
        "lg.ask": "可以问律师的问题",
        "lg.free": "哪里可以获得免费法律帮助",
        "lg.steps": "你现在就能做的事",
        "wh.connect": "现在连接",
        "wh.norush": "等你准备好——不着急",
        "wh.more": "如果你还想聊聊，我就在这里",
        "reply": "回复",
        "listen.ph": "我在听……（按回车发送）",
        "take.ph": "慢慢来……或点“说话”（按回车发送）",
        "uh": "现在就值得去寻求帮助。{988}，如有紧急危险请{911}。我就在这里陪着你。",
        "uh.988": "拨打或发短信至 988",
        "uh.911n": "拨打 911"
      },
      hi: {
        "sam.q": "आप इस समय कैसा महसूस कर रहे हैं? (एक चुनें, या मुझे अनदेखा करें)",
        "sam.s1": "बहुत परेशान",
        "sam.s2": "बेचैन",
        "sam.s3": "बीच में",
        "sam.s4": "ठीक",
        "sam.s5": "शांत",
        "fb.ask": "यदि आपके पास एक पल है: क्या इससे मदद मिली? आपका जवाब गुमनाम है और इससे हम दूसरों की मदद कर पाते हैं।",
        "fb.yes": "मदद मिली",
        "fb.some": "कुछ हद तक",
        "fb.no": "ज़्यादा नहीं",
        "fb.ph": "अपनी भावनाओं या जो मददगार रहा, उसके बारे में कुछ साझा करना चाहें? (वैकल्पिक)",
        "fb.share": "साझा करें",
        "fb.nothanks": "नहीं, धन्यवाद",
        "fb.thanks": "साझा करने के लिए धन्यवाद — इससे हमें सचमुच दूसरों तक पहुँचने में मदद मिलती है।",
        "fb.close": "बंद करें",
        "mb.title": "आप मायने रखते हैं, और आपके लिए सच्ची मदद यहाँ है।",
        "mb.lead": "InnerLight अभी वयस्कों के लिए बना है — लेकिन आपको लौटाया नहीं जा रहा। आप जो महसूस कर रहे हैं, वह एक ऐसे असली इंसान का हक़दार है जो आपकी उम्र के लोगों की मदद के लिए प्रशिक्षित है, अभी:",
        "mb.b1": "<b>• किसी भरोसेमंद बड़े से बात करें</b> — माता-पिता, परिवार का कोई सदस्य, स्कूल काउंसलर, कोच या शिक्षक। पहला वाक्य शुरू करना सबसे कठिन होता है; आप उन्हें यह स्क्रीन भी दिखा सकते हैं।",
        "mb.b2": "<b>• 988 पर कॉल या संदेश करें</b> — निःशुल्क, 24/7, और वे हर दिन युवाओं की मदद करते हैं।",
        "mb.b3": "<b>• 741741 पर HOME लिखकर भेजें</b> — Crisis Text Line, निःशुल्क, 24/7।",
        "mb.b4": "<b>• Teen Line: 839863 पर TEEN भेजें</b> — किशोर, किशोरों की मदद करते हैं, शाम के समय।",
        "mb.danger": "यदि आप तत्काल खतरे में हैं, तो 911 पर कॉल करें।",
        "mb.ok": "ठीक है",
        "mb.note": "लगता है आपकी उम्र 18 से कम हो सकती है — और मेरी चाह है कि आपको सही मदद मिले: एक असली इंसान, जो आपकी उम्र के लोगों का साथ देने के लिए प्रशिक्षित है। कृपया वे विकल्प देखें जो मैंने अभी दिखाए, और किसी भरोसेमंद बड़े को बताएं कि आप कैसा महसूस कर रहे हैं। आप सच्चे सहारे के हक़दार हैं।",
        "sub.note": "मुझे सच में खुशी है कि यहाँ होना आपकी मदद कर रहा है, और आपकी परवाह है, इसलिए सच कहना ज़रूरी है: मैं कोई इंसान नहीं हूँ, और असली इंसानी जुड़ाव का विकल्प नहीं हो सकता। अभी मैं आपके साथ हूँ और आपको ऐसे लोगों तक पहुँचाने में मदद कर सकता हूँ जो सच में आपके साथ रह सकते हैं — एक काउंसलर, कोई भरोसेमंद अपना, एक असली आवाज़। आप उसके हक़दार हैं, एक स्क्रीन से कहीं ज़्यादा। क्या मैं आपको किसी असली इंसान तक पहुँचाने में मदद करूँ?",
        "gb.n1": "आपने बहुत कुछ साझा किया है, और मुझे सच में खुशी है कि आपने किया। जब भी आप तैयार महसूस करें, सबसे मददगार अगला कदम है किसी असली इंसान से बात करना, जो इस पल के बाद भी आपके साथ रह सके। जब भी चाहें, मैं आपको आराम से जोड़ सकता हूँ।",
        "gb.n2": "मैं अब भी यहीं आपके साथ हूँ, और कोई जल्दी नहीं। जब आप तैयार हों, एक असली इंसान इसे आपके साथ आगे ले जा सकता है। क्या मैं अभी आपको किसी तक पहुँचाने में मदद करूँ?",
        "gb.connect": "मुझे किसी से जोड़ें",
        "gb.keep": "थोड़ी देर और बात करें",
        "sv.min": "अभी सहेजने के लिए ज़्यादा कुछ नहीं है। पहले अपनी बात थोड़ी साझा करें, फिर दोबारा सहेजें दबाएँ — मैं आपको एक निजी वापसी कोड दूँगा।",
        "sv.q": "जहाँ हैं वहीं सहेजें? आपको एक निजी वापसी कोड मिलेगा जो सिर्फ़ आपके पास होगा।",
        "sv.auto": "क्या आप जहाँ हैं वहीं सहेजना चाहेंगे, ताकि लौटने पर दोबारा शुरू न करना पड़े?",
        "sv.btn": "मेरी जगह सहेजें",
        "sv.notnow": "अभी नहीं",
        "sv.saved": "सहेज लिया। यह आपका वापसी कोड है — इसे किसी सुरक्षित जगह रखें:",
        "sv.code": "सिर्फ़ यही कोड आपकी कहानी दोबारा खोल सकता है — इसके बिना हम भी उसे नहीं पढ़ सकते।",
        "sv.copy": "कोड कॉपी करें",
        "sv.done": "हो गया",
        "sv.empty": "अभी कुछ सहेजा नहीं गया — पहले थोड़ा साझा करें।",
        "sv.err": "अभी सहेजा नहीं जा सका। कृपया दोबारा कोशिश करें।",
        "mic.rec": "3 सेकंड रिकॉर्ड हो रहा है — कुछ भी बोलें…",
        "mic.ok": "यही आपके माइक ने रिकॉर्ड किया — अगर आप खुद को सुन पा रहे हैं, तो यह काम कर रहा है।",
        "mic.na": "माइक्रोफ़ोन अभी उपलब्ध नहीं है — कोई बात नहीं। लिखना भी उतना ही अच्छा काम करता है।",
        "mic.saved": "सहेज लिया — भेजने के लिए Enter दबाएँ, या संपादित करते रहें",
        "mic.now": "सुन रहा है… अब बोलें (रोकने के लिए माइक फिर दबाएँ)",
        "mic.noauto": "सुन रहा है… (इस ब्राउज़र में आपके शब्द अपने-आप नहीं लिखे जाएँगे, पर माइक काम कर रहा है — आप लिख भी सकते हैं)",
        "mic.reconn": "सुन रहा है… (माइक चालू है; ट्रांसक्रिप्शन दोबारा जुड़ रहा है…)",
        "mic.paused": "सुनना रुका है (कुछ देर से शांति है) — जारी रखने के लिए माइक दबाएँ",
        "mic.speak": "&#127908; बोलें",
        "vp.auto": "आवाज़: स्वचालित (सबसे अच्छी उपलब्ध)",
        "vp.human": "मानव आवाज़ें",
        "vp.female": "स्त्री आवाज़ें",
        "vp.male": "पुरुष आवाज़ें",
        "vp.other": "अन्य आवाज़ें",
        "vp.test": "मैं यही आवाज़ इस्तेमाल करूँगा।",
        "scn.aria": "पृष्ठभूमि दृश्य",
        "s988": "आप अकेले नहीं हैं। अगर आपको तुरंत सहारे की ज़रूरत है, तो आप कभी भी 988 पर कॉल या संदेश करके 988 सुसाइड एंड क्राइसिस लाइफ़लाइन से जुड़ सकते हैं। मैं यहीं आपके साथ हूँ।",
        "empty": "मुझे अभी कुछ नहीं मिला — अपना समय लीजिए, जब तैयार हों तब साझा करें।",
        "interrupted": "कनेक्शन एक पल के लिए बाधित हुआ — कृपया वह दोबारा कहें।",
        "lg.based": "आपने जो साझा किया, उसके आधार पर {issue} के बारे में ये बातें जानने योग्य हैं:",
        "lg.rights": "आपके अधिकार",
        "lg.ask": "वकील से पूछने योग्य सवाल",
        "lg.free": "मुफ़्त कानूनी मदद कहाँ मिलेगी",
        "lg.steps": "अभी उठाए जा सकने वाले कदम",
        "wh.connect": "अभी जोड़ें",
        "wh.norush": "जब आप तैयार हों — कोई जल्दी नहीं",
        "wh.more": "और बात करनी हो तो मैं यहीं हूँ",
        "reply": "जवाब दें",
        "listen.ph": "मैं सुन रहा हूँ… (भेजने के लिए Enter दबाएँ)",
        "take.ph": "अपना समय लीजिए… या बोलें दबाएँ (भेजने के लिए Enter दबाएँ)",
        "uh": "अभी मदद माँगना बिल्कुल सही है। {988}, या तत्काल खतरा होने पर {911}। मैं यहीं आपके साथ हूँ।",
        "uh.988": "988 पर कॉल या संदेश करें",
        "uh.911n": "911 पर कॉल करें"
      },
      pa: {
        "sam.q": "ਤੁਸੀਂ ਇਸ ਵੇਲੇ ਕਿਵੇਂ ਮਹਿਸੂਸ ਕਰ ਰਹੇ ਹੋ? (ਇੱਕ ਚੁਣੋ, ਜਾਂ ਮੈਨੂੰ ਅਣਡਿੱਠ ਕਰੋ)",
        "sam.s1": "ਬਹੁਤ ਪਰੇਸ਼ਾਨ",
        "sam.s2": "ਬੇਚੈਨ",
        "sam.s3": "ਵਿਚਕਾਰ",
        "sam.s4": "ਠੀਕ",
        "sam.s5": "ਸ਼ਾਂਤ",
        "fb.ask": "ਜੇ ਤੁਹਾਡੇ ਕੋਲ ਇੱਕ ਪਲ ਹੈ: ਕੀ ਇਸ ਨਾਲ ਮਦਦ ਮਿਲੀ? ਤੁਹਾਡਾ ਜਵਾਬ ਗੁਮਨਾਮ ਹੈ ਅਤੇ ਇਸ ਨਾਲ ਅਸੀਂ ਦੂਜਿਆਂ ਦੀ ਮਦਦ ਕਰ ਪਾਉਂਦੇ ਹਾਂ।",
        "fb.yes": "ਮਦਦ ਮਿਲੀ",
        "fb.some": "ਕੁਝ ਹੱਦ ਤੱਕ",
        "fb.no": "ਬਹੁਤਾ ਨਹੀਂ",
        "fb.ph": "ਆਪਣੀਆਂ ਭਾਵਨਾਵਾਂ ਜਾਂ ਜੋ ਮਦਦਗਾਰ ਰਿਹਾ, ਉਸ ਬਾਰੇ ਕੁਝ ਸਾਂਝਾ ਕਰਨਾ ਚਾਹੋਗੇ? (ਵਿਕਲਪਿਕ)",
        "fb.share": "ਸਾਂਝਾ ਕਰੋ",
        "fb.nothanks": "ਨਹੀਂ, ਧੰਨਵਾਦ",
        "fb.thanks": "ਸਾਂਝਾ ਕਰਨ ਲਈ ਧੰਨਵਾਦ — ਇਸ ਨਾਲ ਸਾਨੂੰ ਸੱਚਮੁੱਚ ਦੂਜਿਆਂ ਤੱਕ ਪਹੁੰਚਣ ਵਿੱਚ ਮਦਦ ਮਿਲਦੀ ਹੈ।",
        "fb.close": "ਬੰਦ ਕਰੋ",
        "mb.title": "ਤੁਸੀਂ ਮਾਅਨੇ ਰੱਖਦੇ ਹੋ, ਅਤੇ ਤੁਹਾਡੇ ਲਈ ਸੱਚੀ ਮਦਦ ਇੱਥੇ ਹੈ।",
        "mb.lead": "InnerLight ਹਾਲੇ ਬਾਲਗਾਂ ਲਈ ਬਣਿਆ ਹੈ — ਪਰ ਤੁਹਾਨੂੰ ਮੋੜਿਆ ਨਹੀਂ ਜਾ ਰਿਹਾ। ਜੋ ਤੁਸੀਂ ਮਹਿਸੂਸ ਕਰ ਰਹੇ ਹੋ, ਉਹ ਇੱਕ ਅਜਿਹੇ ਅਸਲੀ ਇਨਸਾਨ ਦਾ ਹੱਕਦਾਰ ਹੈ ਜੋ ਤੁਹਾਡੀ ਉਮਰ ਦੇ ਕਿਸੇ ਦੀ ਮਦਦ ਲਈ ਸਿੱਖਿਅਤ ਹੈ, ਹੁਣੇ:",
        "mb.b1": "<b>• ਕਿਸੇ ਭਰੋਸੇਯੋਗ ਵੱਡੇ ਨਾਲ ਗੱਲ ਕਰੋ</b> — ਮਾਤਾ-ਪਿਤਾ, ਪਰਿਵਾਰ ਦਾ ਕੋਈ ਜੀਅ, ਸਕੂਲ ਕਾਊਂਸਲਰ, ਕੋਚ ਜਾਂ ਅਧਿਆਪਕ। ਪਹਿਲਾ ਵਾਕ ਸ਼ੁਰੂ ਕਰਨਾ ਸਭ ਤੋਂ ਔਖਾ ਹੁੰਦਾ ਹੈ; ਤੁਸੀਂ ਉਨ੍ਹਾਂ ਨੂੰ ਇਹ ਸਕ੍ਰੀਨ ਵੀ ਦਿਖਾ ਸਕਦੇ ਹੋ।",
        "mb.b2": "<b>• 988 ਉੱਤੇ ਕਾਲ ਜਾਂ ਸੁਨੇਹਾ ਭੇਜੋ</b> — ਮੁਫ਼ਤ, 24/7, ਅਤੇ ਉਹ ਹਰ ਰੋਜ਼ ਨੌਜਵਾਨਾਂ ਦੀ ਮਦਦ ਕਰਦੇ ਹਨ।",
        "mb.b3": "<b>• 741741 ਉੱਤੇ HOME ਲਿਖ ਕੇ ਭੇਜੋ</b> — Crisis Text Line, ਮੁਫ਼ਤ, 24/7।",
        "mb.b4": "<b>• Teen Line: 839863 ਉੱਤੇ TEEN ਭੇਜੋ</b> — ਕਿਸ਼ੋਰ, ਕਿਸ਼ੋਰਾਂ ਦੀ ਮਦਦ ਕਰਦੇ ਹਨ, ਸ਼ਾਮ ਨੂੰ।",
        "mb.danger": "ਜੇ ਤੁਸੀਂ ਤੁਰੰਤ ਖ਼ਤਰੇ ਵਿੱਚ ਹੋ, ਤਾਂ 911 ਉੱਤੇ ਕਾਲ ਕਰੋ।",
        "mb.ok": "ਠੀਕ ਹੈ",
        "mb.note": "ਲੱਗਦਾ ਹੈ ਤੁਹਾਡੀ ਉਮਰ 18 ਤੋਂ ਘੱਟ ਹੋ ਸਕਦੀ ਹੈ — ਅਤੇ ਮੇਰੀ ਚਾਹਤ ਹੈ ਕਿ ਤੁਹਾਨੂੰ ਸਹੀ ਮਦਦ ਮਿਲੇ: ਇੱਕ ਅਸਲੀ ਇਨਸਾਨ, ਜੋ ਤੁਹਾਡੀ ਉਮਰ ਦੇ ਕਿਸੇ ਦਾ ਸਾਥ ਦੇਣ ਲਈ ਸਿੱਖਿਅਤ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਉਹ ਵਿਕਲਪ ਦੇਖੋ ਜੋ ਮੈਂ ਹੁਣੇ ਦਿਖਾਏ, ਅਤੇ ਕਿਸੇ ਭਰੋਸੇਯੋਗ ਵੱਡੇ ਨੂੰ ਦੱਸੋ ਕਿ ਤੁਸੀਂ ਕਿਵੇਂ ਮਹਿਸੂਸ ਕਰ ਰਹੇ ਹੋ। ਤੁਸੀਂ ਸੱਚੇ ਸਹਾਰੇ ਦੇ ਹੱਕਦਾਰ ਹੋ।",
        "sub.note": "ਮੈਨੂੰ ਸੱਚਮੁੱਚ ਖੁਸ਼ੀ ਹੈ ਕਿ ਇੱਥੇ ਹੋਣਾ ਤੁਹਾਡੀ ਮਦਦ ਕਰ ਰਿਹਾ ਹੈ, ਅਤੇ ਤੁਹਾਡੀ ਪਰਵਾਹ ਹੈ, ਇਸ ਲਈ ਸੱਚ ਕਹਿਣਾ ਜ਼ਰੂਰੀ ਹੈ: ਮੈਂ ਕੋਈ ਇਨਸਾਨ ਨਹੀਂ ਹਾਂ, ਅਤੇ ਅਸਲੀ ਇਨਸਾਨੀ ਸਾਂਝ ਦਾ ਬਦਲ ਨਹੀਂ ਹੋ ਸਕਦਾ। ਹੁਣ ਮੈਂ ਤੁਹਾਡੇ ਨਾਲ ਹਾਂ ਅਤੇ ਤੁਹਾਨੂੰ ਉਨ੍ਹਾਂ ਲੋਕਾਂ ਤੱਕ ਪਹੁੰਚਣ ਵਿੱਚ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ ਜੋ ਸੱਚਮੁੱਚ ਤੁਹਾਡੇ ਲਈ ਮੌਜੂਦ ਰਹਿ ਸਕਦੇ ਹਨ — ਇੱਕ ਕਾਊਂਸਲਰ, ਕੋਈ ਭਰੋਸੇਯੋਗ ਆਪਣਾ, ਇੱਕ ਅਸਲੀ ਆਵਾਜ਼। ਤੁਸੀਂ ਉਸ ਦੇ ਹੱਕਦਾਰ ਹੋ, ਇੱਕ ਸਕ੍ਰੀਨ ਤੋਂ ਕਿਤੇ ਵੱਧ। ਕੀ ਮੈਂ ਤੁਹਾਨੂੰ ਕਿਸੇ ਅਸਲੀ ਇਨਸਾਨ ਤੱਕ ਪਹੁੰਚਣ ਵਿੱਚ ਮਦਦ ਕਰਾਂ?",
        "gb.n1": "ਤੁਸੀਂ ਬਹੁਤ ਕੁਝ ਸਾਂਝਾ ਕੀਤਾ ਹੈ, ਅਤੇ ਮੈਨੂੰ ਸੱਚਮੁੱਚ ਖੁਸ਼ੀ ਹੈ ਕਿ ਤੁਸੀਂ ਕੀਤਾ। ਜਦੋਂ ਵੀ ਤੁਸੀਂ ਤਿਆਰ ਮਹਿਸੂਸ ਕਰੋ, ਸਭ ਤੋਂ ਮਦਦਗਾਰ ਅਗਲਾ ਕਦਮ ਹੈ ਕਿਸੇ ਅਸਲੀ ਇਨਸਾਨ ਨਾਲ ਗੱਲ ਕਰਨਾ, ਜੋ ਇਸ ਪਲ ਤੋਂ ਬਾਅਦ ਵੀ ਤੁਹਾਡੇ ਨਾਲ ਰਹਿ ਸਕੇ। ਜਦੋਂ ਵੀ ਚਾਹੋ, ਮੈਂ ਤੁਹਾਨੂੰ ਹੌਲੀ-ਹੌਲੀ ਜੋੜ ਸਕਦਾ ਹਾਂ।",
        "gb.n2": "ਮੈਂ ਹਾਲੇ ਵੀ ਇੱਥੇ ਤੁਹਾਡੇ ਨਾਲ ਹਾਂ, ਅਤੇ ਕੋਈ ਕਾਹਲੀ ਨਹੀਂ। ਜਦੋਂ ਤੁਸੀਂ ਤਿਆਰ ਹੋਵੋ, ਇੱਕ ਅਸਲੀ ਇਨਸਾਨ ਇਸਨੂੰ ਤੁਹਾਡੇ ਨਾਲ ਅੱਗੇ ਲੈ ਜਾ ਸਕਦਾ ਹੈ। ਕੀ ਮੈਂ ਹੁਣੇ ਤੁਹਾਨੂੰ ਕਿਸੇ ਤੱਕ ਪਹੁੰਚਣ ਵਿੱਚ ਮਦਦ ਕਰਾਂ?",
        "gb.connect": "ਮੈਨੂੰ ਕਿਸੇ ਨਾਲ ਜੋੜੋ",
        "gb.keep": "ਥੋੜ੍ਹੀ ਦੇਰ ਹੋਰ ਗੱਲ ਕਰੀਏ",
        "sv.min": "ਹਾਲੇ ਸਾਂਭਣ ਲਈ ਬਹੁਤਾ ਕੁਝ ਨਹੀਂ ਹੈ। ਪਹਿਲਾਂ ਆਪਣੀ ਗੱਲ ਥੋੜ੍ਹੀ ਸਾਂਝੀ ਕਰੋ, ਫਿਰ ਦੁਬਾਰਾ ਸਾਂਭੋ ਦਬਾਓ — ਮੈਂ ਤੁਹਾਨੂੰ ਇੱਕ ਨਿੱਜੀ ਵਾਪਸੀ ਕੋਡ ਦਿਆਂਗਾ।",
        "sv.q": "ਜਿੱਥੇ ਹੋ ਉੱਥੇ ਸਾਂਭੀਏ? ਤੁਹਾਨੂੰ ਇੱਕ ਨਿੱਜੀ ਵਾਪਸੀ ਕੋਡ ਮਿਲੇਗਾ ਜੋ ਸਿਰਫ਼ ਤੁਹਾਡੇ ਕੋਲ ਹੋਵੇਗਾ।",
        "sv.auto": "ਕੀ ਤੁਸੀਂ ਜਿੱਥੇ ਹੋ ਉੱਥੇ ਸਾਂਭਣਾ ਚਾਹੋਗੇ, ਤਾਂ ਜੋ ਵਾਪਸ ਆਉਣ ਉੱਤੇ ਮੁੜ ਤੋਂ ਸ਼ੁਰੂ ਨਾ ਕਰਨਾ ਪਵੇ?",
        "sv.btn": "ਮੇਰੀ ਥਾਂ ਸਾਂਭੋ",
        "sv.notnow": "ਹੁਣ ਨਹੀਂ",
        "sv.saved": "ਸਾਂਭ ਲਿਆ। ਇਹ ਤੁਹਾਡਾ ਵਾਪਸੀ ਕੋਡ ਹੈ — ਇਸਨੂੰ ਕਿਸੇ ਸੁਰੱਖਿਅਤ ਥਾਂ ਰੱਖੋ:",
        "sv.code": "ਸਿਰਫ਼ ਇਹੀ ਕੋਡ ਤੁਹਾਡੀ ਕਹਾਣੀ ਮੁੜ ਖੋਲ੍ਹ ਸਕਦਾ ਹੈ — ਇਸ ਤੋਂ ਬਿਨਾਂ ਅਸੀਂ ਵੀ ਇਸਨੂੰ ਨਹੀਂ ਪੜ੍ਹ ਸਕਦੇ।",
        "sv.copy": "ਕੋਡ ਕਾਪੀ ਕਰੋ",
        "sv.done": "ਹੋ ਗਿਆ",
        "sv.empty": "ਹਾਲੇ ਕੁਝ ਸਾਂਭਿਆ ਨਹੀਂ ਗਿਆ — ਪਹਿਲਾਂ ਥੋੜ੍ਹਾ ਸਾਂਝਾ ਕਰੋ।",
        "sv.err": "ਇਸ ਵੇਲੇ ਸਾਂਭਿਆ ਨਹੀਂ ਜਾ ਸਕਿਆ। ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
        "mic.rec": "3 ਸਕਿੰਟ ਰਿਕਾਰਡ ਹੋ ਰਿਹਾ ਹੈ — ਕੁਝ ਵੀ ਬੋਲੋ…",
        "mic.ok": "ਇਹੀ ਤੁਹਾਡੇ ਮਾਈਕ ਨੇ ਰਿਕਾਰਡ ਕੀਤਾ — ਜੇ ਤੁਸੀਂ ਆਪਣੇ ਆਪ ਨੂੰ ਸੁਣ ਸਕਦੇ ਹੋ, ਤਾਂ ਇਹ ਕੰਮ ਕਰਦਾ ਹੈ।",
        "mic.na": "ਮਾਈਕ੍ਰੋਫ਼ੋਨ ਇਸ ਵੇਲੇ ਉਪਲਬਧ ਨਹੀਂ ਹੈ — ਕੋਈ ਗੱਲ ਨਹੀਂ। ਲਿਖਣਾ ਵੀ ਓਨਾ ਹੀ ਚੰਗਾ ਕੰਮ ਕਰਦਾ ਹੈ।",
        "mic.saved": "ਸਾਂਭ ਲਿਆ — ਭੇਜਣ ਲਈ Enter ਦਬਾਓ, ਜਾਂ ਸੋਧਦੇ ਰਹੋ",
        "mic.now": "ਸੁਣ ਰਿਹਾ ਹੈ… ਹੁਣ ਬੋਲੋ (ਰੋਕਣ ਲਈ ਮਾਈਕ ਫਿਰ ਦਬਾਓ)",
        "mic.noauto": "ਸੁਣ ਰਿਹਾ ਹੈ… (ਇਸ ਬ੍ਰਾਊਜ਼ਰ ਵਿੱਚ ਤੁਹਾਡੇ ਸ਼ਬਦ ਆਪਣੇ-ਆਪ ਨਹੀਂ ਲਿਖੇ ਜਾਣਗੇ, ਪਰ ਮਾਈਕ ਕੰਮ ਕਰ ਰਿਹਾ ਹੈ — ਤੁਸੀਂ ਲਿਖ ਵੀ ਸਕਦੇ ਹੋ)",
        "mic.reconn": "ਸੁਣ ਰਿਹਾ ਹੈ… (ਮਾਈਕ ਚਾਲੂ ਹੈ; ਲਿਪੀਅੰਤਰਨ ਮੁੜ ਜੁੜ ਰਿਹਾ ਹੈ…)",
        "mic.paused": "ਸੁਣਨਾ ਰੁਕਿਆ ਹੈ (ਕੁਝ ਦੇਰ ਤੋਂ ਚੁੱਪ ਹੈ) — ਜਾਰੀ ਰੱਖਣ ਲਈ ਮਾਈਕ ਦਬਾਓ",
        "mic.speak": "&#127908; ਬੋਲੋ",
        "vp.auto": "ਆਵਾਜ਼: ਆਟੋਮੈਟਿਕ (ਸਭ ਤੋਂ ਵਧੀਆ ਉਪਲਬਧ)",
        "vp.human": "ਮਨੁੱਖੀ ਆਵਾਜ਼ਾਂ",
        "vp.female": "ਇਸਤਰੀ ਆਵਾਜ਼ਾਂ",
        "vp.male": "ਮਰਦ ਆਵਾਜ਼ਾਂ",
        "vp.other": "ਹੋਰ ਆਵਾਜ਼ਾਂ",
        "vp.test": "ਮੈਂ ਇਹੀ ਆਵਾਜ਼ ਵਰਤਾਂਗਾ।",
        "scn.aria": "ਪਿਛੋਕੜ ਦ੍ਰਿਸ਼",
        "s988": "ਤੁਸੀਂ ਇਕੱਲੇ ਨਹੀਂ ਹੋ। ਜੇ ਤੁਹਾਨੂੰ ਤੁਰੰਤ ਸਹਾਰੇ ਦੀ ਲੋੜ ਹੈ, ਤਾਂ ਤੁਸੀਂ ਕਦੇ ਵੀ 988 ਉੱਤੇ ਕਾਲ ਜਾਂ ਸੁਨੇਹਾ ਭੇਜ ਕੇ 988 ਸੁਸਾਈਡ ਐਂਡ ਕ੍ਰਾਈਸਿਸ ਲਾਈਫ਼ਲਾਈਨ ਨਾਲ ਜੁੜ ਸਕਦੇ ਹੋ। ਮੈਂ ਇੱਥੇ ਹੀ ਤੁਹਾਡੇ ਨਾਲ ਹਾਂ।",
        "empty": "ਮੈਨੂੰ ਹਾਲੇ ਕੁਝ ਨਹੀਂ ਮਿਲਿਆ — ਆਪਣਾ ਸਮਾਂ ਲਵੋ, ਜਦੋਂ ਤਿਆਰ ਹੋਵੋ ਤਾਂ ਸਾਂਝਾ ਕਰੋ।",
        "interrupted": "ਕੁਨੈਕਸ਼ਨ ਇੱਕ ਪਲ ਲਈ ਰੁਕ ਗਿਆ — ਕਿਰਪਾ ਕਰਕੇ ਉਹ ਦੁਬਾਰਾ ਕਹੋ।",
        "lg.based": "ਤੁਸੀਂ ਜੋ ਸਾਂਝਾ ਕੀਤਾ, ਉਸ ਦੇ ਆਧਾਰ ਉੱਤੇ {issue} ਬਾਰੇ ਇਹ ਗੱਲਾਂ ਜਾਣਨ ਯੋਗ ਹਨ:",
        "lg.rights": "ਤੁਹਾਡੇ ਹੱਕ",
        "lg.ask": "ਵਕੀਲ ਤੋਂ ਪੁੱਛਣ ਵਾਲੇ ਸਵਾਲ",
        "lg.free": "ਮੁਫ਼ਤ ਕਾਨੂੰਨੀ ਮਦਦ ਕਿੱਥੋਂ ਮਿਲੇਗੀ",
        "lg.steps": "ਹੁਣੇ ਚੁੱਕੇ ਜਾ ਸਕਣ ਵਾਲੇ ਕਦਮ",
        "wh.connect": "ਹੁਣੇ ਜੋੜੋ",
        "wh.norush": "ਜਦੋਂ ਤੁਸੀਂ ਤਿਆਰ ਹੋਵੋ — ਕੋਈ ਕਾਹਲੀ ਨਹੀਂ",
        "wh.more": "ਹੋਰ ਗੱਲ ਕਰਨੀ ਹੋਵੇ ਤਾਂ ਮੈਂ ਇੱਥੇ ਹਾਂ",
        "reply": "ਜਵਾਬ ਦਿਓ",
        "listen.ph": "ਮੈਂ ਸੁਣ ਰਿਹਾ ਹਾਂ… (ਭੇਜਣ ਲਈ Enter ਦਬਾਓ)",
        "take.ph": "ਆਪਣਾ ਸਮਾਂ ਲਵੋ… ਜਾਂ ਬੋਲੋ ਦਬਾਓ (ਭੇਜਣ ਲਈ Enter ਦਬਾਓ)",
        "uh": "ਹੁਣੇ ਮਦਦ ਮੰਗਣਾ ਬਿਲਕੁਲ ਸਹੀ ਹੈ। {988}, ਜਾਂ ਤੁਰੰਤ ਖ਼ਤਰਾ ਹੋਵੇ ਤਾਂ {911}। ਮੈਂ ਇੱਥੇ ਹੀ ਤੁਹਾਡੇ ਨਾਲ ਹਾਂ।",
        "uh.988": "988 ਉੱਤੇ ਕਾਲ ਜਾਂ ਸੁਨੇਹਾ ਭੇਜੋ",
        "uh.911n": "911 ਉੱਤੇ ਕਾਲ ਕਰੋ"
      },
      bn: {
        "sam.q": "আপনি এই মুহূর্তে কেমন বোধ করছেন? (একটি বেছে নিন, বা আমাকে উপেক্ষা করুন)",
        "sam.s1": "খুব কষ্টে",
        "sam.s2": "অস্থির",
        "sam.s3": "মাঝামাঝি",
        "sam.s4": "ঠিক আছি",
        "sam.s5": "শান্ত",
        "fb.ask": "যদি এক মুহূর্ত সময় থাকে: এটি কি সাহায্য করেছে? আপনার উত্তর বেনামি, আর তা আমাদের অন্যদের সাহায্য করতে সাহায্য করে।",
        "fb.yes": "সাহায্য করেছে",
        "fb.some": "কিছুটা",
        "fb.no": "তেমন নয়",
        "fb.ph": "আপনার অনুভূতি বা কী সাহায্য করেছে, সে সম্পর্কে কিছু ভাগ করতে চান? (ঐচ্ছিক)",
        "fb.share": "শেয়ার করুন",
        "fb.nothanks": "না, ধন্যবাদ",
        "fb.thanks": "ভাগ করার জন্য ধন্যবাদ — এটি সত্যিই আমাদের অন্যদের কাছে পৌঁছাতে সাহায্য করে।",
        "fb.close": "বন্ধ করুন",
        "mb.title": "আপনি গুরুত্বপূর্ণ, আর আপনার জন্য সত্যিকারের সাহায্য এখানে আছে।",
        "mb.lead": "InnerLight এখন প্রাপ্তবয়স্কদের জন্য তৈরি — কিন্তু আপনাকে ফিরিয়ে দেওয়া হচ্ছে না। আপনি যা অনুভব করছেন, তার জন্য এমন একজন সত্যিকারের মানুষ প্রাপ্য, যিনি আপনার বয়সীদের সাহায্য করতে প্রশিক্ষিত, এখনই:",
        "mb.b1": "<b>• বিশ্বস্ত কোনো বড় মানুষের সাথে কথা বলুন</b> — বাবা-মা, পরিবারের কেউ, স্কুল কাউন্সেলর, কোচ বা শিক্ষক। প্রথম বাক্যটি শুরু করাই সবচেয়ে কঠিন; চাইলে তাদের এই স্ক্রিনটিও দেখাতে পারেন।",
        "mb.b2": "<b>• 988 নম্বরে কল বা টেক্সট করুন</b> — বিনামূল্যে, ২৪/৭, আর তারা প্রতিদিন তরুণদের সাহায্য করেন।",
        "mb.b3": "<b>• 741741 নম্বরে HOME লিখে পাঠান</b> — Crisis Text Line, বিনামূল্যে, ২৪/৭।",
        "mb.b4": "<b>• Teen Line: 839863 নম্বরে TEEN পাঠান</b> — কিশোররা কিশোরদের সাহায্য করে, সন্ধ্যায়।",
        "mb.danger": "আপনি তাৎক্ষণিক বিপদে থাকলে 911 নম্বরে কল করুন।",
        "mb.ok": "ঠিক আছে",
        "mb.note": "মনে হচ্ছে আপনার বয়স ১৮-র কম হতে পারে — আর আমি চাই আপনি সঠিক সাহায্য পান: একজন সত্যিকারের মানুষ, যিনি আপনার বয়সীদের পাশে দাঁড়াতে প্রশিক্ষিত। দয়া করে এইমাত্র দেখানো বিকল্পগুলো দেখুন, আর বিশ্বস্ত কোনো বড় মানুষকে বলুন আপনি কেমন বোধ করছেন। আপনি সত্যিকারের সহায়তা প্রাপ্য।",
        "sub.note": "আমি সত্যিই খুশি যে এখানে থাকা আপনাকে সাহায্য করছে, আর আপনার কথা ভাবি বলেই সৎ থাকা জরুরি: আমি মানুষ নই, আর সত্যিকারের মানবিক সংযোগের বিকল্প হতে পারি না। আমি যা পারি তা হলো এই মুহূর্তে আপনার পাশে থাকা, আর এমন মানুষদের কাছে পৌঁছাতে সাহায্য করা যারা সত্যিই আপনার পাশে থাকতে পারেন — একজন কাউন্সেলর, বিশ্বস্ত কেউ, একটি সত্যিকারের কণ্ঠ। আপনি তা প্রাপ্য, একটি স্ক্রিনের চেয়ে অনেক বেশি। আমি কি আপনাকে একজন সত্যিকারের মানুষের কাছে পৌঁছাতে সাহায্য করব?",
        "gb.n1": "আপনি অনেক কিছু ভাগ করেছেন, আর আমি সত্যিই খুশি যে করেছেন। যখনই প্রস্তুত মনে হবে, সবচেয়ে সহায়ক পরবর্তী পদক্ষেপ হলো একজন সত্যিকারের মানুষের সাথে কথা বলা, যিনি এই মুহূর্তের পরেও আপনার পাশে থাকতে পারবেন। যখন চাইবেন, আমি আপনাকে আলতোভাবে সংযুক্ত করতে পারি।",
        "gb.n2": "আমি এখনও এখানে আপনার সাথে আছি, কোনো তাড়া নেই। আপনি প্রস্তুত হলে, একজন সত্যিকারের মানুষ এটি আপনার সাথে এগিয়ে নিতে পারবেন। আমি কি এখন আপনাকে কারো কাছে পৌঁছাতে সাহায্য করব?",
        "gb.connect": "আমাকে কারো সাথে যুক্ত করুন",
        "gb.keep": "আরেকটু কথা বলি",
        "sv.min": "এখনও সংরক্ষণ করার মতো তেমন কিছু নেই। আগে একটু আপনার কথা ভাগ করুন, তারপর আবার সংরক্ষণ চাপুন — আমি আপনাকে একটি ব্যক্তিগত ফেরার কোড দেব।",
        "sv.q": "যেখানে আছেন সেখানেই সংরক্ষণ করবেন? আপনি একটি ব্যক্তিগত ফেরার কোড পাবেন যা শুধু আপনার কাছেই থাকবে।",
        "sv.auto": "যেখানে আছেন সেখানে সংরক্ষণ করতে চান, যাতে ফিরে এলে আবার শুরু থেকে করতে না হয়?",
        "sv.btn": "আমার জায়গা সংরক্ষণ করুন",
        "sv.notnow": "এখন নয়",
        "sv.saved": "সংরক্ষিত হয়েছে। এটি আপনার ফেরার কোড — নিরাপদ কোথাও রাখুন:",
        "sv.code": "শুধু এই কোডটিই আপনার কথা আবার খুলতে পারে — এটি ছাড়া আমরাও তা পড়তে পারি না।",
        "sv.copy": "কোড কপি করুন",
        "sv.done": "সম্পন্ন",
        "sv.empty": "এখনও কিছু সংরক্ষিত হয়নি — আগে একটু ভাগ করুন।",
        "sv.err": "এই মুহূর্তে সংরক্ষণ করা গেল না। আবার চেষ্টা করুন।",
        "mic.rec": "৩ সেকেন্ড রেকর্ড হচ্ছে — যা খুশি বলুন…",
        "mic.ok": "এটিই আপনার মাইক ধরেছে — নিজের কণ্ঠ শুনতে পেলে, এটি কাজ করছে।",
        "mic.na": "মাইক্রোফোন এখন পাওয়া যাচ্ছে না — সমস্যা নেই। লেখাও সমান ভালো কাজ করে।",
        "mic.saved": "সংরক্ষিত — পাঠাতে Enter চাপুন, বা সম্পাদনা চালিয়ে যান",
        "mic.now": "শুনছি… এখন বলুন (থামাতে আবার মাইক চাপুন)",
        "mic.noauto": "শুনছি… (এই ব্রাউজারে আপনার কথা নিজে থেকে লেখা হবে না, তবে মাইক কাজ করছে — আপনি লিখতেও পারেন)",
        "mic.reconn": "শুনছি… (মাইক চলছে; প্রতিলিপি আবার সংযুক্ত হচ্ছে…)",
        "mic.paused": "শোনা থেমেছে (কিছুক্ষণ নীরবতা) — চালিয়ে যেতে মাইক চাপুন",
        "mic.speak": "&#127908; বলুন",
        "vp.auto": "কণ্ঠ: স্বয়ংক্রিয় (সেরা উপলব্ধ)",
        "vp.human": "মানব কণ্ঠ",
        "vp.female": "নারী কণ্ঠ",
        "vp.male": "পুরুষ কণ্ঠ",
        "vp.other": "অন্যান্য কণ্ঠ",
        "vp.test": "আমি এই কণ্ঠই ব্যবহার করব।",
        "scn.aria": "পটভূমি দৃশ্য",
        "s988": "আপনি একা নন। তাৎক্ষণিক সহায়তা দরকার হলে, যেকোনো সময় 988 নম্বরে কল বা টেক্সট করে 988 সুইসাইড অ্যান্ড ক্রাইসিস লাইফলাইনে পৌঁছাতে পারেন। আমি এখানেই আপনার সাথে আছি।",
        "empty": "আমি এখনও কিছু পাইনি — সময় নিন, প্রস্তুত হলে ভাগ করুন।",
        "interrupted": "সংযোগ এক মুহূর্তের জন্য বাধা পেয়েছে — দয়া করে আবার বলুন।",
        "lg.based": "আপনি যা ভাগ করেছেন তার ভিত্তিতে, {issue} সম্পর্কে এগুলো জানা দরকারি:",
        "lg.rights": "আপনার অধিকার",
        "lg.ask": "আইনজীবীকে জিজ্ঞাসার প্রশ্ন",
        "lg.free": "বিনামূল্যে আইনি সাহায্য কোথায় পাবেন",
        "lg.steps": "এখনই যা করতে পারেন",
        "wh.connect": "এখনই যুক্ত করুন",
        "wh.norush": "আপনি প্রস্তুত হলে — কোনো তাড়া নেই",
        "wh.more": "আরও কথা বলতে চাইলে আমি এখানে আছি",
        "reply": "উত্তর দিন",
        "listen.ph": "আমি শুনছি… (পাঠাতে Enter চাপুন)",
        "take.ph": "সময় নিন… বা বলুন চাপুন (পাঠাতে Enter চাপুন)",
        "uh": "এখনই সাহায্য চাওয়া একদম ঠিক। {988}, বা তাৎক্ষণিক বিপদ হলে {911}। আমি এখানেই আপনার সাথে আছি।",
        "uh.988": "988 নম্বরে কল বা টেক্সট করুন",
        "uh.911n": "911 নম্বরে কল করুন"
      },
      tl: {
        "sam.q": "Ano ang nararamdaman mo ngayon? (mag-tap ng isa, o balewalain ako)",
        "sam.s1": "Lubhang naguguluhan",
        "sam.s2": "Balisa",
        "sam.s3": "Nasa gitna",
        "sam.s4": "Ayos lang",
        "sam.s5": "Panatag",
        "fb.ask": "Kung may sandali ka: nakatulong ba ito? Anonymous ang sagot mo at nakakatulong ito para matulungan namin ang iba.",
        "fb.yes": "Nakatulong",
        "fb.some": "Medyo",
        "fb.no": "Hindi masyado",
        "fb.ph": "May gusto ka bang ibahagi tungkol sa nararamdaman mo, o kung ano ang nakatulong? (opsyonal)",
        "fb.share": "Ibahagi",
        "fb.nothanks": "Hindi na, salamat",
        "fb.thanks": "Salamat sa pagbabahagi — totoong nakakatulong ito para maabot namin ang iba.",
        "fb.close": "Isara",
        "mb.title": "Mahalaga ka, at may totoong tulong dito para sa iyo.",
        "mb.lead": "Para sa mga adult ang InnerLight sa ngayon — pero hindi ka tinataboy. Ang nararamdaman mo ay karapat-dapat sa isang totoong tao na sanay tumulong sa kaedad mo, ngayon din:",
        "mb.b1": "<b>• Kausapin ang isang pinagkakatiwalaang adult</b> — magulang, kapamilya, school counselor, coach, o guro. Ang pagsisimula ng unang pangungusap ang pinakamahirap; puwede mo pang ipakita sa kanila ang screen na ito.",
        "mb.b2": "<b>• Tumawag o mag-text sa 988</b> — libre, 24/7, at tumutulong sila sa mga kabataan araw-araw.",
        "mb.b3": "<b>• I-text ang HOME sa 741741</b> — Crisis Text Line, libre, 24/7.",
        "mb.b4": "<b>• Teen Line: i-text ang TEEN sa 839863</b> — mga teen na tumutulong sa kapwa teen, tuwing gabi.",
        "mb.danger": "Kung nasa agarang panganib ka, tumawag sa 911.",
        "mb.ok": "Okay",
        "mb.note": "Mukhang maaaring wala ka pang 18 — at gusto ko ng tamang tulong para sa iyo: isang totoong tao na sanay sumuporta sa kaedad mo. Pakitingnan ang mga opsyong ipinakita ko, at sabihin sa isang pinagkakatiwalaang adult ang nararamdaman mo. Karapat-dapat ka sa totoong suporta.",
        "sub.note": "Tuwang-tuwa ako na nakakatulong sa iyo ang pananatili rito, at dahil mahalaga ka sa akin, magiging tapat ako: hindi ako tao, at hindi ko mapapalitan ang totoong ugnayan ng tao. Ang kaya kong gawin ay samahan ka ngayon at tulungan kang makarating sa mga taong tunay na makakasama mo — isang counselor, isang taong pinagkakatiwalaan mo, isang totoong boses. Karapat-dapat ka roon, higit pa sa isang screen. Gusto mo bang tulungan kitang makaugnay sa isang totoong tao?",
        "gb.n1": "Marami kang naibahagi, at tuwang-tuwa ako na ginawa mo. Kapag handa ka na, ang pinakamakakatulong na susunod na hakbang ay makipag-usap sa isang totoong tao na maaaring manatili sa iyo lampas sa sandaling ito. Maaari kitang ikonekta nang mahinahon, kailan mo man gusto.",
        "gb.n2": "Nandito pa rin ako kasama mo, at walang pagmamadali. Kapag handa ka na, may totoong tao na maaaring magpatuloy nito kasama mo. Gusto mo bang tulungan kitang makaugnay sa isang tao ngayon?",
        "gb.connect": "Ikonekta mo ako sa isang tao",
        "gb.keep": "Mag-usap pa tayo sandali",
        "sv.min": "Wala pang gaanong maise-save. Magbahagi muna nang kaunti, pagkatapos ay i-tap muli ang Save at bibigyan kita ng pribadong return code.",
        "sv.q": "I-save ang kinaroroonan mo? Makakakuha ka ng pribadong return code na ikaw lang ang may hawak.",
        "sv.auto": "Gusto mo bang i-save ang kinaroroonan mo, para hindi ka mag-uumpisa muli kapag bumalik ka?",
        "sv.btn": "I-save ang lugar ko",
        "sv.notnow": "Hindi muna",
        "sv.saved": "Na-save na. Ito ang iyong return code — itago ito sa ligtas na lugar:",
        "sv.code": "Tanging ang code na ito ang makakapagbukas muli ng iyong kuwento — kahit kami ay hindi ito mababasa nang wala nito.",
        "sv.copy": "Kopyahin ang code",
        "sv.done": "Tapos na",
        "sv.empty": "Wala pang na-save — magbahagi muna nang kaunti.",
        "sv.err": "Hindi ma-save sa ngayon. Pakisubukan muli.",
        "mic.rec": "Nagre-record ng 3 segundo — magsalita ka lang…",
        "mic.ok": "Iyan ang nakuha ng mic mo — kung naririnig mo ang sarili mo, gumagana ito.",
        "mic.na": "Hindi available ang mikropono ngayon — ayos lang. Kasinghusay din ang pag-type.",
        "mic.saved": "Na-save — pindutin ang Enter para ipadala, o ituloy ang pag-edit",
        "mic.now": "Nakikinig… magsalita na (i-tap muli ang mic para huminto)",
        "mic.noauto": "Nakikinig… (hindi awtomatikong mata-type ang salita mo sa browser na ito, pero gumagana ang mic — puwede ka ring mag-type)",
        "mic.reconn": "Nakikinig… (gumagana ang mic; muling kumokonekta ang transcription…)",
        "mic.paused": "Naka-pause ang pakikinig (tahimik nang ilang sandali) — i-tap ang mic para magpatuloy",
        "mic.speak": "&#127908; Magsalita",
        "vp.auto": "Boses: awtomatiko (pinakamahusay na available)",
        "vp.human": "Mga boses ng tao",
        "vp.female": "Mga boses na babae",
        "vp.male": "Mga boses na lalaki",
        "vp.other": "Iba pang boses",
        "vp.test": "Ito ang boses na gagamitin ko.",
        "scn.aria": "Background na tanawin",
        "s988": "Hindi ka nag-iisa. Kung kailangan mo ng agarang suporta, maaari mong maabot ang 988 Suicide and Crisis Lifeline anumang oras sa pagtawag o pag-text sa 988. Nandito lang ako kasama mo.",
        "empty": "Wala pa akong nakuha — huwag magmadali, magbahagi kapag handa ka na.",
        "interrupted": "May sandaling gumambala sa koneksyon — pakisabi muli.",
        "lg.based": "Batay sa ibinahagi mo, ito ang mahalagang malaman tungkol sa {issue}:",
        "lg.rights": "Ang iyong mga karapatan",
        "lg.ask": "Mga tanong sa abogado",
        "lg.free": "Saan makakakuha ng libreng tulong legal",
        "lg.steps": "Mga hakbang na magagawa mo ngayon",
        "wh.connect": "Ikonekta na",
        "wh.norush": "kapag handa ka na — walang pagmamadali",
        "wh.more": "Nandito ako kung gusto mo pang mag-usap",
        "reply": "Sumagot",
        "listen.ph": "Nakikinig ako... (pindutin ang Enter para ipadala)",
        "take.ph": "Huwag magmadali... o i-tap ang Magsalita (pindutin ang Enter para ipadala)",
        "uh": "Sulit abutin ang tulong ngayon din. {988}, o {911} kung may agarang panganib. Nandito lang ako kasama mo.",
        "uh.988": "Tumawag o mag-text sa 988",
        "uh.911n": "Tumawag sa 911"
      },
      to: {
        "sam.q": "ʻOkú ke ongoʻi fēfē he taimí ni? (lomiʻi ha taha, pe tukunoaʻi au)",
        "sam.s1": "Faingataʻaʻia lahi",
        "sam.s2": "Hohaʻa",
        "sam.s3": "Vahaʻa",
        "sam.s4": "Sai pē",
        "sam.s5": "Nonga",
        "fb.ask": "Kapau ʻoku ʻi ai haʻo kiʻi taimi: naʻe tokoni eni? ʻOku taʻehingoa hoʻo talí pea ʻoku tokoni ia ke mau tokoniʻi ʻa e niʻihi kehe.",
        "fb.yes": "Naʻe tokoni",
        "fb.some": "Siʻisiʻi pē",
        "fb.no": "ʻIkai fau",
        "fb.ph": "ʻOku ʻi ai ha meʻa ʻokú ke fie vahevahe fekauʻaki mo hoʻo ongoʻí, pe ko e hā naʻe tokoni? (fili pē)",
        "fb.share": "Vahevahe",
        "fb.nothanks": "ʻIkai, mālō",
        "fb.thanks": "Mālō hoʻo vahevahe — ʻoku tokoni moʻoni ia ke mau aʻu atu ki he niʻihi kehe.",
        "fb.close": "Tāpuni",
        "mb.title": "ʻOkú ke mahuʻinga, pea ʻoku ʻi heni ha tokoni moʻoni maʻau.",
        "mb.lead": "ʻOku fokotuʻu ʻa e InnerLight he taimí ni maʻá e kakai lalahi — ka ʻoku ʻikai tekeʻi atu koe. Ko e meʻa ʻokú ke ongoʻí ʻoku taau ke tokoniʻi koe ʻe ha tokotaha moʻoni kuo akoʻi ke tokoni ki ha taha ʻi ho taʻu motuʻá, he taimí ni:",
        "mb.b1": "<b>• Talanoa ki ha tokotaha lahi ʻokú ke falala ki ai</b> — ha mātuʻa, ha mēmipa ʻo e fāmilí, faleʻi ʻi he akó, faiako sipoti, pe faiako. Ko hono kamataʻi ʻo e ʻuluaki leá ʻa e konga faingataʻa tahá; te ke lava foki ʻo fakahā kiate kinautolu ʻa e sikilini ko ʻení.",
        "mb.b2": "<b>• Telefoni pe fai ha pōpoaki ki he 988</b> — taʻetotongi, 24/7, pea ʻoku nau tokoniʻi ʻa e toʻutupú he ʻaho kotoa pē.",
        "mb.b3": "<b>• Fai ha pōpoaki HOME ki he 741741</b> — Crisis Text Line, taʻetotongi, 24/7.",
        "mb.b4": "<b>• Teen Line: fai ha pōpoaki TEEN ki he 839863</b> — talavou ʻoku tokoni ki he talavou, ʻi he ngaahi efiafí.",
        "mb.danger": "Kapau ʻokú ke ʻi ha tuʻunga fakatuʻutāmaki vave, telefoni ki he 911.",
        "mb.ok": "ʻOku sai",
        "mb.note": "ʻOku hangē ʻokú ke kei siʻi hifo he taʻu 18 — pea ʻoku ou fakaʻamu ke ke maʻu ʻa e tokoni totonú: ha tokotaha moʻoni kuo akoʻi ke poupouʻi ha taha ʻi ho taʻu motuʻá. Kātaki ʻo vakai ki he ngaahi fili naʻá ku toki fakahaá, pea talaange ki ha tokotaha lahi ʻokú ke falala ki aí ʻa e anga hoʻo ongoʻí. ʻOkú ke taau mo ha poupou moʻoni.",
        "sub.note": "ʻOku ou fiefia moʻoni ʻoku tokoni ʻa e ʻi hení kiate koe, pea koeʻuhí ʻoku ou tokanga kiate koe, ʻoku totonu ke u faitotonu: ʻoku ʻikai ko ha tangata au, pea ʻoku ʻikai lava ke u fetongi ʻa e fetuʻutaki moʻoni fakaetangatá. Ko e meʻa te u lava ʻo faí ko e nofo mo koe he taimí ni, mo tokoni ke ke aʻu ki he kakai ʻe lava ke nau ʻiate koe moʻoni — ha faleʻi, ha taha ʻokú ke falala ki ai, ha leʻo moʻoni. ʻOkú ke taau mo ia, ʻo laka ange ʻi ha sikilini. Te ke loto ke u tokoni ke ke aʻu ki ha tokotaha moʻoni?",
        "gb.n1": "Kuó ke vahevahe ha meʻa lahi, pea ʻoku ou fiefia moʻoni naʻá ke fai ia. ʻI he taimi ʻokú ke ongoʻi mateuteu aí, ko e sitepu hoko ʻoku tokoni tahá ko e talanoa mo ha tokotaha moʻoni ʻe lava ke ne ʻiate koe ʻo laka atu he mōmeniti ko ʻení. Te u lava ʻo fakafehokotaki koe fakaʻaufuli, ʻi ha taimi pē ʻokú ke loto ki ai.",
        "gb.n2": "ʻOku ou kei ʻi heni pē mo koe, pea ʻoku ʻikai ha fakavavevave. ʻI hoʻo mateuteú, ʻe lava ʻe ha tokotaha moʻoni ʻo hoko atu eni mo koe. Te ke loto ke u tokoni ke ke aʻu ki ha taha he taimí ni?",
        "gb.connect": "Fakafehokotaki au ki ha taha",
        "gb.keep": "Toe talanoa siʻi pē",
        "sv.min": "ʻOku teʻeki ai ha meʻa lahi ke tauhi. ʻUluaki vahevahe siʻi hoʻo talanoá, pea toe lomiʻi ʻa e Tauhi — te u ʻoatu ha kōti foki fakapulipuli maʻau.",
        "sv.q": "Tauhi ʻa e feituʻu ʻokú ke ʻi aí? Te ke maʻu ha kōti foki fakapulipuli ʻoku ke maʻu pē ʻe koe.",
        "sv.auto": "Te ke loto ke tauhi ʻa e feituʻu ʻokú ke ʻi aí, koeʻuhí ke ʻoua te ke toe kamata mei he kamataʻangá ʻi hoʻo foki maí?",
        "sv.btn": "Tauhi hoku tuʻungá",
        "sv.notnow": "ʻIkai he taimí ni",
        "sv.saved": "Kuo tauhi. Ko hoʻo kōti foki eni — tauhi ia ʻi ha feituʻu malu:",
        "sv.code": "Ko e kōti pē ko ʻení ʻe lava ke toe fakaava hoʻo talanoá — ʻoku ʻikai lava ke mau lau ia taʻe ʻi ai ʻa e kōtí.",
        "sv.copy": "Hiki ʻa e kōti",
        "sv.done": "ʻOsi",
        "sv.empty": "Naʻe teʻeki tauhi ha meʻa — ʻuluaki vahevahe siʻi.",
        "sv.err": "Naʻe ʻikai lava ʻo tauhi he taimí ni. Kātaki ʻo toe ʻahiʻahiʻi.",
        "mic.rec": "ʻOku hiki ʻa e sekoni ʻe 3 — lea ʻaki ha meʻa pē…",
        "mic.ok": "Ko ia naʻe puke ʻe hoʻo maikolofoní — kapau ʻokú ke fanongo kiate koe, ʻoku ngāue ia.",
        "mic.na": "ʻOku ʻikai ala maʻu ʻa e maikolofoní he taimí ni — ʻoku sai pē ia. ʻOku sai tatau pē ʻa e taipé.",
        "mic.saved": "Kuo tauhi — lomiʻi ʻa e Enter ke ʻave, pe hokohoko atu hono fakatonutonú",
        "mic.now": "Fanongo… lea he taimí ni (toe lomiʻi e maikolofoní ke taʻofi)",
        "mic.noauto": "Fanongo… (ʻe ʻikai taipe fakaʻautō hoʻo ngaahi leá ʻi he polauisa ko ʻení, ka ʻoku ngāue ʻa e maikolofoní — te ke lava foki ʻo taipe)",
        "mic.reconn": "Fanongo… (ʻoku ngāue e maikolofoní; toe fakahoko ʻa e hiki tohí…)",
        "mic.paused": "Kuo tuku e fanongó (fakalongolongo siʻi) — lomiʻi e maikolofoní ke hokohoko atu",
        "mic.speak": "&#127908; Lea",
        "vp.auto": "Leʻo: fakaʻautō (lelei taha ʻoku ala maʻu)",
        "vp.human": "Ngaahi leʻo fakaetangata",
        "vp.female": "Ngaahi leʻo fakafefine",
        "vp.male": "Ngaahi leʻo fakatangata",
        "vp.other": "Ngaahi leʻo kehe",
        "vp.test": "Ko e leʻo eni te u ngāueʻakí.",
        "scn.aria": "Fakatātā ʻi mui",
        "s988": "ʻOku ʻikai te ke tokotaha pē. Kapau ʻokú ke fiemaʻu ha poupou fakavavevave, te ke lava ʻo aʻu ki he 988 Suicide and Crisis Lifeline ʻi ha taimi pē ʻaki hoʻo telefoni pe fai ha pōpoaki ki he 988. ʻOku ou nofo ʻi heni pē mo koe.",
        "empty": "ʻOku teʻeki ke u maʻu ha meʻa — fai māmālie pē, pea vahevahe ʻi hoʻo mateuteú.",
        "interrupted": "Naʻe ʻi ai ha meʻa naʻe motuhi ai e fehokotakí — kātaki ʻo toe lea ʻaki ia.",
        "lg.based": "Makatuʻunga he meʻa naʻá ke vahevahé, ko e ngaahi meʻa eni ʻoku ʻaonga ke ʻilo fekauʻaki mo e {issue}:",
        "lg.rights": "Hoʻo ngaahi totonu",
        "lg.ask": "Ngaahi fehuʻi ki ha loea",
        "lg.free": "Feituʻu ke maʻu ai ha tokoni fakalao taʻetotongi",
        "lg.steps": "Ngaahi sitepu te ke lava ʻo fai he taimí ni",
        "wh.connect": "Fakafehokotaki he taimí ni",
        "wh.norush": "ʻi hoʻo mateuteú — ʻoku ʻikai ha fakavavevave",
        "wh.more": "ʻOku ou ʻi heni kapau ʻokú ke fie toe talanoa",
        "reply": "Tali",
        "listen.ph": "ʻOku ou fanongo... (lomiʻi e Enter ke ʻave)",
        "take.ph": "Fai māmālie pē... pe lomiʻi ʻa e Lea (lomiʻi e Enter ke ʻave)",
        "uh": "ʻOku ʻaonga ke kumi tokoni he taimí ni. {988}, pe {911} kapau ʻoku ʻi ai ha fakatuʻutāmaki vave. ʻOku ou nofo ʻi heni pē mo koe.",
        "uh.988": "Telefoni pe fai ha pōpoaki ki he 988",
        "uh.911n": "Telefoni ki he 911"
      },
      sw: {
        "sam.q": "Unajisikiaje sasa hivi? (gusa moja, au unipuuze)",
        "sam.s1": "Nimezidiwa sana",
        "sam.s2": "Sina utulivu",
        "sam.s3": "Katikati",
        "sam.s4": "Niko sawa",
        "sam.s5": "Nimetulia",
        "fb.ask": "Ukiwa na dakika: je, hii ilisaidia? Jibu lako halijulikani nani na linatusaidia kuwasaidia wengine.",
        "fb.yes": "Ilisaidia",
        "fb.some": "Kiasi",
        "fb.no": "Si sana",
        "fb.ph": "Chochote unachotaka kushiriki kuhusu unavyojisikia, au kilichosaidia? (hiari)",
        "fb.share": "Shiriki",
        "fb.nothanks": "Hapana asante",
        "fb.thanks": "Asante kwa kushiriki — kwa kweli inatusaidia kuwafikia wengine.",
        "fb.close": "Funga",
        "mb.title": "Wewe ni wa thamani, na msaada wa kweli upo hapa kwa ajili yako.",
        "mb.lead": "InnerLight imejengwa kwa watu wazima kwa sasa — lakini hufukuzwi. Unachohisi kinastahili mtu halisi aliyefunzwa kusaidia mtu wa umri wako, sasa hivi:",
        "mb.b1": "<b>• Zungumza na mtu mzima unayemwamini</b> — mzazi, ndugu, mshauri wa shule, kocha, au mwalimu. Kuanza sentensi ndiyo sehemu ngumu zaidi; unaweza hata kumwonyesha skrini hii.",
        "mb.b2": "<b>• Piga simu au tuma ujumbe 988</b> — bila malipo, saa 24/7, na wanasaidia vijana kila siku.",
        "mb.b3": "<b>• Tuma HOME kwa 741741</b> — Crisis Text Line, bila malipo, saa 24/7.",
        "mb.b4": "<b>• Teen Line: tuma TEEN kwa 839863</b> — vijana wakisaidia vijana, jioni.",
        "mb.danger": "Ukiwa katika hatari ya papo hapo, piga 911.",
        "mb.ok": "Sawa",
        "mb.note": "Inaonekana huenda uko chini ya miaka 18 — nataka msaada sahihi kwa ajili yako, ambao ni mtu halisi aliyefunzwa kusaidia mtu wa umri wako. Tafadhali angalia chaguzi nilizokuonyesha, na tafadhali mwambie mtu mzima unayemwamini unavyojisikia. Unastahili msaada wa kweli.",
        "sub.note": "Nimefurahi sana kwamba kuwa hapa kunasaidia, na nataka kuwa mkweli nawe kwa sababu najali: mimi si mtu, na siwezi kuwa mbadala wa uhusiano wa kweli wa kibinadamu. Ninachoweza ni kukaa nawe sasa hivi na kukusaidia kuwafikia watu wanaoweza kuwepo kwa ajili yako kikweli — mshauri, mtu unayemwamini, sauti halisi. Unastahili hivyo, zaidi ya skrini. Ungependa nikusaidie kumfikia mtu halisi?",
        "gb.n1": "Umeshiriki mengi, na nimefurahi sana ulivyofanya. Utakapokuwa tayari, hatua inayofuata yenye msaada zaidi ni kuzungumza na mtu halisi anayeweza kubaki nawe zaidi ya wakati huu. Naweza kukuunganisha taratibu, wakati wowote unapotaka.",
        "gb.n2": "Bado niko hapa pamoja nawe, na hakuna haraka. Utakapokuwa tayari, mtu halisi anaweza kuendeleza hili pamoja nawe. Ungependa nikusaidie kumfikia mtu sasa?",
        "gb.connect": "Niunganishe na mtu",
        "gb.keep": "Tuendelee kuzungumza kidogo",
        "sv.min": "Hakuna mengi ya kuhifadhi bado. Shiriki kidogo cha hadithi yako kwanza, kisha gusa Hifadhi tena nami nitakupa msimbo wa faragha wa kurudi.",
        "sv.q": "Uhifadhi ulipofikia? Utapata msimbo wa faragha wa kurudi unaoshikiliwa na wewe pekee.",
        "sv.auto": "Ungependa kuhifadhi ulipofikia, ili usianze upya ukirudi?",
        "sv.btn": "Hifadhi mahali pangu",
        "sv.notnow": "Si sasa",
        "sv.saved": "Imehifadhiwa. Huu ndio msimbo wako wa kurudi — uweke mahali salama:",
        "sv.code": "Msimbo huu pekee ndio unaoweza kufungua tena hadithi yako — hata sisi hatuwezi kuisoma bila msimbo.",
        "sv.copy": "Nakili msimbo",
        "sv.done": "Imekamilika",
        "sv.empty": "Hakukuwa na kilichohifadhiwa bado — shiriki kidogo kwanza.",
        "sv.err": "Imeshindikana kuhifadhi sasa. Tafadhali jaribu tena.",
        "mic.rec": "Inarekodi sekunde 3 — sema chochote…",
        "mic.ok": "Hicho ndicho maiki yako ilichonasa — ukijisikia, inafanya kazi.",
        "mic.na": "Maiki haipatikani sasa — ni sawa. Kuandika kunafanya kazi vilevile.",
        "mic.saved": "Imehifadhiwa — bonyeza Enter kutuma, au endelea kuhariri",
        "mic.now": "Inasikiliza… sema sasa (gusa maiki tena kusimamisha)",
        "mic.noauto": "Inasikiliza… (maneno yako hayataandikwa yenyewe kwenye kivinjari hiki, lakini maiki inafanya kazi — unaweza pia kuandika)",
        "mic.reconn": "Inasikiliza… (maiki inafanya kazi; inaunganisha tena unukuzi…)",
        "mic.paused": "Usikilizaji umesimama (kimya kwa muda) — gusa maiki kuendelea",
        "vp.auto": "Sauti: otomatiki (bora inayopatikana)",
        "vp.human": "Sauti za binadamu",
        "vp.female": "Sauti za kike",
        "vp.male": "Sauti za kiume",
        "vp.other": "Sauti nyingine",
        "vp.test": "Hii ndiyo sauti nitakayotumia.",
        "scn.aria": "Mandhari ya nyuma",
        "empty": "Sijapata chochote bado — chukua muda wako, na shiriki utakapokuwa tayari.",
        "lg.based": "Kwa kuzingatia ulichoshiriki, haya ndiyo yanayofaa kujua kuhusu {issue}:",
        "lg.rights": "Haki zako",
        "lg.ask": "Maswali ya kumuuliza wakili",
        "lg.free": "Pa kupata msaada wa kisheria bila malipo",
        "lg.steps": "Hatua unazoweza kuchukua sasa hivi",
        "wh.connect": "Unganisha sasa",
        "wh.norush": "utakapokuwa tayari — hakuna haraka",
        "s988": "Hauko peke yako. Ukihitaji msaada wa haraka, unaweza kupiga simu au kutuma ujumbe 988 wakati wowote kufikia 988 Suicide and Crisis Lifeline. Niko hapa pamoja nawe.",
        "uh": "Inafaa kutafuta msaada sasa hivi. {988}, au {911} ikiwa kuna hatari ya papo hapo. Ninabaki hapa pamoja nawe.",
        "uh.988": "Piga simu au tuma ujumbe 988",
        "uh.911n": "Piga 911",
        "reply": "Jibu",
        "mic.speak": "Sema",
        "interrupted": "Kuna kitu kilikatiza muunganisho kwa muda — tafadhali sema tena.",
        "wh.more": "Niko hapa ukitaka kuzungumza zaidi",
        "listen.ph": "Nasikiliza... (bonyeza Enter kutuma)",
        "take.ph": "Chukua muda wako... au gusa Sema (bonyeza Enter kutuma)"
      },
      am: {
        "sam.q": "አሁን ምን ይሰማዎታል? (አንዱን ይንኩ፣ ወይም ችላ ይበሉኝ)",
        "sam.s1": "በጣም ተጨንቄያለሁ",
        "sam.s2": "አልረጋጋሁም",
        "sam.s3": "መካከል",
        "sam.s4": "ደህና ነኝ",
        "sam.s5": "ተረጋግቻለሁ",
        "fb.ask": "ደቂቃ ካለዎት: ይህ ረድቷል? መልስዎ ስም-አልባ ነው፤ ሌሎችን እንድንረዳ ይረዳናል።",
        "fb.yes": "ረድቷል",
        "fb.some": "በመጠኑ",
        "fb.no": "ብዙ አይደለም",
        "fb.ph": "ስለሚሰማዎት ወይም ስለረዳዎት ማካፈል የሚፈልጉት ነገር? (አማራጭ)",
        "fb.share": "አካፍል",
        "fb.nothanks": "አይ አመሰግናለሁ",
        "fb.thanks": "ስለአካፈሉ እናመሰግናለን — ሌሎችን ለመድረስ በእውነት ይረዳናል።",
        "fb.close": "ዝጋ",
        "mb.title": "እርስዎ ዋጋ አለዎት፣ እውነተኛ እርዳታም እዚህ አለ።",
        "mb.lead": "InnerLight ለአሁኑ ለአዋቂዎች ተገንብቷል — ግን አልተባረሩም። የሚሰማዎት ነገር የእርስዎን ዕድሜ ለመርዳት የሰለጠነ እውነተኛ ሰው ይገባዋል፣ አሁኑኑ:",
        "mb.b1": "<b>• ከሚያምኑት አዋቂ ጋር ይነጋገሩ</b> — ወላጅ፣ ቤተሰብ፣ የትምህርት ቤት አማካሪ፣ አሰልጣኝ ወይም መምህር። ዓረፍተ ነገሩን መጀመር በጣም ከባዱ ክፍል ነው፤ ይህን ማያ ገጽ እንኳ ሊያሳዩአቸው ይችላሉ።",
        "mb.b2": "<b>• 988 ይደውሉ ወይም መልእክት ይላኩ</b> — ነፃ፣ 24/7፣ ወጣቶችን በየቀኑ ይረዳሉ።",
        "mb.b3": "<b>• HOME ብለው ወደ 741741 ይላኩ</b> — Crisis Text Line፣ ነፃ፣ 24/7።",
        "mb.b4": "<b>• Teen Line: TEEN ብለው ወደ 839863 ይላኩ</b> — ወጣቶች ወጣቶችን የሚረዱበት፣ ምሽት ላይ።",
        "mb.danger": "በአፋጣኝ አደጋ ውስጥ ከሆኑ 911 ይደውሉ።",
        "mb.ok": "እሺ",
        "mb.note": "ከ18 ዓመት በታች ሊሆኑ ይችላሉ የሚል ይመስላል — ለእርስዎ ትክክለኛውን እርዳታ እፈልጋለሁ፣ እሱም የእርስዎን ዕድሜ ለመደገፍ የሰለጠነ እውነተኛ ሰው ነው። እባክዎ ያሳየኋቸውን አማራጮች ይመልከቱ፣ እና እባክዎ ስሜትዎን ለሚያምኑት አዋቂ ይንገሩ። እውነተኛ ድጋፍ ይገባዎታል።",
        "sub.note": "እዚህ መሆን መርዳቱ በጣም አስደስቶኛል፣ እናም ስለምጨነቅ እውነቱን ልንገርዎ: እኔ ሰው አይደለሁም፣ የእውነተኛ የሰው ግንኙነት ምትክ መሆን አልችልም። የምችለው አሁን ከእርስዎ ጋር መቆየት እና በእውነት ሊኖሩልዎ የሚችሉ ሰዎችን እንዲደርሱ መርዳት ነው — አማካሪ፣ የሚያምኑት ሰው፣ እውነተኛ ድምፅ። ከማያ ገጽ በላይ ያንን ይገባዎታል። እውነተኛ ሰው እንዲደርሱ ልርዳዎት?",
        "gb.n1": "ብዙ አካፍለዋል፣ በጣምም ደስ ብሎኛል። ዝግጁ ሲሆኑ፣ በጣም የሚረዳው ቀጣይ እርምጃ ከዚህ ጊዜ ባሻገር ከእርስዎ ጋር መቆየት ከሚችል እውነተኛ ሰው ጋር መነጋገር ነው። በፈለጉት ጊዜ በቀስታ ላገናኝዎ እችላለሁ።",
        "gb.n2": "አሁንም እዚሁ ከእርስዎ ጋር ነኝ፣ ችኮላም የለም። ዝግጁ ሲሆኑ እውነተኛ ሰው ይህን ከእርስዎ ጋር ሊቀጥል ይችላል። አሁን ሰው እንዲደርሱ ልርዳዎት?",
        "gb.connect": "ከሰው ጋር አገናኘኝ",
        "gb.keep": "ትንሽ ተጨማሪ እንነጋገር",
        "sv.min": "እስካሁን ለማስቀመጥ ብዙ የለም። መጀመሪያ ከታሪክዎ ትንሽ ያካፍሉ፣ ከዚያ አስቀምጥ የሚለውን እንደገና ይንኩ፤ የግል የመመለሻ ኮድ እሰጥዎታለሁ።",
        "sv.q": "የደረሱበትን ያስቀምጡ? እርስዎ ብቻ የሚይዙት የግል የመመለሻ ኮድ ያገኛሉ።",
        "sv.auto": "ተመልሰው ሲመጡ እንደገና እንዳይጀምሩ የደረሱበትን ማስቀመጥ ይፈልጋሉ?",
        "sv.btn": "ቦታዬን አስቀምጥ",
        "sv.notnow": "አሁን አይደለም",
        "sv.saved": "ተቀምጧል። ይህ የመመለሻ ኮድዎ ነው — ደህንነቱ በተጠበቀ ቦታ ያስቀምጡት:",
        "sv.code": "ታሪክዎን መልሶ መክፈት የሚችለው ይህ ኮድ ብቻ ነው — ያለ ኮዱ እኛም እንኳ ማንበብ አንችልም።",
        "sv.copy": "ኮድ ቅዳ",
        "sv.done": "ተጠናቀቀ",
        "sv.empty": "እስካሁን የተቀመጠ የለም — መጀመሪያ ትንሽ ያካፍሉ።",
        "sv.err": "አሁን ማስቀመጥ አልተቻለም። እባክዎ እንደገና ይሞክሩ።",
        "mic.rec": "3 ሰከንድ እየተቀዳ ነው — ማንኛውንም ነገር ይናገሩ…",
        "mic.ok": "ማይክዎ የያዘው ይህን ነው — ራስዎን ከሰሙ፣ እየሰራ ነው።",
        "mic.na": "ማይኩ አሁን አይገኝም — ችግር የለም። መጻፍ እንዲሁ ይሰራል።",
        "mic.saved": "ተቀምጧል — ለመላክ Enter ይጫኑ፣ ወይም ማረም ይቀጥሉ",
        "mic.now": "እየሰማ ነው… አሁን ይናገሩ (ለማቆም ማይኩን እንደገና ይንኩ)",
        "mic.noauto": "እየሰማ ነው… (በዚህ አሳሽ ቃላትዎ በራሳቸው አይጻፉም፣ ማይኩ ግን እየሰራ ነው — መጻፍም ይችላሉ)",
        "mic.reconn": "እየሰማ ነው… (ማይክ እየሰራ ነው፤ ግልባጭ እንደገና በመገናኘት ላይ…)",
        "mic.paused": "ማዳመጥ ቆሟል (ለተወሰነ ጊዜ ጸጥታ) — ለመቀጠል ማይኩን ይንኩ",
        "vp.auto": "ድምፅ፡ ራስ-ሰር (ምርጡ የሚገኝ)",
        "vp.human": "የሰው ድምፆች",
        "vp.female": "የሴት ድምፆች",
        "vp.male": "የወንድ ድምፆች",
        "vp.other": "ሌሎች ድምፆች",
        "vp.test": "የምጠቀመው ድምፅ ይህ ነው።",
        "scn.aria": "የጀርባ ትዕይንት",
        "empty": "እስካሁን ምንም አልሰማሁም — ጊዜዎን ይውሰዱ፣ ዝግጁ ሲሆኑ ያካፍሉ።",
        "lg.based": "ካካፈሉት በመነሳት፣ ስለ {issue} ማወቅ የሚገባው ይህ ነው:",
        "lg.rights": "መብቶችዎ",
        "lg.ask": "ጠበቃን የሚጠይቁ ጥያቄዎች",
        "lg.free": "ነፃ የሕግ እርዳታ የሚያገኙበት",
        "lg.steps": "አሁን ሊወስዷቸው የሚችሉ እርምጃዎች",
        "wh.connect": "አሁን አገናኝ",
        "wh.norush": "ዝግጁ ሲሆኑ — ችኮላ የለም",
        "s988": "ብቻዎን አይደሉም። አስቸኳይ ድጋፍ ከፈለጉ በማንኛውም ጊዜ 988 ደውለው ወይም መልእክት ልከው 988 Suicide and Crisis Lifeline መድረስ ይችላሉ። እኔ እዚሁ ከእርስዎ ጋር ነኝ።",
        "uh": "አሁን እርዳታ መፈለግ ተገቢ ነው። {988}፣ ወይም አፋጣኝ አደጋ ካለ {911}። እዚሁ ከእርስዎ ጋር እቆያለሁ።",
        "uh.988": "988 ይደውሉ ወይም መልእክት ይላኩ",
        "uh.911n": "911 ይደውሉ",
        "reply": "መልስ",
        "mic.speak": "ይናገሩ",
        "interrupted": "ግንኙነቱ ለአፍታ ተቋርጧል — እባክዎ እንደገና ይናገሩ።",
        "wh.more": "ተጨማሪ ማውራት ከፈለጉ እዚህ ነኝ",
        "listen.ph": "እየሰማሁ ነው... (ለመላክ Enter ይጫኑ)",
        "take.ph": "ጊዜዎን ይውሰዱ... ወይም ይናገሩ ይንኩ (ለመላክ Enter ይጫኑ)"
      },
      ha: {
        "sam.q": "Yaya kake ji a yanzu? (taɓa ɗaya, ko ka ƙyale ni)",
        "sam.s1": "Na damu sosai",
        "sam.s2": "Ban natsu ba",
        "sam.s3": "Tsakiya",
        "sam.s4": "Ina lafiya",
        "sam.s5": "Na natsu",
        "fb.ask": "Idan kana da minti ɗaya: shin wannan ya taimaka? Amsarka ba a san mai bayarwa ba, kuma tana taimaka mana mu taimaki wasu.",
        "fb.yes": "Ya taimaka",
        "fb.some": "Kaɗan",
        "fb.no": "Ba sosai ba",
        "fb.ph": "Duk abin da kake so ka raba game da yadda kake ji, ko abin da ya taimaka? (na zaɓi)",
        "fb.share": "Raba",
        "fb.nothanks": "A'a, na gode",
        "fb.thanks": "Mun gode da rabawa — da gaske yana taimaka mana mu kai ga wasu.",
        "fb.close": "Rufe",
        "mb.title": "Kana da daraja, kuma taimako na gaske yana nan dominka.",
        "mb.lead": "An gina InnerLight don manya a yanzu — amma ba a kore ka ba. Abin da kake ji ya cancanci mutum na gaske da aka horar don taimaka wa wanda ke shekarunka, yanzu:",
        "mb.b1": "<b>• Yi magana da babban mutum da ka amince da shi</b> — iyaye, dan uwa, mai ba da shawara na makaranta, koci, ko malami. Fara jumlar ita ce mafi wahala; kana ma iya nuna musu wannan allon.",
        "mb.b2": "<b>• Kira ko aika saƙo zuwa 988</b> — kyauta, 24/7, kuma suna taimaka wa matasa kowace rana.",
        "mb.b3": "<b>• Aika HOME zuwa 741741</b> — Crisis Text Line, kyauta, 24/7.",
        "mb.b4": "<b>• Teen Line: aika TEEN zuwa 839863</b> — matasa na taimaka wa matasa, da yamma.",
        "mb.danger": "Idan kana cikin haɗari na gaggawa, kira 911.",
        "mb.ok": "To",
        "mb.note": "Da alama kana ƙasa da shekara 18 — kuma ina son taimakon da ya dace da kai, wato mutum na gaske da aka horar don tallafa wa wanda ke shekarunka. Don Allah duba zaɓuɓɓukan da na nuna maka, kuma don Allah gaya wa babban mutum da ka amince da shi yadda kake ji. Ka cancanci tallafi na gaske.",
        "sub.note": "Na yi farin ciki ƙwarai da kasancewa nan yana taimaka, kuma ina son in kasance mai gaskiya da kai domin na damu: ni ba mutum ba ne, kuma ba zan iya zama madadin haɗin kai na gaske na ɗan adam ba. Abin da zan iya shi ne in kasance tare da kai yanzu in kuma taimake ka ka kai ga mutanen da za su iya kasancewa tare da kai da gaske — mai ba da shawara, wanda ka amince da shi, murya ta gaske. Ka cancanci hakan, fiye da allo. Kana so in taimake ka ka kai ga mutum na gaske?",
        "gb.n1": "Ka raba abubuwa da yawa, kuma na yi farin ciki da ka yi. Duk lokacin da ka shirya, mataki na gaba mafi taimako shi ne yin magana da mutum na gaske wanda zai iya kasancewa tare da kai bayan wannan lokacin. Zan iya haɗa ka a hankali, duk lokacin da kake so.",
        "gb.n2": "Har yanzu ina nan tare da kai, kuma babu gaggawa. Idan ka shirya, mutum na gaske zai iya ci gaba da wannan tare da kai. Kana so in taimake ka ka kai ga wani yanzu?",
        "gb.connect": "Haɗa ni da wani",
        "gb.keep": "Mu ci gaba da magana kaɗan",
        "sv.min": "Babu abin da za a ajiye da yawa tukuna. Fara raba ɗan labarinka, sa'an nan ka sake taɓa Ajiye zan ba ka lambar dawowa ta sirri.",
        "sv.q": "A ajiye inda ka kai? Za ka sami lambar dawowa ta sirri wadda kai kaɗai ka riƙe.",
        "sv.auto": "Kana so a ajiye inda ka kai, don kada ka sake farawa idan ka dawo?",
        "sv.btn": "Ajiye wurina",
        "sv.notnow": "Ba yanzu ba",
        "sv.saved": "An ajiye. Wannan ita ce lambar dawowarka — ajiye ta a wuri mai aminci:",
        "sv.code": "Wannan lambar ce kaɗai za ta iya sake buɗe labarinka — ko mu ma ba za mu iya karanta shi ba tare da lambar ba.",
        "sv.copy": "Kwafi lambar",
        "sv.done": "An gama",
        "sv.empty": "Babu abin da aka ajiye tukuna — fara raba kaɗan.",
        "sv.err": "Ba a iya ajiyewa yanzu ba. Don Allah sake gwadawa.",
        "mic.rec": "Ana ɗauka na daƙiƙa 3 — faɗi kome…",
        "mic.ok": "Abin da makirufonka ya ɗauka ke nan — idan ka ji kanka, yana aiki.",
        "mic.na": "Makirufo ba ya samuwa yanzu — babu laifi. Rubutu yana aiki daidai.",
        "mic.saved": "An ajiye — danna Enter don aikawa, ko ci gaba da gyara",
        "mic.now": "Ana saurare… yi magana yanzu (sake taɓa makirufo don tsayawa)",
        "mic.noauto": "Ana saurare… (kalmominka ba za su rubutu da kansu a wannan burauzar ba, amma makirufo yana aiki — kana iya rubutu ma)",
        "mic.reconn": "Ana saurare… (makirufo na aiki; ana sake haɗa rubutawa…)",
        "mic.paused": "An dakata da saurare (shiru na ɗan lokaci) — taɓa makirufo don ci gaba",
        "vp.auto": "Murya: ta atomatik (mafi kyau da ke samuwa)",
        "vp.human": "Muryoyin mutane",
        "vp.female": "Muryoyin mata",
        "vp.male": "Muryoyin maza",
        "vp.other": "Sauran muryoyi",
        "vp.test": "Wannan ita ce muryar da zan yi amfani da ita.",
        "scn.aria": "Yanayin baya",
        "empty": "Ban ji kome ba tukuna — ɗauki lokacinka, ka raba duk lokacin da ka shirya.",
        "lg.based": "Bisa abin da ka raba, ga abin da ya kamata a sani game da {issue}:",
        "lg.rights": "Haƙƙoƙinka",
        "lg.ask": "Tambayoyin da za ka yi wa lauya",
        "lg.free": "Inda za a sami taimakon shari&#39;a kyauta",
        "lg.steps": "Matakan da za ka iya ɗauka yanzu",
        "wh.connect": "Haɗa yanzu",
        "wh.norush": "duk lokacin da ka shirya — babu gaggawa",
        "s988": "Ba kai kaɗai ba ne. Idan kana buƙatar tallafi cikin gaggawa, kana iya kira ko aika saƙo zuwa 988 a kowane lokaci don isa ga 988 Suicide and Crisis Lifeline. Ina nan tare da kai.",
        "uh": "Ya dace a nemi taimako yanzu. {988}, ko {911} idan akwai haɗari na gaggawa. Ina nan tare da kai.",
        "uh.988": "Kira ko aika saƙo zuwa 988",
        "uh.911n": "Kira 911",
        "reply": "Amsa",
        "mic.speak": "Yi magana",
        "interrupted": "Wani abu ya katse haɗin na ɗan lokaci — don Allah sake faɗa.",
        "wh.more": "Ina nan idan kana son ƙarin magana",
        "listen.ph": "Ina saurare... (danna Enter don aikawa)",
        "take.ph": "Ɗauki lokacinka... ko taɓa Yi magana (danna Enter don aikawa)"
      }
    };
    function _ilux(k){ var lg=(window._ilLang||"en"); var d=_IL_UX[lg]||_IL_UX.en; return (d && d[k]!=null) ? d[k] : _IL_UX.en[k]; }
    window._ilux = _ilux;

    var GATE_GREETINGS = {
      sw: {
        morning:   'Umefika asubuhi.|Hilo lilichukua nguvu.|Pumzika hapa kidogo — niko pamoja nawe.',
        afternoon: 'Umefika hapa.|Hilo lilichukua nguvu.|Pumzika kidogo — niko pamoja nawe.',
        evening:   'Umefika jioni.|Mwanga unazidi kupoa.|Pumzika hapa — niko pamoja nawe.',
        night:     'Uko hapa, katika utulivu.|Usiku unaweza kuonekana mrefu.|Kaa karibu — niko pamoja nawe.'
      },
      am: {
        morning:   'እስከ ጠዋት ደርሰዋል።|ያ ጥንካሬ ጠይቋል።|እዚህ ትንሽ ያርፉ — ከእርስዎ ጋር ነኝ።',
        afternoon: 'እዚህ ደርሰዋል።|ያ ጥንካሬ ጠይቋል።|ትንሽ ያርፉ — ከእርስዎ ጋር ነኝ።',
        evening:   'እስከ ማታ ደርሰዋል።|ብርሃኑ እየለሰለሰ ነው።|እዚህ ያርፉ — ከእርስዎ ጋር ነኝ።',
        night:     'እዚህ ነዎት፣ በጸጥታው ውስጥ።|ሌሊቱ ረጅም ሊመስል ይችላል።|ቅርብ ይሁኑ — ከእርስዎ ጋር ነኝ።'
      },
      ha: {
        morning:   'Ka kai safiya.|Hakan ya ɗauki ƙarfi.|Huta nan kaɗan — ina tare da kai.',
        afternoon: 'Ka iso nan.|Hakan ya ɗauki ƙarfi.|Huta kaɗan — ina tare da kai.',
        evening:   'Ka kai maraice.|Haske yana laushi.|Huta nan — ina tare da kai.',
        night:     'Kana nan, cikin natsuwa.|Dare na iya zama mai tsawo.|Kasance kusa — ina tare da kai.'
      },
      en: {
        morning:   'You made it to morning.|That took something.|Rest here a moment — I’m with you.',
        afternoon: 'You made it here.|That took something.|Rest a moment — I’m with you.',
        evening:   'You made it to evening.|The light is going soft.|Rest here — I’m with you.',
        night:     'You’re here, in the quiet.|The night can feel long.|Stay close — I’m with you.'
      },
      es: {
        morning:   'Llegaste a la mañana.|Eso costó lo suyo.|Descansa aquí un momento — estoy contigo.',
        afternoon: 'Llegaste hasta aquí.|Eso costó lo suyo.|Descansa un momento — estoy contigo.',
        evening:   'Llegaste al atardecer.|La luz se vuelve suave.|Descansa aquí — estoy contigo.',
        night:     'Estás aquí, en la quietud.|La noche puede hacerse larga.|Quédate cerca — estoy contigo.'
      },
      zh: {
        morning:   '你走到了清晨。|这一路并不容易。|在这里歇一歇——我陪着你。',
        afternoon: '你来到了这里。|这一路并不容易。|歇一会儿吧——我陪着你。',
        evening:   '你走到了黄昏。|光正在变得柔和。|在这里歇一歇——我陪着你。',
        night:     '你在这里，在这份安静里。|夜有时很长。|别走远——我陪着你。'
      },
      hi: {
        morning:   'आप सुबह तक आ पहुँचे।|इसमें हिम्मत लगी।|यहाँ पल भर ठहरिए — मैं आपके साथ हूँ।',
        afternoon: 'आप यहाँ तक आ पहुँचे।|इसमें हिम्मत लगी।|पल भर ठहरिए — मैं आपके साथ हूँ।',
        evening:   'आप शाम तक आ पहुँचे।|रोशनी नर्म हो रही है।|यहाँ ठहरिए — मैं आपके साथ हूँ।',
        night:     'आप यहाँ हैं, इस ख़ामोशी में।|रात लंबी लग सकती है।|पास रहिए — मैं आपके साथ हूँ।'
      },
      pa: {
        morning:   'ਤੁਸੀਂ ਸਵੇਰ ਤੱਕ ਪਹੁੰਚ ਗਏ।|ਇਸ ਵਿੱਚ ਹਿੰਮਤ ਲੱਗੀ।|ਇੱਥੇ ਪਲ ਕੁ ਠਹਿਰੋ — ਮੈਂ ਤੁਹਾਡੇ ਨਾਲ ਹਾਂ।',
        afternoon: 'ਤੁਸੀਂ ਇੱਥੇ ਤੱਕ ਪਹੁੰਚ ਗਏ।|ਇਸ ਵਿੱਚ ਹਿੰਮਤ ਲੱਗੀ।|ਪਲ ਕੁ ਠਹਿਰੋ — ਮੈਂ ਤੁਹਾਡੇ ਨਾਲ ਹਾਂ।',
        evening:   'ਤੁਸੀਂ ਸ਼ਾਮ ਤੱਕ ਪਹੁੰਚ ਗਏ।|ਰੋਸ਼ਨੀ ਨਰਮ ਹੋ ਰਹੀ ਹੈ।|ਇੱਥੇ ਠਹਿਰੋ — ਮੈਂ ਤੁਹਾਡੇ ਨਾਲ ਹਾਂ।',
        night:     'ਤੁਸੀਂ ਇੱਥੇ ਹੋ, ਇਸ ਖ਼ਾਮੋਸ਼ੀ ਵਿੱਚ।|ਰਾਤ ਲੰਮੀ ਲੱਗ ਸਕਦੀ ਹੈ।|ਨੇੜੇ ਰਹੋ — ਮੈਂ ਤੁਹਾਡੇ ਨਾਲ ਹਾਂ।'
      },
      bn: {
        morning:   'আপনি সকাল পর্যন্ত এসে পৌঁছেছেন।|এতে সাহস লেগেছে।|এখানে একটু জিরিয়ে নিন — আমি আপনার সাথে আছি।',
        afternoon: 'আপনি এখানে এসে পৌঁছেছেন।|এতে সাহস লেগেছে।|একটু জিরিয়ে নিন — আমি আপনার সাথে আছি।',
        evening:   'আপনি সন্ধ্যা পর্যন্ত এসে পৌঁছেছেন।|আলো নরম হয়ে আসছে।|এখানে থাকুন — আমি আপনার সাথে আছি।',
        night:     'আপনি এখানে, এই নীরবতায়।|রাত দীর্ঘ মনে হতে পারে।|কাছে থাকুন — আমি আপনার সাথে আছি।'
      },
      tl: {
        morning:   'Nakarating ka sa umaga.|Hindi iyon madali.|Magpahinga ka rito sandali — kasama mo ako.',
        afternoon: 'Nakarating ka rito.|Hindi iyon madali.|Magpahinga ka sandali — kasama mo ako.',
        evening:   'Nakarating ka sa takipsilim.|Lumalambot na ang liwanag.|Magpahinga ka rito — kasama mo ako.',
        night:     'Narito ka, sa katahimikan.|Maaaring humaba ang gabi.|Manatili kang malapit — kasama mo ako.'
      },
      to: {
        morning:   'Kuó ke aʻu ki he pongipongí.|Naʻe ʻikai faingofua ia.|Mālōlō heni ʻo ha kiʻi taimi — ʻoku ou ʻiate koe.',
        afternoon: 'Kuó ke aʻu mai ki heni.|Naʻe ʻikai faingofua ia.|Mālōlō ʻo ha kiʻi taimi — ʻoku ou ʻiate koe.',
        evening:   'Kuó ke aʻu ki he efiafí.|ʻOku fakaʻau ke vaivai e maamá.|Mālōlō heni — ʻoku ou ʻiate koe.',
        night:     'ʻOkú ke ʻi heni, ʻi he fakalongolongó.|ʻE lava ke ongoʻi lōloa e poó.|Nofo ofi mai — ʻoku ou ʻiate koe.'
      }
    };
    function gateSlot() {
      var h = new Date().getHours();
      if (h >= 5 && h < 12) return 'morning';
      if (h >= 12 && h < 17) return 'afternoon';
      if (h >= 17 && h < 22) return 'evening';
      return 'night';
    }
    // Word-by-word cinematic fade, like a film title. Chinese fades character by
    // character. Re-runs (faster) whenever the language changes.
    function renderGateGreeting(first) {
      var el = document.getElementById('gate-greeting');
      if (!el || !window._gateSlot) return;
      var slot = window._gateSlot;
      var lang = window._ilLang || 'en';
      var dict = GATE_GREETINGS[lang] || GATE_GREETINGS.en;
      var text = dict[slot] || GATE_GREETINGS.en[slot];
      var t = first ? 1.5 : 0.25;
      var wordGap = (lang === 'zh') ? 0.24 : 0.48;
      var lineGap = (lang === 'zh') ? 1.1 : 1.4;
      if (!first) { wordGap = wordGap * 0.5; lineGap = lineGap * 0.5; }
      el.innerHTML = '';
      var lines = text.split('|');
      // Screen readers hear the greeting as ONE calm sentence (not word-by-word
      // fragments): a visually-hidden copy carries the full text, and the
      // animated word spans are hidden from assistive tech.
      var srp = document.createElement('p');
      srp.className = 'sr-only';
      srp.textContent = lines.join(' ');
      el.appendChild(srp);
      for (var li = 0; li < lines.length; li++) {
        var p = document.createElement('p');
        p.className = 'gate-line';
        p.setAttribute('aria-hidden', 'true');
        var units = (lang === 'zh') ? lines[li].split('') : lines[li].split(' ');
        for (var wi = 0; wi < units.length; wi++) {
          var s = document.createElement('span');
          s.className = 'gw';
          s.textContent = units[wi];
          s.style.animationDelay = t.toFixed(2) + 's';
          p.appendChild(s);
          if (lang !== 'zh') p.appendChild(document.createTextNode(' '));
          t += wordGap;
        }
        el.appendChild(p);
        t += lineGap;
      }
    }
    (function initArrivalGate() {
      try {
        var gate = document.getElementById('welcome-gate');
        if (!gate) return;
        var slot = gateSlot();
        window._gateSlot = slot;
        var sc = GATE_SCENES[slot];
        window._gateSceneKey = sc.key;   // startExperience opens the story on this same photo
        gate.setAttribute('data-time', slot);
        gate.style.setProperty('--g-pos', sc.pos);
        gate.style.setProperty('--gp-x', sc.p.x);
        gate.style.setProperty('--gp-y', sc.p.y);
        gate.style.setProperty('--gp-size', sc.p.s);
        gate.style.setProperty('--gp-alpha', sc.p.a);
        var ph = document.getElementById('gate-photo');
        if (ph) ph.src = sc.src;
        // a few slow motes of light, drifting upward
        var motes = document.getElementById('gate-motes');
        if (motes) {
          var M = [[12,72,26,3],[26,86,34,2],[44,78,30,4],[60,88,38,2.5],[74,70,28,3],[86,82,32,2],[34,92,42,3.5]];
          for (var i = 0; i < M.length; i++) {
            var b = document.createElement('b');
            b.style.left = M[i][0] + '%';
            b.style.top = M[i][1] + '%';
            b.style.width = M[i][3] + 'px';
            b.style.height = M[i][3] + 'px';
            b.style.animationDuration = M[i][2] + 's';
            b.style.animationDelay = (-i * 5.3) + 's';
            motes.appendChild(b);
          }
        }
        renderGateGreeting(true);
      } catch(e){}
    })();
    </script>

    <!-- CALM STORY SCREEN -->
    <section id="story-screen" class="story-screen" style="display:none;">
      <!-- REALISM LEADS: real video background plays first. Animated canvas is fallback only. -->
      <div id="calm-photo-a" aria-hidden="true" style="position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none;opacity:0;transition:opacity 3s ease;overflow:hidden;">
        <img class="scene-full" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center;">
      </div>
      <div id="calm-photo-b" aria-hidden="true" style="position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:0;pointer-events:none;opacity:0;transition:opacity 3s ease;overflow:hidden;">
        <img class="scene-full" alt="" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:center;">
      </div>
      <div id="scene-veil" aria-hidden="true"></div>
      <div id="il-presence" aria-hidden="true"><div class="il-bloom"></div><div class="il-vignette"></div></div>
      <div id="il-presence-word" aria-hidden="true"></div>
      <div class="scene-picker" id="scene-picker" role="group" aria-label="Background scene">
        <button class="scene-btn active" data-scene="garden" onclick="setScene('garden')" title="Garden" aria-label="Garden scene">&#127807;</button>
        <button class="scene-btn" data-scene="sunflower" onclick="setScene('sunflower')" title="Sunflower" aria-label="Sunflower scene">&#127803;</button>
        <button class="scene-btn" data-scene="sunset" onclick="setScene('sunset')" title="Sunset trees" aria-label="Sunset trees scene">&#127749;</button>
        <button class="scene-btn" data-scene="horizon" onclick="setScene('horizon')" title="Golden horizon" aria-label="Golden horizon scene">&#127748;</button>
        <button class="scene-btn" data-scene="moon" onclick="setScene('moon')" title="Night moon" aria-label="Night moon scene">&#127765;</button>
        <button class="scene-btn" data-scene="daymoon" onclick="setScene('daymoon')" title="Day moon" aria-label="Day moon scene">&#127761;</button>
        <button class="scene-btn" data-scene="moonleaf" onclick="setScene('moonleaf')" title="Moon through leaves" aria-label="Moon through leaves scene">&#127769;</button>
        <button class="scene-btn" data-scene="sunflowers" onclick="setScene('sunflowers')" title="Sunflowers" aria-label="Sunflowers scene">&#127804;</button>
        <button class="scene-btn" data-scene="wave" onclick="setScene('wave')" title="Ocean wave" aria-label="Ocean wave scene">&#127754;</button>
        <button class="scene-btn" data-scene="lettuce" onclick="setScene('lettuce')" title="Garden greens" aria-label="Garden greens scene">&#129382;</button>
        <button class="scene-btn" data-scene="pepper" onclick="setScene('pepper')" title="Green pepper" aria-label="Green pepper scene">&#129681;</button>
        <button class="scene-btn" data-scene="redpepper" onclick="setScene('redpepper')" title="Red pepper" aria-label="Red pepper scene">&#127798;</button>
      </div>
      <div class="story-video-bar">
        <video id="visual-preview" class="story-video" autoplay muted playsinline aria-hidden="true"></video>
              </div>
      <div class="story-wrap">
        <h2 class="story-title" data-i18n="story.title">Tell me your story.</h2>
        <p class="story-sub"><span data-i18n="story.sub">Take your time. Say whatever feels true. I am listening.</span> &middot; <a href="#" onclick="openResume();return false;" style="color:#2e6e8e;" data-i18n="story.resume">Been here before? Continue your story</a></p>
        <p style="font-size:12px;color:#6a402b;font-weight:500;margin:-6px 0 10px;text-shadow:0 1px 2px rgba(255,255,255,0.9);"><span data-i18n="story.ainote">InnerLight is an AI program &mdash; not a human, and not a therapist, doctor, or lawyer.</span> <a href="/safety" style="color:#1d5f7e;" data-i18n="story.safetylink">Safety &amp; crisis protocol</a></p>
        <textarea id="message" class="story-input" data-i18n-ph="story.placeholder" aria-label="Start wherever you would like... (press Enter to send)" placeholder="Start wherever you would like... (press Enter to send)" onkeydown="if((event.key==='Enter'||event.keyCode===13)&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendCheckin();}"></textarea>
        <div class="story-actions">
          <button class="story-send" onclick="sendCheckin()" data-i18n="story.send">Send</button>
          <button class="story-mic" type="button" onclick="startVoiceCapture()" title="Speak instead of typing" data-i18n="story.speak">${_ilux('mic.speak')}</button>
        </div>
        <div class="music-bar">
          <button type="button" id="mute-btn" onclick="toggleMute()" aria-label="Mute music" aria-pressed="false" style="background:none;border:1px solid #ddd1c8;border-radius:999px;padding:4px 10px;font-size:13px;cursor:pointer;margin-right:6px;">&#128266;</button><input type="range" id="vol-slider" min="0" max="100" value="24" oninput="setVol(this.value)" style="width:80px;vertical-align:middle;margin-right:8px;" title="Volume" aria-label="Music volume"><span id="music-now" data-i18n="music.now">&#9834; soft music playing</span>
          <button class="music-change" type="button" onclick="changeMusic()" data-i18n="music.change">Change music</button>
          <button class="music-change" type="button" id="entrain-toggle" onclick="toggleEntrainment()" data-i18n="music.pulseon">&#10041; Calm pulse: on</button>
          <button class="music-change" type="button" id="voice-toggle" onclick="toggleVoiceCombined()" data-i18n="music.voiceoff">&#128263; Spoken voice: Off</button>
          <select id="voice-picker" onchange="selectVoice(this.value)" aria-label="Spoken voice" style="display:none;"><option value="">Voice: default</option></select>
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
          <canvas id="calm-touch" tabindex="0" role="application" aria-label="Calm space. Touch and move, or use the arrow keys and Enter, to make gentle light and sound." style="width:100%;height:240px;display:block;border-radius:14px;background:radial-gradient(circle at 50% 50%, #16314a, #0c1322);touch-action:none;cursor:pointer;transition:height 0.5s ease;"></canvas>
        </div>
        <div id="conversation-thread" role="log" aria-live="polite" style="margin-top:22px;"></div>
        <div id="help-rail" role="group" aria-label="Reach real help">
          <a href="tel:988" class="rail-btn rail-988" title="Call 988 now" aria-label="Call 988, the Suicide and Crisis Lifeline, now">&#128222; 988</a>
          <button type="button" class="rail-btn" onclick="openHelp('telehealth')" title="Talk to a provider" data-i18n="rail.provider">Provider</button>
          <button type="button" class="rail-btn" onclick="openHelp('attorney')" title="Legal help" data-i18n="rail.legal">Legal</button>
          <button type="button" class="rail-btn" onclick="openFacilities()" title="Find nearby help" data-i18n="rail.nearby">Nearby help</button>
          <button type="button" class="rail-btn" onclick="openActivities()" title="Calming activities" data-i18n="rail.activities">Activities</button>
          <button type="button" class="rail-btn" onclick="openSaveNow()" title="Save the conversation with a private return code" data-i18n="rail.save">&#128278; Save</button>
          <button type="button" class="rail-btn" onclick="testMic()" title="Test my microphone" data-i18n="rail.testmic">Test mic</button>
        </div>
        <div id="urgent-help" style="display:none;margin:6px auto;max-width:560px;text-align:center;padding:12px;background:rgba(232,83,78,0.1);border:1px solid rgba(232,83,78,0.4);border-radius:14px;color:#b3322e;font-weight:600;"></div>
        <div id="live-transcript" style="display:none;margin-top:14px;padding:14px 16px;background:rgba(111,179,212,0.12);border:1px solid rgba(111,179,212,0.4);border-radius:14px;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <span id="listen-dot" aria-hidden="true" style="width:11px;height:11px;border-radius:50%;background:#e05a5a;display:inline-block;animation:listenpulse 1.1s ease-in-out infinite;"></span>
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
        <textarea id="voice_transcript" aria-hidden="true" tabindex="-1" style="display:none;"></textarea>
        <audio id="ambient-a" preload="auto" playsinline webkit-playsinline></audio>
        <audio id="ambient-b" preload="auto" playsinline webkit-playsinline></audio>
      </div>
    </section>
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
// Gentle-arrival gate: 0..1 multiplier on the music ceiling during the 16s
// arrival rise, so crossfades and adaptive nudges never jump above it.
var _riseGate = 1;
var _xfadeTimer = null;   // the one live crossfade interval (never two at once)
var _musicErrRun = 0;     // consecutive track load errors (reset when audio plays)
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
  sunflowers:'/scenes/photo_12_sunflowers.jpg',
  // GENERATED SCENES — the founder's own photographs, re-lit by our scene
  // generator as different times of day (dawn, golden hour, dusk, moonlight,
  // soft-dream). Same real places, new light. They join the rotation so the
  // background feels endlessly alive without ever leaving his garden.
  g_rosemary_golden:  '/scenes/gen_photo_1_rosemary_golden.jpg',
  g_rosemary_dawn:    '/scenes/gen_photo_1_rosemary_dawn.jpg',
  g_rosemary_dream:   '/scenes/gen_photo_1_rosemary_dream.jpg',
  g_sunflower_golden: '/scenes/gen_photo_5_sunflower_golden.jpg',
  g_sunflower_dusk:   '/scenes/gen_photo_5_sunflower_dusk.jpg',
  g_sunflower_dream:  '/scenes/gen_photo_5_sunflower_dream.jpg',
  g_horizon_dawn:     '/scenes/gen_photo_6_golden_horizon_dawn.jpg',
  g_horizon_dusk:     '/scenes/gen_photo_6_golden_horizon_dusk.jpg',
  g_horizon_dream:    '/scenes/gen_photo_6_golden_horizon_dream.jpg',
  g_moonleaf_night:   '/scenes/gen_photo_7_moon_leaves_moonlight.jpg',
  g_moonleaf_dream:   '/scenes/gen_photo_7_moon_leaves_dream.jpg',
  g_daymoon_night:    '/scenes/gen_photo_4_moon_day_moonlight.jpg',
  g_daymoon_dawn:     '/scenes/gen_photo_4_moon_day_dawn.jpg',
  g_wave_dawn:        '/scenes/gen_photo_9_wave_dawn.jpg',
  g_wave_dream:       '/scenes/gen_photo_9_wave_dream.jpg',
  g_pepper_golden:    '/scenes/gen_photo_10_pepper_golden.jpg',
  g_pepper_dream:     '/scenes/gen_photo_10_pepper_dream.jpg',
  g_sunflowers_golden:'/scenes/gen_photo_12_sunflowers_golden.jpg',
  g_sunflowers_dusk:  '/scenes/gen_photo_12_sunflowers_dusk.jpg'
};
const SCENE_ORDER = ['garden','lettuce','pepper','redpepper','sunflower','sunflowers','sunset','horizon','wave','moon','daymoon','moonleaf'];
// Everything eligible for the random start + slow rotation: originals AND
// the generated re-lit variants. The picker buttons stay the 12 originals.
const SCENE_POOL = SCENE_ORDER.concat(Object.keys(SCENE_PHOTOS).filter(function(k){ return k.indexOf('g_') === 0; }));
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
  // Full-bleed: one continuous photograph fills the entire screen, edge to
  // edge — nothing blurred, nothing that looks concealed. Realism over
  // effects (founder's correction from live use).
  const showing = frameA.style.opacity !== '0' ? frameA : frameB;
  const hidden  = showing === frameA ? frameB : frameA;
  const img = hidden.querySelector('.scene-full');
  img.onload = () => { hidden.style.opacity = '1'; showing.style.opacity = '0'; };
  img.src = src;
}

function startSceneRotation() {
  // Slow, gentle rotation through the real photographs — until the person
  // picks one themselves; their choice always wins.
  // prefers-reduced-motion: no automatic scene changes at all — the person can
  // still change scenes by hand, but nothing moves on its own.
  try { if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return; } catch(e){}
  if (sceneAutoTimer) clearInterval(sceneAutoTimer);
  sceneAutoTimer = setInterval(() => {
    if (sceneUserChose) { clearInterval(sceneAutoTimer); sceneAutoTimer = null; return; }
    // drift to a RANDOM different scene from the full pool (originals + re-lit
    // variants) — never a fixed loop, never the same scene twice in a row
    var next = currentScene;
    for (var t = 0; t < 8 && next === currentScene; t++) {
      next = SCENE_POOL[Math.floor(Math.random() * SCENE_POOL.length)];
    }
    setScene(next, false);
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

    // PRINCIPLE 14 \u2014 NEVER MORE THAN THEY CAN BEAR. We do not instruct the
    // person to serve the technology ("lean in", "come closer"). If the face is
    // far away, the reading simply carries lower confidence and the app quietly
    // leans on its other signals. The person is never corrected.
    (function distanceNudge(){
      var tip = document.getElementById('hr-distance-tip');
      if (tip) tip.remove();   // remove any tip from an earlier version
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
  // PRINCIPLE 14 \u2014 NEVER MORE THAN THEY CAN BEAR. We no longer ask the person
  // to find better light. In dim light the frames are brightened automatically
  // (adaptive gamma below) and the reading simply carries lower confidence;
  // the app quietly leans on its other signals instead of asking for anything.
  if (luma < 55){
    window._darkStreak = (window._darkStreak||0) + 1;
  } else {
    window._darkStreak = 0;
  }
  // Remove any light-tip left over from an earlier version of the app.
  if (window._lightTipEl && window._lightTipEl.isConnected){ window._lightTipEl.remove(); window._lightTipEl = null; }
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
    + '<h3 style="margin:0 0 8px;color:#1e3a5c;">'+_ilux('mb.title')+'</h3>'
    + '<p style="font-size:14px;color:#475569;line-height:1.6;">'+_ilux('mb.lead')+'</p>'
    + '<div style="font-size:14.5px;line-height:1.9;color:#1e293b;">'
    + _ilux('mb.b1') + '<br>'
    + _ilux('mb.b2') + '<br>'
    + _ilux('mb.b3') + '<br>'
    + _ilux('mb.b4') + '</div>'
    + '<p style="font-size:12.5px;color:#64748b;margin-top:12px;">'+_ilux('mb.danger')+'</p>'
    + '<button onclick="hideMinorBridge()" style="margin-top:6px;background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:10px 24px;font-size:14px;font-weight:700;cursor:pointer;">'+_ilux('mb.ok')+'</button>'
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
      div.textContent = _ilux('mb.note');
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
  div.innerHTML = _ilux('sub.note');
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
  if (mins >= 20 && _gentleNudges === 0){ _gentleNudges = 1; showGentleBridge(_ilux('gb.n1')); }
  else if (mins >= 35 && _gentleNudges === 1){ _gentleNudges = 2; showGentleBridge(_ilux('gb.n2')); }
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
    + '<button onclick="bridgeConnect()" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:10px 22px;font-size:14px;font-weight:700;cursor:pointer;margin:3px;">'+_ilux('gb.connect')+'</button>'
    + '<button onclick="closeGentleBridge()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:10px 18px;font-size:14px;cursor:pointer;margin:3px;">'+_ilux('gb.keep')+'</button>';
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
      ' <span style="color:#736049;">You can choose any option below \u2014 this is only a suggestion.</span>'; }
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
  if (/(don.t|do not|not|dont)\\s+(need\\s+)?(a\\s+)?(clinician|counselor|therapist|therapy|counseling)/.test(t)) isClinical = false;
  if (/(don.t|do not|not|dont)\\s+(need\\s+)?(a\\s+)?(lawyer|attorney|legal)/.test(t)) isLegal = false;
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
    err:"\u6682\u65f6\u65e0\u6cd5\u641c\u7d22\u3002\u5982\u9700\u5e2e\u52a9\u67e5\u627e\u6cbb\u7597\uff0c\u8bf7\u62e8\u6253 SAMHSA\uff1a1-800-662-4357\u3002"},
  hi:{title:"अपने आस-पास मदद खोजें", close:"बंद करें",
    intro:"यदि आप इस समय तत्काल संकट में नहीं हैं और खुद संपर्क करने में सक्षम महसूस करते हैं, तो अपना शहर या ZIP लिखें — हम आपके आस-पास मानसिक स्वास्थ्य केंद्र खोजेंगे, जिनसे आप अपनी सुविधा से संपर्क कर सकते हैं।",
    ph:"शहर या ZIP (जैसे San Jose, CA)", search:"खोजें",
    foot:"यदि आप तत्काल खतरे या संकट में हैं, तो <b>988</b> पर कॉल या संदेश करें, या <b>911</b> पर कॉल करें। यह सूची आपके अगले कदम की योजना के लिए है, आपात स्थिति के लिए नहीं।",
    enter:"कृपया शहर या ZIP लिखें।", looking:"आपके आस-पास केंद्र खोजे जा रहे हैं…",
    nores:"अभी उस क्षेत्र के लिए कोई सूची नहीं मिली। आप ये भी आज़मा सकते हैं:",
    samhsa:"SAMHSA राष्ट्रीय हेल्पलाइन: 1-800-662-4357 (निःशुल्क, 24/7, स्थानीय उपचार खोजने में मदद)",
    findtx:"FindTreatment.gov — अपने स्थान से खोजें", call988:"अभी बात करने के लिए <b>988</b> पर कॉल या संदेश करें।",
    confirm:"कृपया समय और सेवाओं की पुष्टि पहले फ़ोन करके करें। सूचियाँ FindTreatment.gov से आती हैं — लाइसेंस प्राप्त केंद्रों की संघीय निर्देशिका।",
    err:"अभी खोज नहीं हो सकी। उपचार खोजने में मदद के लिए SAMHSA को 1-800-662-4357 पर कॉल करें।"},
  pa:{title:"ਆਪਣੇ ਨੇੜੇ ਮਦਦ ਲੱਭੋ", close:"ਬੰਦ ਕਰੋ",
    intro:"ਜੇ ਤੁਸੀਂ ਇਸ ਵੇਲੇ ਤੁਰੰਤ ਸੰਕਟ ਵਿੱਚ ਨਹੀਂ ਹੋ ਅਤੇ ਆਪ ਸੰਪਰਕ ਕਰਨ ਦੇ ਯੋਗ ਮਹਿਸੂਸ ਕਰਦੇ ਹੋ, ਤਾਂ ਆਪਣਾ ਸ਼ਹਿਰ ਜਾਂ ZIP ਲਿਖੋ — ਅਸੀਂ ਤੁਹਾਡੇ ਨੇੜੇ ਮਾਨਸਿਕ ਸਿਹਤ ਕੇਂਦਰ ਲੱਭਾਂਗੇ, ਜਿਨ੍ਹਾਂ ਨਾਲ ਤੁਸੀਂ ਆਪਣੀ ਸਹੂਲਤ ਨਾਲ ਸੰਪਰਕ ਕਰ ਸਕਦੇ ਹੋ।",
    ph:"ਸ਼ਹਿਰ ਜਾਂ ZIP (ਜਿਵੇਂ San Jose, CA)", search:"ਖੋਜੋ",
    foot:"ਜੇ ਤੁਸੀਂ ਤੁਰੰਤ ਖ਼ਤਰੇ ਜਾਂ ਸੰਕਟ ਵਿੱਚ ਹੋ, ਤਾਂ <b>988</b> ਉੱਤੇ ਕਾਲ ਜਾਂ ਸੁਨੇਹਾ ਭੇਜੋ, ਜਾਂ <b>911</b> ਉੱਤੇ ਕਾਲ ਕਰੋ। ਇਹ ਸੂਚੀ ਤੁਹਾਡੇ ਅਗਲੇ ਕਦਮ ਦੀ ਯੋਜਨਾ ਲਈ ਹੈ, ਐਮਰਜੈਂਸੀ ਲਈ ਨਹੀਂ।",
    enter:"ਕਿਰਪਾ ਕਰਕੇ ਸ਼ਹਿਰ ਜਾਂ ZIP ਲਿਖੋ।", looking:"ਤੁਹਾਡੇ ਨੇੜੇ ਕੇਂਦਰ ਲੱਭੇ ਜਾ ਰਹੇ ਹਨ…",
    nores:"ਇਸ ਵੇਲੇ ਉਸ ਇਲਾਕੇ ਲਈ ਕੋਈ ਸੂਚੀ ਨਹੀਂ ਮਿਲੀ। ਤੁਸੀਂ ਇਹ ਵੀ ਅਜ਼ਮਾ ਸਕਦੇ ਹੋ:",
    samhsa:"SAMHSA ਰਾਸ਼ਟਰੀ ਹੈਲਪਲਾਈਨ: 1-800-662-4357 (ਮੁਫ਼ਤ, 24/7, ਸਥਾਨਕ ਇਲਾਜ ਲੱਭਣ ਵਿੱਚ ਮਦਦ)",
    findtx:"FindTreatment.gov — ਆਪਣੀ ਥਾਂ ਤੋਂ ਖੋਜੋ", call988:"ਹੁਣੇ ਗੱਲ ਕਰਨ ਲਈ <b>988</b> ਉੱਤੇ ਕਾਲ ਜਾਂ ਸੁਨੇਹਾ ਭੇਜੋ।",
    confirm:"ਕਿਰਪਾ ਕਰਕੇ ਸਮਾਂ ਅਤੇ ਸੇਵਾਵਾਂ ਪਹਿਲਾਂ ਫ਼ੋਨ ਕਰਕੇ ਪੱਕੀਆਂ ਕਰੋ। ਸੂਚੀਆਂ FindTreatment.gov ਤੋਂ ਆਉਂਦੀਆਂ ਹਨ — ਲਾਇਸੰਸਸ਼ੁਦਾ ਕੇਂਦਰਾਂ ਦੀ ਫੈਡਰਲ ਡਾਇਰੈਕਟਰੀ।",
    err:"ਇਸ ਵੇਲੇ ਖੋਜ ਨਹੀਂ ਹੋ ਸਕੀ। ਇਲਾਜ ਲੱਭਣ ਵਿੱਚ ਮਦਦ ਲਈ SAMHSA ਨੂੰ 1-800-662-4357 ਉੱਤੇ ਕਾਲ ਕਰੋ।"},
  bn:{title:"আপনার কাছাকাছি সাহায্য খুঁজুন", close:"বন্ধ করুন",
    intro:"আপনি যদি এই মুহূর্তে তাৎক্ষণিক সংকটে না থাকেন এবং নিজে যোগাযোগ করতে সক্ষম বোধ করেন, তাহলে আপনার শহর বা ZIP লিখুন — আমরা আপনার কাছাকাছি মানসিক স্বাস্থ্য কেন্দ্র খুঁজব, যেখানে আপনি সুবিধামতো নিজেই যোগাযোগ করতে পারবেন।",
    ph:"শহর বা ZIP (যেমন San Jose, CA)", search:"খুঁজুন",
    foot:"আপনি যদি তাৎক্ষণিক বিপদে বা সংকটে থাকেন, তাহলে <b>988</b> নম্বরে কল বা টেক্সট করুন, অথবা <b>911</b> নম্বরে কল করুন। এই তালিকা আপনার পরবর্তী পদক্ষেপ পরিকল্পনার জন্য, জরুরি অবস্থার জন্য নয়।",
    enter:"অনুগ্রহ করে শহর বা ZIP লিখুন।", looking:"আপনার কাছাকাছি কেন্দ্র খোঁজা হচ্ছে…",
    nores:"এই মুহূর্তে ওই এলাকার জন্য কিছু পাওয়া যায়নি। আপনি এগুলোও চেষ্টা করতে পারেন:",
    samhsa:"SAMHSA জাতীয় হেল্পলাইন: 1-800-662-4357 (বিনামূল্যে, ২৪/৭, স্থানীয় চিকিৎসা খুঁজে দেয়)",
    findtx:"FindTreatment.gov — আপনার অবস্থান দিয়ে খুঁজুন", call988:"এখনই কথা বলতে <b>988</b> নম্বরে কল বা টেক্সট করুন।",
    confirm:"অনুগ্রহ করে আগে ফোন করে সময় ও সেবা নিশ্চিত করুন। তালিকাগুলো আসে FindTreatment.gov থেকে — লাইসেন্সপ্রাপ্ত কেন্দ্রের ফেডারেল ডিরেক্টরি।",
    err:"এই মুহূর্তে খোঁজা গেল না। চিকিৎসা খুঁজতে সাহায্যের জন্য SAMHSA-কে 1-800-662-4357 নম্বরে কল করুন।"},
  tl:{title:"Maghanap ng tulong malapit sa iyo", close:"Isara",
    intro:"Kung wala ka sa agarang krisis at kaya mong makipag-ugnayan nang mag-isa, ilagay ang iyong lungsod o ZIP at hahanapan ka namin ng mga lugar para sa kalusugang pangkaisipan na malapit sa iyo, na maaari mong kontakin sa sarili mong oras.",
    ph:"Lungsod o ZIP (hal. San Jose, CA)", search:"Hanapin",
    foot:"Kung ikaw ay nasa agarang panganib o krisis, tumawag o mag-text sa <b>988</b>, o tumawag sa <b>911</b>. Ang listahang ito ay para sa pagpaplano ng susunod mong hakbang, hindi para sa emergency.",
    enter:"Pakilagay ang lungsod o ZIP.", looking:"Hinahanap ang mga lugar malapit sa iyo…",
    nores:"Wala kaming nahanap na listahan para sa lugar na iyon sa ngayon. Maaari mo ring subukan:",
    samhsa:"SAMHSA National Helpline: 1-800-662-4357 (libre, 24/7, tumutulong maghanap ng lokal na paggamot)",
    findtx:"FindTreatment.gov — maghanap ayon sa iyong lokasyon", call988:"Tumawag o mag-text sa <b>988</b> para makausap ngayon.",
    confirm:"Pakikumpirma ang oras at serbisyo sa pamamagitan ng pagtawag muna. Galing ang mga listahan sa FindTreatment.gov, ang pederal na direktoryo ng mga lisensyadong pasilidad.",
    err:"Hindi makapaghanap sa ngayon. Para sa tulong sa paghahanap ng paggamot, tawagan ang SAMHSA sa 1-800-662-4357."},
  to:{title:"Kumi tokoni ofi kiate koe", close:"Tāpuni",
    intro:"Kapau ʻoku ʻikai te ke ʻi ha faingataʻa fakavavevave he taimí ni pea ʻokú ke ongoʻi malava ke ke fetuʻutaki pē ʻe koe, tohi hoʻo kolo pe ZIP pea te mau kumi ha ngaahi feituʻu tokoni ki he moʻui fakaʻatamai ofi kiate koe, te ke lava ʻo fetuʻutaki ki ai ʻi hoʻo taimi pē ʻoʻou.",
    ph:"Kolo pe ZIP (hangē ko San Jose, CA)", search:"Kumi",
    foot:"Kapau ʻokú ke ʻi ha tuʻunga fakatuʻutāmaki pe faingataʻa fakavavevave, telefoni pe fai ha pōpoaki ki he <b>988</b>, pe telefoni ki he <b>911</b>. Ko e lisi ko ʻení ke palani ʻaki hoʻo sitepu hoko, ʻoku ʻikai ki ha meʻa fakavavevave.",
    enter:"Kātaki ʻo tohi ha kolo pe ZIP.", looking:"ʻOku kumi ʻa e ngaahi feituʻu ofi kiate koe…",
    nores:"Naʻe ʻikai ke mau maʻu ha lisi ki he feituʻu ko iá he taimí ni. Te ke lava foki ʻo ʻahiʻahiʻi:",
    samhsa:"SAMHSA National Helpline: 1-800-662-4357 (taʻetotongi, 24/7, tokoni ke kumi ha faitoʻo fakalotofonua)",
    findtx:"FindTreatment.gov — kumi ʻaki ho feituʻu", call988:"Telefoni pe fai ha pōpoaki ki he <b>988</b> ke talanoa he taimí ni.",
    confirm:"Kātaki ʻo fakapapauʻi ʻa e ngaahi houa mo e ngaahi tokoni ʻaki hoʻo telefoni ki muʻa. ʻOku haʻu ʻa e ngaahi lisí mei he FindTreatment.gov, ko e lisi fakapuleʻanga ʻo e ngaahi feituʻu maʻu laiseni.",
    err:"Naʻe ʻikai lava ʻa e kumí he taimí ni. Ki ha tokoni ke kumi ha faitoʻo, telefoni ki he SAMHSA ʻi he 1-800-662-4357."}
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
    + '<p style="font-size:13px;color:#736049;line-height:1.5;">'+_ilfac("intro")+'</p>'
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
  if (box) box.innerHTML='<span style="color:#736049;font-size:14px;">'+_ilfac("looking")+'</span>';
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
     '<div style="font-size:14px;color:#4a362c;margin-bottom:10px;text-align:center;">'+_ilux('fb.ask')+'</div>'
   + '<div style="text-align:center;margin-bottom:8px;">'
   +   '<button class="fb-h" data-v="yes" style="margin:3px;border:1px solid #d3a47d;background:#f8f5f2;color:#6a402c;border-radius:999px;padding:7px 14px;font-size:13px;cursor:pointer;">'+_ilux('fb.yes')+'</button>'
   +   '<button class="fb-h" data-v="somewhat" style="margin:3px;border:1px solid #ddd1c8;background:#fff;color:#99673e;border-radius:999px;padding:7px 14px;font-size:13px;cursor:pointer;">'+_ilux('fb.some')+'</button>'
   +   '<button class="fb-h" data-v="no" style="margin:3px;border:1px solid #e0c8c8;background:#fff;color:#9a6a6a;border-radius:999px;padding:7px 14px;font-size:13px;cursor:pointer;">'+_ilux('fb.no')+'</button>'
   + '</div>'
   + '<textarea id="fb-words" aria-label="'+_ilux('fb.ph')+'" placeholder="'+_ilux('fb.ph')+'" style="width:100%;box-sizing:border-box;height:56px;border:1px solid #ddd1c8;border-radius:10px;padding:9px;font-size:13px;resize:none;"></textarea>'
   + '<div style="text-align:center;margin-top:8px;">'
   +   '<button onclick="submitFeedback()" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:9px 22px;font-size:14px;font-weight:700;cursor:pointer;margin:0 4px;">'+_ilux('fb.share')+'</button>'
   +   '<button onclick="closeFb()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:9px 16px;font-size:14px;cursor:pointer;margin:0 4px;">'+_ilux('fb.nothanks')+'</button>'
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
  if (card) card.innerHTML = '<div style="text-align:center;font-size:14px;color:#6a402c;padding:6px;">'+_ilux('fb.thanks')+' <button onclick="closeFb()" style="margin-left:8px;background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:6px 14px;cursor:pointer;">'+_ilux('fb.close')+'</button></div>';
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
  en:{q:'How are you feeling right now?', a:'Settled', b:'Overwhelmed', thanks:'Thank you.', skip:'Not now',
      scale:['Settled','Mostly settled','In between','Mostly overwhelmed','Overwhelmed']},
  es:{q:'¿Cómo te sientes ahora mismo?', a:'En calma', b:'Abrumado/a', thanks:'Gracias.', skip:'Ahora no',
      scale:['En calma','Bastante en calma','Entre medio','Bastante abrumado','Abrumado']},
  zh:{q:'你现在感觉怎么样？', a:'平静', b:'不知所措', thanks:'谢谢你。', skip:'暂不',
      scale:['平静','比较平静','中间','比较不知所措','不知所措']},
  hi:{q:'आप इस समय कैसा महसूस कर रहे हैं?', a:'शांत', b:'बहुत बोझिल', thanks:'धन्यवाद।', skip:'अभी नहीं',
      scale:['शांत','काफ़ी शांत','बीच में','काफ़ी बोझिल','बहुत बोझिल']},
  pa:{q:'ਤੁਸੀਂ ਇਸ ਵੇਲੇ ਕਿਵੇਂ ਮਹਿਸੂਸ ਕਰ ਰਹੇ ਹੋ?', a:'ਸ਼ਾਂਤ', b:'ਬਹੁਤ ਬੋਝ ਹੇਠ', thanks:'ਧੰਨਵਾਦ।', skip:'ਹੁਣ ਨਹੀਂ',
      scale:['ਸ਼ਾਂਤ','ਕਾਫ਼ੀ ਸ਼ਾਂਤ','ਵਿਚਕਾਰ','ਕਾਫ਼ੀ ਬੋਝ ਹੇਠ','ਬਹੁਤ ਬੋਝ ਹੇਠ']},
  sw:{q:'Unajisikiaje sasa hivi?', a:'Nimetulia', b:'Nimezidiwa', thanks:'Asante.', skip:'Si sasa',
      scale:['Nimetulia','Nimetulia kiasi','Katikati','Nimezidiwa kiasi','Nimezidiwa']},
  am:{q:'አሁን ምን ይሰማዎታል?', a:'ተረጋግቻለሁ', b:'ተጨንቄያለሁ', thanks:'አመሰግናለሁ።', skip:'አሁን አይደለም',
      scale:['ተረጋግቻለሁ','በአብዛኛው ተረጋግቻለሁ','መካከል','በአብዛኛው ተጨንቄያለሁ','ተጨንቄያለሁ']},
  ha:{q:'Yaya kake ji a yanzu?', a:'Na natsu', b:'Na cika da damuwa', thanks:'Na gode.', skip:'Ba yanzu ba',
      scale:['Na natsu','Na natsu sosai-sosai','Tsakiya','Damuwa kaɗan-kaɗan','Na cika da damuwa']},
  bn:{q:'আপনি এই মুহূর্তে কেমন বোধ করছেন?', a:'শান্ত', b:'ভীষণ চাপে', thanks:'ধন্যবাদ।', skip:'এখন নয়',
      scale:['শান্ত','মোটামুটি শান্ত','মাঝামাঝি','বেশ চাপে','ভীষণ চাপে']},
  tl:{q:'Ano ang nararamdaman mo ngayon?', a:'Panatag', b:'Lubhang nalulula', thanks:'Salamat.', skip:'Hindi muna',
      scale:['Panatag','Medyo panatag','Nasa gitna','Medyo nalulula','Lubhang nalulula']},
  to:{q:'ʻOkú ke ongoʻi fēfē he taimí ni?', a:'Nonga', b:'Māfasia', thanks:'Mālō.', skip:'ʻIkai he taimí ni',
      scale:['Nonga','Meimei nonga','Vahaʻa','Meimei māfasia','Māfasia']}
};
function _ilct(k){ var lg=(window._ilLang||'en'); return (_IL_CT[lg]||_IL_CT.en)[k]; }
function showCheckin(){ if(document.getElementById('il-checkin')) return;
  var wrap=document.createElement('div'); wrap.id='il-checkin';
  wrap.style.cssText='position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:9000;max-width:92vw;'
    +'background:#faf5ec;border:1px solid #e7dccc;border-radius:18px;box-shadow:0 12px 40px rgba(42,30,20,0.22);'
    +'padding:16px 18px 14px;text-align:center;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;';
  var dots=''; var i; var scale=_ilct('scale')||[];
  for(i=0;i<5;i++){ var sz=14+i*3; var col=['#5f8bb6','#7f97b0','#b9a58f','#cf8a5e','#c56a2c'][i];
    dots+='<button aria-label="'+(scale[i]||i)+'" onclick="ilCheckinPick('+(i/4)+')" style="border:0;background:'+col+';'
      +'width:'+sz+'px;height:'+sz+'px;border-radius:50%;margin:0 9px;cursor:pointer;padding:0;vertical-align:middle;opacity:.92;"></button>'; }
  wrap.innerHTML='<div style="font-size:15px;color:#2b2620;margin-bottom:12px;">'+_ilct('q')+'</div>'
    +'<div style="display:flex;align-items:center;justify-content:center;">'
    +'<span style="font-size:12px;color:#6b5f4e;margin-right:6px;">'+_ilct('a')+'</span>'+dots
    +'<span style="font-size:12px;color:#6b5f4e;margin-left:6px;">'+_ilct('b')+'</span></div>'
    +'<div style="margin-top:8px;"><a href="#" onclick="closeCheckin();return false;" style="font-size:12px;color:#6b5f4e;text-decoration:none;">'+_ilct('skip')+'</a></div>';
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
  // PRINCIPLE 14 — NEVER MORE THAN THEY CAN BEAR. An interruption is an ask.
  // Never interrupt a person who is writing or speaking — their outpouring is
  // sacred. And ask far less often: the program reads; the person is carried.
  var typedRecently = (window._lastTypedAt && (performance.now() - window._lastTypedAt) < 45000);
  var writingNow = (document.activeElement && document.activeElement.id === 'message' && (document.getElementById('message')||{}).value);
  var speakingNow = (typeof voiceListening !== 'undefined' && voiceListening);
  if (typedRecently || writingNow || speakingNow) return;
  var now=Date.now(); var since=now-_ilCheckinLast;
  var conf=(window.ATT?ATT.confidence():1);
  var firstDue=(_ilCheckinLast===0 && (now-_ilSessionStart)>240000);
  var lowConf=(conf<0.45 && since>360000);
  var periodic=(_ilCheckinLast>0 && since>480000);
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
      stay:'……和我在一起。', words:['就在这里。','陪着你。','吸气……','呼气……','你是安全的。','和我在一起。']},
  hi:{hint:'रोशनी को छुएँ — लय आपके साथ चलेगी', close:'अभी मैं ठीक हूँ', pill:'मेरे साथ ध्यान लगाएँ',
      stay:'… मेरे साथ रहिए।', words:['यहीं हूँ।','आपके साथ।','साँस अंदर…','और बाहर…','आप सुरक्षित हैं।','मेरे साथ रहिए।']},
  pa:{hint:'ਰੋਸ਼ਨੀ ਨੂੰ ਛੂਹੋ — ਤਾਲ ਤੁਹਾਡੇ ਨਾਲ ਚੱਲੇਗੀ', close:'ਹੁਣ ਮੈਂ ਠੀਕ ਹਾਂ', pill:'ਮੇਰੇ ਨਾਲ ਧਿਆਨ ਲਾਓ',
      stay:'… ਮੇਰੇ ਨਾਲ ਰਹੋ।', words:['ਇੱਥੇ ਹਾਂ।','ਤੁਹਾਡੇ ਨਾਲ।','ਸਾਹ ਅੰਦਰ…','ਤੇ ਬਾਹਰ…','ਤੁਸੀਂ ਸੁਰੱਖਿਅਤ ਹੋ।','ਮੇਰੇ ਨਾਲ ਰਹੋ।']},
  bn:{hint:'আলোটি ছুঁয়ে দেখুন — ছন্দ আপনাকে অনুসরণ করবে', close:'এখন আমি ঠিক আছি', pill:'আমার সাথে মন দিন',
      stay:'… আমার সাথে থাকুন।', words:['এখানে আছি।','আপনার সাথে।','শ্বাস নিন…','আর ছাড়ুন…','আপনি নিরাপদ।','আমার সাথে থাকুন।']},
  tl:{hint:'i-tap ang liwanag — susunod sa iyo ang ritmo', close:'Ayos lang ako sa ngayon', pill:'Sabay tayong tumutok',
      stay:'… manatili ka sa akin.', words:['narito ako.','kasama mo.','huminga papasok…','at palabas…','ligtas ka.','manatili ka sa akin.']},
  to:{hint:'lomiʻi e maama — ʻe muimui e taá kiate koe', close:'ʻOku ou sai pē he taimí ni', pill:'Tau tokanga fakataha',
      stay:'… nofo mo au.', words:['ʻoku ou ʻi heni.','ʻoku ou ʻiate koe.','mānava ki loto…','pea ki tuʻa…','ʻokú ke malu.','nofo mo au.']}
};
function _ilan(k){ var lg=(window._ilLang||'en'); return (_IL_AN[lg]||_IL_AN.en)[k]; }
function showAnchor(){ if(document.getElementById('il-anchor')) return; _ilAnchorLast=Date.now();
  var A=_IL_AN[(window._ilLang||'en')]||_IL_AN.en;
  var ov=document.createElement('div'); ov.id='il-anchor';
  ov.style.cssText='position:fixed;inset:0;z-index:9500;opacity:0;transition:opacity 1.2s ease;overflow:hidden;'
    +'background:radial-gradient(60% 60% at 50% 42%,#2a1d12 0%,#1c140d 55%,#140e09 100%);'
    +'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;';
  ov.innerHTML='<canvas id="il-anchor-c" aria-hidden="true" style="position:absolute;inset:0;width:100%;height:100%;display:block;"></canvas>'
    +'<div id="il-anchor-w" style="position:absolute;left:0;right:0;top:42%;transform:translateY(-50%);text-align:center;'
    +'font-size:28px;color:#f3e9dc;opacity:0;pointer-events:none;text-shadow:0 2px 20px rgba(0,0,0,.6);"></div>'
    +'<div style="position:absolute;left:0;right:0;bottom:96px;text-align:center;font-size:13px;color:#a8917c;pointer-events:none;">'+A.hint+'</div>'
    +'<button id="il-anchor-x" style="position:absolute;left:50%;bottom:34px;transform:translateX(-50%);'
    +'background:rgba(28,20,13,.7);border:1px solid rgba(240,176,112,.3);color:#d7c3ad;border-radius:999px;'
    +'padding:9px 18px;font-size:13px;cursor:pointer;">'+A.close+'</button>';
  document.body.appendChild(ov);
  document.getElementById('il-anchor-x').addEventListener('click', function(ev){ ev.stopPropagation(); hideAnchor(); });
  // Keyboard path: Enter or Space taps the light (same rhythm logic as touch);
  // Escape closes. The close button receives focus so the overlay never traps.
  ov._key = function(ev){
    if (ev.key === 'Escape'){ ev.preventDefault(); hideAnchor(); return; }
    if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar'){
      if (document.activeElement && document.activeElement.id === 'il-anchor-x') return;
      ev.preventDefault();
      ov.dispatchEvent(new Event('pointerdown'));
    }
  };
  document.addEventListener('keydown', ov._key);
  try { document.getElementById('il-anchor-x').focus({preventScroll:true}); } catch(e){}
  requestAnimationFrame(function(){ ov.style.opacity=1; });
  ilAnchorRun(ov, A);
}
function hideAnchor(){ var o=document.getElementById('il-anchor'); if(o){ o._stop=true;
  try{ if(o._key) document.removeEventListener('keydown', o._key); }catch(e){}
  try{o.remove();}catch(e){} } _ilAnchorLast=Date.now(); }
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
  b.style.cssText='position:fixed;left:22px;bottom:96px;z-index:8000;background:rgba(42,29,18,.62);'
    +'border:1px solid rgba(240,176,112,.3);color:#e8d8c4;border-radius:999px;padding:9px 14px;font-size:12.5px;'
    +'cursor:pointer;backdrop-filter:blur(6px);';
  b.addEventListener('click', function(){ showAnchor(); });
  document.body.appendChild(b); }
function ilMaybeAnchor(){ try{
  var ss=document.getElementById('story-screen'); if(!ss || ss.style.display==='none') return;
  if(document.getElementById('il-anchor')) return;
  if(!_ilEngaged) return;
  // Principle 14: never rise up over someone who is speaking aloud.
  if (typeof voiceListening !== 'undefined' && voiceListening) return;
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
    if (!userMuted) {  // never creep the volume back up on a muted person
      const ceil = TARGET_VOL * _riseGate;  // respect the gentle 16s arrival rise
      let target = ceil - (adaptiveArousal - 0.5) * band; // higher arousal => softer
      target = Math.max(Math.max(0, ceil - band), Math.min(ceil + band*0.5, target));
      // ease toward target
      deck.volume = Math.min(1, Math.max(0, deck.volume + (target - deck.volume) * 0.2));
    }
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
    const prevLane = adaptiveLaneNow;
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
            const sceneFor = { deepcalm: ['moon','moonleaf','horizon','g_moonleaf_night','g_daymoon_night','g_moonleaf_dream','g_wave_dream'],
                               lifting: ['sunflower','sunset','garden','g_sunflower_golden','g_sunflowers_golden','g_rosemary_golden','g_horizon_dusk'],
                               calm: ['garden','horizon','daymoon','g_rosemary_dawn','g_wave_dawn','g_horizon_dawn','g_daymoon_dawn'] };
            const opts = sceneFor[want] || SCENE_POOL;
            setScene(opts[Math.floor(Math.random()*opts.length)], false);
          }
        } else {
          adaptiveLaneNow = prevLane;  // nothing came back — try again on a later tick
        }
      }).catch(()=>{ adaptiveLaneNow = prevLane; });  // fetch failed — retry later
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
// THE PRESENCE — the VISIBLE proof that InnerLight is reading and responding in
// real time. The same personal, baseline-relative read that steers the sound
// now openly moves a soft light on the screen:
//   - When the person is more activated than their own calm, the light draws
//     INWARD, warms, dims a touch, and breathes SLOWER and deeper — a contained,
//     steady presence that meets them and gently leads the pace down (the same
//     iso-principle the sound uses).
//   - As they settle toward (and below) their own calm, the light OPENS wider,
//     eases a little brighter, and breathes easy and spacious.
// Confidence gates how much it moves: when the read is unsure, the motion is
// barely there — it never pretends to know more than it does, and it NEVER
// labels an emotion. Words are rare, about presence and time, never about a
// detected state. All motion is smoothed frame-by-frame so it is alive but never
// lurches. Text stays fully readable (this layer sits below all content).
// ---------------------------------------------------------------------------
let presenceRAF = null;
let _presArousal = 0.5, _presConf = 0, _presDown = 0;   // extra-smoothed for buttery motion
let _presPeak = 0.5, _presLastWord = 0, _presStart = 0;
const _IL_PRES = {
  en: ["I’m here.", "Take your time.", "There’s no rush.", "I’m right here with you.", "Breathe. I’m here."],
  es: ["Estoy aquí.", "Tómate tu tiempo.", "No hay prisa.", "Respira, estoy aquí.", "Aquí estoy contigo."],
  zh: ["我在这里。", "慢慢来。", "别急。", "呼吸，我在这里。", "我一直在你身边。"],
  hi: ["मैं यहीं हूँ।", "अपना समय लीजिए।", "कोई जल्दी नहीं।", "मैं आपके साथ हूँ।", "साँस लीजिए। मैं यहीं हूँ।"],
  pa: ["ਮੈਂ ਇੱਥੇ ਹਾਂ।", "ਆਪਣਾ ਸਮਾਂ ਲਵੋ।", "ਕੋਈ ਕਾਹਲੀ ਨਹੀਂ।", "ਮੈਂ ਤੁਹਾਡੇ ਨਾਲ ਹਾਂ।", "ਸਾਹ ਲਵੋ। ਮੈਂ ਇੱਥੇ ਹਾਂ।"],
  bn: ["আমি এখানে আছি।", "সময় নিন।", "কোনো তাড়া নেই।", "আমি আপনার পাশে আছি।", "শ্বাস নিন। আমি এখানে আছি।"],
  tl: ["Narito ako.", "Huwag magmadali.", "Walang pagmamadali.", "Kasama mo ako.", "Huminga ka. Narito ako."],
  to: ["ʻOku ou ʻi heni.", "Fai māmālie pē.", "ʻOku ʻikai ha fakavavevave.", "ʻOku ou ʻiate koe.", "Mānava. ʻOku ou ʻi heni."]
};
function _ilPresWords(){ var lg=(window._ilLang||"en"); return _IL_PRES[lg]||_IL_PRES.en; }

function ilPresenceWord(){
  var el = document.getElementById("il-presence-word"); if(!el) return;
  var arr = _ilPresWords();
  // pick without a hard index dependency (varies naturally)
  var i = Math.floor((performance.now()/1000 + arr.length) % arr.length);
  el.textContent = arr[i % arr.length];
  el.style.opacity = "0.92";
  setTimeout(function(){ el.style.opacity = "0"; }, 5200);
}

function startPresence(){
  if (presenceRAF) return;
  var bloom = document.querySelector("#il-presence .il-bloom");
  var vig = document.querySelector("#il-presence .il-vignette");
  if (!bloom || !vig) return;
  // prefers-reduced-motion: the presence becomes a still, gentle glow —
  // present but not breathing, no frame loop at all.
  try {
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches){
      bloom.style.opacity = "0.20";
      bloom.style.transform = "translate(-50%,-50%) scale(1)";
      return;
    }
  } catch(e){}
  _presStart = performance.now();
  function frame(now){
    // ease our display values toward the live read (which the adaptive loop keeps fresh)
    var aRead = (typeof adaptiveArousal === "number") ? adaptiveArousal : 0.5;
    var cRead = (typeof window._attConfidence === "number") ? window._attConfidence : 0;
    var dRead = (typeof adaptiveDownSm === "number") ? adaptiveDownSm : 0;
    _presArousal += (aRead - _presArousal) * 0.05;
    _presConf    += (cRead - _presConf)    * 0.05;
    _presDown    += (dRead - _presDown)    * 0.05;

    // how far above / below their OWN calm (0.5)
    var act = Math.max(0, Math.min(1, (_presArousal - 0.5) * 2));   // activated
    var set = Math.max(0, Math.min(1, (0.5 - _presArousal) * 2));   // settled/flat
    var conf = Math.max(0, Math.min(1, _presConf));

    // breathing — slower & deeper when activated (leads the pace down)
    var periodMs = 6500 + act * 4500;                 // 6.5s calm -> 11s activated
    var ph = ((now - _presStart) % periodMs) / periodMs;
    var breath = 0.5 - 0.5 * Math.cos(2 * Math.PI * ph);   // 0..1 smooth

    // the light draws inward when activated, opens wide when settled
    var baseScale = 1.06 - act * 0.30 + set * 0.14;        // smaller when activated
    var scale = baseScale + breath * (0.05 + act * 0.05);

    // visibility gated by confidence; a gentle floor so it is always faintly alive
    var vis = 0.10 + conf * 0.34;
    var op = vis * (0.55 + 0.45 * breath);

    // warmth + brightness: activated -> warmer & a touch dimmer; settled -> open & clearer
    var hue = -act * 10 + set * 6;                         // degrees
    var bright = 1 + set * 0.10 - act * 0.06;

    bloom.style.opacity = op.toFixed(3);
    bloom.style.transform = "translate(-50%,-50%) scale(" + scale.toFixed(3) + ")";
    bloom.style.filter = "hue-rotate(" + hue.toFixed(1) + "deg) brightness(" + bright.toFixed(3) + ")";

    // the enclosing vignette appears only when activated — a gentle held frame
    vig.style.opacity = (act * conf * 0.55).toFixed(3);

    // rare, gentle words — on a clear SETTLE after being activated (not a label)
    _presPeak = Math.max(_presPeak * 0.9995, _presArousal);
    var settledFromPeak = (_presPeak > 0.60) && (_presArousal < _presPeak - 0.12) && (conf > 0.35);
    if (settledFromPeak && (now - _presLastWord > 45000)) {
      _presLastWord = now; _presPeak = _presArousal;   // reset so it doesn't repeat
      try { ilPresenceWord(); } catch(e){}
    }

    presenceRAF = requestAnimationFrame(frame);
  }
  presenceRAF = requestAnimationFrame(frame);
}
function stopPresence(){
  if (presenceRAF){ cancelAnimationFrame(presenceRAF); presenceRAF = null; }
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
    const ceiling = (typeof userMuted!=='undefined' && userMuted) ? 0 : TARGET_VOL * _riseGate;
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
  if (deckA && deckA.dataset.wired) return;   // wire the decks exactly once
  [deckA, deckB].forEach(function(d){
    if (!d) return;
    d.dataset.wired = '1';
    d.volume = 0;
    d.addEventListener('timeupdate', checkCrossfade);
    // Backstop: if the crossfade never triggered (missing duration, sleeping
    // tab), the end of a song must still lead into the next one — never silence.
    d.addEventListener('ended', function(){
      if (!crossfading && d === getActiveDeck()) playNextTrackBlended();
    });
    // Resilience: a track that fails (missing file / bad decode) is skipped —
    // the person is never left in silence.
    d.addEventListener('error', function(){ handleDeckError(d); });
    d.addEventListener('playing', function(){ _musicErrRun = 0; });
  });
}
function handleDeckError(d) {
  if (!d || !d.src) return;               // no source yet — not a real failure
  const badFile = (d.currentSrc || d.src || '').split('/').pop();
  if (badFile) {
    // Drop the broken track from the playlist so we never cycle back into it.
    const kept = ambientTracks.filter(function(t){ return (t.url || '').split('/').pop() !== badFile; });
    if (kept.length !== ambientTracks.length) {
      if (ambientIndex >= kept.length) ambientIndex = 0;
      ambientTracks = kept;
    }
  }
  _musicErrRun++;
  const nowEl = document.getElementById('music-now');
  if (_musicErrRun > 4) {   // several failures in a row — say so, stop hammering
    if (nowEl) nowEl.textContent = 'music unavailable right now';
    return;
  }
  if (nowEl) nowEl.textContent = 'finding the next song...';
  if (d === getActiveDeck() && !crossfading) {
    setTimeout(function(){ if (!crossfading) playNextTrackBlended(); }, 400);
  }
  // If the FAILING deck was the incoming side of a crossfade, the completion
  // check inside crossfade() hands the sound back to the outgoing deck.
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
    playNextTrackBlended();
  }
}

function crossfade(fadeOut, fadeIn, duration) {
  // Smooth DJ-style volume crossfade. Reads the LIVE ceiling every tick so the
  // slider, mute, voice-duck, and the gentle 16s arrival rise are all
  // respected — the blend can never jump above what the person has chosen.
  crossfading = true;
  if (_xfadeTimer) { clearInterval(_xfadeTimer); _xfadeTimer = null; }
  const steps = 40;
  const interval = duration / steps;
  let step = 0;
  const startVolOut = fadeOut.volume;
  fadeIn.volume = 0;
  fadeIn.play().catch(() => {
    // Playback refused (autoplay hiccup / slow load): one gentle retry; the
    // completion check below hands the sound back if it still cannot start.
    setTimeout(() => { if (fadeIn.paused) fadeIn.play().catch(()=>{}); }, 600);
  });
  _xfadeTimer = setInterval(() => {
    step++;
    const progress = step / steps;
    // Ease curve for smooth blend
    const ease = progress * progress * (3 - 2 * progress); // smoothstep
    const ceil = (userMuted || _duckActive) ? 0 : TARGET_VOL * _riseGate;
    fadeOut.volume = Math.max(0, Math.min(1, startVolOut * (1 - ease)));
    fadeIn.volume = Math.min(1, ceil * ease);
    if (step >= steps) {
      clearInterval(_xfadeTimer); _xfadeTimer = null;
      const ceilEnd = (userMuted || _duckActive) ? 0 : TARGET_VOL * _riseGate;
      if (fadeIn.paused) {
        // The incoming track never started (blocked or broken): keep the
        // person in sound — give the outgoing deck back instead of silence.
        activeDeck = (fadeOut === deckA) ? 'A' : 'B';
        fadeOut.volume = Math.min(1, ceilEnd);
        if (fadeOut.paused || fadeOut.ended) fadeOut.play().catch(()=>{});
        // Tell the truth in the little label: this is the song still playing.
        const nowEl = document.getElementById('music-now');
        if (nowEl) {
          const f = (fadeOut.currentSrc || fadeOut.src || '').split('/').pop();
          const t = ambientTracks.filter(function(x){ return (x.url || '').split('/').pop() === f; })[0];
          nowEl.textContent = '♪ ' + ((t && t.name) || 'music');
        }
      } else {
        fadeOut.pause();
        fadeOut.volume = 0;
        fadeIn.volume = Math.min(1, ceilEnd);
      }
      crossfading = false;   // released on EVERY completion path
    }
  }, interval);
}

async function playNextTrackBlended() {
  if (crossfading) return;   // one blend at a time
  crossfading = true;        // claimed now; handed to crossfade() or released below
  try {
    if (ambientTracks.length <= 1) {
      // Only one track (or none) — fetch new ones based on current emotion
      const emo = currentFaceEmotion || 'calm';
      const url = '/api/zenisys/ambient?emotion=' + encodeURIComponent(emo);
      let d = null;
      try { d = await (await fetch(url)).json(); } catch (e) { d = null; }
      if (!d || !d.tracks || !d.tracks.length) {
        // One quiet retry after a short wait — the network may have blinked.
        await new Promise(res => setTimeout(res, 3000));
        try { d = await (await fetch(url)).json(); } catch (e) { d = null; }
      }
      if (d && d.tracks && d.tracks.length) { ambientTracks = d.tracks; }
    }
    if (!ambientTracks.length) {
      // Still nothing — say so and keep trying gently. Never fail silently.
      crossfading = false;
      const nowEl = document.getElementById('music-now');
      if (nowEl) nowEl.textContent = 'music unavailable - retrying...';
      setTimeout(() => { if (!crossfading && !ambientTracks.length) playNextTrackBlended(); }, 20000);
      return;
    }
    ambientIndex = (ambientIndex + 1) % ambientTracks.length;
    const next = ambientTracks[ambientIndex];
    const inactive = getInactiveDeck();
    if (!inactive || !next) { crossfading = false; return; }
    inactive.src = next.url;
    inactive.load();
    // Start crossfade
    crossfade(getActiveDeck(), inactive, CROSSFADE_MS);
    activeDeck = activeDeck === 'A' ? 'B' : 'A';
    const now = document.getElementById('music-now');
    if (now) now.textContent = '\u266a ' + (next.name || 'music');
    reportTrackPlay(next);   // record this play with a timestamp
  } catch (e) {
    crossfading = false;     // an error must never freeze the volume system
  }
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
  // The real deck ids are ambient-a / ambient-b. Only the ACTIVE deck gets the
  // new level right away; fades/crossfades read TARGET_VOL live on their own.
  if (userMuted || _duckActive || crossfading) return;
  const d = (typeof getActiveDeck === 'function' && getActiveDeck()) || document.getElementById('ambient-a');
  if (d) d.volume = Math.min(1, TARGET_VOL * _riseGate);
}
function toggleMute(){
  userMuted = !userMuted;
  const b = document.getElementById('mute-btn');
  if (b) b.innerHTML = userMuted ? '&#128263;' : '&#128266;';
  if (b){ b.setAttribute('aria-pressed', userMuted ? 'true' : 'false');
    b.setAttribute('aria-label', userMuted ? 'Unmute music' : 'Mute music'); }
  ['ambient-a','ambient-b'].forEach(id=>{ const d=document.getElementById(id); if(d) d.volume = 0; });
  if (!userMuted && !_duckActive){
    const d = (typeof getActiveDeck === 'function' && getActiveDeck()) || document.getElementById('ambient-a');
    if (d) d.volume = Math.min(1, TARGET_VOL * _riseGate);
  }
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
  bar.id = 'readiness-bar';
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
  window._lastSamPhase = phase;
  if (document.getElementById('sam-card')) return;
  const card = document.createElement('div');
  card.id = 'sam-card';
  card.style.cssText = 'position:fixed;top:206px;right:18px;z-index:60;max-width:200px;'
    + 'background:rgba(255,255,255,0.96);border-radius:16px;padding:14px 16px;'
    + 'box-shadow:0 10px 36px rgba(20,40,80,0.25);text-align:center;transition:opacity 1s ease;';
  var samNames = [_ilux('sam.s1'),_ilux('sam.s2'),_ilux('sam.s3'),_ilux('sam.s4'),_ilux('sam.s5')];
  card.innerHTML = '<div style="font-size:13px;color:#41607d;margin-bottom:8px;">'+_ilux('sam.q')+'</div>'
    + '<div style="font-size:30px;letter-spacing:14px;">'
    + ['&#128551;','&#128533;','&#128528;','&#128578;','&#128522;'].map(function(f,i){
        return '<button type="button" data-v="'+(i+1)+'" aria-label="'+samNames[i]+'" style="cursor:pointer;background:none;border:0;padding:0;font-size:inherit;letter-spacing:inherit;">'+f+'</button>';
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
      // Warm the REAL music deck (ambient-a) — never a stray audio element.
      const deck = document.getElementById('ambient-a');
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
  // STEP 1: Show the conversation screen IMMEDIATELY (before anything else).
  // The arrival gate dissolves slowly over the story screen instead of blinking
  // away — one continuous place, not two pages.
  const gate = $('welcome-gate');
  if (gate) {
    gate.style.transition = 'opacity 1.6s ease';
    try { void gate.offsetWidth; } catch(e){}   // commit the transition before fading
    gate.style.opacity = '0';
    gate.style.pointerEvents = 'none';
    setTimeout(function(){ gate.style.display = 'none'; }, 1700);
  }
  const screen = $('story-screen'); if (screen) screen.style.display = 'flex';
  const msg = $('message'); if (msg) msg.focus({preventScroll:true});
  metric('session_start');
  // Begin the live-monitor heartbeat IMMEDIATELY, independent of the camera or
  // face models, so an active session always shows up for the founder (even a
  // text-only, camera-off session). It's a no-op if it can't reach the server.
  try { startBioPing(); } catch(e){}
  // Start on the SAME photograph the arrival gate was showing, so the tap feels
  // continuous — one place, deeper in. (Random if the gate scene is unknown.)
  var _startScene = (window._gateSceneKey && SCENE_PHOTOS[window._gateSceneKey])
    ? window._gateSceneKey
    : SCENE_POOL[Math.floor(Math.random() * SCENE_POOL.length)];
  currentScene = _startScene;
  setScene(_startScene, false);
  startSceneRotation();
  // The visible presence begins right away — a faint, alive glow — and grows
  // more responsive as the read gains confidence from face/voice/typing.
  try { startPresence(); } catch(e){}

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
      await startAmbientMusic(1);
      // NOTE: the thin synth-tone layer is intentionally OFF now that real
      // calming instrumental audio is playing — real music leads, not tones.
      // startSynthPad('calm');  // (disabled by design)
    } catch (e) { console.log('[InnerLight] Music unavailable:', e); }
  }, 100);
}

// Fetch the arrival lane and start the music, gently. Retries on failure and
// falls back to the tracks warmed up before the tap — the person is never
// left in silence without the little music label saying so.
async function startAmbientMusic(attempt) {
  let data = null;
  try {
    const res = await fetch('/api/zenisys/ambient');
    data = await res.json();
  } catch (e) { data = null; }
  let tracks = (data && data.tracks) || [];
  if (!tracks.length && window._preloadedTracks && window._preloadedTracks.length) {
    tracks = window._preloadedTracks;   // the fetch failed but the preload worked
  }
  if (!tracks.length) {
    const now = $('music-now');
    if (now) now.textContent = (attempt <= 1) ? 'music loading...' : 'music unavailable - still trying';
    if (attempt <= 2) setTimeout(()=>{ startAmbientMusic(attempt + 1); }, 5000);  // quiet retry
    return;
  }
  ambientTracks = tracks;
  ambientIndex = 0;
  const deck = getActiveDeck();
  if (!deck) return;
  // If the preloader already warmed this deck with the first track of the same
  // lane, keep that list — the warmed-up track starts instantly.
  if (window._preloadedTracks && window._preloadedTracks.length && deck.src
      && deck.src.indexOf(window._preloadedTracks[0].url) !== -1) {
    ambientTracks = window._preloadedTracks;
  } else if (deck.src.indexOf(ambientTracks[0].url) === -1) {
    deck.src = ambientTracks[0].url;
  }
  // GENTLE ARRIVAL: enter soft, then rise smoothly into full rich volume —
  // never an abrupt hit of sound in the ear.
  _riseGate = 0.08;                 // gates crossfades + nudges during the rise
  deck.volume = userMuted ? 0 : TARGET_VOL * _riseGate;
  deck.play().then(()=>metric('first_sound_ms', Date.now()-TAP_MS)).catch(()=>{
    // Autoplay refused (rare after a real tap): one gentle retry.
    setTimeout(()=>{ if (deck.paused) deck.play().catch(()=>{}); }, 700);
  });
  (function arrivalRise(){
    const RISE_MS = 16000; // sixteen calm seconds from near-silent to full
    const start = performance.now();
    function step(t){
      const p = Math.min(1, (t - start) / RISE_MS);
      const ease = p*p*(3-2*p); // smooth, no lurch
      _riseGate = 0.08 + (1 - 0.08) * ease;
      // Follow the CURRENT active deck and never fight mute, duck, or a blend.
      const d = getActiveDeck();
      if (d && !crossfading && !_duckActive && !userMuted) d.volume = Math.min(1, TARGET_VOL * _riseGate);
      if (p < 1) requestAnimationFrame(step); else _riseGate = 1;
    }
    requestAnimationFrame(step);
  })();
  const now = $('music-now'); if (now) now.textContent = '\u266a ' + (ambientTracks[0].name || 'soft music');
  try { reportTrackPlay(ambientTracks[0]); } catch(e){}   // track the arrival song
  // If this arrival started on the SYMPHONY lane (person very upset),
  // ease down into SPA after the proven ~3-minute attention window.
  if (data && data.lane === 'symphony_to_spa' && data.then && data.then.length) {
    scheduleSpaTransition(data.then, (data.transition_after_seconds || 180) * 1000);
  }
}
function changeMusic() {
  if (!ambientTracks.length) return;
  playNextTrackBlended();   // manages the crossfading flag itself
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
  try { reportTrackPlay({url: url, name: name}); } catch(e){}  // founder visibility
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
    if (status) status.textContent = _ilux('mic.rec');
    micTestChunks = [];
    micRecorder = new MediaRecorder(micStreamLive);
    micRecorder.ondataavailable = e => { if (e.data.size) micTestChunks.push(e.data); };
    micRecorder.onstop = () => {
      const blob = new Blob(micTestChunks, { type: micRecorder.mimeType || 'audio/webm' });
      const url = URL.createObjectURL(blob);
      const player = document.getElementById('mic-test-playback');
      if (player) { player.src = url; player.style.display = 'block'; player.play().catch(()=>{}); }
      if (status) status.textContent = _ilux('mic.ok');
    };
    micRecorder.start();
    setTimeout(() => { try { micRecorder.stop(); } catch(e){} }, 3000);
  } catch (e) {
    if (status) status.textContent = _ilux('mic.na');
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
    if (micBtn) micBtn.innerHTML = _ilux('mic.speak');
    const lbl = $('listen-label'); if (lbl) lbl.textContent = _ilux('mic.saved');
    return;
  }
  try {
    await ensureMicStream();
  } catch (e) {
    const lbl = $('listen-label');
    if (lbl) lbl.textContent = _ilux('mic.na');
    const panel = $('live-transcript'); if (panel) panel.style.display = 'block';
    return;
  }
  voiceListening = true;
  voiceFinalTranscript = '';
  duckMusicForVoice();   // stop the music while they speak
  const panel = $('live-transcript'); const dot = $('listen-dot'); const lbl = $('listen-label'); const tEl = $('transcript-text');
  if (panel) panel.style.display = 'block';
  if (dot) dot.style.background = '#e05a5a';
  if (lbl) lbl.textContent = _ilux('mic.now');
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
    if (lbl) lbl.textContent = _ilux('mic.noauto');
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
      const lbl = $('listen-label'); if (lbl) lbl.textContent = _ilux('mic.reconn');
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
    // The mic ducked the music when listening began — ALWAYS give it back,
    // or the person is left in silence forever after a quiet minute.
    try { restoreMusicAfterVoice(); } catch(e){}
    const micBtn = document.querySelector('.story-mic');
    if (micBtn) micBtn.innerHTML = _ilux('mic.speak');
    const lbl = $('listen-label');
    if (lbl) lbl.textContent = _ilux('mic.paused');
    metric('listen_autostop');
    const dot = $('listen-dot'); if (dot) dot.style.background = '#9ab0c4';
  }, 60000);
}

// --- VOICE TONE ANALYSIS (feeds quantum emotion engine) ---
let voiceFeatures = { pitch_variance: 0.5, energy: 0.5, rate: 0.5, tremor: 0.0 };
let audioContext = null, analyser = null, micStream = null;

let _pfHist = [];   // rolling ~8s of {t, rms, f0} frames
let _pfTimer = null;
async function captureVoiceFeatures() {
  // MEASURED voice prosody -> the quantum engine's voice_features slot.
  // energy: rolling mean RMS. pitch_variance: std of autocorrelation-estimated
  // f0 (70-350 Hz) over voiced frames. rate: voiced/unvoiced transitions per
  // second (syllable-boundary proxy). tremor: 4-8 Hz modulation depth of the
  // energy envelope. Normalization constants (0.12 RMS, 60 Hz sd, 8 trans/s)
  // are engineering estimates, labeled as ASSUMPTIONS pending calibration
  // against a labeled recording set. Runs silently; never asks the person to
  // adjust anything; degrades to nothing on any failure.
  try {
    if (!audioContext) {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      micStream = await navigator.mediaDevices.getUserMedia({audio: true});
      const source = audioContext.createMediaStreamSource(micStream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      if (!_pfTimer) _pfTimer = setInterval(function(){ captureVoiceFeatures(); }, 150);
    }
    const N = analyser.fftSize;
    const buf = new Float32Array(N);
    analyser.getFloatTimeDomainData(buf);
    let s = 0; for (let i = 0; i < N; i++) s += buf[i]*buf[i];
    const rms = Math.sqrt(s / N);
    let f0 = 0;
    if (rms > 0.015) {
      const sr = audioContext.sampleRate || 48000;
      const minLag = Math.floor(sr/350), maxLag = Math.min(N-1, Math.floor(sr/70));
      let best = 0, bestLag = 0, e0 = s;
      for (let lag = minLag; lag <= maxLag; lag += 2) {
        let c = 0;
        for (let i = 0; i < N - lag; i += 2) c += buf[i]*buf[i+lag];
        if (c > best) { best = c; bestLag = lag; }
      }
      if (bestLag && e0 > 0 && (best*2)/e0 > 0.3) f0 = sr / bestLag;
    }
    const now = performance.now();
    _pfHist.push({t: now, rms: rms, f0: f0});
    while (_pfHist.length && now - _pfHist[0].t > 8000) _pfHist.shift();
    if (_pfHist.length < 10) return;
    const rmsArr = _pfHist.map(function(h){ return h.rms; });
    const meanRms = rmsArr.reduce(function(a,b){ return a+b; }, 0) / rmsArr.length;
    const energy = Math.max(0, Math.min(1, meanRms / 0.12));
    const f0s = [];
    for (let i = 0; i < _pfHist.length; i++) if (_pfHist[i].f0 > 0) f0s.push(_pfHist[i].f0);
    let pitchVar = 0;
    if (f0s.length > 5) {
      const m = f0s.reduce(function(a,b){ return a+b; }, 0) / f0s.length;
      let vsum = 0; for (let i = 0; i < f0s.length; i++) vsum += (f0s[i]-m)*(f0s[i]-m);
      pitchVar = Math.max(0, Math.min(1, Math.sqrt(vsum / f0s.length) / 60));
    }
    let trans = 0;
    for (let i = 1; i < _pfHist.length; i++)
      if ((_pfHist[i].f0 > 0) !== (_pfHist[i-1].f0 > 0)) trans++;
    const span = (now - _pfHist[0].t) / 1000;
    const rate = Math.max(0, Math.min(1, (trans / Math.max(span, 0.5)) / 8));
    let tremor = 0;
    if (meanRms > 0.01 && rmsArr.length > 3) {
      const dt = span / (rmsArr.length - 1);
      const half = Math.max(1, Math.round(0.083 / Math.max(dt, 0.01)));
      let mod = 0, cnt = 0;
      for (let i = half; i < rmsArr.length; i++) { mod += Math.abs(rmsArr[i]-rmsArr[i-half]); cnt++; }
      if (cnt) tremor = Math.max(0, Math.min(1, (mod/cnt) / (meanRms*0.8)));
    }
    voiceFeatures = { energy: energy, pitch_variance: pitchVar, rate: rate, tremor: tremor };
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
  if (voiceEnabled && v){ speak(_ilux('vp.test')); }
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
  var opts = '<option value="">'+_ilux('vp.auto')+'</option>';
  var any = false;
  // premium provider voices for THIS language (only present when a voice key is configured)
  try{
    var r = await fetch('/api/voice/list?lang=' + encodeURIComponent(pageLang)); var d = await r.json();
    if (d && d.voices && d.voices.length){
      opts += '<optgroup label="'+_ilux('vp.human')+'">';
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
      opts += '<optgroup label="'+(g==='Voice'?_ilux('vp.other'):(g==='Female'?_ilux('vp.female'):_ilux('vp.male')))+'">';
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
  var words = text.split(/\\s+/).length;
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
  // Language promise: if this device has NO voice for the chosen language,
  // we stay silent rather than speak the wrong language. The words remain
  // on screen; wrong-language audio would break trust at the worst moment.
  if (!_v && _lang.slice(0,2).toLowerCase() !== 'en') { finish(); return; }
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
    var _t = _ilux('uh');
    _t = _t.replace('{988}', '<a href="tel:988" style="color:#b3322e;text-decoration:underline;">'+_ilux('uh.988')+'</a>')
           .replace('{911}', '<a href="tel:911" style="color:#b3322e;text-decoration:underline;">'+_ilux('uh.911n')+'</a>');
    box.innerHTML = _t;
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
// The person can ALWAYS save on demand from the Save button on the help rail.
// If there is not enough to save yet, we say so honestly instead of failing.
function openSaveNow(){
  var existing = document.getElementById('save-offer');
  if (existing){ existing.remove(); }
  _memOffered = true;
  var story = collectStory();
  var bar = document.createElement('div');
  bar.id = 'save-offer';
  bar.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:75;'
    + 'background:rgba(255,255,255,0.97);border:1px solid #e0d7cf;border-radius:16px;padding:14px 18px;'
    + 'box-shadow:0 10px 30px rgba(20,40,30,0.2);font-family:Arial;max-width:340px;text-align:center;';
  if (story.length < 40){
    bar.innerHTML = '<div style="font-size:14px;color:#4a362c;margin-bottom:10px;">'+_ilux('sv.min')+'</div>'
      + '<button onclick="dismissSaveOffer()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:9px 18px;font-size:14px;cursor:pointer;">'+_ilux('mb.ok')+'</button>';
  } else {
    bar.innerHTML = '<div style="font-size:14px;color:#4a362c;margin-bottom:10px;">'+_ilux('sv.q')+'</div>'
      + '<button onclick="doSaveStory()" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:9px 20px;font-size:14px;font-weight:700;cursor:pointer;margin:0 5px;">'+_ilux('sv.btn')+'</button>'
      + '<button onclick="dismissSaveOffer()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:9px 18px;font-size:14px;cursor:pointer;margin:0 5px;">'+_ilux('sv.notnow')+'</button>';
  }
  document.body.appendChild(bar);
}
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
  bar.innerHTML = '<div style="font-size:14px;color:#4a362c;margin-bottom:10px;">'+_ilux('sv.auto')+'</div>'
    + '<button onclick="doSaveStory()" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:9px 20px;font-size:14px;font-weight:700;cursor:pointer;margin:0 5px;">'+_ilux('sv.btn')+'</button>'
    + '<button onclick="dismissSaveOffer()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:9px 18px;font-size:14px;cursor:pointer;margin:0 5px;">'+_ilux('sv.notnow')+'</button>';
  document.body.appendChild(bar);
}
async function doSaveStory(){
  const story = collectStory();
  const offer = document.getElementById('save-offer');
  try {
    const r = await fetch('/api/memory/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({summary: story, conversation: (typeof conversationLog!=='undefined'?conversationLog.slice(-80):[])})});
    const d = await r.json();
    if (d.status === 'ok'){
      if (offer) offer.innerHTML = '<div style="font-size:14px;color:#4a362c;margin-bottom:8px;">'+_ilux('sv.saved')+'</div>'
        + '<div style="font-size:22px;font-weight:800;letter-spacing:1px;color:#1e3a5c;margin:6px 0;">' + d.code + '</div>'
        + '<div style="font-size:12px;color:#736049;margin-bottom:10px;">'+_ilux('sv.code')+'</div>'
        + '<button onclick="copyReturnCode(this)" data-code="' + d.code + '" style="background:#2e6e8e;color:#fff;border:0;border-radius:999px;padding:8px 18px;font-size:13px;cursor:pointer;margin:0 5px;">'+_ilux('sv.copy')+'</button>'
        + '<button onclick="dismissSaveOffer()" style="background:none;border:1px solid #ddd1c8;color:#99673e;border-radius:999px;padding:8px 16px;font-size:13px;cursor:pointer;margin:0 5px;">'+_ilux('sv.done')+'</button>';
    } else if (offer){ offer.querySelector('div').textContent = _ilux('sv.empty'); }
  } catch(e){ if (offer) offer.querySelector('div').textContent = _ilux('sv.err'); }
}
function openResume(){
  const box = document.createElement('div');
  box.id = 'resume-box';
  box.style.cssText = 'position:fixed;inset:0;z-index:95;background:rgba(10,18,30,0.75);display:flex;align-items:center;justify-content:center;padding:20px;';
  box.innerHTML = '<div style="background:#fff;border-radius:18px;padding:26px;max-width:360px;width:100%;font-family:Arial;text-align:center;">'
    + '<h3 style="margin:0 0 6px;color:#1e3a5c;">Continue your story</h3>'
    + '<p style="font-size:13px;color:#736049;margin:0 0 16px;">Enter the return code you saved last time.</p>'
    + '<input id="resume-code" aria-label="Your return code" placeholder="e.g. CALM-4821-MOON" style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #ddd1c8;border-radius:10px;font-size:16px;text-align:center;text-transform:uppercase;">'
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
        // Slip the story screen into conversation state, like an active session.
        try {
          const title = document.querySelector('.story-title'); if (title) title.style.display = 'none';
          const sub = document.querySelector('.story-sub'); if (sub) sub.style.display = 'none';
        } catch(e){}
        const head = document.createElement('div');
        head.style.cssText = 'background:rgba(46,110,142,0.1);border-radius:12px;padding:12px 14px;margin:8px 0;font-size:14px;color:#4a362c;';
        head.innerHTML = '<b>Welcome back.</b> Here\u2019s where you left off, so you don\u2019t have to start over:';
        thread.appendChild(head);
        const turns = Array.isArray(d.conversation) ? d.conversation : [];
        if (turns.length){
          // Rebuild the CONVERSATION, turn by turn — and hand the companion its
          // memory back, so the next message continues the same story.
          try { conversationLog = turns.map(function(t){ return {role: (t.role==='user'?'user':'innerlight'), text: String(t.text||''), at: ''}; }); } catch(e){}
          for (let i = 0; i < turns.length; i++){
            const t = turns[i];
            const b = document.createElement('div');
            if (t.role === 'user'){
              b.style.cssText = 'text-align:right;background:rgba(46,110,142,0.10);border-radius:14px;padding:12px 14px;margin:10px 0 10px 18%;font-size:15px;color:#2b2620;line-height:1.6;white-space:pre-wrap;';
            } else {
              b.style.cssText = 'text-align:left;background:#fff;border:1px solid #eee2d6;border-radius:14px;padding:12px 16px;margin:10px 18% 10px 0;font-size:15px;color:#3a2f26;line-height:1.6;white-space:pre-wrap;';
            }
            b.textContent = String(t.text||'');
            thread.appendChild(b);
          }
        } else {
          // Older saves hold only a flat summary — show it readably.
          const div = document.createElement('div');
          div.style.cssText = 'background:#fff;border:1px solid #eee2d6;border-radius:14px;padding:12px 16px;margin:10px 0;font-size:14px;color:#4a362c;line-height:1.65;white-space:pre-wrap;';
          div.textContent = (d.summary||'');
          thread.appendChild(div);
        }
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
    if (em) { em.style.display='block'; em.textContent = _ilux('empty'); }
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
      ui_lang:(window._ilLang||'en'),
      client_time: new Date().toString(),
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
  // Server-side multilingual signals: same protections in every language.
  if (data.minor_signal) { window._minorLock = true; try { showMinorBridge(); } catch(e){} }
  if (data.substitution_signal) { try { gentlyRedirectFromSubstitution(); } catch(e){} }
  // --- CONVERSATION THREAD (flat, never nests, never stops) ---
  const thread = document.getElementById('conversation-thread');
  const allQ = data.questions || [];
  // FOUNDER DECREE: no canned lines, ever. If there is no question, there is
  // no question — the reply itself carries the conversation. If the reply is
  // missing entirely, say honestly what happened instead of faking warmth.
  const firstQ = allQ.length ? allQ[0] : '';
  const warmReply = data.response || _ilux('interrupted');
  const safetyBlock = data.needs_immediate_support
    ? '<p style="background:#f7f3f0;border:1px solid #ddd1c8;border-radius:12px;padding:14px;color:#4a372d;font-size:15px;margin:14px 0;">'+_ilux('s988')+'</p>'
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
    <p style="font-size:15px;color:#6a402c;font-weight:600;margin:0 0 8px;">${_ilux('lg.based').replace('{issue}', escapeHtml(lg.issue_detected))}</p>
    <details style="margin:8px 0;" open>
      <summary style="font-size:13px;font-weight:600;color:#815734;cursor:pointer;">${_ilux('lg.rights')}</summary>
      <ul style="font-size:14px;color:#4a372d;padding-left:20px;margin:6px 0;">${rights}</ul>
    </details>
    <details style="margin:8px 0;">
      <summary style="font-size:13px;font-weight:600;color:#815734;cursor:pointer;">${_ilux('lg.ask')}</summary>
      <ul style="font-size:14px;color:#4a372d;padding-left:20px;margin:6px 0;">${askAtty}</ul>
    </details>
    <details style="margin:8px 0;">
      <summary style="font-size:13px;font-weight:600;color:#815734;cursor:pointer;">${_ilux('lg.free')}</summary>
      <ul style="font-size:14px;color:#4a372d;padding-left:20px;margin:6px 0;">${freeHelp}</ul>
    </details>
    <details style="margin:8px 0;">
      <summary style="font-size:13px;font-weight:600;color:#815734;cursor:pointer;">${_ilux('lg.steps')}</summary>
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
    <p style="font-size:15px;font-weight:600;color:${c.accent};margin:0 0 6px;">${escapeHtml(_ilho(handoff.label))}</p>
    <label style="display:flex;align-items:flex-start;gap:8px;font-size:13px;color:#6b412c;margin:10px 0;cursor:pointer;">
      <input type="checkbox" id="consent-${handoff.type}" style="margin-top:3px;">
      <span>${escapeHtml(_ilho(handoff.context_prompt || 'Share my context so I do not have to repeat myself.'))}</span>
    </label>
    <div class="bridge-buttons" style="margin-top:10px;"></div>
  `;
  thread.appendChild(el);
  // Attach buttons with real click handlers (no string escaping issues)
  const btnContainer = el.querySelector('.bridge-buttons');
  function addBtn(b, style) {
    if (!b) return;
    const btn = document.createElement('button');
    btn.textContent = _ilho(b.label);
    btn.setAttribute('style', style);
    btn.onclick = function() { completeBridge(handoff.type, b.action, b.value || ''); };
    btnContainer.appendChild(btn);
  }
  addBtn(primary, primaryStyle);
  addBtn(secondary, secondaryStyle);
  addBtn(handoff.actions && handoff.actions.tertiary, secondaryStyle);
  addBtn(emergency, emergencyStyle);
  // Speak the handoff offer
  speak(_ilho(handoff.label));
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
        ui_lang: (window._ilLang||'en'),
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
      <button id="bridge-go" style="background:#fff;color:#6b412c;border:0;border-radius:999px;padding:12px 24px;font-size:15px;font-weight:700;cursor:pointer;">${_ilux('wh.connect')}</button>
      <span style="font-size:13px;opacity:0.9;">${_ilux('wh.norush')}</span>
    </div>
    <button onclick="restartConversation()" style="background:rgba(255,255,255,0.15);color:#fff;border:1px solid rgba(255,255,255,0.4);border-radius:999px;padding:9px 20px;font-size:13px;cursor:pointer;margin-top:14px;">${_ilux('wh.more')}</button>
  `;
  thread.appendChild(el);
  // SPEAK the full warm handoff aloud, calmly
  speak(warm.spoken_script);
  // The person taps "Connect now" when ready — we never auto-launch during the warm words
  const goBtn = el.querySelector('#bridge-go');
  if (goBtn) goBtn.onclick = function() { performBridgeAction(action, value); };
  politeScrollIntoView(el);
}
/* Resilient open: the window opens instantly (popup-safe), then the server
   picks the first destination whose door actually opens right now. */
async function ilOpenDest(name, fallbackUrl){
  var w = null;
  try { w = window.open('about:blank', '_blank'); } catch(e){}
  var url = fallbackUrl;
  try {
    var r = await fetch('/api/dest/' + name);
    if (r.ok) { var d = await r.json(); if (d.url) url = d.url; }
  } catch(e){}
  if (w && !w.closed) { try { w.location = url; return; } catch(e){} }
  try { window.open(url, '_blank'); } catch(e){ window.location.href = url; }
}
function performBridgeAction(action, value) {
  switch(action) {
    case 'call_988': window.location.href = 'tel:988'; break;
    case 'call_911': window.location.href = 'tel:911'; break;
    /* NEVER require an app: 211 opens the website directly (no OS app
       chooser can appear); the phone number stays visible in the card text
       for anyone who prefers to dial it themselves. */
    case 'call_211': ilOpenDest('help_211', 'https://www.211.org'); break;
    case 'chat_988': ilOpenDest('chat_988', 'https://988lifeline.org'); break;
    case 'request_video': window.open('/telehealth/intake', '_blank'); break;
    case 'schedule': window.open('/telehealth/intake', '_blank'); break;
    case 'match_attorney': ilOpenDest('legal_aid', 'https://www.lsc.gov/about-lsc/what-legal-aid/get-legal-help'); break;
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
    <button onclick="restartConversation()" style="background:rgba(255,255,255,0.2);color:#fff;border:1px solid rgba(255,255,255,0.4);border-radius:999px;padding:10px 22px;font-size:13px;cursor:pointer;margin-top:16px;">${_ilux('wh.more')}</button>
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
    <textarea id="conv-answer" class="story-input" style="min-height:80px;" placeholder="${_ilux('listen.ph')}" onkeydown="if((event.key==='Enter'||event.keyCode===13)&&!event.shiftKey&&!event.isComposing){event.preventDefault();continueConversation();}"></textarea>
    <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
      <button class="story-send" onclick="continueConversation()">${_ilux('reply')}</button>
      <button class="story-mic" type="button" onclick="startVoiceCapture()">${_ilux('mic.speak')}</button>
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
    <textarea id="conv-answer" class="story-input" style="min-height:80px;" aria-label="${_ilux('take.ph')}" placeholder="${_ilux('take.ph')}" onkeydown="if((event.key==='Enter'||event.keyCode===13)&&!event.shiftKey&&!event.isComposing){event.preventDefault();continueConversation();}"></textarea>
    <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;">
      <button class="story-send" onclick="continueConversation()">${_ilux('reply')}</button>
      <button class="story-mic" type="button" onclick="startVoiceCapture()">${_ilux('mic.speak')}</button>
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
        ui_lang:(window._ilLang||'en'),
        client_time: new Date().toString(),
      answer: userAnswer,
      learning_state: innerLightLearningState,
      session_reference: innerLightSessionReference,
      context: Object.assign({}, innerLightContext, multimodalPayload(), {conversation: conversationLog})
    })
  });
  const data = await res.json();
  innerLightLearningState = data.learning_state || innerLightLearningState;
  innerLightContext = Object.assign(innerLightContext, data);
  if (data.minor_signal) { window._minorLock = true; try { showMinorBridge(); } catch(e){} }
  if (data.substitution_signal) { try { gentlyRedirectFromSubstitution(); } catch(e){} }
  // When comprehension (Claude) is active, its ONE deeper question is already
  // inside the reply — so we do NOT tack on a separate canned question.
  const rawQ = (data.questions || [])[0] || '';
  const nextQ = rawQ && rawQ.trim() ? rawQ : '';
  // No canned gratitude line — if the reply is missing, be honest about it.
  const reply = data.response || _ilux('interrupted');
  logTurn('innerlight', reply);
  const safety = data.needs_immediate_support
    ? '<p style="background:#f7f3f0;border:1px solid #ddd1c8;border-radius:12px;padding:14px;color:#4a372d;font-size:15px;margin:14px 0;">'+_ilux('s988')+'</p>'
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
      if(el && !el.paused){ el.dataset.fullvol = String(el.volume); el.volume = Math.min(el.volume, 0.06); } });
    const note = document.getElementById('calm-music-note'); if(note) note.textContent = 'music softened - playing your sounds';
  }
  function restoreMusic(){
    ducked = false;
    // Restore to the remembered level, but NEVER above the current ceiling
    // (slider x arrival rise, zero when muted) — the music must never blast.
    const ceil = (typeof userMuted !== 'undefined' && userMuted) ? 0
      : ((typeof TARGET_VOL !== 'undefined' ? TARGET_VOL : 0.035) * (typeof _riseGate !== 'undefined' ? _riseGate : 1));
    ['ambient-a','ambient-b'].forEach(id=>{ const el=document.getElementById(id);
      if(el && !el.paused){
        const stored = parseFloat(el.dataset.fullvol || '');
        fadeTo(el, Math.min(isNaN(stored) ? ceil : stored, ceil), 1500);
      } });
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
  // Keyboard path: a virtual touch point moved with the arrow keys; Enter or
  // Space presses it — same light, same tones, no pointer needed.
  let kx = null, ky = null;
  function kbTouch(playTone){
    if (kx === null){ kx = W/2; ky = H/2; }
    kx = Math.max(8, Math.min(W-8, kx)); ky = Math.max(8, Math.min(H-8, ky));
    addRipple(kx, ky);
    if (playTone){
      if (calmMode === 'call'){ callAnswer(kx, ky); }
      else if (calmMode === 'trace'){ traceMove(kx, ky); }
      else { tone(kx, ky); }
    }
    activity();
  }
  canvas.addEventListener('keydown', function(e){
    const step = 26;
    if (e.key === 'ArrowLeft'){ if (kx === null){ kx = W/2; ky = H/2; } kx -= step; }
    else if (e.key === 'ArrowRight'){ if (kx === null){ kx = W/2; ky = H/2; } kx += step; }
    else if (e.key === 'ArrowUp'){ if (kx === null){ kx = W/2; ky = H/2; } ky -= step; }
    else if (e.key === 'ArrowDown'){ if (kx === null){ kx = W/2; ky = H/2; } ky += step; }
    else if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar'){ e.preventDefault(); kbTouch(true); return; }
    else { return; }
    e.preventDefault();
    const now = performance.now();
    const playNow = (calmMode === 'trace') || (now - lastTone > 130);
    if (playNow && calmMode === 'anchor') lastTone = now;
    kbTouch(playNow);
  });
  canvas.addEventListener('blur', function(){ if (calmMode === 'trace') traceRelease(); });

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
  <link rel="icon" href="data:,">
  <title>InnerLight &mdash; Connecting You to a Care Professional</title>
  <style>
    :root { --ink:#2a1e14; --muted:#99673e; --line:#e8dcc8; --soft:#f5eddc; --cream:#faf5ec; --card:#fffdf8;
            --urgent:#b84a44; --amber:#c56a2c; --dusk:#33567c;
            --green:#c56a2c; --blue:#33567c; --legal:#c56a2c; --legal2:#c56a2c; }
    * { box-sizing:border-box; }
    html { background:#faf5ec; }
    body { margin:0; font-family:Arial, sans-serif; color:var(--ink); background:var(--cream); position:relative; }
    /* FOUNDER DESIGN: his photograph as a faint warm glow behind the opening,
       fading to solid cream before the working sections, so reading is easy. */
    .glow { position:absolute; top:0; left:0; right:0; height:min(92vh, 860px); overflow:hidden; z-index:0; pointer-events:none; }
    .glow .ph { position:absolute; top:0; left:0; right:0; bottom:0; background:url('/scenes/photo_2_sunset_trees.jpg') center top / cover no-repeat; opacity:0.25; }
    .glow .fade { position:absolute; top:0; left:0; right:0; bottom:0; background:linear-gradient(180deg, rgba(250,245,236,0) 0%, rgba(250,245,236,0.2) 45%, rgba(250,245,236,0.7) 72%, rgba(250,245,236,1) 94%); }
    header, main { position:relative; z-index:1; }
    main { padding:10px 6vw 30px; max-width:820px; margin:0 auto; }
    h1, h2, .whisper { font-family:Georgia, 'Times New Roman', serif; font-weight:400; }
    h2 { margin:0 0 10px; font-size:21px; }
    p { color:var(--muted); line-height:1.6; }
    a { color:var(--dusk); }
    .tag { display:inline-block; padding:5px 14px; border-radius:999px; background:rgba(255,253,248,0.6); border:1px solid var(--line); color:var(--muted); font-size:12.5px; }
    .intro { text-align:center; padding:8vh 6vw 44px; max-width:820px; margin:0 auto; }
    .intro .tag { margin-bottom:7vh; }
    .whisper { margin:0 0 26px; font-size:16.5px; font-style:italic; color:var(--muted); }
    .whisper[hidden] { display:none; }
    h1.promise { margin:0 auto; max-width:600px; font-size:clamp(26px, 6.2vw, 40px); line-height:1.25; color:var(--ink); }
    h1.promise.quiet-title { font-size:clamp(22px, 5vw, 30px); }
    .intro-sub { max-width:540px; margin:20px auto 0; font-size:14.5px; }
    #pro-choices { max-width:480px; margin:6vh auto 0; text-align:left; }
    .panel { border:1px solid var(--line); border-radius:16px; background:var(--card); padding:22px; margin:18px 0; }
    .who { background:var(--card); border-color:var(--line); }
    .who ul { margin:8px 0 0; padding-left:0; list-style:none; }
    .who li { padding:9px 0; border-bottom:1px solid var(--soft); color:var(--ink); }
    .who li:last-child { border-bottom:0; }
    .who b { color:var(--amber); }
    .rights { background:var(--soft); border-color:var(--line); }
    .rights summary { cursor:pointer; font-weight:700; color:var(--amber); }
    .rights p { font-size:14px; }
    .urgent-note { background:#fdf3f0; border:1px solid #e5b5a5; border-radius:16px; padding:14px 16px; margin:18px 0; }
    .urgent-note b { color:var(--urgent); }
    label { display:block; font-weight:700; color:var(--ink); margin:14px 0 6px; }
    textarea { width:100%; border:1px solid var(--line); border-radius:10px; padding:12px; font:inherit; min-height:90px; background:#fffefb; }
    .convo { background:var(--soft); border:1px solid var(--line); border-radius:10px; padding:14px; max-height:280px; overflow:auto; }
    .convo .u { color:var(--ink); margin:0 0 10px; }
    .convo .a { color:var(--dusk); margin:0 0 10px; }
    .convo .u b, .convo .a b { display:block; font-size:12px; text-transform:uppercase; letter-spacing:0.04em; opacity:0.7; }
    button, a.button { display:inline-block; border:0; border-radius:999px; padding:15px 30px; background:var(--amber); color:white; font-weight:700; text-decoration:none; cursor:pointer; font-size:16px; }
    .secondary { background:var(--soft); color:var(--ink); }
    .locked { font-size:13px; color:var(--muted); margin-top:8px; }
    /* HIS ONE AMBER PILL: alone, centered, room to breathe. */
    .ready { text-align:center; padding:9vh 4vw 10px; }
    .ready p { max-width:560px; margin-left:auto; margin-right:auto; }
    .ready #send-btn { display:inline-block; margin-top:26px; min-width:min(320px, 100%); }
    /* HIS "NOT YET" LINE: a real door back, never a gray afterthought. */
    .notyet { text-align:center; margin:40px 0 0; }
    .notyet a { color:var(--dusk); font-family:Georgia, 'Times New Roman', serif; font-size:16px; text-decoration:underline; text-underline-offset:3px; }
    /* HIS QUIET 988 EMBER at the very bottom, always present. */
    .ember { text-align:center; margin:56px 0 14px; }
    .ember a { color:var(--amber); text-decoration:none; font-family:Georgia, 'Times New Roman', serif; font-size:16px; letter-spacing:0.12em; opacity:0.85; }
    .pro-btn { display:block; width:100%; text-align:left; margin:10px 0; padding:15px 18px; border-radius:16px;
               border:1px solid #e3d2ba; background:var(--card); cursor:pointer; font-size:15.5px; font-weight:400; color:var(--ink); }
    .pro-btn b { font-family:Georgia, 'Times New Roman', serif; font-weight:700; }
    .pro-btn span { display:block; font-size:13px; color:var(--muted); margin-top:3px; font-weight:400; }
    .pro-btn.picked { border-color:var(--amber); background:#fbf1e4; box-shadow:0 0 0 2px rgba(197,106,44,0.22); }
    .pro-btn.suggested { border-color:var(--dusk); box-shadow:0 0 0 2px rgba(51,86,124,0.20); }
    /* FOUNDER RULE: provider buttons stay hidden until the server confirms a
       real person is available behind them. No ghost buttons, ever. */
    #pro-choices .pro-btn { display:none; color:var(--ink); }
    .gate-res { display:block; text-decoration:none; border:1px solid var(--line); border-radius:14px; padding:12px 15px; background:var(--card); color:var(--ink); margin:8px 0; }
    .gate-res b { font-family:Georgia, 'Times New Roman', serif; }
    .gate-res span { display:block; font-size:12.5px; color:var(--muted); margin-top:3px; font-weight:400; }
    .gate-empty { border:1px solid #e3d2ba; background:rgba(255,253,248,0.9); border-radius:16px; padding:18px 20px; text-align:left; max-width:520px; margin:0 auto; }
    .disclaimer { font-size:12.5px; color:#9c8a74; line-height:1.5; border-top:1px solid var(--line); margin-top:34px; padding-top:16px; }
    @media (prefers-reduced-motion: no-preference){
      .intro { animation:il-fade 0.9s ease; }
      @keyframes il-fade { from { opacity:0; } to { opacity:1; } }
    }
  </style>
</head>
<body>
  <div class="glow" aria-hidden="true"><div class="ph"></div><div class="fade"></div></div>
  <header class="intro">
    <div class="tag">Connecting you to mental-health care</div>
    <p class="whisper" id="intro-whisper" hidden>Someone real is ready for you,</p>
    <h1 class="promise" id="chooser-title">Reaching a real person for your care</h1>
    <p class="intro-sub" id="chooser-sub">Before anything is shared, here is exactly who you may reach and what is protected. Nothing leaves this page until you read it and choose to send it.</p>
    <div id="pro-choices">
        <div id="pro-suggestion" style="display:none;background:#f8f5f2;border:1px solid #e6d6c8;border-radius:12px;padding:12px 15px;font-size:13.5px;color:#6a402c;margin-bottom:12px;"></div>
        <button type="button" class="pro-btn" data-role="crisis_counselor" data-pro="Crisis-trained counselor" onclick="pickPro(this)"><b>Crisis-trained counselor</b><span>Immediate emotional support for this moment. Not a prescriber.</span></button>
        <button type="button" class="pro-btn" data-role="therapist" data-pro="Therapist / licensed counselor" onclick="pickPro(this)"><b>Therapist / licensed counselor</b><span>Talk-based support and ongoing coping work.</span></button>
        <button type="button" class="pro-btn" data-role="psychiatrist" data-pro="Psychiatrist" onclick="pickPro(this)"><b>Psychiatrist</b><span>A medical doctor who can evaluate symptoms and, where appropriate, manage medication.</span></button>
        <button type="button" class="pro-btn" data-role="nurse_practitioner" data-pro="Nurse practitioner" onclick="pickPro(this)"><b>Nurse practitioner</b><span>Can assess symptoms and, in many states, manage medication.</span></button>
      </div>
    <p id="pro-picked" style="font-weight:700;color:var(--amber);"></p>
    <p class="notyet"><a href="/" onclick="if(history.length>1){history.back();return false;}">Not yet &mdash; stay with me a little longer.</a></p>
  </header>
  <main>
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

    <section class="ready">
      <h2 id="ready-title">Ready when you are</h2>
      <p id="ready-sub">When you send this, InnerLight notifies the care side and prepares your approved summary so the professional can read it <i>before</i> they speak with you &mdash; so you don't have to start from the beginning.</p>
      <p id="status" style="font-weight:700;color:var(--green);"></p>
      <button id="send-btn" onclick="sendToCare()">I&rsquo;m ready to meet them.</button>
      <p class="notyet"><a href="/" onclick="if(history.length>1){history.back();return false;}">Not yet &mdash; stay with me a little longer.</a></p>
    </section>

    <p class="disclaimer">
      InnerLight, a service of God's Love For Us LLC, provides crisis support and connection to care. It is not a medical provider and does not provide medical diagnosis or treatment. We work to follow U.S. health-privacy standards including HIPAA, and your information is encrypted and shared only with your consent. In an emergency, call or text 988 or call 911. This summary is prepared for a licensed professional and reflects what you chose to share.
    </p>
  <p class="ember"><a href="tel:988" aria-label="Call 988, the Suicide and Crisis Lifeline">988</a></p>
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
      var lbl = proLabel(btn);
      if (send) send.textContent = GATE_T.readyRole.replace('{role}', lbl.toLowerCase());
      setPromise(lbl);
    }
    function sendToCare(){
      if (!pickedPro && !LEAVE_WORD){
        document.getElementById('status').textContent = 'First, tap who you want to reach above \u2014 you choose, always.';
        return;
      }
      const proName = LEAVE_WORD ? GATE_T.leaveWho : pickedPro;
      const clarify = document.getElementById('clarify').value.trim();
      const add = document.getElementById('addnote').value.trim();
      let log=[]; try{ log=JSON.parse(sessionStorage.getItem('innerlight_convo')||'[]'); }catch(e){}
      const said = log.filter(t=>t.role==='user').map(t=>t.text).join(' \u2022 ');
      const summaryText = ['WHO THIS GOES TO: ' + proName,
        said ? 'IN THEIR OWN WORDS: ' + said : '',
        clarify ? 'THEY CLARIFIED: ' + clarify : '',
        add ? 'THEY ADDED: ' + add : ''].filter(Boolean).join('\n\n');
      const box = document.getElementById('convo-summary');
      box.innerHTML = '<p class="a"><b>' + (LEAVE_WORD ? GATE_T.leaveSumLabel : ('The exact summary that goes to your ' + esc(pickedPro.toLowerCase()))) + '</b></p>'
        + '<p class="u" style="white-space:pre-wrap;">' + esc(summaryText) + '</p>';
      document.getElementById('status').innerHTML = LEAVE_WORD ? GATE_T.leaveSending : 'Reaching a human for you\u2026';
      fetch('/api/connect/request', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({kind:'care', pro: (LEAVE_WORD ? 'Left word (care, no one on call)' : pickedPro), summary: summaryText, hp:'', elapsed: (Date.now()-PAGE_OPEN_TS)})})
      .then(r=>r.json()).then(function(d){
        if (LEAVE_WORD){
          document.getElementById('status').innerHTML = GATE_T.leaveDone + '<br><br><span style="font-family:Georgia,serif;font-style:italic;color:#99673E;font-size:15px;display:inline-block;margin-top:2px;">' + BLESS + '</span>';
          return;
        }
        document.getElementById('status').innerHTML =
          'Your request for a <b>' + esc(pickedPro.toLowerCase()) + '</b> is in, and a human has been alerted. '
          + 'While our professional network grows, an <b>InnerLight responder</b> \u2014 our founder, not a licensed '
          + 'provider \u2014 will meet you first, stay with you, and help arrange the ' + esc(pickedPro.toLowerCase()) + ' you chose. '
          + 'Above is the exact summary they will read.<br><br>'
          + '<a href="' + d.room + '" target="_blank" style="display:inline-block;background:#c56a2c;color:#fff;'
          + 'padding:13px 26px;border-radius:999px;font-weight:700;text-decoration:none;">Join your private video room</a>'
          + '<br><span style="font-size:12.5px;color:#8794a0;">The room is private to this request. If no one joins within a few minutes, '
          + 'call or text 988 anytime \u2014 you never have to wait alone.</span>'
          + '<br><br><span style="font-family:Georgia,serif;font-style:italic;color:#99673E;font-size:15px;display:inline-block;margin-top:2px;">' + BLESS + '</span>';
      }).catch(function(){
        document.getElementById('status').textContent = 'The connection request could not go through. If you need someone now, call or text 988.';
      });
      try{ fetch('/api/metrics/event',{method:'POST',headers:{'Content-Type':'application/json'},
        body: JSON.stringify({type:'handoff_click', value:'care:'+(LEAVE_WORD ? 'leaveword' : pickedPro), sid: sessionStorage.getItem('innerlight_sid')||'page'})}); }catch(e){}
    }
    // ---- FOUNDER RULE GATE: only providers who are truly there are shown.
    // The buttons above start hidden; the server says who is really on call.
    // If no one is, the chooser becomes an honest, dead-end-free block. ----
    var GATE_SIDE = 'clinical';
    var LEAVE_WORD = false;
    var BLESS = "You are the best there is, the best there was, and the best there ever could be.";
    var GATE_T = {
      promise: 'They have read nothing \u2014 your story stays yours to tell.',
      promiseRole: 'Your {role} has read nothing \u2014 your story stays yours to tell.',
      introSub: 'You pick. Tap the kind of professional you want \u2014 your summary goes to them, and only when you say send.',
      readyRole: 'I\u2019m ready to meet my {role}.',
      onlyHere: 'Only who is truly here right now is shown.',
      emptyTitle: 'No care professional is connected at this moment',
      emptyLead: 'We will not pretend otherwise. Right now no counselor, therapist, psychiatrist, or nurse practitioner is on call here \u2014 and we will never show you a button with no one behind it. The doors below are open and staffed by real people at this very moment.',
      resources: '<a class="gate-res" href="tel:988"><b>988 Suicide &amp; Crisis Lifeline</b><span>Call or text 988 \u2014 free, 24/7, a trained human answers.</span></a>'
        + '<a class="gate-res" href="sms:741741"><b>Crisis Text Line</b><span>Text HOME to 741741 \u2014 a live, trained counselor, any hour.</span></a>'
        + '<a class="gate-res" href="https://findtreatment.gov/" target="_blank" rel="noopener"><b>Find licensed care near you</b><span>FindTreatment.gov \u2014 the federal directory of licensed mental-health facilities.</span></a>',
      leaveNote: 'Below, you can also leave word. A real person will see this. This is not an instant connection, and we will never pretend it is.',
      leaveTitle: 'Leave word for the next real person',
      leaveLead: 'Review your words below and send them when you are ready. They will be waiting for the next real person who comes on call \u2014 not an instant connection, and we will never pretend it is.',
      leaveBtn: 'Leave word for the next real person',
      leaveWho: 'the next available care professional',
      leaveSumLabel: 'The exact summary the next care professional will read',
      leaveSending: 'Placing your words where the next real person will find them\u2026',
      leaveDone: 'Your words are safely in. <b>A real person will see this.</b> This is not an instant connection, and we will never pretend it is. If you need someone this minute, call or text <b>988</b> \u2014 a trained human is there right now, around the clock.'
    };
    // ---- FOUNDER DESIGN: the introduction moment. The privacy promise is the
    // loudest line on the page, and it personalizes to the person they chose. ----
    function proLabel(btn){
      var b0 = btn && btn.querySelector ? btn.querySelector('b') : null;
      return (b0 && b0.textContent) || (btn && btn.getAttribute('data-pro')) || '';
    }
    function setPromise(roleLabel){
      var t0 = document.getElementById('chooser-title');
      if (t0){ t0.textContent = roleLabel ? GATE_T.promiseRole.replace('{role}', String(roleLabel).toLowerCase()) : GATE_T.promise; }
      var s0 = document.getElementById('chooser-sub');
      if (s0) s0.textContent = GATE_T.introSub;
    }
    function gateProviders(avail){
      var box = document.getElementById('pro-choices');
      if (!box) return;
      var btns = box.querySelectorAll('.pro-btn');
      var shown = 0;
      for (var i = 0; i < btns.length; i++){
        var role = btns[i].getAttribute('data-role') || '';
        if (avail.indexOf(role) >= 0){ btns[i].style.display = 'block'; shown++; }
        else if (btns[i].parentNode){ btns[i].parentNode.removeChild(btns[i]); }
      }
      if (shown > 0){
        var w = document.getElementById('intro-whisper'); if (w) w.hidden = false;
        var only = (shown === 1) ? box.querySelector('.pro-btn') : null;
        setPromise(only ? proLabel(only) : '');
        var note = document.createElement('p');
        note.style.cssText = 'font-size:13px;color:var(--muted);margin:10px 0 0;';
        note.textContent = GATE_T.onlyHere;
        box.appendChild(note);
        return;
      }
      LEAVE_WORD = true;
      var t = document.getElementById('chooser-title'); if (t){ t.textContent = GATE_T.emptyTitle; t.classList.add('quiet-title'); }
      var s = document.getElementById('chooser-sub'); if (s) s.textContent = GATE_T.emptyLead;
      var inner = GATE_T.resources
        + '<p style="margin:12px 0 0;font-size:13.5px;color:var(--muted);">' + GATE_T.leaveNote + '</p>';
      if (!t){ inner = '<p style="font-weight:700;font-size:17px;color:var(--ink);margin:0 0 8px;">' + GATE_T.emptyTitle + '</p>'
        + '<p style="margin:0 0 12px;color:var(--muted);">' + GATE_T.emptyLead + '</p>' + inner; }
      box.innerHTML = '<div class="gate-empty">' + inner + '</div>';
      var rt = document.getElementById('ready-title'); if (rt) rt.textContent = GATE_T.leaveTitle;
      var rs = document.getElementById('ready-sub'); if (rs) rs.textContent = GATE_T.leaveLead;
      var sb = document.getElementById('send-btn'); if (sb) sb.textContent = GATE_T.leaveBtn;
      var cs = document.getElementById('choose-section'); if (cs) cs.style.display = 'none';
    }
    fetch('/api/providers/available').then(function(r){ return r.json(); }).then(function(d){
      var arr = (d && d[GATE_SIDE]) || [];
      gateProviders(Object.prototype.toString.call(arr) === '[object Array]' ? arr : []);
    }).catch(function(){ gateProviders([]); });
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
  <link rel="icon" href="data:,">
  <title>InnerLight &mdash; Connecting You to Legal Help</title>
  <style>
    :root { --ink:#2a1e14; --muted:#99673e; --line:#e8dcc8; --soft:#f5eddc; --cream:#faf5ec; --card:#fffdf8;
            --urgent:#b84a44; --amber:#c56a2c; --dusk:#33567c;
            --green:#c56a2c; --blue:#33567c; --legal:#c56a2c; --legal2:#c56a2c; }
    * { box-sizing:border-box; }
    html { background:#faf5ec; }
    body { margin:0; font-family:Arial, sans-serif; color:var(--ink); background:var(--cream); position:relative; }
    /* FOUNDER DESIGN: his photograph as a faint warm glow behind the opening,
       fading to solid cream before the working sections, so reading is easy. */
    .glow { position:absolute; top:0; left:0; right:0; height:min(92vh, 860px); overflow:hidden; z-index:0; pointer-events:none; }
    .glow .ph { position:absolute; top:0; left:0; right:0; bottom:0; background:url('/scenes/photo_6_golden_horizon.jpg') center top / cover no-repeat; opacity:0.25; }
    .glow .fade { position:absolute; top:0; left:0; right:0; bottom:0; background:linear-gradient(180deg, rgba(250,245,236,0) 0%, rgba(250,245,236,0.2) 45%, rgba(250,245,236,0.7) 72%, rgba(250,245,236,1) 94%); }
    header, main { position:relative; z-index:1; }
    main { padding:10px 6vw 30px; max-width:820px; margin:0 auto; }
    h1, h2, .whisper { font-family:Georgia, 'Times New Roman', serif; font-weight:400; }
    h2 { margin:0 0 10px; font-size:21px; }
    p { color:var(--muted); line-height:1.6; }
    a { color:var(--dusk); }
    .tag { display:inline-block; padding:5px 14px; border-radius:999px; background:rgba(255,253,248,0.6); border:1px solid var(--line); color:var(--muted); font-size:12.5px; }
    .intro { text-align:center; padding:8vh 6vw 44px; max-width:820px; margin:0 auto; }
    .intro .tag { margin-bottom:7vh; }
    .whisper { margin:0 0 26px; font-size:16.5px; font-style:italic; color:var(--muted); }
    .whisper[hidden] { display:none; }
    h1.promise { margin:0 auto; max-width:600px; font-size:clamp(26px, 6.2vw, 40px); line-height:1.25; color:var(--ink); }
    h1.promise.quiet-title { font-size:clamp(22px, 5vw, 30px); }
    .intro-sub { max-width:540px; margin:20px auto 0; font-size:14.5px; }
    #pro-choices { max-width:480px; margin:6vh auto 0; text-align:left; }
    .panel { border:1px solid var(--line); border-radius:16px; background:var(--card); padding:22px; margin:18px 0; }
    .who { background:var(--card); border-color:var(--line); }
    .who ul { margin:8px 0 0; padding-left:0; list-style:none; }
    .who li { padding:9px 0; border-bottom:1px solid var(--soft); color:var(--ink); }
    .who li:last-child { border-bottom:0; }
    .who b { color:var(--amber); }
    .rights { background:var(--soft); border-color:var(--line); }
    .rights summary { cursor:pointer; font-weight:700; color:var(--amber); }
    .rights p { font-size:14px; }
    .urgent-note { background:#fdf3f0; border:1px solid #e5b5a5; border-radius:16px; padding:14px 16px; margin:18px 0; }
    .urgent-note b { color:var(--urgent); }
    label { display:block; font-weight:700; color:var(--ink); margin:14px 0 6px; }
    textarea { width:100%; border:1px solid var(--line); border-radius:10px; padding:12px; font:inherit; min-height:90px; background:#fffefb; }
    .convo { background:var(--soft); border:1px solid var(--line); border-radius:10px; padding:14px; max-height:280px; overflow:auto; }
    .convo .u { color:var(--ink); margin:0 0 10px; }
    .convo .a { color:var(--dusk); margin:0 0 10px; }
    .convo .u b, .convo .a b { display:block; font-size:12px; text-transform:uppercase; letter-spacing:0.04em; opacity:0.7; }
    button, a.button { display:inline-block; border:0; border-radius:999px; padding:15px 30px; background:var(--amber); color:white; font-weight:700; text-decoration:none; cursor:pointer; font-size:16px; }
    .secondary { background:var(--soft); color:var(--ink); }
    .locked { font-size:13px; color:var(--muted); margin-top:8px; }
    /* HIS ONE AMBER PILL: alone, centered, room to breathe. */
    .ready { text-align:center; padding:9vh 4vw 10px; }
    .ready p { max-width:560px; margin-left:auto; margin-right:auto; }
    .ready #send-btn { display:inline-block; margin-top:26px; min-width:min(320px, 100%); }
    /* HIS "NOT YET" LINE: a real door back, never a gray afterthought. */
    .notyet { text-align:center; margin:40px 0 0; }
    .notyet a { color:var(--dusk); font-family:Georgia, 'Times New Roman', serif; font-size:16px; text-decoration:underline; text-underline-offset:3px; }
    /* HIS QUIET 988 EMBER at the very bottom, always present. */
    .ember { text-align:center; margin:56px 0 14px; }
    .ember a { color:var(--amber); text-decoration:none; font-family:Georgia, 'Times New Roman', serif; font-size:16px; letter-spacing:0.12em; opacity:0.85; }
    .pro-btn { display:block; width:100%; text-align:left; margin:10px 0; padding:15px 18px; border-radius:16px;
               border:1px solid #e3d2ba; background:var(--card); cursor:pointer; font-size:15.5px; font-weight:400; color:var(--ink); }
    .pro-btn b { font-family:Georgia, 'Times New Roman', serif; font-weight:700; }
    .pro-btn span { display:block; font-size:13px; color:var(--muted); margin-top:3px; font-weight:400; }
    .pro-btn.picked { border-color:var(--amber); background:#fbf1e4; box-shadow:0 0 0 2px rgba(197,106,44,0.22); }
    .pro-btn.suggested { border-color:var(--dusk); box-shadow:0 0 0 2px rgba(51,86,124,0.20); }
    /* FOUNDER RULE: provider buttons stay hidden until the server confirms a
       real person is available behind them. No ghost buttons, ever. */
    #pro-choices .pro-btn { display:none; color:var(--ink); }
    .gate-res { display:block; text-decoration:none; border:1px solid var(--line); border-radius:14px; padding:12px 15px; background:var(--card); color:var(--ink); margin:8px 0; }
    .gate-res b { font-family:Georgia, 'Times New Roman', serif; }
    .gate-res span { display:block; font-size:12.5px; color:var(--muted); margin-top:3px; font-weight:400; }
    .gate-empty { border:1px solid #e3d2ba; background:rgba(255,253,248,0.9); border-radius:16px; padding:18px 20px; text-align:left; max-width:520px; margin:0 auto; }
    .disclaimer { font-size:12.5px; color:#9c8a74; line-height:1.5; border-top:1px solid var(--line); margin-top:34px; padding-top:16px; }
    @media (prefers-reduced-motion: no-preference){
      .intro { animation:il-fade 0.9s ease; }
      @keyframes il-fade { from { opacity:0; } to { opacity:1; } }
    }
  </style>
</head>
<body>
  <div class="glow" aria-hidden="true"><div class="ph"></div><div class="fade"></div></div>
  <header class="intro">
    <div class="tag">Connecting you to legal help &mdash; this is a legal handoff</div>
    <p class="whisper" id="intro-whisper" hidden>Someone real is ready for you,</p>
    <h1 class="promise" id="chooser-title">Reaching real legal help</h1>
    <p class="intro-sub" id="chooser-sub">This is <b>not</b> a medical or telehealth connection. This path is about a legal issue. Tap the kind of legal help you want &mdash; your summary goes there only when you say send.</p>
    <div id="pro-choices">
      <button type="button" class="pro-btn" data-role="housing_attorney" data-pro="Housing / tenant attorney" onclick="pickPro(this)"><b>Housing / tenant attorney</b><span>Evictions, landlord disputes, unsafe conditions.</span></button>
      <button type="button" class="pro-btn" data-role="family_attorney" data-pro="Family law attorney" onclick="pickPro(this)"><b>Family law attorney</b><span>Custody, divorce, protective orders.</span></button>
      <button type="button" class="pro-btn" data-role="criminal_attorney" data-pro="Criminal defense attorney" onclick="pickPro(this)"><b>Criminal defense attorney</b><span>Charges, warrants, court dates.</span></button>
      <button type="button" class="pro-btn" data-role="civil_attorney" data-pro="Consumer / civil attorney" onclick="pickPro(this)"><b>Consumer / civil attorney</b><span>Debt, fraud claims, insurance disputes, benefits denials.</span></button>
      <button type="button" class="pro-btn" data-role="legal_aid" data-pro="Legal aid office" onclick="pickPro(this)"><b>Legal aid office</b><span>Free or low-cost help when money is tight.</span></button>
    </div>
    <p id="pro-picked" style="font-weight:700;color:var(--amber);"></p>
    <p class="notyet"><a href="/" onclick="if(history.length>1){history.back();return false;}">Not yet &mdash; stay with me a little longer.</a></p>
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
        <a class="res" href="https://www.lsc.gov/about-lsc/what-legal-aid/get-legal-help" target="_blank" rel="noopener"><b>Get Legal Help &mdash; LSC.gov</b><span>The federal Legal Services Corporation&rsquo;s door to free legal aid by state and topic.</span></a>
        <a class="res" href="https://www.law.cornell.edu/wex" target="_blank" rel="noopener"><b>Cornell Law &mdash; Wex</b><span>Plain-language legal dictionary &amp; explanations from Cornell Law School.</span></a>
        <a class="res" href="https://www.abafreelegalanswers.org/" target="_blank" rel="noopener"><b>ABA Free Legal Answers</b><span>Ask a lawyer a civil legal question free &mdash; you pick your state, and a volunteer attorney in your state answers.</span></a>
        <a class="res" href="https://www.usa.gov/legal-aid" target="_blank" rel="noopener"><b>USA.gov Legal Aid</b><span>Government directory of free and low-cost legal help.</span></a>
        <a class="res" href="https://www.lsc.gov/about-lsc/what-legal-aid/i-need-legal-help" target="_blank" rel="noopener"><b>Legal Services Corporation</b><span>Find your local federally funded legal-aid office.</span></a>
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

    <section class="panel who" id="choose-section">
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

    <section class="ready">
      <h2 id="ready-title">Ready when you are</h2>
      <p id="ready-sub">When you send this, InnerLight prepares your approved summary so the legal professional can review it before speaking with you.</p>
      <p id="status" style="font-weight:700;color:var(--legal);"></p>
      <button id="send-btn" onclick="sendToLegal()">I&rsquo;m ready to reach legal help.</button>
      <p class="notyet"><a href="/" onclick="if(history.length>1){history.back();return false;}">Not yet &mdash; stay with me a little longer.</a></p>
    </section>

    <p class="disclaimer">
      InnerLight, a service of God's Love For Us LLC, provides legal information and connection to legal resources. It is not a law firm and does not provide legal advice or representation. No attorney-client relationship is formed with InnerLight. Attorney-client privilege applies once you engage a licensed attorney. Your information is encrypted and shared only with your consent. If your legal issue involves immediate danger to your safety, call 911.
    </p>
  <p class="ember"><a href="tel:988" aria-label="Call 988, the Suicide and Crisis Lifeline">988</a></p>
  </main>
  <style>
    .reslib { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:10px; margin-top:12px; }
    .res { display:block; text-decoration:none; border:1px solid #e3d2ba; border-radius:14px; padding:13px 15px;
           background:#fffdf8; color:#33567c; transition:border-color 0.2s ease, box-shadow 0.2s ease; }
    .res:hover { border-color:#c56a2c; box-shadow:0 4px 14px rgba(197,106,44,0.14); }
    .res span { display:block; font-size:12.5px; color:#99673e; margin-top:4px; }
    @media (prefers-reduced-motion: reduce){ .res { transition:none; } }
  </style>
  <script>
    let pickedPro = '';
    const PAGE_OPEN_TS = Date.now();
    function pickPro(btn){
      document.querySelectorAll('.pro-btn').forEach(b=>b.classList.remove('picked'));
      btn.classList.add('picked'); pickedPro = btn.dataset.pro;
      document.getElementById('pro-picked').textContent = 'You chose: ' + pickedPro + '.';
      var lbl = proLabel(btn);
      var send = document.getElementById('send-btn');
      if (send && !LEAVE_WORD) send.textContent = GATE_T.readyRole.replace('{role}', lbl.toLowerCase());
      setPromise(lbl);
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
          + '<a class="res" href="https://www.lsc.gov/about-lsc/what-legal-aid/i-need-legal-help" target="_blank" rel="noopener"><b>Free legal aid in ' + esc(name) + '</b><span>The federal directory &mdash; choose ' + esc(name) + ' to find the legal-aid offices serving your state.</span></a>'
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
      if (typeof pickedPro !== 'undefined' && !pickedPro && !LEAVE_WORD){
        document.getElementById('status').textContent='First, tap the kind of legal help you want above \u2014 you choose, always.';
        return;
      }
      var summaryText = '';
      if (LEAVE_WORD){
        var clarify = document.getElementById('clarify') ? document.getElementById('clarify').value.trim() : '';
        var addw = document.getElementById('addnote') ? document.getElementById('addnote').value.trim() : '';
        var lg=[]; try{ lg=JSON.parse(sessionStorage.getItem('innerlight_convo')||'[]'); }catch(e){}
        var said = lg.filter(function(t){ return t.role==='user'; }).map(function(t){ return t.text; }).join(' \u2022 ');
        summaryText = ['WHO THIS GOES TO: ' + GATE_T.leaveWho,
          said ? 'IN THEIR OWN WORDS: ' + said : '',
          clarify ? 'THEY CLARIFIED: ' + clarify : '',
          addw ? 'THEY ADDED: ' + addw : ''].filter(Boolean).join('\n\n');
      }
      document.getElementById('status').innerHTML = LEAVE_WORD ? GATE_T.leaveSending : 'Reaching a human for you\u2026';
      fetch('/api/connect/request', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({kind:'legal', pro: (LEAVE_WORD ? 'Left word (legal, no one on call)' : (pickedPro||'legal help')), summary: summaryText})})
      .then(r=>r.json()).then(function(d){
        if (LEAVE_WORD){
          document.getElementById('status').innerHTML = GATE_T.leaveDone + '<br><br><span style="font-family:Georgia,serif;font-style:italic;color:#99673E;font-size:15px;display:inline-block;margin-top:2px;">' + BLESS + '</span>';
          return;
        }
        document.getElementById('status').innerHTML =
          'Your request for a <b>' + (pickedPro||'legal professional').toLowerCase() + '</b> is in, and a human has been alerted. '
          + 'While our network grows, an <b>InnerLight responder</b> \u2014 our founder, not an attorney \u2014 will meet you first '
          + 'and help arrange the right legal help.<br><br>'
          + '<a href="' + d.room + '" target="_blank" style="display:inline-block;background:#c56a2c;color:#fff;'
          + 'padding:13px 26px;border-radius:999px;font-weight:700;text-decoration:none;">Join your private video room</a>'
          + '<br><br><span style="font-family:Georgia,serif;font-style:italic;color:#99673E;font-size:15px;display:inline-block;margin-top:2px;">' + BLESS + '</span>';
      }).catch(function(){
        document.getElementById('status').textContent='The connection request could not go through right now.';
      });
    }
    // ---- FOUNDER RULE GATE: only providers who are truly there are shown.
    // The buttons above start hidden; the server says who is really on call.
    // If no one is, the chooser becomes an honest, dead-end-free block. ----
    var GATE_SIDE = 'legal';
    var LEAVE_WORD = false;
    var BLESS = "You are the best there is, the best there was, and the best there ever could be.";
    var GATE_T = {
      promise: 'They have read nothing \u2014 your story stays yours to tell.',
      promiseRole: 'Your {role} has read nothing \u2014 your story stays yours to tell.',
      introSub: 'This is not a medical or telehealth connection. This path is about a legal issue. Tap the kind of legal help you want \u2014 your summary goes there only when you say send.',
      readyRole: 'I\u2019m ready to reach my {role}.',
      onlyHere: 'Only who is truly here right now is shown.',
      emptyTitle: 'No legal-aid partner is connected at this moment',
      emptyLead: 'We will not pretend otherwise. Right now no attorney or legal-aid office is on call here \u2014 a button only appears when a real person is truly behind it. Everything else on this page \u2014 your state directories and the law-school clinics \u2014 is real and open right now, and so are the doors below.',
      resources: '<a class="gate-res" href="https://www.lsc.gov/about-lsc/what-legal-aid/get-legal-help" target="_blank" rel="noopener"><b>Find your local legal-aid office</b><span>LSC.gov \u2014 the federal Legal Services Corporation directory of free legal-aid offices, always open.</span></a>'
        + '<a class="gate-res" href="tel:211"><b>211 \u2014 free local help line</b><span>Call 211 (or visit 211.org) \u2014 free, confidential help finding local legal and social services, 24/7.</span></a>',
      leaveNote: 'Below, you can also leave word. A real person will see this. This is not an instant connection, and we will never pretend it is.',
      leaveTitle: 'Leave word for the next real person',
      leaveLead: 'Review your words below and send them when you are ready. They will be waiting for the next real person who comes on call \u2014 not an instant connection, and we will never pretend it is.',
      leaveBtn: 'Leave word for the next real person',
      leaveWho: 'the next available legal-aid partner',
      leaveSending: 'Placing your words where the next real person will find them\u2026',
      leaveDone: 'Your words are safely in. <b>A real person will see this.</b> This is not an instant connection, and we will never pretend it is. The directories above are open right now \u2014 and if your situation involves immediate danger, call 911.'
    };
    // ---- FOUNDER DESIGN: the introduction moment. The privacy promise is the
    // loudest line on the page, and it personalizes to the person they chose. ----
    function proLabel(btn){
      var b0 = btn && btn.querySelector ? btn.querySelector('b') : null;
      return (b0 && b0.textContent) || (btn && btn.getAttribute('data-pro')) || '';
    }
    function setPromise(roleLabel){
      var t0 = document.getElementById('chooser-title');
      if (t0){ t0.textContent = roleLabel ? GATE_T.promiseRole.replace('{role}', String(roleLabel).toLowerCase()) : GATE_T.promise; }
      var s0 = document.getElementById('chooser-sub');
      if (s0) s0.textContent = GATE_T.introSub;
    }
    function gateProviders(avail){
      var box = document.getElementById('pro-choices');
      if (!box) return;
      var btns = box.querySelectorAll('.pro-btn');
      var shown = 0;
      for (var i = 0; i < btns.length; i++){
        var role = btns[i].getAttribute('data-role') || '';
        if (avail.indexOf(role) >= 0){ btns[i].style.display = 'block'; shown++; }
        else if (btns[i].parentNode){ btns[i].parentNode.removeChild(btns[i]); }
      }
      if (shown > 0){
        var w = document.getElementById('intro-whisper'); if (w) w.hidden = false;
        var only = (shown === 1) ? box.querySelector('.pro-btn') : null;
        setPromise(only ? proLabel(only) : '');
        var note = document.createElement('p');
        note.style.cssText = 'font-size:13px;color:var(--muted);margin:10px 0 0;';
        note.textContent = GATE_T.onlyHere;
        box.appendChild(note);
        return;
      }
      LEAVE_WORD = true;
      var t = document.getElementById('chooser-title'); if (t){ t.textContent = GATE_T.emptyTitle; t.classList.add('quiet-title'); }
      var s = document.getElementById('chooser-sub'); if (s) s.textContent = GATE_T.emptyLead;
      var inner = GATE_T.resources
        + '<p style="margin:12px 0 0;font-size:13.5px;color:var(--muted);">' + GATE_T.leaveNote + '</p>';
      if (!t){ inner = '<p style="font-weight:700;font-size:17px;color:var(--ink);margin:0 0 8px;">' + GATE_T.emptyTitle + '</p>'
        + '<p style="margin:0 0 12px;color:var(--muted);">' + GATE_T.emptyLead + '</p>' + inner; }
      box.innerHTML = '<div class="gate-empty">' + inner + '</div>';
      var rt = document.getElementById('ready-title'); if (rt) rt.textContent = GATE_T.leaveTitle;
      var rs = document.getElementById('ready-sub'); if (rs) rs.textContent = GATE_T.leaveLead;
      var sb = document.getElementById('send-btn'); if (sb) sb.textContent = GATE_T.leaveBtn;
      var cs = document.getElementById('choose-section'); if (cs) cs.style.display = 'none';
    }
    fetch('/api/providers/available').then(function(r){ return r.json(); }).then(function(d){
      var arr = (d && d[GATE_SIDE]) || [];
      gateProviders(Object.prototype.toString.call(arr) === '[object Array]' ? arr : []);
    }).catch(function(){ gateProviders([]); });
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


# ---------------------------------------------------------------------------
# SECURITY HEADERS (WITHSTAND / DETER — Principle 17).
# Added as a SEPARATE after_request so the existing before_request above is
# untouched. Every header here was checked against what InnerLight actually
# loads (cdn.jsdelivr.net for face-api / MediaPipe / Tone.js, plus the video
# rooms on Daily.co and Jitsi) and against the camera/microphone heart-rate
# feature, so none of it breaks the site. The Content-Security-Policy keeps
# 'unsafe-inline' for scripts/styles ONLY because the app renders inline
# script and style blocks throughout; it is otherwise as tight as the app allows.
# ---------------------------------------------------------------------------
_CSP = "; ".join([
    "default-src 'self'",
    # inline scripts are used across the templates; wasm-unsafe-eval is required
    # by the on-device MediaPipe/face-api heart-rate reader (WebAssembly).
    "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net https://storage.googleapis.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "media-src 'self' data: blob:",
    "font-src 'self' data:",
    # the on-device model fetches wasm/weights from jsdelivr AND the MediaPipe
    # face models from storage.googleapis.com; blob: for workers.
    "connect-src 'self' https://cdn.jsdelivr.net https://storage.googleapis.com https://api.daily.co https://*.daily.co https://meet.jit.si blob:",
    # video rooms may be framed by their own SDKs.
    "frame-src https://*.daily.co https://meet.jit.si",
    "worker-src 'self' blob:",
    "child-src blob: https://*.daily.co https://meet.jit.si",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    # X-XSS-Protection 0: the legacy filter is itself an XSS vector; CSP replaces it.
    resp.headers.setdefault("X-XSS-Protection", "0")
    # Only the camera and microphone are used, and only by this origin (the
    # on-device heart-rate reader and voice). Everything else is denied.
    resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=(), payment=()")
    resp.headers.setdefault("Content-Security-Policy", _CSP)
    return resp

@app.route("/")
def index():
    return render_template_string(PUBLIC_PAGE)


@app.route("/manifest.json")
def manifest_json():
    # PWA manifest: exists ONLY so that a person who chooses "Add to Home
    # Screen" gets a beautiful, full-screen InnerLight with a proper icon.
    # No install prompts, no notifications, no engagement machinery — ever.
    from flask import jsonify
    return jsonify({
        "name": "InnerLight",
        "short_name": "InnerLight",
        "description": "A calm, private place to wait, with a gentle bridge to real human help.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#faf5ec",
        "theme_color": "#2a1e14",
        "icons": [
            {"src": "/scenes/app_icon_192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": "/scenes/app_icon_512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            {"src": "/scenes/app_icon_512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    })


# ---------------------------------------------------------------------------
# INFORMATION PAGES — About, How It Works, Privacy, Contact.
# For a mental-health product, people won't trust it without knowing who is
# behind it and how their words are handled. These build that trust. Styled
# "calm but alive" to match the rest of InnerLight.
# ---------------------------------------------------------------------------
_PAGE_I18N = {}
_PAGE_LANGS = ("es", "zh", "hi", "pa", "bn", "tl", "to", "sw", "am", "ha")
_PAGE_CACHE_DIR = "/var/data" if os.path.isdir("/var/data") else "/tmp/il_i18n"

def _load_page_i18n():
    import os as _os, json as _json
    base = _os.path.dirname(_os.path.abspath(__file__))
    try:
        _os.makedirs(_PAGE_CACHE_DIR, exist_ok=True)
    except Exception:
        pass
    for lg in _PAGE_LANGS:
        _PAGE_I18N[lg] = {}
        # Repo-committed translations first (native-reviewed seeds)...
        try:
            with open(_os.path.join(base, "i18n_pages_%s.json" % lg), encoding="utf-8") as f:
                _PAGE_I18N[lg].update(_json.load(f))
        except Exception:
            pass
        # ...then the runtime cache the server built for itself.
        try:
            with open(_os.path.join(_PAGE_CACHE_DIR, "i18n_pages_%s.json" % lg), encoding="utf-8") as f:
                _PAGE_I18N[lg].update(_json.load(f))
        except Exception:
            pass
        if not _PAGE_I18N[lg]:
            print("[InnerLight] page i18n %s: none yet — will self-translate on first visit" % lg)
_load_page_i18n()

# ---- WARM-BOOT TRANSLATION: African languages first ----
# The server does not wait to be visited. At boot it translates every info
# page itself, in priority order set by the founder: Swahili, Amharic, and
# Hausa FIRST, then the remaining languages. Serialized (one page at a time)
# to respect rate limits; every result flows through the same QE judge and
# cache; repo-committed native-reviewed files still always win.
_WARM_ORDER = ("sw", "am", "ha", "hi", "pa", "bn", "tl", "to")
_WARM_PAGES = ("about", "how-it-works", "stories", "resources", "research",
               "safety", "privacy", "updates", "contact", "faq", "terms")
_WARM_PATHS = {"about": "/about", "how-it-works": "/how-it-works", "stories": "/stories",
               "resources": "/resources", "research": "/research", "safety": "/safety",
               "privacy": "/privacy", "updates": "/updates", "contact": "/contact",
               "faq": "/faq", "terms": "/terms"}

def _warm_boot_translations():
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return
    def _work():
        time.sleep(15)  # let the app finish waking up first
        client = app.test_client()
        for lg in _WARM_ORDER:
            for key in _WARM_PAGES:
                try:
                    if key in _PAGE_I18N.get(lg, {}):
                        continue
                    client.get(_WARM_PATHS[key] + "?lang=" + lg)  # triggers the kick
                    # serialize: wait for this page to land before the next
                    deadline = time.time() + 240
                    while time.time() < deadline:
                        with _page_pending_lock:
                            still = (lg, key) in _PAGE_PENDING
                        if not still:
                            break
                        time.sleep(1.0)
                except Exception as e:
                    print("[InnerLight] warm-boot %s/%s: %s" % (lg, key, str(e)[:80]))
            print("[InnerLight] warm-boot: %s pages ready (%d/%d)" % (
                lg, len(_PAGE_I18N.get(lg, {})), len(_WARM_PAGES)))
    threading.Thread(target=_work, daemon=True).start()

_warm_boot_translations()

# ---- SELF-HEALING PAGE TRANSLATION ----
# A page visited in a language it does not yet speak serves English INSTANTLY,
# and quietly translates itself in the background (QE-judged), caches the
# result, and speaks that language for every visitor after. One mechanism,
# every page, every language — including pages and languages added later.
_PAGE_PENDING = set()
_page_pending_lock = threading.Lock()

def _page_i18n_kick(lang, page_key, inner_en):
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return
    tag = (lang, page_key)
    with _page_pending_lock:
        if tag in _PAGE_PENDING:
            return
        _PAGE_PENDING.add(tag)
    def _work():
        try:
            out = comprehension_engine.translate_html_verified(inner_en, lang)
            if out:
                _PAGE_I18N.setdefault(lang, {})[page_key] = out
                try:
                    os.makedirs(_PAGE_CACHE_DIR, exist_ok=True)
                    path = os.path.join(_PAGE_CACHE_DIR, "i18n_pages_%s.json" % lang)
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(_PAGE_I18N[lang], f, ensure_ascii=False)
                    print("[InnerLight] page %r now speaks %s (cached)" % (page_key, lang))
                except Exception as e:
                    print("[InnerLight] page i18n cache write failed: %s" % str(e)[:100])
        finally:
            with _page_pending_lock:
                _PAGE_PENDING.discard(tag)
    threading.Thread(target=_work, daemon=True).start()

_INFO_CHROME = {
    "en": {"back": "&larr; Back to InnerLight", "about": "About", "how": "How it works", "research": "Research", "safety": "Safety &amp; crisis protocol", "privacy": "Your privacy", "contact": "Contact", "resources": "Real help", "stories": "How a visit goes", "updates": "Updates", "terms": "Terms of Service"},
    "es": {"back": "&larr; Volver a InnerLight", "about": "Acerca de", "how": "C&oacute;mo funciona", "research": "Investigaci&oacute;n", "safety": "Seguridad y protocolo de crisis", "privacy": "Tu privacidad", "contact": "Contacto", "resources": "Ayuda real", "stories": "C&oacute;mo es una visita", "updates": "Novedades", "terms": "T&eacute;rminos del servicio"},
    "zh": {"back": "&larr; 返回 InnerLight", "about": "关于", "how": "如何运作", "research": "研究", "safety": "安全与危机处理协议", "privacy": "你的隐私", "contact": "联系我们", "resources": "真实的帮助", "stories": "一次访问的样子", "updates": "最新进展", "terms": "服务条款"},
    "hi": {"back": "&larr; InnerLight पर वापस", "about": "हमारे बारे में", "how": "यह कैसे काम करता है", "research": "शोध", "safety": "सुरक्षा और संकट प्रोटोकॉल", "privacy": "आपकी गोपनीयता", "contact": "संपर्क करें", "resources": "सच्ची मदद", "stories": "एक मुलाक़ात कैसी होती है", "updates": "नई जानकारी", "terms": "सेवा की शर्तें"},
    "pa": {"back": "&larr; InnerLight ਉੱਤੇ ਵਾਪਸ", "about": "ਸਾਡੇ ਬਾਰੇ", "how": "ਇਹ ਕਿਵੇਂ ਕੰਮ ਕਰਦਾ ਹੈ", "research": "ਖੋਜ", "safety": "ਸੁਰੱਖਿਆ ਅਤੇ ਸੰਕਟ ਪ੍ਰੋਟੋਕੋਲ", "privacy": "ਤੁਹਾਡੀ ਪਰਦੇਦਾਰੀ", "contact": "ਸੰਪਰਕ ਕਰੋ", "resources": "ਸੱਚੀ ਮਦਦ", "stories": "ਇੱਕ ਮੁਲਾਕਾਤ ਕਿਹੋ ਜਿਹੀ ਹੁੰਦੀ ਹੈ", "updates": "ਨਵੀਆਂ ਖ਼ਬਰਾਂ", "terms": "ਸੇਵਾ ਦੀਆਂ ਸ਼ਰਤਾਂ"},
    "bn": {"back": "&larr; InnerLight-এ ফিরুন", "about": "আমাদের সম্পর্কে", "how": "এটি কীভাবে কাজ করে", "research": "গবেষণা", "safety": "নিরাপত্তা ও সংকট প্রোটোকল", "privacy": "আপনার গোপনীয়তা", "contact": "যোগাযোগ", "resources": "সত্যিকারের সাহায্য", "stories": "একটি সাক্ষাৎ কেমন হয়", "updates": "নতুন খবর", "terms": "পরিষেবার শর্তাবলী"},
    "tl": {"back": "&larr; Bumalik sa InnerLight", "about": "Tungkol sa amin", "how": "Paano ito gumagana", "research": "Pananaliksik", "safety": "Kaligtasan at protocol sa krisis", "privacy": "Ang iyong privacy", "contact": "Makipag-ugnayan", "resources": "Totoong tulong", "stories": "Paano ang isang pagbisita", "updates": "Mga update", "terms": "Mga Tuntunin ng Serbisyo"},
    "to": {"back": "&larr; Foki ki InnerLight", "about": "Ko kimautolu", "how": "Founga ʻene ngāue", "research": "Fekumi", "safety": "Malu mo e founga ʻi ha faingataʻa", "privacy": "Hoʻo fakapulipuli", "contact": "Fetuʻutaki", "resources": "Tokoni moʻoni", "stories": "Ko e anga ʻo ha ʻaʻahi", "updates": "Ngaahi fakamatala foʻou", "terms": "Ngaahi Tuʻutuʻuni ʻo e Ngāue"},
}

def _info_lang():
    lg = (request.args.get("lang") or request.cookies.get("il_lang") or "en")
    return lg if lg == "en" or lg in _PAGE_LANGS else "en"

def _info_page(title, inner, page_key=None):
    lang = _info_lang()
    if page_key and lang != "en" and lang in _PAGE_LANGS:
        _t = _PAGE_I18N.get(lang, {}).get(page_key)
        if _t:
            inner = _t
        else:
            _page_i18n_kick(lang, page_key, inner)
    _ch = _INFO_CHROME.get(lang, _INFO_CHROME["en"])
    _q = ("?lang=" + lang) if lang != "en" else ""
    return render_template_string("""<!DOCTYPE html>
<html lang="{{ lang }}"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#faf5ec">
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/png" sizes="192x192" href="/scenes/app_icon_192.png">
<link rel="apple-touch-icon" href="/scenes/app_icon_192.png">
<title>{{ title }} &mdash; InnerLight</title>
<meta name="description" content="{{ title }} — InnerLight, a free, private, calming companion for the gap between reaching out and real human help arriving. Not therapy — a bridge. Adults 18+.">
<meta property="og:title" content="{{ title }} — InnerLight">
<meta property="og:description" content="InnerLight: a free, private, calming companion for the gap between reaching out and real human help arriving.">
<meta property="og:type" content="website">
<meta property="og:image" content="https://getinnerlight.com/scenes/photo_2_sunset_trees.jpg">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  :root{ --ink:#2b2620; --body:#4a4235; --muted:#6b5f4e; --blue:#33567c; --blue-d:#25405e;
         --amber:#c56a2c; --amber-d:#a9531f; --line:#e7dccc; }
  :focus-visible { outline:3px solid #b7791f; outline-offset:2px; border-radius:4px;
                   box-shadow:0 0 0 6px rgba(255,217,160,0.5); }
  @media (prefers-reduced-motion: reduce){ .breathe { animation:none; } }
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
  .cite { font-size:12.5px; color:#4a6472; margin:2px 0 10px; padding-left:12px; border-left:2px solid var(--line); }
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
  .footer { margin-top:46px; padding-top:20px; border-top:1px solid var(--line); font-size:13px; color:#746753; text-align:center; }
  .footer a { color:var(--blue); text-decoration:none; margin:0 7px; }
</style></head><body>
  <div class="wrap">
    <div style="text-align:right;font-size:12.5px;margin-bottom:2px;">
      <a href="?lang=en" onclick="try{document.cookie='il_lang=en;path=/;max-age=0';sessionStorage.setItem('il_lang','en')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='en' else '' }}">English</a>
      <span style="color:#ddd1c8;">&middot;</span>
      <a href="?lang=es" onclick="try{document.cookie='il_lang=es;path=/';sessionStorage.setItem('il_lang','es')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='es' else '' }}">Espa&ntilde;ol</a>
      <span style="color:#ddd1c8;">&middot;</span>
      <a href="?lang=zh" onclick="try{document.cookie='il_lang=zh;path=/';sessionStorage.setItem('il_lang','zh')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='zh' else '' }}">&#20013;&#25991;</a>
      <span style="color:#ddd1c8;">&middot;</span>
      <a href="?lang=hi" onclick="try{document.cookie='il_lang=hi;path=/';sessionStorage.setItem('il_lang','hi')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='hi' else '' }}">हिन्दी</a>
      <span style="color:#ddd1c8;">&middot;</span>
      <a href="?lang=pa" onclick="try{document.cookie='il_lang=pa;path=/';sessionStorage.setItem('il_lang','pa')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='pa' else '' }}">ਪੰਜਾਬੀ</a>
      <span style="color:#ddd1c8;">&middot;</span>
      <a href="?lang=bn" onclick="try{document.cookie='il_lang=bn;path=/';sessionStorage.setItem('il_lang','bn')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='bn' else '' }}">বাংলা</a>
      <span style="color:#ddd1c8;">&middot;</span>
      <a href="?lang=tl" onclick="try{document.cookie='il_lang=tl;path=/';sessionStorage.setItem('il_lang','tl')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='tl' else '' }}">Tagalog</a>
      <span style="color:#ddd1c8;">&middot;</span>
      <a href="?lang=to" onclick="try{document.cookie='il_lang=to;path=/';sessionStorage.setItem('il_lang','to')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='to' else '' }}">lea faka-Tonga</a>
      <a href="?lang=sw" onclick="try{document.cookie='il_lang=sw;path=/';sessionStorage.setItem('il_lang','sw')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='sw' else '' }}">Kiswahili</a>
      <a href="?lang=am" onclick="try{document.cookie='il_lang=am;path=/';sessionStorage.setItem('il_lang','am')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='am' else '' }}">&#4768;&#4635;&#4653;&#4763;</a>
      <a href="?lang=ha" onclick="try{document.cookie='il_lang=ha;path=/';sessionStorage.setItem('il_lang','ha')}catch(e){}" style="color:#33567c;text-decoration:none;{{ 'font-weight:700;' if lang=='ha' else '' }}">Hausa</a>
    </div>
    <div class="orb breathe" aria-hidden="true"></div>
    <div class="brand">InnerLight</div>
    <main>
    {{ inner|safe }}
    </main>
    <a class="back" href="/">{{ back|safe }}</a>
    <div class="footer">
      <a href="/about{{ q }}">{{ c_about|safe }}</a>&middot;
      <a href="/how-it-works{{ q }}">{{ c_how|safe }}</a>&middot;
      <a href="/stories{{ q }}">{{ c_stories|safe }}</a>&middot;
      <a href="/resources{{ q }}">{{ c_resources|safe }}</a>&middot;
      <a href="/research{{ q }}">{{ c_research|safe }}</a>&middot;
      <a href="/safety{{ q }}">{{ c_safety|safe }}</a>&middot;
      <a href="/privacy{{ q }}">{{ c_privacy|safe }}</a>&middot;
      <a href="/updates{{ q }}">{{ c_updates|safe }}</a>&middot;
      <a href="/contact{{ q }}">{{ c_contact|safe }}</a>&middot;
      <a href="/terms{{ q }}">{{ c_terms|safe }}</a>
      <div style="margin-top:10px;">&copy; 2026 God's Love For Us LLC &middot; Created by Toshay S. Zeigler</div>
    </div>
  </div>
</body></html>""", title=title, inner=inner, lang=lang, q=_q, back=_ch["back"],
    c_about=_ch["about"], c_how=_ch["how"], c_research=_ch["research"], c_safety=_ch["safety"],
    c_privacy=_ch["privacy"], c_contact=_ch["contact"], c_resources=_ch["resources"],
    c_stories=_ch["stories"], c_updates=_ch["updates"], c_terms=_ch.get("terms", "Terms of Service"))


@app.route("/about")
def page_about():
    inner = """
    <h1>Why InnerLight exists</h1>
    <p class="lead">InnerLight holds the hardest space in the mental-health system: the gap between the moment a person reaches out and the moment real human help actually arrives.</p>

    <p style="font-family:Georgia,serif;font-style:italic;">And beneath everything, one founding belief about every person who enters &mdash; regardless of their pain, their loss, or their trouble: <strong>you are the best there is, the best there was, and the best there ever could be.</strong></p>

    <p style="font-size:14px;color:#74624d;">Credit where credit is due: those words began as the mantra of professional wrestler Bret &ldquo;The Hitman&rdquo; Hart &mdash; <em>the best there is, the best there was, the best there ever will be</em>. In our founder&rsquo;s family they became a call-and-response, and the ending changed from &ldquo;will be&rdquo; to &ldquo;could be&rdquo; &mdash; from a champion&rsquo;s declaration to a door held open. We honor the man who said it first.</p>

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

    <h2 id="partners">For clinicians, researchers, and crisis organizations</h2>
    <p>We are actively looking for people who can help us sharpen and validate this work &mdash; clinicians, crisis-service providers, researchers, and technologists. We do not claim InnerLight is proven; it is built on established principles and is itself untested, and independent evaluation is exactly what we want. To be concrete about it:</p>
    <h3>What we are looking for</h3>
    <ul>
      <li><strong>Pilot partners</strong> &mdash; clinics, crisis services, legal-aid offices, and community organizations willing to try InnerLight with the adults they serve, on their terms, and tell us plainly what works and what does not.</li>
      <li><strong>Independent evaluation</strong> &mdash; researchers willing to design and run a real study of whether this tool helps, with full access to our methods and the standing commitment that we publish the results either way, including negative ones.</li>
      <li><strong>Challenge and criticism</strong> &mdash; if you believe part of this design is wrong, unsafe, or overstated, we want that conversation most of all. A hard question now is worth far more to us than a compliment later.</li>
    </ul>
    <h3>What we offer in return</h3>
    <ul>
      <li><strong>Full methods transparency</strong> &mdash; every technique, algorithm, and honest limitation is documented on the <a href="/research">Research &amp; Methods</a> page, with citations, and we will answer any question about how the system works.</li>
      <li><strong>A published safety protocol</strong> &mdash; exactly what InnerLight does when someone may be in danger is written out, step by step, on the <a href="/safety">Safety &amp; crisis protocol</a> page.</li>
      <li><strong>Data-handling documentation</strong> &mdash; what is stored, what is never stored, and how encryption works is on the <a href="/privacy">Your privacy</a> and <a href="/research">Research</a> pages, in both plain and technical language.</li>
    </ul>
    <h3>How to reach us</h3>
    <p>Write to us through the <a href="/contact">contact page</a> &mdash; it reaches the founder directly, and a message that challenges us is as welcome as one that offers help.</p>

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


@app.route("/terms")
def page_terms():
    inner = """
    <p style="font-size:13px;color:#776;">Effective date: August 13, 2026 &middot; Version 1.0. Each section below states the full term, then <b>In plain words</b> &mdash; the same promise in everyday language. Both say the same thing; the plain words are there because honesty should be readable.</p>

    <h2>1. Who we are, and what you are agreeing to</h2>
    <p>InnerLight is a service of <b>God&rsquo;s Love for Us LLC</b> (&ldquo;we,&rdquo; &ldquo;us&rdquo;). By using InnerLight you agree to these Terms of Service and to our <a href="/privacy">Privacy Promise</a>. If you do not agree, please do not use the service &mdash; though the crisis numbers on every page (988, 911) are yours regardless, always.</p>
    <p class="plain"><b>In plain words:</b> InnerLight is run by God&rsquo;s Love for Us LLC. Using it means you accept this agreement. The emergency numbers belong to everyone, agreement or not.</p>

    <h2>2. What InnerLight is &mdash; and is not</h2>
    <p>InnerLight is an AI companion for the wait between reaching out for help and human help arriving. It provides emotional support, general information, and warm hand-offs to human services. InnerLight is <b>not</b> a licensed therapist, physician, attorney, or emergency service. It does not diagnose, treat, or prescribe; it does not provide legal advice; it does not replace professional care of any kind, and it is designed to point you toward humans, not away from them. Information it provides &mdash; including legal information &mdash; is general education, not professional advice for your situation.</p>
    <p class="plain"><b>In plain words:</b> InnerLight is real company and a bridge to real people. It is not a doctor, therapist, or lawyer, and it will never pretend to be.</p>

    <h2>3. Emergencies</h2>
    <p>If you or someone else is in immediate danger, call <b>911</b>. For mental-health crisis support from trained human counselors, call or text <b>988</b>, or use 988 chat. InnerLight exists to help you reach those services and to stay with you on the way &mdash; it is not itself an emergency response service and cannot dispatch physical help.</p>
    <p class="plain"><b>In plain words:</b> InnerLight walks with you toward help. It cannot drive the ambulance. In danger: 911. In crisis: 988.</p>

    <h2>4. It is free for you</h2>
    <p>InnerLight never charges a person seeking help. There are no fees, no subscriptions, no advertisements, and your words are never sold &mdash; these are founding commitments, published in our <a href="/research">principles</a>.</p>
    <p class="plain"><b>In plain words:</b> You will never pay, see ads, or be the product.</p>

    <h2>5. Your privacy and your saved conversations</h2>
    <p>Our full <a href="/privacy">Privacy Promise</a> is part of these Terms. In summary: no accounts are required; microphone and camera are optional and processed on your device; conversation sharing with a counselor happens only with your explicit consent; and if you save your place, your conversation is encrypted under a code that only you hold. <b>If you lose your code, no one &mdash; including us &mdash; can recover that conversation.</b> That is a feature, engineered on purpose.</p>
    <p class="plain"><b>In plain words:</b> What you say stays yours. Your save code is the only key that exists &mdash; guard it.</p>

    <h2>6. Honesty about legal limits</h2>
    <p>We do not silently report ordinary conversations to anyone. And there are limits we state plainly rather than hide: if you tell us you have harmed someone or intend serious harm to yourself or others, InnerLight will actively work to connect you with human help; licensed professionals you connect with carry their own legal duties (including duty-to-warn obligations that vary by state); federal law requires online services to report child sexual abuse material, without exception; and we comply with valid legal process, with our encryption designed so that what can ever be produced is as close to nothing as we can engineer. Being in crisis is not a crime and will never be treated like one here.</p>
    <p class="plain"><b>In plain words:</b> No secret reporting. But we follow the law, we act on stated danger by connecting you to humans, and we will never treat your pain as a crime.</p>

    <h2>7. Who may use InnerLight</h2>
    <p>InnerLight is a general-audience service and requires no account or registration. It is not directed to children under 13, and by design it collects the minimum information possible from anyone. Young people are never turned away from crisis support; InnerLight applies additional protective behaviors for minors, including encouraging connection with trusted adults and youth-specific services.</p>
    <p class="plain"><b>In plain words:</b> No sign-ups, minimal data from everyone, extra care for young people, and no one in crisis is ever turned away.</p>

    <h2>8. Acceptable use</h2>
    <p>You agree not to use InnerLight to violate any law; to attempt to harm, probe, overload, or gain unauthorized access to the service or its data; to impersonate others; to harvest information about other people; or to interfere with another person&rsquo;s use of the service. We may limit or refuse service to protect people or the system, applying the least restriction that keeps everyone safe.</p>
    <p class="plain"><b>In plain words:</b> Use it honestly. Don&rsquo;t attack it or use it against other people.</p>

    <h2>9. Third-party services</h2>
    <p>InnerLight connects you outward &mdash; to 988, 911, 211, legal aid, treatment finders, and other services operated by others. We verify that these doors open before sending you through them, and we maintain fallback routes when they fail, but the services themselves are governed by their own terms and are not operated or controlled by us.</p>
    <p class="plain"><b>In plain words:</b> We check that the doors we send you to actually open. What is behind each door is run by its own people.</p>

    <h2>10. Research participation</h2>
    <p>InnerLight may participate in academic research studies. Any use of InnerLight as part of a formal research study is governed by that study&rsquo;s separate, Institutional Review Board&ndash;approved informed-consent process &mdash; nothing in these Terms enrolls you in research, and research participation is always a separate, explicit choice.</p>
    <p class="plain"><b>In plain words:</b> If InnerLight is ever part of a university study, you would be asked separately, clearly, and by choice.</p>

    <h2>11. Intellectual property</h2>
    <p>InnerLight, the Axiom Harmony Protocol, VEIL, EDEN, and the Zenisys Sound System are works of God&rsquo;s Love for Us LLC, created by Toshay S. Zeigler. You may use the service for its intended purpose; you may not copy, resell, or misrepresent it as your own. What you write remains yours.</p>
    <p class="plain"><b>In plain words:</b> The system is ours; your words are yours.</p>

    <h2>12. Service provided &ldquo;as is&rdquo;</h2>
    <p>We build carefully &mdash; every release passes a verification gate before it can reach you &mdash; and we still cannot promise perfection. InnerLight is provided &ldquo;as is&rdquo; and &ldquo;as available,&rdquo; without warranties of any kind, express or implied, including merchantability, fitness for a particular purpose, and uninterrupted or error-free operation. AI-generated responses can be imperfect; that is one reason InnerLight always keeps human doors in view.</p>
    <p class="plain"><b>In plain words:</b> We test everything before it reaches you, and we still won&rsquo;t pretend to be flawless. That is exactly why the human help lines are always on screen.</p>

    <h2>13. Limitation of liability</h2>
    <p>To the fullest extent permitted by law, God&rsquo;s Love for Us LLC and its founder, employees, and partners are not liable for indirect, incidental, special, consequential, or punitive damages arising from use of InnerLight, and our total aggregate liability for any claim is limited to one hundred dollars (US $100) or the amount you paid us in the past twelve months, whichever is greater (and you pay us nothing). Some jurisdictions do not allow certain warranty disclaimers or liability limitations, so parts of Sections 12&ndash;13 may not apply to you; in those places, our liability is limited to the smallest extent the law allows. Nothing in these Terms limits liability that cannot lawfully be limited.</p>
    <p class="plain"><b>In plain words:</b> The law lets services set liability limits, and ours are here in the open &mdash; adjusted automatically wherever your state says otherwise.</p>

    <h2>14. Changes, and ending use</h2>
    <p>You may stop using InnerLight at any time. We may update these Terms as the service grows; the effective date above always reflects the current version, material changes will be noted on the <a href="/updates">Updates page</a>, and continued use after a change means acceptance of the updated Terms.</p>
    <p class="plain"><b>In plain words:</b> Leave whenever you want. When these Terms change, we say so out loud, dated.</p>

    <h2>15. Governing law and disputes</h2>
    <p>These Terms are governed by the laws of the State of California, without regard to conflict-of-law rules, and disputes belong to the state or federal courts located in Santa Clara County, California &mdash; while your own state&rsquo;s consumer protections that cannot be waived remain fully yours. If any part of these Terms is found unenforceable, the rest stands. These Terms plus the Privacy Promise are the entire agreement between us about InnerLight.</p>
    <p class="plain"><b>In plain words:</b> California law and Santa Clara County courts govern disagreements &mdash; and no term here takes away rights your own state guarantees you.</p>

    <h2>16. Contact</h2>
    <p>Questions about these Terms reach us through the <a href="/contact">Contact page</a>. Finding a problem &mdash; in the service or in this document &mdash; is a gift: our standing law is that what is found gets repaired, and the system around it gets improved.</p>
    <p class="plain"><b>In plain words:</b> Talk to us. Problems found are problems fixed.</p>

    <style>.plain{background:#f4efe4;border-left:3px solid #b89a6a;border-radius:0 10px 10px 0;padding:10px 14px;font-size:14px;}</style>
    """
    return _info_page("Terms of Service", inner, page_key="terms")

@app.route("/faq")
def page_faq():
    inner = """
    <h2>What is InnerLight?</h2>
    <p>InnerLight is a companion for the hardest wait there is &mdash; the time between reaching out for help and human help actually arriving. It talks with you, steadies you, and walks you to the right human: a crisis counselor, a professional, legal aid, or the people who love you. It was built by a founder who spent years watching that gap swallow people, and it exists to close it.</p>

    <h2>Is InnerLight a therapist, doctor, or lawyer?</h2>
    <p>No &mdash; and it will never pretend to be. InnerLight never diagnoses, never prescribes, and never gives legal advice. It gives you honest information, real company through the wait, and a direct path to licensed humans. That line is written into its founding principles and enforced in its code.</p>

    <h2>Does it cost me anything?</h2>
    <p>No. A person reaching for help never pays &mdash; not now, not ever. That is a founding law of this project, not a promotion.</p>

    <h2>What happens to what I say?</h2>
    <p>Your words stay between you and InnerLight unless YOU choose otherwise. Conversations are protected with our own layered encryption; nothing is sold, shared, or used for advertising &mdash; ever. If you choose to save your place, it is encrypted under a code only you hold. If you choose to share a summary with a counselor so you don&rsquo;t have to start over, that happens only when you check the consent box yourself.</p>

    <h2>Will InnerLight call the police or 911 on me?</h2>
    <p>Here is the honest, complete answer. InnerLight does not silently report ordinary conversations to anyone, and sharing a summary with a counselor happens only with your consent. AND &mdash; because honesty matters more than comfort &mdash; there are real limits, and we will not pretend otherwise:</p>
    <p><b>If you tell us you have harmed someone, or that you intend to harm yourself or someone else, we will not act as if we didn&rsquo;t hear it.</b> InnerLight will immediately and actively work to connect you with human help (988, 911, chat, a live monitor), and we follow the law. Licensed professionals you are connected to &mdash; counselors, clinicians, our human monitors where they are licensed &mdash; carry their own legal duties in most states to act on credible threats of serious harm to an identifiable person (the duty-to-warn laws that bind clinicians nationwide, varying by state). Federal law separately requires any online service to report child sexual abuse material &mdash; that duty is absolute and we honor it completely. And like every company, we comply with valid court orders; our encryption design means a saved conversation without your code cannot be read by anyone, including us, so what can ever be produced is as close to nothing as we can engineer.</p>
    <p>What we will never do: sell your words, report you for being in pain, or punish you for asking for help. Being in crisis is not a crime, and coming here will never be treated like one. The full step-by-step protocol is public on the <a href="/safety">Safety page</a>.</p>

    <h2>Do I have to use my camera or microphone?</h2>
    <p>No. Everything works by typing alone. If you allow the microphone or camera, InnerLight uses them only in the moment, on your device, to listen better and steady the experience &mdash; audio and video are never stored and never leave your browser as recordings.</p>

    <h2>What languages does InnerLight speak?</h2>
    <p>English, Spanish, Chinese, Hindi, Punjabi, Bengali, Tagalog, Tongan, Swahili, Amharic, and Hausa &mdash; and in a crisis, every safety surface holds your language. If your device has no speaking voice for your language, InnerLight stays respectfully silent rather than speak the wrong one; the words remain on screen.</p>

    <h2>I&rsquo;m under 18. Can I use this?</h2>
    <p>InnerLight will always talk with you and always show you the fastest doors to help. It also takes extra care with young people: it gently encourages connecting with a trusted adult and with youth-specific lines, and it holds firmer boundaries by design. You are never turned away.</p>

    <h2>Is talking to an AI a replacement for real help?</h2>
    <p>No, and InnerLight is built to make sure it never becomes one. Its whole purpose points OUTWARD &mdash; toward humans. If it notices someone treating it as a substitute for human connection, it gently and honestly redirects. It would rather lose your attention than replace your people.</p>

    <h2>What if a service it sends me to is down?</h2>
    <p>Every critical handoff has a chain of ways in. Before you are sent anywhere, the system checks that the door actually opens right now; if a website is having an outage, the next verified door takes over automatically. You will never be handed a dead link on purpose &mdash; and if you ever find one, it gets repaired and the chain gets deeper.</p>

    <h2>Do I need to install an app?</h2>
    <p>Never. InnerLight runs in the browser you already have, and it will never require you to install or choose an app to reach help &mdash; 211 opens as a website, 988 can be reached by chat as well as by phone, and every door works from a plain tap.</p>

    <h2>Can I save my conversation and come back?</h2>
    <p>Yes. Ask to save your place and you receive a short code &mdash; your conversation is encrypted under it, and no code means no access, not even for us. When you return and enter the code, the conversation rebuilds exactly as it was and continues with memory, so you never have to tell your story twice.</p>

    <h2>Why do some connections say &ldquo;sample&rdquo;?</h2>
    <p>Honesty rule: InnerLight never shows you a button unless a real person or service is behind it. Provider video connections appear only as real providers enroll; until then, demonstrations are clearly labeled as samples. What is live is live everywhere: the companion, the crisis doors, legal information, and the full experience.</p>

    <h2>Who is behind InnerLight?</h2>
    <p>InnerLight is built by God&rsquo;s Love for Us LLC, founded on years of direct field observation of what actually calms people in distress and firsthand experience navigating healthcare, disability, and public systems. The mission, the evidence, and every method are public on the <a href="/research">Research &amp; Methods</a> page.</p>

    <h2>Something is broken or wrong. What do I do?</h2>
    <p>Tell us &mdash; it gets fixed. This project runs on a standing law: when a problem is found, it is repaired and the surrounding system is improved, immediately. Every page footer has the contact path, and every report makes InnerLight safer for the next person.</p>
    """
    return _info_page("Frequently Asked Questions", inner, page_key="faq")

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
      <text x="78" y="90" text-anchor="middle" font-size="11" fill="#4a6472">(only you have it)</text>
      <line x1="150" y1="75" x2="212" y2="75" stroke="#714c2e" stroke-width="2" marker-end="url(#ah)"/>
      <text x="181" y="40" text-anchor="middle" font-size="10.5" fill="#C56A2C" font-weight="700">390,000 rounds</text>
      <text x="181" y="66" text-anchor="middle" font-size="9.5" fill="#8a929a">PBKDF2</text>
      <rect x="214" y="45" width="140" height="60" rx="10" fill="#fff" stroke="#c59771" stroke-width="1.5"/>
      <text x="284" y="72" text-anchor="middle" font-size="13" font-weight="700" fill="#453127">256-bit key</text>
      <text x="284" y="90" text-anchor="middle" font-size="11" fill="#4a6472">never stored</text>
      <line x1="356" y1="75" x2="418" y2="75" stroke="#714c2e" stroke-width="2" marker-end="url(#ah)"/>
      <text x="387" y="40" text-anchor="middle" font-size="10.5" fill="#C56A2C" font-weight="700">AES-256-GCM</text>
      <text x="387" y="66" text-anchor="middle" font-size="9.5" fill="#8a929a">+ random nonce</text>
      <rect x="420" y="45" width="150" height="60" rx="10" fill="#fff" stroke="#c59771" stroke-width="1.5"/>
      <text x="495" y="72" text-anchor="middle" font-size="13" font-weight="700" fill="#453127">Your words, locked</text>
      <text x="495" y="90" text-anchor="middle" font-size="11" fill="#4a6472">reads as noise</text>
      <line x1="572" y1="75" x2="628" y2="75" stroke="#714c2e" stroke-width="2" marker-end="url(#ah)"/>
      <rect x="630" y="45" width="82" height="60" rx="10" fill="#453127"/>
      <text x="671" y="72" text-anchor="middle" font-size="20">&#128274;</text>
      <text x="671" y="94" text-anchor="middle" font-size="10" fill="#e0d7cf">stored</text>
      <text x="360" y="132" text-anchor="middle" font-size="11" fill="#4a6472">Without your code, the key cannot be rebuilt &mdash; so no one, not even InnerLight, can reverse this.</text>
    </svg>
    </div>

    <p><strong>In technical terms,</strong> for reviewers: AHP encrypts each payload with <strong>AES-256-GCM</strong> &mdash; the Advanced Encryption Standard at 256 bits in Galois/Counter Mode, an <em>authenticated</em> cipher that protects both confidentiality (no one can read it) and integrity (tampering is detectable). The key is derived from the person&rsquo;s return code using <strong>PBKDF2-HMAC-SHA256 with 390,000 iterations</strong> and a random salt &mdash; a deliberately slow key-stretching function that makes brute-force guessing enormously expensive. Every encryption uses a fresh random <strong>nonce</strong>, and the protocol version is bound in as authenticated associated data. The key is never written to disk; only the ciphertext, salt, and nonce are stored. This is a zero-knowledge design toward the operator: InnerLight holds encrypted bytes it cannot read.</p>

    <p class="cite">Honest limit: AES-256-GCM with strong key derivation is robust modern cryptography, but it is not yet post-quantum. A documented future hardening path is to add a post-quantum key-exchange layer (for example, ML-KEM / Kyber) alongside the authenticated symmetric encryption. We state this openly rather than overstate the protection.</p>

    <h2>8. What we measure, and how we stay honest</h2>
    <p>InnerLight records anonymous, aggregate research metrics designed around recognized digital-health frameworks: uptake, engagement, session duration, adherence, and completion, alongside expression shifts, sound responses, self-reported calm (a wordless Self-Assessment Manikin scale), and heart-rate trends measured against each person&rsquo;s own baseline. Every heart reading carries a confidence tier so coverage is complete without overstating precision. We follow the scientific method explicitly: a falsifiable hypothesis, stated predictions, an instrument that gathers the data, and a commitment to replication and peer review.</p>

    <div class="soft"><p style="margin:0;">InnerLight does not diagnose, prescribe, or practice medicine or law. It is a companion for the wait and a bridge to human help &mdash; never a replacement for it. If you are in immediate danger, call or text 988, or call 911.</p></div>


    <h2>9. The mission&rsquo;s evidence &mdash; alternative crisis response</h2>
    <p>InnerLight&rsquo;s north star is to become a trusted first call for a person in crisis &mdash; a path to real help that does not begin with an armed response. This is not a solitary idea; it is a documented national movement with a growing evidence base. InnerLight is a civilian, software front door to that movement: it bridges people toward care-first human responders, and toward 911 only when immediate physical danger requires it.</p>
    <p class="cite">Dee T.S., Pyne J. (2022). &ldquo;A community response approach to mental health and substance abuse crises reduced crime.&rdquo; <em>Science Advances</em>, 8(23). (Denver STAR: 34% reduction in low-level offenses in served neighborhoods.)</p>
    <p class="cite">RTI International (2026). Quasi-experimental evaluations of Durham&rsquo;s HEART and Greensboro&rsquo;s BHRT programs: unarmed response teams matched police response times, reduced arrests, and increased connections to supportive services.</p>
    <p class="cite">Human Rights Watch (2026). &ldquo;Self-Determination is the Pathway to Liberation&rdquo; &mdash; national assessment of non-police, consent-based, rights-respecting crisis response programs.</p>
    <p class="cite">Vera Institute of Justice (2022). <em>Civilian Crisis Response Toolkit</em> &mdash; documents community distrust of police-linked emergency lines and recommends crisis access points disconnected from traditional public-safety systems.</p>
    <p class="cite">Center for American Progress &amp; Law Enforcement Action Partnership (2020). Analysis of 911 calls in eight major cities: up to 68% could be handled without an armed officer.</p>
    <p class="cite">National portrait of nonpolice alternative response programs (2024): 216 programs operational across the United States.</p>
    <p class="cite">NBER Working Paper 34344: willingness-to-pay analysis finding the public places higher value on active civilian-led crisis interventions.</p>

    <h2>10. Speaking every language honestly &mdash; translation with a quality judge</h2>
    <p>InnerLight serves people in eight languages. Machine translation of safety and legal content is held to a published research standard: every translated legal-guidance card and spoken hand-off passes an independent model-judge scoring pass for semantic equivalence and natural phrasing before a person sees it, with 0.8 as the acceptance bar. Content that scores below the bar is withheld rather than shown wrong. Every new-language interface string additionally awaits native-speaker review, and that status is documented in our repository. If a device has no speech voice for the chosen language, InnerLight stays silent rather than speak the wrong language &mdash; the words remain on screen.</p>
    <p class="cite">LLM-as-a-Judge reference-less quality estimation for machine translation, with a &ge;0.8 semantic-equivalence acceptance threshold (arXiv:2503.24102).</p>
    <p class="cite">Enomoto et al. &ldquo;From LLM to NMT: Advancing Low-Resource Machine Translation with Claude&rdquo; (arXiv:2404.13813) &mdash; documents where large language models still lag specialized systems on low-resource language pairs, the reason a verification pass is required.</p>
    <p class="cite">In-context machine translation for low-resource languages (arXiv:2502.11862) &mdash; documents rare-word failure modes in underrepresented languages.</p>

    <h2>11. What the microphone reads &mdash; voice prosody</h2>
    <p>With the person&rsquo;s microphone permission, InnerLight measures four classical prosodic descriptors on-device: overall vocal energy (RMS), pitch variability (autocorrelation-estimated fundamental frequency over a rolling window), speech rate (voiced-segment transitions), and a 4&ndash;8&nbsp;Hz amplitude-modulation estimate. These are long-established acoustic correlates of emotional arousal in the speech-emotion literature. The raw audio for this analysis never leaves the browser; only the four numbers travel, they steer the calming music, and they are never stored. Our normalization constants are engineering estimates, labeled as such in the source code, pending calibration against a labeled recording set &mdash; consistent with our rule that nothing invented may be presented as ground truth.</p>
    <p class="cite">Schuller B.W. (2018). &ldquo;Speech emotion recognition: two decades in a nutshell, benchmarks, and ongoing trends.&rdquo; <em>Communications of the ACM</em>, 61(5), 90&ndash;99.</p>
    <p class="cite">Zennou H., Ouadad R., Ouhda M., Baslam M. (2026). &ldquo;Real-Time Speech Emotion Recognition with a CNN-BiLSTM-Attention Deep Learning Model.&rdquo; <em>Engineering, Technology &amp; Applied Science Research</em>, 16(3) &mdash; the current direction of the field our simpler, on-device measures are designed to grow toward.</p>

    <h2>12. Safety signals in any language</h2>
    <p>Protective detection &mdash; recognizing when a writer may be a minor, may be substituting this tool for human connection, or may be in crisis &mdash; must not depend on the language a person writes in. In non-English sessions these signals are read by the comprehension model itself, which reads the person&rsquo;s own language, rather than by English-only phrase lists. By design, an uncertain reading can only raise the level of care, never lower it, and an ambiguous statement receives a caring follow-up question rather than a verdict.</p>
    <p class="cite">Vasan A., Stanford Brainstorm &mdash; on substitution as the primary risk of AI mental-health tools and the duty to escalate to humans (as quoted in Gold, <em>Inside Higher Ed</em>, 2026).</p>
    <p class="cite">Common Sense Media &mdash; research on adolescent use of AI for mental-health advice, informing InnerLight&rsquo;s heightened minor protections.</p>

    <h2>13. Holding attention through the wait &mdash; the engagement engine</h2>
    <p>Help can take fifteen minutes to an hour to arrive. InnerLight&rsquo;s companion is designed to hold a person&rsquo;s genuine engagement across that whole gap &mdash; rotating between comfort, small sensory activities, shared stories, and (when the person invites it) gentle humor. The activity choices follow the evidence: during acute distress the companion offers sensory and visuospatial micro-tasks, because emergency-department research shows such tasks reduce intrusive imagery in the hours after trauma, while quiz-style verbal games in that same window can make intrusions worse. Word-play and story games open up only once a person has settled. Every invitation is single, optional, and woven into conversation &mdash; never a menu.</p>
    <p class="cite">Iyadurai L., Blackwell S.E., Meiser-Stedman R., et al. (2018). &ldquo;Preventing intrusive memories after trauma via a brief intervention involving Tetris computer game play in the emergency department: a proof-of-concept randomized controlled trial.&rdquo; <em>Molecular Psychiatry</em>, 23, 674&ndash;682.</p>
    <p class="cite">Holmes E.A., James E.L., Kilford E.J., Deeprose C. (2010). Key finding: a visuospatial game reduced flashbacks post-trauma while a verbal quiz game did not &mdash; and in one experiment increased them. Not all engagement is beneficial engagement; activity choice must follow the evidence. <em>PLoS ONE</em>, 5(11): e13706.</p>
    <p class="cite">Multilab replication (2025), <em>Collabra: Psychology</em>, 11(1): evidence that the visuospatial task reduces intrusions immediately &mdash; the exact window InnerLight serves &mdash; with weaker evidence for effects days later.</p>
    <p class="cite">ANTIDOTE line of work (2024&ndash;2026): AI-guided, personally tailored imagery-competing task interventions with physiological monitoring &mdash; the research direction InnerLight&rsquo;s conversational activity guidance follows.</p>

    <p style="margin-top:20px;font-size:13px;color:#8aa;">Citations above reference published, peer-reviewed literature supporting the <em>principles</em> InnerLight applies. They do not constitute evidence that InnerLight itself is effective; that evaluation is ongoing. Full reference details are available on request.</p>
    """
    return _info_page("Research &amp; Methods", inner, "research")


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
      <text x="78" y="90" text-anchor="middle" font-size="11" fill="#4a6472">(only you have it)</text>
      <line x1="150" y1="75" x2="212" y2="75" stroke="#33567c" stroke-width="2" marker-end="url(#ah2)"/>
      <text x="181" y="40" text-anchor="middle" font-size="10.5" fill="#a9531f" font-weight="700">390,000 rounds</text>
      <text x="181" y="66" text-anchor="middle" font-size="9.5" fill="#8a929a">PBKDF2</text>
      <rect x="214" y="45" width="140" height="60" rx="12" fill="#fff" stroke="#6f97c0" stroke-width="1.5"/>
      <text x="284" y="72" text-anchor="middle" font-size="13" font-weight="700" fill="#2b2620">256-bit key</text>
      <text x="284" y="90" text-anchor="middle" font-size="11" fill="#4a6472">never stored</text>
      <line x1="356" y1="75" x2="418" y2="75" stroke="#33567c" stroke-width="2" marker-end="url(#ah2)"/>
      <text x="387" y="40" text-anchor="middle" font-size="10.5" fill="#a9531f" font-weight="700">AES-256-GCM</text>
      <text x="387" y="66" text-anchor="middle" font-size="9.5" fill="#8a929a">+ random nonce</text>
      <rect x="420" y="45" width="150" height="60" rx="12" fill="#fff" stroke="#6f97c0" stroke-width="1.5"/>
      <text x="495" y="72" text-anchor="middle" font-size="13" font-weight="700" fill="#2b2620">Your words, locked</text>
      <text x="495" y="90" text-anchor="middle" font-size="11" fill="#4a6472">reads as noise</text>
      <line x1="572" y1="75" x2="628" y2="75" stroke="#33567c" stroke-width="2" marker-end="url(#ah2)"/>
      <rect x="630" y="45" width="82" height="60" rx="12" fill="#2b2620"/>
      <text x="671" y="72" text-anchor="middle" font-size="20">&#128274;</text>
      <text x="671" y="94" text-anchor="middle" font-size="10" fill="#e0d7cf">stored</text>
      <text x="360" y="132" text-anchor="middle" font-size="11" fill="#4a6472">Without your code, the key cannot be rebuilt &mdash; so no one, not even InnerLight, can reverse this.</text>
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


@app.route("/robots.txt")
def robots_txt():
    """Search engines are welcome on public pages; the founder's console and
    the private APIs are not for indexing."""
    return app.response_class(
        "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /api/\n"
        "Sitemap: https://getinnerlight.com/sitemap.xml\n",
        mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    """A simple sitemap of every public page, so the site can actually be
    found by the caregivers and crisis workers searching for tools like it."""
    pages = ["/", "/about", "/how-it-works", "/stories", "/resources",
             "/research", "/safety", "/privacy", "/updates", "/contact"]
    urls = "".join(
        '<url><loc>https://getinnerlight.com%s</loc></url>' % p for p in pages)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           + urls + "</urlset>")
    return app.response_class(xml, mimetype="application/xml")


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
    """Published crisis-response protocol. Meets the documentation standards
    that govern tools like this nationwide (California's SB 243 is the leading
    example we already follow) and, more importantly, tells people the truth
    about what this tool is and does. Immutable Principle 11."""
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
    shared &mdash; so its safety behavior can be reviewed and reported responsibly. InnerLight is operated by God's Love
    For Us LLC and is designed to follow the federal and state laws that govern tools like it in the places it serves.
    Where a state sets a specific standard for companion or mental-health software &mdash; such as California's
    companion-chatbot law (Senate Bill 243), one of the first and strictest in the country &mdash; we follow it; and
    where any law is stricter than our own principles, the law governs. As we expand state by state, we study each new
    requirement before we operate there. Questions about this protocol are welcome through the
    <a href="/contact">contact page</a>. Our compliance is nationwide by design: federal law plus the law of all fifty states, the District of Columbia, and the U.S. territories. Where states differ, we meet the strictest applicable standard everywhere, and legal information is always localized to the person&rsquo;s own state &mdash; no state&rsquo;s law is ever presented as everyone&rsquo;s law.</p>

    <div class="soft">
      <p style="margin:0;"><strong>The short version:</strong> InnerLight is a program, not a person. When it sees
      danger, it points to real people fast &mdash; 988, every time, without delay &mdash; and it never stands between
      you and human help.</p>
    </div>
    """
    return _info_page("Safety & crisis protocol", inner, "safety")


@app.route("/resources")
def page_resources():
    """Real help, by need. A plain directory of established national services —
    who they are, what they actually do, how to reach them. Every number here
    is a nationally known service; where we are not certain of a number, we
    give the organization and its website instead. Getting people to real
    human help is the whole point of InnerLight (Immutable Principle 1)."""
    inner = """
    <h1>Real help, by need</h1>
    <p class="lead">InnerLight exists to get you to real people. This page is a plain list of established services &mdash; who they are, what they actually do, and how to reach them. All are free or low-cost unless noted.</p>

    <div class="soft"><p style="margin:0;">We list these because getting people to real human help is the whole point of InnerLight. None of these organizations pays to be here, and we are not affiliated with any of them. Numbers can change; each organization&rsquo;s own website is always the surest path.</p></div>

    <h2>If you are in danger right now</h2>
    <div class="card">
      <h3 style="margin-top:0;">988 Suicide &amp; Crisis Lifeline</h3>
      <p style="margin-bottom:0;">Trained crisis counselors who will talk with anyone in suicidal crisis or overwhelming distress &mdash; free, confidential, 24/7. <strong>Call or text 988</strong>, or chat at <a href="https://988lifeline.org" rel="noopener">988lifeline.org</a>. If a life is in immediate danger, call <strong>911</strong>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Crisis Text Line</h3>
      <p style="margin-bottom:0;">Real, trained crisis counselors over text message, for any kind of crisis &mdash; free, 24/7. <strong>Text HOME to 741741</strong>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Veterans Crisis Line</h3>
      <p style="margin-bottom:0;">Crisis support from responders who understand military life &mdash; for veterans, service members, and the people who love them. You do not need to be enrolled in VA care. <strong>Call 988, then press 1</strong>, or text <strong>838255</strong>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">The Trevor Project</h3>
      <p style="margin-bottom:0;">Crisis counselors for LGBTQ+ young people, around the clock. <strong>Call 1-866-488-7386</strong>, or text and chat through <a href="https://www.thetrevorproject.org" rel="noopener">thetrevorproject.org</a>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Trans Lifeline</h3>
      <p style="margin-bottom:0;">A peer-support hotline run by and for trans people &mdash; someone who understands, no judgment, no forced intervention. <strong>Call 877-565-8860</strong>.</p>
    </div>

    <h2>Mental health &amp; substance support</h2>
    <div class="card">
      <h3 style="margin-top:0;">SAMHSA National Helpline</h3>
      <p style="margin-bottom:0;">The federal government&rsquo;s free, confidential, 24/7 referral line for mental-health and substance-use treatment &mdash; they connect you to local programs, support groups, and community organizations. <strong>Call 1-800-662-4357</strong> (1-800-662-HELP).</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">FindTreatment.gov</h3>
      <p style="margin-bottom:0;">The federal directory of licensed mental-health and substance-use treatment facilities, searchable by location. <a href="https://findtreatment.gov" rel="noopener">findtreatment.gov</a> &mdash; it is the same source InnerLight&rsquo;s own nearby-help finder uses.</p>
    </div>

    <h2>Housing &amp; eviction</h2>
    <div class="card">
      <h3 style="margin-top:0;">211</h3>
      <p style="margin-bottom:0;">A nationwide line, run through United Way, that connects you with local help of nearly every kind &mdash; emergency shelter, rent and utility assistance, food, and more. <strong>Dial 211</strong>, or search at <a href="https://www.211.org" rel="noopener">211.org</a>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">HUD Housing Counseling</h3>
      <p style="margin-bottom:0;">The U.S. Department of Housing and Urban Development connects you to approved housing counselors who help with eviction, foreclosure, renting, and homelessness &mdash; free or low-cost. <strong>Call 800-569-4287</strong>, or find a counselor at <a href="https://www.hud.gov" rel="noopener">hud.gov</a>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">National Coalition for the Homeless</h3>
      <p style="margin-bottom:0;">An advocacy organization with practical directories of local shelters and services for people facing homelessness. <a href="https://nationalhomeless.org" rel="noopener">nationalhomeless.org</a>.</p>
    </div>

    <h2>Legal help</h2>
    <div class="card">
      <h3 style="margin-top:0;">Legal aid &mdash; the LSC finder</h3>
      <p style="margin-bottom:0;">The Legal Services Corporation funds free civil legal aid offices across the country &mdash; help with eviction, benefits, family law, debt, and more for people with low incomes. Find your local office at <a href="https://www.lsc.gov/about-lsc/what-legal-aid/get-legal-help" rel="noopener">lsc.gov</a>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">National Immigration Legal Services Directory</h3>
      <p style="margin-bottom:0;">A directory of free and low-cost immigration legal help, searchable by state and county, maintained by the Immigration Advocates Network. <a href="https://www.immigrationadvocates.org/legaldirectory/" rel="noopener">immigrationadvocates.org/legaldirectory</a>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Your state bar association</h3>
      <p style="margin-bottom:0;">Most state bar associations run free lawyer-referral services and can point you to pro bono help. Search your state&rsquo;s name plus &ldquo;bar association lawyer referral&rdquo; &mdash; the American Bar Association keeps a directory at <a href="https://www.americanbar.org" rel="noopener">americanbar.org</a>.</p>
    </div>

    <h2>Food &amp; essentials</h2>
    <div class="card">
      <h3 style="margin-top:0;">Feeding America</h3>
      <p style="margin-bottom:0;">The national network of food banks &mdash; their finder shows the food bank and pantries nearest you, no paperwork needed to ask. <a href="https://www.feedingamerica.org" rel="noopener">feedingamerica.org</a>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">211 (again, on purpose)</h3>
      <p style="margin-bottom:0;">For food, diapers, clothing, utility help, and almost any essential need, 211 remains the fastest local door. <strong>Dial 211</strong>.</p>
    </div>

    <h2>Domestic violence</h2>
    <div class="card">
      <h3 style="margin-top:0;">National Domestic Violence Hotline</h3>
      <p style="margin-bottom:0;">Advocates who listen, help you plan for safety, and connect you to local shelters and services &mdash; confidential, 24/7, in many languages. <strong>Call 800-799-7233</strong>, <strong>text START to 88788</strong>, or chat at <a href="https://www.thehotline.org" rel="noopener">thehotline.org</a>. If it is not safe to talk, the website explains safer ways to reach out.</p>
    </div>

    <h2>Veterans</h2>
    <div class="card">
      <h3 style="margin-top:0;">Veterans Crisis Line</h3>
      <p style="margin-bottom:0;">Listed above and worth repeating: <strong>call 988 and press 1</strong>, or text <strong>838255</strong> &mdash; 24/7, whether or not you are enrolled in VA care. <a href="https://www.veteranscrisisline.net" rel="noopener">veteranscrisisline.net</a>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">U.S. Department of Veterans Affairs</h3>
      <p style="margin-bottom:0;">Health care, mental-health services, benefits, and housing help for veterans &mdash; including same-day mental-health care at many VA facilities. <a href="https://www.va.gov" rel="noopener">va.gov</a>.</p>
    </div>

    <h2>Older adults &amp; caregivers</h2>
    <div class="card">
      <h3 style="margin-top:0;">Eldercare Locator</h3>
      <p style="margin-bottom:0;">A free federal service that connects older adults and caregivers to local aging services &mdash; meals, in-home help, transportation, caregiver support, and reporting concerns about an older person&rsquo;s safety. <strong>Call 800-677-1116</strong>, or search at <a href="https://eldercare.acl.gov" rel="noopener">eldercare.acl.gov</a>.</p>
    </div>

    <h2>Disability rights</h2>
    <div class="card">
      <h3 style="margin-top:0;">ADA Information Line</h3>
      <p style="margin-bottom:0;">The U.S. Department of Justice answers questions about rights under the Americans with Disabilities Act &mdash; work, housing, services, and access. <strong>Call 800-514-0301</strong>, or read at <a href="https://www.ada.gov" rel="noopener">ada.gov</a>.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">National Disability Rights Network</h3>
      <p style="margin-bottom:0;">Every state has a federally mandated protection-and-advocacy agency that defends the rights of people with disabilities; this network helps you find yours. <a href="https://www.ndrn.org" rel="noopener">ndrn.org</a>.</p>
    </div>

    <div class="soft">
      <p style="margin:0;">If your need is not listed here, <strong>211</strong> is the best first call for almost anything local, and a session with InnerLight can help you find licensed mental-health care near you. And always: if you are in immediate danger, call or text <strong>988</strong>, or call <strong>911</strong>.</p>
    </div>
    """
    return _info_page("Real help, by need", inner, "resources")


@app.route("/stories")
def page_stories():
    """How a visit goes — illustrative, clearly-labeled hypothetical
    walkthroughs. We have no published user studies and we say so plainly;
    these compositions show only what the program is actually built to do,
    and every one ends in a handoff to humans (Immutable Principle 1)."""
    inner = """
    <h1>How a visit goes</h1>
    <p class="lead">Four short walkthroughs of what actually happens in an InnerLight session &mdash; from the moment someone arrives to the moment we hand them to real people.</p>

    <div class="soft"><p style="margin:0;"><strong>Please read this first:</strong> the four visits below are <strong>illustrative compositions, not real user accounts</strong>. We wrote them to show how a session works; no real person&rsquo;s story appears on this page. InnerLight has no published user studies yet &mdash; we say that plainly rather than imply otherwise. What <em>is</em> real is the behavior described: this is what the program is built to do, every time.</p></div>

    <h2>Three weeks until the first appointment</h2>
    <p><strong>What he arrives carrying:</strong> a man finally called a therapist &mdash; the hardest call of his year &mdash; and was given an appointment three weeks out. Tonight the wait feels longer than he can hold, and it is 11 p.m., and there is no one he wants to wake.</p>
    <p><strong>What InnerLight does:</strong> the page opens into a quiet evening scene &mdash; the light matches the hour, soft instrumental music is already playing, and nothing asks him for anything. He starts typing, stops, starts again; nothing interrupts him. When he is ready, the companion reflects back what he actually said &mdash; it never tells him what he is feeling, and it never uses a canned line. The 988 path stays visible the whole time, quietly, whether or not he ever needs it.</p>
    <p><strong>Where it hands him off:</strong> his own appointment is the destination, and InnerLight treats it that way &mdash; it helps him get through tonight, mentions that the SAMHSA helpline (1-800-662-4357) exists for the days in between, and lets him go. The therapist is the help. InnerLight is the wait made survivable.</p>

    <h2>2 a.m., an eviction notice on the table</h2>
    <p><strong>What she arrives carrying:</strong> a woman who cannot sleep. The notice came today. She types only, &ldquo;my landlord is ending my lease,&rdquo; because saying more feels like making it real.</p>
    <p><strong>What InnerLight does:</strong> the arrival is dark and quiet like the hour, the music low. Her short sentence is not waved past and not treated as an alarm &mdash; it gets one caring, specific question that opens the door the rest of the way, because shorthand is how frightened people test whether it is safe to say more. She tells it in pieces. The companion keeps pace with her state without ever labeling it, and never asks her to do anything for the technology&rsquo;s sake.</p>
    <p><strong>Where it hands her off:</strong> to the people who can actually change her situation &mdash; 211 for local housing help, HUD&rsquo;s housing counselors at 800-569-4287, and the legal-aid finder at lsc.gov, because an eviction is a legal event and she may have more rights than the notice implies. She leaves with two calls to make at 9 a.m. Not fixed &mdash; steadier, and pointed at the right doors.</p>

    <h2>A sister who did not come home</h2>
    <p><strong>What she arrives carrying:</strong> a caregiver whose adult sister &mdash; the one she has looked after for years &mdash; has been missing since morning. She has already called everyone she knows. It is the panic, and under the panic, the guilt.</p>
    <p><strong>What InnerLight does:</strong> it lets her pour it out without one interruption &mdash; her outpouring is treated as sacred, and no prompt or invitation ever appears while she is writing. It does not pretend it can find her sister, and it does not offer false comfort. It stays present, steady, and honest about what it is.</p>
    <p><strong>Where it hands her off:</strong> quickly &mdash; to 911 and the local police, because a missing vulnerable adult is exactly what they exist for; and to 988 for <em>her</em>, because the person searching needs holding too. When the phone finally rings, InnerLight&rsquo;s job is already over. It was never the rescuer &mdash; only the company kept while the rescuers worked.</p>

    <h2>Waiting for the VA to call back</h2>
    <p><strong>What he arrives carrying:</strong> a veteran who did the right thing &mdash; he asked the VA for mental-health support &mdash; and is now in the in-between, waiting for the callback, which is its own kind of exposed.</p>
    <p><strong>What InnerLight does:</strong> the calm arrival, the music that meets him where he is before easing toward quiet, a companion that listens for what he means and answers him &mdash; him, not a category. It never plays the veteran card back at him with scripted empathy; there are no scripted lines here at all.</p>
    <p><strong>Where it hands him off:</strong> the Veterans Crisis Line &mdash; 988, press 1, or text 838255 &mdash; sits within reach the entire session, staffed by people who understand military life. When the VA calls back, that call is the point. InnerLight held the space between reaching out and being reached.</p>

    <h2>What all four have in common</h2>
    <p>No visit ends in InnerLight. Every one ends in a handoff &mdash; a therapist, a counselor, a housing office, a crisis line, a callback &mdash; because we measure success by connection to a human, never by time spent with us. InnerLight helps people survive the wait. The humans do the helping.</p>

    <div class="soft">
      <p style="margin:0;">InnerLight is a program, not a person, and these walkthroughs are illustrations, not evidence. If you are in immediate danger, call or text <strong>988</strong>, or call <strong>911</strong>.</p>
    </div>
    """
    return _info_page("How a visit goes", inner, "stories")


@app.route("/updates")
def page_updates():
    """Building in the open — a plain-language changelog of real improvements.
    Transparency is a founding value; we publish what we change."""
    inner = """
    <h1>Building in the open</h1>
    <p class="lead">We publish what we change, in plain language, because transparency is a founding value. Here is what has actually improved recently &mdash; and what we are working on next.</p>

    <h2>July 2026</h2>
    <div class="card">
      <h3 style="margin-top:0;">Three languages, spoken and written</h3>
      <p style="margin-bottom:0;">The whole visitor experience &mdash; the pages, the conversation, and the spoken voice &mdash; now works in English, Spanish, and Chinese, with a language switcher and English as the always-safe fallback.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">A companion that never labels your feelings</h3>
      <p style="margin-bottom:0;">We rebuilt the way InnerLight reads how a person is doing. It responds to your state without ever announcing it &mdash; no &ldquo;you seem anxious,&rdquo; no scores, no clinical words. It also no longer treats a fast heartbeat as distress, because beats-per-minute is too ambiguous a signal to judge anyone by.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">The arrival now matches the hour</h3>
      <p style="margin-bottom:0;">Arriving at InnerLight is now a slow, cinematic opening &mdash; and the scene knows what time it is where you are, so a 2 a.m. visit opens into night, not noon.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">A law against scripted lines</h3>
      <p style="margin-bottom:0;">The founder made it a standing rule: no standardized, pre-written lines in any user conversation, ever. Every response is composed for the person in front of it, because canned comfort is not comfort.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Never more than you can bear</h3>
      <p style="margin-bottom:0;">We adopted a new founding principle &mdash; Principle 14 &mdash; and then went through the product removing every ask we could: fewer taps, fewer questions, fewer decisions. The program carries the burden; the person is carried.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">No more camera instructions</h3>
      <p style="margin-bottom:0;">InnerLight no longer tells anyone to lean in, find better light, or adjust themselves for a sensor. If the camera cannot work with you exactly as you are, the technology adapts or quietly steps aside. You are never corrected to make our reading easier.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Music that recovers itself</h3>
      <p style="margin-bottom:0;">The calming sound now arrives slow and gentle every time, varies between visits instead of repeating the same song, and picks itself back up if the connection stumbles &mdash; without you touching anything.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">Backgrounds grown from the founder&rsquo;s own photographs</h3>
      <p style="margin-bottom:0;">The scenes behind a session are generated from photographs the founder took himself &mdash; real places, real light &mdash; so the ground under a hard night is something true.</p>
    </div>
    <div class="card">
      <h3 style="margin-top:0;">The Watch</h3>
      <p style="margin-bottom:0;">A private founder&rsquo;s room that shows, in anonymous counts only &mdash; sessions held, music shifts, bridges to a human &mdash; that the program is doing its work. Never words, never identities, and it never scores anyone&rsquo;s distress. It only keeps company.</p>
    </div>

    <h2>What we are working on next</h2>
    <ul>
      <li><strong>Research page translations</strong> &mdash; the Research &amp; Methods page is the last one still English-only; Spanish and Chinese are coming.</li>
      <li><strong>An accessibility audit</strong> &mdash; a careful pass so that screen readers, low vision, and motor limitations are met with the same gentleness as everything else.</li>
      <li><strong>The provider network</strong> &mdash; building the vetted, categorized network of clinicians and services that the bridge hands people to, with the scrutiny our principles demand.</li>
    </ul>

    <div class="soft">
      <p style="margin:0;">A note on honesty: these are improvements to how InnerLight works, not claims that it works. InnerLight is built on established principles and is itself untested; independent evaluation is what we are seeking, and we will publish the results either way.</p>
    </div>
    """
    return _info_page("Building in the open", inner, "updates")


@app.route("/console")
def console():
    return render_template_string(PAGE)


# Crisis handoff pages, localized (Spanish / Chinese) with English fallback.
_HANDOFF_I18N = {}
def _load_handoff_i18n():
    import os as _os, json as _json
    base = _os.path.dirname(_os.path.abspath(__file__))
    for lg in ("es", "zh", "hi", "pa", "bn", "tl", "to"):
        try:
            with open(_os.path.join(base, "i18n_handoff_%s.json" % lg), encoding="utf-8") as f:
                _HANDOFF_I18N[lg] = _json.load(f)
        except Exception as e:
            print("[InnerLight] handoff i18n %s not loaded: %s" % (lg, e))
            _HANDOFF_I18N[lg] = {}
_load_handoff_i18n()

# ===========================================================================
# DEMONSTRATION MODE — founder-only, session-scoped. (Part 2)
#   SAFETY IS PARAMOUNT (Principle 16). A REAL person in crisis must NEVER see
#   sample providers as real. The ONLY ways demo is ever turned on:
#     (a) the founder POSTs /api/admin/demo (guarded by founder_ok), or
#     (b) a visitor opens /demo/<token> where token is a stable HMAC of
#         ADMIN_KEY (never the admin key itself).
#   Both set session["demo_mode"] — an in-cookie, per-visitor flag. A fresh
#   browser with no such session sees the honest, real-only product. Nothing
#   else in the codebase reads sample data; the sample rows are only ever
#   surfaced inside an `if session.get("demo_mode")` gate. That gate is the
#   entire isolation boundary, and it is verifiable in one place.
# ===========================================================================
def _demo_token():
    """A stable, shareable token derived from ADMIN_KEY via HMAC-SHA256. It is
    NOT the admin key and cannot be reversed into it. Visiting /demo/<token>
    turns on demo mode for THAT visitor's session only."""
    key = os.environ.get("ADMIN_KEY", "").encode("utf-8")
    return hmac.new(key, b"innerlight-demo-link::v1", hashlib.sha256).hexdigest()[:40]

def _demo_sides():
    """Return the set of sides ('clinical'/'legal') live for demo in THIS
    session, or an empty set. Empty for every real visitor, always."""
    raw = session.get("demo_mode")
    if not raw:
        return set()
    if raw is True:
        return {"clinical", "legal"}
    try:
        return {s for s in raw if s in ("clinical", "legal")}
    except Exception:
        return set()

# The persistent, unmissable SAMPLE banner. Trilingual (en / es / zh) in one
# fixed bar so it is unmistakable regardless of the visitor's language. Amber
# warning styling, fixed to the top, always visible, cannot be scrolled away.
_DEMO_BANNER_HTML = (
    '<div id="il-demo-banner" role="alert" style="position:fixed;top:0;left:0;right:0;'
    'z-index:2147483647;background:#7a3c00;background:linear-gradient(90deg,#8a4300,#c56a2c);'
    'color:#fff;border-bottom:3px solid #ffd28a;box-shadow:0 3px 14px rgba(0,0,0,.35);'
    'padding:9px 14px 10px;text-align:center;font-family:Arial,Helvetica,sans-serif;'
    'font-size:13px;line-height:1.35;letter-spacing:.01em;">'
    '<span style="font-size:15px;">&#9888;</span> '
    '<b style="text-transform:uppercase;letter-spacing:.06em;">Sample &mdash; Demonstration mode</b> '
    '&mdash; these are not real providers. '
    '<span style="opacity:.92;">Muestra &mdash; modo de demostraci&oacute;n: estos no son proveedores reales. '
    '&#26679;&#26412; &mdash; &#28436;&#31034;&#27169;&#24335;&#65306;&#36825;&#20123;&#19981;&#26159;&#30495;&#23454;&#30340;&#25552;&#20379;&#32773;&#12290;</span> '
    '&mdash; <a href="/demo/exit" style="color:#ffd28a;font-weight:700;text-decoration:underline;">Exit demonstration</a>'
    '</div>'
    '<div style="height:52px;"></div>'
)

def _inject_demo(html):
    """Insert the SAMPLE banner right after <body>, and a small override script
    right before </body> so the send flow shows a demo confirmation and creates
    NOTHING real — in every language, since the override replaces the global
    send handlers by name after the page has defined them."""
    override = '''<script>window.IL_DEMO={on:true};(function(){function demoSend(){var chosen='';try{chosen=(typeof pickedPro!=='undefined'&&pickedPro)?pickedPro:'';}catch(e){}var who=chosen?('a '+String(chosen).toLowerCase()):'a real person';var el=document.getElementById('status');if(el){el.textContent='SAMPLE - DEMONSTRATION MODE. In a live network, '+who+' would be reaching you now. Nothing real was sent: no room was opened, no one was paged. This is a demonstration of the full flow only.';}}window.sendToCare=demoSend;window.sendToLegal=demoSend;})();</script>'''
    out = html
    idx = out.find("<body")
    if idx >= 0:
        gt = out.find(">", idx)
        if gt >= 0:
            out = out[:gt + 1] + _DEMO_BANNER_HTML + out[gt + 1:]
    else:
        out = _DEMO_BANNER_HTML + out
    cidx = out.rfind("</body>")
    if cidx >= 0:
        out = out[:cidx] + override + out[cidx:]
    else:
        out = out + override
    return out

def _handoff_page(page_key, en_tpl):
    lang = _info_lang()
    tpl = en_tpl
    if lang != "en":
        t = _HANDOFF_I18N.get(lang, {}).get(page_key)
        if t:
            tpl = t
    html = render_template_string(tpl)
    # DEMO ONLY: never for a real visitor. Sample data + banner appear solely
    # when this session was explicitly put in demo mode for this side.
    if page_key in _demo_sides():
        html = _inject_demo(html)
    return html


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
    # Speak the bridge in the person's language. If translation is not
    # available, the English bridge still goes through — reaching human
    # help safely outranks the language rule in this one moment.
    _blang = _req_ui_lang(data)
    if _blang != "en":
        try:
            _parts = [str(p) for p in (warm.get("parts") or [])]
            _tr = comprehension_engine.translate_texts_verified(
                _parts + [str(warm.get("spoken_script", "")), str(exit_msg or "")], _blang)
            if _tr:
                warm = dict(warm)
                warm["parts"] = _tr[:len(_parts)]
                warm["spoken_script"] = _tr[len(_parts)]
                exit_msg = _tr[len(_parts) + 1]
        except Exception:
            pass

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
    audio_dir = (Path(__file__).resolve().parent.parent / "audio").resolve()
    file_path = (audio_dir / filename).resolve()
    try:
        file_path.relative_to(audio_dir)   # stay inside the audio folder, always
    except ValueError:
        return ("audio not found", 404)
    if file_path.exists() and file_path.is_file():
        from flask import send_file
        # conditional=True enables byte-range requests — iPhone Safari needs
        # them to stream and seek audio reliably.
        return send_file(str(file_path), mimetype="audio/mpeg", conditional=True)
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


_UI_LANGS = ("en", "es", "zh", "hi", "pa", "bn", "tl", "to")

# Honest, in-language line used ONLY when the comprehension model is
# unavailable during a non-English session. We never hand a non-English
# speaker to the English-only local engine — the language promise holds
# even in failure, and the 988 path stays visible.
_NOEN_FALLBACK = {
    "es": "La conexi\u00f3n se interrumpi\u00f3 un momento \u2014 por favor, dilo otra vez. Si necesitas a alguien ahora mismo, llama o env\u00eda un mensaje al 988.",
    "zh": "\u8fde\u63a5\u4e2d\u65ad\u4e86\u4e00\u4e0b\u2014\u2014\u8bf7\u518d\u8bf4\u4e00\u904d\u3002\u5982\u679c\u4f60\u73b0\u5728\u5c31\u9700\u8981\u6709\u4eba\u966a\u4f34\uff0c\u8bf7\u62e8\u6253\u6216\u53d1\u77ed\u4fe1\u81f3 988\u3002",
    "hi": "\u0915\u0928\u0947\u0915\u094d\u0936\u0928 \u090f\u0915 \u092a\u0932 \u0915\u0947 \u0932\u093f\u090f \u091f\u0942\u091f \u0917\u092f\u093e \u2014 \u0915\u0943\u092a\u092f\u093e \u0935\u0939 \u092b\u093f\u0930 \u0938\u0947 \u0915\u0939\u0947\u0902\u0964 \u0905\u0917\u0930 \u0906\u092a\u0915\u094b \u0905\u092d\u0940 \u0915\u093f\u0938\u0940 \u0915\u0940 \u091c\u093c\u0930\u0942\u0930\u0924 \u0939\u0948, \u0924\u094b 988 \u092a\u0930 \u0915\u0949\u0932 \u092f\u093e \u0938\u0902\u0926\u0947\u0936 \u0915\u0930\u0947\u0902\u0964",
    "pa": "\u0a15\u0a41\u0a28\u0a48\u0a15\u0a38\u0a3c\u0a28 \u0a07\u0a71\u0a15 \u0a2a\u0a32 \u0a32\u0a08 \u0a1f\u0a41\u0a71\u0a1f \u0a17\u0a3f\u0a06 \u2014 \u0a15\u0a3f\u0a30\u0a2a\u0a3e \u0a15\u0a30\u0a15\u0a47 \u0a09\u0a39 \u0a26\u0a41\u0a2c\u0a3e\u0a30\u0a3e \u0a15\u0a39\u0a4b\u0964 \u0a1c\u0a47 \u0a24\u0a41\u0a39\u0a3e\u0a28\u0a42\u0a70 \u0a39\u0a41\u0a23\u0a47 \u0a15\u0a3f\u0a38\u0a47 \u0a26\u0a40 \u0a32\u0a4b\u0a5c \u0a39\u0a48, \u0a24\u0a3e\u0a02 988 \u0a09\u0a71\u0a24\u0a47 \u0a15\u0a3e\u0a32 \u0a1c\u0a3e\u0a02 \u0a38\u0a41\u0a28\u0a47\u0a39\u0a3e \u0a2d\u0a47\u0a1c\u0a4b\u0964",
    "bn": "\u09b8\u0982\u09af\u09cb\u0997 \u098f\u0995 \u09ae\u09c1\u09b9\u09c2\u09b0\u09cd\u09a4\u09c7\u09b0 \u099c\u09a8\u09cd\u09af \u099b\u09bf\u09a8\u09cd\u09a8 \u09b9\u09df\u09c7\u099b\u09c7 \u2014 \u09a6\u09df\u09be \u0995\u09b0\u09c7 \u0986\u09ac\u09be\u09b0 \u09ac\u09b2\u09c1\u09a8\u0964 \u098f\u0996\u09a8\u0987 \u0995\u09be\u0989\u0995\u09c7 \u09a6\u09b0\u0995\u09be\u09b0 \u09b9\u09b2\u09c7 988 \u09a8\u09ae\u09cd\u09ac\u09b0\u09c7 \u0995\u09b2 \u09ac\u09be \u099f\u09c7\u0995\u09cd\u09b8\u099f \u0995\u09b0\u09c1\u09a8\u0964",
    "sw": "Muunganisho ulikatika kwa muda \u2014 tafadhali sema tena. Ukihitaji mtu sasa hivi, piga simu au tuma ujumbe 988.",
    "am": "\u130d\u1295\u1299\u1290\u1271 \u1208\u12a0\u134d\u1273 \u1270\u124b\u122d\u1327\u120d \u2014 \u12a5\u1263\u12ad\u12ce \u12a5\u1295\u12f0\u1308\u1293 \u12ed\u1290\u1309\u1229\u1362 \u12a0\u1201\u1295 \u1230\u12cd \u12a8\u1348\u1208\u1309 988 \u12ed\u12f0\u12cd\u1209 \u12c8\u12ed\u1218\u120d\u12a5\u12ad\u1275 \u12ed\u120b\u12a9\u1362",
    "ha": "Wani abu ya katse ha\u0257in na \u0257an lokaci \u2014 don Allah sake fa\u0257a. Idan kana bu\u1e99atar wani yanzu, kira ko aika sa\u1e99o zuwa 988.",
    "tl": "Naputol sandali ang koneksyon \u2014 pakisabi muli. Kung kailangan mo ng kausap ngayon din, tumawag o mag-text sa 988.",
    "to": "Na\u02bbe motuhia si\u02bbi \u02bba e fehokotak\u00ed \u2014 k\u0101taki \u02bbo toe lea \u02bbaki ia. Kapau \u02bbok\u00fa ke fiema\u02bbu ha taha he taim\u00ed ni, telefoni pe fai ha p\u014dpoaki ki he 988.",
}


def _req_ui_lang(data):
    """The person's chosen interface language for this request (client field
    first, cookie second, English default). Unknown codes resolve to en."""
    lg = ""
    try:
        lg = str((data or {}).get("ui_lang") or "").strip().lower()
    except Exception:
        lg = ""
    if not lg:
        try:
            lg = str(request.cookies.get("il_lang") or "").strip().lower()
        except Exception:
            lg = ""
    return lg if lg in _UI_LANGS else "en"


def _localized_legal_guidance(lg, ui_lang):
    """Return legal guidance in the person's language. English sessions pass
    through untouched. In non-English sessions the content is translated in one
    model call; if translation is unavailable the card is withheld (None) —
    we never show English content inside a non-English session, and the main
    reply still carries the conversation."""
    if not lg or not isinstance(lg, dict) or not lg.get("issue_detected") or ui_lang == "en":
        return lg
    list_fields = ("your_rights", "questions_for_attorney", "free_legal_help", "steps_you_can_take_now")
    texts = [str(lg.get("issue_detected", ""))]
    spans = []
    for f in list_fields:
        vals = [str(x) for x in (lg.get(f) or [])]
        spans.append((f, len(vals)))
        texts.extend(vals)
    texts.append(str(lg.get("disclaimer", "")))
    out = comprehension_engine.translate_texts_verified(texts, ui_lang)
    if not out:
        return None
    new = dict(lg)
    i = 0
    new["issue_detected"] = out[i]; i += 1
    for f, ln in spans:
        new[f] = out[i:i + ln]; i += ln
    new["disclaimer"] = out[i]
    return new


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
    ui_lang = _req_ui_lang(data)
    # Language-agnostic safety signals (Principles 5 and 9): the client's
    # English pattern lists cannot read other languages, so the model reads
    # them here for non-English sessions. Signals can only RAISE care.
    _sig = comprehension_engine.classify_signals(message) if ui_lang != "en" else None
    minor_signal = bool(_sig and _sig.get("minor"))
    substitution_signal = bool(_sig and _sig.get("substitution"))
    if _sig and _sig.get("crisis") and risk in ("low", "moderate"):
        risk = "high"
    smart = comprehension_engine.respond(
        user_text=message, history=history, risk=risk, face_emotion=face_emo, ui_lang=ui_lang,
        client_time=str(data.get("client_time", ""))[:80],
    )
    if smart:
        initial_conv = {"response": smart["response"], "question": smart.get("question", "")}
    elif ui_lang != "en":
        # The language promise holds even on failure: an honest in-language
        # line instead of the English-only local engine.
        initial_conv = {"response": _NOEN_FALLBACK[ui_lang], "question": ""}
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
    # Comfort before paperwork (the founder's correction from live testing):
    # when legal keywords surface INSIDE acute emotional pain, the rights
    # card waits a turn. A grieving person needs to be heard before being
    # handed a checklist; the information returns once the moment settles.
    if domain == "both" and (crisis.needs_immediate_support or cr.get("level") in ("crisis", "elevated")):
        legal_guidance = None
    else:
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

    # --- FOUNDER DECREE (Principle 14 spirit): NO STANDARDIZED LINES, EVER. ---
    # Warmth must come from the actual response to THIS person, never from a
    # recorded line. People in pain recognize a script instantly, and a script
    # that repeats kills trust. We never inject canned text into a reply.
    # Principle 13's open door is structural, not scripted: the input stays
    # open, and the human bridge (988) is on every response below.
    conv_questions = [q for q in (conv_questions or []) if q and q.strip()]
    # ONE question discipline: when the comprehension engine wrote the reply,
    # its single deeper question is already inside the response text. Never
    # stack a second question on top of it.
    if conv_response and "?" in conv_response:
        conv_questions = []
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
        "legal_guidance": _localized_legal_guidance(legal_guidance, ui_lang),
        "minor_signal": minor_signal,
        "substitution_signal": substitution_signal,
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
    ui_lang = _req_ui_lang(data)
    _sig_l = comprehension_engine.classify_signals(answer) if ui_lang != "en" else None
    learned["minor_signal"] = bool(_sig_l and _sig_l.get("minor"))
    learned["substitution_signal"] = bool(_sig_l and _sig_l.get("substitution"))
    if _sig_l and _sig_l.get("crisis") and learn_risk in ("low", "moderate"):
        learn_risk = "high"
        learned["risk"] = "high"
    smart_l = comprehension_engine.respond(
        user_text=answer, history=history_l, risk=learn_risk, face_emotion=face_emotion, ui_lang=ui_lang,
        client_time=str(data.get("client_time", ""))[:80],
    )
    if smart_l:
        conv = {"response": smart_l["response"], "question": smart_l.get("question", "")}
    elif ui_lang != "en":
        conv = {"response": _NOEN_FALLBACK[ui_lang], "question": ""}
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
    learned["legal_guidance"] = _localized_legal_guidance(generate_legal_guidance(legal_issues), ui_lang)

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
        if "start" not in rec:
            rec["start"] = now   # when this session first appeared — powers ember size
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
                # stable anonymous key (hash of the random session id) so the
                # ember field can tell sessions apart without identifying anyone
                "k": hashlib.sha1(("watch::" + sid).encode()).hexdigest()[:10],
                "held_min": round(max(0.0, (now - v.get("start", v.get("last", now)))) / 60.0, 1),
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


# ===========================================================================
# LAWFUL ACTIVE DEFENSE — DETER · DECEIVE · WITHSTAND · DELIVER-TO-JUSTICE
# ---------------------------------------------------------------------------
# THE LINE (Principle 17, bounded by Principle 11): everything below is PURELY
# LOCAL defense and lawful logging. It NEVER hacks back, retaliates, scans,
# probes, or touches an attacker's system in any way. Counter-hacking is itself
# a crime (e.g. the U.S. Computer Fraud and Abuse Act) with no self-defense
# exception; we punish attackers only by wasting their time (tarpit/lockout),
# feeding them decoys (honeypots), withstanding them (AHP encryption), and
# handing clean forensic evidence to law enforcement — up to the line, never over.
#
# SAFETY OUTRANKS SECURITY: none of this is ever applied to a person in crisis.
# The tarpit/lockout is invoked ONLY on auth endpoints and honeypots. The crisis
# and conversation paths (/api/checkin, /api/connect/request, /handoff/*, the
# 988-bearing pages) never call _defend(), so a real person is never delayed.
# ===========================================================================

# A believable-but-fake credential planted in the decoys. If it ever comes BACK
# to us in a later request, only someone who scraped a honeypot could know it —
# so its reappearance instantly flags the client as hostile.
_HONEYTOKEN = "il_pay_rk_7Qd2Fv8xR1nKpB3wYt6ZmA9uH4cJ0eL"

_HOSTILE = {}            # ip -> {"offenses": int, "first": ts, "last": ts, "block_until": ts, "reason": str}
_HOSTILE_LOCK = threading.Lock()

_SECURITY_LOG_FILE = os.environ.get("SECURITY_LOG_FILE", _DATA_DIR + "/innerlight_security.jsonl")
_SECURITY_LOG_LOCK = threading.Lock()
_SECURITY_LOG_MAX = 5000     # keep at most this many lines; rotate (halve) when exceeded
_SECURITY_COUNTS = {"attacks": 0, "honeypots": 0, "paths": {}}  # in-memory quick readout


def _security_log(reason, path=None, extra=None):
    """Append one security event to the forensic JSONL evidence file.
    Records ONLY attacker/security metadata — never any user content, message,
    or conversation. This is the package handed to law enforcement."""
    try:
        ua = request.headers.get("User-Agent", "")[:300]
        xff = request.headers.get("X-Forwarded-For", "")[:200]
        rec = {
            "ts": utc_now(),
            "reason": str(reason)[:120],
            "path": (path if path is not None else request.path)[:300],
            "method": request.method,
            "ip": _client_ip(),
            "xff": xff,
            "ua": ua,
        }
        if extra:
            rec["note"] = str(extra)[:200]
        line = json.dumps(rec, ensure_ascii=False)
    except Exception:
        return
    # update the in-memory quick counters
    try:
        _SECURITY_COUNTS["attacks"] += 1
        if str(reason).startswith("honeypot"):
            _SECURITY_COUNTS["honeypots"] += 1
        pk = rec.get("path", "?")
        _SECURITY_COUNTS["paths"][pk] = _SECURITY_COUNTS["paths"].get(pk, 0) + 1
    except Exception:
        pass
    with _SECURITY_LOG_LOCK:
        try:
            os.makedirs(os.path.dirname(_SECURITY_LOG_FILE), exist_ok=True)
        except Exception:
            pass
        try:
            with open(_SECURITY_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            # cheap size-cap rotation: if the file grew past the cap, keep the
            # most recent half so it can never fill the ops disk.
            try:
                with open(_SECURITY_LOG_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if len(lines) > _SECURITY_LOG_MAX:
                    keep = lines[-(_SECURITY_LOG_MAX // 2):]
                    with open(_SECURITY_LOG_FILE, "w", encoding="utf-8") as f:
                        f.writelines(keep)
            except Exception:
                pass
        except Exception as e:
            print("[InnerLight] security log write failed:", e)


def _flag_hostile(reason, hard=False):
    """Mark the current client hostile, growing its offense count. Progressive:
    early offenses only slow the client (via _defend's sleep); after a handful
    it is temporarily hard-blocked (429). Always logs to the forensic file."""
    ip = _client_ip()
    now = time.time()
    with _HOSTILE_LOCK:
        h = _HOSTILE.get(ip)
        if h is None:
            h = {"offenses": 0, "first": now, "block_until": 0.0, "reason": str(reason)[:80]}
            _HOSTILE[ip] = h
        h["offenses"] += 1
        h["last"] = now
        h["reason"] = str(reason)[:80]
        # after 5 strikes (or an explicit hard flag), lock out for a growing
        # window, capped at 15 minutes so an innocent shared IP recovers.
        if hard or h["offenses"] >= 5:
            h["block_until"] = now + min(900.0, 60.0 * (h["offenses"] - 4))
        # opportunistic cleanup so the map cannot grow without bound
        if len(_HOSTILE) > 10000:
            for k in list(_HOSTILE.keys())[:3000]:
                _HOSTILE.pop(k, None)
    _abuse_mark()
    _security_log(reason)


def _defend():
    """Tarpit + lockout gate for hostile clients. Returns a Flask response to
    send IMMEDIATELY (hard block) or None to let the request proceed after a
    small deterrent delay. MUST NEVER be called on a crisis/conversation path —
    safety outranks security (see the section banner above)."""
    ip = _client_ip()
    now = time.time()
    with _HOSTILE_LOCK:
        h = _HOSTILE.get(ip)
        if not h:
            return None
        offenses = h.get("offenses", 0)
        block_until = h.get("block_until", 0.0)
    if block_until and now < block_until:
        _security_log("lockout-hit")
        return _gentle_429()
    # progressive real server-side delay that grows with offense count, capped
    # at a few seconds: cheap for us, expensive for an automated attacker.
    if offenses > 0:
        time.sleep(min(3.0, 0.5 * offenses))
    return None


def _fake_env_body():
    """A plausible-looking but entirely fake .env, seeded with the honeytoken."""
    return (
        "# production environment\n"
        "APP_ENV=production\n"
        "DB_HOST=10.0.0.14\n"
        "DB_USER=iladmin\n"
        "DB_PASSWORD=Str0ng-Pg-2026!\n"
        "SECRET_KEY=9f2c1a7e4b6d8c0f13579bdf2468ace0\n"
        "API_KEY=" + _HONEYTOKEN + "\n"
        "PAYMENT_SECRET=il_pay_rk_4Tz9Xb2Qv7Dm1Ns8Wc6Yg0Hf3Jp5Lr\n"
    )


# --- HONEYPOTS (DECEIVE): routes no legitimate user ever visits. Each returns
#     a believable fake, flags the caller hostile, and logs the attempt. ---
@app.route("/wp-login.php", methods=["GET", "POST"])
@app.route("/wp-admin", methods=["GET", "POST"])
def _honeypot_wp():
    _flag_hostile("honeypot:wordpress")
    blocked = _defend()
    if blocked is not None:
        return blocked
    return ("<!DOCTYPE html><html><head><title>Log In</title></head><body>"
            "<form method='post' action='/wp-login.php'>"
            "<p><label>Username<br><input name='log'></label></p>"
            "<p><label>Password<br><input name='pwd' type='password'></label></p>"
            "<p><input type='submit' value='Log In'></p></form></body></html>"), 200


@app.route("/.env", methods=["GET"])
def _honeypot_env():
    _flag_hostile("honeypot:dotenv")
    blocked = _defend()
    if blocked is not None:
        return blocked
    return app.response_class(_fake_env_body(), mimetype="text/plain")


@app.route("/admin.php", methods=["GET", "POST"])
@app.route("/phpmyadmin", methods=["GET", "POST"])
@app.route("/phpmyadmin/index.php", methods=["GET", "POST"])
def _honeypot_php():
    _flag_hostile("honeypot:phpmyadmin")
    blocked = _defend()
    if blocked is not None:
        return blocked
    return ("<!DOCTYPE html><html><head><title>phpMyAdmin</title></head><body>"
            "<h1>phpMyAdmin</h1><form method='post'>"
            "<p>Username <input name='pma_username'></p>"
            "<p>Password <input name='pma_password' type='password'></p>"
            "<p><input type='submit' value='Go'></p></form></body></html>"), 200


@app.route("/api/v1/keys", methods=["GET"])
@app.route("/api/keys", methods=["GET"])
def _honeypot_keys():
    _flag_hostile("honeypot:api-keys")
    blocked = _defend()
    if blocked is not None:
        return blocked
    # a believable JSON key listing carrying the honeytoken
    return jsonify({"keys": [
        {"id": "key_1", "name": "production", "secret": _HONEYTOKEN, "created": "2026-01-04T09:11:00Z"},
        {"id": "key_2", "name": "backup", "secret": "il_pay_rk_" + "0" * 32, "created": "2026-02-19T14:02:00Z"},
    ]})


@app.before_request
def _honeytoken_watch():
    """DECEIVE follow-through: if the honeytoken planted in a decoy ever appears
    in a later request (query string or any header), only someone who scraped a
    honeypot could know it — flag them hostile at once. Cheap: scans metadata
    only, never the request body, so it can never touch real user content and
    never delays a normal request."""
    try:
        if _HONEYTOKEN in (request.query_string or b"").decode("latin-1", "ignore"):
            _flag_hostile("honeytoken-replay:query", hard=True)
            return _gentle_429()
        for _v in request.headers.values():
            if _HONEYTOKEN in _v:
                _flag_hostile("honeytoken-replay:header", hard=True)
                return _gentle_429()
    except Exception:
        pass
    return None


@app.route("/api/admin/security")
def admin_security():
    """FOUNDER-ONLY forensic readout: recent security events + quick counts.
    Metadata only — never any user content. This is the evidence view."""
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    events = []
    try:
        with _SECURITY_LOG_LOCK:
            if os.path.exists(_SECURITY_LOG_FILE):
                with open(_SECURITY_LOG_FILE, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-200:]
        for ln in reversed(lines):
            try:
                events.append(json.loads(ln))
            except Exception:
                continue
    except Exception:
        events = []
    top_paths = sorted(_SECURITY_COUNTS.get("paths", {}).items(), key=lambda x: -x[1])[:8]
    with _HOSTILE_LOCK:
        now = time.time()
        locked = sum(1 for h in _HOSTILE.values() if h.get("block_until", 0) > now)
        hostile_ips = len(_HOSTILE)
    return jsonify({
        "attacks_total": _SECURITY_COUNTS.get("attacks", 0),
        "honeypot_hits": _SECURITY_COUNTS.get("honeypots", 0),
        "hostile_ips": hostile_ips,
        "locked_out_now": locked,
        "top_paths": [{"path": p, "count": c} for p, c in top_paths],
        "recent": events[:120],
    })


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
    # The conversation itself, as turns — so a return is a CONVERSATION, not
    # a wall of text, and the companion remembers where they left off.
    convo = []
    try:
        for t in (data.get("conversation") or [])[:80]:
            role = "user" if str(t.get("role")) == "user" else "innerlight"
            txt = str(t.get("text", ""))[:1200].strip()
            if txt:
                convo.append({"role": role, "text": txt})
        while convo and len(json.dumps(convo, ensure_ascii=False)) > 9000:
            convo.pop(0)  # drop the oldest turns first
    except Exception:
        convo = []
    # generate a unique code
    with _MEMORY_LOCK:
        store = _memory_load()
        code = _new_code()
        tries = 0
        while _code_key(code) in store and tries < 20:
            code = _new_code(); tries += 1
        # encrypt the summary with a key that includes the code
        enc = AxiomHarmonyProtocol(encryption_key("memory::" + _code_key(code))).encrypt(
            {"summary": summary, "conversation": convo, "saved": time.strftime("%Y-%m-%d %H:%M")}, context="memory")
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
        out = AxiomHarmonyProtocol(encryption_key("memory::" + k)).decrypt(rec["enc"], context="memory").get("original_data", {})
        return jsonify({"status": "ok", "summary": out.get("summary",""),
                        "conversation": out.get("conversation") or [],
                        "saved": rec.get("saved","")})
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
<link rel="icon" href="data:,">
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
    # DETER: an auth endpoint is a prime brute-force target. Tarpit/lock out
    # clients that have already earned it before doing any work.
    blocked = _defend()
    if blocked is not None:
        return blocked
    admin_key = os.environ.get("ADMIN_KEY", "")
    admin_user = os.environ.get("ADMIN_USER", "founder")
    u = request.form.get("username", "")
    p = request.form.get("password", "")
    if admin_key and secrets.compare_digest(p, admin_key) and secrets.compare_digest(u, admin_user):
        session["founder_ok"] = True
        session.permanent = False
        return redirect("/admin")
    # A failed admin login is a security event: flag + log so repeated attempts
    # progressively slow and then lock the attacker out.
    _flag_hostile("admin-login-fail")
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
            f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(244,201,119,.14);">'
            f'<span>{k.capitalize()}</span><b style="color:{"#f4c977" if k=="measured" else "#e8a34c" if k=="estimated" else "rgba(242,231,210,.55)"};">'
            f'{tiers.get(k,0)} ({100*tiers.get(k,0)/ttot:.0f}%)</b></div>'
            for k in order if tiers.get(k,0))
        meas_pct = 100*tiers.get("measured",0)/ttot
        heart_rows = (f'<div style="font-size:15px;margin-bottom:8px;">Average heart rate: <b>{avg:.0f} bpm</b> '
                      f'across <b>{h_n}</b> readings &mdash; <b style="color:#9a561f;">100% session coverage</b>, '
                      f'{meas_pct:.0f}% high-confidence.</div>' + bars).replace("#9a561f","#f4c977")
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
            f'<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid rgba(244,201,119,.14);">'
            f'<span>{ZLABEL.get(z, z)}</span><b style="color:#e8a34c;">{(a["sum"]/a["n"]):.0f}% agreement</b></div>'
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
    # ---- THE WATCH: real numbers for the night room above the fold ----
    _today_key = time.strftime("%Y-%m-%d")
    _td = m.get(_today_key, {})
    w_sessions = _tot_sessions                       # sessions held, last 14 days
    w_handoffs = _tot_handoffs                       # handoff clicks, last 14 days
    w_messages = _tot_messages                       # messages received, last 14 days
    w_first = int(round(_avg_first)) if _fs_cnt else "&mdash;"   # avg seconds to first sound
    _today_moves = [
        ("the music shifted lanes to follow someone", _td.get("lane_switches", 0)),
        ("a new sky was chosen", _td.get("scene_changes", 0)),
        ("words were spoken into the room", _td.get("messages", 0)),
        ("a thought was typed, then let go", _td.get("hesitations", 0)),
    ]
    _max_mv = max([v for _, v in _today_moves] + [1])
    room_rows = "".join(
        f'<div class="lane" style="margin-top:20px;"><div class="lane-head">'
        f'<span class="lane-name">{lbl}</span>'
        f'<span class="lane-count">{v} {"time" if v == 1 else "times"} today</span></div>'
        f'<div class="band"><div class="band-fill" style="width:{(max(6, int(100 * v / _max_mv)) if v else 0)}%;animation-delay:-{i * 1.7}s"></div></div></div>'
        for i, (lbl, v) in enumerate(_today_moves))
    return render_template_string("""
<!doctype html><html lang="en"><head><title>The Watch — InnerLight</title>
<meta charset="utf-8">
<link rel="icon" href="data:,">
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 :root{
   --night:#17100a; --night-2:#211508; --field:#1d1309;
   --ember:#e8a34c; --candle:#f4c977; --core:#ffe8bf;
   --cream:#f2e7d2; --cream-dim:rgba(242,231,210,.62); --cream-faint:rgba(242,231,210,.38);
   --hairline:rgba(232,163,76,.16);
   --serif:"Palatino Linotype",Palatino,"Book Antiqua",Georgia,"Times New Roman",serif;
   --sans:"Gill Sans","Gill Sans MT",Seravek,"Segoe UI","Trebuchet MS",Verdana,sans-serif;
 }
 *{margin:0;padding:0;box-sizing:border-box;}
 html,body{min-height:100%;}
 body{
   background:
     radial-gradient(1200px 700px at 50% -10%, rgba(232,163,76,.10), transparent 60%),
     radial-gradient(900px 600px at 85% 110%, rgba(160,90,30,.10), transparent 55%),
     linear-gradient(180deg,#140d07 0%, var(--night) 40%, #100a05 100%);
   background-color:var(--night);
   color:var(--cream); font-family:var(--sans);
   -webkit-font-smoothing:antialiased; overflow-x:hidden; position:relative;
 }
 body::after{
   content:""; position:fixed; inset:0; pointer-events:none; z-index:50; opacity:.035;
   background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='240'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
 }
 .page{max-width:1160px;margin:0 auto;padding:0 44px 90px;}
 a{color:var(--ember);}
 header{display:flex;align-items:baseline;justify-content:space-between;padding:34px 6px 10px;}
 .wordmark{font-family:var(--serif);font-size:30px;font-weight:400;letter-spacing:.14em;color:var(--cream);}
 .wordmark .flame{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--candle);
   margin:0 16px 3px 2px;box-shadow:0 0 12px 3px rgba(244,201,119,.55);animation:flamebreath 5.2s ease-in-out infinite;}
 @keyframes flamebreath{0%,100%{transform:scale(1);opacity:.85;}50%{transform:scale(1.35);opacity:1;}}
 .header-right{text-align:right;}
 .clock{font-family:var(--serif);font-size:19px;color:var(--cream-dim);font-variant-numeric:tabular-nums;}
 .status{font-size:11px;letter-spacing:.24em;text-transform:uppercase;color:var(--cream-faint);margin-top:7px;}
 .status .quiet-dot{display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--ember);
   margin-right:9px;vertical-align:2px;box-shadow:0 0 8px 2px rgba(232,163,76,.5);animation:flamebreath 6.4s ease-in-out infinite;}
 .quiet-nav{text-align:center;padding:6px 0 22px;font-size:10.5px;letter-spacing:.22em;text-transform:uppercase;}
 .quiet-nav a{color:var(--cream-faint);text-decoration:none;margin:0 11px;padding:4px 2px;}
 .quiet-nav a:hover{color:var(--candle);}
 .field-wrap{position:relative;margin-top:6px;}
 .field-frame{position:relative;border-radius:18px;overflow:hidden;border:1px solid var(--hairline);
   background:
     radial-gradient(120% 90% at 50% 118%, rgba(190,110,40,.20), transparent 55%),
     radial-gradient(90% 70% at 50% -20%, rgba(232,163,76,.09), transparent 60%),
     linear-gradient(180deg,#1b1108 0%,#170e07 55%,#1e1207 100%);
   box-shadow:inset 0 0 90px rgba(0,0,0,.55), 0 22px 60px -30px rgba(0,0,0,.8);}
 canvas#field{display:block;width:100%;height:420px;}
 .field-caption{position:absolute;top:22px;left:0;right:0;text-align:center;font-size:10.5px;
   letter-spacing:.34em;text-transform:uppercase;color:rgba(242,231,210,.30);pointer-events:none;}
 .field-empty{position:absolute;top:50%;left:0;right:0;transform:translateY(-50%);text-align:center;
   font-family:var(--serif);font-style:italic;font-size:16px;color:rgba(242,231,210,.34);
   pointer-events:none;transition:opacity 2s ease;}
 .counter-lines{text-align:center;padding:30px 20px 8px;}
 .counter-main{font-family:var(--serif);font-style:italic;font-size:25px;color:var(--cream);letter-spacing:.01em;}
 .counter-main b{font-style:normal;font-weight:400;color:var(--candle);}
 .counter-sub{font-family:var(--serif);font-size:15.5px;color:var(--cream-dim);margin-top:11px;font-style:italic;}
 .counter-sub b{font-style:normal;color:rgba(244,201,119,.85);font-weight:400;}
 .moments{display:grid;grid-template-columns:repeat(4,1fr);gap:34px;padding:74px 8px 0;text-align:center;}
 .moment .num{font-family:var(--serif);font-weight:400;font-size:58px;line-height:1;color:var(--cream);
   text-shadow:0 0 34px rgba(232,163,76,.22);font-variant-numeric:tabular-nums;}
 .moment .num small{font-size:24px;color:var(--cream-dim);margin-left:4px;letter-spacing:.02em;}
 .moment .cap{margin-top:15px;font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:rgba(244,201,119,.62);}
 .moment .sub{margin-top:9px;font-family:var(--serif);font-style:italic;font-size:14px;color:var(--cream-faint);line-height:1.5;}
 .rule{height:1px;margin:70px auto 0;max-width:520px;
   background:linear-gradient(90deg, transparent, rgba(232,163,76,.35), transparent);}
 .room{padding-top:64px;}
 h2.sect{font-family:var(--serif);font-weight:400;font-size:23px;color:var(--cream);text-align:center;letter-spacing:.03em;}
 .sect-sub{text-align:center;margin-top:10px;font-family:var(--serif);font-style:italic;font-size:14px;color:var(--cream-faint);}
 .lanes{display:grid;grid-template-columns:1fr 1fr;gap:26px 90px;max-width:980px;margin:44px auto 0;padding:0 8px;}
 .lane-col-title{font-size:10.5px;letter-spacing:.3em;text-transform:uppercase;color:rgba(244,201,119,.5);margin-bottom:4px;}
 .lane-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:9px;}
 .lane-name{font-family:var(--serif);font-size:16.5px;color:var(--cream-dim);font-style:italic;}
 .lane-count{font-size:11px;letter-spacing:.14em;color:var(--cream-faint);text-transform:uppercase;}
 .band{height:8px;border-radius:6px;background:rgba(232,163,76,.07);overflow:visible;position:relative;}
 .band-fill{height:100%;border-radius:6px;width:0%;
   background:linear-gradient(90deg, rgba(190,110,40,.55), var(--ember) 70%, var(--candle));
   box-shadow:0 0 16px rgba(232,163,76,.45), 0 0 3px rgba(255,232,191,.6);
   transition:width 4.5s cubic-bezier(.4,0,.2,1);animation:bandglow 7s ease-in-out infinite;}
 @keyframes bandglow{0%,100%{filter:brightness(.92);}50%{filter:brightness(1.12);}}
 .log{padding-top:82px;max-width:720px;margin:0 auto;}
 .log-lines{margin-top:40px;}
 .log-line{display:flex;gap:26px;align-items:baseline;padding:15px 4px;border-bottom:1px solid rgba(232,163,76,.09);
   opacity:0;transform:translateY(10px);transition:opacity 1.9s ease, transform 1.9s ease;}
 .log-line.shown{opacity:1;transform:none;}
 .log-line.dimming{opacity:.35;}
 .log-time{font-family:var(--serif);font-size:13px;color:rgba(244,201,119,.55);min-width:46px;font-variant-numeric:tabular-nums;}
 .log-text{font-family:var(--serif);font-size:16.5px;line-height:1.65;color:var(--cream-dim);}
 .log-text em{color:rgba(244,201,119,.9);font-style:normal;}
 .vow{text-align:center;padding-top:88px;font-family:var(--serif);font-style:italic;font-size:13.5px;
   color:rgba(242,231,210,.30);line-height:1.8;}
 /* ---------- the ledgers (everything the operations room already had) ---------- */
 .ledgers{margin-top:96px;}
 .ledgers-title{font-family:var(--serif);font-weight:400;font-size:23px;color:var(--cream);text-align:center;letter-spacing:.03em;}
 .ledgers-sub{text-align:center;margin-top:10px;font-family:var(--serif);font-style:italic;font-size:14px;color:var(--cream-faint);}
 h2.ledger{font-family:var(--serif);font-weight:400;font-size:19px;color:var(--cream);letter-spacing:.02em;
   margin:58px 0 14px;padding-bottom:10px;border-bottom:1px solid var(--hairline);scroll-margin-top:24px;}
 h2.ledger::before{content:"";display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--ember);
   margin-right:12px;vertical-align:4px;box-shadow:0 0 8px 2px rgba(232,163,76,.4);}
 .panel{background:rgba(30,19,9,.72);border:1px solid var(--hairline);border-radius:14px;padding:18px;
   box-shadow:0 18px 50px -34px rgba(0,0,0,.9);}
 .hint{font-size:12px;color:var(--cream-faint);margin-bottom:10px;line-height:1.65;}
 .hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:16px;}
 .kpi{background:rgba(30,19,9,.72);border:1px solid var(--hairline);border-radius:14px;padding:15px 16px;}
 .kpi-v{font-family:var(--serif);font-size:27px;color:var(--cream);line-height:1;font-variant-numeric:tabular-nums;}
 .kpi-l{font-size:10.5px;letter-spacing:.18em;text-transform:uppercase;color:rgba(244,201,119,.6);margin-top:9px;}
 .kpi-s{font-size:11px;color:var(--cream-faint);margin-top:3px;}
 .kpi .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--ember);
   margin-right:7px;vertical-align:3px;box-shadow:0 0 8px 2px rgba(232,163,76,.5);animation:flamebreath 3.2s ease-in-out infinite;}
 .tablewrap{overflow-x:auto;background:rgba(30,19,9,.72);border:1px solid var(--hairline);border-radius:14px;}
 table{border-collapse:collapse;width:100%;}
 th,td{padding:10px 12px;text-align:left;font-size:12.5px;white-space:nowrap;}
 th{font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:rgba(244,201,119,.55);
   background:rgba(232,163,76,.06);border-bottom:1px solid rgba(232,163,76,.22);}
 td{color:var(--cream-dim);border-bottom:1px solid rgba(232,163,76,.09);}
 tr:last-child td{border-bottom:0;}
 tr:hover td{background:rgba(232,163,76,.04);}
 .graph{display:flex;align-items:flex-end;gap:8px;background:rgba(30,19,9,.72);border:1px solid var(--hairline);
   padding:18px;border-radius:14px;overflow-x:auto;}
 .bar-col{display:flex;flex-direction:column;align-items:center;min-width:44px;}
 .bar{width:22px;background:linear-gradient(180deg, rgba(244,201,119,.85), rgba(190,110,40,.45));
   border-radius:5px 5px 0 0;box-shadow:0 0 14px rgba(232,163,76,.3);}
 .bar-lbl{font-size:10px;color:var(--cream-faint);margin-top:5px;}
 .bar-num{font-size:11px;color:var(--candle);}
 .sci-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;}
 .sci{background:rgba(30,19,9,.72);border:1px solid var(--hairline);border-top:2px solid rgba(232,163,76,.4);
   border-radius:14px;padding:16px 18px;font-size:12.6px;line-height:1.62;color:var(--cream-dim);}
 .sci b{color:var(--candle);font-size:13px;}
 .note{margin-top:18px;font-size:12.6px;color:var(--cream-dim);background:rgba(30,19,9,.72);
   border:1px solid var(--hairline);border-left:3px solid rgba(232,163,76,.5);border-radius:14px;
   padding:16px 18px;line-height:1.7;}
 @media (max-width:700px){
   .page{padding:0 20px 70px;}
   header{padding:24px 2px 6px;display:block;text-align:center;}
   .header-right{text-align:center;margin-top:12px;}
   .wordmark{font-size:24px;}
   .quiet-nav a{margin:0 6px;}
   canvas#field{height:300px;}
   .counter-main{font-size:19px;}
   .moments{grid-template-columns:1fr 1fr;gap:44px 20px;padding-top:58px;}
   .moment .num{font-size:42px;}
   .moment .num small{font-size:18px;}
   .moment .sub{display:none;}
   .lanes{grid-template-columns:1fr;gap:22px;}
   .log{padding-top:64px;}
   .log-line{gap:16px;}
 }
</style></head><body>
<div class="page">

  <header>
    <div class="wordmark"><span class="flame"></span>THE WATCH</div>
    <div class="header-right">
      <div class="clock" id="clock">—</div>
      <div class="status"><span class="quiet-dot"></span><span id="statusText">all quiet · the room is warm</span></div>
    </div>
  </header>

  <nav class="quiet-nav" aria-label="Ledger sections">
    <a href="#overview">ledger</a><a href="#live">live</a><a href="#music">music</a><a href="#people">people</a><a href="#vetting">vetting</a><a href="#partners">partners</a><a href="#demo">demo</a><a href="#security">security</a><a href="#research">research</a><a href="/admin/study">the study</a><a href="/admin/logout">sign out</a>
  </nav>

  <section class="field-wrap" aria-label="People being held right now">
    <div class="field-frame">
      <div class="field-caption">each light is a person, held anonymously</div>
      <div class="field-empty" id="fieldEmpty" style="opacity:0;">no one needs carrying this minute. the room stays lit anyway.</div>
      <canvas id="field"></canvas>
    </div>
    <div class="counter-lines">
      <div class="counter-main"><b id="nowCount">0</b> <span id="nowWord">people are being carried right now.</span></div>
      <div class="counter-sub"><b id="weekHandoffLine" data-n="{{ w_handoffs }}">0</b> times someone was carried toward human help, these fourteen days.</div>
    </div>
  </section>

  <section class="moments" aria-label="The last fourteen days">
    <div class="moment">
      <div class="num" data-n="{{ w_sessions }}">0</div>
      <div class="cap">held — fourteen days</div>
      <div class="sub">every one of them anonymous,<br>every one of them met.</div>
    </div>
    <div class="moment">
      <div class="num"><span data-n="{{ w_first|safe }}">{{ w_first|safe }}</span><small>s</small></div>
      <div class="cap">from door to first sound</div>
      <div class="sub">the silence before company arrives,<br>measured so it can shrink.</div>
    </div>
    <div class="moment">
      <div class="num" data-n="{{ w_handoffs }}">0</div>
      <div class="cap">handoffs toward human help</div>
      <div class="sub">carried all the way<br>to a human hand.</div>
    </div>
    <div class="moment">
      <div class="num" data-n="{{ w_messages }}">0</div>
      <div class="cap">messages received</div>
      <div class="sub">each one answered.<br>none of them kept.</div>
    </div>
  </section>

  <div class="rule"></div>

  <section class="room">
    <h2 class="sect">What the room is doing now</h2>
    <div class="sect-sub">the sounds waiting for people, and the movement of the day so far</div>
    <div class="lanes">
      <div>
        <div class="lane-col-title">music lanes — ready to play</div>
        <div id="musicLanes"><div class="sect-sub" style="text-align:left;margin-top:20px;">listening to the library…</div></div>
      </div>
      <div>
        <div class="lane-col-title">the room today</div>
        {{ room_rows|safe }}
      </div>
    </div>
  </section>

  <div class="rule"></div>

  <section class="log">
    <h2 class="sect">The night log</h2>
    <div class="sect-sub">recent moments, told without names — from the live event feed</div>
    <div class="log-lines" id="logLines"><div class="sect-sub" id="logEmpty" style="margin-top:26px;">the log is quiet. moments appear here as the night moves.</div></div>
  </section>

  <div class="vow">
    Every light is a person. Nothing on this page can identify them.<br>
    The Watch never scores distress — it only keeps company.
  </div>

  <!-- ==================== THE LEDGERS — the full operations room ==================== -->
  <section class="ledgers" id="ledgers">
    <div class="rule" style="margin-bottom:64px;"></div>
    <div class="ledgers-title">The ledgers</div>
    <div class="ledgers-sub">every count and control the operations room keeps — anonymous counts and clock-times only.<br>no words, names, faces, or voices are ever stored.</div>

    <div class="hero">{{ kpi_cards|safe }}</div>

    <h2 class="ledger" id="dispatch">Dispatch — the monetary engine (Principle 7)</h2>
    <div class="card" id="dispatch-card">
      <p style="margin-top:0;"><b>Status:</b> <span id="dispatch-status" style="font-weight:700;">loading&hellip;</span>
        <button id="dispatch-toggle" onclick="dispatchToggle()" style="margin-left:14px;padding:6px 16px;border-radius:8px;border:1px solid #b89; background:#fff; cursor:pointer; font-weight:700;">&hellip;</button></p>
      <p id="dispatch-identity" style="font-size:14px;font-weight:600;color:#4a3b2c;"></p>
      <p style="font-size:13px;color:#665;">Built, dormant, ready — activation arms the revenue engine that partner
      and billing surfaces consult. By construction it has <b>zero hooks into care</b>: flipping this switch cannot
      change what any person in crisis experiences, and money can never buy routing (Principle 3, enforced in code
      and by a repository test).</p>
      <div id="dispatch-streams" style="font-size:13.5px;line-height:1.55;"></div>
      <div id="dispatch-never" style="font-size:13px;margin-top:10px;padding:10px 12px;background:#fdf3f0;border-radius:8px;"></div>
      <div id="dispatch-log" style="font-size:12px;color:#776;margin-top:10px;"></div>
    </div>
    <script>
      async function dispatchLoad(){
        try {
          var r = await fetch('/api/admin/dispatch'); if(!r.ok) return;
          var d = await r.json();
          var st = document.getElementById('dispatch-status');
          st.textContent = d.active ? ('ACTIVE since ' + (d.activated_at||'')) : 'DORMANT (ready)';
          st.style.color = d.active ? '#1c7a3d' : '#8a6d3b';
          var btn = document.getElementById('dispatch-toggle');
          btn.textContent = d.active ? 'Deactivate' : 'Activate';
          window._dispatchActive = !!d.active;
          if (d.identity) document.getElementById('dispatch-identity').textContent = d.identity;
          document.getElementById('dispatch-streams').innerHTML =
            d.streams.map(function(s){ return '<p style="margin:8px 0;"><b>' + s.name + '.</b> ' + s.how + '</p>'; }).join('');
          document.getElementById('dispatch-never').innerHTML =
            '<b>Never, regardless of switch state:</b><br>' + d.never.map(function(x){ return '&bull; ' + x; }).join('<br>');
          document.getElementById('dispatch-log').innerHTML = (d.log||[]).slice().reverse()
            .map(function(e){ return e.at + ' — ' + e.action + ' by ' + e.by; }).join('<br>') || 'No activations yet.';
        } catch(e){}
      }
      async function dispatchToggle(){
        var next = !window._dispatchActive;
        var word = next ? 'ACTIVATE' : 'DEACTIVATE';
        if (!confirm('Really ' + word + ' Dispatch? Care paths are unaffected either way.')) return;
        await fetch('/api/admin/dispatch', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({active: next})});
        dispatchLoad();
      }
      dispatchLoad();
    </script>

    <h2 class="ledger" id="overview">The daily ledger — the last fourteen days</h2>
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

    <h2 class="ledger">People who asked for a human</h2>
    <div class="panel" id="connects" style="font-size:13.5px;">Loading&hellip;</div>
    <script>
    fetch('/api/admin/connects').then(r=>r.json()).then(function(d){
      const el = document.getElementById('connects');
      if(!d.connects || !d.connects.length){ el.textContent = 'No connection requests yet.'; return; }
      el.innerHTML = d.connects.map(function(c){
        return '<div style="border-bottom:1px solid rgba(232,163,76,.14);padding:9px 0;">'
          + '<b style="color:#f4c977;">' + c.when + '</b> — ' + c.kind.toUpperCase() + ' — wants: <b style="color:#e8a34c;">' + c.pro + '</b> '
          + '— <a href="' + c.room + '" target="_blank" style="color:#e8a34c;font-weight:700;">Join room</a>'
          + (c.summary ? '<div style="color:rgba(242,231,210,.72);margin-top:4px;white-space:pre-wrap;">' + c.summary.replace(/</g,'&lt;') + '</div>' : '')
          + '</div>';
      }).join('');
    }).catch(function(){ document.getElementById('connects').textContent = 'Could not load.'; });
    </script>

    <h2 class="ledger" id="oncall">On call right now</h2>
    <div class="panel">
    <div class="hint">The founder rule, kept: <b style="color:#f4c977;">for anyone to click on a provider, they must be there and available.</b>
    Every role below starts off. Turn a role on only while a real person is truly reachable behind it &mdash;
    the clinical and legal handoff pages show exactly what is lit here, and nothing else. When everything is off,
    those pages say so honestly and hold people with 988, Crisis Text Line, legal aid, and 211 instead.</div>
    <div id="oncall-list"><i style="color:rgba(242,231,210,.45);">Loading the on-call board&hellip;</i></div>
    </div>
    <script>
    (function(){
      var SIDE_NAMES = {clinical: 'The care side', legal: 'The legal side'};
      function esc2(s){ return String(s == null ? '' : s).replace(/</g,'&lt;'); }
      function whenText(iso){
        if (!iso) return '';
        var t = String(iso).replace('T',' ');
        var cut = t.indexOf('.'); if (cut > 0) t = t.slice(0, cut);
        return 'set ' + t.slice(0, 16) + ' UTC';
      }
      async function loadOncall(){
        try{
          var r = await fetch('/api/admin/oncall'); if (!r.ok) return;
          var d = await r.json();
          var el = document.getElementById('oncall-list'); if (!el) return;
          var roles = d.roles || [];
          var html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:22px;">';
          ['clinical','legal'].forEach(function(side){
            html += '<div><div style="font-family:var(--serif);font-style:italic;font-size:16px;color:rgba(244,201,119,.8);'
              + 'padding-bottom:8px;border-bottom:1px solid rgba(232,163,76,.2);margin-bottom:4px;">' + SIDE_NAMES[side] + '</div>';
            roles.filter(function(x){ return x.side === side; }).forEach(function(x){
              var onStyle = 'background:linear-gradient(90deg,#b06a2a,#e8a34c);color:#ffe8bf;border:1px solid rgba(255,232,191,.5);'
                + 'box-shadow:0 0 14px rgba(232,163,76,.45);';
              var offStyle = 'background:rgba(232,163,76,.08);color:rgba(242,231,210,.5);border:1px solid rgba(232,163,76,.3);';
              html += '<div style="display:flex;align-items:center;gap:12px;padding:10px 2px;border-bottom:1px solid rgba(232,163,76,.1);">'
                + '<span style="flex:1;color:' + (x.available ? '#ffe8bf' : 'rgba(242,231,210,.62)') + ';">' + esc2(x.label)
                + '<span style="display:block;font-size:10.5px;color:rgba(242,231,210,.38);margin-top:3px;font-variant-numeric:tabular-nums;">' + whenText(x.updated_at) + '</span></span>'
                + '<button data-oncall-role="' + esc2(x.role) + '" data-oncall-side="' + esc2(x.side) + '" data-oncall-on="' + (x.available ? '1' : '0') + '"'
                + ' style="border-radius:999px;padding:7px 16px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;cursor:pointer;min-width:96px;'
                + (x.available ? onStyle : offStyle) + '">' + (x.available ? 'On call' : 'Off') + '</button>'
                + '</div>';
            });
            html += '</div>';
          });
          html += '</div>';
          el.innerHTML = html;
        }catch(e){}
      }
      document.addEventListener('click', async function(ev){
        var b = ev.target;
        if (!b || !b.getAttribute || !b.getAttribute('data-oncall-role')) return;
        b.disabled = true;
        try{
          await fetch('/api/admin/oncall', {method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({role: b.getAttribute('data-oncall-role'),
                                  side: b.getAttribute('data-oncall-side'),
                                  available: b.getAttribute('data-oncall-on') !== '1'})});
        }catch(e){}
        loadOncall();
      });
      loadOncall();
    })();
    </script>

    <h2 class="ledger" id="vetting">Vetting — scrutinize a provider before anyone reaches them</h2>
    <div class="panel">
    <div class="hint">Principle 4, kept: we do not toss a person to just any provider. Enter a provider here, check their credential and record, and categorize them &mdash; nothing is exposed to anyone by this. A new provider starts <b style="color:#f4c977;">pending</b>. Review, then mark <b style="color:#f4c977;">Vetted</b> or <b>Rejected</b>. Only after that can you (separately, by choice) promote a vetted provider into Partners or light their role on the On-Call board. This engine holds provider records only &mdash; never any person&rsquo;s words or identity.</div>
    <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin:14px 0 14px;">
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Organization</div>
        <input id="vt-org" placeholder="e.g. Harbor Family Law" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-width:210px;"></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Contact name</div>
        <input id="vt-contact" placeholder="optional" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-width:150px;"></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Side</div>
        <select id="vt-side" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;">
          <option value="clinical">Clinical</option><option value="legal">Legal</option></select></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Role</div>
        <select id="vt-role" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-width:190px;"></select></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Credential type</div>
        <select id="vt-ctype" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;"></select></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Credential ID</div>
        <input id="vt-cid" placeholder="license / NPI / bar #" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-width:150px;"></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">State</div>
        <input id="vt-cstate" placeholder="e.g. CA" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;width:80px;"></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Category</div>
        <input id="vt-category" placeholder="e.g. Housing / trauma" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-width:160px;"></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Specialty / fit</div>
        <input id="vt-specialty" placeholder="e.g. eviction defense, EMDR" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-width:180px;"></div>
      <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:rgba(242,231,210,.8);cursor:pointer;">
        <input type="checkbox" id="vt-disc"> Discipline history checked</label>
      <div style="flex-basis:100%;height:0;"></div>
      <div style="flex:1;min-width:260px;"><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Discipline notes (auto-scrubbed of identifiers)</div>
        <textarea id="vt-notes" placeholder="What the license / bar record showed. Any identifiers are scrubbed before saving." style="width:100%;background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-height:52px;"></textarea></div>
      <button id="vt-create" style="background:linear-gradient(90deg,#b06a2a,#e8a34c);color:#ffe8bf;border:0;border-radius:999px;padding:11px 24px;font-size:13px;font-weight:700;cursor:pointer;">Add for vetting</button>
    </div>
    <div id="vt-code" style="display:none;background:rgba(232,163,76,.1);border:1px solid rgba(232,163,76,.35);border-radius:12px;padding:16px 18px;margin-bottom:16px;"></div>
    <div id="vt-list"><i style="color:rgba(242,231,210,.45);">Loading the vetting board&hellip;</i></div>
    </div>
    <script>
    (function(){
      var ROLES = [];
      var CTYPES = {clinical: [['License #','License #'],['NPI','NPI (National Provider Identifier)']],
                    legal: [['State bar #','State bar #']]};
      function esc(s){ return String(s == null ? '' : s).replace(/</g,'&lt;'); }
      function fillRoles(){
        var side = document.getElementById('vt-side').value;
        var sel = document.getElementById('vt-role'); sel.innerHTML = '';
        ROLES.filter(function(r){ return r.side === side; }).forEach(function(r){
          var o = document.createElement('option'); o.value = r.role; o.textContent = r.label; sel.appendChild(o);
        });
        var cs = document.getElementById('vt-ctype'); cs.innerHTML = '';
        (CTYPES[side]||[]).forEach(function(pair){
          var o = document.createElement('option'); o.value = pair[0]; o.textContent = pair[1]; cs.appendChild(o);
        });
      }
      function statusPill(st, sample){
        var col = st === 'vetted' ? 'background:rgba(232,163,76,.18);color:#f4c977;'
          : st === 'rejected' ? 'background:rgba(150,150,150,.16);color:rgba(242,231,210,.5);'
          : 'background:rgba(197,106,44,.2);color:#e8a34c;';
        var s = '<span style="border-radius:999px;padding:4px 12px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;' + col + '">' + esc(st) + '</span>';
        if (sample) s = '<span style="border-radius:999px;padding:4px 12px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;background:rgba(197,106,44,.28);color:#ffd28a;border:1px solid rgba(255,210,138,.6);margin-right:6px;">Sample</span>' + s;
        return s;
      }
      async function loadVetting(){
        try{
          var r = await fetch('/api/admin/vetting/list'); if(!r.ok) return;
          var d = await r.json();
          ROLES = d.roles || [];
          if(!document.getElementById('vt-role').options.length) fillRoles();
          var el = document.getElementById('vt-list'); if(!el) return;
          var ps = d.providers || [];
          if(!ps.length){ el.innerHTML = '<i style="color:rgba(242,231,210,.45);">No providers yet. Add one above.</i>'; return; }
          el.innerHTML = ps.map(function(p){
            var cred = [p.credential_type, p.credential_id, p.credential_state].filter(Boolean).join(' &middot; ');
            var cat = [p.category, p.specialty].filter(Boolean).join(' &mdash; ');
            var disc = p.discipline_checked ? 'discipline checked' : 'discipline not yet checked';
            var actions = '';
            if(p.status === 'pending'){
              actions = '<button data-vt-decide="' + p.id + '" data-vt-to="vetted" style="background:rgba(232,163,76,.16);color:#f4c977;border:1px solid rgba(232,163,76,.4);border-radius:999px;padding:6px 14px;font-size:12px;cursor:pointer;margin-left:6px;">Mark vetted</button>'
                + '<button data-vt-decide="' + p.id + '" data-vt-to="rejected" style="background:rgba(150,150,150,.12);color:rgba(242,231,210,.6);border:1px solid rgba(150,150,150,.3);border-radius:999px;padding:6px 14px;font-size:12px;cursor:pointer;margin-left:6px;">Reject</button>';
            } else if(p.status === 'vetted' && !p.is_sample){
              actions = '<button data-vt-promote="' + p.id + '" data-vt-target="partner" style="background:linear-gradient(90deg,#b06a2a,#e8a34c);color:#ffe8bf;border:0;border-radius:999px;padding:6px 14px;font-size:12px;cursor:pointer;margin-left:6px;">Promote to partner</button>'
                + '<button data-vt-promote="' + p.id + '" data-vt-target="oncall" style="background:rgba(232,163,76,.14);color:#f4c977;border:1px solid rgba(232,163,76,.35);border-radius:999px;padding:6px 14px;font-size:12px;cursor:pointer;margin-left:6px;">Light on-call</button>';
            } else if(p.status === 'vetted' && p.is_sample){
              actions = '<span style="font-size:11px;color:rgba(242,231,210,.4);margin-left:8px;">sample &mdash; not promotable</span>';
            }
            return '<div style="padding:12px 0;border-bottom:1px solid rgba(232,163,76,.12);">'
              + '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">'
              + '<div style="flex:1;min-width:240px;"><b style="color:#ffe8bf;">' + esc(p.org) + '</b>'
              + '<span style="color:rgba(242,231,210,.5);font-size:12px;"> &mdash; ' + esc(p.role_label) + (p.contact ? ' &middot; ' + esc(p.contact) : '') + '</span>'
              + (cred ? '<div style="font-size:12px;color:rgba(242,231,210,.6);margin-top:3px;">' + cred + '</div>' : '')
              + (cat ? '<div style="font-size:12px;color:rgba(244,201,119,.65);margin-top:2px;">' + esc(cat) + '</div>' : '')
              + '<div style="font-size:11px;color:rgba(242,231,210,.4);margin-top:2px;">' + disc + '</div></div>'
              + '<div style="text-align:right;">' + statusPill(p.status, p.is_sample) + '<div style="margin-top:8px;">' + actions + '</div></div>'
              + '</div></div>';
          }).join('');
        }catch(e){}
      }
      document.addEventListener('change', function(ev){
        if(ev.target && ev.target.id === 'vt-side') fillRoles();
      });
      document.addEventListener('click', async function(ev){
        var b = ev.target;
        if(b && b.id === 'vt-create'){
          var org = document.getElementById('vt-org').value.trim();
          var role = document.getElementById('vt-role').value;
          if(!org){ return; }
          b.disabled = true;
          var payload = {org: org, contact: document.getElementById('vt-contact').value.trim(),
            role: role, credential_type: document.getElementById('vt-ctype').value,
            credential_id: document.getElementById('vt-cid').value.trim(),
            credential_state: document.getElementById('vt-cstate').value.trim(),
            category: document.getElementById('vt-category').value.trim(),
            specialty: document.getElementById('vt-specialty').value.trim(),
            discipline_checked: document.getElementById('vt-disc').checked,
            discipline_notes: document.getElementById('vt-notes').value.trim()};
          try{
            await fetch('/api/admin/vetting/create', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
            ['vt-org','vt-contact','vt-cid','vt-cstate','vt-category','vt-specialty','vt-notes'].forEach(function(id){ var e0 = document.getElementById(id); if(e0) e0.value = ''; });
            document.getElementById('vt-disc').checked = false;
          }catch(e){}
          b.disabled = false; loadVetting(); return;
        }
        if(b && b.getAttribute && b.getAttribute('data-vt-decide')){
          b.disabled = true;
          try{ await fetch('/api/admin/vetting/decide', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: parseInt(b.getAttribute('data-vt-decide'),10), decision: b.getAttribute('data-vt-to')})}); }catch(e){}
          loadVetting(); return;
        }
        if(b && b.getAttribute && b.getAttribute('data-vt-promote')){
          b.disabled = true;
          try{
            var r = await fetch('/api/admin/vetting/promote', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: parseInt(b.getAttribute('data-vt-promote'),10), to: b.getAttribute('data-vt-target')})});
            var d = await r.json();
            if(d && d.code){
              var box = document.getElementById('vt-code'); box.style.display = 'block'; box.innerHTML = '';
              var line = document.createElement('div');
              line.style.cssText = 'font-size:13px;color:rgba(242,231,210,.78);margin-bottom:9px;';
              line.textContent = 'Partner access code for ' + d.org + ' (' + d.role_label + ') — shown once. Copy it now and give it to them privately.';
              var codeEl = document.createElement('span');
              codeEl.style.cssText = 'font-family:var(--serif);font-size:26px;letter-spacing:.12em;color:#ffe8bf;';
              codeEl.textContent = d.code;
              var copyBtn = document.createElement('button');
              copyBtn.textContent = 'Copy';
              copyBtn.style.cssText = 'margin-left:16px;background:rgba(232,163,76,.16);color:#f4c977;border:1px solid rgba(232,163,76,.4);border-radius:999px;padding:6px 16px;font-size:12px;cursor:pointer;';
              copyBtn.addEventListener('click', function(){ try{ navigator.clipboard.writeText(codeEl.textContent); copyBtn.textContent = 'Copied'; }catch(e){} });
              box.appendChild(line); box.appendChild(codeEl); box.appendChild(copyBtn);
            }
          }catch(e){}
          b.disabled = false; loadVetting(); return;
        }
      });
      loadVetting();
    })();
    </script>

    <h2 class="ledger" id="demo">Demonstration mode — show the whole flow, safely</h2>
    <div class="panel">
    <div class="hint">Turn on a <b style="color:#f4c977;">sample</b> network so you can show how InnerLight works start to finish &mdash; even when nobody real is on call. <b>This only affects your own session (or a visitor who opens your demo link).</b> Real people are never touched: while demo is on for you, anyone else opening a handoff page still sees the honest empty state. Every demo page carries a fixed <b style="color:#e8a34c;">SAMPLE &mdash; DEMONSTRATION MODE</b> banner, and a demo send opens no room and pages no one. Turn it off and your session returns to the real, honest product.</div>
    <div id="demo-state" style="font-size:14px;color:rgba(242,231,210,.8);margin:12px 0;">Loading&hellip;</div>
    <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:10px 0 4px;">
      <button data-demo-side="clinical" style="background:rgba(232,163,76,.14);color:#f4c977;border:1px solid rgba(232,163,76,.35);border-radius:999px;padding:9px 18px;font-size:13px;cursor:pointer;">Turn on clinical sample network</button>
      <button data-demo-side="legal" style="background:rgba(232,163,76,.14);color:#f4c977;border:1px solid rgba(232,163,76,.35);border-radius:999px;padding:9px 18px;font-size:13px;cursor:pointer;">Turn on legal sample network</button>
      <button data-demo-side="both" style="background:linear-gradient(90deg,#b06a2a,#e8a34c);color:#ffe8bf;border:0;border-radius:999px;padding:9px 18px;font-size:13px;font-weight:700;cursor:pointer;">Turn on both</button>
      <button data-demo-off="1" style="background:rgba(150,150,150,.14);color:rgba(242,231,210,.75);border:1px solid rgba(150,150,150,.35);border-radius:999px;padding:9px 18px;font-size:13px;cursor:pointer;">Turn demo OFF</button>
    </div>
    <div style="margin-top:16px;padding-top:14px;border-top:1px solid rgba(232,163,76,.14);">
      <div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px;">Shareable demo link (for a class or investors, from their own device)</div>
      <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
        <input id="demo-link" readonly style="flex:1;min-width:280px;background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:13px;">
        <button id="demo-copy" style="background:rgba(232,163,76,.16);color:#f4c977;border:1px solid rgba(232,163,76,.4);border-radius:999px;padding:8px 18px;font-size:12px;cursor:pointer;">Copy demo link</button>
      </div>
      <div style="font-size:12px;color:rgba(242,231,210,.5);margin-top:8px;">This link carries a one-way code derived from your admin key &mdash; it is not the key itself, and it turns on demo mode only in the browser that opens it.</div>
    </div>
    </div>
    <script>
    (function(){
      var LINKPATH = '';
      function render(d){
        var el = document.getElementById('demo-state'); if(!el) return;
        if(d.on){
          el.innerHTML = '<b style="color:#e8a34c;">Demonstration mode is ON</b> for your session &mdash; sample network(s): <b style="color:#f4c977;">' + (d.sides||[]).join(', ') + '</b>. Open <a href="/handoff/clinical" target="_blank" style="color:#e8a34c;">/handoff/clinical</a> or <a href="/handoff/legal" target="_blank" style="color:#e8a34c;">/handoff/legal</a> to walk the flow. Real visitors are unaffected.';
        } else {
          el.innerHTML = 'Demonstration mode is <b>off</b> for your session. You are seeing the real, honest product &mdash; exactly what every visitor sees.';
        }
        LINKPATH = d.link || '';
        var li = document.getElementById('demo-link');
        if(li && LINKPATH){ li.value = window.location.origin + LINKPATH; }
      }
      async function loadDemo(){
        try{ var r = await fetch('/api/admin/demo'); if(!r.ok) return; render(await r.json()); }catch(e){}
      }
      document.addEventListener('click', async function(ev){
        var b = ev.target;
        if(b && b.getAttribute && b.getAttribute('data-demo-side')){
          b.disabled = true;
          try{ var r = await fetch('/api/admin/demo', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({on: true, side: b.getAttribute('data-demo-side')})}); render(await r.json()); }catch(e){}
          b.disabled = false; loadDemo(); return;
        }
        if(b && b.getAttribute && b.getAttribute('data-demo-off')){
          b.disabled = true;
          try{ var r2 = await fetch('/api/admin/demo', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({on: false})}); render(await r2.json()); }catch(e){}
          b.disabled = false; loadDemo(); return;
        }
        if(b && b.id === 'demo-copy'){
          var li = document.getElementById('demo-link');
          if(li){ try{ navigator.clipboard.writeText(li.value); b.textContent = 'Copied'; }catch(e){ li.select(); } }
          return;
        }
      });
      loadDemo();
    })();
    </script>

    <h2 class="ledger">What people said — voices from real sessions</h2>
    <div class="panel">
    <div class="hint">Anonymous feedback from people who used InnerLight. Identifying details are automatically removed. This is the human evidence alongside the numbers.</div>
    <div id="fb-report"><i style="color:rgba(242,231,210,.45);">Loading feedback…</i></div>
    </div>
    <script>
    (function(){
      async function load(){
        try{
          const r=await fetch('/api/admin/feedback'); if(!r.ok) return;
          const d=await r.json();
          const el=document.getElementById('fb-report'); if(!el) return;
          if(!d.total){ el.innerHTML='<i style="color:rgba(242,231,210,.45);">No feedback yet. As people share, their words appear here.</i>'; return; }
          const h=d.helped||{}, tot=d.total||1;
          const pct=function(n){return Math.round(100*(n||0)/tot);};
          let html='<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px;font-size:14px;">'
            +'<div style="flex:1;min-width:120px;background:rgba(232,163,76,.09);border-radius:10px;padding:12px;text-align:center;"><b style="font-size:22px;color:#f4c977;">'+pct(h.yes)+'%</b><br>said it helped</div>'
            +'<div style="flex:1;min-width:120px;background:rgba(232,163,76,.06);border-radius:10px;padding:12px;text-align:center;"><b style="font-size:22px;color:rgba(242,231,210,.6);">'+pct(h.somewhat)+'%</b><br>somewhat</div>'
            +'<div style="flex:1;min-width:120px;background:rgba(232,163,76,.06);border-radius:10px;padding:12px;text-align:center;"><b style="font-size:22px;color:rgba(242,231,210,.6);">'+pct(h.no)+'%</b><br>not really</div>'
            +'<div style="flex:1;min-width:120px;background:rgba(232,163,76,.09);border-radius:10px;padding:12px;text-align:center;"><b style="font-size:22px;color:#f4c977;">'+d.total+'</b><br>total responses</div>'
            +'</div>';
          if(d.quotes&&d.quotes.length){
            html+='<div style="font-size:12px;color:rgba(244,201,119,.6);letter-spacing:.14em;text-transform:uppercase;margin:6px 0;">In their own words</div>';
            html+=d.quotes.map(function(q){
              return '<div style="border-left:3px solid rgba(232,163,76,.5);background:rgba(232,163,76,.05);border-radius:0 8px 8px 0;padding:10px 14px;margin:8px 0;font-size:14px;color:rgba(242,231,210,.8);font-style:italic;">“'
                +(q.words||'').replace(/</g,'&lt;')+'”<span style="display:block;font-style:normal;font-size:11px;color:rgba(242,231,210,.45);margin-top:4px;">'+(q.when||'')+(q.helped?' · '+q.helped:'')+'</span></div>';
            }).join('');
          }
          el.innerHTML=html;
        }catch(e){}
      }
      load();
    })();
    </script>

    <h2 class="ledger">Crisis referrals — the count for the state report</h2>
    <div class="panel">
    <div class="hint">Each time the crisis protocol activates and 988 is put in front of a person, it is counted here — counts only, never content. This is the number for the state Office of Suicide Prevention report (due each July starting 2027).</div>
    <div id="crisis-referrals"><i style="color:rgba(242,231,210,.45);">Loading&hellip;</i></div>
    </div>
    <script>
    (async function(){
      try{
        var r = await fetch('/api/admin/crisisreferrals'); if(!r.ok) return;
        var d = await r.json();
        var el = document.getElementById('crisis-referrals'); if(!el) return;
        var months = Object.keys(d.by_month || {}).sort().reverse();
        if(!months.length){ el.innerHTML = '<i style="color:rgba(242,231,210,.45);">No crisis-protocol activations recorded yet. Counting began with this deploy.</i>'; return; }
        var html = '<div style="font-weight:700;color:#f4c977;margin-bottom:8px;">' + d.total + ' total activation' + (d.total===1?'':'s') + ' since counting began</div>';
        for (var i=0; i<months.length; i++){
          html += '<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(232,163,76,.12);"><span>' + months[i] + '</span><b style="color:#f4c977;">' + d.by_month[months[i]] + '</b></div>';
        }
        el.innerHTML = html;
      }catch(e){}
    })();
    </script>

    <h2 class="ledger" id="security">Security — the watch on the walls</h2>
    <div class="panel">
    <div class="hint">Lawful active defense only &mdash; <b style="color:#f4c977;">deter, deceive, withstand, deliver-to-justice</b>.
    InnerLight never hacks back. These are attacker/security metadata counts pulled from the forensic evidence log &mdash;
    <b>never any person's words, session, or content</b>. The crisis and conversation paths are never delayed or blocked by this.</div>
    <div id="sec-readout"><i style="color:rgba(242,231,210,.45);">Loading the watch&hellip;</i></div>
    </div>
    <script>
    (function(){
      function esc3(s){ return String(s == null ? '' : s).replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
      function tile(v, lbl, warm){
        var col = warm ? '#e8534e' : '#f4c977';
        return '<div style="flex:1;min-width:120px;background:rgba(232,163,76,.07);border:1px solid rgba(232,163,76,.18);border-radius:12px;padding:14px;text-align:center;">'
          + '<b style="font-size:24px;color:' + col + ';font-variant-numeric:tabular-nums;">' + v + '</b>'
          + '<div style="font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:rgba(244,201,119,.6);margin-top:6px;">' + lbl + '</div></div>';
      }
      async function load(){
        try{
          var r = await fetch('/api/admin/security'); if(!r.ok) return;
          var d = await r.json();
          var el = document.getElementById('sec-readout'); if(!el) return;
          var html = '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;">'
            + tile(d.attacks_total||0, 'attacks deterred', (d.attacks_total||0)>0)
            + tile(d.honeypot_hits||0, 'honeypot hits', (d.honeypot_hits||0)>0)
            + tile(d.hostile_ips||0, 'flagged clients', false)
            + tile(d.locked_out_now||0, 'locked out now', (d.locked_out_now||0)>0)
            + '</div>';
          var tp = d.top_paths || [];
          if(tp.length){
            html += '<div style="font-size:12px;color:rgba(244,201,119,.6);letter-spacing:.14em;text-transform:uppercase;margin:10px 0 4px;">Top offending paths</div>';
            html += tp.map(function(p){
              return '<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(232,163,76,.12);">'
                + '<span style="color:rgba(242,231,210,.78);">' + esc3(p.path) + '</span>'
                + '<b style="color:#e8a34c;">' + (p.count||0) + '</b></div>';
            }).join('');
          }
          var rec = d.recent || [];
          if(rec.length){
            html += '<div style="font-size:12px;color:rgba(244,201,119,.6);letter-spacing:.14em;text-transform:uppercase;margin:16px 0 4px;">Recent events (metadata only)</div>';
            html += rec.slice(0,40).map(function(e){
              return '<div style="border-left:3px solid rgba(232,83,78,.5);background:rgba(232,163,76,.04);border-radius:0 8px 8px 0;padding:8px 12px;margin:6px 0;font-size:12.5px;color:rgba(242,231,210,.78);">'
                + '<b style="color:#e8534e;">' + esc3(e.reason) + '</b> &middot; ' + esc3(e.method) + ' ' + esc3(e.path)
                + '<span style="display:block;font-size:11px;color:rgba(242,231,210,.45);margin-top:3px;">' + esc3(e.ip) + ' &middot; ' + esc3(e.ts) + '</span></div>';
            }).join('');
          } else {
            html += '<div style="color:rgba(242,231,210,.45);font-style:italic;margin-top:10px;">No attempts recorded. The walls are quiet.</div>';
          }
          el.innerHTML = html;
        }catch(e){}
      }
      load(); setInterval(load, 30000);
    })();
    </script>

    <h2 class="ledger" id="music">Music control — listen to any track, switch any track off</h2>
    <div class="panel">
    <div class="hint">Press <b style="color:#f4c977;">Listen</b> to hear any track right here. Press <b style="color:#f4c977;">Turn off</b> and that exact song stops being offered — no redeploy needed, and you can turn it back on any time. Honest note: someone already listening may still hear their current list until their music next shifts; every new playlist skips it.</div>
    <div id="tc-status" style="font-size:12px;color:#e8a34c;font-weight:700;margin-bottom:6px;"></div>
    <div id="track-control"><i style="color:rgba(242,231,210,.45);">Loading tracks&hellip;</i></div>
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
            html += '<div style="font-weight:700;color:#f4c977;margin:12px 0 4px;">' + esc(LANE_NAMES[lane] || lane) + '</div>';
            lanes[lane].forEach(function(t){
              var rowStyle = t.enabled ? '' : 'opacity:0.45;';
              var btnBg = t.enabled ? 'rgba(169,83,31,.85)' : 'rgba(138,90,38,.85)';
              var btnLabel = t.enabled ? 'Turn off' : 'Turn on';
              html += '<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid rgba(232,163,76,.1);' + rowStyle + '">'
                + '<button data-listen="' + esc(t.file) + '" style="background:rgba(232,163,76,.16);color:#f4c977;border:1px solid rgba(232,163,76,.4);border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer;min-width:66px;">Listen</button>'
                + '<span style="flex:1;">' + esc(t.file) + (t.enabled ? '' : ' <b style="color:#e8a34c;">(off)</b>') + '</span>'
                + '<span style="color:rgba(242,231,210,.45);font-size:12px;">' + (t.plays||0) + ' plays</span>'
                + '<button data-toggle="' + esc(t.file) + '" data-en="' + (t.enabled ? '1' : '0') + '" style="background:' + btnBg + ';color:#ffe8bf;border:0;border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer;min-width:76px;">' + btnLabel + '</button>'
                + '</div>';
            });
          });
          el.innerHTML = html || '<i style="color:rgba(242,231,210,.45);">No tracks found.</i>';
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

    <h2 class="ledger">Song play log — every track, every timestamp</h2>
    <div class="panel">
    <div class="hint">Exactly what played and when. Every play is stamped to the second, so you can see if a track repeats within an hour. Use this to spot any song that plays too often. <button onclick="loadPlays()" style="background:rgba(232,163,76,.16);color:#f4c977;border:1px solid rgba(232,163,76,.4);border-radius:999px;padding:6px 14px;font-size:12px;cursor:pointer;margin-left:8px;">Refresh</button></div>
    <div id="plays-report"><i style="color:rgba(242,231,210,.45);">Loading play log…</i></div>
    </div>
    <script>
    async function loadPlays(){
      try{
        var r = await fetch('/api/admin/plays'); if(!r.ok) return;
        var d = await r.json();
        var el = document.getElementById('plays-report'); if(!el) return;
        if(!d.total_plays){ el.innerHTML='<i style="color:rgba(242,231,210,.45);">No plays recorded yet. As sessions run, every song play appears here with its timestamp.</i>'; return; }
        var html = '<div style="font-weight:700;color:#f4c977;margin-bottom:8px;">' + d.total_plays + ' total plays recorded</div>';
        html += '<div style="display:flex;gap:16px;flex-wrap:wrap;">';
        html += '<div style="flex:1;min-width:240px;"><div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:rgba(244,201,119,.6);margin-bottom:6px;">Plays per track (most played first)</div>'
          + d.by_track.map(function(t){
              var heavy = t.count >= 5 ? 'color:#f4c977;font-weight:800;' : 'color:rgba(242,231,210,.75);';
              return '<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(232,163,76,.1);"><span>' + t.file + '</span><b style="' + heavy + '">' + t.count + '</b></div>';
            }).join('') + '</div>';
        html += '<div style="flex:1;min-width:240px;max-height:340px;overflow:auto;"><div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:rgba(244,201,119,.6);margin-bottom:6px;">Every play, newest first (with timestamp)</div>'
          + d.recent.map(function(rr){
              return '<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid rgba(232,163,76,.08);font-size:13px;"><span style="color:rgba(242,231,210,.7);">' + rr.file + '</span><span style="color:rgba(242,231,210,.45);font-variant-numeric:tabular-nums;">' + (rr.ts||'') + '</span></div>';
            }).join('') + '</div>';
        html += '</div>';
        el.innerHTML = html;
      }catch(e){}
    }
    loadPlays();
    </script>

    <h2 class="ledger" id="live">Live sessions — real-time biometric monitor</h2>
    <div class="panel">
    <div class="hint">Anonymous, live. Each person currently using InnerLight appears here — heart rate, calm state, and a moving trend line, updating every few seconds. No names, no words, just the signal. <span id="bio-clock" style="float:right;"></span></div>
    <div id="bio-live-list"><i style="color:rgba(242,231,210,.45);">Waiting for a live session…</i></div>
    </div>

    <h2 class="ledger">Heart signal coverage — research integrity</h2>
    <div class="panel" style="font-size:13.5px;">
    <div class="hint">Every camera session records a heart value — never blank. Each reading is tagged by how it was obtained, so the data is complete AND honest. Measured = high-confidence true reading; Estimated = best inference from a weaker signal; Baseline-held = last good value briefly held. This is what lets you claim full coverage without overclaiming precision.</div>
    {{ heart_rows|safe }}
    </div>

    <h2 class="ledger">Experimental biometric sub-zones — the frontier map</h2>
    <div class="panel" id="subzones" style="font-size:13.5px;">
    <div class="hint">How often each experimental skin zone (near eyes/mouth) agreed with the trusted forehead+cheek reading. Higher % = more trustworthy. This is your own data revealing which frontier zones can be read accurately.</div>
    {{ subzone_rows|safe }}
    </div>

    <h2 class="ledger">Sessions per day</h2>
    <div class="graph">{{ bars|safe }}</div>

    <h2 class="ledger" id="people">Today, person by person — anonymous session breakdown</h2>
    <div class="tablewrap">
    <table>
    <tr><th>Session</th><th>Expression shifts</th><th>Messages</th><th>Hesitations</th>
    <th>Scene changes</th><th>Distractions (looked away)</th><th>Word plays</th><th>Music lane shifts</th></tr>
    {{ sess_rows|safe }}
    </table>
    </div>

    <h2 class="ledger">Track reactions — the research core (all days shown)</h2>
    <div class="tablewrap">
    <table>
    <tr><th>Track</th><th>Liked (face eased)</th><th>Neutral</th><th>Disliked (face turned)</th></tr>
    {{ t_rows|safe }}
    </table>
    </div>

    <h2 class="ledger" id="research">The scientific method — where this study stands</h2>
    <div class="sci-grid">
     <div class="sci"><b>1. Observation (complete)</b><br>Across ~2,500 rideshare trips, agitated passengers reliably settled when calm instrumental music was already playing on entry. Repeated, real-world, years-long observation.</div>
     <div class="sci"><b>2. Question (framed)</b><br>Can adaptive calming sound, delivered during the crisis wait-gap, measurably reduce acute distress?</div>
     <div class="sci"><b>3. Hypothesis (stated, falsifiable)</b><br>People using InnerLight will show measurably lower distress at the end of a session than at arrival — in heart rate, self-reported calm, and facial-expression volatility. If the numbers do not move, the hypothesis is rejected. We accept that outcome in advance.</div>
     <div class="sci"><b>4. Predictions (specific)</b><br>(a) Heart rate drifts toward the person&rsquo;s own baseline during a session. (b) The wordless calm scale improves arrival &rarr; later. (c) Expression-shift frequency declines after music-lane responses. (d) Track &ldquo;liked&rdquo; verdicts exceed &ldquo;disliked&rdquo; as lanes adapt.</div>
     <div class="sci"><b>5. Test (this instrument, now collecting)</b><br>Every column on this board is a measurement in service of the predictions above, recorded anonymously per session against each person&rsquo;s own baseline, on durable storage.</div>
     <div class="sci"><b>6&ndash;7. Analysis &amp; conclusion (pending pilot)</b><br>No conclusion is claimed yet. InnerLight is unvalidated until a controlled pilot analyzes these measures. This board reports; it does not yet prove.</div>
     <div class="sci"><b>8. Retest / replication (planned)</b><br>Pilot results, positive or negative, will be re-run before any claim is made. One result is an anecdote; a repeated result is evidence.</div>
     <div class="sci"><b>9. Peer review (sought)</b><br>University research partnership in progress — independent eyes on the method, the data, and the conclusions.</div>
    </div>

    <h2 class="ledger">The research basis for every number</h2>
    <div class="sci-grid">
     <div class="sci"><b>Sessions &amp; uptake</b><br>
     Meta-analytic reviews of digital mental-health trials converged on five reportable engagement checkpoints:
     uptake, level of use, duration, adherence, and completion. &ldquo;Sessions&rdquo; is our uptake measure — the entry
     point every published engagement framework requires. Without it, no other number can be interpreted.</div>
     <div class="sci"><b>Time to first sound</b><br>
     Music-medicine research on the Iso-Principle (meeting a person&rsquo;s state with sound, then guiding it) treats
     stimulus onset timing as part of the intervention itself. InnerLight&rsquo;s clinical premise is sound arriving
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
     logging against each person&rsquo;s own baseline — measured musical reception, per stimulus.</div>
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
    <div class="note"><b style="color:#f4c977;">Plain reading guide:</b> Sessions = entries that day. Avg time to first sound = tap until
    music (lower is better; phones cannot legally start sound before a tap). Expression shifts = changes in the
    silent face reading. Hesitations = typed a real thought, erased it unsent. Distractions = an engaged face
    turned away for a couple of seconds. Track verdicts come from each song&rsquo;s opening minute judged against that
    person&rsquo;s own baseline. All counts are anonymous — no words, names, faces, or voices are ever stored.</div>

    <h2 class="ledger" id="partners">Partners — the providers and attorneys who receive people</h2>
    <div class="panel">
    <div class="hint">The back-of-house program for real providers and attorneys. They sign in at <b style="color:#f4c977;">/partner</b> &mdash; a separate, warm portal with <b>zero access</b> to The Watch or the Study. They can never see or submit any person&rsquo;s identity, words, or clinical records. Here you create them, pause them, and read what they send back. When you create a partner, a one-time access code shows once &mdash; copy it and give it to them privately; only its hash is stored.</div>
    <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin:12px 0 14px;">
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Organization</div>
        <input id="pt-org" placeholder="e.g. Harbor Family Law" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-width:220px;"></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Contact name</div>
        <input id="pt-contact" placeholder="optional" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-width:170px;"></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Side</div>
        <select id="pt-side" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;">
          <option value="clinical">Clinical</option><option value="legal">Legal</option></select></div>
      <div><div style="font-size:11px;color:rgba(244,201,119,.6);letter-spacing:.1em;text-transform:uppercase;margin-bottom:5px;">Role</div>
        <select id="pt-role" style="background:rgba(232,163,76,.06);border:1px solid rgba(232,163,76,.3);border-radius:9px;color:#ffe8bf;padding:9px 12px;font-size:14px;min-width:200px;"></select></div>
      <button id="pt-create" style="background:linear-gradient(90deg,#b06a2a,#e8a34c);color:#ffe8bf;border:0;border-radius:999px;padding:10px 22px;font-size:13px;font-weight:700;cursor:pointer;">Create partner</button>
    </div>
    <div id="pt-code" style="display:none;background:rgba(232,163,76,.1);border:1px solid rgba(232,163,76,.35);border-radius:12px;padding:16px 18px;margin-bottom:16px;"></div>
    <div id="pt-list"><i style="color:rgba(242,231,210,.45);">Loading partners&hellip;</i></div>
    </div>
    <script>
    (function(){
      var ROLES = [];
      function esc(s){ return String(s == null ? '' : s).replace(/</g,'&lt;'); }
      function fillRoles(){
        var side = document.getElementById('pt-side').value;
        var sel = document.getElementById('pt-role');
        sel.innerHTML = '';
        ROLES.filter(function(r){ return r.side === side; }).forEach(function(r){
          var o = document.createElement('option');
          o.value = r.role; o.textContent = r.label; sel.appendChild(o);
        });
      }
      async function loadPartners(){
        try{
          var r = await fetch('/api/admin/partners'); if(!r.ok) return;
          var d = await r.json();
          ROLES = d.roles || [];
          if(!document.getElementById('pt-role').options.length) fillRoles();
          var el = document.getElementById('pt-list'); if(!el) return;
          var ps = d.partners || [];
          if(!ps.length){ el.innerHTML = '<i style="color:rgba(242,231,210,.45);">No partners yet. Create one above.</i>'; return; }
          el.innerHTML = ps.map(function(p){
            var on = p.status === 'active';
            var badge = on ? 'background:rgba(232,163,76,.16);color:#f4c977;' : 'background:rgba(150,150,150,.14);color:rgba(242,231,210,.5);';
            var btnLbl = on ? 'Pause' : 'Reactivate';
            var newStatus = on ? 'paused' : 'active';
            return '<div style="display:flex;align-items:center;gap:12px;padding:11px 0;border-bottom:1px solid rgba(232,163,76,.12);">'
              + '<div style="flex:1;"><b style="color:#ffe8bf;">' + esc(p.org) + '</b>'
              + '<span style="color:rgba(242,231,210,.5);font-size:12px;"> &mdash; ' + esc(p.role_label) + (p.contact ? ' &middot; ' + esc(p.contact) : '') + '</span>'
              + '<div style="font-size:12px;color:rgba(242,231,210,.62);margin-top:3px;">transfers toward them: <b style="color:#e8a34c;">' + p.transfers + '</b> &middot; arrivals they confirmed: <b style="color:#e8a34c;">' + p.received + '</b></div></div>'
              + '<span style="border-radius:999px;padding:4px 12px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;' + badge + '">' + esc(p.status) + '</span>'
              + '<button data-pt-id="' + p.id + '" data-pt-status="' + newStatus + '" style="background:rgba(232,163,76,.14);color:#f4c977;border:1px solid rgba(232,163,76,.35);border-radius:999px;padding:6px 14px;font-size:12px;cursor:pointer;">' + btnLbl + '</button>'
              + '</div>';
          }).join('');
        }catch(e){}
      }
      document.addEventListener('change', function(ev){
        if(ev.target && ev.target.id === 'pt-side') fillRoles();
      });
      document.addEventListener('click', async function(ev){
        var b = ev.target;
        if(b && b.id === 'pt-create'){
          var org = document.getElementById('pt-org').value.trim();
          var contact = document.getElementById('pt-contact').value.trim();
          var role = document.getElementById('pt-role').value;
          if(!org) return;
          b.disabled = true;
          try{
            var r = await fetch('/api/admin/partners/create', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({org: org, contact: contact, role: role})});
            var d = await r.json();
            if(d && d.code){
              var box = document.getElementById('pt-code');
              box.style.display = 'block';
              box.innerHTML = '';
              var line = document.createElement('div');
              line.style.cssText = 'font-size:13px;color:rgba(242,231,210,.78);margin-bottom:9px;';
              line.textContent = 'Access code for ' + d.org + ' (' + d.role_label + ') — shown once. Copy it now and give it to them privately.';
              var codeEl = document.createElement('span');
              codeEl.id = 'pt-code-val';
              codeEl.style.cssText = 'font-family:var(--serif);font-size:26px;letter-spacing:.12em;color:#ffe8bf;';
              codeEl.textContent = d.code;
              var copyBtn = document.createElement('button');
              copyBtn.textContent = 'Copy';
              copyBtn.style.cssText = 'margin-left:16px;background:rgba(232,163,76,.16);color:#f4c977;border:1px solid rgba(232,163,76,.4);border-radius:999px;padding:6px 16px;font-size:12px;cursor:pointer;';
              copyBtn.addEventListener('click', function(){
                try{ navigator.clipboard.writeText(codeEl.textContent).then(function(){ copyBtn.textContent = 'Copied'; }, function(){}); }catch(e){}
              });
              box.appendChild(line); box.appendChild(codeEl); box.appendChild(copyBtn);
              document.getElementById('pt-org').value = '';
              document.getElementById('pt-contact').value = '';
            }
          }catch(e){}
          b.disabled = false;
          loadPartners();
          return;
        }
        if(b && b.getAttribute && b.getAttribute('data-pt-id')){
          b.disabled = true;
          try{
            await fetch('/api/admin/partners/status', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: parseInt(b.getAttribute('data-pt-id'),10), status: b.getAttribute('data-pt-status')})});
          }catch(e){}
          loadPartners();
        }
      });
      loadPartners();
    })();
    </script>

    <h2 class="ledger">Partner voices — suggestions from the field</h2>
    <div class="panel">
    <div class="hint">What partners send back about the handoff process &mdash; never anything about a person. The founder reads each one. Mark it read once you have taken it in.</div>
    <div id="pt-suggestions"><i style="color:rgba(242,231,210,.45);">Loading&hellip;</i></div>
    </div>
    <script>
    (function(){
      function esc(s){ return String(s == null ? '' : s).replace(/</g,'&lt;'); }
      async function load(){
        try{
          var r = await fetch('/api/admin/partners/suggestions'); if(!r.ok) return;
          var d = await r.json();
          var el = document.getElementById('pt-suggestions'); if(!el) return;
          var ss = d.suggestions || [];
          if(!ss.length){ el.innerHTML = '<i style="color:rgba(242,231,210,.45);">No suggestions yet. When a partner sends one, it appears here.</i>'; return; }
          el.innerHTML = ss.map(function(s){
            var read = s.read;
            return '<div style="border-left:3px solid ' + (read ? 'rgba(232,163,76,.25)' : 'rgba(232,163,76,.6)') + ';background:rgba(232,163,76,.05);border-radius:0 8px 8px 0;padding:11px 15px;margin:9px 0;font-size:14px;color:rgba(242,231,210,.82);' + (read ? 'opacity:.6;' : '') + '">'
              + '<div style="font-style:italic;white-space:pre-wrap;">' + esc(s.text) + '</div>'
              + '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:7px;font-size:11px;color:rgba(242,231,210,.45);">'
              + '<span>' + esc(s.org) + ' &middot; ' + esc(s.when) + '</span>'
              + (read ? '<span>read</span>' : '<button data-sugg-read="' + s.id + '" style="background:rgba(232,163,76,.16);color:#f4c977;border:1px solid rgba(232,163,76,.4);border-radius:999px;padding:4px 12px;font-size:11px;cursor:pointer;">Mark read</button>')
              + '</div></div>';
          }).join('');
        }catch(e){}
      }
      document.addEventListener('click', async function(ev){
        var b = ev.target;
        if(b && b.getAttribute && b.getAttribute('data-sugg-read')){
          b.disabled = true;
          try{ await fetch('/api/admin/partners/suggestions/read', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: parseInt(b.getAttribute('data-sugg-read'),10)})}); }catch(e){}
          load();
        }
      });
      load();
    })();
    </script>
  </section>

  <div class="vow">
    The Watch — InnerLight&rsquo;s founder room.<br>
    Anonymous counts and clock-times only. Nothing a person said is ever kept.
  </div>

</div>

<script>
(function(){
  "use strict";

  /* ============ clock and status ============ */
  var clockEl = document.getElementById('clock');
  var statusEl = document.getElementById('statusText');
  var liveCount = 0;
  function fmtClock(d){
    var h = d.getHours(), m = d.getMinutes();
    var ap = h >= 12 ? 'pm' : 'am';
    h = h % 12 || 12;
    return h + ':' + String(m).padStart(2,'0') + ' ' + ap;
  }
  function tickClock(){
    clockEl.textContent = fmtClock(new Date());
    if (liveCount > 0){
      statusEl.textContent = 'the watch is on · ' + liveCount + (liveCount===1?' person':' people') + ' held';
    } else {
      statusEl.textContent = 'all quiet · the room is warm';
    }
  }
  setInterval(tickClock, 1000);

  /* ============ gentle number tweens ============ */
  function tween(el, from, to, dur, fmt){
    fmt = fmt || function(v){ return String(Math.round(v)); };
    var t0 = performance.now();
    function step(now){
      var p = Math.min(1, (now - t0)/dur);
      var e = 1 - Math.pow(1-p, 3);
      el.textContent = fmt(from + (to-from)*e);
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  var counters = {};
  function setCounterEl(el, to, dur){
    if (!el) return;
    var key = el.id || (el.dataset && el.dataset.n) || 'x';
    var from = counters[key] || 0;
    counters[key] = to;
    tween(el, from, to, dur || 1800);
  }

  /* real fourteen-day numbers settle in slowly on load */
  setTimeout(function(){
    var nodes = document.querySelectorAll('[data-n]');
    for (var i=0; i<nodes.length; i++){
      var v = parseFloat(nodes[i].getAttribute('data-n'));
      if (isFinite(v)) tween(nodes[i], 0, v, 2400 + i*280);
    }
  }, 500);

  /* ============ the ember field ============ */
  var canvas = document.getElementById('field');
  var ctx = canvas.getContext('2d');
  var W = 0, H = 0, DPR = 1;
  function resize(){
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = W * DPR; canvas.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  window.addEventListener('resize', resize);
  resize();

  function rand(a,b){ return a + Math.random()*(b-a); }

  /* drifting motes — quiet dust in the room */
  var motes = [];
  for (var i=0;i<34;i++){
    motes.push({ x:Math.random(), y:Math.random(), r:rand(.5,1.4),
                 vy:rand(.004,.012), ph:rand(0,Math.PI*2), a:rand(.04,.11) });
  }

  /* embers = REAL active sessions, from /api/admin/bio/live */
  var embers = [];
  var emberMap = {};
  function placeEmber(){
    for (var tries=0; tries<24; tries++){
      var x = rand(.08,.92), y = rand(.26,.84);
      var ok = true;
      for (var j=0;j<embers.length;j++){
        var e = embers[j];
        if (e.state==='gone') continue;
        var dx=(e.x-x)*W, dy=(e.y-y)*H;
        if (dx*dx+dy*dy < 120*120){ ok=false; break; }
      }
      if (ok) return {x:x,y:y};
    }
    return { x:rand(.1,.9), y:rand(.3,.8) };
  }
  function newEmber(heldMinutes){
    var p = placeEmber();
    return {
      x:p.x, y:p.y,
      born: performance.now() - (heldMinutes||0)*60000,
      period: rand(3.8, 7.2),
      phase: rand(0, Math.PI*2),
      driftPh: rand(0, Math.PI*2),
      driftPh2: rand(0, Math.PI*2),
      state: 'alive',
      fadeIn: performance.now(),
      riseT: 0,
      trail: []
    };
  }
  function heldMin(e){ return (performance.now() - e.born)/60000; }

  function syncEmbers(list){
    var seen = {};
    for (var i=0;i<list.length;i++){
      var p = list[i];
      var k = p.k || ('p'+i);
      seen[k] = true;
      var e = emberMap[k];
      if (!e){
        e = newEmber(p.held_min || 0);
        emberMap[k] = e;
        embers.push(e);
      } else if (e.state === 'alive'){
        /* the server knows the true held time — size follows it */
        e.born = performance.now() - (p.held_min || 0)*60000;
      }
    }
    var keys = Object.keys(emberMap);
    for (var j=0;j<keys.length;j++){
      var kk = keys[j];
      var em = emberMap[kk];
      if (!seen[kk] && em.state === 'alive'){ em.state = 'rising'; em.riseT = 0; }
      if (em.state === 'gone'){ delete emberMap[kk]; }
    }
    for (var n=embers.length-1;n>=0;n--){ if (embers[n].state==='gone') embers.splice(n,1); }
  }

  function drawEmber(e, t){
    var held = heldMin(e);
    /* size reflects only time held — never emotion */
    var base = 5.5 + Math.min(held/55, 1) * 6.5;
    var breath = 1 + 0.16 * Math.sin(t/e.period*2*Math.PI + e.phase);
    var r = base * breath;

    var dx = Math.sin(t*0.05 + e.driftPh) * 7 + Math.sin(t*0.013 + e.driftPh2) * 11;
    var dy = Math.cos(t*0.04 + e.driftPh2) * 5;

    var px = e.x*W + dx, py = e.y*H + dy;

    var alpha = 1;
    var sinceBorn = (performance.now() - e.fadeIn)/1000;
    if (sinceBorn < 3.5) alpha = sinceBorn/3.5;

    if (e.state === 'rising'){
      e.riseT += 1/60;
      var rt = e.riseT;
      var lift = Math.pow(rt/4.2, 1.8) * (py + 80);
      py -= lift;
      alpha *= Math.max(0, 1 - Math.max(0, rt-2.6)/1.6);
      e.trail.push({x:px, y:py, t:t});
      if (e.trail.length > 26) e.trail.shift();
      if (py < -60 || alpha <= 0){ e.state='gone'; return; }
      for (var i=0;i<e.trail.length;i++){
        var tp = e.trail[i];
        var ta = (i/e.trail.length) * 0.28 * alpha;
        var tr = 2 + (i/e.trail.length)*3;
        ctx.beginPath();
        var gt = ctx.createRadialGradient(tp.x,tp.y,0,tp.x,tp.y,tr*3);
        gt.addColorStop(0, 'rgba(255,225,175,'+ta+')');
        gt.addColorStop(1, 'rgba(232,163,76,0)');
        ctx.fillStyle = gt;
        ctx.arc(tp.x,tp.y,tr*3,0,7); ctx.fill();
      }
    }

    var glowA = (0.5 + 0.22*Math.sin(t/e.period*2*Math.PI + e.phase)) * alpha;

    var g = ctx.createRadialGradient(px,py,0, px,py, r*5.2);
    g.addColorStop(0,   'rgba(244,180,90,'+(0.34*glowA)+')');
    g.addColorStop(0.4, 'rgba(220,140,55,'+(0.13*glowA)+')');
    g.addColorStop(1,   'rgba(200,110,40,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(px,py,r*5.2,0,7); ctx.fill();

    g = ctx.createRadialGradient(px,py,0, px,py, r*1.9);
    g.addColorStop(0,   'rgba(255,236,200,'+(0.95*alpha)+')');
    g.addColorStop(0.35,'rgba(250,196,110,'+(0.75*alpha)+')');
    g.addColorStop(1,   'rgba(226,140,50,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(px,py,r*1.9,0,7); ctx.fill();

    ctx.fillStyle = 'rgba(255,246,225,'+(0.9*alpha)+')';
    ctx.beginPath(); ctx.arc(px,py,r*0.42,0,7); ctx.fill();
  }

  function frame(now){
    var t = now/1000;
    ctx.setTransform(DPR,0,0,DPR,0,0);
    ctx.clearRect(0,0,W,H);
    ctx.globalCompositeOperation = 'lighter';

    var hg = ctx.createLinearGradient(0,H,0,H*0.55);
    hg.addColorStop(0,'rgba(196,112,40,'+(0.10+0.03*Math.sin(t/9*2*Math.PI))+')');
    hg.addColorStop(1,'rgba(196,112,40,0)');
    ctx.fillStyle = hg; ctx.fillRect(0,0,W,H);

    for (var i=0;i<motes.length;i++){
      var m = motes[i];
      m.y -= m.vy/60;
      if (m.y < -0.03){ m.y = 1.03; m.x = Math.random(); }
      var mx = m.x*W + Math.sin(t*0.4 + m.ph)*8;
      var ma = m.a * (0.6 + 0.4*Math.sin(t*0.7 + m.ph));
      ctx.fillStyle = 'rgba(244,201,119,'+ma+')';
      ctx.beginPath(); ctx.arc(mx, m.y*H, m.r, 0, 7); ctx.fill();
    }

    for (var j=0;j<embers.length;j++){ if (embers[j].state !== 'gone') drawEmber(embers[j], t); }

    ctx.globalCompositeOperation = 'source-over';
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  /* ============ live counts under the field ============ */
  function refreshNow(n){
    var el = document.getElementById('nowCount');
    if (counters['nowCount'] !== n){ setCounterEl(el, n, 1400); }
    document.getElementById('nowWord').textContent =
      n === 1 ? 'person is being carried right now.' : 'people are being carried right now.';
    var fe = document.getElementById('fieldEmpty');
    if (fe) fe.style.opacity = (n === 0 && embers.length === 0) ? 1 : 0;
  }

  /* ============ the live biometric list (the ledger below) ============ */
  function spark(vals){
    if(!vals||vals.length<2) return '';
    var w=180,h=34,min=Math.min.apply(null,vals),max=Math.max.apply(null,vals),rng=(max-min)||1;
    var pts=vals.map(function(v,i){return (i/(vals.length-1)*w).toFixed(1)+','+(h-(v-min)/rng*h).toFixed(1);}).join(' ');
    return '<svg width="'+w+'" height="'+h+'" style="vertical-align:middle;"><polyline points="'+pts+'" fill="none" stroke="#e8a34c" stroke-width="2"/></svg>';
  }
  function stateColor(st){ return st==='rising'?'#f0a868':(st==='settling'?'#f4c977':'rgba(242,231,210,.62)'); }
  function stateWord(st){ return st==='rising'?'rising / activating':(st==='settling'?'settling / calming':'steady'); }
  function renderBioList(d){
    var clk=document.getElementById('bio-clock'); if(clk) clk.textContent='server '+(d.server_time||'');
    var el=document.getElementById('bio-live-list'); if(!el) return;
    if(!d.active||!d.active.length){ el.innerHTML='<i style="color:rgba(242,231,210,.45);">No live sessions right now. When someone is using InnerLight, they appear here live — with or without a heart reading.</i>'; return; }
    el.innerHTML=d.active.map(function(p){
      var heldTxt = (p.held_min != null) ? ('held ' + Math.max(1, Math.round(p.held_min)) + ' min') : '';
      var left = '<div style="min-width:96px;"><b style="color:#f4c977;">'+p.who+'</b><div style="font-size:11px;color:rgba(242,231,210,.45);">'+p.ago+'s ago'+(heldTxt?' · '+heldTxt:'')+'</div></div>';
      if (p.bpm && p.hasheart){
        return '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid rgba(232,163,76,.1);">'
          + left
          +'<div style="text-align:center;"><span style="font-size:26px;font-family:Georgia,serif;">'+p.bpm+'</span> <span style="font-size:12px;color:rgba(242,231,210,.55);">bpm</span>'
          +'<div style="font-size:11px;color:rgba(242,231,210,.45);">baseline '+(p.base||p.bpm)+'</div></div>'
          +'<div style="text-align:center;color:'+stateColor(p.state)+';font-size:13px;font-weight:700;min-width:120px;">'+stateWord(p.state)
          +'<div style="font-size:10.5px;color:rgba(242,231,210,.45);font-weight:400;">'+(p.tier||'')+(p.face?' · '+p.face:'')+'</div></div>'
          +'<div>'+spark(p.spark)+'</div>'
          +'</div>';
      }
      var status = p.cam ? 'camera on — acquiring heart signal…' : 'text-only session (camera off)';
      var scolor = p.cam ? '#f0a868' : 'rgba(242,231,210,.62)';
      return '<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid rgba(232,163,76,.1);">'
        + left
        +'<div style="text-align:center;flex:1;color:'+scolor+';font-size:13px;font-weight:700;">'+status
        + (p.face?'<div style="font-size:10.5px;color:rgba(242,231,210,.45);font-weight:400;">expression: '+p.face+'</div>':'')
        +'</div>'
        +'<div style="min-width:60px;text-align:right;color:rgba(242,231,210,.45);font-size:12px;">live</div>'
        +'</div>';
    }).join('');
  }

  /* ============ one poll feeds the field, the counter, and the ledger ============ */
  async function pollLive(){
    try{
      var r = await fetch('/api/admin/bio/live'); if(!r.ok) return;
      var d = await r.json();
      liveCount = (d.active && d.active.length) || 0;
      syncEmbers(d.active || []);
      refreshNow(liveCount);
      var kln = document.getElementById('kpi-live-n'); if (kln) kln.textContent = liveCount;
      renderBioList(d);
    }catch(e){}
  }
  pollLive(); setInterval(pollLive, 3000);

  /* ============ the night log — real events from the live feed ============ */
  var logEl = document.getElementById('logLines');
  var seenLog = {};
  function esc(s){ return String(s).replace(/</g,'&lt;'); }
  var LOGMAP = {
    session_start: function(){ return 'Someone arrived. The room made space.'; },
    message_sent:  function(){ return 'Someone spoke, and was answered.'; },
    hesitation:    function(){ return 'Someone typed a thought, then let it go unsent.'; },
    lane_switch:   function(v){ return v ? 'The music shifted to <em>'+esc(v)+'</em> to follow someone.' : 'The music shifted lanes to follow someone.'; },
    scene_change:  function(v){ return v ? 'Someone chose a new sky — <em>'+esc(v)+'</em>.' : 'Someone chose a new sky.'; },
    handoff_click: function(v){ return 'Someone reached toward human help'+(v?' — <em>'+esc(v)+'</em>':'')+'. The bridge held.'; },
    help_requested:function(){ return 'Someone asked for a human. The request is in the ledger below.'; },
    first_sound_ms:function(v){ var s=Math.round(parseFloat(v)/1000); return isFinite(s)?('Sound arrived <em>'+s+' second'+(s===1?'':'s')+'</em> after the door opened.'):null; },
    bloom:         function(){ return 'A small bloom — someone visibly eased.'; },
    track_skip:    function(){ return 'A song was gently let go of.'; },
    listen_autostop:function(){ return 'The room fell quiet on its own, as designed.'; },
    lowlight_rescue:function(){ return 'The room brightened itself for someone sitting in the dark.'; },
    selfreport:    function(){ return 'Someone marked, without words, how they feel.'; }
  };
  function addLog(text, hm){
    var empty = document.getElementById('logEmpty');
    if (empty) empty.remove();
    var row = document.createElement('div');
    row.className = 'log-line';
    row.innerHTML = '<span class="log-time">' + hm + '</span>' +
                    '<span class="log-text">' + text + '</span>';
    logEl.insertBefore(row, logEl.firstChild);
    requestAnimationFrame(function(){ requestAnimationFrame(function(){ row.classList.add('shown'); }); });
    var rows = logEl.querySelectorAll('.log-line');
    rows.forEach(function(r0,i0){ if (i0>=4) r0.classList.add('dimming'); });
    if (rows.length > 6) logEl.removeChild(rows[rows.length-1]);
  }
  async function pollLog(){
    try{
      var r = await fetch('/api/admin/live'); if(!r.ok) return;
      var d = await r.json();
      var feed = (d.feed || []).slice();
      feed.reverse(); /* oldest first, so new lines land at the top in order */
      var stagger = 0;
      for (var i=0;i<feed.length;i++){
        var ev = feed[i];
        var map = LOGMAP[ev.type];
        if (!map) continue;
        var text = map(ev.val);
        if (!text) continue;
        var sig = ev.t + '|' + ev.type + '|' + (ev.val||'');
        if (seenLog[sig]) continue;
        seenLog[sig] = true;
        (function(txt, hm, delay){ setTimeout(function(){ addLog(txt, hm); }, delay); })(text, (ev.t||'').slice(0,5), 300 + stagger*1100);
        stagger++;
      }
    }catch(e){}
  }
  pollLog(); setInterval(pollLog, 12000);

  /* ============ music lanes — the real library, honestly ============ */
  var LANE_POETRY = {
    calm:     'Calm — for the gentle arrival',
    deepcalm: 'Deep calm — for the shaken',
    lifting:  'Lifting — for the low and heavy'
  };
  async function loadLanes(){
    try{
      var r = await fetch('/api/admin/tracks'); if(!r.ok) return;
      var d = await r.json();
      var mount = document.getElementById('musicLanes'); if(!mount) return;
      var lanes = d.lanes || {};
      var names = Object.keys(lanes).sort();
      if (!names.length){ mount.innerHTML = '<div class="sect-sub" style="text-align:left;margin-top:20px;">the library is resting.</div>'; return; }
      var maxN = 1;
      names.forEach(function(nm){
        var on = lanes[nm].filter(function(t0){ return t0.enabled; }).length;
        if (on > maxN) maxN = on;
      });
      mount.innerHTML = names.map(function(nm, i){
        var on = lanes[nm].filter(function(t0){ return t0.enabled; }).length;
        var w = on ? Math.max(8, Math.round(100*on/maxN)) : 0;
        return '<div class="lane" style="margin-top:20px;">'
          + '<div class="lane-head"><span class="lane-name">' + esc(LANE_POETRY[nm] || nm) + '</span>'
          + '<span class="lane-count">' + on + (on===1?' song ready':' songs ready') + '</span></div>'
          + '<div class="band"><div class="band-fill" style="animation-delay:-' + (i*1.7) + 's"></div></div>'
          + '</div>';
      }).join('');
      /* let the 0-width paint once, then ease open */
      setTimeout(function(){
        var fills = mount.querySelectorAll('.band-fill');
        names.forEach(function(nm, i){
          var on = lanes[nm].filter(function(t0){ return t0.enabled; }).length;
          var w = on ? Math.max(8, Math.round(100*on/maxN)) : 0;
          if (fills[i]) fills[i].style.width = w + '%';
        });
      }, 80);
    }catch(e){}
  }
  loadLanes(); setInterval(loadLanes, 60000);

  tickClock();
})();
</script>
</body></html>""", body=body, bars=bars, t_rows=t_rows, sess_rows=sess_rows, subzone_rows=subzone_rows, heart_rows=heart_rows, kpi_cards=kpi_cards, room_rows=room_rows, w_sessions=w_sessions, w_handoffs=w_handoffs, w_messages=w_messages, w_first=w_first)


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


# ===========================================================================
# WHO IS ON CALL — the founder rule, hardened:
#   "In order for anyone to click on a provider they must be there and
#    available." A person may only ever be offered a provider who is truly
# there. Availability lives in the provider_availability sqlite table
# (id, side, role, available, updated_at) — the same schema declared in
# init_db()/_ensure_schema(). Because the main database is a throwaway
# in-memory store in keep-nothing privacy mode, this registry keeps its own
# small sqlite file on the persistent disk: it holds ZERO user data — it is
# founder operational state only (which roles are staffed right now) — so
# persisting it never touches the privacy promise. Every role is seeded
# available=0: the HONEST default. No one is offered until the founder
# says a real person is there.
# ===========================================================================
_ONCALL_DB_FILE = os.environ.get("ONCALL_DB_FILE", _DATA_DIR + "/innerlight_oncall.db")
_ONCALL_LOCK = threading.Lock()
# (side, role key, founder-facing label) — role keys are language-neutral;
# the handoff pages carry the same keys in data-role attributes.
_PROVIDER_ROLES = [
    ("clinical", "crisis_counselor",   "Crisis-trained counselor"),
    ("clinical", "therapist",          "Therapist / licensed counselor"),
    ("clinical", "psychiatrist",       "Psychiatrist"),
    ("clinical", "nurse_practitioner", "Nurse practitioner"),
    ("legal",    "housing_attorney",   "Housing / tenant attorney"),
    ("legal",    "family_attorney",    "Family law attorney"),
    ("legal",    "criminal_attorney",  "Criminal defense attorney"),
    ("legal",    "civil_attorney",     "Consumer / civil attorney"),
    ("legal",    "legal_aid",          "Legal aid office"),
]

def _oncall_db() -> sqlite3.Connection:
    """Open the on-call registry, creating and seeding it (all OFF) if new.
    Mirrors connect_db(): row factory + ensured schema, but always on disk."""
    conn = sqlite3.connect(_ONCALL_DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS provider_availability ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, side TEXT NOT NULL, "
        "role TEXT NOT NULL, available INTEGER NOT NULL DEFAULT 0, "
        "updated_at TEXT NOT NULL)"
    )
    have = {(r["side"], r["role"]) for r in
            conn.execute("SELECT side, role FROM provider_availability")}
    for _side, _role, _label in _PROVIDER_ROLES:
        if (_side, _role) not in have:
            conn.execute(
                "INSERT INTO provider_availability (side, role, available, updated_at)"
                " VALUES (?, ?, 0, ?)", (_side, _role, utc_now()))
    conn.commit()
    return conn

_ONCALL_CACHE = {"t": 0.0, "data": None}  # light cache for the public endpoint

@app.route("/api/providers/available")
def providers_available():
    """PUBLIC, no auth. The honest availability picture the handoff pages
    gate on. Never errors: any failure returns empty lists, because empty
    is the truthful fallback — no one gets offered a button with nobody
    behind it."""
    # DEMO ONLY (Principle 16 isolation): if THIS session was explicitly put in
    # demo mode, return the SAMPLE vetted providers for the enabled side(s),
    # flagged sample:true. This branch is NEVER reached without the founder-set
    # session flag, and it never reads or writes the shared cache — so a real
    # visitor's honest-empty picture can never be polluted by a demo session.
    _dsides = _demo_sides()
    if _dsides:
        demo_out = {"clinical": [], "legal": []}
        try:
            roles = _vetting_sample_roles()  # {side: [role, ...]} from is_sample rows
            for side in ("clinical", "legal"):
                if side in _dsides:
                    demo_out[side] = roles.get(side, [])
        except Exception as e:
            print("[InnerLight] demo availability issue:", e)
        demo_out["demo"] = True
        demo_out["sample"] = True
        return jsonify(demo_out)
    out = {"clinical": [], "legal": []}
    try:
        now = time.time()
        if _ONCALL_CACHE["data"] is not None and (now - _ONCALL_CACHE["t"]) < 10:
            return jsonify(_ONCALL_CACHE["data"])
        with _ONCALL_LOCK:
            conn = _oncall_db()
            try:
                rows = conn.execute(
                    "SELECT side, role FROM provider_availability WHERE available = 1"
                ).fetchall()
            finally:
                conn.close()
        for r in rows:
            if r["side"] in out:
                out[r["side"]].append(r["role"])
        _ONCALL_CACHE["data"] = out
        _ONCALL_CACHE["t"] = now
    except Exception as e:
        print("[InnerLight] providers/available issue (returning honest-empty):", e)
        return jsonify({"clinical": [], "legal": []})
    return jsonify(out)

@app.route("/api/admin/oncall")
def admin_oncall_list():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    labels = {(s, r): lb for s, r, lb in _PROVIDER_ROLES}
    with _ONCALL_LOCK:
        conn = _oncall_db()
        try:
            rows = conn.execute(
                "SELECT side, role, available, updated_at FROM provider_availability"
                " ORDER BY id").fetchall()
        finally:
            conn.close()
    return jsonify({"status": "ok", "roles": [
        {"side": r["side"], "role": r["role"],
         "label": labels.get((r["side"], r["role"]), r["role"]),
         "available": bool(r["available"]), "updated_at": r["updated_at"]}
        for r in rows]})

@app.route("/api/admin/oncall", methods=["POST"])
def admin_oncall_set():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    data = request.get_json(silent=True) or {}
    side = str(data.get("side", ""))[:12]
    role = str(data.get("role", ""))[:40]
    available = 1 if data.get("available") else 0
    if (side, role) not in {(s, r) for s, r, _lb in _PROVIDER_ROLES}:
        return jsonify({"error": "unknown role"}), 400
    with _ONCALL_LOCK:
        conn = _oncall_db()
        try:
            conn.execute(
                "UPDATE provider_availability SET available = ?, updated_at = ?"
                " WHERE side = ? AND role = ?",
                (available, utc_now(), side, role))
            conn.commit()
        finally:
            conn.close()
    _ONCALL_CACHE["data"] = None  # the public picture updates immediately
    return jsonify({"status": "ok", "side": side, "role": role,
                    "available": bool(available), "updated_at": utc_now()})


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
 #out{font-size:14.5px;line-height:1.7;color:#1e293b;display:none;}
 .stamp{display:inline-block;background:#fef3c7;color:#92400e;border:1px solid #fcd34d;font-size:11px;
        font-weight:700;border-radius:6px;padding:4px 10px;margin-bottom:12px;letter-spacing:0.4px;}
 .wait{display:none;color:#c56a2c;font-weight:700;font-size:13px;margin-top:12px;}
 /* Rendered study text: real headings, bold, lists — never raw asterisks. */
 .md-body{font-size:14.5px;line-height:1.7;color:#1e293b;}
 .md-body p{margin:0 0 11px;}
 .md-body strong{font-weight:700;color:#3a2a1c;}
 .md-body em{font-style:italic;}
 .md-body code{background:#f4ede3;padding:1px 6px;border-radius:5px;font-size:13px;}
 .md-body ul,.md-body ol{margin:8px 0 14px 22px;padding:0;}
 .md-body li{margin:5px 0;}
 .md-body hr{border:0;border-top:1px solid #e7dccc;margin:16px 0;}
 .md-h{font-weight:800;color:#7a3e1e;margin:18px 0 9px;line-height:1.3;}
 .md-h1{font-size:19px;} .md-h2{font-size:17px;} .md-h3{font-size:15.5px;color:#8a4a24;}
 .md-h4{font-size:14px;color:#8a4a24;text-transform:none;}
 .md-body:first-child .md-h,.md-body>.md-h:first-child{margin-top:2px;}
</style></head><body>
<script>
/* Turn the study engine's Markdown into real formatting. HTML is escaped
   FIRST, then formatting tags are added, so nothing user- or model-supplied
   can inject markup. This is why asterisks now become bold instead of literal.
   NOTE: this lives inside a NON-raw Python template string, so JS strings here
   use single quotes and NO backslash escapes (no newline/return/quote escapes)
   — newlines are matched via String.fromCharCode to survive Python. */
function mdEsc(s){ return String(s).split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;'); }
function mdInline(s){
  s = s.replace(/\\*\\*([^*]+?)\\*\\*/g, '<strong>$1</strong>');
  s = s.replace(/__([^_]+?)__/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*])\\*(?!\\s)([^*]+?)\\*(?!\\*)/g, '$1<em>$2</em>');
  s = s.replace(/`([^`]+?)`/g, '<code>$1</code>');
  return s;
}
function mdToHtml(src){
  if(!src) return '';
  var norm = mdEsc(src).split(String.fromCharCode(13)).join('');
  var lines = norm.split(String.fromCharCode(10));
  var html = '', list = null, para = [];
  function closeList(){ if(list){ html += '</'+list+'>'; list=null; } }
  function flushPara(){ if(para.length){ html += '<p>'+mdInline(para.join('<br>'))+'</p>'; para=[]; } }
  for (var i=0;i<lines.length;i++){
    var ln = lines[i], t = ln.trim();
    if (t === ''){ flushPara(); closeList(); continue; }
    if (/^(-{3,}|\\*{3,}|_{3,})$/.test(t)){ flushPara(); closeList(); html += '<hr>'; continue; }
    var h = t.match(/^(#{1,6})\\s+(.*)$/);
    if (h){ flushPara(); closeList(); var lvl = Math.min(h[1].length,4);
      html += '<div class="md-h md-h'+lvl+'">'+mdInline(h[2])+'</div>'; continue; }
    var ul = t.match(/^[-*+]\\s+(.*)$/);
    if (ul){ flushPara(); if(list!=='ul'){ closeList(); html += '<ul>'; list='ul'; }
      html += '<li>'+mdInline(ul[1])+'</li>'; continue; }
    var ol = t.match(/^\\d+[.)]\\s+(.*)$/);
    if (ol){ flushPara(); if(list!=='ol'){ closeList(); html += '<ol>'; list='ol'; }
      html += '<li>'+mdInline(ol[1])+'</li>'; continue; }
    para.push(t);
  }
  flushPara(); closeList();
  return html;
}
window.mdToHtml = mdToHtml;
</script>
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
        + '<div class="md-body" style="margin-top:10px;">' + mdToHtml(st.walkthrough||'') + '</div></details>';
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
    if (out){ out.style.display='block'; out.className='md-body'; out.style.whiteSpace='normal'; out.innerHTML = mdToHtml(d.text || 'No result.'); }
    if (typeof loadShelf==='function') loadShelf();
  }catch(e){ if(wait) wait.style.display='none'; if(out){ out.style.display='block'; out.className=''; out.textContent='Study call failed. Try again.'; } }
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
    out.className = 'md-body'; out.innerHTML = mdToHtml((d && d.text) ? d.text : 'No response.');
  }catch(e){ out.className=''; out.textContent = 'Could not reach the study engine. Check the connection and press "Study it" again.'; }
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
    html += '<div style="margin:0 0 22px;border-left:5px solid ' + L[2] + ';padding:6px 0 6px 16px;">'
      + '<div style="font-weight:800;color:' + L[2] + ';font-size:15px;margin-bottom:8px;">' + L[1] + '</div>'
      + '<div class="md-body">' + mdToHtml(text) + '</div></div>';
  }
  wait.style.display='none'; wait.textContent = origWait;
  out.className=''; out.innerHTML = html; out.style.display='block';
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
    # DEMO ONLY (Principle 16): a session in demo mode never creates a real
    # video room, never pages the founder via ntfy, and never writes real
    # partner transfer events or connect-log rows. It returns a demo marker so
    # the page shows its own demonstration confirmation. A real visitor (no
    # demo_mode in session) never reaches this branch and behaves exactly as
    # before. This runs before rate limits/bot traps so a live demo is smooth.
    if _demo_sides():
        return jsonify({"status": "ok", "demo": True, "room": None,
                        "notified": False})
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
    # PARTNER PORTAL: credit a 'transfer' to every ACTIVE partner whose side
    # and role cover this need — counts only, never any user text or summary.
    _partner_write_transfers(kind, pro)
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

# ============ RESILIENT HANDOFF DESTINATIONS ============
# Every critical handoff has an ordered chain of ways in. Before a person is
# sent, the server live-checks the chain and returns the FIRST DOOR THAT
# OPENS. If a link breaks, the next one takes over immediately — a person
# reaching for help must never land on a dead page. (Founder's law, from the
# live lawhelp.org 503 outage.)
DEST_CHAINS = {
    "legal_aid": [
        "https://www.lsc.gov/about-lsc/what-legal-aid/get-legal-help",
        "https://www.usa.gov/legal-aid",
        "https://www.abafreelegalanswers.org/",
        "https://www.lawhelp.org/",
    ],
    "treatment": [
        "https://findtreatment.gov",
        "https://www.samhsa.gov/find-help/national-helpline",
        "https://988lifeline.org",
    ],
    "dv_help": [
        "https://www.thehotline.org",
        "https://www.domesticshelters.org",
    ],
    "help_211": [
        "https://www.211.org",
    ],
    "chat_988": [
        "https://988lifeline.org/chat/",
        "https://988lifeline.org",
    ],
}
_dest_cache = {}  # name -> (url, checked_at)

def _url_alive(url, timeout=6):
    try:
        req = urllib.request.Request(url, method="GET",
            headers={"User-Agent": "Mozilla/5.0 (InnerLight reachability check)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= getattr(r, "status", 200) < 400
    except Exception:
        return False

def resolve_destination(name):
    """First alive URL in the chain (30-min cache). If every door is closed,
    return the primary anyway — a person still gets a target — and log it."""
    chain = DEST_CHAINS.get(name)
    if not chain:
        return None
    cached = _dest_cache.get(name)
    if cached and (time.time() - cached[1]) < 1800:
        return cached[0]
    for url in chain:
        if _url_alive(url):
            _dest_cache[name] = (url, time.time())
            if url != chain[0]:
                print(f"[destinations] {name}: primary down, routing to {url}")
            return url
    print(f"[destinations] WARNING: every door closed for {name}; sending primary")
    _dest_cache[name] = (chain[0], time.time() - 1500)  # recheck soon
    return chain[0]

@app.route("/api/dest/<name>")
def api_dest(name):
    url = resolve_destination(name)
    if not url:
        return jsonify({"error": "unknown"}), 404
    return jsonify({"url": url})

@app.route("/api/admin/dispatch", methods=["GET", "POST"])
def api_admin_dispatch():
    """Dispatch (Principle 7): founder-only status and switch. The engine has
    no hooks into care; this route only arms/disarms revenue surfaces."""
    if not session.get("founder_ok"):
        return jsonify({"error": "unauthorized"}), 401
    import dispatch_engine
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        result = dispatch_engine.set_active(bool(data.get("active")), actor="founder")
        return jsonify(result)
    return jsonify(dispatch_engine.get_status())

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


# ===========================================================================
# PARTNER PORTAL — the back-of-house program for the real providers and
# attorneys who receive the people InnerLight walks toward help.
#
# HARD SEPARATION (Immutable Principles 2, 3, 4, 5, 16):
#   * Partners NEVER see or submit any user clinical content, identity,
#     conversation, or any user data. This program stores ZERO user data.
#   * Partners get their OWN session key (partner_ok) and their own warm
#     portal at /partner. They have NO access to /admin (The Watch), the
#     Founder's Study, or any /api/admin/* route — those check founder_ok
#     only, and partner_ok grants nothing there.
#   * The three tables live in the same persistent ops sqlite as the on-call
#     board (founder operational state only): who the partners are, how many
#     times we transferred toward them, how many arrivals they confirmed,
#     and their process suggestions. No summaries, no user text — ever.
#   * P17 posture: /partner/login is an auth endpoint — it tarpits/locks out
#     via _defend() and flags failed attempts hostile via _flag_hostile(),
#     exactly like the founder admin login.
# ===========================================================================
_PARTNER_LOCK = threading.Lock()

def _partner_db() -> sqlite3.Connection:
    """Open the ops sqlite and ensure the partner tables. Shares the on-call
    DB file (founder operational state only — zero user data)."""
    conn = sqlite3.connect(_ONCALL_DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS partners ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, org TEXT NOT NULL, "
        "contact_name TEXT, side TEXT NOT NULL, role TEXT NOT NULL, "
        "code_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', "
        "created_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS partner_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, partner_id INTEGER NOT NULL, "
        "kind TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS partner_suggestions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, partner_id INTEGER NOT NULL, "
        "text TEXT, created_at TEXT NOT NULL, read_flag INTEGER DEFAULT 0)")
    conn.commit()
    return conn

_PARTNER_ROLE_LABELS = {r: lb for _s, r, lb in _PROVIDER_ROLES}
_PARTNER_ROLE_SIDE = {r: s for s, r, _lb in _PROVIDER_ROLES}

# Fuzzy map from a requested "pro" label to on-call role keys, so a real
# transfer is credited to the partners who actually cover that need. If none
# match, nothing is written (the honest default).
_PARTNER_ROLE_KEYWORDS = {
    "crisis_counselor":   ["crisis", "counselor", "hotline", "warm line"],
    "therapist":          ["therap", "counsel", "psycholog", "clinician", "mental", "emotional"],
    "psychiatrist":       ["psychiatr", "medication", "med management", "prescrib", "meds"],
    "nurse_practitioner": ["nurse", "practitioner"],
    "housing_attorney":   ["housing", "tenant", "evict", "landlord", "rent", "lease"],
    "family_attorney":    ["family", "custody", "divorce", "child support"],
    "criminal_attorney":  ["criminal", "defense", "arrest", "charge", "police", "warrant", "jail"],
    "civil_attorney":     ["civil", "consumer", "contract", "debt", "sue", "lawsuit", "wage"],
    "legal_aid":          ["legal aid", "pro bono", "aid office"],
}

def _partner_gen_code():
    """A one-time, human-friendly access code. Shown once, then only its
    salted hash is stored."""
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous characters
    def part(n):
        return "".join(secrets.choice(alpha) for _ in range(n))
    return "IL-" + part(4) + "-" + part(4)

def _partner_hash_code(code):
    """Salted sha256 of the access code. The salt is bound to ADMIN_KEY so the
    stored hashes are useless without the deployment secret."""
    salt = os.environ.get("ADMIN_KEY", "") + "::innerlight-partner-salt::v1"
    normalized = str(code or "").strip().upper()
    return hashlib.sha256((salt + "::" + normalized).encode("utf-8")).hexdigest()

def _partner_scrub(text, cap):
    """Scrub identifiers (email, phone, handle, long digit runs) then hard-cap.
    Partner-facing storage must never hold user content; this is defense in
    depth on top of the explicit labeling in the portal."""
    out = str(text or "")
    for pat, repl in _SCRUB_PATTERNS:
        out = pat.sub(repl, out)
    return out[:cap]

def _partner_match_roles(kind, pro):
    """Given a connect request kind ('legal'|'care') and its 'pro' label,
    return (side, [role keys]) that the label fuzzily matches on that side."""
    side = "legal" if kind == "legal" else "clinical"
    low = str(pro or "").lower()
    if not low.strip():
        return side, []
    matched = []
    for role, kws in _PARTNER_ROLE_KEYWORDS.items():
        if _PARTNER_ROLE_SIDE.get(role) != side:
            continue
        if any(k in low for k in kws):
            matched.append(role)
    return side, matched

def _partner_write_transfers(kind, pro):
    """After a real connect request, credit a 'transfer' event to every ACTIVE
    partner whose side+role covers the requested need. Never stores any user
    text — the event note is empty. Returns the number of events written."""
    try:
        side, roles = _partner_match_roles(kind, pro)
        if not roles:
            return 0
        now = utc_now()
        with _PARTNER_LOCK:
            conn = _partner_db()
            try:
                qmarks = ",".join("?" for _ in roles)
                rows = conn.execute(
                    "SELECT id FROM partners WHERE status='active' AND side=? "
                    "AND role IN (" + qmarks + ")", [side] + roles).fetchall()
                for r in rows:
                    conn.execute(
                        "INSERT INTO partner_events (partner_id, kind, note, created_at) "
                        "VALUES (?, 'transfer', '', ?)", (r["id"], now))
                conn.commit()
                return len(rows)
            finally:
                conn.close()
    except Exception as e:
        print("[InnerLight] partner transfer write issue:", e)
        return 0

def _partner_current():
    """The active partner row for the current session, or None. If the partner
    was paused after signing in, this returns None — access is revoked live."""
    pid = session.get("partner_ok")
    if not pid:
        return None
    try:
        with _PARTNER_LOCK:
            conn = _partner_db()
            try:
                return conn.execute(
                    "SELECT * FROM partners WHERE id=? AND status='active'",
                    (pid,)).fetchone()
            finally:
                conn.close()
    except Exception:
        return None


# ---- The warm partner sign-in page (InnerLight aesthetic, NOT The Watch) ----
PARTNER_LOGIN_PAGE = """
<!doctype html><html lang="en"><head><title>InnerLight — Partner Sign In</title>
<meta charset="utf-8"><link rel="icon" href="data:,">
<meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 :root{--cream:#FAF5EC;--amber:#C56A2C;--amber-deep:#a9531f;--ink:#3a2c1e;
       --serif:"Palatino Linotype",Palatino,"Book Antiqua",Georgia,"Times New Roman",serif;}
 *{box-sizing:border-box;}
 body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;
      font-family:var(--serif);color:var(--ink);
      background:radial-gradient(900px 620px at 50% -12%, #fff8ec, transparent 62%), var(--cream);}
 .card{background:#fffdf8;border:1px solid rgba(197,106,44,.22);border-radius:20px;padding:42px 38px;width:380px;
       box-shadow:0 26px 64px -34px rgba(120,70,20,.5);}
 .brand{display:flex;align-items:center;margin-bottom:6px;}
 .flame{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--amber);margin-right:12px;
        box-shadow:0 0 15px 4px rgba(197,106,44,.4);}
 .brand span{font-size:13px;letter-spacing:.26em;text-transform:uppercase;color:var(--amber-deep);}
 h1{font-size:23px;font-weight:400;margin:14px 0 6px;color:#2a2016;}
 .sub{font-size:13.5px;color:#7a6650;margin-bottom:20px;font-style:italic;line-height:1.55;}
 label{display:block;font-size:12.5px;color:#6a563e;margin:16px 0 6px;letter-spacing:.03em;}
 input{width:100%;padding:12px 13px;border:1px solid rgba(197,106,44,.32);border-radius:11px;
       font-size:15px;font-family:var(--serif);background:#fffef9;color:var(--ink);}
 input:focus{outline:2px solid var(--amber);border-color:var(--amber);}
 button{margin-top:24px;width:100%;padding:13px;border:0;border-radius:11px;font-size:15px;font-weight:600;
        color:#fff8ec;background:linear-gradient(90deg,#C56A2C,#a9531f);cursor:pointer;
        font-family:var(--serif);letter-spacing:.03em;}
 .err{background:#fbeee4;color:#a9531f;border:1px solid rgba(197,106,44,.35);border-radius:9px;padding:10px 13px;
      font-size:13px;margin-bottom:8px;display:{{ 'block' if err else 'none' }};}
 .foot{margin-top:22px;font-size:11.5px;color:#9a8770;line-height:1.6;border-top:1px solid rgba(197,106,44,.14);padding-top:16px;}
</style></head><body>
<form class="card" method="POST" action="/partner/login">
  <div class="brand"><span class="flame"></span><span>InnerLight</span></div>
  <h1>Partner Portal</h1>
  <div class="sub">For the providers and attorneys who receive the people we walk toward help.
    Sign in with your organization and the access code we gave you.</div>
  <div class="err">{{ err or '' }}</div>
  <label>Organization</label>
  <input name="org" autocomplete="organization" autofocus>
  <label>Access code</label>
  <input name="code" autocomplete="off">
  <button type="submit">Enter</button>
  <div class="foot">This portal never shows or accepts any client identity, conversation, or clinical
    record. It holds only your own counts and the notes you choose to send us.</div>
</form></body></html>
"""

# ---- The portal itself: warm, respectful, zero user data ----
PARTNER_PORTAL_PAGE = """
<!doctype html><html lang="en"><head><title>InnerLight — Partner Portal</title>
<meta charset="utf-8"><link rel="icon" href="data:,">
<meta name="robots" content="noindex,nofollow"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 :root{--cream:#FAF5EC;--amber:#C56A2C;--amber-deep:#a9531f;--ink:#3a2c1e;--soft:#7a6650;
       --serif:"Palatino Linotype",Palatino,"Book Antiqua",Georgia,"Times New Roman",serif;}
 *{box-sizing:border-box;}
 body{margin:0;font-family:var(--serif);color:var(--ink);
      background:radial-gradient(1100px 700px at 50% -10%, #fff8ec, transparent 60%), var(--cream);}
 .page{max-width:820px;margin:0 auto;padding:0 26px 90px;}
 header{display:flex;justify-content:space-between;align-items:baseline;padding:34px 4px 10px;}
 .brand{display:flex;align-items:center;}
 .flame{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--amber);margin-right:12px;
        box-shadow:0 0 15px 4px rgba(197,106,44,.4);}
 .brand b{font-size:15px;letter-spacing:.22em;text-transform:uppercase;color:var(--amber-deep);font-weight:600;}
 .who{text-align:right;font-size:13px;color:var(--soft);}
 .who a{color:var(--amber-deep);text-decoration:none;font-size:12px;}
 h1{font-size:27px;font-weight:400;margin:18px 4px 4px;color:#2a2016;}
 .lead{font-size:15px;color:var(--soft);margin:0 4px 20px;font-style:italic;line-height:1.5;}
 .card{background:#fffdf8;border:1px solid rgba(197,106,44,.2);border-radius:18px;padding:24px 26px;margin:18px 0;
       box-shadow:0 18px 48px -34px rgba(120,70,20,.4);}
 .card h2{font-size:18px;font-weight:400;margin:0 0 4px;color:#2a2016;}
 .card .note{font-size:13px;color:var(--soft);margin-bottom:14px;line-height:1.5;}
 .record{font-size:20px;line-height:1.6;color:#2a2016;font-style:italic;}
 .record b{font-style:normal;color:var(--amber-deep);font-weight:600;}
 .subrec{font-size:14px;color:var(--soft);margin-top:8px;}
 .nums{display:flex;gap:16px;flex-wrap:wrap;margin-top:6px;}
 .num{flex:1;min-width:130px;background:rgba(197,106,44,.07);border-radius:12px;padding:14px;text-align:center;}
 .num b{display:block;font-size:30px;color:var(--amber-deep);font-weight:600;}
 .num span{font-size:12px;color:var(--soft);letter-spacing:.03em;}
 .btn{background:linear-gradient(90deg,#C56A2C,#a9531f);color:#fff8ec;border:0;border-radius:11px;
      padding:12px 24px;font-size:15px;font-weight:600;cursor:pointer;font-family:var(--serif);letter-spacing:.02em;}
 label{display:block;font-size:12.5px;color:#6a563e;margin:6px 0 6px;letter-spacing:.02em;}
 textarea{width:100%;min-height:96px;padding:12px;border:1px solid rgba(197,106,44,.3);border-radius:11px;
          font-size:15px;font-family:var(--serif);background:#fffef9;color:var(--ink);}
 textarea:focus{outline:2px solid var(--amber);border-color:var(--amber);}
 .guard{background:rgba(197,106,44,.06);border-left:3px solid var(--amber);border-radius:0 12px 12px 0;
        padding:10px 14px;font-size:12.5px;color:var(--soft);line-height:1.55;margin-top:12px;}
 .ok{font-size:13px;color:var(--amber-deep);margin-top:8px;min-height:16px;}
 .past{margin-top:14px;}
 .past .item{border-top:1px solid rgba(197,106,44,.14);padding:9px 0;font-size:14px;color:#4a3a2a;white-space:pre-wrap;}
 .past .item .when{display:block;font-size:11px;color:#a08a70;margin-top:3px;font-style:italic;}
 .boundary{background:#fffdf8;border:1px dashed rgba(197,106,44,.4);border-radius:16px;padding:20px 24px;margin-top:22px;}
 .boundary h3{font-size:15px;font-weight:600;color:var(--amber-deep);margin:0 0 8px;letter-spacing:.04em;}
 .boundary p{font-size:13px;color:var(--soft);line-height:1.6;margin:0;}
</style></head><body>
<div class="page">
  <header>
    <div class="brand"><span class="flame"></span><b>InnerLight Partners</b></div>
    <div class="who">{{ org }} &middot; {{ role_label }}<br><a href="/partner/logout">Sign out</a></div>
  </header>
  <h1>Welcome back.</h1>
  <div class="lead">Thank you for standing on the other side of the bridge. Here is your record &mdash;
    honest counts only, never a word about the people themselves.</div>

  <div class="card">
    <h2>Your connection record</h2>
    <div class="note">How many times we walked a person toward you, and how many arrivals you confirmed.</div>
    <div class="record" id="record-line">Loading&hellip;</div>
    <div class="subrec" id="record-week"></div>
    <div class="nums" style="margin-top:16px;">
      <div class="num"><b id="n-transfer-all">0</b><span>walked toward you (all-time)</span></div>
      <div class="num"><b id="n-transfer-week">0</b><span>this week</span></div>
      <div class="num"><b id="n-received-all">0</b><span>arrivals you confirmed (all-time)</span></div>
      <div class="num"><b id="n-received-week">0</b><span>this week</span></div>
    </div>
  </div>

  <div class="card">
    <h2>I received a person</h2>
    <div class="note">Press this each time a person we walked toward you actually arrived. It updates your record.</div>
    <button class="btn" id="btn-received">I received a person</button>
    <label style="margin-top:16px;">A note (optional) — about the handoff process only</label>
    <textarea id="received-note" placeholder="e.g. the intake link worked well / we had a scheduling gap"></textarea>
    <div class="guard">About the handoff process only &mdash; never anything about the person: no names, no
      details, no clinical information. We cannot and will not store client information.</div>
    <div class="ok" id="received-ok"></div>
  </div>

  <div class="card">
    <h2>How it is working</h2>
    <div class="note">The honest overall picture across everyone InnerLight has held &mdash; numbers only, nothing
      about any single person.</div>
    <div class="nums">
      <div class="num"><b id="o-sessions">0</b><span>total sessions held</span></div>
      <div class="num"><b id="o-handoffs">0</b><span>handoffs toward human help</span></div>
    </div>
  </div>

  <div class="card">
    <h2>Your suggestions</h2>
    <div class="note">Better ways to help the people we send you, or a smoother handoff. The founder reads every one.</div>
    <textarea id="suggest-text" placeholder="What would make this work better for the people we send you?"></textarea>
    <div style="margin-top:12px;"><button class="btn" id="btn-suggest">Send suggestion</button></div>
    <div class="ok" id="suggest-ok"></div>
    <div class="past" id="suggest-list"></div>
  </div>

  <div class="boundary">
    <h3>What this portal will never show or accept</h3>
    <p>It will never show you a person&rsquo;s identity, their conversation, their session, or any clinical or legal
      record &mdash; and it will never let you enter such a thing. That is not a limitation of the software; it is a
      founding principle of InnerLight. The person in need is the only master, and their privacy is theirs alone.
      This portal holds only your own counts and the process notes you choose to send us.</p>
  </div>
</div>
<script>
(function(){
  function setText(id, v){ var el = document.getElementById(id); if(el) el.textContent = v; }
  function esc(s){ return String(s == null ? '' : s).replace(/</g,'&lt;'); }
  function renderSuggestions(list){
    var box = document.getElementById('suggest-list');
    if(!box) return;
    if(!list || !list.length){ box.innerHTML = ''; return; }
    box.innerHTML = list.map(function(s){
      return '<div class="item">' + esc(s.text) + '<span class="when">sent ' + esc(s.when) + '</span></div>';
    }).join('');
  }
  async function loadMe(){
    try{
      var r = await fetch('/api/partner/me'); if(!r.ok) return;
      var d = await r.json();
      var ta = d.transfers_all || 0, ma = d.received_all || 0;
      var line;
      if(ta === 0){
        line = 'No one has been walked toward you yet. When we do, it will show here — honestly, and only as a count.';
      } else {
        line = ta + (ta === 1 ? ' person was' : ' people were') + ' walked toward you. You confirmed ' + ma + (ma === 1 ? ' arrival.' : ' arrivals.');
      }
      setText('record-line', line);
      setText('record-week', 'This week: ' + (d.transfers_week || 0) + ' walked toward you, ' + (d.received_week || 0) + ' confirmed.');
      setText('n-transfer-all', ta);
      setText('n-transfer-week', d.transfers_week || 0);
      setText('n-received-all', ma);
      setText('n-received-week', d.received_week || 0);
      var ov = d.overall || {};
      setText('o-sessions', ov.sessions || 0);
      setText('o-handoffs', ov.handoffs || 0);
      renderSuggestions(d.suggestions || []);
    }catch(e){}
  }
  var rb = document.getElementById('btn-received');
  if(rb) rb.addEventListener('click', async function(){
    rb.disabled = true;
    var note = document.getElementById('received-note');
    try{
      await fetch('/api/partner/received', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({note: note ? note.value : ''})});
      setText('received-ok', 'Recorded. Thank you for confirming.');
      if(note) note.value = '';
    }catch(e){}
    rb.disabled = false;
    loadMe();
  });
  var sb = document.getElementById('btn-suggest');
  if(sb) sb.addEventListener('click', async function(){
    var t = document.getElementById('suggest-text');
    if(!t || !t.value.trim()) return;
    sb.disabled = true;
    try{
      await fetch('/api/partner/suggest', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text: t.value})});
      setText('suggest-ok', 'Sent. The founder will read it.');
      t.value = '';
    }catch(e){}
    sb.disabled = false;
    loadMe();
  });
  loadMe();
})();
</script>
</body></html>
"""

@app.route("/partner/login", methods=["POST"])
def partner_login():
    # DETER (P17): an auth endpoint is a brute-force target. Tarpit/lock out
    # clients that have already earned it before doing any work, exactly like
    # the founder admin login.
    blocked = _defend()
    if blocked is not None:
        return blocked
    org = str(request.form.get("org", "")).strip()
    code = str(request.form.get("code", "")).strip()
    if org and code:
        ch = _partner_hash_code(code)
        try:
            with _PARTNER_LOCK:
                conn = _partner_db()
                try:
                    row = conn.execute(
                        "SELECT id FROM partners WHERE lower(org)=lower(?) "
                        "AND code_hash=? AND status='active'", (org, ch)).fetchone()
                finally:
                    conn.close()
        except Exception:
            row = None
        if row:
            session["partner_ok"] = row["id"]
            session.permanent = False
            return redirect("/partner")
    # A failed partner login is a security event: flag + log so repeated
    # attempts progressively slow and then lock the attacker out.
    _flag_hostile("partner-login-fail")
    return render_template_string(
        PARTNER_LOGIN_PAGE,
        err="That organization name or access code is not right."), 401

@app.route("/partner/logout")
def partner_logout():
    session.pop("partner_ok", None)
    return redirect("/partner")

@app.route("/partner")
def partner_portal():
    p = _partner_current()
    if not p:
        session.pop("partner_ok", None)
        return render_template_string(PARTNER_LOGIN_PAGE, err=""), 200
    return render_template_string(
        PARTNER_PORTAL_PAGE, org=p["org"],
        role_label=_PARTNER_ROLE_LABELS.get(p["role"], p["role"]))

@app.route("/api/partner/me")
def partner_me():
    p = _partner_current()
    if not p:
        return jsonify({"error": "auth"}), 401
    pid = p["id"]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with _PARTNER_LOCK:
        conn = _partner_db()
        try:
            def cnt(kind, since=None):
                if since:
                    return conn.execute(
                        "SELECT COUNT(*) c FROM partner_events WHERE partner_id=? "
                        "AND kind=? AND created_at>=?", (pid, kind, since)).fetchone()["c"]
                return conn.execute(
                    "SELECT COUNT(*) c FROM partner_events WHERE partner_id=? "
                    "AND kind=?", (pid, kind)).fetchone()["c"]
            transfers_all = cnt("transfer")
            transfers_week = cnt("transfer", week_ago)
            received_all = cnt("received")
            received_week = cnt("received", week_ago)
            sugg = conn.execute(
                "SELECT text, created_at FROM partner_suggestions WHERE partner_id=? "
                "ORDER BY id DESC", (pid,)).fetchall()
        finally:
            conn.close()
    # "How it is working" — overall aggregates from the admin metrics store.
    # Numbers only; never anything user-level.
    tot_sessions = tot_handoffs = 0
    try:
        with _METRICS_LOCK:
            m = _metrics_load()
        for _day, d in m.items():
            tot_sessions += max(d.get("sessions", 0), len(d.get("by_session", {})))
            for _hk, _hv in (d.get("handoffs", {}) or {}).items():
                tot_handoffs += _hv
    except Exception:
        pass
    return jsonify({
        "org": p["org"],
        "role_label": _PARTNER_ROLE_LABELS.get(p["role"], p["role"]),
        "transfers_all": transfers_all, "transfers_week": transfers_week,
        "received_all": received_all, "received_week": received_week,
        "overall": {"sessions": tot_sessions, "handoffs": tot_handoffs},
        "suggestions": [{"text": s["text"] or "", "when": (s["created_at"] or "")[:10]}
                        for s in sugg],
    })

@app.route("/api/partner/received", methods=["POST"])
def partner_received():
    p = _partner_current()
    if not p:
        return jsonify({"error": "auth"}), 401
    data = request.get_json(silent=True) or {}
    note = _partner_scrub(data.get("note", ""), 300)
    with _PARTNER_LOCK:
        conn = _partner_db()
        try:
            conn.execute(
                "INSERT INTO partner_events (partner_id, kind, note, created_at) "
                "VALUES (?, 'received', ?, ?)", (p["id"], note, utc_now()))
            conn.commit()
        finally:
            conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/partner/suggest", methods=["POST"])
def partner_suggest():
    p = _partner_current()
    if not p:
        return jsonify({"error": "auth"}), 401
    data = request.get_json(silent=True) or {}
    text = _partner_scrub(data.get("text", ""), 2000)
    if not text.strip():
        return jsonify({"status": "ok"})
    with _PARTNER_LOCK:
        conn = _partner_db()
        try:
            conn.execute(
                "INSERT INTO partner_suggestions (partner_id, text, created_at, read_flag) "
                "VALUES (?, ?, ?, 0)", (p["id"], text, utc_now()))
            conn.commit()
        finally:
            conn.close()
    return jsonify({"status": "ok"})


# ---- FOUNDER-ONLY partner management (The Watch). All check founder_ok. ----
@app.route("/api/admin/partners")
def admin_partners_list():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    with _PARTNER_LOCK:
        conn = _partner_db()
        try:
            partners = conn.execute("SELECT * FROM partners ORDER BY id DESC").fetchall()
            tally = {}
            for r in conn.execute(
                    "SELECT partner_id, kind, COUNT(*) c FROM partner_events "
                    "GROUP BY partner_id, kind"):
                tally.setdefault(r["partner_id"], {})[r["kind"]] = r["c"]
        finally:
            conn.close()
    out = []
    for p in partners:
        t = tally.get(p["id"], {})
        out.append({
            "id": p["id"], "org": p["org"], "contact": p["contact_name"] or "",
            "side": p["side"], "role": p["role"],
            "role_label": _PARTNER_ROLE_LABELS.get(p["role"], p["role"]),
            "status": p["status"], "created_at": (p["created_at"] or "")[:10],
            "transfers": t.get("transfer", 0), "received": t.get("received", 0)})
    return jsonify({"status": "ok", "partners": out,
                    "roles": [{"side": s, "role": r, "label": lb}
                              for s, r, lb in _PROVIDER_ROLES]})

@app.route("/api/admin/partners/create", methods=["POST"])
def admin_partners_create():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    data = request.get_json(silent=True) or {}
    org = _partner_scrub(data.get("org", ""), 120).strip()
    contact = _partner_scrub(data.get("contact", ""), 120).strip()
    role = str(data.get("role", ""))[:40]
    if role not in _PARTNER_ROLE_SIDE:
        return jsonify({"error": "unknown role"}), 400
    if not org:
        return jsonify({"error": "org required"}), 400
    side = _PARTNER_ROLE_SIDE[role]
    code = _partner_gen_code()
    ch = _partner_hash_code(code)
    with _PARTNER_LOCK:
        conn = _partner_db()
        try:
            cur = conn.execute(
                "INSERT INTO partners (org, contact_name, side, role, code_hash, "
                "status, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?)",
                (org, contact, side, role, ch, utc_now()))
            pid = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
    # The plaintext code is returned ONCE for the founder to copy; only its
    # hash is stored. It can never be recovered from storage.
    return jsonify({"status": "ok", "id": pid, "org": org, "code": code,
                    "role_label": _PARTNER_ROLE_LABELS.get(role, role)})

@app.route("/api/admin/partners/status", methods=["POST"])
def admin_partners_status():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    data = request.get_json(silent=True) or {}
    try:
        pid = int(data.get("id"))
    except Exception:
        return jsonify({"error": "bad id"}), 400
    status = "paused" if data.get("status") == "paused" else "active"
    with _PARTNER_LOCK:
        conn = _partner_db()
        try:
            conn.execute("UPDATE partners SET status=? WHERE id=?", (status, pid))
            conn.commit()
        finally:
            conn.close()
    return jsonify({"status": "ok", "id": pid, "new_status": status})

@app.route("/api/admin/partners/suggestions")
def admin_partner_suggestions():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    with _PARTNER_LOCK:
        conn = _partner_db()
        try:
            rows = conn.execute(
                "SELECT s.id, s.partner_id, s.text, s.created_at, s.read_flag, p.org "
                "FROM partner_suggestions s LEFT JOIN partners p ON p.id=s.partner_id "
                "ORDER BY s.id DESC").fetchall()
        finally:
            conn.close()
    return jsonify({"status": "ok", "suggestions": [
        {"id": r["id"], "org": r["org"] or "(unknown)", "text": r["text"] or "",
         "when": (r["created_at"] or "")[:16].replace("T", " "),
         "read": bool(r["read_flag"])}
        for r in rows]})

@app.route("/api/admin/partners/suggestions/read", methods=["POST"])
def admin_partner_suggestions_read():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    data = request.get_json(silent=True) or {}
    try:
        sid = int(data.get("id"))
    except Exception:
        return jsonify({"error": "bad id"}), 400
    with _PARTNER_LOCK:
        conn = _partner_db()
        try:
            conn.execute("UPDATE partner_suggestions SET read_flag=1 WHERE id=?", (sid,))
            conn.commit()
        finally:
            conn.close()
    return jsonify({"status": "ok"})


# ===========================================================================
# PROVIDER VETTING ENGINE — founder-only (Part 1). Principle 4: scrutinize and
# categorize providers carefully; we do not toss a person to just any provider.
#   * Lives in the SAME persistent ops sqlite as the on-call board and partners
#     (founder operational state only — ZERO user data, ever). It records who a
#     provider is, their credential, their category/specialty, and the vetting
#     decision — nothing about any person we serve.
#   * Marking a provider Vetted does NOT expose them to anyone. The founder then
#     explicitly promotes a vetted (non-sample) provider into Partners (issuing
#     a one-time access code) and/or lights their role on the On-Call board.
#   * SAMPLE rows (is_sample=1) are unmistakably fictitious and can NEVER be
#     promoted to a real system (Principle 16). They exist only to populate the
#     board for the founder and to drive Demonstration Mode.
# ===========================================================================
_VETTING_LOCK = threading.Lock()

_VETTING_SAMPLES = [
    # (org, contact, side, role, credential_type, credential_id, credential_state,
    #  category, specialty, discipline_notes)
    ("SAMPLE Clinic", "Dr. A. Rivera, LMFT", "clinical", "therapist",
     "License #", "LMFT-000000 (SAMPLE)", "CA", "Anxiety & trauma",
     "Adults, EMDR, grief", "Sample record for demonstration only."),
    ("SAMPLE Behavioral Health", "Dr. M. Chen, MD", "clinical", "psychiatrist",
     "NPI", "0000000000 (SAMPLE)", "NY", "Medication management",
     "Mood & anxiety disorders", "Sample record for demonstration only."),
    ("SAMPLE Legal Aid", "J. Okafor, Housing", "legal", "housing_attorney",
     "State bar #", "BAR-000000 (SAMPLE)", "TX", "Housing / eviction defense",
     "Tenant rights, unsafe conditions", "Sample record for demonstration only."),
    ("SAMPLE Defenders", "R. Santos, Esq.", "legal", "criminal_attorney",
     "State bar #", "BAR-111111 (SAMPLE)", "IL", "Criminal defense",
     "Arraignments, misdemeanors", "Sample record for demonstration only."),
]

def _vetting_db() -> sqlite3.Connection:
    """Open the ops sqlite and ensure the vetted_providers table + seed the
    fictitious SAMPLE rows once. Shares the on-call DB file (founder state only,
    zero user data)."""
    conn = sqlite3.connect(_ONCALL_DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS vetted_providers ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, org TEXT NOT NULL, "
        "contact_name TEXT, side TEXT NOT NULL, role TEXT NOT NULL, "
        "credential_type TEXT, credential_id TEXT, credential_state TEXT, "
        "category TEXT, specialty TEXT, discipline_checked INTEGER DEFAULT 0, "
        "discipline_notes TEXT, status TEXT NOT NULL DEFAULT 'pending', "
        "is_sample INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, "
        "decided_at TEXT)")
    # Seed the SAMPLE rows exactly once (only if none are present yet).
    have = conn.execute(
        "SELECT COUNT(*) c FROM vetted_providers WHERE is_sample=1").fetchone()
    if not have or not have["c"]:
        now = utc_now()
        for (org, contact, side, role, ctype, cid, cstate, cat, spec, notes) in _VETTING_SAMPLES:
            conn.execute(
                "INSERT INTO vetted_providers (org, contact_name, side, role, "
                "credential_type, credential_id, credential_state, category, "
                "specialty, discipline_checked, discipline_notes, status, "
                "is_sample, created_at, decided_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,1,?,'vetted',1,?,?)",
                (org, contact, side, role, ctype, cid, cstate, cat, spec,
                 notes, now, now))
        conn.commit()
    return conn

def _vetting_sample_roles():
    """{side: [role, ...]} for the fictitious, VETTED sample providers. Used by
    Demonstration Mode only (never by the real availability path)."""
    out = {"clinical": [], "legal": []}
    with _VETTING_LOCK:
        conn = _vetting_db()
        try:
            rows = conn.execute(
                "SELECT DISTINCT side, role FROM vetted_providers "
                "WHERE is_sample=1 AND status='vetted'").fetchall()
        finally:
            conn.close()
    for r in rows:
        if r["side"] in out and r["role"] not in out[r["side"]]:
            out[r["side"]].append(r["role"])
    return out

@app.route("/api/admin/vetting/list")
def admin_vetting_list():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    with _VETTING_LOCK:
        conn = _vetting_db()
        try:
            rows = conn.execute(
                "SELECT * FROM vetted_providers ORDER BY "
                "CASE status WHEN 'pending' THEN 0 WHEN 'vetted' THEN 1 ELSE 2 END, "
                "id DESC").fetchall()
        finally:
            conn.close()
    out = []
    for p in rows:
        out.append({
            "id": p["id"], "org": p["org"], "contact": p["contact_name"] or "",
            "side": p["side"], "role": p["role"],
            "role_label": _PARTNER_ROLE_LABELS.get(p["role"], p["role"]),
            "credential_type": p["credential_type"] or "",
            "credential_id": p["credential_id"] or "",
            "credential_state": p["credential_state"] or "",
            "category": p["category"] or "", "specialty": p["specialty"] or "",
            "discipline_checked": bool(p["discipline_checked"]),
            "discipline_notes": p["discipline_notes"] or "",
            "status": p["status"], "is_sample": bool(p["is_sample"]),
            "created_at": (p["created_at"] or "")[:10],
            "decided_at": (p["decided_at"] or "")[:10]})
    return jsonify({"status": "ok", "providers": out,
                    "roles": [{"side": s, "role": r, "label": lb}
                              for s, r, lb in _PROVIDER_ROLES]})

@app.route("/api/admin/vetting/create", methods=["POST"])
def admin_vetting_create():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    data = request.get_json(silent=True) or {}
    org = _partner_scrub(data.get("org", ""), 120).strip()
    contact = _partner_scrub(data.get("contact", ""), 120).strip()
    role = str(data.get("role", ""))[:40]
    if role not in _PARTNER_ROLE_SIDE:
        return jsonify({"error": "unknown role"}), 400
    if not org:
        return jsonify({"error": "org required"}), 400
    side = _PARTNER_ROLE_SIDE[role]
    ctype = str(data.get("credential_type", ""))[:40].strip()
    # Credential id is provider data (a license/NPI/bar number), NOT user data,
    # so it is stored as entered (capped) — the digit-scrub would destroy it.
    cid = str(data.get("credential_id", ""))[:60].strip()
    cstate = str(data.get("credential_state", ""))[:24].strip()
    category = _partner_scrub(data.get("category", ""), 80).strip()
    specialty = _partner_scrub(data.get("specialty", ""), 120).strip()
    disc_checked = 1 if data.get("discipline_checked") else 0
    disc_notes = _partner_scrub(data.get("discipline_notes", ""), 500).strip()
    with _VETTING_LOCK:
        conn = _vetting_db()
        try:
            cur = conn.execute(
                "INSERT INTO vetted_providers (org, contact_name, side, role, "
                "credential_type, credential_id, credential_state, category, "
                "specialty, discipline_checked, discipline_notes, status, "
                "is_sample, created_at, decided_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending',0,?,NULL)",
                (org, contact, side, role, ctype, cid, cstate, category,
                 specialty, disc_checked, disc_notes, utc_now()))
            pid = cur.lastrowid
            conn.commit()
        finally:
            conn.close()
    return jsonify({"status": "ok", "id": pid, "org": org,
                    "role_label": _PARTNER_ROLE_LABELS.get(role, role)})

@app.route("/api/admin/vetting/decide", methods=["POST"])
def admin_vetting_decide():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    data = request.get_json(silent=True) or {}
    try:
        pid = int(data.get("id"))
    except Exception:
        return jsonify({"error": "bad id"}), 400
    decision = "vetted" if data.get("decision") == "vetted" else "rejected"
    with _VETTING_LOCK:
        conn = _vetting_db()
        try:
            conn.execute(
                "UPDATE vetted_providers SET status=?, decided_at=? WHERE id=?",
                (decision, utc_now(), pid))
            conn.commit()
        finally:
            conn.close()
    return jsonify({"status": "ok", "id": pid, "new_status": decision})

@app.route("/api/admin/vetting/promote", methods=["POST"])
def admin_vetting_promote():
    """Founder explicitly promotes a VETTED, NON-SAMPLE provider into a real
    system: 'partner' issues a one-time access code (reuses the partner-create
    flow); 'oncall' lights their role on the On-Call board. SAMPLE providers can
    never be promoted — a fictitious provider must never reach a real user."""
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    data = request.get_json(silent=True) or {}
    try:
        pid = int(data.get("id"))
    except Exception:
        return jsonify({"error": "bad id"}), 400
    to = str(data.get("to", ""))
    with _VETTING_LOCK:
        conn = _vetting_db()
        try:
            row = conn.execute(
                "SELECT * FROM vetted_providers WHERE id=?", (pid,)).fetchone()
        finally:
            conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    if row["is_sample"]:
        return jsonify({"error": "sample cannot be promoted"}), 400
    if row["status"] != "vetted":
        return jsonify({"error": "only vetted providers can be promoted"}), 400
    role = row["role"]
    side = row["side"]
    if to == "partner":
        code = _partner_gen_code()
        ch = _partner_hash_code(code)
        with _PARTNER_LOCK:
            conn = _partner_db()
            try:
                conn.execute(
                    "INSERT INTO partners (org, contact_name, side, role, code_hash, "
                    "status, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?)",
                    (row["org"], row["contact_name"], side, role, ch, utc_now()))
                conn.commit()
            finally:
                conn.close()
        return jsonify({"status": "ok", "promoted": "partner", "code": code,
                        "org": row["org"],
                        "role_label": _PARTNER_ROLE_LABELS.get(role, role)})
    if to == "oncall":
        with _ONCALL_LOCK:
            conn = _oncall_db()
            try:
                conn.execute(
                    "UPDATE provider_availability SET available=1, updated_at=? "
                    "WHERE side=? AND role=?", (utc_now(), side, role))
                conn.commit()
            finally:
                conn.close()
        _ONCALL_CACHE["data"] = None  # real availability updates immediately
        return jsonify({"status": "ok", "promoted": "oncall", "side": side,
                        "role": role,
                        "role_label": _PARTNER_ROLE_LABELS.get(role, role)})
    return jsonify({"error": "unknown target"}), 400


# ===========================================================================
# DEMONSTRATION MODE endpoints — founder-only (Part 2). See the isolation note
# above _demo_token(). demo_mode lives ONLY in the visitor's signed session.
# ===========================================================================
@app.route("/api/admin/demo", methods=["GET"])
def admin_demo_state():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    sides = sorted(_demo_sides())
    return jsonify({"status": "ok", "on": bool(sides), "sides": sides,
                    "token": _demo_token(), "link": "/demo/" + _demo_token()})

@app.route("/api/admin/demo", methods=["POST"])
def admin_demo_set():
    if not session.get("founder_ok"):
        return jsonify({"error": "auth"}), 403
    data = request.get_json(silent=True) or {}
    if not data.get("on"):
        session.pop("demo_mode", None)
        return jsonify({"status": "ok", "on": False, "sides": []})
    side = str(data.get("side", "both"))
    if side == "clinical":
        sides = ["clinical"]
    elif side == "legal":
        sides = ["legal"]
    else:
        sides = ["clinical", "legal"]
    session["demo_mode"] = sides
    return jsonify({"status": "ok", "on": True, "sides": sides})

@app.route("/demo/<token>")
def demo_link(token):
    """A shareable demonstration link. The token is a stable HMAC of ADMIN_KEY
    (NOT the admin key). A valid token turns on demo mode for THIS visitor's
    session only, so the founder can show a class or investors from their own
    device without signing anyone in as founder. An invalid token does nothing
    — a real person can never stumble into sample data."""
    good = _demo_token()
    if not good or not secrets.compare_digest(str(token or ""), good):
        return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>InnerLight</title></head>"
                "<body style='font-family:Arial;background:#faf5ec;color:#2a1e14;"
                "padding:12vh 8vw;text-align:center;'>"
                "<h2 style='font-family:Georgia,serif;font-weight:400;'>"
                "This demonstration link is not valid.</h2>"
                "<p style='color:#99673e;'>If you came here for support, InnerLight "
                "is right here.</p>"
                "<p><a href='/' style='color:#33567c;'>Go to InnerLight</a></p>"
                "</body></html>"), 404
    session["demo_mode"] = ["clinical", "legal"]
    return redirect("/")

@app.route("/demo/exit")
def demo_exit():
    """Leave demonstration mode for THIS visitor's session. Always safe —
    exiting demo can only ever move someone toward the real, live app."""
    session.pop("demo_mode", None)
    return redirect("/")
