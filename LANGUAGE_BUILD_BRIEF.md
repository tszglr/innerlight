# InnerLight — Add 5 Languages (Hindi, Punjabi, Bengali, Tagalog, Tongan)

Goal: make **hi, pa, bn, tl, to** behave IDENTICALLY to the existing es/zh — every
string, every page, the footer links, the handoff, the spoken voice — not partial
additions. Codes to use everywhere: `hi` `pa` `bn` `tl` `to`.

All line numbers are for `core/axiom_harmony_unified_app.py` as delivered (they will
drift as you edit — search the anchors given).

## A. The footer-link fix is ALREADY DONE in this file
The gate footer links (lines ~845–855) already carry `data-i18n="glink.about"` …
`glink.contact`, and the en/es/zh `glink.*` keys exist in the I18N dict. You only
need to ADD the `glink.*` keys for the 5 new languages (see B). Nothing to redo.

## B. Gate string dictionary — `var I18N = {` (~line 866, closes ~919)
Contains `es:` and `zh:` blocks. Add five sibling blocks `hi:`, `pa:`, `bn:`, `tl:`,
`to:` with EVERY key the es block has:
gate.tagline, gate.begin, gate.startnote, gate.camera, gate.ainotice, gate.adult,
story.title, story.sub, story.resume, story.ainote, story.safetylink,
story.placeholder, story.send, story.speak, music.now, music.change, music.pulseon,
music.voiceoff, rail.provider, rail.legal, rail.nearby, rail.activities, rail.save,
rail.testmic, glink.about, glink.how, glink.stories, glink.resources, glink.research,
glink.safety, glink.privacy, glink.updates, glink.contact.
(Use HTML entities for non-ASCII where the es/zh blocks do; native scripts are fine
as UTF-8 too — this file is UTF-8.)

## C. Gate language switcher links (~lines 822–827)
After the `data-langbtn="zh"` link, add five `<a … onclick="setLang('hi')…"
data-langbtn="hi">हिन्दी</a>` links (and pa ਪੰਜਾਬੀ, bn বাংলা, tl Tagalog, to
lea faka-Tonga). `setLang`/`applyLang` (lines ~1002 / ~959) are already generic —
any code present in I18N just works.

## D. Speech-recognition locale — `ilBcp47` (~line 942)
Extend the map: hi→hi-IN, pa→pa-IN, bn→bn-IN, tl→fil-PH (or tl-PH), to→to-TO.
Tongan speech recognition is unlikely to exist in browsers — that's fine, it only
affects the optional Speak feature; typing is unaffected.

## E. Secondary in-JS dictionaries — add a block per new language to EACH:
- `_IL_FAC` (~2457) — nearby-facilities strings
- `_IL_CT`  (~2762) — check-in prompt
- `_IL_AN`  (~2821) — rhythm-anchor strings
- `_IL_PRES` (~3027) — the rare presence words
Each already has en/es/zh; mirror the key set for hi/pa/bn/tl/to.

## F. The blessing (Principle 15) — `var BLESS = "..."` (~lines 5673 AND 6110,
inside the two handoff templates). Currently English only in those spots. Add a
per-language version keyed off the page lang so the send-off blessing appears in the
visitor's language. (In the handoff JSON files you can carry the translated BLESS
string; wire it the same way the other handoff strings are localized.)

## G. Server-side supported-language gate (CRITICAL — without this the new langs 404
to English):
- `_PAGE_I18N` loader (~line 6289): change `for lg in ("es", "zh"):` →
  `("es","zh","hi","pa","bn","tl","to")`.
- Supported check (~line 6306): `return lg if lg in ("en","es","zh") else "en"` →
  include the 5 new codes.
- `_HANDOFF_I18N` loader (~line 7094): same expansion.

## H. Info-page + handoff translation files (native-quality, full page bodies):
Create, using the es/zh files as the exact structural template (same keys/pages):
- `core/i18n_pages_hi.json`, `_pa.json`, `_bn.json`, `_tl.json`, `_to.json`
  (pages: about, how-it-works, privacy, contact, safety, resources, stories, updates)
- `core/i18n_handoff_hi.json`, `_pa.json`, `_bn.json`, `_tl.json`, `_to.json`
  (pages: clinical, legal — keep GATE_T dict, whisper, privacy promise, not-yet line,
  the SAMPLE demo banner, and the blessing)

## I. Info-page language switcher (~lines 6372–6374): add five `?lang=xx` links
matching the existing es/zh pattern so info pages expose all languages too.

## J. Native spoken voice per language: find the earlier per-language voice work
(search `populateVoice`, `voiceForLang`, or where es/zh voices Sofía/Mei were mapped)
and add hi/pa/bn/tl/to → the best matching browser TTS voice, with graceful fallback
to the default when the OS has no voice for that language (very likely for Tongan,
and possibly Punjabi/Bengali). Never break — just fall back silently.

## K. VERIFY before commit (mandatory):
- `python -m py_compile core/axiom_harmony_unified_app.py`
- `python3 check_frontend.py core/axiom_harmony_unified_app.py` (0 failures)
- `grep -c "\\'" core/axiom_harmony_unified_app.py` must be 0 (no backslash-escaped
  quotes inside JS strings — this file is a Python template; use single-quoted JS
  strings with literal double quotes, and NO \n \r \t \" \' inside them)
- Each new JSON must `json.load` cleanly.
- Boot the server and load `/?lang=hi` (and pa/bn/tl/to), switch languages on the
  gate, open an info page and a handoff page in each — confirm no English leaks and
  no page errors.

## L. TRANSLATION QUALITY — the founder's standing instruction (do this):
Write the five sets directly, but for a crisis-context app, phrasing and register
matter more than usual. MARK any phrase where tone/register is uncertain (a trailing
comment or a companion notes file), rather than presenting it as verified. Flag the
whole set for review by a native speaker of each language — **especially Tongan**,
where machine translation is weakest. Present these as "ready, pending native review,"
never as "verified."
