// serve/web/app.js - the AryaInfer web app: Chat, Monitor, About. No framework, no network beyond this server.
// The Monitor tab rebuilds PR #22's dashboard idea (code-martin) on the server's own /metrics.
"use strict";

const $ = (id) => document.getElementById(id);
const SPRITE = "web/sprite.svg";
const icon = (name, cls = "st-icon") => `<svg class="${cls}" aria-hidden="true"><use href="${SPRITE}#i-${name}"/></svg>`;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmt = (n, d = 0) => (n == null || Number.isNaN(n) ? "–" : Number(n).toLocaleString(undefined, {maximumFractionDigits: d, minimumFractionDigits: d}));
const kfmt = (n) => (n == null ? "–" : n >= 1000 ? `${fmt(n / 1000, n >= 10000 ? 0 : 1)}k` : fmt(n));
// a context size: 32768 -> "32K" (powers of two), else like kfmt
const ctxfmt = (n) => (n && n % 1024 === 0 ? `${fmt(n / 1024)}K` : kfmt(n));
const gb = (b, d = 1) => (b == null ? "–" : fmt(b / 1073741824, d));   // memory: binary GB, as Windows shows it

const store = {
  get(k, d) { try { const v = localStorage.getItem("strata." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("strata." + k, JSON.stringify(v)); } catch (e) { /* private mode: in memory only */ } },
};

// ------------------------------------------------------------------ toasts
function toast(kind, title, text = "", ms = 3500, action = null) {
  const names = {info: "info", success: "check", warn: "warning", error: "error"};
  const el = document.createElement("div");
  el.className = `st-toast st-toast--${kind}`;
  el.innerHTML = `${icon(names[kind] || "info")}<div><div class="st-toast__title"></div><div class="t-text"></div></div>`;
  el.querySelector(".st-toast__title").textContent = title;
  el.querySelector(".t-text").textContent = text;
  if (action) {
    const b = document.createElement("button");
    b.className = "st-btn st-btn--secondary";
    b.style.height = "32px";
    b.style.marginLeft = "auto";
    b.textContent = action.label;
    b.onclick = () => { action.run(); el.remove(); };
    el.appendChild(b);
  }
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), ms);
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {                                   // http on another host: no async clipboard
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  if (btn) {
    const use = btn.querySelector("use");
    use.setAttribute("href", `${SPRITE}#i-check`);
    setTimeout(() => use.setAttribute("href", `${SPRITE}#i-copy`), 1500);
  }
  toast("success", "Copied to clipboard", "", 1800);
}

// ------------------------------------------------------------------ theme
// "system" is the default and is never written: the stored value is only a choice the user made.
function savedTheme() { try { return localStorage.getItem("strata.theme"); } catch (e) { return null; } }
function resolveTheme(mode) { return mode === "dark" || mode === "light" ? mode : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); }
function setTheme(mode, save) {
  const choice = ["system", "light", "dark"].includes(mode) ? mode : "system";
  const shown = resolveTheme(choice);
  document.documentElement.dataset.theme = shown;
  if (save) try {
    if (choice === "system") localStorage.removeItem("strata.theme");
    else localStorage.setItem("strata.theme", choice);
  } catch (e) { /* ignore */ }
  $("theme-icon").setAttribute("href", `${SPRITE}#i-${shown === "dark" ? "sun" : "moon"}`);
  for (const b of $("theme-seg").children) b.setAttribute("aria-checked", String(b.dataset.v === choice));
}
const flipTheme = () => setTheme(resolveTheme(savedTheme()) === "dark" ? "light" : "dark", true);
$("theme-btn").onclick = flipTheme;
for (const b of $("theme-seg").children) b.onclick = () => setTheme(b.dataset.v, true);

// ---------------------------------------------------------------- the device this page is on
// A phone is not a small desktop: taps need bigger boxes, nothing may depend on hover, and the layout has to know
// which one it is drawing. `data-device` is that fact, on <html>: coarse pointer or a narrow window means mobile, and
// Settings can override it (a tablet with a keyboard, or a desktop window someone wants compact).
const DEVICE = {coarse: matchMedia("(pointer: coarse)"), narrow: matchMedia("(max-width: 900px)")};
function deviceChoice() { try { return localStorage.getItem("strata.device") || "auto"; } catch (e) { return "auto"; } }
function applyDevice() {
  const choice = ["auto", "desktop", "mobile"].includes(deviceChoice()) ? deviceChoice() : "auto";
  const mobile = choice === "auto" ? (DEVICE.coarse.matches || DEVICE.narrow.matches) : choice === "mobile";
  const root = document.documentElement;
  root.dataset.device = mobile ? "mobile" : "desktop";
  root.dataset.pointer = DEVICE.coarse.matches ? "coarse" : "fine";
  const seg = $("device-seg");
  if (seg) for (const b of seg.children) b.setAttribute("aria-checked", String(b.dataset.v === choice));
}
function setDevice(choice, save) {
  if (save) try {
    if (choice === "auto") localStorage.removeItem("strata.device");
    else localStorage.setItem("strata.device", choice);
  } catch (e) { /* private mode: this session only */ }
  applyDevice();
addEventListener("focusin", (e) => {
  if (document.documentElement.dataset.device !== "mobile") return;
  if (!e.target.matches("input, textarea")) return;
  setTimeout(() => e.target.scrollIntoView({block: "nearest"}), 260);   // after the keyboard has moved
});
}
DEVICE.coarse.addEventListener("change", applyDevice);
DEVICE.narrow.addEventListener("change", applyDevice);
for (const b of $("device-seg").children) b.onclick = () => setDevice(b.dataset.v, true);
applyDevice();
setTheme(savedTheme() || "system", false);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!savedTheme()) setTheme("system", false);
});

// ------------------------------------------------------------------ views, sidebar, overlays
const VIEWS = ["chat", "images", "monitor", "models", "engines", "config", "about"];
const VIEW_TITLES = {chat: "Chat", images: "Images", monitor: "Monitor", models: "Models", engines: "Engines",
                     config: "Settings", about: "About"};
let tab = "chat";
function showTab(name) {
  tab = VIEWS.includes(name) ? name : "chat";
  for (const b of document.querySelectorAll(".st-nav[data-tab]"))
    b.setAttribute("aria-current", b.dataset.tab === tab ? "page" : "false");
  for (const v of VIEWS) $(`view-${v}`).hidden = v !== tab;
  $("view-title").textContent = VIEW_TITLES[tab];
  if (tab === "images") {
    if (typeof roomFocus === "function") { roomFocus(); if (typeof roomRender === "function") roomRender(); }
    else $("img-prompt").focus();
  }
  if (location.hash.slice(1) !== tab) history.replaceState(null, "", tab === "chat" ? location.pathname : `#${tab}`);
  if (tab === "chat") $("input").focus();
  if (tab === "monitor") loadMcp();
  if (tab === "models") loadModelsView();
  if (tab === "engines") loadEngines();
  if (tab === "config" && !cfgView) openConfigPage(null);
  if (lastMetrics) render(lastMetrics);
  closeSidebar();
  closeSettings();
}
for (const b of document.querySelectorAll(".st-nav[data-tab]")) b.onclick = () => showTab(b.dataset.tab);
window.addEventListener("hashchange", () => showTab(location.hash.slice(1)));

// One scrim, one stack: the sampling drawer, the settings popover and the narrow sidebar share it, and Escape
// closes whatever was opened last.
const overlayStack = [];
const overlayClose = {drawer: () => openDrawer(false), settings: () => closeSettings(), sidebar: () => closeSidebar()};
function syncScrim() { $("scrim").hidden = overlayStack.length === 0; }
function openOverlay(name) {
  const at = overlayStack.indexOf(name);
  if (at >= 0) overlayStack.splice(at, 1);
  overlayStack.push(name);
  syncScrim();
}
function closeOverlay(name) {
  const at = overlayStack.indexOf(name);
  if (at >= 0) overlayStack.splice(at, 1);
  syncScrim();
}
function closeTopOverlay() {
  const name = overlayStack[overlayStack.length - 1];
  if (name && overlayClose[name]) overlayClose[name]();
  return Boolean(name);
}

// The sidebar: collapsed on a wide window, an overlay drawer below 900px. Both are remembered in this browser.
const NARROW = matchMedia("(max-width: 900px)");
function setSidebar(collapsed, save) {
  document.querySelector(".app").dataset.collapsed = String(collapsed);
  $("sidebar").dataset.collapsed = String(collapsed);
  $("sidebar-collapse").setAttribute("aria-label", collapsed ? "Expand the sidebar" : "Collapse the sidebar");
  $("sidebar-collapse").title = collapsed ? "Expand" : "Collapse";
  if (save) store.set("sidebar", collapsed);
}
function openSidebar(open) {
  const shown = NARROW.matches && open;
  document.querySelector(".app").dataset.sidebarOpen = String(shown);
  $("sidebar-toggle").setAttribute("aria-expanded", String(shown));
  if (shown) openOverlay("sidebar");
  else closeOverlay("sidebar");
}
function closeSidebar() { openSidebar(false); }
function syncNarrow() {
  $("sidebar-toggle").hidden = !NARROW.matches;
  if (!NARROW.matches) closeSidebar();
}
$("sidebar-collapse").onclick = () => setSidebar(document.querySelector(".app").dataset.collapsed !== "true", true);
$("sidebar-toggle").onclick = () => openSidebar(document.querySelector(".app").dataset.sidebarOpen !== "true");
setSidebar(store.get("sidebar", false) === true, false);
syncNarrow();
NARROW.addEventListener("change", syncNarrow);

// A popover anchored to its trigger; on a narrow window the CSS puts it across the top instead.
function placePopover(el, anchor) {
  if (NARROW.matches || !anchor) { el.removeAttribute("style"); return; }
  const r = anchor.getBoundingClientRect();
  const left = Math.min(r.right + 10, innerWidth - el.offsetWidth - 12);
  el.style.left = `${Math.max(12, left)}px`;
  el.style.bottom = `${Math.max(12, innerHeight - r.bottom)}px`;
}
function settingsOpen() { return !$("settings-pop").hidden; }
function openSettings(open) {
  $("settings-pop").hidden = !open;
  $("settings-btn").setAttribute("aria-expanded", String(open));
  if (!open) { closeOverlay("settings"); return; }
  closeModelMenu();
  loadMcp();                                       // the Tools rows: how many servers, and their state
  loadSearch();
  openOverlay("settings");
  placePopover($("settings-pop"), $("settings-btn"));
}
function closeSettings() { if (settingsOpen()) openSettings(false); }
$("settings-btn").onclick = () => openSettings(!settingsOpen());
$("settings-close").onclick = () => openSettings(false);
$("about-link").onclick = () => { openSettings(false); showTab("about"); };

// ------------------------------------------------------------------ server access
function headers(json = false) {
  const h = {};
  const key = store.get("apikey", "");
  if (key) h.Authorization = "Bearer " + key;
  if (json) h["Content-Type"] = "application/json";
  return h;
}
$("api-key").value = store.get("apikey", "");
$("api-key").onchange = () => { store.set("apikey", $("api-key").value.trim()); toast("success", "API key saved", "Kept in this browser only."); };

let health = {model: "strata", images: false, max_context: 0};
let healthShown = false;
async function loadHealth() {
  try {
    health = await (await fetch("health")).json();
    $("attach-btn").title = health.images ? "Attach a text file or a picture (or drop it here)"
                                          : "Attach a text file (or drop it here)";
    $("chat-empty-sub").textContent = `${health.model} runs on this PC. Nothing leaves it.`;
    $("nav-images").hidden = !(health.image_generation || (health.comfyui && health.comfyui.configured));
    // the deep link is honoured once, on the first answer: a later retry must not move the view the user is on
    if (!healthShown) {
      healthShown = true;
      if (location.hash === "#images" && !$("nav-images").hidden) showTab("images");
    }
    renderToolPills();
  } catch (e) {
    setTimeout(loadHealth, 2000);
  }
}

// The installed models (GET api/models). The picker sits in the composer, and the sidebar's Models row opens the same
// menu. Choosing one switches the server to it, which stops the model in memory first and starts a new chat.
function modelLabel(m) { return m.display_name && m.display_name !== m.id ? `${m.display_name} (${m.id})` : m.id; }
async function loadModels() {
  const sel = $("model-select");
  let models = [];
  try {
    const r = await fetch("api/models", {headers: headers()});
    if (r.ok) models = (await r.json()).models || [];
  } catch (e) { return; }
  const current = models.find((m) => m.current);
  sel.innerHTML = models.map((m) =>
    `<option value="${esc(m.id)}"${m.current ? " selected" : ""}${m.status === "unavailable" ? " disabled" : ""}>` +
    `${esc(modelLabel(m))}${m.status === "unavailable" ? " - unavailable" : ""}</option>`).join("");
  sel.hidden = true;                                 // the chip (and the menu) is what the page shows; this keeps the state
  sel.dataset.current = (current || {}).id || "";
  $("model-btn-name").textContent = current ? (current.display_name || current.id) : "Model";
  $("model-btn").hidden = models.length < 2;
  $("models-nav-sub").textContent = current ? (current.display_name || current.id) : `${models.length} models`;
  $("model-menu").innerHTML = models.map((m) =>
    `<button class="st-menu__item" role="menuitemradio" aria-checked="${m.current ? "true" : "false"}"` +
    ` data-model="${esc(m.id)}"${m.status === "unavailable" ? " disabled" : ""}>` +
    `${icon("check", m.current ? "st-icon st-icon--sm" : "st-icon st-icon--sm invisible-ink")}` +
    `<span>${esc(modelLabel(m))}</span>` +
    `${m.status === "unavailable" ? `<span class="st-menu__note">unavailable</span>` : ""}</button>`).join("");
}
function closeModelMenu() {
  $("model-menu").hidden = true;
  $("model-btn").setAttribute("aria-expanded", "false");
}
function openModelMenu(anchor) {
  const wasOpen = !$("model-menu").hidden;
  closeModelMenu();
  if (wasOpen && anchor === $("model-btn")) return;
  $("model-menu").hidden = false;
  $("model-btn").setAttribute("aria-expanded", String(anchor === $("model-btn")));
  placePopover($("model-menu"), anchor);
}
$("model-btn").onclick = () => openModelMenu($("model-btn"));
$("models-nav").onclick = () => { closeSidebar(); openModelMenu($("models-nav")); };
$("model-menu").onclick = (e) => {
  const b = e.target.closest("[data-model]");
  if (!b || b.disabled) return;
  $("model-select").value = b.dataset.model;
  closeModelMenu();
  switchModel(b.dataset.model);
};
$("model-select").onchange = () => switchModel($("model-select").value);

async function switchModel(name) {
  const sel = $("model-select"), before = sel.dataset.current;
  if (!name || name === before) return;
  if (busy) { toast("warn", "Still writing", "Stop the answer first."); sel.value = before; return; }
  sel.disabled = true;
  $("model-btn").disabled = true;
  toast("info", `Switching to ${name}`, "The model in memory is stopped first, then this one is loaded.", 8000);
  let message = "";
  try {
    const r = await fetch("api/models/load", {method: "POST", headers: headers(true), body: JSON.stringify({model: name})});
    if (!r.ok) message = ((await r.json()).error || {}).message || `the server answered ${r.status}`;
  } catch (e) { message = String(e); }
  sel.disabled = false;
  $("model-btn").disabled = false;
  await loadHealth();
  await loadModels();
  if (tab === "models") loadModelsView();
  if (message) { toast("error", "The model was not switched", message, 10000); return; }
  newChat();                                   // the other model answers from a fresh chat, as before
  toast("success", `${name} is loaded`, "A new chat was started.");
}

// ------------------------------------------------------------------ Monitor
const METRICS = [
  {key: "speed", label: "Speed", icon: "gauge", unit: "t/s", series: "tok_s"},
  {key: "gpu", label: "GPU load", icon: "gpu", unit: "%", series: "gpu_util", max: 100},
  {key: "vram", label: "VRAM", icon: "layers", unit: "GB", series: "gpu_mem_used"},
  {key: "temp", label: "GPU temp", icon: "thermometer", unit: "°C", series: "gpu_temp", tone: "warn"},
  {key: "power", label: "Power", icon: "bolt", unit: "W", series: "gpu_power"},
  {key: "pcie", label: "PCIe", icon: "link", unit: "", series: "gpu_pcie_rx_mb", tone: "info"},
  {key: "cpu", label: "CPU", icon: "cpu", unit: "%", series: "cpu", max: 100},
  {key: "disk", label: "Disk read", icon: "disk", unit: "MB/s", series: "disk_read_mb", tone: "info"},
];
$("metrics").innerHTML = METRICS.map((m) => `
  <div class="st-card metric-card"><div class="st-metric">
    <span class="st-metric__label">${icon(m.icon, "st-icon st-icon--sm")}${esc(m.label)}</span>
    ${m.key === "speed" ? `<div class="speed-values">
      <div><span class="st-metric__value" id="mv-speed">-</span><span class="st-metric__sub" id="ms-speed">Decode</span></div>
      <div class="speed-prefill"><span class="st-metric__value" id="mv-prefill">-</span><span class="st-metric__sub" id="ms-prefill">Prefill</span></div>
    </div>` : `<span class="st-metric__value" id="mv-${m.key}">–</span>
    <span class="st-metric__sub" id="ms-${m.key}"></span>`}
    <svg class="st-metric__spark" id="sp-${m.key}" viewBox="0 0 100 32" preserveAspectRatio="none"${m.tone ? ` data-tone="${m.tone}"` : ""}>
      <path class="area" fill="currentColor" opacity=".12"/><path class="line" fill="none" stroke="currentColor"
      stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
      ${m.key === "speed" ? `<g id="sp-prefill" class="speed-prefill"><path class="area" fill="currentColor" opacity=".12"/>
        <path class="line" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"
        stroke-linecap="round" vector-effect="non-scaling-stroke"/></g>` : ""}</svg>
  </div></div>`).join("");

function spark(id, values, max) {
  const svg = $(id);
  const v = (values || []).map((x) => (x == null ? 0 : x));
  if (v.length < 2) { svg.querySelector(".line").setAttribute("d", ""); svg.querySelector(".area").setAttribute("d", ""); return; }
  const top = Math.max(max || 0, ...v, 1);
  const pts = v.map((x, i) => [(i / (v.length - 1)) * 100, 30 - (x / top) * 26]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join("");
  svg.querySelector(".line").setAttribute("d", line);
  svg.querySelector(".area").setAttribute("d", `${line}L100,32L0,32Z`);
}
function setMetric(key, value, unit, sub) {
  $(`mv-${key}`).innerHTML = value == null ? "–" : `${esc(value)}${unit ? `<small>${esc(unit)}</small>` : ""}`;
  $(`ms-${key}`).textContent = sub || "";
}

let lastMetrics = null, metricsFailures = 0, keyWarned = false, mcpTick = 0;
let reqShowAll = false;   // the Monitor's request table: the last 12, or every one the server keeps (issue #35)
async function poll() {
  try {
    const r = await fetch(reqShowAll ? "metrics?requests=all" : "metrics", {headers: headers()});
    if (r.status === 401) {
      setPill("error", "API key needed");
      if (!keyWarned) { keyWarned = true; toast("warn", "API key needed", "This server needs a key: add it under About > Settings.", 6000); }
    } else if (r.ok) {
      lastMetrics = await r.json();
      metricsFailures = 0;
      render(lastMetrics);
    } else {
      throw new Error(`HTTP ${r.status}`);
    }
  } catch (e) {
    if (++metricsFailures === 3) setPill("error", "Server not reachable");
  }
  if (tab === "monitor" && ++mcpTick % 10 === 0) loadMcp();       // server states change rarely: every 10 s
  renderChats();                                                  // the list's "3m" ages once a minute; a no-op otherwise
  setTimeout(poll, 1000);
}

// Companion (the Arya mascot from the brand kit): a corner figure in the chat and a badge on the Monitor
// state card. The src swaps to the kit's animated WebP per state, and to the supplied reduced-motion PNG
// under prefers-reduced-motion. Files are flat under /web/ (companion-<state>.webp).
const COMPANION_BY_PILL = {idle: "idle", reading: "researching", generating: "writing", queued: "waiting", error: "error"};
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let companionFlash = null;
function setCompanion(state) {
  for (const el of [$("header-companion"), $("monitor-companion")]) {
    if (!el || el.dataset.state === state) continue;
    el.dataset.state = state;
    el.src = `web/companion-${state}${reducedMotion.matches ? "-reduced.png" : ".webp"}`;
  }
}
function flashCompanionSuccess() {   // celebrate the finished answer, then back to what the pill says
  clearTimeout(companionFlash);
  setCompanion("success-celebrating");
  companionFlash = setTimeout(() => setCompanion(COMPANION_BY_PILL[pillState()] || "idle"), 2200);
}
function pillState() { return $("pill").dataset.state; }

function setPill(state, text) {
  $("pill").dataset.state = state === "error" ? "queued" : state;
  $("pill-text").textContent = text;
  setCompanion(COMPANION_BY_PILL[state] || "idle");
}

// The phone hides the header pill's words for room, so its speed lives in the footer: one chip, shown while the model
// is writing, with the same live rate the header reads.
function renderTps(live) {
  const chip = $("foot-tps");
  if (!chip) return;
  const rate = live.state === "generating" ? live.tok_s : null;
  if (rate > 0) {
    $("foot-tps-text").textContent = `${fmt(rate, 1)} tok/s`;
    chip.hidden = false;
  } else {
    chip.hidden = true;
  }
}

function render(m) {
  const live = m.live || {}, hw = m.hardware || {}, st = m.hardware_static || {}, eng = m.engine || {}, h = m.history || {};
  const last = (m.requests || [])[0];
  // the header pill
  if (live.state === "reading") {
    const pct = live.prompt_total ? Math.round((100 * live.prompt_read) / live.prompt_total) : null;
    setPill("reading", pct != null ? `Reading prompt · ${pct}%` : "Reading prompt");
  } else if (live.state === "generating") {
    setPill("generating", `Generating · ${fmt(live.tok_s, 1)} tok/s`);
  } else {
    setPill("idle", "Idle");
  }
  if (live.queued > 0) setPill("queued", `${live.queued} queued`);
  renderTps(live);
  if (tab === "monitor") renderMonitor(live, hw, st, eng, h, last, m.requests || [], m.totals, m.requests_kept);
  if (tab === "monitor") renderConvCache(m.conversation_cache);
  if (tab === "about") renderAbout(eng, hw, st);
}

// #596: the conversation cache - the prompt's state the engine keeps between requests (always), and the whole
// conversations it parks in RAM when "--conversation-cache-mib N" is in the run config's args (opt-in)
function since(t) {
  if (!t) return "";
  const s = Math.max(0, Date.now() / 1000 - t);
  return s < 60 ? "just now" : s < 3600 ? `${fmt(s / 60)} min ago` : `${fmt(s / 3600, 1)} h ago`;
}
function renderConvCache(c) {
  $("cc-card").hidden = !c;
  if (!c) return;                                  // an older server
  const pct = (a, b) => (b ? `${Math.min(100, (100 * a) / b)}%` : "0%");
  $("cc-bars").hidden = !c.enabled;
  if (c.enabled) {
    $("cc-slots-text").textContent = `${fmt(c.parked)} / ${fmt(c.slots)}`;
    $("cc-slots-bar").style.width = pct(c.parked, c.slots);
    const budget = c.budget_mib * 1048576;
    $("cc-mem-text").textContent = `${gb(c.bytes)} / ${gb(budget)} GB`;
    $("cc-mem-bar").style.width = pct(c.bytes, budget);
  }
  $("cc-sum").textContent = c.requests ? `${fmt(c.requests_reused)} of ${fmt(c.requests)} requests reused part of their prompt` : "";
  const share = c.prompt_tokens ? ` (${fmt((100 * c.reused_tokens) / c.prompt_tokens)}% of all prompt tokens)` : "";
  const event = c.last_event ? `${c.last_event === "parked" ? "Parked" : "Restored"} ${fmt(c.last_tokens)} tokens, ${since(c.last_at)}` : null;
  facts($("cc-facts"), [
    ["Last request", c.last_prompt != null ? `${fmt(c.last_reused || 0)} of ${fmt(c.last_prompt)} prompt tokens reused` : null],
    ["Reused since start", c.requests ? `${fmt(c.reused_tokens)} tokens${share}` : null],
    ["Parked / restored", c.enabled ? `${fmt(c.parks)} / ${fmt(c.restores)}${c.evictions ? ` · ${fmt(c.evictions)} evicted` : ""}` : null],
    ["Last switch", c.enabled ? event : null],
  ]);
  $("cc-note").textContent = c.enabled
    ? "A request that continues a parked conversation gets its state back instead of reading it again; the oldest goes when the slots or the memory are full."
    : "The engine keeps the last conversation's state, so a follow-up reads only what is new. To keep several conversations (agents taking turns), add \"--conversation-cache-mib\", \"8192\" to the run config's args (docs/DETAILS.md).";
}

function renderTotals(t) {
  if (!t || !t.requests) return "";
  const since = new Date(t.since * 1000).toLocaleString([], {weekday: "short", hour: "2-digit", minute: "2-digit"});
  const read = t.prompt_tokens - t.reused;
  const pSpeed = t.prompt_ms > 0 && read > 0 ? ` at ${fmt(read / (t.prompt_ms / 1000))} tok/s` : "";
  const oSpeed = t.decode_ms > 0 && t.output_tokens > 0 ? ` at ${fmt(t.output_tokens / (t.decode_ms / 1000), 1)} tok/s` : "";
  return `Since ${since}: ${fmt(t.requests)} requests · ${fmt(read)} prompt tokens read${pSpeed} (${fmt(t.reused)} reused) · ` +
         `${fmt(t.output_tokens)} written${oSpeed}`;
}
function renderMonitor(live, hw, st, eng, h, last, requests, totals, kept) {
  // model state
  const on = live.queued > 0 ? "queued" : live.state;
  for (const b of document.querySelectorAll("#state-badges .st-badge")) b.classList.toggle("on", b.dataset.s === on || b.dataset.s === live.state);
  const prog = $("state-progress");
  let label = "Waiting for a request", detail = "", pct = 0;
  if (live.state === "reading") {
    label = "Reading prompt";
    prog.dataset.tone = "info";
    if (live.prompt_total) {
      pct = (100 * live.prompt_read) / live.prompt_total;
      detail = `${fmt(live.prompt_read)} / ${fmt(live.prompt_total)} tokens · ${fmt(pct)}%`;
    } else {
      detail = `${fmt(live.prompt_tokens)} tokens`;
    }
  } else if (live.state === "generating") {
    label = live.phase ? live.phase[0].toUpperCase() + live.phase.slice(1) : "Generating";
    delete prog.dataset.tone;
    pct = live.max_tokens ? Math.min(100, (100 * live.generated) / live.max_tokens) : 0;
    detail = `${fmt(live.generated)} tokens · ${fmt(live.tok_s, 1)} tok/s`;
  } else if (last) {
    delete prog.dataset.tone;
    detail = `last: ${fmt(last.output_tokens)} tokens${last.decode_tok_s ? ` at ${fmt(last.decode_tok_s, 1)} tok/s` : ""}`;
  }
  $("state-label").textContent = label;
  $("state-detail").textContent = detail;
  $("state-bar").style.width = `${pct}%`;

  // the eight cards
  const speed = live.state === "generating" ? live.tok_s : last ? last.decode_tok_s : null;
  setMetric("speed", speed == null ? null : fmt(speed, 1), "t/s",
            live.state === "generating" ? "Decode now" : last ? "Decode last request" : "Decode");
  const prefill = live.state !== "idle" ? live.prefill_tok_s_mean
                : last && last.prompt_ms > 0 ? Math.max(0, last.prompt_tokens - (last.reused || 0)) / (last.prompt_ms / 1000) : null;
  setMetric("prefill", prefill == null ? null : fmt(prefill), "t/s",
            live.state === "reading" ? "Prefill now" : live.state === "generating" ? "Prefill this request" : last ? "Prefill last request" : "Prefill");
  spark("sp-speed", h.tok_s);
  spark("sp-prefill", h.prefill_tok_s_mean);
  // a model split across several cards (issue #112): the cards show their total / mean / hottest, and each card's own
  const per = (f) => (hw.gpus || []).map((g) => `GPU ${g.index} ${f(g)}`).join(" · ");
  const multi = (hw.gpus || []).length > 1;
  setMetric("gpu", hw.gpu_util == null ? null : fmt(hw.gpu_util), "%",
            multi ? per((g) => (g.util == null ? "–" : `${fmt(g.util)}%`)) : st.gpu_name || (st.gpu_note ? "not available" : ""));
  spark("sp-gpu", h.gpu_util, 100);
  setMetric("vram", hw.gpu_mem_used == null ? null : gb(hw.gpu_mem_used), hw.gpu_mem_total ? `/ ${gb(hw.gpu_mem_total, 0)} GB` : "GB",
            multi ? per((g) => (g.mem_used == null ? "–" : `${gb(g.mem_used)} GB`))
                  : eng.expert_slots ? `${fmt(eng.expert_slots)} experts cached` : (st.gpu_note ? "not available on Windows AMD yet" : ""));
  spark("sp-vram", h.gpu_mem_used, hw.gpu_mem_total);
  setMetric("temp", hw.gpu_temp == null ? null : fmt(hw.gpu_temp), "°C",
            multi ? per((g) => (g.temp == null ? "–" : `${fmt(g.temp)}°`)) : "");
  spark("sp-temp", h.gpu_temp, 90);
  setMetric("power", hw.gpu_power == null ? null : fmt(hw.gpu_power), "W", hw.gpu_power_limit ? `of ${fmt(hw.gpu_power_limit)} W limit` : "");
  spark("sp-power", h.gpu_power, hw.gpu_power_limit);
  const gen = hw.gpu_pcie_gen_max || hw.gpu_pcie_gen;
  setMetric("pcie", gen ? `Gen${gen}` : null, hw.gpu_pcie_width ? `x${hw.gpu_pcie_width}` : "",
            hw.gpu_pcie_rx_mb == null ? "" : `to GPU ${fmt(hw.gpu_pcie_rx_mb, hw.gpu_pcie_rx_mb < 10 ? 1 : 0)} MB/s` +
            (hw.gpu_pcie_gen && gen && hw.gpu_pcie_gen < gen ? ` · idle Gen${hw.gpu_pcie_gen}` : ""));
  spark("sp-pcie", h.gpu_pcie_rx_mb);
  setMetric("cpu", hw.cpu == null ? null : fmt(hw.cpu), "%", st.threads ? `${st.cores ? `${st.cores} cores · ` : ""}${st.threads} threads` : "");
  spark("sp-cpu", h.cpu, 100);
  if (hw.disk_read_mb == null) {
    setMetric("disk", null, "", st.psutil ? "" : "needs psutil (setup installs it)");
  } else {
    const big = hw.disk_read_mb >= 1000;
    setMetric("disk", big ? fmt(hw.disk_read_mb / 1024, 2) : fmt(hw.disk_read_mb, hw.disk_read_mb < 10 ? 1 : 0), big ? "GB/s" : "MB/s",
              hw.disk_write_mb == null ? "" : `write ${fmt(hw.disk_write_mb, 1)} MB/s`);
  }
  spark("sp-disk", h.disk_read_mb);

  // context fill: the running request, else the last one
  const ctx = eng.max_context || 0;
  let used = 0;
  if (live.state !== "idle") used = (live.prompt_tokens || 0) + (live.generated || 0);
  else if (last) used = (last.prompt_tokens || 0) + (last.output_tokens || 0);
  const frac = ctx ? Math.min(1, used / ctx) : 0;
  $("ctx-fill").setAttribute("stroke-dasharray", `${(235.6 * frac).toFixed(1)} 314.2`);
  $("ctx-fill").style.opacity = 235.6 * frac >= 3 ? "1" : "0";         // a near-zero arc would draw just its round cap
  $("ctx-pct").textContent = `${Math.round(frac * 100)}%`;
  $("ctx-sub").textContent = ctx ? `${kfmt(used)} / ${ctxfmt(ctx)}` : "–";
  const cacheBytes = (eng.expert_cache_mib || 0) * 1048576;
  $("slots-text").textContent = eng.expert_slots ? `${fmt(eng.expert_slots)} · ${gb(cacheBytes)} GB` : "–";
  $("slots-bar").style.width = hw.gpu_mem_total ? `${Math.min(100, (100 * cacheBytes) / hw.gpu_mem_total)}%` : "0%";
  $("ram-text").textContent = hw.ram_total ? `${gb(hw.ram_used)} / ${gb(hw.ram_total, 0)} GB` : "–";
  const ramPct = hw.ram_total ? (100 * hw.ram_used) / hw.ram_total : 0;
  $("ram-bar").style.width = `${ramPct}%`;
  if (ramPct > 92) $("ram-progress").dataset.tone = "danger"; else delete $("ram-progress").dataset.tone;
  $("temp-text").textContent = hw.gpu_temp == null ? "–" : `${fmt(hw.gpu_temp)} °C`;
  $("temp-bar").style.width = hw.gpu_temp == null ? "0%" : `${Math.min(100, hw.gpu_temp)}%`;

  // recent requests
  const body = $("req-body");
  if (!requests.length) {
    body.innerHTML = `<tr><td colspan="9" class="muted">No requests yet</td></tr>`;
  } else {
    const badge = {stop: ["", "Done"], length: ["", "Max tokens"], cancel: ["st-badge--queued", "Stopped"],
                   disconnect: ["st-badge--queued", "Closed"], error: ["st-badge--error", "Error"]};
    body.innerHTML = requests.slice(0, reqShowAll ? requests.length : 12).map((r) => {
      const [cls, text] = badge[r.finish] || ["", r.finish || "–"];
      const t = new Date(r.time * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});
      const proj = r.projection == null ? "" : ` <span class="st-badge${r.projection ? " st-badge--reading" : ""}" title="experimental speed projection ${r.projection ? "on" : "off"}">${r.projection ? "ESP" : "stock"}</span>`;
      // #588: the VRAM share; the PCIe share (--pcie-frac) beside it when there is one
      const hit = r.hit_rate == null ? "–" : `${(r.hit_rate * 100).toFixed(1)}%` +
        (r.pcie_share ? ` <span class="muted" title="routed experts the GPU read over PCIe (--pcie-frac) or another GPU computed">+${(r.pcie_share * 100).toFixed(1)}% PCIe</span>` : "");
      // Reused tokens are not prefetched again. Match the Monitor's existing Prefill metric.
      const fresh = r.prompt_tokens == null ? null : Math.max(0, r.prompt_tokens - (r.reused || 0));
      const prefillRate = fresh > 0 && r.prompt_ms > 0 ? fresh / (r.prompt_ms / 1000) : null;
      return `<tr><td>${esc(t)}</td><td><span class="st-badge ${cls}">${esc(text)}</span>${proj}</td><td class="num">${fmt(r.prompt_tokens)}</td>
        <td class="num">${fmt(r.reused)}</td><td class="num">${fmt(r.output_tokens)}</td><td class="num">${fmt(prefillRate)}</td><td class="num">${fmt(r.decode_tok_s, 1)}</td>
        <td class="num">${hit}</td><td class="num">${fmt(r.duration_s, 1)} s</td></tr>`;
    }).join("");
  }
  const all = $("req-all");
  kept = kept == null ? requests.length : kept;
  all.hidden = kept <= 12;
  all.textContent = reqShowAll ? "Show fewer" : `Show all (${kept})`;
  $("req-wrap").classList.toggle("all", reqShowAll);
  $("req-totals").textContent = renderTotals(totals);
}

