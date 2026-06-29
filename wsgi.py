"""
WSGI entry point for hosting InnerLight on Render (or any app host).

Render starts the app with gunicorn, which looks for an object called `app`.
This file makes the core Flask app importable from the project root and
ensures the database is initialized on startup.

Start command on Render:
    gunicorn wsgi:app

Privacy: KEEP_NOTHING mode stays ON by default (set in the app), so nothing
is written to disk unless AHP_KEEP_DATA=1 is explicitly set.
"""

import os
import sys
from pathlib import Path

# Make the /core modules importable
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))

from axiom_harmony_unified_app import app, init_db  # noqa: E402

# Initialize (in keep-nothing mode this is an in-memory throwaway schema)
init_db()

# gunicorn imports `app` from this module.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
