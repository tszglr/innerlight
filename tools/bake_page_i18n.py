#!/usr/bin/env python3
"""Bake every info page into every language, into the repo — the founder's
translation law made physical. Requires ANTHROPIC_API_KEY. Writes
core/i18n_pages/{lang}_{page}.json ({"html": ...}); when all are present,
create core/i18n_pages/COMPLETE to arm strict gate mode. Baked pages are
loaded by the server ahead of any runtime self-translation, so no visitor
ever sees English in another language's chair — and deploys cannot erase
what is committed."""
import io, json, os, re, sys
sys.path.insert(0, "core")
import axiom_harmony_unified_app as app_mod
import comprehension_engine as ce

PAGES = {"about": "/about", "how-it-works": "/how-it-works", "stories": "/stories",
         "resources": "/resources", "research": "/research", "safety": "/safety",
         "privacy": "/privacy", "updates": "/updates", "contact": "/contact",
         "faq": "/faq", "terms": "/terms"}
LANGS = ["es", "zh", "hi", "pa", "bn", "tl", "to", "sw", "am", "ha", "ru"]
OUT = os.path.join("core", "i18n_pages")

def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY required to bake"); sys.exit(2)
    os.makedirs(OUT, exist_ok=True)
    c = app_mod.app.test_client()
    done = missing = 0
    for key, path in PAGES.items():
        page = c.get(path).get_data(as_text=True)
        for lg in LANGS:
            fp = os.path.join(OUT, "%s_%s.json" % (lg, key))
            if os.path.exists(fp):
                done += 1; continue
            out = ce.translate_html_chunked_verified(page, lg)
            if out:
                with io.open(fp, "w", encoding="utf-8") as f:
                    json.dump({"html": out}, f, ensure_ascii=False)
                done += 1
                print("baked", lg, key)
            else:
                missing += 1
                print("FAILED", lg, key, "- retry this pair")
    print("baked %d; failed %d" % (done, missing))
    if missing == 0:
        print("All present. Create the strict marker with: touch core/i18n_pages/COMPLETE")

if __name__ == "__main__":
    main()