function facts(el, rows) {
  el.innerHTML = rows.filter((r) => r[1] != null && r[1] !== "").map(([k, v, copy]) =>
    `<dt>${esc(k)}</dt><dd>${copy ? `<code>${esc(v)}</code><button class="st-btn st-btn--icon" data-copy="${esc(v)}" aria-label="Copy">${icon("copy")}</button>` : esc(v)}</dd>`).join("");
}
// INFO cvec=project:4-44[:singleL] | add:A-B | 0
function projectionText(c) {
  if (!c || c === "0" || c === 0) return null;
  const [mode, range, single] = String(c).split(":");
  const [a, b] = (range || "").split("-");
  return `${mode === "project" ? "Projection" : "Additive"} control vector on layers ${a}–${b}` +
         `${single ? ` (layer ${single.replace("single", "")}'s direction)` : ""}. Per chat in Sampling. Its package ` +
         "describes the vector as a refusal-direction projection; measure the speed yourself";
}
function renderAbout(eng, hw, st) {
  const kv = {int8: "8-bit", q4_0: "4-bit (Hadamard-rotated)", fp16: "16-bit"}[eng.kv] || eng.kv;
  facts($("facts-engine"), [
    ["Model", eng.model],
    ["Engine", eng.version ? `v${eng.version}` : "built from source"],
    ["Context", eng.max_context ? `${fmt(eng.max_context)} tokens` : null],
    ["KV cache", kv ? `${kv}${eng.kv_resident ? `, streamed: ${fmt(eng.kv_resident)} positions per layer in VRAM, the rest in RAM` : ", all in VRAM"}` : null],
    ["Experts in VRAM", eng.expert_slots ? `${fmt(eng.expert_slots)} (${gb((eng.expert_cache_mib || 0) * 1048576)} GB)` : null],
    ["Speculation", eng.spec ? `MTP drafts up to ${Math.max(0, (eng.mtp_max || eng.spec) - 1)} tokens${eng.lookup ? ", prompt lookup on" : ""}` : null],
    ["Images", eng.images ? "on" : "off"],
    ["Experimental speed projection", projectionText(eng.cvec)],
  ]);
  facts($("facts-hw"), [
    ["GPU", st.gpu_name ? `${st.gpu_name}${hw.gpu_mem_total ? `, ${gb(hw.gpu_mem_total, 0)} GB` : ""}` : (st.gpu_note || "not readable (NVML)")],
    ["CPU", st.cpu_name ? `${st.cpu_name}${st.threads ? `, ${st.threads} threads` : ""}` : null],
    ["RAM", hw.ram_total ? `${gb(hw.ram_total, 0)} GB` : null],
  ]);
  const base = location.origin;
  facts($("facts-api"), [
    ["OpenAI base URL", `${base}/v1`, true],
    ["Anthropic base URL", base, true],
    ["Model name", eng.model, true],
  ]);
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-copy]");
  if (b) copyText(b.dataset.copy, b);
});
$("req-all").addEventListener("click", () => { reqShowAll = !reqShowAll; if (lastMetrics) render(lastMetrics); });

// ------------------------------------------------------------------ MCP servers (GET / POST /mcp)
// The dialog lists the servers, shows one in full, and adds one three ways: from the catalog
// (serve/web/mcp-catalog.js), from a pasted Claude Desktop block, or by hand.  POST /mcp writes mcp-servers.json
// beside the run config and starts or stops the server it names - no restart of the model.
let mcpInfo = {servers: [], tools: 0, managed: null}, mcpRetry = null;
let mcpSelected = null;                 // the server the detail pane shows
let mcpPicked = null;                   // the catalog entry whose form is open
let mcpEditing = null;                  // the server the manual form edits (null: a new one)

const MCP_STATE = {ready: ["ready", "Connected"], starting: ["starting", "Starting"], failed: ["failed", "Failed"],
                   stopped: ["stopped", "Stopped"], disabled: ["disabled", "Disabled"], idle: ["idle", "Waiting"]};

async function loadMcp() {
  try {
    const r = await fetch("mcp", {headers: headers()});
    if (!r.ok) return;
    mcpInfo = await r.json();
  } catch (e) { return; /* an older server: no MCP */ }
  const servers = mcpInfo.servers || [];
  const ready = servers.filter((s) => s.status === "ready" || s.status === "stopped");
  $("mcp-nav-badge").textContent = String(ready.length);
  $("mcp-nav-badge").hidden = !ready.length;
  $("mcp-sum").textContent = servers.length
    ? `${fmt(mcpInfo.tools)} tools from ${servers.length} server${servers.length === 1 ? "" : "s"}` : "none yet";
  $("mcp-count").textContent = servers.length
    ? `${fmt(mcpInfo.tools)} tools · ${ready.length} of ${servers.length} connected` : "";
  $("mcp-row").hidden = !mcpInfo.tools;
  $("mcp-row-sub").textContent = mcpInfo.tools
    ? `${fmt(mcpInfo.tools)} tools from ${ready.map((s) => s.name).join(", ")}` : "no server is connected yet";
  if ($("mcp-dialog").open) renderMcp();
  clearTimeout(mcpRetry);                            // right after the start, servers may still be starting (npx)
  if (servers.some((s) => s.status === "starting")) mcpRetry = setTimeout(loadMcp, 3000);
}

// Which mark a server gets: the one stored when it was added from the catalog, else the catalog entry whose command
// or address it matches, else the generic MCP glyph.
function mcpIcon(server) {
  // a server from GET /mcp keeps its settings under .config; a catalog entry carries its own .icon
  const cfg = server && server.config ? server.config : (server || {});
  if (cfg.icon) return cfg.icon;
  const hay = `${cfg.command || ""} ${(cfg.args || []).join(" ")} ${cfg.url || ""}`.toLowerCase();
  const entry = (window.MCP_CATALOG || []).find((e) => (e.match || []).some((m) => hay.includes(String(m).toLowerCase())));
  return entry ? entry.icon : "mcp";
}
function mcpIconHtml(server, cls = "st-icon-tile") {
  return `<span class="${cls}"><svg class="st-icon"><use href="web/mcp-icons.svg#m-${esc(mcpIcon(server))}"/></svg></span>`;
}
function mcpPick(name) {
  mcpSelected = name;
  $("mcp-add-view").hidden = true;
  $("mcp-detail").hidden = false;
  mcpPicked = null;
  renderMcp();
}
function openMcpDialog() {
  closeSettings();
  closeSidebar();
  mcpEditing = null;
  if (!mcpSelected) mcpSelected = ((mcpInfo.servers || [])[0] || {}).name || null;
  $("mcp-dialog").showModal();
  renderMcp();
  loadMcp();
}
function renderMcp() {
  renderMcpList();
  if (!$("mcp-add-view").hidden) return;            // the add view has its own content
  renderMcpDetail();
}

function renderMcpList() {
  const filter = ($("mcp-filter").value || "").trim().toLowerCase();
  const all = mcpInfo.servers || [];
  const servers = all.filter((s) => !filter || `${s.name} ${s.transport}`.toLowerCase().includes(filter));
  const list = $("mcp-list");
  list.replaceChildren();
  if (!servers.length) {
    const empty = document.createElement("div");
    empty.className = "st-empty";
    empty.innerHTML = `<span class="st-empty__title"></span><span></span>`;
    empty.firstChild.textContent = all.length ? "No match" : "No servers yet";
    empty.lastChild.textContent = all.length ? "Try another name." : "Add one from the catalog.";
    list.append(empty);
    return;
  }
  for (const s of servers) {
    const [dot, label] = MCP_STATE[s.status] || ["idle", s.status];
    const row = document.createElement("div");
    row.className = "mcp-item";
    row.dataset.mcpSelect = s.name;
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-current", String(s.name === mcpSelected));
    row.innerHTML = mcpIconHtml(s) +
      `<span class="mcp-item__text"><span class="mcp-item__name"></span>` +
      `<span class="mcp-item__meta"><span class="st-dot" data-s="${dot}"></span><span class="mcp-item__state"></span></span></span>` +
      `<button class="st-toggle" type="button" role="switch" aria-checked="${s.disabled ? "false" : "true"}"` +
      ` aria-label="Enabled" data-mcp-enable="${esc(s.name)}"${s.editable ? "" : " disabled title=\"this server comes from the run config\""}></button>`;
    row.querySelector(".mcp-item__name").textContent = s.name;
    row.querySelector(".mcp-item__state").textContent = `${label} · ${fmt(s.tools.length)} tools`;
    list.append(row);
  }
}

function renderMcpDetail() {
  const pane = $("mcp-detail");
  const s = (mcpInfo.servers || []).find((x) => x.name === mcpSelected);
  pane.replaceChildren();
  if (!s) {
    const empty = document.createElement("div");
    empty.className = "st-empty mcp-empty";
    empty.innerHTML = `<span class="st-empty__title">No server picked</span>` +
      `<span>Choose one on the left, or add one from the catalog.</span>`;
    pane.append(empty);
    return;
  }
  const cfg = s.config || {};
  const [dot, label] = MCP_STATE[s.status] || ["idle", s.status];

  const head = document.createElement("div");
  head.className = "mcp-detail__head";
  head.innerHTML = mcpIconHtml(s) + `<div><div class="mcp-detail__title"></div><div class="mcp-detail__sub muted small"></div></div>`;
  head.querySelector(".mcp-detail__title").textContent = cfg.title || s.name;
  const info = s.info && s.info.name ? ` · ${s.info.name}${s.info.version ? ` ${s.info.version}` : ""}` : "";
  head.querySelector(".mcp-detail__sub").textContent = `${s.transport}${info}`;

  const actions = document.createElement("div");
  actions.className = "mcp-detail__actions";
  if (s.editable) {
    const edit = mcpButton("Edit", "secondary");
    edit.dataset.mcpEdit = s.name;
    actions.append(edit);
    if (!s.disabled) {
      const restart = mcpButton("Restart", "secondary");
      restart.dataset.mcpReconnect = s.name;
      actions.append(restart);
    }
    const copy = mcpButton("Copy JSON", "secondary");
    copy.dataset.mcpCopy = s.name;
    actions.append(copy);
    const remove = mcpButton("Remove", "danger");
    remove.dataset.mcpRemove = s.name;
    actions.append(remove);
  }
  head.append(actions);
  pane.append(head);

  const facts = document.createElement("dl");
  facts.className = "mcp-detail__facts";
  const add = (k, v) => {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    facts.append(dt, dd);
  };
  add("Name", s.name);
  if (cfg.url) add("Address", cfg.url);
  else add("Program", [cfg.command, ...(cfg.args || [])].join(" "));
  if (cfg.cwd) add("Working folder", cfg.cwd);
  if (cfg.env && Object.keys(cfg.env).length) add("Environment", Object.keys(cfg.env).join(", "));
  add("State", `${label}${s.disabled ? " (switch it on to use its tools)" : ""}`);
  add("Source", s.source === "managed" ? "this page (mcp-servers.json)" :
      s.source === "config" ? "the run config: edit it there" : "--mcp-config: edit it there");
  pane.append(facts);

  if (s.error) {
    const err = document.createElement("div");
    err.className = "mcp-detail__error";
    err.textContent = s.error;
    pane.append(err);
  }

  const toolsHead = document.createElement("div");
  toolsHead.className = "req-head";
  toolsHead.innerHTML = `<span class="st-label">Tools</span><span class="muted small"></span>`;
  toolsHead.querySelector(".small").textContent = s.tools.length
    ? `${fmt(s.tools.length)} offered to the model` : "none yet (a connected server lists them)";
  pane.append(toolsHead);

  const tools = document.createElement("div");
  tools.className = "mcp-tools";
  if (!s.tools.length) {
    const none = document.createElement("span");
    none.className = "muted small";
    none.textContent = s.disabled ? "The server is switched off." : "Nothing yet: a server lists its tools once it connects.";
    tools.append(none);
  }
  for (const t of s.tools) {
    const row = document.createElement("div");
    row.className = "mcp-tool";
    row.innerHTML = `<span class="mcp-tool__name"></span><span class="mcp-tool__desc"></span>`;
    row.querySelector(".mcp-tool__name").textContent = t.name || t.tool;
    row.querySelector(".mcp-tool__desc").textContent = t.description || "";
    tools.append(row);
  }
  pane.append(tools);
}

function mcpButton(text, kind) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `st-btn st-btn--${kind}`;
  b.textContent = text;
  return b;
}

// ---- the add view: catalog, paste, manual ----
function openMcpAdd(tab = "catalog") {
  mcpEditing = null;
  mcpSelected = null;
  mcpPicked = null;
  $("mcp-detail").hidden = true;
  $("mcp-add-view").hidden = false;
  $("mcp-msg").textContent = "";
  setMcpTab(tab);
  renderMcpList();
  if (tab === "catalog") { renderCatalog(); $("mcp-catalog-search").focus(); }
  if (tab === "manual") resetMcpForm();
}
function closeMcpAdd() {
  mcpPicked = null;
  mcpEditing = null;
  $("mcp-add-view").hidden = true;
  $("mcp-detail").hidden = false;
  renderMcp();
}
function setMcpTab(tab) {
  for (const b of document.querySelectorAll("[data-mcp-tab]")) b.setAttribute("aria-selected", String(b.dataset.mcpTab === tab));
  for (const p of document.querySelectorAll("[data-mcp-pane]")) p.hidden = p.dataset.mcpPane !== tab;
}
for (const b of document.querySelectorAll("[data-mcp-tab]")) b.onclick = () => setMcpTab(b.dataset.mcpTab);

function renderCatalog() {
  const box = $("mcp-catalog");
  const q = ($("mcp-catalog-search").value || "").trim().toLowerCase();
  const entries = (window.MCP_CATALOG || []).filter((e) => !q ||
    `${e.title} ${e.summary} ${e.id} ${(e.match || []).join(" ")}`.toLowerCase().includes(q));
  box.replaceChildren();
  let category = null;
  for (const e of entries) {
    if (e.category !== category) {
      category = e.category;
      const head = document.createElement("div");
      head.className = "mcp-cat-head";
      head.textContent = category;
      box.append(head);
    }
    const card = document.createElement("button");
    card.type = "button";
    card.className = "mcp-cardbtn";
    card.dataset.mcpPick = e.id;
    card.innerHTML = `<span class="mcp-cardbtn__top">` +
      `<span class="st-icon-tile"><svg class="st-icon"><use href="web/mcp-icons.svg#m-${esc(e.icon)}"/></svg></span>` +
      `<span class="mcp-cardbtn__title"></span><span class="mcp-cardbtn__kind"></span></span>` +
      `<span class="mcp-cardbtn__sum"></span><span class="mcp-cardbtn__needs"></span>`;
    card.querySelector(".mcp-cardbtn__title").textContent = e.title;
    card.querySelector(".mcp-cardbtn__kind").textContent = e.transport === "http" ? "http" : "stdio";
    card.querySelector(".mcp-cardbtn__sum").textContent = e.summary;
    for (const need of e.needs || []) {
      const chip = document.createElement("span");
      chip.className = "mcp-chip";
      chip.textContent = need;
      card.querySelector(".mcp-cardbtn__needs").append(chip);
    }
    box.append(card);
  }
  if (!entries.length) {
    const none = document.createElement("div");
    none.className = "st-empty";
    none.innerHTML = `<span class="st-empty__title">Nothing matches</span><span>Try "git", "browser" or "database".</span>`;
    box.append(none);
  }
}
$("mcp-catalog-search").oninput = renderCatalog;
$("mcp-filter").oninput = renderMcpList;

// The form a catalog entry opens: its name, one field per thing it needs, and the command it will run.
function openMcpConfigure(entry) {
  mcpPicked = entry;
  $("mcp-add-view").hidden = true;
  $("mcp-detail").hidden = false;
  const pane = $("mcp-detail");
  pane.replaceChildren();
  const box = document.createElement("div");
  box.className = "mcp-config";
  box.innerHTML =
    `<div class="mcp-detail__head">${mcpIconHtml(entry)}` +
    `<div><div class="mcp-detail__title"></div><div class="muted small mcp-detail__sub"></div></div></div>` +
    `<label class="st-field"><span class="st-label">Name</span>` +
    `<input class="st-input" data-cfg-name autocomplete="off" spellcheck="false"></label>` +
    `<div data-cfg-fields></div>` +
    `<div class="st-field"><span class="st-label">What it starts</span><pre class="mcp-runs" data-cfg-runs></pre></div>` +
    `<div class="cfg-actions"><button class="st-btn st-btn--primary" type="button" data-cfg-add>Add server</button>` +
    `<button class="st-btn st-btn--secondary" type="button" data-cfg-back>Back to the catalog</button>` +
    `<span class="muted small" data-cfg-msg role="status"></span></div>`;
  box.querySelector(".mcp-detail__title").textContent = entry.title;
  box.querySelector(".mcp-detail__sub").textContent = `${entry.transport === "http" ? "an address" : "a program"} · ${entry.category}`;
  const name = box.querySelector("[data-cfg-name]");
  name.value = entry.id;
  const fields = box.querySelector("[data-cfg-fields]");
  for (const p of entry.params || []) {
    const field = document.createElement("label");
    field.className = "st-field";
    field.innerHTML = `<span class="st-label"></span><input class="st-input" data-cfg-param autocomplete="off" spellcheck="false">` +
      (p.help ? `<span class="muted small"></span>` : "");
    field.querySelector(".st-label").textContent = p.label + (p.required ? "" : " (optional)");
    const input = field.querySelector("[data-cfg-param]");
    input.dataset.cfgParam = p.key;
    input.placeholder = p.placeholder || "";
    if (p.help) field.querySelector(".small").textContent = p.help;
    fields.append(field);
  }
  for (const e of entry.env || []) {
    const field = document.createElement("label");
    field.className = "st-field";
    field.innerHTML = `<span class="st-label"></span>` +
      `<input class="st-input" data-cfg-env autocomplete="off" spellcheck="false"${e.secret ? ' type="password"' : ""}>` +
      (e.help ? `<span class="muted small"></span>` : "");
    field.querySelector(".st-label").textContent = e.label;
    const input = field.querySelector("[data-cfg-env]");
    input.dataset.cfgEnv = e.key;
    input.placeholder = e.placeholder || "";
    if (e.help) field.querySelector(".small").textContent = e.help;
    fields.append(field);
  }
  box.querySelector("[data-cfg-runs]").textContent = catalogCommand(entry, box);
  box.addEventListener("input", () => { box.querySelector("[data-cfg-runs]").textContent = catalogCommand(entry, box); });
  box.querySelector("[data-cfg-back]").onclick = () => { mcpPicked = null; openMcpAdd("catalog"); };
  box.querySelector("[data-cfg-add]").onclick = () => mcpAddFromCatalog(entry, box);
  pane.append(box);
  name.focus();
  name.select();
}

// The command as the fields stand: {{placeholders}} filled in, an optional argument left out when its field is empty.
function catalogArgs(entry, box) {
  const values = {};
  for (const p of entry.params || []) {
    const input = box.querySelector(`[data-cfg-param="${p.key}"]`);
    values[p.key] = input ? input.value.trim() : "";
  }
  const out = [];
  const raw = entry.args || [];
  for (let i = 0; i < raw.length; i++) {
    const tok = String(raw[i]);
    const m = /^\{\{([a-z0-9_]+)\}\}$/i.exec(tok);
    if (!m) { out.push(tok); continue; }
    const value = values[m[1]];
    if (value) out.push(value);
    else if (i > 0 && String(raw[i - 1]).startsWith("--")) out.pop();     // "--flag {{value}}" with no value
  }
  return out;
}
function catalogCommand(entry, box) {
  if (entry.transport === "http") return entry.url || "";
  return [entry.command, ...catalogArgs(entry, box)].join(" ");
}
function catalogConfig(entry, box) {
  const cfg = {command: entry.command, args: catalogArgs(entry, box)};
  if (entry.transport === "http" && entry.url) { delete cfg.command; delete cfg.args; cfg.url = entry.url; }
  const env = {};
  for (const e of entry.env || []) {
    const input = box.querySelector(`[data-cfg-env="${e.key}"]`);
    const value = input ? input.value : "";
    if (value) env[e.key] = value;
  }
  if (Object.keys(env).length) cfg.env = env;
  cfg.icon = entry.icon;
  cfg.title = entry.title;
  return cfg;
}
async function mcpAddFromCatalog(entry, box) {
  const msg = box.querySelector("[data-cfg-msg]");
  const say = (text, bad) => { msg.textContent = text; msg.className = `muted small ${bad ? "mcp-msg-bad" : "mcp-msg-ok"}`; };
  let name = box.querySelector("[data-cfg-name]").value.trim() || entry.id;
  if (!/^[A-Za-z0-9_-]{1,40}$/.test(name)) {
    say("A name is 1-40 letters, digits, \"-\" or \"_\".", true);
    return;
  }
  const missing = (entry.params || []).filter((p) => p.required &&
    !box.querySelector(`[data-cfg-param="${p.key}"]`).value.trim());
  if (missing.length) { say(`Fill in ${missing.map((p) => p.label).join(", ")}.`, true); return; }
  const missingEnv = (entry.env || []).filter((e) => e.required &&
    !box.querySelector(`[data-cfg-env="${e.key}"]`).value.trim());
  if (missingEnv.length) { say(`Fill in ${missingEnv.map((e) => e.label).join(", ")}.`, true); return; }
  if ((mcpInfo.servers || []).some((s) => s.name === name)) {        // the server's names are the file's keys
    let n = 2;
    while ((mcpInfo.servers || []).some((s) => s.name === `${entry.id}-${n}`)) n += 1;
    name = `${entry.id}-${n}`;
  }
  const res = await mcpSend({add: {[name]: catalogConfig(entry, box)}}, `Added ${name}`, true);
  if (res !== false) { mcpSelected = name; closeMcpAdd(); }
}

