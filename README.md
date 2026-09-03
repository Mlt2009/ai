# Mehltani — AI Creative Director

A real-time voice AI companion for **fashion design, hair, makeup and styling**,
built on the same real-time workspace this repo started as (shopping/finance,
receipt scanning, smart home, printers, live data), extended into a Jarvis-style
operator: it scouts the web for pieces that match your taste, learns from every
verdict you give it, runs your inbox and calendar across Google and Microsoft,
messages you on WhatsApp, watches over its own security with a real fingerprint
gate, and can propose, test and ship changes to its own source code — or write
a brand-new specialist from scratch when the team is missing a skill.

Talk to it from your **phone** (web app) or your **computer** (A.D.A. desktop
app with live camera/screen vision, powered by the Gemini Live API).

```
                        ┌───────────────────────────────┐
   Phone (PWA) ────────►│                               │
   voice + chat over    │     MEHLTANI  (orchestrator)  │
   WebSocket            │     Gemini/OpenAI + tool use  │
                        │                               │
   Desktop (A.D.A.) ───►│  identity.py + style_memory →  │
   Gemini Live voice,   │  system prompt rebuilt every  │
   webcam/screen vision │  session from the taste you   │
                        │  actually showed it            │
                        └───────────────┬───────────────┘
                                         │
        ┌────────┬──────────┬──────┬────┴────┬───────────┬──────────┐
        │ style  │photoshoot│ glam │  trend   │ whatsapp  │workspace │  ← creative
        │(taste) │ (shoots) │(hmu) │(scouting)│ (phone)   │(Gmail/365)│    + business
        └────────┴──────────┴──────┴──────────┴───────────┴──────────┘
        ┌────────┬──────────┬──────┬──────────┬───────────┬──────────┐
        │  scan  │ finance  │shop- │ council  │  files    │ computer │  ← original
        │(receipt)│(spend)  │ping  │(other AI)│(this PC)  │(this PC) │    workspace
        └────────┴──────────┴──────┴──────────┴───────────┴──────────┘
        ┌────────┬──────────┬──────────┬───────────────────────────┐
        │ home   │ printer  │  data    │  guardian     │ evolution  │  ← safety +
        │  (HA)  │(3D+paper)│(wx/news) │(fingerprint,  │(self-edit, │    self-growth
        │        │          │          │ threats, audit)│new agents)│
        └────────┴──────────┴──────────┴───────────────────────────┘
```

## The subagent team

**Creative core**

| Agent | What it does |
|---|---|
| **Style Agent** | Critiques a look/photo (palette, silhouette, proportion, references), builds colour palettes, and owns the learned taste profile — every verdict you give trains it |
| **Photoshoot Agent** | Turns a photo into a full editorial direction (lighting, lens, location, posing, shot list, call sheet), or renders an AI mockup from a reference photo |
| **Glam Agent** | Hair and makeup at working-artist depth — face/hair reads, step-by-step looks with timings and products *by category* (never invented brands), colour formulation with honest damage risk, client profiles |
| **Trend Agent** | Scouts the *live* web for pieces matching your taste, checks authenticity before you buy, sends finds to WhatsApp with tap-to-answer buttons, and gets you to checkout (it never completes a purchase itself) |
| **WhatsApp Agent** | Send/receive on WhatsApp Business — looks, photos, tap-to-decide questions |
| **Workspace Agent** | Gmail + Outlook, Google Drive + OneDrive, both calendars, Teams — read freely, send needs a fingerprint |

**Original workspace**

| Agent | What it does |
|---|---|
| **Scan Agent** | Photo → OCR → structured receipt/invoice → filed as an expense → laid out as a slip → printed |
| **Finance Agent** | Expenses, spend summaries, budgets, tax-year totals, CSV export, printed reports |
| **Shopping Agent** | The shopping list, live price and deal lookups, spend so far this month |
| **Council Agent** | One prompt to every other AI you own at once (Claude, ChatGPT, Gemini, OpenRouter, any endpoint) — broadcast, ask one, or merge |
| **Files Agent** | Browse, search, read, write, move, copy, delete, zip, open — anywhere inside `FILE_ROOTS` |
| **Home Agent** | Home Assistant: lights, climate, scenes, sensors |
| **Printer Agent** | OctoPrint 3D printer + paper printing via CUPS |
| **Computer Agent** | Live stats, processes, volume, open apps/sites, optional shell |
| **Data Agent** | Real-time weather, time, news, crypto prices |

