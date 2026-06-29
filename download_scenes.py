"""
Scene Downloader for InnerLight.

Downloads real, free-to-use moving footage from Pexels into the app's
/scenes/ folder so the backgrounds are REAL video with genuine motion
(a drone gliding over a city, waves rolling, clouds drifting) — not still
photos. Realism and motion keep a waiting person engaged.

All Pexels content is under the Pexels License: free to use, including
commercially, with no attribution required.  https://www.pexels.com/license/

HOW TO USE
----------
1. Get a free Pexels API key (takes 1 minute): https://www.pexels.com/api/
   Click "Get Started", sign in, copy your key.
2. Put the key in the line below, or set it as an environment variable:
       Windows:  setx PEXELS_API_KEY "your-key-here"
       Mac:      export PEXELS_API_KEY="your-key-here"
3. Run:  python download_scenes.py

The script SEARCHES Pexels live for the best calming clip for each scene,
so the links never go stale. If anything fails, the app falls back to its
built-in gentle animation, so the experience never breaks.
"""

from __future__ import annotations
import os, sys, json, urllib.request, urllib.parse
from pathlib import Path

SCENES_DIR = Path(__file__).resolve().parent / "scenes"

# Paste your Pexels key here if you don't want to use an environment variable:
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "").strip() or "PASTE_YOUR_PEXELS_KEY_HERE"

# Each scene: a search query for calming MOTION footage. The first good
# landscape HD clip found is downloaded. City uses aerial/drone motion.
SCENE_QUERIES = {
    "meadow": "calm green meadow grass wind",
    "clouds": "time lapse clouds sky drifting",
    "ocean":  "calm ocean waves gentle",
    "rain":   "gentle rain window calm",
    "stars":  "night sky stars time lapse",
    "city":   "aerial drone city skyline flying",   # the motion you described
    "forest": "sunlight forest trees gentle",
    "candle": "candle flame flickering dark",
}

def search_pexels(query):
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode({
        "query": query, "orientation": "landscape", "size": "medium", "per_page": 5})
    req = urllib.request.Request(url, headers={"Authorization": PEXELS_API_KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    # pick the best HD-ish mp4 file from the first result that has one
    for vid in data.get("videos", []):
        files = sorted(vid.get("video_files", []),
                       key=lambda f: (f.get("width") or 0), reverse=True)
        for f in files:
            w = f.get("width") or 0
            if f.get("file_type") == "video/mp4" and 1200 <= w <= 2200:
                return f["link"]
        if files:  # fallback to whatever mp4 exists
            for f in files:
                if f.get("file_type") == "video/mp4":
                    return f["link"]
    return None

def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "InnerLight/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as out:
        out.write(r.read())

def main():
    if PEXELS_API_KEY == "PASTE_YOUR_PEXELS_KEY_HERE":
        print("\n  You need a free Pexels API key first.")
        print("  1. Go to https://www.pexels.com/api/ and click Get Started")
        print("  2. Copy your key")
        print("  3. Either paste it into download_scenes.py (PEXELS_API_KEY line),")
        print('     or run:  setx PEXELS_API_KEY "your-key"   (Windows)')
        print("  Then run this script again.\n")
        sys.exit(1)

    SCENES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Saving moving scenes into: {SCENES_DIR}\n")
    ok = 0
    for name, query in SCENE_QUERIES.items():
        dest = SCENES_DIR / f"{name}.mp4"
        try:
            print(f"  {name}: searching Pexels for '{query}'...")
            link = search_pexels(query)
            if not link:
                print(f"     no clip found, skipping (app will animate this one)")
                continue
            print(f"     downloading...")
            download(link, dest)
            size = dest.stat().st_size // 1024
            print(f"     saved {name}.mp4 ({size} KB)")
            ok += 1
        except Exception as e:
            print(f"     failed ({e}) — app will animate this scene instead")
    print(f"\nDone. {ok} moving scenes downloaded. Start the app to see them.")

if __name__ == "__main__":
    main()