// ---- paste a Claude Desktop / Cursor block ----
$("mcp-paste-add").onclick = async () => {
  const msg = $("mcp-paste-msg");
  const say = (text, bad) => { msg.textContent = text; msg.className = `muted small ${bad ? "mcp-msg-bad" : "mcp-msg-ok"}`; };
  let data;
  try {
    data = JSON.parse($("mcp-paste").value || "{}");
  } catch (e) { say("That is not JSON.", true); return; }
  const block = data && (data.mcpServers || data.mcp_servers) ? (data.mcpServers || data.mcp_servers) : data;
  if (!block || typeof block !== "object" || Array.isArray(block)) { say("Send an object of servers.", true); return; }
  const names = Object.keys(block);
  if (!names.length) { say("There is no server in it.", true); return; }
  let added = 0;
  for (const name of names) {
    const cfg = block[name];
    if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) { say(`${name}: not an object.`, true); continue; }
    let target = name;
    if ((mcpInfo.servers || []).some((s) => s.name === target)) { target = `${name}-2`; }
    if (await mcpSend({add: {[target]: cfg}}, `Added ${target}`, true) !== false) added += 1;
  }
  $("mcp-paste").value = "";
  say(added ? `Added ${added} server${added === 1 ? "" : "s"}.` : "Nothing was added.", !added);
  if (added) { mcpSelected = names[0]; closeMcpAdd(); }
};

// ---- the manual form (and Edit) ----
function resetMcpForm() {
  $("mcp-name").value = "";
  $("mcp-name").disabled = false;
  $("mcp-kind").value = "stdio";
  $("mcp-command").value = "";
  $("mcp-args").value = "";
  $("mcp-env").value = "";
  $("mcp-cwd").value = "";
  $("mcp-url").value = "";
  $("mcp-headers").value = "";
  $("mcp-disabled").setAttribute("aria-checked", "false");
  $("mcp-msg").textContent = "";
  mcpFields();
}
function openMcpForm(name = null) {
  const s = name ? (mcpInfo.servers || []).find((x) => x.name === name) : null;
  const cfg = (s && s.config) || {};
  mcpEditing = s ? s.name : null;
  $("mcp-detail").hidden = true;
  $("mcp-add-view").hidden = false;
  setMcpTab("manual");
  $("mcp-name").value = s ? s.name : "";
  $("mcp-name").disabled = !!s;                    // the name is the file's key: remove and add to rename
  $("mcp-kind").value = cfg.url ? "http" : "stdio";
  $("mcp-command").value = cfg.command || "";
  $("mcp-args").value = (cfg.args || []).join("\n");
  $("mcp-env").value = mcpText(cfg.env, "=");      // a secret arrives as ******** and is kept when sent back
  $("mcp-cwd").value = cfg.cwd || "";
  $("mcp-url").value = cfg.url || "";
  $("mcp-headers").value = mcpText(cfg.headers, ": ");
  $("mcp-disabled").setAttribute("aria-checked", String(cfg.disabled === true));
  $("mcp-msg").textContent = "";
  $("mcp-save").textContent = s ? "Save" : "Add";
  mcpFields();
  $("mcp-name").focus();
  $("mcp-name").select();
}
function mcpFields() {                             // program vs address: one block of fields at a time
  const http = $("mcp-kind").value === "http";
  $("mcp-http").hidden = !http;
  $("mcp-stdio").hidden = http;
}
// the editor: KEY=VALUE (env) or Name: value (headers) lines, one per line
function mcpLines(text) { return String(text || "").split("\n").map((x) => x.trim()).filter(Boolean); }
function mcpMap(lines, sep) {
  const out = {};
  for (const line of mcpLines(lines)) {
    const at = line.indexOf(sep);
    if (at < 1) continue;
    out[line.slice(0, at).trim()] = line.slice(at + sep.length).trim();
  }
  return out;
}
function mcpText(map, sep) { return Object.entries(map || {}).map(([k, v]) => `${k}${sep}${v}`).join("\n"); }
function mcpFormConfig() {
  const cfg = {};
  if ($("mcp-kind").value === "http") {
    cfg.url = $("mcp-url").value.trim();
    const headers = mcpMap($("mcp-headers").value, ":");
    if (Object.keys(headers).length) cfg.headers = headers;
  } else {
    cfg.command = $("mcp-command").value.trim();
    const args = mcpLines($("mcp-args").value);
    if (args.length) cfg.args = args;
    const env = mcpMap($("mcp-env").value, "=");
    if (Object.keys(env).length) cfg.env = env;
    if ($("mcp-cwd").value.trim()) cfg.cwd = $("mcp-cwd").value.trim();
  }
  if ($("mcp-disabled").getAttribute("aria-checked") === "true") cfg.disabled = true;
  if (mcpEditing) {                                // the page's own keys are not fields: keep the ones on the server
    const s = (mcpInfo.servers || []).find((x) => x.name === mcpEditing);
    const served = (s && s.config) || {};
    if (served.icon) cfg.icon = served.icon;
    if (served.title) cfg.title = served.title;
  }
  return cfg;
}
// One change, reported by its HTTP status: mcpSend adds the toast, mcpPost is for the callers that batch.
async function mcpPost(body) {
  try {
    const r = await fetch("mcp", {method: "POST", headers: headers(true), body: JSON.stringify(body)});
    let j = null;
    try { j = await r.json(); } catch (e) { /* not json */ }
    if (!r.ok) return {ok: false, error: (j && j.error && j.error.message) || `HTTP ${r.status}`};
    mcpInfo = j;
    return {ok: true, data: j};
  } catch (e) { return {ok: false, error: String(e.message || e)}; }
}
async function mcpSend(body, done, quiet) {
  const res = await mcpPost(body);
  if (!res.ok) {
    toast("error", "The MCP server was not changed", res.error, 7000);
    $("mcp-msg").textContent = res.error;
    return false;
  }
  if ($("mcp-dialog").open) renderMcp();
  if (!quiet) toast("success", done, "");
  return true;
}
$("mcp-kind").onchange = mcpFields;
$("mcp-disabled").onclick = () => $("mcp-disabled").setAttribute(
  "aria-checked", String($("mcp-disabled").getAttribute("aria-checked") !== "true"));
$("mcp-add").onclick = () => openMcpAdd("catalog");
$("mcp-cancel").onclick = () => { resetMcpForm(); closeMcpAdd(); };
$("mcp-form").onsubmit = async (e) => {
  e.preventDefault();                              // Enter saves; it never reloads the page
  const cfg = mcpFormConfig();
  const name = mcpEditing || $("mcp-name").value.trim();
  if (!/^[A-Za-z0-9_-]{1,40}$/.test(name)) { $("mcp-msg").textContent = 'A name is 1-40 letters, digits, "-" or "_".'; return; }
  if (!cfg.url && !cfg.command) { $("mcp-msg").textContent = "Give it a program to start, or an address."; return; }
  const ok = mcpEditing ? await mcpSend({update: {name, config: cfg}}, `Saved ${name}`)
                        : await mcpSend({add: {[name]: cfg}}, `Added ${name}`);
  if (ok) { mcpSelected = name; resetMcpForm(); closeMcpAdd(); }
};
$("mcp-open").onclick = () => openMcpDialog();
$("mcp-nav").onclick = () => openMcpDialog();
$("mcp-close").onclick = () => $("mcp-dialog").close();
$("mcp-dialog").addEventListener("close", () => { closeMcpAdd(); mcpEditing = null; });
$("mcp-dialog").addEventListener("click", (e) => { if (e.target === $("mcp-dialog")) $("mcp-dialog").close(); });

// the list and the detail pane share one click handler: a row selects, its switch enables
$("mcp-list").onclick = (e) => {
  const toggle = e.target.closest("[data-mcp-enable]");
  if (toggle) {
    e.stopPropagation();
    const name = toggle.dataset.mcpEnable;
    const on = toggle.getAttribute("aria-checked") !== "true";
    toggle.setAttribute("aria-checked", String(on));
    const server = (mcpInfo.servers || []).find((x) => x.name === name);
    const cfg = {...((server && server.config) || {}), disabled: !on};   // an update is the whole server: keep its fields
    mcpPost({update: {name, config: cfg}}).then((res) => {
      if (!res.ok) { toggle.setAttribute("aria-checked", String(!on)); toast("error", "Not changed", res.error, 6000); }
      else { mcpSelected = name; renderMcp(); }
    });
    return;
  }
  const pick = e.target.closest("[data-mcp-select]");
  if (pick) mcpPick(pick.dataset.mcpSelect);
};
$("mcp-list").onkeydown = (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  if (e.target.closest("button")) return;
  const pick = e.target.closest("[data-mcp-select]");
  if (pick) { e.preventDefault(); mcpPick(pick.dataset.mcpSelect); }
};
$("mcp-detail").onclick = async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.mcpEdit) { openMcpForm(b.dataset.mcpEdit); return; }
  if (b.dataset.mcpReconnect) {
    await mcpSend({reconnect: b.dataset.mcpReconnect}, `Restarted ${b.dataset.mcpReconnect}`);
    mcpSelected = b.dataset.mcpReconnect;
    renderMcp();
    return;
  }
  if (b.dataset.mcpCopy) {
    const s = (mcpInfo.servers || []).find((x) => x.name === b.dataset.mcpCopy);
    const cfg = Object.fromEntries(Object.entries(s.config || {}).filter(([k]) => !["icon", "title"].includes(k)));
    copyText(JSON.stringify({[s.name]: cfg}, null, 2));
    return;
  }
  if (b.dataset.mcpRemove) {
    const name = b.dataset.mcpRemove;
    if (!confirm(`Remove the MCP server "${name}"? Its tools are no longer offered to the model.`)) return;
    if (await mcpSend({remove: [name]}, `Removed ${name}`) !== false) {
      mcpSelected = ((mcpInfo.servers || [])[0] || {}).name || null;
      renderMcp();
    }
  }
};
// the catalog cards live in the add view, not in the detail pane
$("mcp-catalog").onclick = (e) => {
  const card = e.target.closest("[data-mcp-pick]");
  if (card) openMcpConfigure((window.MCP_CATALOG || []).find((x) => x.id === card.dataset.mcpPick));
};

// ------------------------------------------------------------------ Web search (GET / POST /search)
// A SearXNG instance the model may search with.  The tools are web_search and read_page, offered only when the URL is
// saved and the switch is on; the chat asks for them with "strata_search": true, which only this page sends.  The
// dialog saves what it shows: the switch writes at once, the rest on Save, and Test runs a real query with the fields
// as they stand, saved or not.
let searchInfo = {configured: false, settings: {}, tools: []};

