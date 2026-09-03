/* Mehltani web client — real-time voice chat over WebSocket, the workspace
   grid (agents, AI companions, money, shopping), the style/taste dashboard,
   the security panel (WebAuthn fingerprint enrolment and confirmation), and
   one-tap receipt scanning. Speech-to-text and text-to-speech run in the
   browser (Web Speech API), so the phone does the talking and the server
   does the thinking. */

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
const TOKEN_KEY = "mehltani_token";
let token = localStorage.getItem(TOKEN_KEY) || localStorage.getItem("atlas_token") || "";

function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (token) headers["X-Mehltani-Token"] = token;
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

// ── Views: chat ⇄ workspace ⇄ style ⇄ security ─────────────────────
let currentView = "chat";
const workspaceEl = document.getElementById("workspace");
const styleEl = document.getElementById("style");
const securityEl = document.getElementById("security");
const VIEWS = { chat, workspace: workspaceEl, style: styleEl, security: securityEl };

for (const tab of document.querySelectorAll(".tab")) {
  tab.onclick = () => {
    currentView = tab.dataset.view;
    for (const other of document.querySelectorAll(".tab")) other.classList.toggle("active", other === tab);
    for (const [name, node] of Object.entries(VIEWS)) node.classList.toggle("hidden", currentView !== name);
    if (currentView === "workspace") loadWorkspace();
    if (currentView === "style") loadStyle();
    if (currentView === "security") loadSecurity();
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

  // Agents — one cell each; tapping one asks Mehltani to use it.
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

// ── Style: taste profile, scouting queue, lookbook ─────────────────
async function loadStyle() {
  let data;
  try { data = await apiJson("/api/style"); } catch { return; }

  document.getElementById("style-summary").textContent = data.summary || "Nothing learned yet.";
  const stats = data.stats || {};
  document.getElementById("style-stat").textContent = `${stats.verdicts || 0} verdicts`;

  const attrs = document.getElementById("style-attributes");
  attrs.innerHTML = "";
  const peak = Math.max(...(data.attributes || []).map((a) => Math.abs(a.score)), 1);
  for (const a of (data.attributes || []).slice(0, 20)) {
    const row = el("div", "bar-row");
    row.appendChild(el("span", "bar-label", a.attribute));
    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill" + (a.score < 0 ? " neg" : ""));
    fill.style.width = `${Math.round((Math.abs(a.score) / peak) * 100)}%`;
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("span", "bar-value", `${a.score > 0 ? "+" : ""}${a.score}`));
    attrs.appendChild(row);
  }
  if (!(data.attributes || []).length) attrs.appendChild(el("p", "hint", "Record a verdict on a look and it shows up here."));

  const looks = document.getElementById("style-looks");
  looks.innerHTML = "";
  for (const look of data.looks || []) {
    const row = el("div", "row");
    row.appendChild(el("span", "row-main", look.title));
    row.appendChild(el("span", "row-sub", look.status));
    looks.appendChild(row);
  }
  if (!(data.looks || []).length) looks.appendChild(el("p", "hint", "No saved looks yet."));

  let queue;
  try { queue = await apiJson("/api/style/scouted?state=new"); } catch { queue = { items: [] }; }
  const queueEl = document.getElementById("style-queue");
  queueEl.innerHTML = "";
  document.getElementById("style-queue-count").textContent = queue.count || 0;
  for (const item of queue.items || []) {
    const cell = el("button", "cell live");
    cell.appendChild(el("span", "cell-name", item.title));
    cell.appendChild(el("span", "cell-sub", item.price ? money(item.price) : "price on request"));
    cell.onclick = () => {
      document.querySelector('.tab[data-view="chat"]').click();
      input.value = `About scouted item #${item.id} (${item.title}): `;
      input.focus();
    };
    queueEl.appendChild(cell);
  }
  if (!(queue.items || []).length) queueEl.appendChild(el("p", "hint", "Nothing waiting on a verdict — ask me to scout something."));
}

// ── Security: posture, threats, audit, WebAuthn fingerprint ────────
//
// Two independent ceremonies live here — enrol and confirm — both driven by
// the browser's own navigator.credentials API. No amount of talking to
// Mehltani in chat can trigger or satisfy either one; that's what makes the
// gate real. See guardian.py's module docstring for the full reasoning.

function base64urlToBuffer(base64url) {
  const padded = base64url.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((base64url.length + 3) % 4);
  const raw = atob(padded);
  const buffer = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buffer[i] = raw.charCodeAt(i);
  return buffer.buffer;
}

function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function decodeCreationOptions(options) {
  return {
    ...options,
    challenge: base64urlToBuffer(options.challenge),
    user: { ...options.user, id: base64urlToBuffer(options.user.id) },
    excludeCredentials: (options.excludeCredentials || []).map((c) => ({ ...c, id: base64urlToBuffer(c.id) })),
  };
}

function decodeRequestOptions(options) {
  return {
    ...options,
    challenge: base64urlToBuffer(options.challenge),
    allowCredentials: (options.allowCredentials || []).map((c) => ({ ...c, id: base64urlToBuffer(c.id) })),
  };
}

function encodeAttestation(credential) {
  return {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment || undefined,
    response: {
      clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
      attestationObject: bufferToBase64url(credential.response.attestationObject),
    },
  };
}

function encodeAssertion(credential) {
  const response = {
    clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
    authenticatorData: bufferToBase64url(credential.response.authenticatorData),
    signature: bufferToBase64url(credential.response.signature),
  };
  if (credential.response.userHandle) response.userHandle = bufferToBase64url(credential.response.userHandle);
  return { id: credential.id, rawId: bufferToBase64url(credential.rawId), type: credential.type, response };
}

let presenceToken = "";
let presenceExpiresAt = 0;

async function enrolFingerprint() {
  const msg = document.getElementById("sec-enroll-msg");
  if (!("credentials" in navigator)) { msg.textContent = "This browser doesn't support WebAuthn — use Chrome, Safari or Edge."; return; }
  const label = document.getElementById("sec-device-label").value.trim() || "my device";

  // Adding a device beyond the first one needs confirmation from one already
  // enrolled — otherwise anyone reaching this page could plant a fingerprint
  // backdoor. Get that confirmation first so the new device only has to be
  // touched once. The very first-ever enrolment skips this — nothing exists
  // yet to confirm it with.
  const existing = await apiJson("/api/guardian/biometrics").catch(() => ({ enrolled: [] }));
  if ((existing.enrolled || []).length > 0 && !(presenceToken && Date.now() < presenceExpiresAt)) {
    msg.textContent = "Adding another device needs confirmation from one you already enrolled first.";
    const token = await confirmFingerprint("credential_add");
    if (!token) { msg.textContent = "Could not confirm — enrolment cancelled."; return; }
  }

  msg.textContent = "follow the prompt — Touch ID / Face ID / Windows Hello…";
  try {
    const begin = await apiJson("/api/guardian/register/begin", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ label }),
    });
    if (begin.error) { msg.textContent = begin.error; return; }
    const publicKey = decodeCreationOptions(begin.options);
    const credential = await navigator.credentials.create({ publicKey });
    const result = await apiJson("/api/guardian/register/finish", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        state: begin.state, credential: encodeAttestation(credential),
        presence_token: presenceToken,
      }),
    });
    if (result.error) { msg.textContent = result.error; return; }
    msg.textContent = `Enrolled "${result.label}" — ${result.total_enrolled} device(s) now protect Mehltani.`;
    document.getElementById("sec-device-label").value = "";
    loadSecurity();
  } catch (err) {
    msg.textContent = err.name === "NotAllowedError" ? "Cancelled or timed out." : `Failed: ${err.message}`;
  }
}

