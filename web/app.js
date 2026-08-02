/* Atlas web client — real-time voice chat over WebSocket, plus the workspace
   grid (agents, AI companions, money, shopping) and one-tap receipt scanning.
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

// ── Access token (only used when the server sets ACCESS_TOKEN) ─────
const TOKEN_KEY = "atlas_token";
let token = localStorage.getItem(TOKEN_KEY) || "";

function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (token) headers["X-Atlas-Token"] = token;
  return fetch(path, { ...options, headers });
}

async function apiJson(path, options) {
  const res = await api(path, options);
  if (res.status === 401) { showGate("That token wasn't accepted."); throw new Error("locked"); }
  return res.json();
}

const gateEl = document.getElementById("gate");
function showGate(message) {
  gateEl.classList.remove("hidden");
  document.getElementById("gate-msg").textContent = message || "";
}
document.getElementById("gate-unlock").onclick = async () => {
  const candidate = document.getElementById("gate-token").value.trim();
  const res = await fetch(`/api/auth?token=${encodeURIComponent(candidate)}`).then((r) => r.json());
  if (!res.ok) { document.getElementById("gate-msg").textContent = "Wrong token."; return; }
  token = candidate;
  localStorage.setItem(TOKEN_KEY, token);
  gateEl.classList.add("hidden");
  connect();
  refreshTiles();
};

// ── WebSocket ─────────────────────────────────────────────────────
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  ws = new WebSocket(`${proto}://${location.host}/ws${query}`);
  ws.onopen = () => setStatus("online — ready", true);
  ws.onclose = (e) => {
    if (e.code === 1008) { showGate("This server needs an access token."); return; }
    setStatus("reconnecting…", false);
    setTimeout(connect, 2000);
  };
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "tool") {
      addMsg("tool", `⚙ ${msg.name.replace("__", " → ")}`);
      setOrb("thinking");
    } else if (msg.type === "tool_result") {
      // A printed slip is worth showing verbatim, not just narrating.
      const slip = msg.result && (msg.result.slip || msg.result.list || msg.result.report);
      if (slip) showSlip(slip);
    } else if (msg.type === "reply") {
      addMsg("bot", msg.text);
      speak(msg.text);
    } else if (msg.type === "turn_end") {
      if (!speechSynthesis.speaking) setOrb("");
      if (currentView === "workspace") loadWorkspace();
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

// ── Views: chat ⇄ workspace ───────────────────────────────────────
let currentView = "chat";
const workspaceEl = document.getElementById("workspace");

for (const tab of document.querySelectorAll(".tab")) {
  tab.onclick = () => {
    currentView = tab.dataset.view;
    for (const other of document.querySelectorAll(".tab")) other.classList.toggle("active", other === tab);
    chat.classList.toggle("hidden", currentView !== "chat");
    workspaceEl.classList.toggle("hidden", currentView !== "workspace");
    if (currentView === "workspace") loadWorkspace();
  };
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function money(value) {
  return "$" + Number(value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

async function loadWorkspace() {
  let data;
  try { data = await apiJson("/api/workspace"); } catch { return; }

  // Agents — one cell each; tapping one asks Atlas to use it.
  const agents = document.getElementById("ws-agents");
  agents.innerHTML = "";
  document.getElementById("ws-agent-count").textContent = data.agents.length;
  for (const agent of data.agents) {
    const cell = el("button", "cell live");
    cell.appendChild(el("span", "cell-name", agent.name));
    cell.appendChild(el("span", "cell-sub", `${agent.tools.length} tools`));
    cell.title = agent.description;
    cell.onclick = () => {
      document.querySelector('.tab[data-view="chat"]').click();
      input.value = `Use the ${agent.name} agent to `;
      input.focus();
    };
    agents.appendChild(cell);
  }

  // AI companions — every brain you can broadcast to.
  const companions = document.getElementById("ws-companions");
  companions.innerHTML = "";
  document.getElementById("ws-companion-count").textContent = data.companions.length;
  if (!data.companions.length) {
    companions.appendChild(el("p", "hint", "No companions yet — add Claude / ChatGPT / OpenRouter keys in Settings ⚙"));
  }
  for (const companion of data.companions) {
    const cell = el("button", "cell live");
    cell.appendChild(el("span", "cell-name", companion.name));
    cell.appendChild(el("span", "cell-sub", companion.model));
    cell.onclick = () => {
      document.getElementById("broadcast-input").focus();
    };
    companions.appendChild(cell);
  }

  // Money this month.
  document.getElementById("ws-total").textContent = money(data.month.total);
  const bars = document.getElementById("ws-spend");
  bars.innerHTML = "";
  const peak = Math.max(...data.month.by_category.map((g) => g.total || 0), 1);
  for (const group of data.month.by_category) {
    const row = el("div", "bar-row");
    row.appendChild(el("span", "bar-label", group.group_key || "other"));
    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    fill.style.width = `${Math.round(((group.total || 0) / peak) * 100)}%`;
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("span", "bar-value", money(group.total)));
    bars.appendChild(row);
  }

  // Recent receipts.
  const recent = document.getElementById("ws-recent");
  recent.innerHTML = "";
  for (const receipt of data.recent) {
    const row = el("div", "row");
    row.appendChild(el("span", "row-main", receipt.merchant || "(no merchant)"));
    row.appendChild(el("span", "row-sub", receipt.date));
    row.appendChild(el("span", "row-amount", money(receipt.total)));
    recent.appendChild(row);
  }
  if (!data.recent.length) recent.appendChild(el("p", "hint", "No expenses yet — scan a receipt above."));

  // Money owed to you, overdue first.
  const owed = data.outstanding || { count: 0, total: 0, invoices: [] };
  document.getElementById("ws-owed").textContent =
    owed.count ? money(owed.total) : "all paid";
  const invoices = document.getElementById("ws-invoices");
  invoices.innerHTML = "";
  for (const invoice of owed.invoices.slice(0, 8)) {
    const row = el("div", "row");
    row.appendChild(el("span", "row-main", `${invoice.number}  ${invoice.customer}`));
    row.appendChild(el("span", "row-sub", invoice.overdue ? "OVERDUE" : (invoice.due_on || "")));
    row.appendChild(el("span", "row-amount", money(invoice.total)));
    if (invoice.overdue) row.style.borderLeft = "3px solid #ff7d7d";
    invoices.appendChild(row);
  }
  if (!owed.count) invoices.appendChild(el("p", "hint", "Nothing outstanding — every invoice is paid."));

  // Schedule + mileage this year.
  const mileage = data.mileage || { miles: 0, deduction: 0 };
  document.getElementById("ws-miles").textContent =
    `${mileage.miles.toLocaleString()} mi · ${money(mileage.deduction)}`;
  const schedule = document.getElementById("ws-schedule");
  schedule.innerHTML = "";
  for (const job of data.schedule || []) {
    const [day, clock] = String(job.starts_at).split("T");
    const row = el("div", "row");
    row.appendChild(el("span", "row-main", job.title));
    row.appendChild(el("span", "row-sub", `${day} ${clock || ""}`.trim()));
    schedule.appendChild(row);
  }
  if (!(data.schedule || []).length) schedule.appendChild(el("p", "hint", "Nothing scheduled — say \u201cbook a drain clear tomorrow at 9\u201d."));

  // Shopping list.
  const shopping = document.getElementById("ws-shopping");
  shopping.innerHTML = "";
  for (const item of data.shopping) {
    const row = el("div", "row");
    row.appendChild(el("span", "row-main", `${item.qty} × ${item.name}`));
    row.appendChild(el("span", "row-sub", item.store || "anywhere"));
    shopping.appendChild(row);
  }
  if (!data.shopping.length) shopping.appendChild(el("p", "hint", "List is empty — say “add milk to the shopping list”."));
}

// ── Camera → scan → layout → print ────────────────────────────────
const cameraInput = document.getElementById("camera");
const slipEl = document.getElementById("slip");

function showSlip(text) {
  slipEl.textContent = text;
  slipEl.classList.remove("hidden");
}

document.getElementById("camera-btn").onclick = () => cameraInput.click();

cameraInput.onchange = async () => {
  const file = cameraInput.files && cameraInput.files[0];
  if (!file) return;
  cameraInput.value = "";
  const wantsPrint = document.getElementById("scan-print").checked;
  setStatus("uploading photo…", true);
  showSlip("reading the photo…");

  try {
    const body = new FormData();
    body.append("photo", file, file.name || "shot.jpg");
    const uploaded = await apiJson("/api/upload", { method: "POST", body });
    if (uploaded.error) { showSlip(uploaded.error); return; }

    setStatus("scanning…", true);
    const result = await apiJson("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_id: uploaded.image_id, print: wantsPrint }),
    });

    if (result.error) { showSlip(result.error); return; }
    showSlip(result.slip || "(scanned, but no slip was produced)");
    const printed = result.printed;
    const suffix = printed ? (printed.ok ? " · sent to the printer" : ` · print failed: ${printed.error}`) : "";
    addMsg("bot", `Scanned ${result.merchant || "that receipt"} for ${money(result.total)}${suffix}.`);
    loadWorkspace();
  } catch (err) {
    showSlip(`Something went wrong: ${err.message}`);
  } finally {
    setStatus("online — ready", true);
  }
};

// ── Broadcast to every AI companion at once ───────────────────────
const broadcastInput = document.getElementById("broadcast-input");
const broadcastResults = document.getElementById("broadcast-results");

async function runBroadcast() {
  const prompt = broadcastInput.value.trim();
  if (!prompt) return;
  broadcastResults.innerHTML = "";
  broadcastResults.appendChild(el("p", "hint", "asking every companion…"));
  try {
    const data = await apiJson("/api/broadcast", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    broadcastResults.innerHTML = "";
    if (!data.results || !data.results.length) {
      broadcastResults.appendChild(el("p", "hint", "No companions configured yet — add keys in Settings ⚙"));
      return;
    }
    for (const result of data.results) {
      const box = el("div", "answer" + (result.ok ? "" : " failed"));
      box.appendChild(el("div", "answer-head", `${result.companion} · ${result.model}`));
      box.appendChild(el("div", "", result.ok ? result.answer : result.error));
      broadcastResults.appendChild(box);
    }
  } catch {
    broadcastResults.innerHTML = "";
    broadcastResults.appendChild(el("p", "hint", "Broadcast failed — is the server reachable?"));
  }
}

document.getElementById("broadcast-send").onclick = runBroadcast;
broadcastInput.addEventListener("keydown", (e) => { if (e.key === "Enter") runBroadcast(); });

// ── Live dashboard tiles ──────────────────────────────────────────
async function refreshTiles() {
  try {
    const s = await (await api("/api/stats")).json();
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
    const { values, services } = await apiJson("/api/settings");
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
    const res = await apiJson("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    renderServices(res.services);
    const on = Object.values(res.services).filter((s) => s.on).length;
    settingsMsg.textContent = `saved — ${on}/${Object.keys(res.services).length} services live`;
    // Setting a token from here locks this device out until it is stored.
    if (payload.ACCESS_TOKEN) {
      token = payload.ACCESS_TOKEN;
      localStorage.setItem(TOKEN_KEY, token);
    }
    refreshTiles();
  } catch {
    settingsMsg.textContent = "save failed — is the server reachable?";
  }
}

document.getElementById("settings-btn").onclick = openSettings;
document.getElementById("settings-close").onclick = () => settingsEl.classList.add("hidden");
document.getElementById("settings-save").onclick = saveSettings;
settingsEl.addEventListener("click", (e) => { if (e.target === settingsEl) settingsEl.classList.add("hidden"); });

// First run: unlock if needed, then open settings if the brain is off.
fetch(`/api/auth?token=${encodeURIComponent(token)}`)
  .then((r) => r.json())
  .then((auth) => {
    if (auth.required && !auth.ok) { showGate(); return; }
    connect();
    api("/api/stats").then((r) => r.json()).then((s) => { if (!s.gemini) openSettings(); }).catch(() => {});
  })
  .catch(() => connect());

// ── PWA ───────────────────────────────────────────────────────────
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");

addMsg("bot", "Hey, I'm Atlas — your shopping and finance companion. Tap the camera to scan a receipt, hit Workspace to see the whole team, or just talk to me. I run your printers, your files, this computer, and every other AI you've plugged in.");