async function loadSearch() {
  try {
    const r = await fetch("search", {headers: headers()});
    if (!r.ok) return;
    searchInfo = await r.json();
  } catch (e) { return; /* an older server: no web search */ }
  renderSearch();
  renderToolPills();
}
function searchToggle(id, on) { $(id).setAttribute("aria-checked", String(!!on)); }
function searchOn(id) { return $(id).getAttribute("aria-checked") === "true"; }
function searchAuthFields() {
  const auth = $("search-auth").value;
  $("search-bearer").hidden = auth !== "bearer";
  $("search-basic").hidden = auth !== "basic";
  $("search-headers").hidden = auth !== "header";
}
function searchNote() {                              // the URL's shape, as it is typed
  const url = $("search-url").value.trim();
  const note = $("search-url-note");
  note.textContent = !url ? "" : /^https?:\/\/[^\s/]+/i.test(url) ? ""
    : "Start with http:// or https://, and leave out ?query and #hash.";
}
function renderSearch() {
  const s = searchInfo.settings || {};
  searchToggle("search-enabled", s.enabled);
  $("search-url").value = s.base_url || "";
  $("search-auth").value = s.auth || "none";
  $("search-token").value = s.token || "";
  $("search-user").value = s.basic_user || "";
  $("search-pass").value = s.basic_pass || "";
  $("search-headers-text").value = Object.entries(s.headers || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
  $("search-language").value = s.language || "";
  $("search-safe").value = s.safesearch == null ? "" : String(s.safesearch);
  $("search-categories").value = s.categories || "";
  $("search-time").value = s.time_range || "";
  $("search-timeout").value = s.timeout_s || "";
  $("search-max").value = s.max_results || "";
  searchToggle("search-readpage", s.read_page !== false);
  searchToggle("search-local", s.allow_local === true);
  searchAuthFields();
  searchNote();
  $("search-sum").textContent = searchInfo.configured
    ? `${(searchInfo.tools || []).join(", ")} · ${s.base_url}` : "not set up";
  const searchStatus = $("search-state");
  searchStatus.textContent = searchInfo.configured ? "in use" : "not set up";
  searchStatus.dataset.state = searchInfo.configured ? "on" : "off";
  $("search-row").hidden = !searchInfo.configured;
  $("search-row-sub").textContent = searchInfo.configured
    ? `${(searchInfo.tools || []).join(", ")} from ${s.base_url}` : "SearXNG";
  if (searchInfo.error) searchSay(searchInfo.error, true);
}
function searchSay(text, bad) {
  const msg = $("search-msg");
  msg.textContent = text;
  msg.className = `small ${bad ? "mcp-msg-bad" : "mcp-msg-ok"}`;
}
// What the server would also refuse, said before the request: a URL without a scheme, a token the chosen kind needs.
function searchProblem() {
  const url = $("search-url").value.trim();
  if (searchOn("search-enabled") && !url) return "An enabled web search needs the SearXNG instance's URL.";
  if (url && !/^https?:\/\/[^\s/]+/i.test(url)) return "The instance's URL must start with http:// or https://.";
  if (url && /[?#]/.test(url)) return "The instance's URL is a base address: leave out ?query and #hash.";
  const auth = $("search-auth").value;
  if (auth === "bearer" && !$("search-token").value.trim()) return "Bearer authentication needs a token.";
  if (auth === "basic" && !$("search-user").value.trim()) return "Basic authentication needs a user name.";
  if (auth === "header" && !$("search-headers-text").value.trim()) return "Header authentication needs at least one header.";
  return "";
}
function searchPayload() {                       // the whole settings object the server checks and saves
  const body = {
    enabled: searchOn("search-enabled"), base_url: $("search-url").value.trim(), auth: $("search-auth").value,
    token: $("search-token").value, basic_user: $("search-user").value.trim(), basic_pass: $("search-pass").value,
    headers: mcpMap($("search-headers-text").value, ":"),
    language: $("search-language").value.trim(), safesearch: $("search-safe").value,
    categories: $("search-categories").value.trim(), time_range: $("search-time").value,
    read_page: searchOn("search-readpage"), allow_local: searchOn("search-local"),
  };
  const timeout = $("search-timeout").value.trim(), max = $("search-max").value.trim();
  if (timeout !== "") body.timeout_s = Number(timeout);
  if (max !== "") body.max_results = Number(max);
  return body;
}
async function searchPost(body) {
  const r = await fetch("search", {method: "POST", headers: headers(true), body: JSON.stringify(body)});
  let j = null;
  try { j = await r.json(); } catch (e) { /* not json */ }
  if (!r.ok) throw new Error((j && j.error && j.error.message) || `HTTP ${r.status}`);
  return j;
}
async function saveSearch(quiet, fromToggle) {
  const problem = searchProblem();
  if (problem) {
    searchSay(problem, true);
    if (fromToggle) searchToggle("search-enabled", false);
    return false;
  }
  try {
    searchInfo = await searchPost({set: searchPayload()});
    renderSearch();
    searchSay("Saved.", false);
    if (!quiet) toast("success", "Web search saved", searchInfo.configured
      ? "The chat offers web_search and read_page from its next turn."
      : "It is off, so the model is not offered the tools.");
    return true;
  } catch (e) {
    searchSay(e.message, true);
    if (fromToggle) searchToggle("search-enabled", false);
    if (!quiet) toast("error", "Web search was not saved", e.message, 7000);
    return false;
  }
}
$("search-auth").onchange = searchAuthFields;
$("search-url").oninput = searchNote;
$("search-enabled").onclick = async () => {          // the master switch writes at once: a reload must not lose it
  searchToggle("search-enabled", !searchOn("search-enabled"));
  await saveSearch(true, true);
};
for (const id of ["search-readpage", "search-local"]) {
  $(id).onclick = () => searchToggle(id, !searchOn(id));
}
$("search-form").onsubmit = (e) => { e.preventDefault(); saveSearch(false); };   // Enter saves; it never reloads
$("search-save").onclick = () => saveSearch(false);
$("search-test").onclick = async () => {             // one real query with the fields as they stand
  const query = $("search-test-query").value.trim() || "AryaInfer web search";
  const result = $("search-test-result");
  const say = (text, bad) => { result.textContent = text; result.className = `small ${bad ? "mcp-msg-bad" : "mcp-msg-ok"}`; };
  const problem = searchProblem();
  if (problem) { say(problem, true); return; }
  $("search-test").disabled = true;
  say("Searching…", false);
  try {
    const r = await searchPost({test: {query, settings: searchPayload()}});
    if (!r.ok) { say(r.error || "The search failed.", true); return; }
    const engines = (r.engines || []).join(", ") || "none named";
    const down = (r.unresponsive || []).map((u) => u.engine).filter(Boolean);
    say(`${fmt(r.results)} results in ${(r.ms / 1000).toFixed(1)} s · engines: ${engines}` +
        (down.length ? ` · no answer: ${down.join(", ")}` : "") +
        (r.first_url ? ` · first: ${r.first_url}` : ""), false);
  } catch (e) {
    say(e.message, true);
  } finally {
    $("search-test").disabled = false;
  }
};
$("search-open").onclick = () => openSearchDialog();
function openSearchDialog() {
  closeSettings();
  $("search-dialog").showModal();
  loadSearch().then(() => $("search-url").focus());
}
$("search-close").onclick = () => $("search-dialog").close();
$("search-dialog").addEventListener("click", (e) => { if (e.target === $("search-dialog")) $("search-dialog").close(); });

// ------------------------------------------------------------------ images (ComfyUI)
// The dialog behind Settings > Tools > Images: the endpoint, the workflows, the local server's Start/Stop and the Check
// that names what a ComfyUI lacks.  Every call goes through this server (serve/comfyui.py), never to ComfyUI directly,
// so a remote server behind a token works from the same page.
let comfyInfo = {configured: false, reachable: false, workflows: [], server: {}, settings: {}, gallery: {}, jobs: []};
let comfyCheck = null;

async function loadComfy() {
  try {
    const r = await fetch("comfy", {headers: headers()});
    if (!r.ok) return;
    comfyInfo = await r.json();
  } catch (e) { return; /* an older server: no images */ }
  renderComfy();
}
function comfySettings() { return comfyInfo.settings || {}; }
function renderComfy() {
  const s = comfySettings(), server = comfyInfo.server || {};
  const launch = s.launch || {}, free = s.free_vram || {}, gal = s.gallery || {};
  const workflows = comfyInfo.workflows || [];
  $("images-sum").textContent = !comfyInfo.configured ? "not set up"
    : comfyInfo.reachable ? `ComfyUI ${comfyInfo.version || ""} · ${workflows.length} workflows`.trim()
    : "set up, not reachable";
  $("images-row").hidden = !comfyInfo.configured;
  const status = $("image-status");
  // a phone has no room for the version beside the title: the pill says connected and the title attribute keeps it
  const phone = matchMedia("(max-width: 560px)").matches;
  status.textContent = !comfyInfo.configured ? "not set up"
    : comfyInfo.reachable ? (phone ? "connected" : `connected${comfyInfo.version ? ` · ComfyUI ${comfyInfo.version}` : ""}`)
    : "not reachable";
  status.title = comfyInfo.reachable && comfyInfo.version ? `ComfyUI ${comfyInfo.version}` : "";
  status.dataset.state = !comfyInfo.configured ? "off" : comfyInfo.reachable ? "on" : "down";
  $("image-url").value = s.base_url || "";
  $("image-headers").value = Object.entries(s.headers || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
  $("image-timeout").value = s.timeout_s || "";
  $("image-launch-mode").value = launch.mode || "auto";
  $("image-server-dir").value = launch.server_dir || "";
  $("image-python").value = launch.python_exe || "";
  $("image-extra-args").value = launch.extra_args || "";
  $("image-task").value = launch.task_name || "";
  $("image-auto-start").setAttribute("aria-checked", String(!!launch.auto_start));
  $("image-policy").value = free.policy || "auto";
  $("image-need").value = free.need_mib || "";
  $("image-max-files").value = gal.max_files || "";
  $("image-max-mib").value = gal.max_mib == null ? "" : gal.max_mib;
  const device = comfyInfo.device || {};
  $("image-server-state").textContent = [
    server.hint || "",
    comfyInfo.reachable ? `${device.name || "a GPU"} · ${fmt(device.vram_free_mib)} MiB free` : "",
    (server.pids || []).length ? `process ${server.pids.join(", ")}` : "",
    server.task_state ? `task: ${server.task_state}` : "",
  ].filter(Boolean).join(" · ");
  $("images-row-sub").textContent = comfyInfo.reachable
    ? "a generate_image tool in this page's chat" : "set the server up first";
  renderComfyWorkflows();
  renderComfyCheck();
  renderToolPills();
  if (typeof roomOnComfy === "function") roomOnComfy();      // the Images room shares these settings
}
// Two lights in the header: is web search on, and is the image engine on and answering.  A click opens the card that
// turns it on, so the light is also the shortcut.  "unset" means the tool has never been configured.
function renderToolPills() {
  const s = settings || {};
  const search = !searchInfo.configured ? "unset" : (s.search !== false ? "on" : "off");
  const images = !comfyInfo.configured ? "unset"
    : (!comfyInfo.reachable ? "down" : (s.images !== false ? "on" : "off"));
  const words = {on: "on", off: "off", unset: "not set up", down: "ComfyUI is not answering"};
  const set = (id, state, label) => {
    const el = $(id);
    el.dataset.state = state;
    el.title = `${label}: ${words[state]}`;
    el.setAttribute("aria-label", `${label}: ${words[state]}`);
  };
  set("pill-search", search, "Web search");
  set("pill-images", images, "Images");
}
$("pill-search").onclick = () => openSearchDialog();
$("pill-images").onclick = () => { if (typeof openImagesDialog === "function") openImagesDialog(); };
function renderComfyWorkflows() {
  const box = $("image-workflows");
  const list = comfyInfo.workflows || [];
  const s = comfySettings();
  box.replaceChildren();
  if (!list.length) {
    const empty = document.createElement("div");
    empty.className = "st-empty";
    empty.innerHTML = `<span class="st-empty__title">No workflows</span><span>Import an API-format graph to begin.</span>`;
    box.append(empty);
    return;
  }
  const checked = comfyCheck ? new Map((comfyCheck.workflows || []).map((w) => [w.name, w])) : new Map();
  for (const w of list) {
    const bad = checked.get(w.name);
    const row = document.createElement("div");
    row.className = "image-wf";
    row.dataset.bad = String(!!(bad && !bad.ok));
    row.dataset.name = w.name;
    row.innerHTML = `<span class="image-wf__name"></span><span class="image-wf__meta">` +
      `<span class="mcp-chip"></span><span class="image-wf__size"></span>` +
      `${bad && !bad.ok ? `<span class="mcp-chip mcp-msg-bad" title=""></span>` : ""}</span>` +
      `<span class="image-wf__pick"><button type="button" data-pick="text">Text</button>` +
      `<button type="button" data-pick="edit">Edit</button></span>` +
      `${w.source === "imported" ? `<button class="st-btn st-btn--icon image-wf__remove" type="button" data-remove aria-label="Remove">` +
        icon("trash", "st-icon st-icon--sm") + `</button>` : ""}`;
    row.querySelector(".image-wf__name").textContent = w.name;
    row.querySelector(".mcp-chip").textContent = w.role === "image-to-image" ? "edit" : "text";
    row.querySelector(".image-wf__size").textContent = w.baked_size
      ? `${w.baked_size.width}×${w.baked_size.height}` : "source size";
    const badChip = row.querySelector(".mcp-chip.mcp-msg-bad");
    if (badChip) {
      badChip.textContent = "needs attention";
      badChip.title = [...(bad.missing_nodes || []), ...(bad.missing_models || [])].join(", ");
    }
    const textBtn = row.querySelector('[data-pick="text"]');
    const editBtn = row.querySelector('[data-pick="edit"]');
    textBtn.setAttribute("aria-pressed", String(s.active_text === w.name));
    editBtn.setAttribute("aria-pressed", String(s.active_edit === w.name));
    textBtn.disabled = w.role !== "text-to-image";
    editBtn.disabled = w.role !== "image-to-image";
    textBtn.onclick = () => setComfyDefault("active_text", w.name);
    editBtn.onclick = () => setComfyDefault("active_edit", w.name);
    const remove = row.querySelector("[data-remove]");
    if (remove) remove.onclick = () => removeComfyWorkflow(w.name);
    box.append(row);
  }
}
function renderComfyCheck() {
  const out = $("image-check-result");
  if (!comfyCheck) { out.textContent = ""; out.className = "muted small"; return; }
  const bad = (comfyCheck.workflows || []).filter((w) => !w.ok);
  out.className = `muted small ${bad.length ? "mcp-msg-bad" : "mcp-msg-ok"}`;
  if (!bad.length) {
    out.textContent = `All ${(comfyCheck.workflows || []).length} workflows check out against ComfyUI ` +
      `${comfyCheck.version || ""}.`.trim();
    return;
  }
  out.textContent = bad.map((w) => {
    const parts = [...(w.missing_nodes || []), ...(w.missing_models || [])];
    return `${w.name}: ${parts.length ? parts.join(", ") : w.error || "failed"}`;
  }).join("\n");
  out.style.whiteSpace = "pre-wrap";
}
function comfyPayload() {
  const s = comfySettings();
  const number = (id, fallback) => {
    const raw = $(id).value.trim();
    return raw === "" ? fallback : Number(raw);
  };
  return {
    base_url: $("image-url").value.trim(),
    headers: mcpMap($("image-headers").value, ":"),
    timeout_s: number("image-timeout", 600),
    active_text: s.active_text || "",
    active_edit: s.active_edit || "",
    launch: {
      mode: $("image-launch-mode").value,
      server_dir: $("image-server-dir").value.trim(),
      python_exe: $("image-python").value.trim(),
      extra_args: $("image-extra-args").value,
      task_name: $("image-task").value.trim(),
      auto_start: $("image-auto-start").getAttribute("aria-checked") === "true",
    },
    free_vram: {policy: $("image-policy").value, need_mib: number("image-need", 10240)},
    gallery: {max_files: number("image-max-files", 500), max_mib: number("image-max-mib", 8192)},
    imported: s.imported || [],
    max_rounds: s.max_rounds || 8,
  };
}
async function comfyPost(body) {
  const r = await fetch("comfy", {method: "POST", headers: headers(true), body: JSON.stringify(body)});
  let j = null;
  try { j = await r.json(); } catch (e) { /* not json */ }
  if (!r.ok) throw new Error((j && j.error && j.error.message) || `HTTP ${r.status}`);
  return j;
}
async function saveComfy(quiet) {
  $("image-msg").textContent = "";
  try {
    await comfyPost({set: comfyPayload()});
    await loadComfy();
    $("image-msg").textContent = "Saved.";
    $("image-msg").className = "muted small mcp-msg-ok";
    if (!quiet) toast("success", "Images settings saved", comfyInfo.reachable
      ? "The Images room and the chat's generate_image use this server."
      : "The address is saved; ComfyUI is not answering yet.");
  } catch (e) {
    $("image-msg").textContent = e.message;
    $("image-msg").className = "muted small mcp-msg-bad";
    if (!quiet) toast("error", "Images settings were not saved", e.message, 7000);
  }
}
async function setComfyDefault(key, name) {
  const body = comfyPayload();
  if (key === "active_edit") body.active_text = comfySettings().active_text || "";
  body[key] = name;
  try {
    await comfyPost({set: body});
    await loadComfy();
  } catch (e) {
    toast("error", "The default was not changed", e.message, 6000);
  }
}
async function removeComfyWorkflow(name) {
  if (!confirm(`Remove the imported workflow "${name}"?`)) return;
  try {
    await comfyPost({remove_workflow: name});
    await loadComfy();
    toast("success", "Workflow removed", name);
  } catch (e) {
    toast("error", "The workflow was not removed", e.message, 6000);
  }
}
async function comfyServerAction(action) {
  const buttons = ["image-start", "image-stop", "image-restart"];
  for (const id of buttons) $(id).disabled = true;
  const state = $("image-server-state");
  state.textContent = action === "start" ? "Starting… this can take a minute or two."
    : action === "stop" ? "Stopping…" : "Restarting…";
  try {
    const j = await comfyPost({[action]: true});
    comfyInfo = {...comfyInfo, server: j.server || {}, reachable: !!(j.server && j.server.up),
                 version: (j.server || {}).version};
    renderComfy();
    toast("success", action === "stop" ? "ComfyUI stopped" : "ComfyUI is running",
          (j.server || {}).hint || "");
  } catch (e) {
    state.textContent = e.message;
    toast("error", "The ComfyUI server was not changed", e.message, 9000);
  } finally {
    for (const id of buttons) $(id).disabled = false;
  }
}
function openImagesDialog() {
  closeSettings();
  comfyCheck = null;
  $("image-dialog").showModal();
  loadComfy();
}
$("images-open").onclick = () => openImagesDialog();
$("image-close").onclick = () => $("image-dialog").close();
// A footer Close on every settings dialog: on a phone the dialog is full screen, Save keeps it open, and a tap that
// misses the header's X would leave nothing to do.
document.addEventListener("click", (e) => {
  const button = e.target.closest("[data-dialog-close]");
  if (!button) return;
  const dialog = $(button.dataset.dialogClose);
  if (dialog && dialog.open) dialog.close();
});
$("image-dialog").addEventListener("click", (e) => { if (e.target === $("image-dialog")) $("image-dialog").close(); });
$("image-save").onclick = () => saveComfy(false);
$("image-start").onclick = () => comfyServerAction("start");
$("image-stop").onclick = () => comfyServerAction("stop");
$("image-restart").onclick = () => comfyServerAction("restart");
$("image-auto-start").onclick = () => $("image-auto-start").setAttribute(
  "aria-checked", String($("image-auto-start").getAttribute("aria-checked") !== "true"));
$("image-check").onclick = async () => {
  const out = $("image-check-result");
  out.className = "muted small";
  out.textContent = "Checking…";
  $("image-check").disabled = true;
  try {
    const j = await comfyPost({check: true});
    comfyCheck = j.check;
  } catch (e) {
    out.className = "muted small mcp-msg-bad";
    out.textContent = e.message;
  } finally {
    $("image-check").disabled = false;
  }
  renderComfyWorkflows();
  renderComfyCheck();
};
$("image-import").onclick = () => $("image-file").click();
$("image-file").onchange = async () => {
  const file = $("image-file").files[0];
  if (!file) return;
  try {
    const text = await file.text();
    const name = file.name.replace(/\.json$/i, "");
    await comfyPost({import: {name, json: text}});
    await loadComfy();
    toast("success", "Workflow imported", name);
  } catch (e) {
    toast("error", "That workflow was not imported", e.message, 8000);
  } finally {
    $("image-file").value = "";
  }
};
$("image-url").oninput = () => {
  const url = $("image-url").value.trim();
  $("image-url-note").textContent = !url ? "" : /^https?:\/\/[^\s/]+/i.test(url) ? ""
    : "Start with http:// or https://, and leave out ?query and #hash.";
};

// ------------------------------------------------------------------ Models view (GET /api/models)
// One card per installed run config: what the model is, what it needs, and its actions — Load/Unload (the engine in
// memory) and Settings (the full-page editor below). The composer's chip and menu still switch quickly.
function paramsText(n) {
  if (n == null) return "";
  return n >= 1e9 ? (n / 1e9).toFixed(1) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : String(n);
}
let modelList = [];
async function loadModelsView() {
  const wrap = $("models-cards");
  try {
    const r = await fetch("api/models", {headers: headers()});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    modelList = (await r.json()).models || [];
  } catch (e) {
    $("models-note").textContent = "";
    wrap.innerHTML = `<p class="muted">Could not load models: ${esc(e.message || e)}</p>`;
    return;
  }
  $("models-note").textContent = `${modelList.length} model${modelList.length === 1 ? "" : "s"}`;
  if (!modelList.length) {
    wrap.innerHTML = `<p class="muted">No models found. Setup writes a run config (strata-*.json) beside the server when it installs a model.</p>`;
    return;
  }
  wrap.innerHTML = modelList.map((m) => {
    const bad = m.status === "unavailable";
    const badge = m.current ? "st-badge st-badge--generating" : bad ? "st-badge st-badge--error" : "st-badge st-badge--reading";
    const stat = m.current ? (m.status === "loading" ? "loading" : m.status === "loaded" ? "loaded" : "unloaded")
                           : bad ? "unavailable" : "ready";
    const chips = [];
    if (m.backend) chips.push(`<span class="chip-info">${icon("cpu", "st-icon st-icon--sm")} ${esc(m.backend)}</span>`);
    if (m.quantization) chips.push(`<span class="chip-info"><b>${esc(m.quantization)}</b></span>`);
    if (m.params_active != null) chips.push(`<span class="chip-info">${icon("experts", "st-icon st-icon--sm")} <b>${paramsText(m.params_active)}</b> active</span>`);
    else if (m.params_total != null) chips.push(`<span class="chip-info"><b>${paramsText(m.params_total)}</b></span>`);
    if (m.context) chips.push(`<span class="chip-info">${icon("layers", "st-icon st-icon--sm")} <b>${ctxfmt(m.context)}</b></span>`);
    if (m.multimodal) chips.push(`<span class="chip-info">${icon("image", "st-icon st-icon--sm")} vision</span>`);
    if (m.mtp) chips.push(`<span class="chip-info">${icon("bolt", "st-icon st-icon--sm")} MTP</span>`);
    const actions = [];
    if (m.current) {
      if (m.status === "loaded") actions.push(`<button class="st-btn st-btn--secondary" type="button" data-unload="${esc(m.id)}">${icon("stop", "st-icon st-icon--sm")} Unload</button>`);
    } else {
      actions.push(`<button class="st-btn st-btn--primary" type="button" data-load="${esc(m.id)}"${bad ? " disabled" : ""}>${icon("play", "st-icon st-icon--sm")} Load</button>`);
    }
    actions.push(`<button class="st-btn st-btn--secondary" type="button" data-configure="${esc(m.id)}">${icon("settings", "st-icon st-icon--sm")} Settings</button>`);
    return `<article class="model-card" data-current="${m.current ? "true" : "false"}">
      <div class="card-head"><div class="card-head__titles">
        <span class="card-title-lg">${esc(m.display_name || m.id)}</span>
        <span class="card-sub">${esc(m.id)}</span></div>
        <span class="${badge}">${stat}</span></div>
      <div class="card-chips">${chips.join("")}</div>
      ${m.problem ? `<p class="cfg-note">${esc(m.problem)}</p>` : ""}
      <div class="card-actions">${actions.join("")}</div></article>`;
  }).join("");
}
async function unloadModel() {
  if (busy) { toast("warn", "Still writing", "Stop the answer first."); return; }
  try {
    const r = await fetch("api/models/unload", {method: "POST", headers: headers(true), body: "{}"});
    const b = await r.json();
    if (!r.ok) throw new Error((b.error || {}).message || `HTTP ${r.status}`);
    toast("success", "Model unloaded", "The next request — or Load — starts it again.");
  } catch (e) { toast("error", "Not unloaded", String(e.message || e), 9000); }
  await loadHealth(); await loadModels(); await loadModelsView();
}
async function loadModelNow(id) {
  // the current model, unloaded: start it again (switchModel refuses a "switch" to the model that is already selected)
  if (busy) { toast("warn", "Still writing", "Stop the answer first."); return; }
  toast("info", `Loading ${id}`, "The engine starts …", 8000);
  let message = "";
  try {
    const r = await fetch("api/models/load", {method: "POST", headers: headers(true), body: JSON.stringify({model: id})});
    if (!r.ok) message = ((await r.json()).error || {}).message || `the server answered ${r.status}`;
  } catch (e) { message = String(e); }
  await loadHealth(); await loadModels(); await loadModelsView();
  if (message) toast("error", "The model was not loaded", message, 10000);
  else toast("success", `${id} is loaded`, "");
}
$("models-cards").addEventListener("click", (e) => {
  const load = e.target.closest("[data-load]");
  if (load && !load.disabled) {
    if (load.dataset.load === $("model-select").dataset.current) loadModelNow(load.dataset.load);
    else switchModel(load.dataset.load);
    return;
  }
  const un = e.target.closest("[data-unload]");
  if (un) { unloadModel(); return; }
  const conf = e.target.closest("[data-configure]");
  if (conf) openConfigPage(conf.dataset.configure);
});

// ------------------------------------------------------------------ Engines view (GET /api/engines)
// One card per engine of engines.json: pinned and installed version, CUDA archs, provenance links, and the run
// configs that use it. Repair runs setup.py --repair-engines in the background, only when the server was started
// with --allow-engine-repair.
function engStatusLabel(s) { return {current: "current", outdated: "outdated", missing: "missing", manual: "manual", unknown: "unknown"}[s] || s; }
function engBadge(s) {
  return s === "current" ? "st-badge st-badge--generating" : s === "outdated" ? "st-badge st-badge--queued"
    : s === "missing" ? "st-badge st-badge--error" : "st-badge";
}
async function loadEngines() {
  const wrap = $("engines-cards");
  let data;
  try {
    const r = await fetch("api/engines", {headers: headers()});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    data = await r.json();
  } catch (e) {
    $("engines-note").textContent = "";
    wrap.innerHTML = `<p class="muted">Could not load engines: ${esc(e.message || e)}</p>`;
    return;
  }
  const engs = data.engines || [];
  const used = data.used_by || {};
  $("engines-note").textContent = data.release ? `pinned release ${data.release}` : "";
  if (!engs.length) { wrap.innerHTML = `<p class="muted">No engines</p>`; return; }
  wrap.innerHTML = engs.map((e) => {
    const users = used[e.key] || [];
    const links = [];
    if (e.upstream) links.push(`<a href="${esc(e.upstream)}" target="_blank" rel="noopener noreferrer">source ${icon("external", "st-icon st-icon--sm")}</a>`);
    if (e.release) links.push(`<a href="${esc(e.release)}" target="_blank" rel="noopener noreferrer">releases ${icon("external", "st-icon st-icon--sm")}</a>`);
    const rows = [
      `<div class="kv-line"><b>binary</b> <code>${esc(e.dir)}/${esc(e.binary)}</code></div>`,
      `<div class="kv-line"><b>pinned</b> <span>${esc(e.version || "—")}${e.required ? " · required" : ""}${e.manual ? " · manual build" : ""}</span></div>`,
      `<div class="kv-line"><b>installed</b> <span>${esc(e.installed_version || "—")}</span></div>`,
    ];
    if (Array.isArray(e.archs) && e.archs.length) rows.push(`<div class="kv-line"><b>cuda archs</b> <span>${esc(e.archs.join(", "))}</span></div>`);
    if (e.cuda) rows.push(`<div class="kv-line"><b>cuda</b> <span>${esc(String(e.cuda))}</span></div>`);
    if (e.core) rows.push(`<div class="kv-line"><b>core</b> <span>${esc(e.core)}${e.core_commit ? ` @ ${esc(String(e.core_commit).slice(0, 7))}` : ""}</span></div>`);
    if (e.source) rows.push(`<div class="kv-line"><b>source</b> <span>${esc(e.source)}</span></div>`);
    return `<article class="engine-card">
      <div class="card-head"><div class="card-head__titles">
        <span class="card-title-lg">${esc(e.title || e.key)}</span><span class="card-sub">${esc(e.key)}</span></div>
        <span class="${engBadge(e.status)} eng-status">${esc(engStatusLabel(e.status))}</span></div>
      ${rows.join("")}
      ${links.length ? `<div class="engine-links">${links.join("")}</div>` : ""}
      <div class="kv-line"><b>used by</b> <span class="used-by">${users.length ? users.map((u) => `<span class="chip-info">${esc(u)}</span>`).join("") : "—"}</span></div>
    </article>`;
  }).join("");
}
$("engines-repair").addEventListener("click", async () => {
  $("engines-msg").textContent = "";
  try {
    const r = await fetch("api/engines/repair", {method: "POST", headers: headers(true), body: "{}"});
    const b = await r.json();
    if (!r.ok) throw new Error((b.error || {}).message || `HTTP ${r.status}`);
    $("engines-msg").textContent = b.note || "Repair started.";
    toast("info", "Repair started", "The engines download and install in the background.", 8000);
  } catch (e) {
    $("engines-msg").textContent = "";
    toast("error", "Repair not started", String(e.message || e), 8000);
  }
});

// ------------------------------------------------------------------ Model settings page (GET/POST /api/models/config)
// A whole view for one model's run config: a rail to switch model, section cards for every knob the schema knows
// (sliders where a range is known, a file browser for every path), and a Changes rail with the pending diff.
// Saving is all-or-nothing: the server checks every value before the file is written, and keeps the old one as .bak.
let cfgModel = null;             // the model id being edited (null: the server's current run config)
let cfgView = null;              // the last view: {file, groups, note, raw, efforts}
let cfgEngines = [];             // engine inventory, for the exe picker
let cfgExeTouched = false;       // exe is only sent after the user moved the picker (a legacy path must survive)
let cfgThinkTouched = false;     // reasoning_effort only after a row was clicked
let cfgBudgetTouched = false;    // reasoning_budget_by_effort only after a cap was edited
const cfgId = (key) => `cfgk-${String(key).replace(/[^a-zA-Z0-9]/g, "-")}`;
const cfgFlagId = (key, flag) => `${cfgId(key)}-f-${String(flag).replace(/[^a-zA-Z0-9]/g, "-")}`;
const NUMERIC_KIND = /^(int>=0|num>=0|0<x<=1|0<=x<=1|1\.\.64|num>0|int>0|int|num)$/;
const INT_KIND = /^(int>=0|int>0|int)$/;
// The sampling chips come from the catalog (serve/configschema.py SAMPLING_PRESETS), not from here: their
// values have to pass the same kind and range checks a hand edit does, and that can only be checked in one
// place.  A preset that only moved the temperature left every other sampler where the file had it, which is
// why "Precise" and "Creative" used to produce the same kind of text.
function samplingPresets() {
  return (cfgView && cfgView.sampling_presets) || [];
}
const PATH_BROWSE = {                                    // string keys that get a Browse… button
  "vision.exe": {want: "file", ext: ".exe"},
  "vision.mmproj": {want: "file", ext: ".gguf"},
  "vision.model": {want: "file", ext: ""},
  "cwd": {want: "dir", ext: ""},
};

// one control for one kind; the label (with its live <output>) is added by cfgFieldHtml
// The placeholder is the value the engine uses when the setting is absent, so an empty field still
// says what happens if you leave it alone ("engine default" when nothing is documented).
function cfgPlaceholder(def) {
  if (def == null || def === "") return "default";
  if (typeof def === "boolean") return def ? "on" : "off";
  return String(def);
}
function sliderNumber(id, range, value, label, anyStep, ph, def) {
  const [min, max, step] = range;
  const has = value != null && value !== "";
  // Unset shows the documented default under the handle, so the picture matches what the engine does;
  // the number box stays empty, which is how "follow the default" is stored.
  const shown = has ? value : (def != null && def !== "" && !isNaN(Number(def)) ? def : null);
  const pos = shown == null ? min : Math.min(max, Math.max(min, Number(shown)));
  return `<span class="cfg-slider">` +
    `<input class="st-slider" type="range" id="${id}-r" min="${min}" max="${max}" step="${step}" value="${pos}" aria-label="${esc(label)} slider">` +
    `<input class="st-input" type="number" id="${id}" min="${min}" max="${max}" step="${anyStep ? "any" : step}" ` +
    `value="${has ? esc(String(value)) : ""}" placeholder="${esc(ph || "default")}" autocomplete="off" aria-label="${esc(label)}"></span>`;
}
function cfgControl(k, id, ph) {
  const v = k.value;
  // the accessible name is the plain-language label; the long help lives under the control
  const label = k.label || k.key;
  if (k.kind === "bool") {
    return `<button class="st-toggle" type="button" role="switch" id="${id}" aria-checked="${v === true}" aria-label="${esc(label)}"></button>`;
  }
  if (k.kind === "enum") {
    const cur = v == null ? "" : String(v);
    return `<select class="st-input" id="${id}" aria-label="${esc(label)}"><option value=""${cur === "" ? " selected" : ""}>default</option>` +
      (k.choices || []).map((x) => `<option value="${esc(x)}"${cur === x ? " selected" : ""}>${esc(x)}</option>`).join("") + `</select>`;
  }
  if (k.kind === "object") {
    const pairs = v == null ? [] : Object.entries(v);
    return `<div class="kv-grid">` + pairs.map(([kk, vv]) =>
      `<div class="kv-row"><input class="st-input" type="text" value="${esc(kk)}" data-kv-key="${id}" aria-label="Name">` +
      `<input class="st-input" type="text" value="${esc(vv ?? "")}" data-kv-val="${id}" aria-label="Value">` +
      `<button class="st-btn st-btn--icon" type="button" data-kv-del="${id}" aria-label="Remove">${icon("x")}</button></div>`).join("") +
      `<button class="st-btn st-btn--secondary" type="button" data-kv-add="${id}">Add</button></div>`;
  }
  if (k.kind === "list") {
    const rows = (v || []).map((vv) =>
      `<div class="list-row"><input class="st-input" type="text" value="${esc(vv ?? "")}" data-list-val="${id}" aria-label="Entry">` +
      `<button class="st-btn st-btn--icon" type="button" data-list-del="${id}" aria-label="Remove">${icon("x")}</button></div>`).join("");
    return `<div class="kv-grid">${rows}<button class="st-btn st-btn--secondary" type="button" data-list-add="${id}">Add</button></div>`;
  }
  if (k.kind === "readonly") {
    return `<div class="cfg-readonly" id="${id}">${v == null || v === "" ? "—" : esc(String(v))}</div>`;
  }
  if (NUMERIC_KIND.test(k.kind)) {
    if (k.range) return sliderNumber(id, k.range, v, label, !INT_KIND.test(k.kind), ph, k.default);
    return `<input class="st-input" id="${id}" type="number" step="any" value="${v == null ? "" : esc(String(v))}" placeholder="${esc(ph || "default")}" autocomplete="off" aria-label="${esc(label)}">`;
  }
  const text = v == null ? "" : Array.isArray(v) ? v.join(", ") : String(v);
  const inp = `<input class="st-input" id="${id}" type="text" value="${esc(text)}" placeholder="${esc(ph || "default")}" autocomplete="off" spellcheck="false" aria-label="${esc(label)}">`;
  // every path field browses: the known keys keep their own filter, anything the schema calls a path gets the
  // plain picker, so no setting asks the user to type a directory by hand.
  const br = PATH_BROWSE[k.key] || (k.kind === "path" ? {want: "file", ext: ""} : null);
  if (br) {
    return `<span class="cfg-path">${inp}<button class="st-btn st-btn--secondary" type="button" data-browse="${id}" ` +
      `data-want="${br.want}" data-ext="${br.ext}" aria-label="Browse for ${esc(label)}">${icon("folder", "st-icon st-icon--sm")}</button></span>`;
  }
  return inp;
}
// One field row: the plain-language name with the raw key beside it, and the tools on the right - a hint
// carrying the default, a "changed" pill, and Reset. The explanation sits under the control, so the label
// stays a name rather than a paragraph.
// The "?" tooltip: the facts a hint under the field cannot carry - what the value means, what it may be,
// whether this engine takes the setting at all, and what the file holds right now.  It used to print
// "Default: the engine decides" on every row, which told a reader nothing.
function cfgTip({tag, kind, unit, def, range, risk, applicable, base, known}) {
  const parts = [];
  if (tag) parts.push(tag);
  const kindName = {bool: "on or off", enum: "a choice", int: "a whole number", num: "a number",
                    text: "text", path: "a file or folder", object: "a group of values",
                    list: "a list", readonly: "read-only", args: "the engine's flags"}[kind];
  if (kindName) parts.push(kindName);
  if (def != null && def !== "") parts.push(`default ${def}${unit ? ` ${unit}` : ""}`);
  else if (known === false) parts.push("no default: the engine takes it from the model");
  if (range) parts.push(`allowed ${range[0]} to ${range[1]}${range[2] ? `, steps of ${range[2]}` : ""}`);
  if (applicable === false) parts.push("this engine does not list it, but the file may still set it");
  const now = base == null || base === "" ? "empty" : String(base);
  parts.push(base == null || base === "" ? "not set in the file" : `in the file: ${now}`);
  if (risk === "quality") parts.push("Changes the words the model produces");
  return parts.join(" · ");
}
function fieldShell({id, label, tag, help, unit, base, def, risk, control, extra, tip}) {
  const text = tip || ("Default: " + (def == null || def === "" ? "no documented value" : String(def)));
  return `<div class="cfg-field" data-base="${esc(base == null ? "" : String(base))}" data-def="${esc(def == null ? "" : String(def))}">
    <div class="cfg-head"><label class="st-label" for="${id}"><span class="cfg-name">${esc(label)}</span><code>${esc(tag)}</code>${extra || ""}</label>
    <span class="cfg-tools"><span class="cfg-pill" data-pill="changed"${risk === "quality" ? ` title="Changes the words the model produces"` : ""} hidden>changed</span><button class="st-btn st-btn--text cfg-reset" type="button" data-reset="${id}">Reset</button><span class="st-tip" tabindex="0" role="note" aria-label="About ${esc(tag)}" data-tip="${esc(text)}">?</span></span></div>
    <div class="cfg-body">${control}${unit ? `<span class="cfg-unit">${esc(unit)}</span>` : ""}</div>
    ${help ? `<p class="cfg-hint">${esc(help)}</p>` : ""}</div>`;
}
function cfgFieldHtml(k) {
  const id = cfgId(k.key);
  const out = k.range && NUMERIC_KIND.test(k.kind) ? ` <output id="${id}-o">${k.value == null ? "" : esc(String(k.value))}</output>` : "";
  return fieldShell({
    id, label: k.label || k.help || k.key, tag: k.key, help: k.help, unit: k.unit, base: k.value, def: k.default,
    risk: k.risk, extra: out, control: cfgControl(k, id, cfgPlaceholder(k.default)),
    tip: cfgTip({tag: k.key, kind: k.kind, unit: k.unit, def: k.default, range: k.range, risk: k.risk,
                 base: k.value}),
  }).replace('class="cfg-field"', `class="cfg-field" data-key="${esc(k.key)}" data-advanced="${k.advanced ? "true" : "false"}" data-hidden="${k.advanced ? "true" : "false"}"`);
}
function flagControl(f, id, ph) {
  const label = f.label || f.flag;
  if (f.kind === "bool") {
    return `<button class="st-toggle" type="button" role="switch" id="${id}" aria-checked="${f.value === true}" aria-label="${esc(label)}"></button>`;
  }
  if (f.kind === "enum") {
    const cur = f.value == null ? "" : String(f.value);
    return `<select class="st-input" id="${id}" aria-label="${esc(label)}"><option value=""${cur === "" ? " selected" : ""}>default</option>` +
      (f.choices || []).map((x) => `<option value="${esc(x)}"${cur === x ? " selected" : ""}>${esc(x)}</option>`).join("") + `</select>`;
  }
  if (f.kind === "int" || f.kind === "num") {
    if (f.range) return sliderNumber(id, f.range, f.value, label, f.kind === "num", ph, f.default);
    return `<input class="st-input" id="${id}" type="number" step="any" value="${f.value == null ? "" : esc(String(f.value))}" placeholder="${esc(ph || "default")}" autocomplete="off" aria-label="${esc(label)}">`;
  }
  // a documented set of values becomes a list the field offers as you type: "--prefill auto|4096|8192" needs a
  // starting point, but it is not an enum (any chunk size is legal), so it must stay typeable.
  const sug = Array.isArray(f.suggest) && f.suggest.length
    ? `<datalist id="${id}-dl">${f.suggest.map((s) => `<option value="${esc(String(s))}"></option>`).join("")}</datalist>` : "";
  const inp = `<input class="st-input" id="${id}" type="text" value="${f.value == null ? "" : esc(String(f.value))}" placeholder="${esc(ph || "default")}" autocomplete="off" spellcheck="false" aria-label="${esc(label)}"${sug ? ` list="${id}-dl"` : ""}>`;
  if (f.kind === "path") {
    return `<span class="cfg-path">${inp}<button class="st-btn st-btn--secondary" type="button" data-browse="${id}" ` +
      `data-want="file" data-ext="" aria-label="Browse for ${esc(label)}">${icon("folder", "st-icon st-icon--sm")}</button></span>${sug}`;
  }
  return inp + sug;
}
function flagFieldHtml(f) {
  const key = "args";
  const id = cfgFlagId(key, f.flag);
  const out = f.range && (f.kind === "int" || f.kind === "num") ? ` <output id="${id}-o">${f.value == null ? "" : esc(String(f.value))}</output>` : "";
  return fieldShell({
    id, label: f.label || f.help || f.flag, tag: f.flag, help: f.help, unit: f.unit, base: f.value, def: f.default,
    risk: f.risk, extra: out, control: flagControl(f, id, cfgPlaceholder(f.default)),
    tip: cfgTip({tag: f.flag, kind: f.kind, unit: f.unit, def: f.default, range: f.range, risk: f.risk,
                 applicable: f.applicable, base: f.value}),
  }).replace('class="cfg-field"', `class="cfg-field" data-flag="${esc(f.flag)}"`);
}
// ---- environment variables (the knobs with no flag) --------------------------------------------------------
// A variable is stored as text in the file, so every control writes the text the engine parses: an int a number,
// a bool "1"/"0" with an empty option that means "not set, use the engine's default". A name the catalog does not
// know is still a row, because a variable set by hand must not become invisible in the editor.
function envValue(e) {
  return e.value == null ? "" : String(e.value);
}
function envControl(e, id) {
  const cur = envValue(e);
  const ph = cfgPlaceholder(e.default);
  const label = e.label || e.name;
  if (e.kind === "bool") {
    const tri = cur.trim() === "" ? "" : (cur.trim() === "0" ? "0" : "1");
    return `<select class="st-input" id="${id}" aria-label="${esc(label)}">` +
      `<option value=""${tri === "" ? " selected" : ""}>default</option>` +
      `<option value="1"${tri === "1" ? " selected" : ""}>on</option>` +
      `<option value="0"${tri === "0" ? " selected" : ""}>off</option></select>`;
  }
  if (e.kind === "int" || e.kind === "num") {
    const n = cur.trim() === "" ? null : Number(cur);
    if (e.range) return sliderNumber(id, e.range, Number.isNaN(n) ? null : n, label, e.kind === "num", ph, e.default);
    return `<input class="st-input" id="${id}" type="number" step="any" value="${esc(cur)}" placeholder="${esc(ph)}" autocomplete="off" aria-label="${esc(label)}">`;
  }
  return `<input class="st-input" id="${id}" type="text" value="${esc(cur)}" placeholder="${esc(ph)}" autocomplete="off" spellcheck="false" aria-label="${esc(label)}">`;
}
function envRowHtml(e) {
  const id = `cfgenv-${e.name.replace(/[^A-Za-z0-9]/g, "-")}`;
  const out = e.range && (e.kind === "int" || e.kind === "num")
    ? ` <output id="${id}-o">${e.value == null ? "" : esc(String(e.value))}</output>` : "";
  const adv = e.advanced ? ` data-advanced="true" data-hidden="true"` : "";
  return fieldShell({
    id, label: e.label || e.name, tag: e.name, help: e.help, unit: e.unit, base: envValue(e),
    def: e.default, risk: e.risk, extra: out, control: envControl(e, id),
    tip: cfgTip({tag: e.name, kind: e.kind, unit: e.unit, def: e.default, range: e.range, risk: e.risk,
                 base: envValue(e)}),
  }).replace('class="cfg-field"', `class="cfg-field" data-env="${esc(e.name)}" data-env-kind="${esc(e.kind)}"${adv}`);
}
function unknownEnvRow(name, value) {
  return `<div class="kv-row" data-env-unknown>
    <input class="st-input" type="text" value="${esc(name || "")}" placeholder="NAME" data-env-name aria-label="Variable name" autocomplete="off" spellcheck="false">
    <input class="st-input" type="text" value="${esc(value || "")}" placeholder="value" data-env-val aria-label="Variable value" autocomplete="off" spellcheck="false">
    <button class="st-btn st-btn--icon" type="button" data-env-del aria-label="Remove">${icon("x")}</button></div>`;
}
function envAddRow() {
  const known = ((cfgView && cfgView.engine && cfgView.engine.env) || []).map((e) => e.name);
  return `<datalist id="cfg-env-names">${known.map((n) => `<option value="${esc(n)}"></option>`).join("")}</datalist>
    <div class="kv-row" data-env-unknown>
    <input class="st-input" type="text" list="cfg-env-names" placeholder="NAME" data-env-name aria-label="New variable name" autocomplete="off" spellcheck="false">
    <input class="st-input" type="text" placeholder="value" data-env-val aria-label="New variable value" autocomplete="off" spellcheck="false">
    <button class="st-btn st-btn--icon" type="button" data-env-del aria-label="Remove">${icon("x")}</button></div>`;
}
function envSection(advanced) {
  const eng = (cfgView && cfgView.engine) || {};
  const items = (eng.env || []).filter((e) => Boolean(e.advanced) === Boolean(advanced));
  const known = (eng.env || []).length;
  let rows = items.map(envRowHtml).join("");
  if (!advanced) {
    const vals = eng.unknown_env_values || {};
    rows += (eng.unknown_env || []).map((n) => unknownEnvRow(n, vals[n])).join("");
    rows += envAddRow();
  }
  if (!rows) return "";
  const title = advanced ? "More environment" : "Environment";
  return `<div class="flag-group"><div class="flag-group__title">${esc(title)}</div>
    <p class="cfg-note">Variables the engine reads at startup, for the settings that have no command-line flag.
      Empty means "not set": the engine's own default applies.</p>
    <div class="cfg-fields">${rows}</div></div>`;
}
// read every env row back into the file's shape: {NAME: "text"}, an empty value leaving the name out
function collectEnv() {
  const out = {};
  document.querySelectorAll(".cfg-field[data-env]").forEach((f) => {
    const name = f.dataset.env;
    const kind = f.dataset.envKind;
    const sel = f.querySelector("select");
    const num = f.querySelector("input[type=number]");
    const txt = f.querySelector("input[type=text]");
    let v = "";
    if (kind === "bool") v = sel ? sel.value : "";
    else if (kind === "int" || kind === "num") v = num && num.value.trim() !== "" ? num.value.trim() : "";
    else v = txt ? txt.value.trim() : "";
    if (v !== "") out[name] = String(v);
  });
  document.querySelectorAll("[data-env-unknown]").forEach((row) => {
    const n = row.querySelector("[data-env-name]");
    const v = row.querySelector("[data-env-val]");
    if (!n || !v) return;
    const name = n.value.trim();
    const val = v.value.trim();
    if (name && val !== "") out[name] = val;
  });
  return out;
}
function sameEnv(a, b) {
  const norm = (o) => Object.entries(o || {}).map(([k, v]) => [String(k), String(v)]).sort((x, y) => (x[0] < y[0] ? -1 : 1));
  return JSON.stringify(norm(a)) === JSON.stringify(norm(b));
}
// A field goes back to the value the file holds; a card does it for every field it holds. Neither writes:
// the Changes rail follows, and Save stays the only thing that touches the file.
function cfgResetField(field) {
  if (!field || field.dataset.base == null) return;
  const base = field.dataset.base ?? "";
  const tgl = field.querySelector(".st-toggle");
  const box = field.querySelector("select") || field.querySelector("input[type=number]") || field.querySelector("input[type=text]");
  if (tgl) tgl.setAttribute("aria-checked", String(base === "true"));
  if (box) box.value = base;
  const r = field.querySelector('input[type="range"]'), o = field.querySelector("output");
  if (r) r.value = base === "" ? r.min : base;
  if (o) o.textContent = base;
  cfgValidateField(field);
  cfgSyncPill(box || tgl || field);
}
function cfgResetCard(cardId) {
  const card = document.getElementById(cardId);
  if (!card) return;
  card.querySelectorAll(".cfg-field[data-base]").forEach(cfgResetField);
  cfgMarkDirty();
}
function cfgResetAll() {
  document.querySelectorAll("#cfg-sections .cfg-field[data-base]").forEach(cfgResetField);
  cfgMarkDirty();
}
// A card title carries one Reset for the group, shown only when something in the group differs from the file.
function cfgCardTitle(cardId, iconName, label) {
  return `<h3 class="set-card__title">${icon(iconName, "st-icon st-icon--sm")} ${esc(label)}` +
    `<button class="st-btn st-btn--text cfg-card-reset" type="button" data-card-reset="${esc(cardId)}" hidden>Reset card</button></h3>`;
}
function cfgSyncCardResets() {
  document.querySelectorAll("[data-card-reset]").forEach((b) => {
    const card = document.getElementById(b.dataset.cardReset);
    b.hidden = !(card && card.querySelector('.cfg-field[data-changed="true"]'));
  });
}
// A value outside the range the control states is caught here instead of by the server after Save: the field says
// what is wrong, and Save stays disabled until it is fixed.
function cfgValidateField(field) {
  if (!field) return true;
  const num = field.querySelector("input[type=number]");
  let bad = "";
  if (num && num.value.trim() !== "") {
    const n = Number(num.value);
    const lo = num.min === "" ? null : Number(num.min);
    const hi = num.max === "" ? null : Number(num.max);
    if (Number.isNaN(n)) bad = "Type a number.";
    else if (lo != null && n < lo) bad = `The smallest value here is ${lo}.`;
    else if (hi != null && n > hi) bad = `The largest value here is ${hi}.`;
  }
  field.dataset.invalid = bad ? "true" : "false";
  let err = field.querySelector(".cfg-error");
  if (bad) {
    if (!err) { err = document.createElement("p"); err.className = "cfg-error"; field.appendChild(err); }
    err.textContent = bad;
    if (num) num.setAttribute("aria-invalid", "true");
  } else {
    if (err) err.remove();
    if (num) num.removeAttribute("aria-invalid");
  }
  return !bad;
}
// A field is "changed" when its control no longer holds the value the file had. Reset puts that value back,
// so the pill is the same signal the Changes rail uses: pending here, not yet saved.
function cfgFieldOf(el) {
  return el && el.closest ? el.closest(".cfg-field") : null;
}
function cfgSyncPill(el) {
  const field = cfgFieldOf(el);
  if (!field) return;
  const tgl = field.querySelector(".st-toggle");
  // the value control, not the slider that drives it: a slider row's range input always holds a number, so
  // reading it would report "changed" for a field that is back at the file's (empty) value.
  const box = field.querySelector('select, input:not([type="range"]), textarea');
  const base = field.dataset.base === "" && tgl ? "false" : (field.dataset.base ?? "");
  const cur = tgl ? (tgl.getAttribute("aria-checked") === "true" ? "true" : "false")
                  : (box && box.value != null ? String(box.value) : "");
  const changed = cur !== base;
  field.dataset.changed = changed ? "true" : "false";
  const pill = field.querySelector('[data-pill="changed"]');
  if (pill) pill.hidden = !changed;
}

// The Thinking card is the honest effort knob: one row per level with the sentence it puts in the prompt and the
// cap it applies. A row click picks the default level; the caps edit reasoning_budget_by_effort.
function thinkCard() {
  const findKey = (key) => {
    for (const g of cfgView.groups || []) for (const it of g.keys || []) if (it.key === key) return it;
    return null;
  };
  const eff = findKey("reasoning_effort") || {value: null};
  const auto = `<div class="think-row" role="radio" tabindex="0" aria-checked="${eff.value == null || eff.value === ""}" data-level="" data-open="true" data-plain="true">
    <span class="think-row__level" data-name="Auto">Auto</span>
    <span class="think-row__text">Not pinned here: every request picks its own level (the chat drawer and API calls decide).</span>
    <span class="think-row__budget"></span></div>`;
  const rows = (cfgView.efforts || []).map((e) => {
    const sel = eff.value === e.level;
    const budget = e.level === "none" ? `<span class="cfg-note">no cap — thinking off</span>`
      : sliderNumber(`think-${e.level}`, [0, 65536, 256], e.budget, `${e.level} thinking cap`, true);
    return `<div class="think-row" role="radio" tabindex="0" aria-checked="${sel}" data-level="${esc(e.level)}"${e.level === "none" ? ` data-open="true"` : ""}>
      <span class="think-row__level" data-name="${esc(e.level)}">${esc(e.level)}${sel ? ` ${icon("check", "st-icon st-icon--sm")}` : ""}</span>
      <span class="think-row__text">${esc(e.instruction || "")}</span>
      <span class="think-row__budget">${budget}</span></div>`;
  }).join("");
  const g = (cfgView.groups || []).find((x) => x.key === "reasoning") || {keys: []};
  const skip = new Set(["reasoning_effort", "reasoning_budget_by_effort"]);
  const rest = (g.keys || []).filter((k) => !skip.has(k.key));
  return `<section class="cfg-card" id="cfg-think">
    <h3 class="set-card__title">${icon("thinking", "st-icon st-icon--sm")} Thinking</h3>
    <p class="cfg-note">The level a request uses when it does not ask for one. It picks the instruction sentence below and
      the thinking cap — nothing else: your sampling settings stay exactly as they are. Click a sentence to read it in full.</p>
    <div class="think-rows" role="radiogroup" aria-label="Default thinking level">${auto}${rows}</div>
    <div class="cfg-fields">${rest.map(cfgFieldHtml).join("")}</div>
  </section>`;
}
// One click from a measured starting point. A chip fills the fields below as unsaved changes, so the
// Changes list shows exactly what it would write and Save stays the only thing that writes.
function presetCard() {
  const ps = (cfgView && cfgView.engine && cfgView.engine.presets) || [];
  if (!ps.length) return "";
  const chips = ps.map((p, i) =>
    `<button type="button" class="chip" data-preset="${i}" title="${esc(p.note || "")}" aria-pressed="false">${esc(p.label)}</button>`).join("");
  return `<section class="cfg-card" id="cfg-presets">
    <h3 class="set-card__title">${icon("bolt", "st-icon st-icon--sm")} Quick presets</h3>
    <p class="cfg-note">A measured starting point for this engine. A chip fills the fields below as an unsaved change; the Changes list shows exactly what it would write.</p>
    <div class="chips" role="group" aria-label="Engine presets">${chips}</div>
    <p class="cfg-note" data-preset-note></p>
  </section>`;
}
// Put one value into one field's control, whatever kind it is, and let the page's own listeners notice.
// Returns false when the field has no control this can write (a readonly row, or one the preset cannot reach).
function cfgSetValue(field, value) {
  if (!field) return false;
  const tgl = field.querySelector(".st-toggle");
  if (tgl) {
    tgl.setAttribute("aria-checked", String(value === true || value === "true"));
    tgl.dispatchEvent(new Event("input", {bubbles: true}));
    tgl.dispatchEvent(new Event("change", {bubbles: true}));
    return true;
  }
  const box = field.querySelector("select") || field.querySelector("input[type=number]") ||
              field.querySelector("input.st-input");
  if (!box) return false;
  box.value = String(value);
  // A slider row is two controls over one value: move the handle and its readout too, or the row shows a
  // number the handle disagrees with (a chip once left the handle parked at 64 while the box read 80).
  const range = field.querySelector('input[type="range"]');
  if (range && !Number.isNaN(Number(value))) {
    const n = Number(value);
    range.value = String(Math.min(Number(range.max), Math.max(Number(range.min), n)));
    const out = field.querySelector("output");
    if (out) out.textContent = String(value);
  }
  box.dispatchEvent(new Event("input", {bubbles: true}));
  box.dispatchEvent(new Event("change", {bubbles: true}));
  return true;
}
function cfgApplyPreset(i) {
  const ps = (cfgView && cfgView.engine && cfgView.engine.presets) || [];
  const p = ps[i];
  if (!p) return;
  const missing = [];
  let n = 0;
  for (const [flag, val] of Object.entries(p.flags || {})) {
    const field = Array.from(document.querySelectorAll(".cfg-field")).find((el) => el.dataset.flag === flag);
    if (!field) { missing.push(flag); continue; }
    if (cfgSetValue(field, val)) n += 1;
  }
  const note = document.querySelector("[data-preset-note]");
  if (note) {
    note.textContent = `${p.note || ""} Set ${n} setting${n === 1 ? "" : "s"} as an unsaved change` +
      (p.stays ? `. ${p.stays}` : ".") + (missing.length ? `  Not in this editor: ${missing.join(", ")}.` : "");
  }
  document.querySelectorAll("[data-preset]").forEach((c) =>
    c.setAttribute("aria-pressed", String(Number(c.dataset.preset) === i)));
  cfgMarkDirty();
}
function samplingCard() {
  const g = (cfgView.groups || []).find((x) => x.key === "sampling");
  if (!g) return "";
  const ps = samplingPresets();
  if (!ps.length) return "";
  const cur = {};
  for (const k of g.keys || []) {
    if (k.key in (ps[0].values || {})) cur[k.key] = k.value == null ? null : Number(k.value);
  }
  const matches = (p) => Object.keys(p.values || {}).every((k) => cur[k] == null ? false : Math.abs(cur[k] - Number(p.values[k])) < 1e-9);
  const chips = ps.map((p, i) =>
    `<button type="button" class="chip" data-sampling-preset="${i}" title="${esc(p.note || "")}" ` +
    `aria-pressed="${matches(p)}">${esc(p.name)} ${esc(String(Number(p.values["sampling.temperature"])))}</button>`).join("");
  return `<section class="cfg-card" id="cfg-sampling">
    ${cfgCardTitle("cfg-sampling", "gauge", g.label)}
    <p class="cfg-note">Defaults for every request; the chat drawer and API calls override them per request.
      A chip sets every sampler below, not only the temperature.</p>
    <div class="chips" role="group" aria-label="Sampling presets">${chips}</div>
    <p class="cfg-note" id="cfg-sampling-note"></p>
    <div class="cfg-fields">${(g.keys || []).map(cfgFieldHtml).join("")}</div>
  </section>`;
}
function cfgApplySampling(i) {
  const p = samplingPresets()[i];
  if (!p) return;
  let n = 0;
  for (const [key, value] of Object.entries(p.values || {})) {
    const field = document.querySelector(`#cfg-sections .cfg-field[data-key="${CSS.escape(key)}"]`);
    if (field && cfgSetValue(field, String(value))) n += 1;
  }
  for (const c of document.querySelectorAll("#cfg-sampling [data-sampling-preset]")) {
    c.setAttribute("aria-pressed", String(Number(c.dataset.samplingPreset) === i));
  }
  const note = document.getElementById("cfg-sampling-note");
  if (note) note.textContent = `${p.name}: ${p.note} Set ${n} field${n === 1 ? "" : "s"} as an unsaved change.`;
  cfgMarkDirty();
}
function exeFieldHtml(k) {
  const id = cfgId("exe");
  const cur = k.value == null ? "" : String(k.value);
  const norm = cur.replace(/\\/g, "/").toLowerCase();
  const opts = cfgEngines.filter((e) => e.status !== "missing");
  let matched = "";
  for (const e of opts) {
    const p = `${e.dir}/${e.binary}`.replace(/\\/g, "/").toLowerCase();
    if (norm === p) { matched = `${e.dir}/${e.binary}`; break; }
  }
  const options = opts.map((e) => {
    const val = `${e.dir}/${e.binary}`;
    return `<option value="${esc(val)}"${matched.toLowerCase() === val.toLowerCase() ? " selected" : ""}>` +
      `${esc(e.title || e.key)} — ${esc(val)}${e.installed_version ? ` (${esc(e.installed_version)})` : ""}</option>`;
  }).join("");
  const custom = !matched;
  return `<div class="cfg-field" data-key="exe">
    <label class="st-label" for="${id}-sel">Engine executable<code>exe</code></label>
    <select class="st-input" id="${id}-sel" aria-label="Engine executable">${options}<option value="custom"${custom ? " selected" : ""}>Custom path…</option></select>
    <span class="cfg-path" id="${id}-wrap"${custom ? "" : " hidden"}>
      <input class="st-input" id="${id}" type="text" value="${esc(cur)}" placeholder="engine/strata.exe" autocomplete="off" spellcheck="false" aria-label="Engine executable path">
      <button class="st-btn st-btn--secondary" type="button" data-browse="${id}" data-want="file" data-ext=".exe" aria-label="Browse for the engine executable">${icon("folder", "st-icon st-icon--sm")}</button>
    </span>
  </div>`;
}
function engineCard() {
  const g = (cfgView.groups || []).find((x) => x.key === "engine");
  if (!g) return "";
  const byKey = Object.fromEntries((g.keys || []).map((k) => [k.key, k]));
  const advanced = new Set(["env", "lib_dirs", "cwd"]);           // those live in the Advanced collapse
  const rest = (g.keys || []).filter((k) => !advanced.has(k.key) && k.key !== "exe" && k.key !== "args");
  const args = byKey.args;
  const fgroups = args && args.flag_groups && args.flag_groups.length ? args.flag_groups
    : (args && args.flags ? [{key: "flags", label: "Engine flags", flags: args.flags}] : []);   // older server: no groups, render flat
  const groups = fgroups.map((fg) =>
    `<div class="flag-group"><div class="flag-group__title">${esc(fg.label)}</div>` +
    (fg.flags || []).map((f) => flagFieldHtml(f, args.key)).join("") + `</div>`).join("");
  return `<section class="cfg-card" id="cfg-engine">
    ${cfgCardTitle("cfg-engine", "cpu", g.label)}
    ${byKey.exe ? exeFieldHtml(byKey.exe) : ""}
    ${args ? `<div class="cfg-field" data-key="args"><label class="st-label">Engine flags<code>args</code></label>${groups}</div>` : ""}
    ${envSection(false)}
    <div class="cfg-fields">${rest.map(cfgFieldHtml).join("")}</div>
  </section>`;
}
function groupCard(key, iconName, note) {
  const g = (cfgView.groups || []).find((x) => x.key === key);
  if (!g || !(g.keys || []).length) return "";
  const id = `cfg-group-${key}`;
  return `<section class="cfg-card" id="${esc(id)}">
    ${cfgCardTitle(id, iconName, g.label)}
    ${note ? `<p class="cfg-note">${note}</p>` : ""}
    <div class="cfg-fields">${g.keys.map(cfgFieldHtml).join("")}</div>
  </section>`;
}
function advancedCard() {
  const g = (cfgView.groups || []).find((x) => x.key === "engine") || {keys: []};
  const byKey = Object.fromEntries((g.keys || []).map((k) => [k.key, k]));
  const fields = ["cwd", "lib_dirs"].map((n) => byKey[n]).filter(Boolean).map(cfgFieldHtml).join("");
  const other = byKey.args && (byKey.args.other || []).length
    ? `<div class="cfg-field"><label class="st-label">Other arguments<code>args</code></label>` +
      `<div class="other-args">${byKey.args.other.map((o) => `<code>${esc(o)}</code>`).join(" ")}</div>` +
      `<span class="cfg-note">Arguments this editor does not know; they pass through unchanged. Edit them in the file.</span></div>` : "";
  return `<details class="st-collapse" id="cfg-advanced">
    <summary>Advanced${icon("chevron", "st-icon st-icon--sm st-chev")}</summary>
    <div class="st-collapse__body"><div class="cfg-fields">${fields}${other}</div>
      ${envSection(true)}
      <div class="cfg-fields"><div class="cfg-field"><label class="st-label" for="config-raw">Raw run config<code>${esc(cfgView.file || "")}</code></label>
      <textarea class="st-input" id="config-raw" rows="14" readonly spellcheck="false">${esc(cfgView.raw || "")}</textarea>
      <span class="cfg-note">The file as stored. Every edit above is checked by the server before it is written, and the
        earlier file is kept as <code>.bak</code>.</span></div></div>
    </div></div>
  </details>`;
}
function renderFacts() {
  const g = (cfgView.groups || []).find((x) => x.key === "info");
  const rows = ((g && g.keys) || []).map((k) =>
    `<dt>${esc(k.key)}</dt><dd>${k.value == null || k.value === "" ? "—" : esc(String(k.value))}</dd>`).join("");
  $("cfg-facts").innerHTML = `<h3 class="set-card__title">${icon("info", "st-icon st-icon--sm")} Model facts</h3>
    <dl class="facts-grid">${rows || `<dt>—</dt><dd>nothing detected</dd>`}</dl>
    <p class="cfg-note">Detected from the run config and the model file; not editable.</p>`;
}
function renderSide() {
  // the Changes card is static markup (index.html); only the list, the facts and the button states are rendered
  renderFacts();
  cfgMarkDirty();
}
function renderRail() {
  $("cfg-rail").innerHTML = `<div class="rail-head">Run configs</div>` + modelList.map((m) =>
    `<button type="button" class="rail-card" data-cfg-model="${esc(m.id)}" aria-current="${m.id === cfgModel ? "true" : "false"}">
      <strong>${esc(m.display_name || m.id)}</strong><span>${esc(m.id)}</span>
      ${m.current ? `<span class="st-badge st-badge--generating rail-badge">${m.status === "loaded" ? "loaded" : "current"}</span>` : ""}
    </button>`).join("");
}
function renderSections() {
  $("cfg-sections").innerHTML = presetCard() + thinkCard() + samplingCard() + engineCard() +
    groupCard("vision", "image", "The external encoder for picture inputs; empty when the model has no vision.") +
    groupCard("behavior", "bolt") + groupCard("lifecycle", "clock") + groupCard("identity", "cube") + advancedCard();
  cfgApplyAdvanced();
  cfgMarkDirty();
}
// Advanced settings stay collapsed until asked for: they are real knobs, but a page that opens with 80 of them
// is one a new user closes.  The choice is remembered, and a field the file already sets is never hidden.
function cfgShowAdvanced() {
  try { return localStorage.getItem("cfg-advanced") === "1"; } catch (e) { return false; }
}
function cfgApplyAdvanced() {
  const show = cfgShowAdvanced();
  for (const f of document.querySelectorAll('#cfg-sections .cfg-field[data-advanced="true"]')) {
    f.dataset.hidden = show || f.dataset.changed === "true" ? "false" : "true";
  }
  const box = $("cfg-show-advanced");
  if (box) box.checked = show;
}
$("cfg-show-advanced").addEventListener("change", (e) => {
  try { localStorage.setItem("cfg-advanced", e.target.checked ? "1" : "0"); } catch (err) { /* private mode */ }
  cfgApplyAdvanced();
});
$("cfg-save").addEventListener("click", cfgSave);
$("cfg-reset-all").addEventListener("click", () => {
  // every field back to the value the file holds: the same as pressing Revert, but nothing is thrown away
  // that the user did not type into a form, and Save still decides whether it reaches the file.
  if (!document.querySelector('#cfg-sections .cfg-field[data-changed="true"]')) return;
  if (!confirm("Put every setting back to the value the file holds? Nothing is written until you save.")) return;
  cfgResetAll();
});
$("cfg-revert").addEventListener("click", () => {
  cfgExeTouched = cfgThinkTouched = cfgBudgetTouched = false;
  renderSections();                                   // rebuild from cfgView: every pending edit is dropped
});
function renderConfigPage() {
  const m = modelList.find((x) => x.id === cfgModel);
  $("cfg-title").textContent = m ? (m.display_name || m.id) : "Model settings";
  $("cfg-file").textContent = cfgView.file || "";
  renderRail();
  renderSections();
  renderSide();
}
async function openConfigPage(modelId) {
  try {
    const q = modelId ? `?model=${encodeURIComponent(modelId)}` : "";
    const [modelsR, cfgR, engR] = await Promise.all([
      fetch("api/models", {headers: headers()}),
      fetch(`api/models/config${q}`, {headers: headers()}),
      fetch("api/engines", {headers: headers()}),
    ]);
    if (modelsR.ok) modelList = (await modelsR.json()).models || [];
    const b = await cfgR.json();
    if (!cfgR.ok) throw new Error((b.error || {}).message || `HTTP ${cfgR.status}`);
    try { cfgEngines = ((await engR.json()).engines) || []; } catch (e) { cfgEngines = []; }
    cfgView = b;
    cfgModel = modelId || (modelList.find((m) => m.current) || {}).id || null;
    cfgExeTouched = cfgThinkTouched = cfgBudgetTouched = false;
    renderConfigPage();
    showTab("config");
  } catch (e) {
    toast("error", "Settings not opened", String(e.message || e), 10000);
  }
}
function cfgDiscardOk() {
  try {
    if (cfgView && Object.keys(collectSet()).length) return confirm("This editor has unsaved changes. Discard them?");
  } catch (e) { /* a form that cannot be read is no reason to trap the user on this page */ }
  return true;
}
$("cfg-back").addEventListener("click", () => { if (cfgDiscardOk()) showTab("models"); });
$("cfg-rail").addEventListener("click", (e) => {
  const b = e.target.closest("[data-cfg-model]");
  if (!b || b.dataset.cfgModel === cfgModel) return;
  if (!cfgDiscardOk()) return;
  openConfigPage(b.dataset.cfgModel);
});

// ---- reading the form back into a change set --------------------------------------------------------------
function cfgValue(k, id) {
  // one non-args field → the value the server understands (null = remove / keep the default)
  if (k.kind === "readonly") return k.value ?? null;
  if (k.kind === "object") {
    const numeric = k.key === "reasoning_budget_by_effort";       // level: token counts; env keeps strings
    const out = {};
    document.querySelectorAll(`[data-kv-key="${id}"]`).forEach((keyEl, i) => {
      const valEl = document.querySelectorAll(`[data-kv-val="${id}"]`)[i];
      const key = keyEl.value.trim();
      if (!key) return;
      const s = valEl.value.trim();
      if (s === "") { out[key] = null; return; }                  // an empty value removes that entry
      if (numeric && /^-?\d+(\.\d+)?$/.test(s)) out[key] = Number(s);
      else out[key] = s;
    });
    if (!Object.keys(out).length && (k.value == null || !Object.keys(k.value).length)) return k.value ?? null;
    return out;
  }
  if (k.kind === "list") {
    const out = [];
    document.querySelectorAll(`[data-list-val="${id}"]`).forEach((el) => { const s = el.value.trim(); if (s !== "") out.push(s); });
    if (!out.length && (k.value == null || (Array.isArray(k.value) && !k.value.length))) return k.value ?? null;
    return out;
  }
  const el = $(id);
  if (!el) return k.value ?? null;
  if (k.kind === "bool") return el.getAttribute("aria-checked") === "true";
  if (k.kind === "names") {
    const s = el.value.trim();
    return s === "" ? null : s.split(",").map((x) => x.trim()).filter(Boolean);
  }
  const s = el.value.trim();
  if (s === "") return null;
  if (INT_KIND.test(k.kind)) return parseInt(s, 10);
  if (NUMERIC_KIND.test(k.kind)) return Number(s);
  return s;
}
function readFlag(f, key) {
  const el = $(cfgFlagId(key, f.flag));
  if (!el) return null;
  if (f.kind === "bool") return el.getAttribute("aria-checked") === "true";
  const s = el.value.trim();
  if (s === "") return null;                                      // empty = remove (the server drops the flag)
  return (f.kind === "int" || f.kind === "num") ? Number(s) : s;
}
function normFlag(f, v) {
  // args store every value as a string; a slider reads a number. Compare the same way both sides arrive.
  if (v == null || v === "") return null;
  if (f.kind === "bool") return v === true;
  if (f.kind === "int" || f.kind === "num") { const n = Number(v); return Number.isNaN(n) ? String(v) : n; }
  return String(v);
}
function collectSet() {
  const set = {};
  for (const g of cfgView.groups || []) for (const k of g.keys || []) {
    if (k.kind === "readonly") continue;
    if (k.key === "exe") {
      if (!cfgExeTouched) continue;                               // untouched: the stored path stays, however it looks
      const sel = $(cfgId("exe") + "-sel");
      const inp = $(cfgId("exe"));
      const v = sel && sel.value !== "custom" ? sel.value : (inp ? inp.value.trim() || null : null);
      if ((v ?? null) !== (k.value ?? null)) set.exe = v;
      continue;
    }
    if (k.key === "reasoning_effort") {
      if (!cfgThinkTouched) continue;
      const row = document.querySelector(`#cfg-think .think-row[aria-checked="true"]`);
      const v = row && row.dataset.level ? row.dataset.level : null;
      if ((v ?? null) !== (k.value ?? null)) set.reasoning_effort = v;
      continue;
    }
    if (k.key === "reasoning_budget_by_effort") {
      if (!cfgBudgetTouched) continue;                            // untouched: the stored caps stay (they may be empty)
      // merge into the stored caps: only a level whose slider moved is written; an emptied slider removes that cap
      const obj = Object.assign({}, k.value || {});
      for (const e of cfgView.efforts || []) {
        const lv = e.level;
        if (lv === "none") continue;
        const el = $(`think-${lv}`);
        if (!el) continue;
        const s = el.value.trim();
        if (s === "") delete obj[lv];
        else if (Number(s) !== (e.budget == null ? null : Number(e.budget))) obj[lv] = Number(s);
      }
      if (JSON.stringify(obj) !== JSON.stringify(k.value ?? null)) set.reasoning_budget_by_effort = obj;
      continue;
    }
    if (k.kind === "args") {
      for (const f of k.flags || []) {
        if (!$(cfgFlagId(k.key, f.flag))) continue;               // not rendered (old server): never a change
        const v = readFlag(f, k.key);
        if (JSON.stringify(v) !== JSON.stringify(normFlag(f, f.value))) set[`arg:${f.flag}`] = v;   // an off switch is the same as no flag
      }
      continue;
    }
    if (k.key === "env") {
      // the catalog rows and the hand-written rows are one block: what the file gets is exactly what is on screen
      const v = collectEnv();
      if (!sameEnv(v, k.value)) set.env = Object.keys(v).length ? v : null;
      continue;
    }
    const v = cfgValue(k, cfgId(k.key));
    const old = k.kind === "bool" ? k.value === true : k.value;       // absent and false are the same setting
    if (JSON.stringify(v) !== JSON.stringify(old ?? null)) set[k.key] = v;
  }
  return set;
}
function cfgOldValue(key) {
  if (key.startsWith("arg:")) {
    const flag = key.slice(4);
    for (const g of cfgView.groups || []) for (const k of g.keys || []) if (k.kind === "args") {
      const f = (k.flags || []).find((x) => x.flag === flag);
      if (f) return f.kind === "bool" ? f.value === true : f.value ?? null;
    }
    return null;
  }
  for (const g of cfgView.groups || []) for (const k of g.keys || [])
    if (k.key === key) return k.kind === "bool" ? k.value === true : k.value ?? null;
  return null;
}
function fmtVal(v) {
  if (v == null) return "default";
  if (typeof v === "object") return JSON.stringify(v);
  const s = String(v);
  return s.length > 44 ? s.slice(0, 44) + "…" : s;
}
function cfgMarkDirty() {
  if (!cfgView) return;
  let set = {};
  try { set = collectSet(); } catch (e) { set = {}; }
  const keys = Object.keys(set);
  const bad = document.querySelectorAll('#cfg-sections .cfg-field[data-invalid="true"]').length;
  $("cfg-dirty-dot").hidden = !keys.length;
  const list = $("cfg-changes");
  if (list) {
    list.innerHTML = (keys.length ? keys.map((k) =>
      `<div class="change-row"><code>${esc(k)}</code><span class="change-vals">${esc(fmtVal(cfgOldValue(k)))} → <b>${esc(fmtVal(set[k]))}</b></span></div>`).join("")
      : `<p class="cfg-note">Nothing has changed in this editor.</p>`)
      + (bad ? `<p class="cfg-error cfg-error--list">${bad} value${bad === 1 ? "" : "s"} outside the allowed range: fix ${bad === 1 ? "it" : "them"} to save.</p>` : "");
  }
  const save = $("cfg-save"), rev = $("cfg-revert");
  if (save) save.disabled = !keys.length || bad > 0;
  if (rev) rev.disabled = !keys.length;
  const rail = $("cfg-reset-all");
  if (rail) rail.disabled = !keys.length;
  cfgSyncCardResets();
  cfgApplyAdvanced();                 // a changed advanced field shows itself even while the rest stay tucked away
}
async function cfgSave() {
  if (!cfgView) return;
  let set;
  try { set = collectSet(); }
  catch (e) { toast("error", "Not saved", `Could not read the form: ${e.message || e}`, 9000); return; }
  if (!Object.keys(set).length) { $("cfg-msg").textContent = "Nothing changed."; return; }
  $("cfg-msg").textContent = "Saving…";
  try {
    const q = cfgModel ? `?model=${encodeURIComponent(cfgModel)}` : "";
    const r = await fetch(`api/models/config${q}`, {method: "POST", headers: headers(true), body: JSON.stringify({set})});
    const b = await r.json();
    if (!r.ok) throw new Error((b.error || {}).message || `HTTP ${r.status}`);
    cfgView = b;
    cfgExeTouched = cfgThinkTouched = cfgBudgetTouched = false;
    renderConfigPage();
    $("cfg-msg").textContent = (b.changed || []).length
      ? `Saved ${b.changed.join(", ")}. The earlier file is kept as .bak; start or switch the model to run with it.`
      : "Nothing changed.";
    toast("success", "Settings saved", (b.changed || []).join(", ") || "No changes", 8000);
    loadModels();                                                  // a display_name may have changed
    if (tab === "models") loadModelsView();
  } catch (e) {
    const m = $("cfg-msg");
    if (m) m.textContent = "";
    toast("error", "Not saved", String(e.message || e), 10000);
  }
}

// ---- delegated editing on the sections container ------------------------------------------------------------
$("cfg-sections").addEventListener("click", (e) => {
  const cardRst = e.target.closest("[data-card-reset]");
  if (cardRst) { cfgResetCard(cardRst.dataset.cardReset); return; }
  const rst = e.target.closest("[data-reset]");
  if (rst) {
    cfgResetField(rst.closest(".cfg-field"));
    cfgMarkDirty();
    return;
  }
  const br = e.target.closest("[data-browse]");
  if (br) {
    const inp = $(br.dataset.browse);
    const cur = inp ? inp.value.trim() : "";
    const start = cur ? cur.replace(/[\\/][^\\/]*$/, "") : "";     // the file's folder, when the field has a path
    openBrowser({want: br.dataset.want || "file", ext: br.dataset.ext || "", start,
                 onPick: (p) => { if (inp) { inp.value = p; inp.dispatchEvent(new Event("input", {bubbles: true})); } }});
    return;
  }
  const pchip = e.target.closest("[data-preset]");
  if (pchip) { cfgApplyPreset(Number(pchip.dataset.preset)); return; }
  const add = e.target.closest("[data-kv-add], [data-list-add]");
  if (add) {
    const grid = add.parentElement;
    const id = add.dataset.kvAdd || add.dataset.listAdd;
    const row = add.dataset.listAdd != null
      ? `<div class="list-row"><input class="st-input" type="text" data-list-val="${id}" aria-label="Entry"><button class="st-btn st-btn--icon" type="button" data-list-del="${id}" aria-label="Remove">${icon("x")}</button></div>`
      : `<div class="kv-row"><input class="st-input" type="text" placeholder="key" data-kv-key="${id}" aria-label="Name"><input class="st-input" type="text" placeholder="value" data-kv-val="${id}" aria-label="Value"><button class="st-btn st-btn--icon" type="button" data-kv-del="${id}" aria-label="Remove">${icon("x")}</button></div>`;
    grid.insertAdjacentHTML("beforeend", row);
    cfgMarkDirty();
    return;
  }
  const del = e.target.closest("[data-kv-del], [data-list-del], [data-env-del]");
  if (del) { del.closest(".kv-row, .list-row").remove(); cfgMarkDirty(); return; }
  const chip = e.target.closest("[data-sampling-preset]");
  if (chip) { cfgApplySampling(Number(chip.dataset.samplingPreset)); return; }
  const tgl = e.target.closest(".st-toggle");
  if (tgl) {
    tgl.setAttribute("aria-checked", String(tgl.getAttribute("aria-checked") !== "true"));
    cfgSyncPill(tgl);
    cfgMarkDirty();
    return;
  }
  const row = e.target.closest(".think-row");
  if (row && !e.target.closest(".cfg-slider")) {                   // slider/number clicks do not pick the level
    const txt = e.target.closest(".think-row__text");
    if (txt) row.dataset.open = row.dataset.open === "true" ? "false" : "true";
    row.parentElement.querySelectorAll(".think-row").forEach((r) => {
      const on = r === row;
      r.setAttribute("aria-checked", String(on));
      const lvl = r.querySelector(".think-row__level");
      if (lvl) lvl.innerHTML = esc(lvl.dataset.name) + (on ? ` ${icon("check", "st-icon st-icon--sm")}` : "");
    });
    cfgThinkTouched = true;
    cfgMarkDirty();
  }
});
$("cfg-sections").addEventListener("input", (e) => {
  const t = e.target;
  if (t.type === "range") {
    const base = t.id.replace(/-r$/, "");
    const n = $(base);
    if (n) n.value = t.value;
    const o = $(base + "-o");
    if (o) o.textContent = t.value;
    if (base.startsWith("think-")) cfgBudgetTouched = true;
  } else if (t.type === "number") {
    const r = $(t.id + "-r");
    if (r && t.value !== "") r.value = t.value;
    const o = $(t.id + "-o");
    if (o) o.textContent = t.value;
    if (t.id.startsWith("think-")) cfgBudgetTouched = true;
  } else if (t.id === cfgId("exe")) {
    cfgExeTouched = true;                                          // typing a custom path is a picked exe
  }
  cfgSyncPill(t);
  cfgValidateField(cfgFieldOf(t));
  cfgMarkDirty();
});
$("cfg-sections").addEventListener("change", (e) => {
  cfgSyncPill(e.target);
  cfgValidateField(cfgFieldOf(e.target));
  if (e.target.id === cfgId("exe") + "-sel") {
    const wrap = $(cfgId("exe") + "-wrap");
    if (wrap) wrap.hidden = e.target.value !== "custom";
    cfgExeTouched = true;
  }
  cfgMarkDirty();
});
$("cfg-sections").addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.classList && e.target.classList.contains("think-row")) {
    e.preventDefault();
    e.target.click();
  }
});

// ------------------------------------------------------------------ file browser (GET /api/fs/list)
// A read-only picker behind every path field: folders to walk, an ending filter, click a file to select it (double
// click takes it at once) or type a path. The server lists directories; it never reads file contents.
let fsPick = null;                 // callback(path) for the field that opened the browser
let fsWant = "file";
let fsExt = "";
let fsState = {path: "", entries: [], selected: ""};
function fsQuery(path) {
  const q = new URLSearchParams();
  if (path) q.set("path", path);
  if (fsWant === "dir") q.set("want", "dir");
  if (fsExt) q.set("ext", fsExt);
  return `api/fs/list?${q.toString()}`;
}
async function fsLoad(path) {
  $("fs-list").innerHTML = `<div class="fs-empty">Loading…</div>`;
  try {
    const r = await fetch(fsQuery(path), {headers: headers()});
    const b = await r.json();
    if (!r.ok) throw new Error((b.error || {}).message || `HTTP ${r.status}`);
    fsState = {path: b.path || "", entries: b.entries || [], selected: ""};
    fsRender();
  } catch (e) {
    $("fs-list").innerHTML = `<div class="fs-empty">${esc(e.message || e)}</div>`;
  }
}
function fsRender() {
  $("fs-cwd").textContent = fsState.path || "This PC";
  const segs = [{label: "This PC", path: ""}];
  const norm = String(fsState.path || "").replace(/\\/g, "/");
  if (norm) {
    const win = /^[A-Za-z]:/.test(norm);
    let acc = win ? "" : "/";
    norm.split("/").filter(Boolean).forEach((part, i) => {
      acc = win ? (i === 0 ? part : `${acc}/${part}`) : `${acc}${i ? "/" : ""}${part}`;
      segs.push({label: part, path: acc});
    });
  }
  $("fs-pathbar").innerHTML = segs.map((s, i) =>
    `${i ? `<span class="fs-sep">/</span>` : ""}<button type="button" class="fs-seg" data-fs-goto="${esc(s.path)}">${esc(s.label)}</button>`).join("");
  $("fs-list").innerHTML = fsState.entries.length ? fsState.entries.map((ent, i) =>
    `<button type="button" class="fs-item" role="option" aria-selected="false" data-fs-i="${i}">` +
    `${icon(ent.dir ? "folder" : "file", "st-icon st-icon--sm")}<span>${esc(ent.name)}</span></button>`).join("")
    : `<div class="fs-empty">Nothing here${fsWant === "file" && fsExt ? ` ending in ${esc(fsExt)}` : ""}.</div>`;
  $("fs-name").value = fsState.selected;
}
$("fs-pathbar").addEventListener("click", (e) => {
  const b = e.target.closest("[data-fs-goto]");
  if (b) fsLoad(b.dataset.fsGoto);
});
$("fs-list").addEventListener("click", (e) => {
  const item = e.target.closest("[data-fs-i]");
  if (!item) return;
  const ent = fsState.entries[Number(item.dataset.fsI)];
  if (!ent) return;
  if (ent.dir) { fsLoad(ent.path); return; }
  fsState.selected = ent.path;
  $("fs-list").querySelectorAll(".fs-item").forEach((x) => x.setAttribute("aria-selected", String(x === item)));
  $("fs-name").value = ent.path;
});
$("fs-list").addEventListener("dblclick", (e) => {
  const item = e.target.closest("[data-fs-i]");
  const ent = item ? fsState.entries[Number(item.dataset.fsI)] : null;
  if (ent && !ent.dir) fsChoose();
});
function fsChoose() {
  const v = $("fs-name").value.trim() || (fsWant === "dir" ? fsState.path : "");
  if (!v) return;
  const cb = fsPick;
  fsPick = null;
  $("fs-dialog").close();
  if (cb) cb(v);
}
function openBrowser(opts) {
  fsPick = opts.onPick || null;
  fsWant = opts.want === "dir" ? "dir" : "file";
  fsExt = opts.ext || "";
  $("fs-title").textContent = opts.title || (fsWant === "dir" ? "Choose a folder" : "Choose a file");
  $("fs-name").value = "";
  $("fs-dialog").showModal();
  fsLoad(opts.start || "");
}
$("fs-select").addEventListener("click", fsChoose);
$("fs-cancel").addEventListener("click", () => $("fs-dialog").close());
$("fs-close").addEventListener("click", () => $("fs-dialog").close());
$("fs-name").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); fsChoose(); } });

