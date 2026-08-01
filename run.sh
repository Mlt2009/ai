#!/usr/bin/env bash
# Start the AI Companion server (web + phone access).
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo ">> Creating virtual environment…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo ">> Created .env — add your GEMINI_API_KEY (and Home Assistant / OctoPrint keys) then re-run."
  exit 0
fi

exec ./.venv/bin/python -m server.main