**Safety and self-growth**

| Agent | What it does |
|---|---|
| **Guardian Agent** | Security posture, threat log, audit trail, lockdown — the read side of the fingerprint gate |
| **Evolution Agent** | Proposes a change to Mehltani's own code, verifies it against the real test suite in a sandboxed repo copy, shows the diff, ships it only behind a fingerprint; also designs and registers brand-new subagents at runtime |

Every agent registers its tools with **Mehltani**, the orchestrator, which runs
on **either Gemini or OpenAI** — whichever key you have. It decides which
agent/tool to call, chains calls when needed, and answers back in natural
speech. The system prompt (`server/identity.py`) is rebuilt at the start of
every session from the live taste profile, so a session started after a month
of verdicts already talks like it knows you.

## Quick start (server + phone)

```bash
./run.sh            # first run creates .venv and .env, then re-run
```

1. Put **one** model key in `.env` — Mehltani runs on either:
   - `OPENAI_API_KEY` ([platform.openai.com](https://platform.openai.com/api-keys)) —
     keep `OPENAI_MODEL` vision-capable (`gpt-4o`) so photo/receipt reading works, or
   - `GEMINI_API_KEY` (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey))

   With both set, Gemini drives by default; `BRAIN_PROVIDER=openai` pins OpenAI.
2. `./run.sh` again. It prints a URL **and a QR code**.
3. On your phone (same Wi-Fi): scan the QR code, then use your browser's
   **"Add to Home Screen"** — Mehltani installs like a native app.
4. Tap the mic and talk. Replies are spoken back; after each answer it
   listens again automatically for a hands-free conversation.
5. Open **Security** in the app and enrol your fingerprint (Touch ID / Face
   ID / Windows Hello / Android) — see [Security & the biometric
   gate](#security--the-biometric-gate) below before you rely on it.

> Voice input uses the browser's speech recognition (best in Chrome/Android
> and Safari/iOS). Note: browsers may require HTTPS for mic access **and for
> WebAuthn** on non-localhost addresses; if the mic or fingerprint prompt
> doesn't work over plain HTTP, put the server behind a reverse proxy with TLS
> (e.g. Caddy/Tailscale Serve).

### Remote access from anywhere

**Set `ACCESS_TOKEN` before you expose this server past your own Wi-Fi.** With
one set, every API call and WebSocket must present it; the web app asks once
and remembers it on that device.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # put this in ACCESS_TOKEN
```

The easiest safe transport is [Tailscale](https://tailscale.com): install it on
the server and your phone, then open `http://<machine-name>:8000` from
anywhere. `tailscale serve 8000` also gives you HTTPS for phone mic access
**and lets WebAuthn work off your own network** — see `RP_ID` below.

## Security & the biometric gate

Every irreversible or expensive action — shutting Mehltani down, spending
money, sending mail/messages outside the household, revealing a stored secret,
disabling an agent, unlocking the shell, shipping a change to Mehltani's own
code — is gated behind a **real WebAuthn check**: Touch ID, Face ID, Windows
Hello, or an Android fingerprint reader. This is enforced server-side
(`server/guardian.py`), not just hidden in the UI.

**Read this before you rely on it.** A biometric gate on a process you own can
stop *other people* — someone who picks up your unlocked phone, or reaches the
dashboard on your network — but it cannot and should not stop *you*: `Ctrl-C`,
`kill`, and closing the lid always work, because software that fights its
owner's shutdown is malware by definition, not a safety feature. Uptime comes
from running Mehltani under a supervisor that restarts it on a crash, not from
resisting being stopped.

**Setup:**
1. Open **Security** in the web app and tap **Enrol this device's fingerprint**
   the first time — there's nothing to confirm it against yet, so this one
   enrolment is unprotected by design. Every device after the first requires
   confirming with one you already enrolled, so nobody else can quietly add
   their own fingerprint as a backdoor.
2. `RP_ID` in `.env` must match the domain in your browser's address bar (no
   scheme, no port) — `localhost` is correct for local-only use; set it to your
   Tailscale/tunnel hostname if you access Mehltani remotely.
