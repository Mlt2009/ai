/* Atlas web client — real-time voice chat over WebSocket.
   Speech-to-text and text-to-speech run in the browser (Web Speech API),
   so the phone does the talking and the server does the thinking. */

const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");
const micBtn = document.getElementById("mic");
const orb = document.getElementById("orb");
const statusEl = document.getElementById("status");
const resetBtn = document.getElementById("reset");

let ws = null;
let listening = false;
let voiceMode = false; // after a voice turn, auto-listen again for hands-free flow

// ── WebSocket ─────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => setStatus("online — ready", true);
  ws.onclose = () => { setStatus("reconnecting…", false); setTimeout(connect, 2000); };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "tool") {
      addMsg("tool", `⚙ ${msg.name.replace("__", " → ")}`);
      setOrb("thinking");
    } else if (msg.type === "reply") {
      addMsg("bot", msg.text);
      speak(msg.text);
    } else if (msg.type === "turn_end") {
      if (!speechSynthesis.speaking) setOrb("");
    }
  };
}

function setStatus(text, live) {
  statusEl.textContent = text;
  statusEl.classList.toggle("live", !!live);
}

function setOrb(state) {
  orb.className = "orb" + (state ? " " + state : "");
}

// ── Chat UI ───────────────────────────────────────────────────────
function addMsg(kind, text) {
  const div = document.createElement("div");
  div.className = `msg ${kind}`;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function sendText(text) {
  text = text.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  addMsg("user", text);
  ws.send(JSON.stringify({ type: "user_text", text }));
  setOrb("thinking");
}

sendBtn.onclick = () => { sendText(input.value); input.value = ""; };
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") { sendText(input.value); input.value = ""; }
});
resetBtn.onclick = () => {
  ws && ws.send(JSON.stringify({ type: "reset" }));
  chat.innerHTML = "";
  voiceMode = false;
};

// ── Text-to-speech (browser voices) ───────────────────────────────
function speak(text) {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 1.05;
  const voices = speechSynthesis.getVoices();
  u.voice =
    voices.find((v) => /en[-_]/i.test(v.lang) && /natural|neural|premium|google/i.test(v.name)) ||
    voices.find((v) => /en[-_]/i.test(v.lang)) || null;
  u.onstart = () => setOrb("speaking");
  u.onend = () => {
    setOrb("");
    if (voiceMode) startListening(); // hands-free: listen again after replying
  };
  speechSynthesis.speak(u);
}
if ("speechSynthesis" in window) speechSynthesis.getVoices();

// ── Speech-to-text (browser recognition) ─────────────────────────
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null;

function startListening() {
  if (!SR) { addMsg("bot", "Voice input isn't supported in this browser — try Chrome, or just type."); return; }
  if (listening) return;
  rec = new SR();
  rec.lang = navigator.language || "en-US";
  rec.interimResults = true;
  listening = true;
  voiceMode = true;
  micBtn.classList.add("active");
  setOrb("listening");
  setStatus("listening…", true);

  let finalText = "";
  rec.onresult = (e) => {
    let interim = "";
    for (const r of e.results) (r.isFinal ? (finalText += r[0].transcript) : (interim += r[0].transcript));
    input.placeholder = interim || "listening…";
  };
  rec.onend = () => {
    listening = false;
    micBtn.classList.remove("active");
    input.placeholder = "Type or tap the mic…";
    setStatus("online — ready", true);
    if (finalText.trim()) sendText(finalText);
    else if (!speechSynthesis.speaking) setOrb("");
  };
  rec.onerror = () => { listening = false; voiceMode = false; micBtn.classList.remove("active"); setOrb(""); };
  rec.start();
}

micBtn.onclick = () => {
  if (listening) { voiceMode = false; rec && rec.stop(); }
  else startListening();
};

// ── Live dashboard tiles ──────────────────────────────────────────
async function refreshTiles() {
  try {
    const s = await (await fetch("/api/stats")).json();
    document.getElementById("t-cpu").textContent = s.cpu.toFixed(0) + "%";
    document.getElementById("t-mem").textContent = s.mem.toFixed(0) + "%";
    setTile("t-home", s.home_assistant);
    setTile("t-printer", s.octoprint);
  } catch {}
}
function setTile(id, ok) {
  const el = document.getElementById(id);
  el.textContent = ok ? "linked" : "off";
  el.className = "tile-value " + (ok ? "ok" : "off");
}
refreshTiles();
setInterval(refreshTiles, 5000);

// ── Settings panel: turn every agent on from your phone ──────────
const settingsEl = document.getElementById("settings");
const settingsMsg = document.getElementById("settings-msg");

function renderServices(services) {
  for (const [svc, s] of Object.entries(services || {})) {
    const box = document.querySelector(`.svc[data-svc="${svc}"]`);
    if (!box) continue;
    const dot = box.querySelector(".dot");
    dot.className = "dot " + (s.on ? "on" : "off");
    box.querySelector(".svc-detail").textContent = s.detail || "";
  }
  const anyOff = Object.values(services || {}).some((s) => !s.on);
  setStatus(anyOff ? "online — some agents off (⚙)" : "online — all agents live", true);
}

async function openSettings() {
  settingsEl.classList.remove("hidden");
  settingsMsg.textContent = "checking connections…";
  try {
    const { values, services } = await (await fetch("/api/settings")).json();
    for (const inp of settingsEl.querySelectorAll("[data-key]")) {
      const v = values[inp.dataset.key];
      if (inp.type === "checkbox") inp.checked = !!v;
      else if (v) inp.value = v;
    }
    renderServices(services);
    settingsMsg.textContent = "";
  } catch {
    settingsMsg.textContent = "couldn't load settings";
  }
}

async function saveSettings() {
  const payload = {};
  for (const inp of settingsEl.querySelectorAll("[data-key]")) {
    if (inp.type === "checkbox") payload[inp.dataset.key] = inp.checked;
    else if (inp.value.trim() && !inp.value.includes("••••"))
      payload[inp.dataset.key] = inp.value.trim();
  }
  settingsMsg.textContent = "saving & testing connections…";
  try {
    const res = await (await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })).json();
    renderServices(res.services);
    const on = Object.values(res.services).filter((s) => s.on).length;
    settingsMsg.textContent = `saved — ${on}/${Object.keys(res.services).length} services live`;
    refreshTiles();
  } catch {
    settingsMsg.textContent = "save failed — is the server reachable?";
  }
}

document.getElementById("settings-btn").onclick = openSettings;
document.getElementById("settings-close").onclick = () => settingsEl.classList.add("hidden");
document.getElementById("settings-save").onclick = saveSettings;
settingsEl.addEventListener("click", (e) => { if (e.target === settingsEl) settingsEl.classList.add("hidden"); });

// First run: if the brain is off, open settings automatically.
fetch("/api/stats").then((r) => r.json()).then((s) => { if (!s.gemini) openSettings(); }).catch(() => {});

// ── PWA ───────────────────────────────────────────────────────────
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");

connect();
addMsg("bot", "Hey, I'm Atlas — your AI companion. Tap the mic and talk to me, or type below. I can run your smart home, your printers, this computer, and pull live data for you.");