async function confirmFingerprint(op) {
  const msg = document.getElementById("sec-confirm-msg");
  if (!("credentials" in navigator)) { msg.textContent = "This browser doesn't support WebAuthn."; return null; }
  msg.textContent = "follow the prompt…";
  try {
    const begin = await apiJson("/api/guardian/verify/begin", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: op || "" }),
    });
    if (begin.error) { msg.textContent = begin.error; return null; }
    const publicKey = decodeRequestOptions(begin.options);
    const credential = await navigator.credentials.get({ publicKey });
    const result = await apiJson("/api/guardian/verify/finish", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: begin.state, op: op || "", credential: encodeAssertion(credential) }),
    });
    if (result.error) { msg.textContent = result.error; return null; }
    presenceToken = result.presence_token;
    presenceExpiresAt = Date.now() + result.expires_in * 1000;
    msg.textContent = `Confirmed with "${result.device}" — good for ${Math.round(result.expires_in / 60)} minutes.`;
    return presenceToken;
  } catch (err) {
    msg.textContent = err.name === "NotAllowedError" ? "Cancelled or timed out." : `Failed: ${err.message}`;
    return null;
  }
}

document.getElementById("sec-enroll").onclick = enrolFingerprint;
document.getElementById("sec-confirm").onclick = () => confirmFingerprint("");

