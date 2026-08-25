#!/usr/bin/env python3
"""Language parity guard — AND the founder's internal translation law:
EVERY page must be properly translated in EVERY language. Not a public
principle; a build requirement. The page-coverage check below reports every
missing page x language; once core/i18n_pages/COMPLETE exists, any missing
baked page FAILS the build permanently.

Original guard: every per-language dictionary in the app must carry
EVERY language, with the same key count as its reference language. A feature
that ships a private dictionary missing any language fails the build — this
class of gap (found by the founder, twice) is now mechanically impossible."""
import io, re, sys

SRC = "core/axiom_harmony_unified_app.py"
LANGS = ["es", "zh", "hi", "pa", "bn", "tl", "to", "sw", "am", "ha", "ru"]
DICTS = [
    ("var I18N = {", False),          # en lives as inline HTML defaults
    ("var GATE_GREETINGS = {", True),
    ("var _IL_CT = {", True),
    ("var _IL_AN = {", True),
    ("var _IL_UX = {", True),
    ("var _IL_HO = {", False),        # en passes through untranslated
]

def blocks(src, start_marker):
    i = src.find(start_marker)
    if i < 0:
        return None
    i = src.find("{", i)
    depth = 0; j = i
    in_s = None; esc = False
    langs = {}
    cur_lang = None; cur_start = None
    while j < len(src):
        ch = src[j]
        if in_s:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == in_s: in_s = None
        else:
            if ch in "'\"": in_s = ch
            elif ch == "{":
                depth += 1
                if depth == 2:
                    m = re.search(r'([A-Za-z]{2}):\s*$', src[max(i, j-8):j].rstrip() and src[max(i, j-8):j] or "")
                    mm = re.search(r'([A-Za-z]{2})\s*:\s*\{$', src[max(i, j-12):j+1])
                    cur_lang = mm.group(1) if mm else None
                    cur_start = j
            elif ch == "}":
                if depth == 2 and cur_lang:
                    langs[cur_lang] = src[cur_start:j+1]
                    cur_lang = None
                depth -= 1
                if depth == 0:
                    break
        j += 1
    return langs

def key_count(block):
    # count top-level colons inside the lang block (depth 1), skipping strings
    depth = 0; in_s = None; esc = False; cnt = 0
    for ch in block:
        if in_s:
            if esc: esc = False
            elif ch == "\\": esc = True
            elif ch == in_s: in_s = None
            continue
        if ch in "'\"": in_s = ch
        elif ch in "{[": depth += 1
        elif ch in "}]": depth -= 1
        elif ch == ":" and depth == 1: cnt += 1
    return cnt

def main():
    src = io.open(SRC, encoding="utf-8").read()
    failures = []
    for marker, has_en in DICTS:
        got = blocks(src, marker)
        if got is None:
            failures.append("%s: dictionary not found" % marker)
            continue
        want = (["en"] if has_en else []) + LANGS
        missing = [lg for lg in want if lg not in got]
        if missing:
            failures.append("%s: MISSING languages %s" % (marker, missing))
            continue
        ref = "en" if has_en else max(LANGS, key=lambda l: key_count(got[l]))
        ref_n = key_count(got[ref])
        for lg in want:
            n = key_count(got[lg])
            if n != ref_n:
                failures.append("%s: %s has %d keys, %s has %d" % (marker, lg, n, ref, ref_n))
    if failures:
        print("LANGUAGE PARITY FAILURES:")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("language parity: every dictionary carries every language (%d dicts x %d languages)" % (len(DICTS), len(LANGS)))

def info_surfaces():
    """No half-added languages: the info-page picker and the info chrome must
    carry EVERY language. A language reachable on the landing page but absent
    from any other surface fails the build."""
    src = io.open(SRC, encoding="utf-8").read()
    fails = []
    for lg in LANGS:
        if ('?lang=%s"' % lg) not in src:
            fails.append("info-page picker missing ?lang=%s" % lg)
        if ('"%s": {"back"' % lg) not in src:
            fails.append("_INFO_CHROME missing %s" % lg)
    if fails:
        print("INFO-PAGE LANGUAGE FAILURES:")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("info-page surfaces: picker + chrome carry all %d languages" % len(LANGS))

def page_coverage():
    import os
    pages = ("about", "how-it-works", "stories", "resources", "research",
             "safety", "privacy", "updates", "contact", "faq", "terms")
    baked_dir = os.path.join(os.path.dirname(SRC), "i18n_pages")
    strict = os.path.exists(os.path.join(baked_dir, "COMPLETE"))
    missing = []
    for lg in LANGS:
        for pg in pages:
            if not os.path.exists(os.path.join(baked_dir, "%s_%s.json" % (lg, pg))):
                missing.append("%s/%s" % (lg, pg))
    total = len(LANGS) * len(pages)
    print("page translation coverage: %d/%d baked" % (total - len(missing), total))
    if missing:
        print("  MISSING (founder's law: every page, every language):")
        for m in missing[:40]:
            print("   -", m)
        if len(missing) > 40:
            print("   ... and %d more" % (len(missing) - 40))
        if strict:
            print("STRICT MODE (COMPLETE marker present): build FAILED")
            sys.exit(1)
        print("  (bootstrap mode: run tools/bake_page_i18n.py with the API key, then create core/i18n_pages/COMPLETE)")

if __name__ == "__main__":
    main()
    info_surfaces()
    page_coverage()
