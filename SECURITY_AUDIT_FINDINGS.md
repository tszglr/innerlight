# InnerLight Security Check — Plain-Language Findings

_Prepared for the founder. Written to be read without any technical background. Every short-form term is spelled out the first time it appears._

---

## 1. The short version (please read this first)

**Good news: we searched the entire project, top to bottom, and found no real
passwords, no real keys, and no real login secrets hiding in the code.** Nothing
sensitive is exposed to the public, even though the project's code is public.

The people-facing secrets that matter (your admin password, and the keys that let
InnerLight talk to the outside services it uses) are **not written in the code at
all**. They live safely in your Render dashboard as "environment variables"
(settings the code reads at runtime but that never appear in the code itself).
That is exactly the right, professional way to do it.

We did find a few things that *look* like passwords sitting in the code. **Those
are fakes on purpose** — decoys planted to trap and slow down attackers. They are
not real and cannot unlock anything. Section 3 explains them in kind detail so
they never worry you again.

We also have **three small "make-it-even-safer" suggestions** (none urgent, none a
leak today). They are in Section 4, written as things you simply decide or click —
never anything you have to type or run.

**Bottom line: there is no emergency here, and nothing you need to rotate or panic
about. This is a healthy result.**

---

## 2. What we checked

Think of the project as a house. We checked both the house as it stands today
**and** its full construction history — because sometimes a secret gets written
down, then removed, but the old note is still tucked inside the walls where a
determined person could find it.

Concretely, we looked through:

- **Every current file** in the project (the code, the settings, the notes).
- **The complete history** of every change ever made — all 267 recorded
  save-points ("commits"), including anything that was once added and later
  deleted.

And we searched for every common shape of a real secret:

- Passwords and admin login credentials.
- Keys and tokens for the outside services InnerLight uses. ("API key" = 
  Application Programming Interface key — a long password-like string that lets
  one program talk to another service, such as the voice or the conversation
  service.) We searched for the tell-tale patterns of Anthropic, ElevenLabs,
  Deepgram, OpenAI, Amazon Web Services, GitHub, and Slack keys specifically.
- "Private keys" (the secret half of a digital certificate).
- Database connection strings (a single line that bundles a database address,
  username, and password together).
- Any other value that looked like it might be sensitive.

---

## 3. What we found

### 3a. Real secrets exposed in the code: **none**

We found **zero** real passwords, keys, or tokens committed anywhere — not in the
current files, and not anywhere in the full history. This is the result you want.

Here is *why* the project is safe, in plain terms:

- **Your real secrets are read from the Render dashboard, not stored in code.**
  The code asks the hosting service ("Render") for each secret by name when it
  runs — your admin password (named `ADMIN_KEY`), the conversation service key,
  the voice service keys, and so on. The actual values are never written in the
  project. If someone reads all the public code, they still learn none of your
  secrets.

- **The website's "session secret" has a safe automatic backup.** A session
  secret is a value the site uses to keep each visitor's session secure. If you
  ever forgot to set one, the code doesn't fall back to something guessable — it
  makes up a fresh, strong, random one on its own. So there is no weak default to
  exploit.

- **The admin login is built carefully.** Signing in to the founder's operations
  room ("The Watch") compares your password in a way that doesn't leak hints
  about how close a guess was, and it deliberately slows down and then locks out
  anyone who keeps guessing wrong. In everyday terms: the front door is sturdy and
  it gets *harder* to force, not easier, the more someone bangs on it.

### 3b. Things that LOOK like secrets but are safe on purpose (decoys / "honeypots")

While searching, we came across a handful of official-looking passwords and keys
sitting right in the code. **These are intentional fakes.** In security, a
"honeypot" is a decoy left out in the open to catch intruders — like a fake
jewelry box with costume jewelry, positioned so that anyone who opens it reveals
themselves as a thief.

InnerLight has several of these decoys built in on purpose:

- A **fake settings file** that an attacker might go looking for. If they request
  it, InnerLight hands them a believable-but-completely-fake set of passwords and
  keys, and quietly marks that visitor as hostile.