// ------------------------------------------------------------------ Markdown (escaped first, then formatted)
function inline(s) {
  const codes = [];
  s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s)
    .replace(/!\[([^\]\n]{0,160})\]\((\/comfy\/files\/[0-9a-f]{32}\.png|web\/[A-Za-z0-9._-]+)\)/g,
             '<a class="inline-img-link" href="$2" download="arya-image.png" title="Download the picture">' +
             '<img class="inline-img" src="$2" alt="$1" loading="lazy"></a>')
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*([^*\n]+)\*(?![*\w])/g, "$1<em>$2</em>")
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code class="inline">${esc(codes[+i])}</code>`);
}
// A fenced block that is a picture or a page is worth seeing: SVG, HTML and Markdown get a sandboxed preview above
// the code, and a button downloads the block as the file it is.  A very large block, and one that is still streaming
// (its closing fence has not arrived), stay as code.
function codeBlock(lang, code, opts = {}) {
  const kind = opts.live ? null : wbKind(lang, code);
  const render = Boolean(kind) && String(code || "").length <= 200_000;
  const preview = render
    ? `<div class="st-artifact"><iframe class="st-artifact__frame" sandbox="allow-scripts" ` +
      `referrerpolicy="no-referrer" title="${esc(String(kind).toUpperCase())} preview" ` +
      `srcdoc="${esc(wbDoc({lang: kind, code}))}"></iframe></div>`
    : "";
  const download = render
    ? `<button class="st-btn st-btn--secondary st-code__download" type="button" data-artifact-download>` +
      `Download</button>`
    : "";
  const body = render
    ? `${preview}<details class="st-code__code"><summary>Code</summary><pre><code>${esc(code)}</code></pre></details>`
    : `<pre><code>${esc(code)}</code></pre>`;
  return `<div class="st-code"${kind ? ` data-kind="${kind}"` : ""}>` +
    `<div class="st-code__head"><span>${esc(lang || kind || "code")}</span>` +
    `<span class="st-code__acts">${download}` +
    `<button class="st-btn st-btn--icon" data-code-copy aria-label="Copy code">${icon("copy")}</button></span></div>` +
    `${body}</div>`;
}
function blocks(text) {
  const out = [], lines = text.split("\n");
  let para = [], list = null;
  const flushPara = () => { if (para.length) out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; };
  const flushList = () => { if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    let m;
    if (!l.trim()) { flushPara(); flushList(); continue; }
    if ((m = l.match(/^(#{1,6})\s+(.*)$/))) { flushPara(); flushList(); out.push(`<${m[1].length <= 2 ? "h3" : "h4"}>${inline(m[2])}</${m[1].length <= 2 ? "h3" : "h4"}>`); continue; }
    if (/^\s*([-*_])\s*\1\s*\1[\s\1]*$/.test(l)) { flushPara(); flushList(); out.push("<hr>"); continue; }
    if ((m = l.match(/^>\s?(.*)$/))) { flushPara(); flushList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(lines[i + 1])) {
      flushPara(); flushList();
      const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      let html = `<table><thead><tr>${cells(l).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>`;
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) html += `<tr>${cells(lines[i++]).map((c) => `<td>${c}</td>`).join("")}</tr>`;
      i--;
      out.push(html + "</tbody></table>");
      continue;
    }
    if ((m = l.match(/^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/))) {
      flushPara();
      const tag = m[1] ? "ol" : "ul";
      if (!list || list.tag !== tag) { flushList(); list = {tag, items: []}; }
      list.items.push(m[2]);
      continue;
    }
    if (list && /^\s{2,}\S/.test(l)) { list.items[list.items.length - 1] += " " + l.trim(); continue; }
    flushList();
    para.push(l);
  }
  flushPara(); flushList();
  return out.join("");
}
function markdown(text) {
  let html = "", rest = text;
  for (;;) {
    const m = rest.match(/(^|\n)```([^\n`]*)\n/);
    if (!m) { html += blocks(rest); break; }
    html += blocks(rest.slice(0, m.index));
    rest = rest.slice(m.index + m[0].length);
    const end = rest.match(/(^|\n)```[ \t]*(\n|$)/);
    if (!end) { html += codeBlock(m[2].trim(), rest, {live: true}); break; }   // still streaming: no preview yet
    html += codeBlock(m[2].trim(), rest.slice(0, end.index));
    rest = rest.slice(end.index + end[0].length);
  }
  return html;
}