3. Set `RECOVERY_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(32))"`)
   as your escape hatch if the enrolled device is ever lost or broken — using it
   is logged as a threat on purpose, so you'll know if it was used without you.
4. `REQUIRE_BIOMETRIC=false` turns the whole gate off if you'd rather not use
   it; `AUTO_LOCKDOWN=true` (default) freezes every protected action the moment
   a critical threat is detected (a tampered file, a burst of failed
   fingerprint checks), until cleared with a fingerprint.

Ask Mehltani *"am I secure"* or *"has anything tried to get in"* any time — the
Guardian agent reads the threat log, the audit trail, and runs a live check
(file-integrity hashes on its own safety-relevant code, network exposure,
unexpected listening ports).

## The workspace

Tap **Workspace** to see every agent as a tile, every AI companion you've
plugged in, this month's spend by category, recent receipts, and the shopping
list. Tap **Style** for the taste profile — what Mehltani has learned you love
and reject, the scouting queue awaiting a verdict, and the lookbook.

## Learning your taste and scouting the web

Every time you react to a look — *"love it"*, *"not for me, the cut is
wrong"*, a tap on a WhatsApp button — Mehltani writes it to a taste profile
(`server/style_memory.py`): recency-weighted attribute scores (a look from
last week counts more than one from a year ago), stated rules you said
outright (*"I never wear yellow"*), a lookbook, and client profiles.

*"Find me something like the coat I loved last week"* fans out to a live web
search, checks each result's authenticity before proposing it (price against
real retail/resale, seller signals, photo quality — never a false
reassurance), and sends finds to your WhatsApp Business number with **Love
it / Pass / Show me more** buttons. Your tap trains the profile automatically.
When you want to buy, Mehltani gets you a verified checkout link and your
size — behind your fingerprint, since it never completes a purchase itself
(storing your card and fighting retailers' bot defenses is a liability, not
a convenience worth the risk).

## Connecting WhatsApp Business

1. developers.facebook.com → your Meta app → WhatsApp → API Setup. Note the
   **phone number ID** and generate a **permanent system-user token**.
2. Webhook URL: `https://<your-host>/api/whatsapp/webhook`. Verify token:
   whatever you set as `WHATSAPP_VERIFY_TOKEN`. Subscribe to the `messages`
   field.
3. `WHATSAPP_APP_SECRET` (Meta app → Settings → Basic) lets the webhook verify
   Meta's signature on every inbound message — set it before exposing the
   webhook publicly.
4. `WHATSAPP_OWNER` is your own number (country code + digits, no `+`).

Outside a 24-hour window opened by your own message, WhatsApp only delivers
pre-approved templates — a free-form send outside that window comes back with
a plain-English explanation rather than silently failing.

## Connecting Google Workspace and Microsoft 365

Both go through plain REST with a refresh token — no heavy SDK, no separate
credential store.

```bash
python -m server.integrations.google_ws      # walks the OAuth flow, prints
                                              # GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN
python -m server.integrations.microsoft_ws   # same, for MS_CLIENT_ID/SECRET/TENANT/REFRESH_TOKEN
```

Once connected: *"anything important in my inbox"*, *"what's on my calendar
this week"*, *"draft a reply saying the fitting needs to move to Thursday"*.
Reading is unrestricted; **sending mail, Teams messages, or WhatsApp to anyone
but yourself needs a fingerprint** — an assistant that asks for one just to
check your inbox is one you stop using by Thursday, but mail that leaves the
building cannot be recalled.

## Meta glasses

There is **no public streaming API** for Ray-Ban Meta glasses yet — Meta's
Wearables Device Access Toolkit is a gated developer preview. Two routes work
today:

1. **Say "Hey Meta, send a photo to Mehltani"** — it lands on your WhatsApp
   Business number and Mehltani replies in the thread, which the glasses read
   back to you. Fastest, zero extra setup beyond WhatsApp above.
2. **Point `GLASSES_WATCH_DIR` at a folder your camera roll syncs to**
   (iCloud Photos, Google Photos desktop, Syncthing, Dropbox) — full
   resolution, ingested automatically, higher latency.

`server/integrations/glasses.py` documents route 3 (the real toolkit, when
your access is approved) as a seam that needs no other code to change.

## Mehltani rewriting his own code