- A **fake "list of keys" page** that does the same thing.
- Fake **WordPress** and **phpMyAdmin** login pages (common things attackers probe
  for) that lead nowhere real.

The clever part: one of the fake values is a tripwire. If it ever comes *back* to
InnerLight in a later request, that could only happen if someone had scooped it up
from a decoy — so the system instantly flags and blocks them.

**None of these fake values can unlock anything. They protect the site rather than
endanger it.** You do not need to remove them or worry about them. We are only
naming them here so that if you or a helper ever spot them, you'll know they are
friendly decoys, not a mistake.

### 3c. The founder's encryption module — a quick health check

You built a module that scrambles sensitive stored information so it can't be read
without the right key. We reviewed it at a high level (we did not change it), and
it is **genuinely strong and modern**:

- It uses **AES-256-GCM**, a widely trusted, top-tier method that both scrambles
  the data *and* detects tampering — if someone alters the stored data, it refuses
  to unlock rather than quietly returning corrupted results.
- For turning your key into the scrambling key, new records use **scrypt**, a
  method deliberately designed to be slow and memory-hungry for attackers, which
  makes mass password-guessing extremely expensive. (Older records used a
  respectable earlier method, and the code still reads them correctly forever.)
- Every stored item gets its own fresh random values, so no two items share a
  pattern an attacker could exploit.
- There's an optional extra "server-held secret" ("pepper") that, if turned on,
  means even a stolen copy of the data can't be cracked without a piece that was
  never stored alongside it.

One honest note the module itself already states: this is excellent *classical*
protection, but it is **not yet "quantum-proof."** That is a future-facing
consideration, not a problem today, and the module is upfront about it. No action
needed now.

---

## 4. What to do

**Nothing here is urgent, and none of it is a leak today.** These are three ways to
make an already-healthy setup even sturdier. Each is written as a decision or a
click — you never have to type a command or touch anything technical. If you have a
technical helper, the exact details are in the appendix for them.

1. **Tell the browser to only ever send the login cookie over a secure
   connection.** Right now the site works fine, but it doesn't *explicitly* insist
   that the small "you're logged in" token only travels over the padlock-secured
   (HTTPS) connection. Since your site is always secured on Render anyway, turning
   this on is a small, safe tightening. **Decision for you:** ask your helper to
   set the three "session cookie" safety flags (details in the appendix). No
   downside, and it closes a theoretical gap.

2. **Add one line to the "ignore list" so a secrets file can never be uploaded by
   accident.** Projects keep an "ignore list" of files that should never be saved
   into the public code. Yours currently doesn't list the usual name for a local
   secrets file (`.env`). No such file exists today, so nothing is exposed — but
   adding it is cheap insurance against a future accidental upload. **Decision for
   you:** ask your helper to add `.env` to that ignore list.

3. **Fix a misleading note in the code about the admin login.** There is an old
   comment in the code suggesting you can sign in by putting your admin password
   directly into the web address (like `/admin?key=YOUR_PASSWORD`). **Good news:
   the code does not actually work that way** — we checked, and that method is
   ignored; the only real way in is the proper sign-in form. Putting a password in
   a web address is risky because addresses get saved in browser history and
   server logs, so we're glad it isn't honored. **Decision for you:** ask your
   helper to delete that misleading comment so no one is ever tempted to try it.
   (This is tidying up wording, not fixing a live hole.)

---

## 5. For the technical helper (exact references)

_This appendix is for an engineer. Everything above is the founder-facing summary._

**Scope:** full working tree plus complete git history (`git log --all -p`, 267
commits). Repository: public, `github.com/tszglr/innerlight`.

**Secret scans run (all clean):**

- High-confidence token patterns across the working tree —
  `grep -rnE '(sk-[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-)'`
  → no matches.
- Same patterns across full history —
  `git log --all -p | grep -inE '(sk-[A-Za-z0-9]{20}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36})'`
  → no matches.
- `BEGIN … PRIVATE KEY`, database connection strings (`postgres://…:…@`, etc.),
  and hardcoded `password|secret|api_key|token = "literal"` assignments → no real
  matches. The only hits were (a) the `_HONEYTOKEN` decoy references and (b) doc
  placeholders `"your_key_here"` / `"your-key-here"` in `core/zenisys_music_engine.py`
  and `download_scenes.py`.