// ------------------------------------------------------------------ Chat
// The sampling shown until the user changes it is the model card's thinking set. Untouched, the page sends NO sampling
// fields: the server picks the card's set for the request's thinking state (thinking 1.0 / 0.95 / 20, not thinking
// 0.7 / 0.8 / 20 with a presence penalty). Before 0.1.45 the page sent 0.6 itself; a stored 0.6 with the other two
// values untouched counts as "not set" too.
const DEFAULTS = {thinking: "high", temperature: 1.0, top_p: 0.95, top_k: 20, max: "", seed: "", show: true, esp: true,
                  mcp: true, search: true, images: true};
const OLD_DEFAULT_TEMPERATURE = 0.6;
function samplingUntouched(s) {
  const t = +s.temperature;
  return (t === DEFAULTS.temperature || t === OLD_DEFAULT_TEMPERATURE) && +s.top_p === DEFAULTS.top_p && +s.top_k === DEFAULTS.top_k;
}
let settings = {...DEFAULTS, ...store.get("sampling", {})};
if (samplingUntouched(settings)) settings.temperature = DEFAULTS.temperature;
let attachments = [];                 // {name, url}
let busy = null;                      // {controller, msg, cutoff?}

// ------------------------------------------------------------------ chats (kept in this browser)
// Every conversation lives in strata.chats: {version, active, items:[{id, title, times, messages}]}.  `messages` is
// the active chat's own array, so the chat code works on it directly; saveChat writes it back into the list.  An
// install that predates this keeps one chat in strata.chat: the first run copies it into the list and leaves the old
// key untouched, so going back to an older build still finds it.
const CHAT_STORE = "chats", OLD_CHAT_STORE = "chat", CHAT_CAP = 50;
let chats = [], activeChat = "", lastChatStamp = null, chatMenuFor = null;
let messages = [];

