# Atlas — AI Companion

A real-time voice AI companion powered by **Gemini**, with a team of specialist
subagents running under one orchestrator. Talk to it from your **phone** (web
app) or your **computer** (A.D.A. desktop app with live camera/screen vision),
and it acts in the real world: **shopping and finance**, receipt scanning and
printing, your files, your computer, smart home, printers, and live data — plus
a **council** that puts one question to every other AI you own at once.

```
                        ┌─────────────────────────────┐
   Phone (PWA) ────────►│                             │
   voice + chat over    │    ATLAS  (orchestrator)    │
   WebSocket            │    Gemini + function calls  │
                        │                             │
   Desktop (A.D.A.) ───►│  ┌──────┬───────┬────────┬──┴───┐
   Gemini Live voice,   │  │ Home │Printer│Computer│ Data │   ← subagent team
   webcam/screen vision │  │Agent │ Agent │ Agent  │Agent │
                        └──┴──────┴───────┴────────┴──────┘
                             │        │       │        │
                       Home Assistant │    this PC   weather/news/
                                 OctoPrint + CUPS     crypto/time
```

## The subagent team

| Agent | What it does |
|---|---|
| **Scan Agent** | Photo → OCR → structured receipt/invoice → filed as an expense → laid out as a slip → printed. Also image-to-PDF |
| **Finance Agent** | Expenses, spend summaries by category/merchant/month, budgets, tax-year totals, CSV export, printed expense reports |
| **Shopping Agent** | The shopping list (add, check off, print), live price and deal lookups, spend so far this month |
| **Council Agent** | One prompt to **every AI companion at once** — Claude, ChatGPT, Gemini, OpenRouter, or any OpenAI-compatible endpoint you add — side by side, or merged into one verdict |
| **Files Agent** | Full control of the files on this computer (Windows/macOS/Linux): browse, search by name or content, read, write, move, copy, delete, zip, open |
| **Home Agent** | Controls Home Assistant: lights, switches, climate, scenes, any service call, sensor readings |
| **Printer Agent** | OctoPrint 3D printer (status, temperatures, start/pause/resume/cancel jobs, print files) + paper printing via CUPS |
| **Computer Agent** | Live CPU/RAM/disk/battery stats, top processes, volume, open apps & websites, optional shell commands |
| **Data Agent** | Real-time weather + forecast (any city), date/time, news headlines, live crypto prices |

All nine agents register their tools with **Atlas**, the orchestrator. Atlas
runs on **either Gemini or OpenAI** — whichever key you have. It decides which
agent to call, chains calls when needed, and answers back in natural speech.

## Quick start (server + phone)

```bash
./run.sh            # first run creates .venv and .env, then re-run
```

1. Put **one** model key in `.env` — Atlas runs on either:
   - `OPENAI_API_KEY` ([platform.openai.com](https://platform.openai.com/api-keys)) —
     keep `OPENAI_MODEL` vision-capable (`gpt-4o`) so receipt scanning works, or
   - `GEMINI_API_KEY` (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey))

   With both set, Gemini drives by default; `BRAIN_PROVIDER=openai` pins OpenAI.
2. `./run.sh` again. It prints a URL **and a QR code**.
3. On your phone (same Wi-Fi): scan the QR code, then use your browser's
   **"Add to Home Screen"** — Atlas installs like a native app.
4. Tap the mic and talk. Replies are spoken back; after each answer it
   listens again automatically for a hands-free conversation.

> Voice input uses the browser's speech recognition (best in Chrome/Android
> and Safari/iOS). Note: browsers may require HTTPS for mic access on
> non-localhost addresses; if the mic button doesn't work over plain HTTP,
> typing still works, or put the server behind a reverse proxy with TLS
> (e.g. Caddy/Tailscale Serve) for full voice on the phone.

### Remote access from anywhere

**Set `ACCESS_TOKEN` before you expose this server past your own Wi-Fi.** With
one set, every API call and WebSocket must present it; the web app asks once
and remembers it on that device.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # put this in ACCESS_TOKEN
```

The easiest safe transport is [Tailscale](https://tailscale.com): install it on
the server and your phone, then open `http://<machine-name>:8000` from
anywhere. `tailscale serve 8000` also gives you HTTPS for phone mic access.
A token plus Tailscale means the server is never on the open internet at all.

## The workspace

Tap **Workspace** to see the whole operation on one screen: every agent as a
tile, every AI companion you've plugged in, this month's spend by category,
recent receipts, and the shopping list. Tap an agent to hand it a job; type in
the broadcast box to ask every companion the same question and read their
answers side by side.

