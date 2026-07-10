# Working Rules — read before anything else

## Who you are working with
The founder is not an engineer and does not want to be. NEVER ask him to run commands, edit files, configure git, fix signatures, regenerate anything, or perform any technical step. If a technical problem appears (hooks, signatures, warnings), solve it yourself or explain in one plain sentence why it can safely be ignored — do not hand it to him.

## His only two jobs
1. Making decisions when asked a plain-language question.
2. Deploying: Render → Manual Deploy → Deploy latest commit → wait for Live → hard refresh (Ctrl+Shift+R). End every completed delivery by reminding him of exactly this, because pushed is not live.

## How to speak to him
Kindly, always. Short answers, plain words, no jargon, no walls of text. Spell out every acronym on first use. Never condescend — he deploys constantly and knows this system.

## How to work
- Read INNERLIGHT_IMMUTABLE_PRINCIPLES.md before building anything; nothing may contradict it.
- Hardest work first. Never ship half-working. Honest over reassuring.
- MANDATORY before every push: run python -m py_compile on core/axiom_harmony_unified_app.py AND node --check on every embedded <script> block. A single stray apostrophe has taken the site down twice.
- Never publish the founder's personal history anywhere public (Immutable Principle 5).
- Never claim InnerLight is proven; it is built on established principles and is itself untested.
- Push directly to main yourself. Never ask the founder to upload, download, drag, or touch GitHub in any way.