function newChatId() {
  try { return crypto.randomUUID(); } catch (e) { return `c${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`; }
}
function chatTitle(text) {
  const line = String(text || "").replace(/\s+/g, " ").trim();
  return line ? (line.length > 60 ? `${line.slice(0, 57).trimEnd()}…` : line) : "New chat";
}
function blankChat() {
  return {id: newChatId(), title: "New chat", createdAt: Date.now(), updatedAt: Date.now(), messages: [],
          stats: blankStats()};
}
function savedMessages(list) {
  return list.map((m) => ({...m, images: (m.images || []).map((i) => ({name: i.name})),
                           files: (m.files || []).map((f) => ({name: f.name}))}));
}
function loadChats() {
  const saved = store.get(CHAT_STORE, null);
  if (saved && Array.isArray(saved.items)) {
    chats = saved.items.filter((c) => c && typeof c.id === "string" && Array.isArray(c.messages));
    if (chats.length) {
      activeChat = chats.some((c) => c.id === saved.active) ? saved.active : chats[0].id;
      ensureChat();
      return;
    }
  }
  const old = store.get(OLD_CHAT_STORE, []);
  chats = [];
  if (Array.isArray(old) && old.length) {
    const first = old.find((m) => m.role === "user");
    chats.push({id: newChatId(), title: chatTitle(first && first.text), createdAt: Date.now(), updatedAt: Date.now(),
                messages: old});
  }
  ensureChat();
  store.set(CHAT_STORE, {version: 1, active: activeChat, items: chats});   // the migration is written once
}
function ensureChat() {
  if (!chats.length) chats.push(blankChat());
  if (!chats.some((c) => c.id === activeChat)) activeChat = chats[0].id;
  const chat = chats.find((c) => c.id === activeChat);
  messages = chat.messages;
  footStats = chat.stats || (chat.stats = blankStats());   // this chat's own totals: they come back with it
  return chat;
}
function activeChatItem() { return chats.find((c) => c.id === activeChat) || null; }
function saveChat() {
  // The active chat by id, without ensureChat(): that one re-points `messages` at the chat's stored array, which
  // would throw away every turn added since the last save (the second turn, then the fourth, and so on).
  const chat = activeChatItem();
  if (!chat) {                                       // the last chat was deleted: still persist the empty list
    store.set(CHAT_STORE, {version: 1, active: activeChat, items: chats});
    renderChats();
    return;
  }
  chat.updatedAt = Date.now();
  if (chat.title === "New chat") {
    const first = messages.find((m) => m.role === "user");
    if (first) chat.title = chatTitle(first.text);
  }
  chats.sort((a, b) => b.updatedAt - a.updatedAt);
  if (chats.length > CHAT_CAP) chats.length = CHAT_CAP;   // the active chat is the newest, so it is never dropped
  // the live array stays the chat's own; the stored copy is a snapshot (attachments keep only their names)
  const items = chats.map((c) => (c.id === chat.id ? {...c, messages: savedMessages(messages)} : c));
  store.set(CHAT_STORE, {version: 1, active: activeChat, items});
  renderChats();
}
function ago(t) {
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "now";
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)}d`;
  return new Date(t).toLocaleDateString([], {month: "short", day: "numeric"});
}
// A chat is filed under the day it last changed: Today, Yesterday, the week before, the month before, Older.
function chatGroupLabel(t) {
  const start = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(new Date()) - start(new Date(t))) / 86400000);
  return days <= 0 ? "Today" : days === 1 ? "Yesterday" : days <= 7 ? "Previous 7 days"
    : days <= 30 ? "Previous 30 days" : "Older";
}
let chatFilter = "";
function renderChats() {
  const query = chatFilter.trim().toLowerCase();
  const items = chats.filter((c) => !query ||
    `${c.title} ${c.messages.map((m) => m.text || "").join(" ")}`.toLowerCase().includes(query));
  // rebuild only when something visible changed, so the 1 s poll does not fight the pointer
  const stamp = JSON.stringify([activeChat, query, chats.length, Math.floor(Date.now() / 60000),
                                items.map((c) => [c.id, c.title, c.updatedAt, !!c.archived])]);
  if (stamp === lastChatStamp) return;
  lastChatStamp = stamp;
  const list = $("chat-list");
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "st-empty";
    empty.innerHTML = `<span class="st-empty__title"></span><span></span>`;
    empty.firstChild.textContent = query ? "No chat matches" : "No chats yet";
    empty.lastChild.textContent = query ? "Try another word." : "Ask something and it is kept here.";
    list.append(empty);
    return;
  }
  // a search is one flat list (an archived match says so); otherwise the chats are filed by day and the archived
  // ones wait at the end, out of the way but never lost.
  const groups = [];
  if (query) {
    groups.push({label: "", chats: items});
  } else {
    for (const chat of items) {
      if (chat.archived) continue;
      const label = chatGroupLabel(chat.updatedAt);
      const last = groups[groups.length - 1];
      if (last && last.label === label) last.chats.push(chat);
      else groups.push({label, chats: [chat]});
    }
    const archived = items.filter((c) => c.archived);
    if (archived.length) groups.push({label: "Archived", chats: archived, archived: true});
  }
  for (const group of groups) {
    if (group.label) {
      const head = document.createElement("div");
      head.className = "st-chat-group";
      head.setAttribute("role", "presentation");
      head.textContent = group.label;
      list.append(head);
    }
    for (const chat of group.chats) list.append(chatRow(chat, Boolean(query) && Boolean(chat.archived)));
  }
}
function chatRow(chat, tagged) {
  const row = document.createElement("div");
  row.className = "st-chat-item" + (chat.archived ? " st-chat-item--archived" : "");
  row.dataset.chat = chat.id;
  if (chat.archived) row.dataset.archived = "true";
  row.setAttribute("role", "listitem");
  row.setAttribute("aria-current", String(chat.id === activeChat));
  row.tabIndex = 0;
  const title = document.createElement("span");
  title.className = "st-chat-item__title";
  title.textContent = chat.title;
  title.title = chat.title;
  const when = document.createElement("span");
  when.className = "st-chat-item__time";
  when.textContent = ago(chat.updatedAt);
  const menu = document.createElement("button");
  menu.type = "button";
  menu.className = "st-chat-item__menu";
  menu.dataset.chatMenu = chat.id;
  menu.setAttribute("aria-label", `Options for ${chat.title}`);
  menu.innerHTML = icon("more", "st-icon st-icon--sm");
  if (tagged) {
    const tag = document.createElement("span");
    tag.className = "st-chat-item__tag";
    tag.textContent = "Archived";
    row.append(title, tag, when, menu);
  } else {
    row.append(title, when, menu);
  }
  return row;
}
function openChat(id) {
  if (busy) { toast("warn", "Still writing", "Stop the answer first."); return; }
  const chat = chats.find((c) => c.id === id);
  if (!chat) return;
  closeSidebar();
  closeChatMenu();
  if (chat.id === activeChat) { $("input").focus(); return; }
  attachments = [];
  renderAttachments();
  activeChat = chat.id;
  messages = chat.messages;
  footStats = chat.stats || (chat.stats = blankStats());
  renderFoot();
  store.set(CHAT_STORE, {version: 1, active: activeChat, items: chats});
  lastChatStamp = null;
  renderChats();
  renderChat();
  showTab("chat");
  $("input").focus();
  scrollDown(true);
}
function newChat() {
  if (busy) { toast("warn", "Still writing", "Stop the answer first."); return; }
  closeChatMenu();
  const current = activeChatItem();
  if (current && !current.messages.length) { showTab("chat"); $("input").focus(); return; }
  const chat = blankChat();
  chats.unshift(chat);
  activeChat = chat.id;
  messages = chat.messages;
  footStats = chat.stats || (chat.stats = blankStats());
  renderFoot();
  attachments = [];
  renderAttachments();
  saveChat();
  renderChat();
  showTab("chat");
  $("input").focus();
}
function deleteChat(id) {
  if (busy) { toast("warn", "Still writing", "Stop the answer first."); return; }
  const at = chats.findIndex((c) => c.id === id);
  if (at < 0) return;
  const chat = chats[at];
  if (!confirm(`Delete "${chat.title}"? Chats are kept in this browser only, so this cannot be undone.`)) return;
  chats.splice(at, 1);
  if (activeChat === id) {
    const next = chats[Math.min(at, chats.length - 1)];
    if (next) { activeChat = next.id; messages = next.messages; } else { activeChat = ""; messages = []; }
    renderChat();
  }
  closeChatMenu();
  saveChat();
  lastChatStamp = null;
  renderChats();
  toast("info", "Chat deleted", "", 4000);
}
function renameChat(id) {
  const row = $("chat-list").querySelector(`[data-chat="${CSS.escape(id)}"]`);
  const chat = chats.find((c) => c.id === id);
  if (!row || !chat) return;
  closeChatMenu();
  const title = row.querySelector(".st-chat-item__title");
  const input = document.createElement("input");
  input.type = "text";
  input.value = chat.title === "New chat" ? "" : chat.title;
  input.placeholder = "Chat name";
  input.setAttribute("aria-label", "Chat name");
  title.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const finish = (save) => {
    if (done) return;
    done = true;
    if (save) {
      const name = input.value.replace(/\s+/g, " ").trim();
      chat.title = name || chat.title;
      chat.updatedAt = Date.now();
      store.set(CHAT_STORE, {version: 1, active: activeChat, items: chats});
    }
    lastChatStamp = null;
    renderChats();
  };
  input.onkeydown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  };
  input.onblur = () => finish(true);
}
// Archive hides a chat from the day groups without losing it; the menu's own label flips to Unarchive.
function archiveChat(id) {
  const chat = chats.find((c) => c.id === id);
  if (!chat) return;
  closeChatMenu();
  chat.archived = !chat.archived;
  store.set(CHAT_STORE, {version: 1, active: activeChat, items: chats});
  lastChatStamp = null;
  renderChats();
  toast("info", chat.archived ? "Chat archived" : "Chat restored",
        chat.archived ? "It waits at the end of the list, under Archived." : "It is back with its day.", 4000);
}
function openChatMenu(id, anchor) {
  const wasOpen = !$("chat-menu").hidden && chatMenuFor === id;
  closeChatMenu();
  if (wasOpen) return;
  chatMenuFor = id;
  const chat = chats.find((c) => c.id === id);
  const label = $("chat-menu").querySelector('[data-chat-act="archive"] span');
  if (label) label.textContent = chat && chat.archived ? "Unarchive" : "Archive";
  $("chat-menu").hidden = false;
  placePopover($("chat-menu"), anchor);
}
function closeChatMenu() {
  $("chat-menu").hidden = true;
  chatMenuFor = null;
}
$("chat-menu").onclick = (e) => {
  const b = e.target.closest("[data-chat-act]");
  if (!b || !chatMenuFor) return;
  const id = chatMenuFor;
  if (b.dataset.chatAct === "rename") renameChat(id);
  else if (b.dataset.chatAct === "export") exportChat(id);
  else if (b.dataset.chatAct === "archive") archiveChat(id);
  else if (b.dataset.chatAct === "delete") deleteChat(id);
};
$("chat-list").onclick = (e) => {
  if (e.target.closest("input")) return;                       // a row being renamed
  const menu = e.target.closest("[data-chat-menu]");
  if (menu) { e.stopPropagation(); openChatMenu(menu.dataset.chatMenu, menu); return; }
  const row = e.target.closest("[data-chat]");
  if (row) openChat(row.dataset.chat);
};
$("chat-list").onkeydown = (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  if (e.target.closest("input") || e.target.closest("button")) return;
  const row = e.target.closest("[data-chat]");
  if (!row) return;
  e.preventDefault();
  openChat(row.dataset.chat);
};
$("chat-search").oninput = () => { chatFilter = $("chat-search").value; renderChats(); };
$("chat-search").onkeydown = (e) => {
  if (e.key === "Escape") { e.preventDefault(); $("chat-search").value = ""; chatFilter = ""; renderChats(); }
};
function timeStr(t) { return new Date(t).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}); }

// ------------------------------------------------------------------ swipes
// Each assistant message carries its own variants. m.text/m.reasoning/m.tools/m.meta always hold the
// *current* one; m.swipes[m.swipeIndex] mirrors it, so navigating is just save-current / load-target.
// Regenerating discards any variants after the current one and appends the new one at the end.
function swipeInit(m) {
  if (!Array.isArray(m.swipes) || !m.swipes.length) {
    m.swipes = [{text: m.text || "", reasoning: m.reasoning || "", tools: m.tools || null, meta: m.meta || null}];
    m.swipeIndex = 0;
  }
}
function swipeSnapshot(m) {
  return {text: m.text || "", reasoning: m.reasoning || "", tools: m.tools || null, meta: m.meta || null};
}
function swipeSave(m) {
  swipeInit(m);
  m.swipes[m.swipeIndex] = swipeSnapshot(m);
}
function swipeLoad(m) {
  swipeInit(m);
  const s = m.swipes[m.swipeIndex] || {};
  m.text = s.text || ""; m.reasoning = s.reasoning || ""; m.tools = s.tools || null; m.meta = s.meta || null;
  m.thinkSecs = null; m.stopped = false; m.error = null; m.limit = null;
}

// The streaming itself, shared by send() and regenerateMessage(). On abort it sets m.stopped and returns
// normally (so the caller can still save the partial answer); on any other error it rethrows.
async function streamInto(m, el, signal) {
  const body = {model: health.model, messages: apiMessages(), stream: true, reasoning_effort: settings.thinking};
  if (!(settings.temperature > 0)) {
    body.temperature = 0;
  } else if (!samplingUntouched(settings)) {
    Object.assign(body, {temperature: +settings.temperature, top_p: +settings.top_p, top_k: +settings.top_k});
  }
  if (settings.seed) body.seed = +settings.seed;
  if (settings.max) body.max_tokens = +settings.max;
  if (projectionLoaded()) body.experimental_speed_projection = !!settings.esp;
  if (settings.mcp !== false && mcpInfo.tools > 0) body.strata_mcp = true;
  if (settings.search !== false && searchInfo.configured) body.strata_search = true;
  if (settings.images !== false && comfyInfo.configured) body.strata_images = true;

  let firstAt = null, thinkStart = null, usage = null, frame = 0, ctxParts = null;
  const t0 = performance.now();
  const paint = () => { frame = 0; updateAssistant(el, m, true); scrollDown(); };
  try {
    const r = await fetch("v1/chat/completions", {method: "POST", headers: headers(true),
                                                   body: JSON.stringify(body), signal});
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try { msg = (await r.json()).error.message || msg; } catch (e) { /* not json */ }
      if (r.status === 401) msg = "This server needs an API key: add it under About > Settings.";
      throw new Error(msg);
    }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line.startsWith("data:")) continue;              // ": keep-alive" comments while a long prompt is read
        const data = line.slice(5).trim();
        if (data === "[DONE]") continue;
        let j;
        try { j = JSON.parse(data); } catch (e) { continue; }
        if (j.error) throw new Error(j.error.message || "the engine reported an error");
        if (j.usage) usage = j.usage;
        if (j.strata_context) ctxParts = j.strata_context;   // the server's split of the prompt it just read
        if (j.strata_mcp) onTool(m, j.strata_mcp);
        const d = (j.choices && j.choices[0] && j.choices[0].delta) || {};
        const lastTool = m.tools && m.tools.length ? m.tools[m.tools.length - 1] : null;   // a new round after a tool
        if (d.reasoning_content) {
          setCompanion("thinking");
          if (!firstAt) firstAt = performance.now();
          if (!thinkStart) thinkStart = performance.now();
          if (lastTool && m.reasoning && lastTool.rat === m.reasoning.length) m.reasoning += "\n\n";
          m.reasoning += d.reasoning_content;
        }
        if (d.content) {
          if (!firstAt) firstAt = performance.now();
          if (thinkStart && m.thinkSecs == null) m.thinkSecs = (performance.now() - thinkStart) / 1000;
          if (lastTool && m.text && lastTool.at === m.text.length) m.text += "\n\n";
          m.text += d.content;
        }
        if (!frame) frame = requestAnimationFrame(paint);
      }
    }
  } catch (e) {
    if (e.name === "AbortError") {
      m.stopped = true;
    } else {
      if (thinkStart && m.thinkSecs == null) m.thinkSecs = (performance.now() - thinkStart) / 1000;
      if (frame) cancelAnimationFrame(frame);
      throw e;
    }
  }
  if (thinkStart && m.thinkSecs == null) m.thinkSecs = (performance.now() - thinkStart) / 1000;
  if (frame) cancelAnimationFrame(frame);
  // this chat's footer totals: the time this answer took, when its first token landed, and what the server counted
  footStats.llm_ms += performance.now() - t0;
  if (firstAt) {
    footStats.ttft_ms += firstAt - t0;
    footStats.ttft_n += 1;
    footStats.gen_ms += Math.max(0, performance.now() - firstAt);
  }
  if (usage) {
    footStats.in_tokens += usage.prompt_tokens || 0;
    footStats.cached_tokens += (usage.prompt_tokens_details && usage.prompt_tokens_details.cached_tokens) || 0;
    footStats.out_tokens += usage.completion_tokens || 0;
    footStats.ctx.prompt = usage.prompt_tokens || 0;
    footStats.ctx.out = usage.completion_tokens || 0;
    footStats.ctx.max = health.max_context || footStats.ctx.max;
  }
  if (ctxParts) {                 // system turns and tool definitions: the conversation is the rest of the prompt
    footStats.ctx.system = ctxParts.system || 0;
    footStats.ctx.tools = ctxParts.tools || 0;
  }
  const n = usage ? usage.completion_tokens : null;
  if (n && firstAt) {
    const secs = (performance.now() - firstAt) / 1000;
    m.meta = `${fmt(n)} tokens${secs > 0.25 ? ` · ${fmt(n / secs, 1)} tok/s` : ""}${m.stopped ? " · stopped" : ""}` +
             (projectionLoaded() ? (settings.esp ? " · projection on" : " · projection off") : "");
  } else if (m.stopped) {
    m.meta = "Stopped";
  }
  for (const t of m.tools || []) if (t.state === "writing" || t.state === "running") { t.state = "skipped"; t.ms = null; }
  const ran = (m.tools || []).filter((t) => t.state === "done" || t.state === "error").length;
  if (ran) m.meta = `${m.meta ? `${m.meta} · ` : ""}${ran} tool call${ran > 1 ? "s" : ""}`;
  footStats.steps += 1 + ran;                     // one model round, plus one more for each tool it ran
  footStats.tool_ms += (m.tools || []).reduce((a, t) => a + (Number(t.ms) || 0), 0);
  renderFoot();
  if (m.limit) m.meta = `${m.meta || ""} · stopped at the limit of ${m.limit} tool rounds (mcp.max_rounds)`;
  updateAssistant(el, m, false);
  if (!m.stopped && !m.error) flashCompanionSuccess();
}

// Regenerates the answer at messages[i]: keeps the previous one as a variant, discards any variants after
// the current one, streams a new answer into the same message. On failure the previous answer is restored.
async function regenerateMessage(i) {
  if (busy) { toast("warn", "Still writing", "Stop the answer first."); return; }
  const m = messages[i];
  if (!m || m.role !== "assistant") return;
  const el = $("chat").querySelector(`.st-msg[data-i="${i}"]`);
  if (!el) return;
  swipeInit(m);
  swipeSave(m);
  m.swipes.length = m.swipeIndex + 1;          // a new variant discards the ones after the current one
  const keep = swipeSnapshot(m);
  m.text = ""; m.reasoning = ""; m.tools = null; m.meta = null;
  m.thinkSecs = null; m.stopped = false; m.error = null; m.limit = null;
  const controller = new AbortController();
  busy = {controller, msg: m, cutoff: i};
  if (i < messages.length - 1) {
    toast("info", "Regenerating an earlier message",
          `${messages.length - i - 1} later message(s) stay in the chat, and the next request will still see them.`,
          7000);
  }
  setBusy(true);
  updateAssistant(el, m, true);
  try {
    await streamInto(m, el, controller.signal);
    m.swipes.push(swipeSnapshot(m));
    m.swipeIndex = m.swipes.length - 1;
  } catch (e) {
    m.error = e.message || String(e);
    setCompanion("error");
    toast("error", "Regeneration failed", m.error, 6000);
    Object.assign(m, keep);
    m.swipes[m.swipeIndex] = keep;
  }
  busy = null;
  setBusy(false);
  updateAssistant(el, m, false);
  saveChat();
  scrollDown();
}

// Moves between variants: saves the current answer, loads the neighbour.
function swipeGo(i, delta) {
  if (busy) return;
  const m = messages[i];
  if (!m || m.role !== "assistant") return;
  swipeInit(m);
  const n = m.swipes.length;
  if (n < 2) return;
  swipeSave(m);
  m.swipeIndex = (m.swipeIndex + delta + n) % n;
  swipeLoad(m);
  const el = $("chat").querySelector(`.st-msg[data-i="${i}"]`);
  if (el) updateAssistant(el, m, false);
  saveChat();
}

function msgEl(m, i) {
  const el = document.createElement("div");
  el.className = `st-msg st-msg--${m.role}`;
  el.dataset.i = i;
  if (m.role === "user") {
    if (m.files && m.files.length) {
      const wrap = document.createElement("div");
      wrap.className = "msg-images";
      for (const f of m.files) {
        const c = document.createElement("span");
        c.className = "chip";
        c.innerHTML = icon("attach", "st-icon st-icon--sm");
        c.append(f.name);
        wrap.appendChild(c);
      }
      el.appendChild(wrap);
    }
    if (m.images && m.images.length) {
      const wrap = document.createElement("div");
      wrap.className = "msg-images";
      for (const im of m.images) {
        if (im.url) { const img = document.createElement("img"); img.src = im.url; img.alt = im.name || "image"; wrap.appendChild(img); }
        else { const c = document.createElement("span"); c.className = "chip"; c.innerHTML = icon("image", "st-icon st-icon--sm"); c.append(im.name || "image"); wrap.appendChild(c); }
      }
      el.appendChild(wrap);
    }
    const b = document.createElement("div");
    b.className = "st-bubble";
    b.textContent = m.text;
    el.appendChild(b);
    const meta = document.createElement("div");
    meta.className = "st-msg__meta";
    meta.textContent = `You · ${timeStr(m.time)}`;
    el.appendChild(meta);
  } else {
    el.innerHTML = `<details class="st-collapse think" hidden><summary>${icon("thinking", "st-icon st-icon--sm")}<span class="think-title"></span>` +
      `${icon("chevron", "st-icon st-icon--sm st-chev")}</summary><div class="st-collapse__body thinking"></div></details>` +
      `<div class="st-bubble"></div><div class="st-msg__meta"><span class="meta-text"></span>` +
      `<button class="st-btn st-btn--icon" data-msg-regen aria-label="Regenerate" title="Regenerate">↻</button>` +
      `<button class="st-btn st-btn--icon" data-msg-prev aria-label="Previous variant" title="Previous variant">‹</button>` +
      `<span class="swipe-count" data-swipe-count></span>` +
      `<button class="st-btn st-btn--icon" data-msg-next aria-label="Next variant" title="Next variant">›</button>` +
      `<button class="st-btn st-btn--icon" data-msg-copy aria-label="Copy the answer" title="Copy">${icon("copy")}</button></div>`;
    updateAssistant(el, m, false);
  }
  return el;
}
// One MCP tool call in the answer: a compact block (name, state, a one-line preview) that opens to the arguments and
// the result as the model read it.  Its body is built only while open: a result can be 20,000 characters.
const TOOL_STATE = {writing: ["st-badge--reading", "Writing"], running: ["st-badge--generating", "Running"], done: ["", "Done"],
                    error: ["st-badge--error", "Error"], skipped: ["st-badge--queued", "Not run"]};
// The images a tool call made (generate_image) or a tool result names.  Only this server's own files: a URL from
// anywhere else stays text, so an answer cannot pull in a picture from the internet.
const IMAGE_URL = /(?:\/comfy\/files\/[0-9a-f]{32}\.png|web\/[A-Za-z0-9._-]+\.(?:png|webp|jpg|jpeg|svg))/g;
function sameOriginImage(url) {
  return typeof url === "string" && (url.startsWith("/comfy/files/") || url.startsWith("web/")) &&
         !url.includes("..");
}
function toolImages(t) {
  const out = [], seen = new Set();
  const add = (url, width, height) => {
    if (!sameOriginImage(url) || seen.has(url)) return;
    seen.add(url);
    out.push({url, width, height});
  };
  for (const image of t.images || []) add(image.url, image.width, image.height);
  for (const match of (t.result || "").matchAll(IMAGE_URL)) add(match[0]);
  return out.slice(0, 6);
}
function toolHtml(t, k) {
  const [cls, label] = TOOL_STATE[t.state] || ["", t.state];
  const args = t.arguments == null ? "" : JSON.stringify(t.arguments, null, 2);
  const preview = t.result != null ? t.result : args.replace(/\s+/g, " ");
  let body = "";
  if (t.open) {
    body = `<div class="tool-call__label">Arguments</div><pre class="tool-call__pre">${esc(args || "(being written)")}</pre>`;
    if (t.result != null) {
      body += `<div class="tool-call__label">${t.ok ? "Result" : "Error"}${t.chars ? ` · ${fmt(t.chars)} characters` : ""}` +
              `${t.truncated ? ", cut for the model" : ""}</div><pre class="tool-call__pre">${esc(t.result)}</pre>`;
    }
  }
  const pics = toolImages(t);
  const thumbnails = pics.length
    ? `<div class="tool-call__pics">` + pics.map((p) =>
        `<a class="tool-pic" href="${esc(p.url)}" download="arya-image.png" title="Download the picture" ` +
        `aria-label="Download the picture">` +
        `<img src="${esc(p.url)}" alt="" loading="lazy"></a>`).join("") + `</div>`
    : "";
  return `<details class="st-collapse tool-call" data-tool="${k}" data-state="${esc(t.state)}"${t.open ? " open" : ""}>` +
    `<summary>${icon("tool", "st-icon st-icon--sm")}<span class="tool-call__name" title="${esc(t.name || "")}">${esc(t.tool || t.name || "tool")}</span>` +
    (t.server ? `<span class="muted small">${esc(t.server)}</span>` : "") +
    `<span class="tool-call__preview muted">${esc(preview.slice(0, 200))}</span>` +
    `<span class="st-badge ${cls}">${esc(label)}</span>${t.ms != null && t.state !== "skipped" ? `<span class="muted small">${fmt(t.ms / 1000, 1)} s</span>` : ""}` +
    `${icon("chevron", "st-icon st-icon--sm st-chev")}</summary><div class="st-collapse__body">${body}</div></details>` +
    thumbnails;
}
// the answer's text with the tool blocks where the model called them
function answerHtml(m) {
  if (!m.tools || !m.tools.length) return markdown(m.text || "");
  let html = "", pos = 0;
  m.tools.forEach((t, k) => {
    const at = Math.min(Math.max(t.at || 0, pos), m.text.length);
    if (at > pos) html += markdown(m.text.slice(pos, at));
    pos = at;
    html += toolHtml(t, k);
  });
  return html + markdown(m.text.slice(pos));
}
// a tool event from the stream (the `strata_mcp` field of a chunk)
function onTool(m, x) {
  if (x.event === "limit") { m.limit = x.max_rounds; return; }
  m.tools = m.tools || [];
  let t = m.tools.find((y) => y.id === x.id);
  if (!t) { t = {id: x.id, name: x.name, at: m.text.length, rat: m.reasoning.length, state: "writing"}; m.tools.push(t); }
  if (x.event === "call") {
    Object.assign(t, {name: x.name, server: x.server, tool: x.tool, arguments: x.arguments, round: x.round, state: "running"});
    setCompanion("running-testing");
  } else if (x.event === "result") {
    Object.assign(t, {result: x.text, ok: x.ok, chars: x.chars, truncated: x.truncated, ms: x.ms,
                      state: x.skipped ? "skipped" : x.ok ? "done" : "error"});
    if (Array.isArray(x.images) && x.images.length) t.images = x.images;   // a generate_image call made them
    setCompanion("writing");
  }
}
function updateAssistant(el, m, streaming) {
  const det = el.querySelector("details.think");
  if (m.reasoning) {
    det.hidden = false;
    const thinkingNow = streaming && !m.text;
    el.querySelector(".think-title").textContent = thinkingNow ? "Thinking…" :
      m.thinkSecs != null ? `Thought for ${fmt(m.thinkSecs, 1)} s` : "Thoughts";
    const body = el.querySelector(".thinking");
    if (det.open || thinkingNow) body.textContent = m.reasoning;
    else body.dataset.pending = "1";
    // open while it streams (if wanted), closed once the answer starts - unless the user toggled it themselves
    if (thinkingNow && settings.show && !det.dataset.touched && !det.open) { det._auto = true; det.open = true; }
    if (!thinkingNow && det.open && !det.dataset.touched) { det._auto = true; det.open = false; }
  }
  const bubble = el.querySelector(".st-bubble");
  if (m.error) {
    bubble.innerHTML = `<div class="msg-error"></div>`;
    bubble.firstChild.textContent = m.error;
  } else if (!m.text && streaming && !(m.tools && m.tools.length)) {
    bubble.innerHTML = m.reasoning ? `<span class="muted cursor">Writing</span>` : `<span class="cursor"></span>`;
  } else {
    bubble.innerHTML = answerHtml(m);
    if (streaming) bubble.classList.add("cursor"); else bubble.classList.remove("cursor");
  }
  el.querySelector(".meta-text").textContent = m.meta || (streaming ? "" : m.stopped ? "Stopped" : "");
  el.querySelector("[data-msg-copy]").hidden = streaming || !m.text;
  // swipe controls: regenerate disabled while streaming; prev/next shown when there is more than one variant
  const rg = el.querySelector("[data-msg-regen]");
  const pv = el.querySelector("[data-msg-prev]");
  const nx = el.querySelector("[data-msg-next]");
  const cnt = el.querySelector("[data-swipe-count]");
  const n = Array.isArray(m.swipes) ? m.swipes.length : 1;
  const idx = m.swipeIndex || 0;
  if (rg) rg.disabled = streaming;
  if (pv) pv.hidden = streaming || n < 2;
  if (nx) nx.hidden = streaming || n < 2;
  if (cnt) { cnt.hidden = streaming || n < 2; cnt.textContent = n > 1 ? `${idx + 1}/${n}` : ""; }
}
function renderChat() {
  const chat = $("chat");
  chat.querySelectorAll(".st-msg").forEach((e) => e.remove());
  $("chat-empty").hidden = messages.length > 0;
  messages.forEach((m, i) => chat.appendChild(msgEl(m, i)));
  scrollDown(true);
}
function nearBottom() { const s = $("chat-scroll"); return s.scrollHeight - s.scrollTop - s.clientHeight < 120; }
function scrollDown(force) { const s = $("chat-scroll"); if (force || nearBottom()) s.scrollTop = s.scrollHeight; }

$("chat").addEventListener("click", (e) => {
  const rg = e.target.closest("[data-msg-regen]");
  if (rg) { regenerateMessage(+rg.closest(".st-msg").dataset.i); return; }
  const pv = e.target.closest("[data-msg-prev]");
  if (pv) { swipeGo(+pv.closest(".st-msg").dataset.i, -1); return; }
  const nx = e.target.closest("[data-msg-next]");
  if (nx) { swipeGo(+nx.closest(".st-msg").dataset.i, +1); return; }
  const cc = e.target.closest("[data-code-copy]");
  if (cc) { copyText(cc.closest(".st-code").querySelector("pre").textContent, cc); return; }
  const mc = e.target.closest("[data-msg-copy]");
  if (mc) { const i = +mc.closest(".st-msg").dataset.i; copyText(messages[i].text, mc); return; }
  // a tool block: its open state lives in the message (the answer is rebuilt while it streams), so the click sets it
  const sum = e.target.closest(".tool-call > summary");
  if (sum) {
    e.preventDefault();
    const el = sum.closest(".st-msg"), m = messages[+el.dataset.i], t = m && m.tools && m.tools[+sum.parentElement.dataset.tool];
    if (!t) return;
    t.open = !t.open;
    updateAssistant(el, m, !!busy && busy.msg === m);
  }
});
$("chat").addEventListener("toggle", (e) => {
  const d = e.target;
  if (d.tagName !== "DETAILS" || !d.classList.contains("think")) return;
  if (d._auto) { d._auto = false; return; }          // our own open/close, not the user's
  d.dataset.touched = "1";
  const body = d.querySelector(".thinking");
  if (d.open && body.dataset.pending) { body.textContent = messages[+d.closest(".st-msg").dataset.i].reasoning; delete body.dataset.pending; }
}, true);

function apiMessages() {
  const out = [];
  const end = busy && busy.cutoff != null ? busy.cutoff + 1 : messages.length;
  for (let k = 0; k < end; k++) {
    const m = messages[k];
    if (m.role === "user") {
      const imgs = (m.images || []).filter((i) => i.url);
      const text = userText(m);
      out.push({role: "user", content: imgs.length ? [{type: "text", text},
        ...imgs.map((i) => ({type: "image_url", image_url: {url: i.url}}))] : text});
    } else if (!(busy && busy.msg === m)) {            // the answer being asked for now is not history yet
      out.push(...assistantMessages(m));
    }
  }
  return out;
}
// An answer that used MCP tools goes back as the model wrote it: per round the text before the calls, the calls and
// their results (as the model read them), then the rest - so the next question can build on what the tools found.
function assistantMessages(m) {
  const ran = (m.tools || []).filter((t) => t.round != null && t.result != null && t.state !== "skipped");
  // #1392: a turn with no answer text (only reasoning, a stop before the first content token, or an error) still goes
  // back as an assistant turn, so the history keeps alternating and a reasoning model sees that it already answered.
  // The server leaves such a turn out of the prompt itself (serve/frontend.py, #843); reasoning_content rides along.
  if (!ran.length) {
    const msg = {role: "assistant", content: m.text || ""};
    if (!m.text && m.reasoning) msg.reasoning_content = m.reasoning;
    return [msg];
  }
  const out = [];
  let pos = 0;
  for (const r of [...new Set(ran.map((t) => t.round))]) {
    const calls = ran.filter((t) => t.round === r);
    const at = Math.min(Math.max(pos, calls[0].at || 0), m.text.length);
    out.push({role: "assistant", content: m.text.slice(pos, at).trim(),
              tool_calls: calls.map((t) => ({id: t.id, type: "function", function: {name: t.name, arguments: JSON.stringify(t.arguments || {})}}))});
    for (const t of calls) out.push({role: "tool", tool_call_id: t.id, content: t.result});
    pos = at;
  }
  const rest = m.text.slice(pos).trim();
  if (rest) out.push({role: "assistant", content: rest});
  return out;
}

function setBusy(on) {
  $("stop-btn").hidden = !on;
  $("send-btn").disabled = on;
  $("composer-hint").textContent = on ? "" : "Shift+Enter: new line";
}

async function send() {
  const text = $("input").value.trim();
  if ((!text && !attachments.length) || busy) return;
  messages.push({role: "user", text, images: attachments.filter((a) => a.kind !== "file"),
                 files: attachments.filter((a) => a.kind === "file"), time: Date.now()});
  footStats.turns += 1;
  attachments = [];
  renderAttachments();
  $("input").value = "";
  autosize();
  const m = {role: "assistant", text: "", reasoning: "", time: Date.now()};
  messages.push(m);
  renderChat();
  const el = $("chat").lastElementChild;
  const controller = new AbortController();
  busy = {controller, msg: m};
  setBusy(true);
  try {
    await streamInto(m, el, controller.signal);
  } catch (e) {
    m.error = e.message || String(e);
    setCompanion("error");
    toast("error", "The request failed", m.error, 6000);
    updateAssistant(el, m, false);
  }
  busy = null;
  setBusy(false);
  updateAssistant(el, m, false);
  saveChat();
  scrollDown();
}

$("composer").onsubmit = (e) => { e.preventDefault(); send(); };
$("stop-btn").onclick = () => { if (busy) busy.controller.abort(); };
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});
function autosize() { const t = $("input"); t.style.height = "auto"; t.style.height = `${Math.min(t.scrollHeight, innerHeight * 0.4)}px`; }
$("input").addEventListener("input", autosize);

$("new-btn").onclick = newChat;
$("export-btn").onclick = () => exportChat(activeChat);
// One chat as Markdown: the answers, their thinking and the tool calls behind them.
function exportChat(id) {
  const chat = chats.find((c) => c.id === id) || activeChatItem();
  if (!chat || !chat.messages.length) { toast("info", "Nothing to save yet"); return; }
  closeChatMenu();
  const tools = (m) => (m.tools || []).filter((t) => t.result != null).map((t) =>
    `<details><summary>Tool ${t.server ? `${t.server} / ` : ""}${t.tool || t.name}${t.ok ? "" : " (error)"}</summary>\n\n` +
    `\`\`\`json\n${JSON.stringify(t.arguments || {}, null, 2)}\n\`\`\`\n\n\`\`\`\n${t.result}\n\`\`\`\n\n</details>\n\n`).join("");
  const md = chat.messages.map((m) => m.role === "user" ? `## You\n\n${m.text}\n` :
    `## ${health.model}\n\n${m.reasoning ? `<details><summary>Thinking</summary>\n\n${m.reasoning}\n\n</details>\n\n` : ""}${tools(m)}${m.text || m.error || ""}\n`).join("\n");
  const a = document.createElement("a");
  const name = (chat.title || "chat").replace(/[\\/:*?"<>|]+/g, "-").slice(0, 60).trim() || "chat";
  a.href = URL.createObjectURL(new Blob([`# ${chat.title || "Chat"}\n\n${md}`], {type: "text/markdown"}));
  a.download = `${name}-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.md`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

// pictures and text files: the attach button, dropping them on the chat, or pasting a picture (issue #30)
const TEXT_EXT = /\.(txt|md|markdown|rst|tex|py|pyi|ipynb|js|mjs|cjs|ts|tsx|jsx|vue|svelte|json|jsonl|csv|tsv|log|ya?ml|toml|ini|cfg|conf|env|xml|html?|css|scss|less|c|cc|cpp|cxx|h|hh|hpp|cu|cuh|rs|go|java|kt|kts|swift|rb|php|pl|lua|r|jl|scala|sql|sh|bash|zsh|fish|ps1|psm1|bat|cmd|diff|patch|gradle|cmake|mk|dockerfile|gitignore|proto|graphql)$/i;
const MAX_TEXT_FILE = 512 * 1024;
function isTextFile(f) {
  return f.type.startsWith("text/") || /json|xml|javascript|yaml|toml|x-sh|x-python/.test(f.type) ||
         TEXT_EXT.test(f.name) || /(^|[\\/])(makefile|dockerfile|readme|license)$/i.test(f.name);
}
function addFiles(files) {
  for (const f of files) {
    if (f.type.startsWith("image/")) {
      if (!health.images) { toast("warn", "Pictures are off", "This model was set up for text only."); continue; }
      if (f.size > 20e6) { toast("warn", "Picture too large", `${f.name} is over 20 MB.`); continue; }
      const r = new FileReader();
      r.onload = () => { attachments.push({kind: "image", name: f.name || "pasted image", url: r.result}); renderAttachments(); };
      r.readAsDataURL(f);
      continue;
    }
    if (!isTextFile(f)) { toast("warn", "Not a text file", `${f.name}: attach text files (code, notes, logs, data)${health.images ? " or pictures" : ""}.`); continue; }
    if (f.size > MAX_TEXT_FILE) { toast("warn", "File too large", `${f.name} is over 512 KB.`); continue; }
    const r = new FileReader();
    r.onload = () => {
      const text = String(r.result);
      if (text.includes("\u0000")) { toast("warn", "Not a text file", `${f.name} looks like a binary file.`); return; }
      attachments.push({kind: "file", name: f.name, text});
      renderAttachments();
    };
    r.readAsText(f);
  }
}
// a file's text in the message, fenced with more backticks than it contains itself
function fileBlock(f) {
  const longest = Math.max(2, ...(f.text.match(/`+/g) || []).map((s) => s.length));
  const fence = "`".repeat(longest + 1);
  return `File: ${f.name}\n${fence}\n${f.text}\n${fence}`;
}
function userText(m) {
  const files = (m.files || []).filter((f) => f.text != null);
  return [m.text, ...files.map(fileBlock)].filter((s) => s).join("\n\n");
}
function renderAttachments() {
  const box = $("attachments");
  box.hidden = !attachments.length;
  box.innerHTML = "";
  attachments.forEach((a, i) => {
    const c = document.createElement("span");
    c.className = "chip";
    c.innerHTML = icon(a.kind === "file" ? "attach" : "image", "st-icon st-icon--sm");
    c.append(a.name);
    const x = document.createElement("button");
    x.type = "button"; x.className = "st-btn st-btn--icon"; x.setAttribute("aria-label", "Remove");
    x.innerHTML = icon("trash");
    x.onclick = () => { attachments.splice(i, 1); renderAttachments(); };
    c.appendChild(x);
    box.appendChild(c);
  });
}
$("attach-btn").onclick = () => $("file").click();
// Dictation: the browser's own speech recognition (Safari on iOS, Chrome), appending what it hears to the box.  The
// audio goes to that browser's speech service, not to this server - the tooltip says so - and the button stays hidden
// where the API is missing.  iOS ends a session on a pause even with continuous on, so a wanted session restarts itself.
const SPEECH = window.SpeechRecognition || window.webkitSpeechRecognition;
function setupVoice(button, target) {
  if (!SPEECH || !button || !target) { if (button) button.hidden = true; return; }
  let rec = null, want = false, base = "";
  const paint = (on) => {
    button.hidden = false;
    button.setAttribute("aria-pressed", String(on));
    button.setAttribute("aria-label", on ? "Stop dictating" : "Dictate");
    button.title = on ? "Stop dictating" : "Dictate (the browser's speech service)";
    button.classList.toggle("is-recording", on);
  };
  button.onclick = () => {
    if (want) { want = false; if (rec) rec.stop(); paint(false); return; }
    base = target.value;
    rec = new SPEECH();
    rec.lang = navigator.language || "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e) => {
      let final = "", interim = "";
      for (let i = e.resultIndex; i < e.results.length; i += 1) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript; else interim += r[0].transcript;
      }
      if (final.trim()) base = `${base}${base && !/\s$/.test(base) ? " " : ""}${final.trim()}`;
      target.value = base + (interim ? `${base ? " " : ""}${interim}` : "");
      target.dispatchEvent(new Event("input", {bubbles: true}));
    };
    rec.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return;
      want = false;
      toast("error", "Dictation stopped", e.error === "not-allowed" || e.error === "service-not-allowed"
        ? "Allow the microphone for this page, then try again."
        : `The browser's speech service said: ${e.error}`, 7000);
    };
    rec.onend = () => {
      if (want) { try { rec.start(); return; } catch (e) { want = false; } }
      target.value = base;                       // an unfinished phrase is dropped
      paint(false);
    };
    want = true;
    try {
      rec.start();
      paint(true);
    } catch (e) {
      want = false;
      paint(false);
      toast("error", "Dictation could not start", e.message, 6000);
    }
  };
  paint(false);
}
setupVoice($("voice-btn"), $("input"));
// drop files on the chat or the message box
for (const id of ["chat", "composer"]) {
  const el = $(id);
  el.addEventListener("dragover", (e) => {
    if (![...(e.dataTransfer || {}).types || []].includes("Files")) return;
    e.preventDefault();
    $("composer").classList.add("dragging");
  });
  el.addEventListener("dragleave", () => $("composer").classList.remove("dragging"));
  el.addEventListener("drop", (e) => {
    $("composer").classList.remove("dragging");
    if (!e.dataTransfer || !e.dataTransfer.files.length) return;
    e.preventDefault();
    addFiles(e.dataTransfer.files);
    $("input").focus();
  });
}
$("file").onchange = () => { addFiles($("file").files); $("file").value = ""; };
$("input").addEventListener("paste", (e) => {
  if (!health.images) return;
  const files = [...(e.clipboardData || {}).files || []].filter((f) => f.type.startsWith("image/"));
  if (files.length) { e.preventDefault(); addFiles(files); }
});

// ------------------------------------------------------------------ the sampling drawer
function openDrawer(open) {
  $("drawer").dataset.open = String(open);
  $("drawer").setAttribute("aria-hidden", String(!open));
  if (open) {
    closeSettings();
    closeModelMenu();
    closeSidebar();
    loadDrawer(); loadShared(); loadMcp(); loadSearch();
    openOverlay("drawer");
  } else closeOverlay("drawer");
}
function loadDrawer(s = settings) {
  for (const b of $("s-thinking").children) b.setAttribute("aria-checked", String(b.dataset.v === s.thinking));
  $("s-temp").value = s.temperature; $("s-topp").value = s.top_p; $("s-topk").value = s.top_k;
  $("s-max").value = s.max; $("s-seed").value = s.seed;
  $("s-show").setAttribute("aria-checked", String(!!s.show));
  $("s-esp").setAttribute("aria-checked", String(s.esp !== false));
  $("esp-row").hidden = !projectionLoaded();
  $("s-mcp").setAttribute("aria-checked", String(s.mcp !== false));
  $("s-search").setAttribute("aria-checked", String(s.search !== false));
  $("s-images").setAttribute("aria-checked", String(s.images !== false));
  $("s-share").setAttribute("aria-checked", String(sharedOn));
  outputs();
}
// "Use for other apps too": the server keeps these settings as every client's defaults (GET/POST /settings)
let sharedOn = false;
async function loadShared() {
  try {
    const r = await fetch("settings", {headers: headers()});
    if (r.ok) sharedOn = !!(await r.json()).shared;
  } catch (e) { /* an older server: the switch just stays off */ }
  $("s-share").setAttribute("aria-checked", String(sharedOn));
}
function sharedDefaults(s) {
  const d = {reasoning_effort: s.thinking};
  if (!(+s.temperature > 0)) d.temperature = 0;
  else if (!samplingUntouched(s)) Object.assign(d, {temperature: +s.temperature, top_p: +s.top_p, top_k: +s.top_k});
  if (s.seed) d.seed = +s.seed;
  if (s.max) d.max_tokens = +s.max;
  if (projectionLoaded()) d.experimental_speed_projection = s.esp !== false;
  return d;
}
async function saveShared(on, s) {
  const r = await fetch("settings", {method: "POST", headers: headers(true),
                                      body: JSON.stringify({defaults: on ? sharedDefaults(s) : null})});
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { msg = (await r.json()).error.message || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  sharedOn = !!(await r.json()).shared;
}
// the engine was started with the experimental-speed-projection control vector (INFO cvec=...)
function projectionLoaded() {
  const c = lastMetrics && lastMetrics.engine ? lastMetrics.engine.cvec : 0;
  return !!c && c !== "0";
}
function outputs() {
  const t = +$("s-temp").value;
  $("o-temp").textContent = t === 0 ? "0 · greedy" : t.toFixed(2);
  $("o-topp").textContent = (+$("s-topp").value).toFixed(2);
  $("o-topk").textContent = $("s-topk").value;
  const sel = [...$("s-thinking").children].find((b) => b.getAttribute("aria-checked") === "true");
  $("o-thinking").textContent = sel ? {none: "answers right away", low: "short", medium: "medium", high: "thorough (default)"}[sel.dataset.v] : "";
  for (const id of ["s-topp", "s-topk"]) $(id).disabled = t === 0;
}
for (const b of $("s-thinking").children) b.onclick = () => { for (const x of $("s-thinking").children) x.setAttribute("aria-checked", String(x === b)); outputs(); };
for (const id of ["s-temp", "s-topp", "s-topk"]) $(id).oninput = outputs;
$("s-show").onclick = () => $("s-show").setAttribute("aria-checked", String($("s-show").getAttribute("aria-checked") !== "true"));
$("s-esp").onclick = () => $("s-esp").setAttribute("aria-checked", String($("s-esp").getAttribute("aria-checked") !== "true"));
$("s-mcp").onclick = () => $("s-mcp").setAttribute("aria-checked", String($("s-mcp").getAttribute("aria-checked") !== "true"));
$("s-search").onclick = () => $("s-search").setAttribute("aria-checked", String($("s-search").getAttribute("aria-checked") !== "true"));
$("s-images").onclick = () => $("s-images").setAttribute("aria-checked", String($("s-images").getAttribute("aria-checked") !== "true"));
$("s-share").onclick = () => $("s-share").setAttribute("aria-checked", String($("s-share").getAttribute("aria-checked") !== "true"));
$("s-reset").onclick = () => loadDrawer(DEFAULTS);
$("s-apply").onclick = async () => {
  const sel = [...$("s-thinking").children].find((b) => b.getAttribute("aria-checked") === "true");
  settings = {thinking: sel ? sel.dataset.v : "high", temperature: +$("s-temp").value, top_p: +$("s-topp").value,
              top_k: +$("s-topk").value, max: $("s-max").value.trim(), seed: $("s-seed").value.trim(),
              show: $("s-show").getAttribute("aria-checked") === "true",
              esp: $("s-esp").getAttribute("aria-checked") === "true",
              mcp: $("s-mcp").getAttribute("aria-checked") === "true",
              search: $("s-search").getAttribute("aria-checked") === "true",
              images: $("s-images").getAttribute("aria-checked") === "true"};
  store.set("sampling", settings);
  renderToolPills();                       // the switches for web search and images take effect now
  const share = $("s-share").getAttribute("aria-checked") === "true";
  openDrawer(false);
  if (share || sharedOn) {
    try {
      await saveShared(share, settings);
      toast("success", "Sampling saved", share ? "Other apps (omp, API clients) use these settings from their next request."
                                               : "Other apps use their own settings again.");
    } catch (e) {
      toast("error", "Saved here, but not for other apps", e.message, 6000);
    }
    return;
  }
  toast("success", "Sampling saved", settings.temperature === 0 ? "Greedy: the same question gives the same answer." : "");
};
$("sampling-btn").onclick = () => openDrawer(true);
$("drawer-close").onclick = () => openDrawer(false);
$("scrim").onclick = () => { if (!closeTopOverlay()) { openDrawer(false); openSettings(false); closeSidebar(); } };
// Escape: the menus first, then whatever overlay is on top
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("chat-menu").hidden) { closeChatMenu(); return; }
  if (!$("model-menu").hidden) { closeModelMenu(); $("model-btn").focus(); return; }
  closeTopOverlay();
});
// the page's own shortcuts: search the chats, start one, open Settings
document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  const key = e.key.toLowerCase();
  if (key === "k") {
    e.preventDefault();
    if (NARROW.matches) openSidebar(true);
    $("chat-search").focus();
    $("chat-search").select();
  } else if (key === "n" && e.shiftKey) {
    e.preventDefault();
    newChat();
  }
});
// a click outside an anchored panel closes it
document.addEventListener("click", (e) => {
  if (!$("model-menu").hidden && !$("model-menu").contains(e.target) &&
      !$("model-btn").contains(e.target) && !$("models-nav").contains(e.target)) closeModelMenu();
  if (!$("chat-menu").hidden && !$("chat-menu").contains(e.target) &&
      !e.target.closest("[data-chat-menu]")) closeChatMenu();
  if (settingsOpen() && !$("settings-pop").contains(e.target) && !$("settings-btn").contains(e.target)) openSettings(false);
});