## Scan a receipt from your phone

Tap 📷, take the photo, and it goes: **photo → OCR → structured fields → filed
as an expense → laid out as a slip → printed.**

```
      REDMAN'S DRAIN CLEANING
================================
Date:                 2026-04-18
Ref:                       #0042
Category:               services
--------------------------------
Main line snake, 75 ft   $120.00
Camera inspection         $40.00
--------------------------------
Subtotal                 $160.00
Tax                       $13.20
TOTAL                    $173.20
================================
  Thank you for your business
```

Set `BUSINESS_NAME`, `BUSINESS_PHONE` and `RECEIPT_FOOTER` to brand the slip,
and `RECEIPT_WIDTH` to match your paper (32 = 58mm roll, 40 = 80mm, 64 =
letter). Amounts come from a real structured parse, so a receipt whose layout
moves still reads correctly — nothing depends on which line a value landed on.

## Running on OpenAI instead of Gemini

Everything that needs a model goes through one layer (`server/brain.py`), so a
single OpenAI key powers the whole workspace: tool-calling orchestration,
reading receipts from photos, and merging the council's answers.

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o      # must be vision-capable to scan receipts
BRAIN_PROVIDER=openai    # optional — only needed if a Gemini key is also present
```

One gap worth knowing: **live price checks need a model that can search the
web.** Gemini does it through Google Search grounding; on OpenAI it goes through
the Responses API's `web_search` tool, which not every model or account has. If
it isn't available, `price_check` returns an error saying so — it will not
guess a price from memory, because a shopping companion that invents prices is
worse than one that admits it can't check.

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

## Controlling your files

The Files agent reads anywhere inside `FILE_ROOTS` (your home folder by
default; `*` for the whole computer). Writing, moving and deleting additionally
need `ALLOW_FILE_WRITE=true` — off by default, because this server is reachable
from your phone and a leaked link shouldn't be able to erase your documents.
For arbitrary commands (PowerShell, shell), turn on `ALLOW_SHELL` too.

## Desktop app (A.D.A.) — real-time voice + vision

The `desktop/` app uses the **Gemini Live API** for low-latency
voice-to-voice conversation, can watch your **webcam or screen**, and has the
same subagent team plus Google Search, code execution, and file tools.

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
| `OPENAI_MODEL`, `OPENAI_BASE_URL` | OpenAI model (vision-capable for scanning) and endpoint |
| `HA_URL`, `HA_TOKEN` | Home Assistant URL + long-lived access token |
| `OCTOPRINT_URL`, `OCTOPRINT_API_KEY` | 3D printer control |
| `CUPS_PRINTER` | Paper printer name (blank = system default) |
| `WEATHER_LAT`, `WEATHER_LON` | Default weather location |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY` | AI companions for the council |
| `COMPANION_ENDPOINTS` | Extra companions: `name\|base_url\|model\|key`, comma separated |
| `BUSINESS_NAME`, `BUSINESS_PHONE`, `RECEIPT_WIDTH`, `RECEIPT_FOOTER` | Printed slip layout |
| `FILE_ROOTS`, `ALLOW_FILE_WRITE` | Which folders the Files agent may touch, and whether it may change them |
| `ACCESS_TOKEN` | Required before exposing the server beyond your own network |
| `DATA_DIR` | Where the ledger, photos and exports live (default `./data`) |
| `ALLOW_SHELL` | `true` to let the Computer Agent run shell commands |
| `ELEVENLABS_API_KEY` | Optional premium TTS for the desktop app |

## Things to say

- "Turn off the living room lights and set the thermostat to 21."
- "How's the print going? Pause it if it's past 80 degrees on the bed."
- "Print this on paper: milk, eggs, coffee."
- "What's my CPU usage? Kill whatever is eating memory."
- "Weather in Tokyo this weekend, and today's top headlines."
- "Open YouTube on my computer and set the volume to 40."

## Security notes

- The server binds to your LAN — anyone on your network can reach it. Keep it
  on a trusted network or behind Tailscale/VPN.
- `ALLOW_SHELL` is **off by default**; shell access lets the AI run arbitrary
  commands as your user. Enable it only if you understand that.
- `.env` (your keys) is git-ignored — never commit it.

## Tests

```bash
python -m unittest discover -s tests -v
```

Covers the ledger (amount parsing, filters, grouping, budgets, shopping list),
the slip layout (nothing overflows the paper at any width, long item names wrap
rather than truncate), path safety (the Scan agent refuses directory traversal,
the Files agent refuses paths outside `FILE_ROOTS` and refuses writes until
they're enabled), and the companion registry.
