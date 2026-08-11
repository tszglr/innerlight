# InnerLight — 5-Language Expansion: Status & Native-Review Notes
Languages: Hindi (hi) · Punjabi (pa) · Bengali (bn) · Tagalog (tl) · Tongan (to)
Status of ALL new-language strings: **READY, PENDING NATIVE REVIEW — NOT VERIFIED.**

## Build status (verified by automated checks — 30/30 pass)
DONE and live:
- Gate footer links (glink.*) translated in all 5 languages — the en/es/zh footer-link
  wiring was already present in the delivered file; only the new keys were needed.
- Gate I18N dictionary: full 29-key set per language (tagline, camera/AI notices,
  story screen, music controls, rail buttons, footer links).
- Gate + info-page language switchers show all 8 languages.
- Speech-recognition locales: hi-IN, pa-IN, bn-IN, fil-PH, to-TO (Tongan browser
  speech recognition likely unavailable — affects the optional Speak button only;
  typing is unaffected, by design).
- In-app dictionaries: nearby-facilities (_IL_FAC), check-in (_IL_CT), rhythm
  anchor (_IL_AN), presence words (_IL_PRES) — all 5 languages.
- Info-page chrome (back link + footer) in all 5 languages.
- Server language gates accept all 8 codes; missing JSON falls back to English
  gracefully (same behavior es/zh had before their files existed). No 404s.
- Spoken voice: the existing picker is fully generic by language code — it will
  prefer a matching browser voice and silently fall back when the OS has none
  (expected for Tongan, possibly Punjabi/Bengali). No code change was needed.
- Blessing (Principle 15): es/zh handoff files already carry it translated; each
  new handoff file will carry its own translated blessing.

REMAINING (next build batches; English fallback active meanwhile):
1. i18n_handoff_{hi,pa,bn,tl,to}.json — clinical + legal handoff pages.
   The EN↔ES structural diff is extracted (i18n_build/diff_clinical.txt,
   i18n_build/diff_legal.txt): 23 + 35 translated segments incl. the 50-state
   clinic blurbs. Generation will be mechanical line-replacement on the English
   template so code cannot be corrupted.
2. i18n_pages_{hi,pa,bn,tl,to}.json — the 8 info pages per language.

## Native-review flags (translator, please check these first)
ARRIVAL GREETING (GATE_GREETINGS): the time-of-day welcome banner ("You made it
here / to morning / to evening...") is now translated in all 5 new languages,
four variants each. These are the first words a person in crisis sees — review
them first in every language. "That took something" is rendered as "that took
courage/strength" (hi/pa/bn) and "that was not easy" (tl/to); confirm the tone
lands as gentle acknowledgment, not as emphasizing hardship.

GLOBAL: 988/911/SAMHSA/FindTreatment numbers and names intentionally untranslated.
"18" age line: Bengali uses Bengali numerals (১৮) in prose; others use ASCII 18 —
reviewer should confirm preferred numeral style per language.

- TONGAN (to) — HIGHEST PRIORITY. Written without native review; machine-quality
  Tongan is the weakest of the five. Specific uncertainty: register of the
  informal "ʻokú ke / hoʻo" (kept informal-warm to match the app's voice —
  confirm this is right for a crisis context, or whether a more respectful
  register is expected); "mea faitā (camera)" gloss; "polokalama ʻatamai
  fakaʻilekitulōnika (AI)" coinage for artificial intelligence; "Māfasia" for
  "overwhelmed"; "Tā ʻo e nonga" for "calm pulse"; ʻokina and toloi (macron)
  placement throughout.
- PUNJABI (pa): "ਪਰਦੇਦਾਰੀ" chosen for privacy (alt: ਗੁਪਤਤਾ); "ਬੋਝ ਹੇਠ" for
  overwhelmed — confirm naturalness on the check-in scale.
- HINDI (hi): gender-neutral phrasing chosen for the companion's own lines
  ("मैं सुनने के लिए यहीं हूँ" instead of gendered सुन रहा/रही) — confirm it
  reads warm, not stiff. "देखभाल सेवा" for the Provider rail button.
- BENGALI (bn): "ভীষণ চাপে" for overwhelmed; informal-respectful আপনি register
  used throughout — confirm.
- TAGALOG (tl): mixed Tagalog/English kept where natural for US-based Filipino
  speakers (camera, device, ZIP, privacy, update, mic); "Pangangalaga" for the
  Provider rail; "nalulula" for overwhelmed — confirm register.

Per the founder's standing rule these five sets must be presented as
"ready, pending native review" — never as "verified."