document.getElementById("sec-scan").onclick = async () => {
  const posture = document.getElementById("sec-posture");
  posture.textContent = "scanning…";
  try {
    const result = await apiJson("/api/guardian/scan", { method: "POST" });
    posture.textContent = result.posture;
    posture.className = "badge " + (result.posture === "ok" ? "ok" : result.posture === "warn" ? "warn" : "bad");
    document.getElementById("sec-summary").textContent =
      `Integrity: ${typeof result.integrity === "string" ? result.integrity : result.integrity.length + " issue(s)"}. ` +
      `Exposure: ${typeof result.exposure === "string" ? result.exposure : result.exposure.length + " issue(s)"}.`;
    loadSecurity();
  } catch {
    posture.textContent = "scan failed";
  }
};

async function loadSecurity() {
  let status;
  try { status = await apiJson("/api/guardian/status"); } catch { return; }
  const posture = document.getElementById("sec-posture");
  posture.textContent = status.lockdown.on ? "LOCKED DOWN" : status.open_threats ? "attention" : "ok";
  posture.className = "badge " + (status.lockdown.on ? "bad" : status.open_threats ? "warn" : "ok");
  document.getElementById("sec-summary").textContent = status.lockdown.on
    ? `In lockdown: ${status.lockdown.reason}. Confirm your fingerprint to clear it.`
    : (status.gate_on
        ? `Fingerprint gate is on · ${status.enrolled_devices} device(s) enrolled · ${status.open_threats} open threat(s).`
        : "Fingerprint gate is off — protected actions run without confirmation.");

  const devicesData = await apiJson("/api/guardian/biometrics").catch(() => ({ enrolled: [] }));
  const devices = document.getElementById("sec-devices");
  devices.innerHTML = "";
  document.getElementById("sec-device-count").textContent = (devicesData.enrolled || []).length;
  for (const device of devicesData.enrolled || []) {
    const row = el("div", "row");
    row.appendChild(el("span", "row-main", device.label));
    row.appendChild(el("span", "row-sub", `enrolled ${device.created_at}`));
    const remove = el("button", "ghost", "remove");
    remove.onclick = async () => {
      await api(`/api/guardian/devices/${encodeURIComponent(device.id)}`, { method: "DELETE" });
      loadSecurity();
    };
    row.appendChild(remove);
    devices.appendChild(row);
  }
  if (!(devicesData.enrolled || []).length) devices.appendChild(el("p", "hint", "No fingerprint enrolled yet."));

  const threats = await apiJson("/api/guardian/threats?unresolved_only=true").catch(() => ({ threats: [] }));
  const threatsEl = document.getElementById("sec-threats");
  threatsEl.innerHTML = "";
  for (const t of threats.threats || []) {
    const row = el("div", "row");
    row.appendChild(el("span", "row-main", `[${t.severity}] ${t.kind}`));
    row.appendChild(el("span", "row-sub", t.summary));
    threatsEl.appendChild(row);
  }
  if (!(threats.threats || []).length) threatsEl.appendChild(el("p", "hint", "Nothing flagged."));

  const audit = await apiJson("/api/guardian/audit?limit=15").catch(() => ({ entries: [] }));
  const auditEl = document.getElementById("sec-audit");
  auditEl.innerHTML = "";
  for (const a of audit.entries || []) {
    const row = el("div", "row");
    row.appendChild(el("span", "row-main", `${a.allowed ? "✓" : "✗"} ${a.op}`));
    row.appendChild(el("span", "row-sub", a.reason || a.at));
    auditEl.appendChild(row);
  }
  if (!(audit.entries || []).length) auditEl.appendChild(el("p", "hint", "No protected actions attempted yet."));
}

// If the model asks for a fingerprint mid-conversation, a fresh presence
// token gets appended to the next thing the user says, so it reaches the
// tool call as a normal piece of context rather than a wire-protocol change.
const originalSendText = sendText;
sendText = function (text) {
  text = text.trim();
  if (!text) return;
  if (presenceToken && Date.now() < presenceExpiresAt) {
    text += ` (presence_token: ${presenceToken})`;
  }
  originalSendText(text);
};

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

addMsg("bot", "Hey, I'm Mehltani — your creative director for fashion, hair, makeup and styling. Tap the camera to scan a receipt, hit Style to see your taste profile, Workspace for the whole team, or just talk to me. I scout the web, run your inbox, message your WhatsApp, and rewrite my own code when I need a new skill.");