// ------------------------------------------------------------------ previews in the chat, and downloads
// A fenced block that is a picture or a page is worth seeing: SVG, HTML and Markdown get a sandboxed preview above
// their code (codeBlock), and the block's button downloads it as the file it is.  There is no side panel: what the
// model writes stays in the answer, where it was produced.
function wbKind(lang, code) {
  const label = String(lang || "").toLowerCase();
  const head = String(code || "").slice(0, 4000);
  if (label === "svg" || /^\s*(?:<\?xml[^>]*>\s*)?<svg[\s>]/i.test(head)) return "svg";
  if (label === "html" || label === "xhtml" || label === "htm" ||
      /^\s*<!doctype\s+html/i.test(head) || /<html[\s>]/i.test(head)) return "html";
  if (label === "markdown" || label === "md") return "markdown";
  if (label === "xml" || label === "") {                 // the model often labels neither, or calls SVG "xml"
    if (/^\s*<(?:!doctype\s+html|html|head|body|svg|div|section|main|article|table|style|canvas|form)[\s>]/i.test(head)) {
      return /^\s*(?:<\?xml[^>]*>\s*)?<svg[\s>]/i.test(head) ? "svg" : "html";
    }
  }
  return null;
}
// The frame's own policy: no network at all, no access to this page, inline script and style only. Nothing the model
// writes can reach the server, the user's other tabs or the internet through it.
const WB_CSP = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; ` +
               `style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; media-src data: blob:">`;
function wbDoc(a) {
  // A preview is a thumbnail, not a window: its own document must not scroll.  A document that can scroll keeps the
  // wheel for itself (measured: 500 px of wheel over a scrollable preview moved the chat 0 px), so a conversation
  // ending in a tall artifact could not be scrolled past it.  Clipped, the wheel chains to the chat.
  const FIT = "html,body{height:100%;overflow:hidden}";
  if (a.lang === "markdown") {
    return `<!doctype html><html><head><meta charset="utf-8">${WB_CSP}<style>` +
           FIT +
           `body{margin:0;padding:16px;font:15px/1.55 system-ui,sans-serif;color:#1b2431}` +
           `pre{background:#f2f5fa;padding:10px;border-radius:8px;overflow:auto}code{font-family:ui-monospace,monospace}` +
           `h1,h2{margin:.4em 0 .3em;line-height:1.2}table{border-collapse:collapse}td,th{border:1px solid #d4ddea;padding:4px 8px}` +
           `</style></head><body>${markdown(a.code)}</body></html>`;
  }
  // An SVG with only a viewBox has no intrinsic size, and `max-height:96%` inside an auto-height grid row resolved to
  // zero in Chrome - the preview was a blank frame for every such drawing.  A flex box with width/height 100% lets the
  // viewBox scale the drawing (preserveAspectRatio keeps it centred).
  const inner = a.lang === "svg"
    ? `<!doctype html><html><head><meta charset="utf-8">${WB_CSP}<style>${FIT};html,body{margin:0;background:#fff}` +
      `body{display:flex;align-items:center;justify-content:center}` +
      `svg{display:block;width:100%;height:100%}</style></head><body>${a.code}</body></html>`
    : a.code;
  const style = `<style>${FIT}</style>`;
  if (/<head[\s>]/i.test(inner)) {
    return inner.replace(/<head([^>]*)>/i, `<head$1><meta charset="utf-8">${WB_CSP}${style}`);
  }
  if (/<html[\s>]/i.test(inner)) return inner.replace(/<html([^>]*)>/i, `<html$1><head>${WB_CSP}${style}</head>`);
  return `<!doctype html><html><head><meta charset="utf-8">${WB_CSP}${style}</head><body>${inner}</body></html>`;
}
// The file a downloaded block becomes: its own <title>, <h1> or first heading, else "artifact", with the kind's
// extension.  Characters Windows does not allow in a name become dashes.
function artifactFileName(kind, code) {
  const m = code.match(/<title[^>]*>([^<]{1,80})<\/title>/i) || code.match(/<h1[^>]*>([^<]{1,80})<\/h1>/i) ||
            code.match(/^#\s+(.{1,80})$/m);
  const base = (m ? m[1] : "artifact").trim().replace(/[\\/:*?"<>|]+/g, "-").replace(/\s+/g, " ").slice(0, 60).trim();
  return `${base || "artifact"}.${kind === "markdown" ? "md" : kind === "svg" ? "svg" : "html"}`;
}
function downloadArtifact(kind, code) {
  if (!code) return;
  const type = kind === "svg" ? "image/svg+xml" : kind === "markdown" ? "text/markdown" : "text/html";
  const url = URL.createObjectURL(new Blob([code], {type}));
  const link = document.createElement("a");
  link.href = url;
  link.download = artifactFileName(kind, code);
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
// The download button is inside both the chat's answers and the Images room's thread; one listener on the document
// serves both.  The block's kind and its text are the source of truth, so the file is exactly what was rendered.
document.addEventListener("click", (e) => {
  const button = e.target.closest("[data-artifact-download]");
  if (!button) return;
  const box = button.closest(".st-code");
  const code = box && box.querySelector("pre code");
  if (code && box.dataset.kind) downloadArtifact(box.dataset.kind, code.textContent);
});

// ------------------------------------------------------------------ session footer
// This chat's own accounting: turns and model steps, how long the model and its tools took, the tokens the server
// counted (and the share the conversation cache already held), and how full the window is. The prompt's split is the
// server's: `strata_context` on the last chunk says how many of its tokens were the system turns and the tool
// definitions, so the conversation is the rest. The totals are kept with the chat and come back with it.
function blankStats() {
  return {turns: 0, steps: 0, llm_ms: 0, gen_ms: 0, tool_ms: 0, ttft_ms: 0, ttft_n: 0,
          in_tokens: 0, cached_tokens: 0, out_tokens: 0,
          ctx: {prompt: 0, system: 0, tools: 0, out: 0, max: 0}};
}
let footStats = blankStats();

const footDur = (ms) => {
  if (!ms) return "–";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
};
const footTok = (n) => (n == null ? "–" : n >= 1e9 ? `${fmt(n / 1e9, 2)}B`
  : n >= 1e6 ? `${fmt(n / 1e6, 1)}M` : n >= 1e4 ? `${fmt(n / 1e3)}K` : fmt(n));
const footPct = (part, whole) => (whole > 0 ? Math.round((part / whole) * 100) : 0);
const FOOT_POPS = [["foot-turns", "foot-turns-pop"], ["foot-tokens", "foot-tokens-pop"],
                   ["foot-context", "foot-context-pop"]];

function renderFoot() {
  const s = footStats;
  const max = s.ctx.max || health.max_context || 0;
  const total = s.in_tokens + s.out_tokens;
  const used = s.ctx.prompt + (s.ctx.out || 0);
  const hit = footPct(s.cached_tokens, s.in_tokens);
  $("foot-turns-text").textContent = s.turns
    ? `${fmt(s.turns)} turn${s.turns === 1 ? "" : "s"} · ${fmt(s.steps)} step${s.steps === 1 ? "" : "s"}` : "No turns yet";
  $("foot-tokens-text").textContent = total ? `${footTok(total)} tok · cache ${hit}%` : "0 tokens";
  $("foot-context-text").textContent = max ? `${footPct(used, max)}%` : "–";

  const tps = s.gen_ms > 0 ? Math.round(s.out_tokens / (s.gen_ms / 1000)) : null;
  $("foot-turns-pop").innerHTML =
    `<div class="foot-pop__head"><span class="foot-pop__title">${icon("activity", "st-icon st-icon--sm")}` +
    `Session statistics</span><span class="foot-pop__value">${fmt(s.turns)} turns ${fmt(s.steps)} steps</span></div>` +
    `<div class="foot-pop__row"><span>LLM time</span><b>${footDur(s.llm_ms)}</b></div>` +
    `<div class="foot-pop__row"><span>Tool time</span><b>${footDur(s.tool_ms)}</b></div>` +
    `<div class="foot-pop__row"><span>Avg time to first token (TTFT)</span>` +
    `<b>${s.ttft_n ? `${(s.ttft_ms / s.ttft_n / 1000).toFixed(1)}s` : "–"}</b></div>` +
    `<div class="foot-pop__row"><span>Tokens per second (TPS)</span><b>${tps ? `${fmt(tps)} tok/s` : "–"}</b></div>`;
  $("foot-tokens-pop").innerHTML =
    `<div class="foot-pop__head"><span class="foot-pop__title">${icon("layers", "st-icon st-icon--sm")}` +
    `Token usage</span><span class="foot-pop__value">${fmt(total)} tok</span></div>` +
    `<div class="foot-pop__row"><span>Cache hit</span><b>${s.in_tokens ? `${hit}%` : "–"}</b></div>` +
    `<div class="foot-pop__row"><span>Uncached input</span><b>${fmt(s.in_tokens - s.cached_tokens)} tok</b></div>` +
    `<div class="foot-pop__row"><span>Cached input</span><b>${fmt(s.cached_tokens)} tok</b></div>` +
    `<div class="foot-pop__row"><span>Output</span><b>${fmt(s.out_tokens)} tok</b></div>`;
  const parts = [["system", "System prompt", s.ctx.system], ["tools", "Tool definitions", s.ctx.tools],
                 ["messages", "Messages", Math.max(0, s.ctx.prompt - s.ctx.system - s.ctx.tools)]];
  const share = (n) => (used > 0 ? Math.max(0, (n / used) * 100) : 0);
  $("foot-context-pop").innerHTML =
    `<div class="foot-pop__head"><span class="foot-pop__title">${icon("gauge", "st-icon st-icon--sm")}` +
    `${max ? `${footPct(used, max)}%` : "–"} of context used</span>` +
    `<span class="foot-pop__value">~${footTok(used)} / ${footTok(max)}</span></div>` +
    `<div class="foot-pop__bar">${parts.map(([key, , n]) =>
      `<span class="foot-pop__seg foot-pop__seg--${key}" style="width:${share(n)}%"></span>`).join("")}</div>` +
    parts.map(([key, label, n]) =>
      `<div class="foot-pop__row"><span><i class="foot-pop__key foot-pop__key--${key}"></i>${label}</span>` +
      `<b>~${footTok(n)}</b></div>`).join("");
}

function closeFootPops() {
  for (const [chip, pop] of FOOT_POPS) {
    $(pop).hidden = true;
    $(chip).setAttribute("aria-expanded", "false");
  }
}
function openFootPop(chipId, popId) {
  const wasOpen = !$(popId).hidden;
  closeFootPops();
  if (wasOpen) return;
  const anchor = $(chipId), el = $(popId);
  el.hidden = false;
  anchor.setAttribute("aria-expanded", "true");
  // above the whole footer strip and right-aligned to the chip that opened it: on a phone the chips wrap to two rows,
  // and a popover placed over the pressed chip alone would cover the other two
  const r = anchor.getBoundingClientRect();
  const foot = $("chat-foot").getBoundingClientRect();
  el.style.left = `${Math.max(12, Math.min(r.right - el.offsetWidth, innerWidth - el.offsetWidth - 12))}px`;
  el.style.bottom = `${Math.max(12, innerHeight - foot.top + 6)}px`;
}
for (const [chip, pop] of FOOT_POPS) $(chip).onclick = () => openFootPop(chip, pop);
document.addEventListener("click", (e) => {
  if (!e.target.closest("#chat-foot")) closeFootPops();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && FOOT_POPS.some(([, pop]) => !$(pop).hidden)) closeFootPops();
});

// ------------------------------------------------------------------ start
setBusy(false);
loadChats();
renderChats();
renderChat();
renderFoot();
const startQuestion = new URLSearchParams(location.search).get("q");   // /?q=... starts a chat (a shortcut)
if (startQuestion) history.replaceState(null, "", location.pathname + location.hash);
loadModels();
loadHealth().then(() => renderFoot()).then(loadMcp).then(loadSearch).then(loadComfy).then(() => { if (startQuestion) { $("input").value = startQuestion; send(); } });
showTab(location.hash.slice(1) || "chat");
poll();

// ------------------------------------------------------------------ images (POST /v1/images/generations)
$("img-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const prompt = $("img-prompt").value.trim();
  if (!prompt) return;
  const body = {prompt, size: $("img-size").value, response_format: "b64_json"};
  if ($("img-seed").value !== "") body.seed = Number($("img-seed").value);
  $("img-go").disabled = true;
  const t0 = performance.now();
  $("img-hint").textContent = "Generating\u2026 (a minute or more on a small GPU)";
  try {
    const r = await fetch("v1/images/generations", {method: "POST", headers: headers(true), body: JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok) throw new Error((j.error && j.error.message) || r.statusText);
    for (const d of j.data) {
      const fig = document.createElement("figure");
      const img = document.createElement("img");
      img.src = "data:image/png;base64," + d.b64_json;
      img.alt = prompt;
      const cap = document.createElement("figcaption");
      cap.textContent = `${j.size}, seed ${d.seed}, ${((performance.now() - t0) / 1000).toFixed(0)} s: ${prompt}`;
      fig.append(img, cap);
      $("img-results").prepend(fig);
    }
    $("img-hint").textContent = "Done. Right-click an image to save it.";
  } catch (e) {
    $("img-hint").textContent = "";
    toast("error", "No image", String(e.message || e), 8000);
  } finally {
    $("img-go").disabled = false;
  }
};