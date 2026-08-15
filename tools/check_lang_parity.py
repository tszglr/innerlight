#!/usr/bin/env python3
"""Language parity guard: every per-language dictionary in the app must carry
EVERY language, with the same key count as its reference language. A feature
that ships a private dictionary missing any language fails the build — this
class of gap (found by the founder, twice) is now mechanically impossible."""
import io, re, sys

SRC = "core/axiom_harmony_unified_app.py"
LANGS = ["es", "zh", "hi", "pa", "bn", "tl", "to", "sw", "am", "ha"]
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

if __name__ == "__main__":
    main()