- No `.env` / secrets / credential files are tracked, present on disk, or in
  history.

**Verified-safe facts (independently confirmed, not just inherited):**

- Real secrets read from the environment (all via `os.environ.get`, none in repo):
  `ADMIN_KEY`, `ADMIN_USER`, `AHP_UNIFIED_SECRET`, `ELEVENLABS_API_KEY`,
  `ANTHROPIC_API_KEY`, `DEEPGRAM_API_KEY`, `DAILY_API_KEY`, `HUME_API_KEY`,
  `OPENAI_API_KEY`, `FREESOUND_API_KEY`, `NTFY_TOPIC`, `AHP_DATA_SECRET`,
  `AHP_PEPPER`.
- `app.secret_key`: `core/axiom_harmony_unified_app.py:88` falls back to
  `os.urandom(32).hex()` when `AHP_UNIFIED_SECRET` is unset. Note a second
  assignment at line ~12323 derives the key as
  `sha256("innerlight-founder-session::" + ADMIN_KEY)`; when `ADMIN_KEY` is set on
  Render this is stable and non-guessable, but it means the session key is derived
  deterministically from `ADMIN_KEY` rather than an independent random secret —
  acceptable, but worth being aware of (rotating `ADMIN_KEY` invalidates existing
  sessions).
- Admin auth: `admin_login()` (~line 12639) uses
  `secrets.compare_digest(p, admin_key)` and `secrets.compare_digest(u, admin_user)`
  (constant-time), gated by `_defend()` (progressive tarpit + lockout) and
  `_flag_hostile("admin-login-fail")` on failure.
- Honeypots are deliberate: `_HONEYTOKEN` at line ~11808; fake `.env` body in
  `_fake_env_body()` (~11819, serves fabricated `DB_PASSWORD` / `SECRET_KEY` /
  `API_KEY` / `PAYMENT_SECRET`); decoy routes `/.env`, `/api/keys`, `/api/v1/keys`,
  `/wp-login.php`, `/wp-admin`, `/admin.php`, `/phpmyadmin` (~11833–12046); replay
  tripwire `_honeytoken_watch()` `@app.before_request` (~12047). All fabricated,
  none real.

**Encryption module (`core/ahp_encryption.py`) — high-level assessment:** sound.
AES-256-GCM AEAD; default KDF is scrypt (N=2^15, r=8, p=1) for new records; legacy
PBKDF2-HMAC-SHA256 at 390,000 iterations retained read-only for v1 records; fresh
16-byte salt + 12-byte nonce per record; version/context bound as GCM associated
data; optional HKDF-mixed `AHP_PEPPER`. No changes recommended in this pass; the
module is honest that it is classical (not post-quantum) crypto.

**Hardening recommendations (not active leaks):**

1. **Session cookie flags.** No `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE`,
   or `SESSION_COOKIE_HTTPONLY` are set anywhere (no `app.config[...]` for them).
   Since Render serves over HTTPS, add:
   `app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")`.
2. **.gitignore.** `.gitignore` currently lists only `__pycache__/` and `*.pyc`.
   Add `.env` (and any local secrets filenames) as belt-and-suspenders against
   accidental commits. No such file exists today.
3. **Stale `?key=` docstring.** `admin_dashboard()` docstring
   (`core/axiom_harmony_unified_app.py:13331`) reads
   `Open /admin?key=YOUR_ADMIN_KEY`. **Verified: no code reads
   `request.args.get("key")`** — access is gated solely by `session["founder_ok"]`
   (set only by the POST `/admin/login` form) or `_has_watch_access()`. The
   query-string login is **not honored**; only the docstring is misleading. Delete
   or correct the docstring so no one is tempted to place a secret in a URL.

**No real secret was found. No rotation is required.** (If one had been found, the
correct remediation — which only the founder/orchestrator can perform, not this
audit — would be: rotate the secret in the provider dashboard, remove it from code
and history, and read it from an environment variable going forward.)
