# Artist — AI Companion

**Artist** is a J.A.R.V.I.S.-inspired AI companion powered by **Gemini**.
It serves four roles at once:

| Role | Description |
|---|---|
| **Chat assistant** | Conversational dialogue that maintains context across turns |
| **Coding companion** | Syntax checking, file reading, code review and generation |
| **Swarm coordinator** | Routes tasks to specialist subagents, chains calls when needed |
| **Token-saving helper** | Auto-compresses long context to keep sessions lean and fast |

Artist also carries a curated library of **50 J.A.R.V.I.S.-inspired creative
image/video generation prompts** — searchable by keyword or theme.

## Run Artist (terminal chat)

```bash
# one-time setup
pip install -r requirements.txt

# set your key
echo "GEMINI_API_KEY=your_key_here" >> .env

# start chatting
python artist.py
```

In-session commands:

| Command | Effect |
|---|---|
| `/reset` | Clear conversation history |
| `/compress` | Manually summarise context to save tokens |
| `/team` | Show the active agent roster |
| `/prompts` | List the 50 creative prompt themes |
| `/help` | Show command reference |
| `exit` / `quit` | End the session |

### Artist's persona

Artist adopts a **J.A.R.V.I.S.-style personality**:
- Formal, precise, and dryly witty
- Addresses the user as *Sir*
- Demands clarity before acting on vague requests
- Breaks complex tasks into actionable steps
- Flags risks and misconfigurations proactively
- Delivers concise, efficient responses

### Agent team

| Agent | What it does |
|---|---|
| **Coding** | `syntax_check`, `read_file`, `list_files` — grounded code answers |
| **Creative** | `get_prompt`, `search_prompts`, `list_themes` — 50 creative prompts |
| **Data** | Real-time weather, time, news, crypto |
| **Computer** | CPU/RAM stats, processes, volume, open apps |
| **Home** | Home Assistant smart-home control |
| **Printer** | OctoPrint 3D + CUPS paper printing |

### Creative prompt library

Artist's creative agent holds **50 J.A.R.V.I.S.-inspired visual/video
generation prompts** across themes including:

`ai` · `ar` · `audio` · `automation` · `biotech` · `coding` · `command` ·
`cybersecurity` · `diagnostics` · `energy` · `engineering` · `exploration` ·
`hardware` · `infrastructure` · `manufacturing` · `media` · `mobility` ·
`physics` · `productivity` · `quantum` · `research` · `robotics` · `space`

Ask Artist to retrieve any prompt by number (1–50) or search by keyword/theme.

---

## Atlas — Web + Voice companion

Artist's subagent team (Home, Printer, Computer, Data) is shared with
**Atlas**, the real-time voice assistant you can run on your phone or the
A.D.A. desktop app.

A real-time voice AI companion powered by **Gemini**, with a team of specialist
subagents running under one orchestrator. Talk to it from your **phone** (web
app) or your **computer** (A.D.A. desktop app with live camera/screen vision),
and it acts in the real world: smart home, printers, your computer, and live
data.

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
| **Home Agent** | Controls Home Assistant: lights, switches, climate, scenes, any service call, sensor readings |
| **Printer Agent** | OctoPrint 3D printer (status, temperatures, start/pause/resume/cancel jobs, print files) + paper printing via CUPS |
| **Computer Agent** | Live CPU/RAM/disk/battery stats, top processes, volume, open apps & websites, optional shell commands |
| **Data Agent** | Real-time weather + forecast (any city), date/time, news headlines, live crypto prices |

All four agents register their tools with **Atlas**, the Gemini-powered
orchestrator. Gemini decides which agent to call, chains calls when needed,
and answers back in natural speech.

## Quick start (server + phone)

```bash
./run.sh            # first run creates .venv and .env, then re-run
```

1. Put your keys in `.env` (only `GEMINI_API_KEY` is required — free at
   [aistudio.google.com/apikey](https://aistudio.google.com/apikey)).
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

The easiest safe option is [Tailscale](https://tailscale.com): install it on
the server and your phone, then open `http://<machine-name>:8000` from
anywhere. `tailscale serve 8000` also gives you HTTPS for phone mic access.

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
| `GEMINI_API_KEY` | The brain — required |
| `HA_URL`, `HA_TOKEN` | Home Assistant URL + long-lived access token |
| `OCTOPRINT_URL`, `OCTOPRINT_API_KEY` | 3D printer control |
| `CUPS_PRINTER` | Paper printer name (blank = system default) |
| `WEATHER_LAT`, `WEATHER_LON` | Default weather location |
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