*"You're missing a skill — add one"* or *"fix the bug where..."* runs a real
pipeline (`server/evolution.py`), not a naive exec-the-model's-output shortcut:

1. **propose** — the model rewrites a whole file to achieve the goal; nothing
   runs yet, nothing touches the live tree.
2. **verify** — the *entire repo* is copied to a scratch directory, the change
   applied there, and the real test suite run against the copy in a
   subprocess. A syntax error or a failing test kills the proposal before it
   ever reaches your code.
3. **diff** — you read exactly what would change.
4. **apply** — gated behind your fingerprint, and lands as a git commit, so a
   bad change is one `evolution__rollback` away.

Two things are never negotiable: `guardian.py` cannot be edited through this
pipeline (code that can edit its own safety check has no safety check), and a
shipped change never hot-patches the running process — it takes effect on the
next restart, so a bad change can't corrupt a conversation in progress.

*"Build me a new agent that knows fabric weights"* runs a parallel, faster
pipeline (`server/factory.py`) for brand-new specialists: the generated source
is checked against an import allowlist (no `os`, `subprocess`, `socket`,
`eval`, `exec`, dunder attribute access) via an AST scan — not a regex, so it
can't be defeated by string tricks — before anything is written to disk, and a
generated agent can never take an existing agent's name. It joins the team
immediately; say "reset" or reconnect to have the model see its tools in its
own list.

## Running on OpenAI instead of Gemini

Everything that needs a model goes through one layer (`server/brain.py`), so a
single OpenAI key powers the whole workspace: tool-calling orchestration,
reading photos, image generation for photoshoot mockups, and merging the
council's answers.

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o      # must be vision-capable to read photos/receipts
BRAIN_PROVIDER=openai    # optional — only needed if a Gemini key is also present
```

One gap worth knowing: **live web search (price checks, trend scouting) needs
a model that can search the web.** Gemini does it through Google Search
grounding; on OpenAI it goes through the Responses API's `web_search` tool,
which not every model or account has. If it isn't available, the tool returns
an error saying so — it will not guess a price or invent a listing from
memory, because acting on a hallucinated fact costs more than admitting it
can't check.

`OPENAI_BASE_URL` points the brain at a proxy, an Azure gateway, or a local
OpenAI-compatible server instead of `api.openai.com`.

## Talking to all your AI companions at once

Fill in any of `ANTHROPIC_API_KEY` (Claude), `OPENAI_API_KEY` (ChatGPT),
`OPENROUTER_API_KEY`, or the Gemini key you already have, and each becomes a
council member. `COMPANION_ENDPOINTS` adds anything else that speaks the
OpenAI `/chat/completions` shape:

```
COMPANION_ENDPOINTS=ollama|http://localhost:11434/v1|llama3|,work|https://my-router/v1|auto|sk-xxx
```

Then: *"ask all of them whether this quote is fair"* broadcasts in parallel, or
*"get a consensus on…"* merges the answers into one, flagging where they
disagree.

**What this does not do:** it doesn't drive the ChatGPT, Gemini or Cursor
*desktop apps* — those have no public automation surface. It talks to the same
models through their APIs, which is the part that's actually controllable.

## Controlling your computer

The Files agent reads anywhere inside `FILE_ROOTS` (your home folder by
default; `*` for the whole computer). Writing, moving and deleting additionally
need `ALLOW_FILE_WRITE=true` — off by default, because this server is reachable
from your phone and a leaked link shouldn't be able to erase your documents.
For arbitrary shell commands, turn on `ALLOW_SHELL` too — and consider turning
`REQUIRE_BIOMETRIC` on if you do, since a shell is the highest-value target on
the machine.

## Desktop app (A.D.A.) — real-time voice + vision

The `desktop/` app uses the **Gemini Live API** for low-latency
voice-to-voice conversation, can watch your **webcam or screen**, and shares
the full subagent team plus Google Search, code execution, and file tools.

```bash
pip install -r requirements.txt -r desktop/requirements.txt
python desktop/companion.py            # optional: --mode camera|screen|none
```

Optional: set `ELEVENLABS_API_KEY` in `.env` for premium TTS voices (without
it, A.D.A. runs with text output; the web app always speaks using free
browser voices). `desktop/tutorials/` contains step-by-step scripts showing
how each Gemini feature works.

## Configuration (.env)

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` / `GEMINI_API_KEY` | The brain — **one of these is required** |
| `BRAIN_PROVIDER` | `auto` (default), `gemini` or `openai` |
| `OPENAI_MODEL`, `OPENAI_BASE_URL` | OpenAI model (vision-capable for photos) and endpoint |
| `GEMINI_IMAGE_MODEL`, `OPENAI_IMAGE_MODEL` | Image-generation models for photoshoot mockups |
| `HA_URL`, `HA_TOKEN` | Home Assistant URL + long-lived access token |
| `OCTOPRINT_URL`, `OCTOPRINT_API_KEY` | 3D printer control |
| `CUPS_PRINTER` | Paper printer name (blank = system default) |
| `WEATHER_LAT`, `WEATHER_LON` | Default weather location |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` | AI companions for the council |
| `COMPANION_ENDPOINTS` | Extra companions: `name\|base_url\|model\|key`, comma separated |
| `BUSINESS_NAME`, `BUSINESS_PHONE`, `RECEIPT_WIDTH`, `RECEIPT_FOOTER` | Printed slip layout |
| `FILE_ROOTS`, `ALLOW_FILE_WRITE` | Which folders the Files agent may touch, and whether it may change them |
| `ACCESS_TOKEN` | Required before exposing the server beyond your own network |
| `DATA_DIR` | Where the ledger, taste profile, guardian log, photos and exports live (default `./data`) |
| `ALLOW_SHELL` | `true` to let the Computer Agent run shell commands |
| `ELEVENLABS_API_KEY` | Optional premium TTS for the desktop app |
| `OWNER_NAME` | Your name, used in the WebAuthn enrolment prompt |
| `RP_ID`, `EXTRA_ORIGINS` | The domain WebAuthn binds credentials to, plus any extra tunnel origins |
| `REQUIRE_BIOMETRIC`, `AUTO_LOCKDOWN` | Turn the fingerprint gate and auto-lockdown-on-critical-threat on/off |
| `RECOVERY_KEY` | Escape hatch if your enrolled device is lost — using it is logged as a threat |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_OWNER` | WhatsApp Business Cloud API |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` | Google Workspace (Gmail/Drive/Calendar) |
| `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT`, `MS_REFRESH_TOKEN` | Microsoft 365 (Outlook/OneDrive/Calendar/Teams) |
| `GLASSES_WATCH_DIR` | Folder to watch for new Meta glasses captures (camera-roll sync) |

## Things to say

- "What do you think of this look?" *(photo of an outfit)*
- "Find me something in this direction, under $400."
- "Design a hair and makeup look to go with this — twelve-hour shoot day."
- "Direct a shoot around this photo — moody, late-autumn light."
- "Am I secure? Has anything tried to get in?"
- "Anything important in my inbox? What's on my calendar this week?"
- "Turn off the living room lights and set the thermostat to 21."
- "Print this on paper: milk, eggs, coffee."
- "What's my CPU usage? Kill whatever is eating memory."
- "Weather in Tokyo this weekend, and today's top headlines."

## Security notes

- The server binds to your LAN — anyone on your network can reach it. Keep it
  on a trusted network or behind Tailscale/VPN.
- Money, sending mail/messages outside the household, revealing a secret,
  disabling an agent, unlocking the shell, and shipping a self-code-change all
  require a live fingerprint (`REQUIRE_BIOMETRIC=true` by default) — see
  [Security & the biometric gate](#security--the-biometric-gate).
- `ALLOW_SHELL` is **off by default**; shell access lets the AI run arbitrary
  commands as your user. Enable it only if you understand that.
- `.env` (your keys) is git-ignored — never commit it.

## Tests

```bash
python -m unittest discover -s tests -v
```

`tests/test_workspace.py` covers the original workspace: the ledger (amount
parsing, filters, grouping, budgets, shopping list), the slip layout, path
safety (Scan/Files agents), and the companion registry.

`tests/test_mehltani.py` covers the new core: the taste profile's
recency-weighted scoring, the biometric gate's every branch (including that
enrolling a second fingerprint device is itself gated), the self-evolution
pipeline end to end (propose → sandboxed verify → apply denied without a
fingerprint → the live file stays untouched), the subagent factory's AST
validator (every rejection path — banned imports, `eval`, dunder access,
missing tools, reserved-name collisions), and tolerant JSON parsing.
