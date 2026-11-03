// ------------------------------------------------------------------ the Images room
// A conversation about pictures: the user says what they want (and what to change), the agent writes the prompt and
// picks the ComfyUI workflow through the generate_image tool.  The room shows the answer the way the chat does - tool
// block, thumbnails - and the agent may search the web for a reference description when that helps.  It talks to this
// server only: the tool runs on the server, and the page never calls ComfyUI itself.
const ROOM_KEY = "room";
let room = {tab: "create", messages: [], sending: false, refs: [], page: null, query: "", favs: false,
            viewer: null, abort: null, last: null};

function roomOnComfy() {
  if (!$("view-images") || $("view-images").hidden) return;
  roomRender();
}
function roomFocus() {
  if (room.tab !== "create") roomTab("create");
  $("room-prompt").focus();
}
function roomTab(tab) {
  room.tab = tab;
  for (const b of $("room-tabs").children) b.setAttribute("aria-selected", String(b.dataset.roomTab === tab));
  for (const pane of document.querySelectorAll("[data-room-pane]")) pane.hidden = pane.dataset.roomPane !== tab;
  if (tab === "mine") roomLoadGallery(true);
  if (tab === "templates") roomRenderTemplates();
  roomRender();
}
// The room's instructions: the agent owns the prompt and the graph, and only what it is told about this server.
async function roomSystem() {
  const workflows = (comfyInfo.workflows || []).map((w) => {
    const shape = w.baked_size ? `${w.baked_size.width}x${w.baked_size.height}` : "the source's size";
    return `${w.name} (${w.role.replace("-", " ")}, ${shape})`;
  }).join("; ");
  let made = roomMade();
  if (!made.length && comfyInfo.configured) {
    // the browser may have thrown the thread away (a phone, a reload): the gallery still knows the newest pictures
    try {
      const j = await (await fetch("comfy?gallery=1&limit=3", {headers: headers()})).json();
      made = ((j.page && j.page.items) || []).map((x) => ({id: x.id, workflow: x.workflow, prompt: x.prompt}));
    } catch (e) { /* the room still works without it */ }
  }
  const last = made.length
    ? `Pictures already made in this room, newest first: ` +
      made.map((m) => `${m.id} (${m.workflow || "a workflow"})`).join(", ") +
      `. To change or restyle one, call generate_image with reference_id = <that id> and an image-to-image workflow; ` +
      `keep what the user liked and change only what they asked about. If you do not have an id, an image-to-image ` +
      `workflow with no reference_id edits the newest picture in the gallery.`
    : "No picture is in this room's gallery yet. If the user asks to change 'the last picture' anyway, call " +
      "generate_image with an image-to-image workflow and no reference_id: the server edits the newest picture or " +
      "says there is none.";
  const refs = room.refs.map((r) => r.id).filter(Boolean);
  return [
    "You are the picture room of AryaInfer, running on this PC. You make and edit pictures with ComfyUI through the " +
    "generate_image tool.",
    "- You decide the image prompt and the workflow. Write a rich, concrete prompt yourself: subject, style, light, " +
    "composition, and what to leave out. Sixty to eighty words is plenty; do not paste the user's sentence verbatim.",
    "- Pick the workflow by role and shape from the list below: a text-to-image graph for a new picture, an " +
    "image-to-image graph for a change to an existing one. A 1:1 request wants a square graph; a poster, banner or " +
    "wallpaper wants the wide one; a portrait or phone wallpaper wants the portrait one.",
    "- Call generate_image once per request. To change the last picture, pass BOTH reference_id (its id) and an " +
    "image-to-image workflow: one without the other fails. A request for the same thing again may ask for two or " +
    "three variants with count.",
    "- This room makes raster pictures through ComfyUI. When the user asks for an SVG, HTML, a diagram, a chart, an " +
    "icon set or a UI mockup, do not call generate_image: answer with the code in a fenced block (```svg or ```html), " +
    "which this page renders.",
    "- You may search the web when a factual reference helps (a plant, a landmark, a product, a style); turn what you " +
    "learn into the prompt. Web pictures cannot be downloaded into ComfyUI, so never claim to have used one.",
    "- After the tool answers, reply in one or two short sentences about what you made. Never invent image links.",
    `Workflows on this ComfyUI: ${workflows || "(none)"}.`,
    last,
    refs.length
      ? `The user attached ${refs.length === 1 ? "this picture" : "these pictures"} to this request: ` +
        `${refs.join(", ")}. Edit the first one with an image-to-image workflow; the server uses it even if you leave ` +
        `reference_id out, so do not make a new picture from the text alone.`
      : "",
  ].filter(Boolean).join("\n");
}
function roomRender() {
  const narrow = typeof NARROW === "object" && NARROW.matches;      // a phone shows the state, not the version
  $("room-status").textContent = !comfyInfo.configured ? "not set up" : comfyInfo.reachable
    ? (narrow ? "connected" : (comfyInfo.version ? `ComfyUI ${comfyInfo.version}` : "connected")) : "not reachable";
  $("room-status").className = `muted small ${comfyInfo.configured && !comfyInfo.reachable ? "mcp-msg-bad" : ""}`;
  $("room-tab-local").hidden = !health.image_generation;
  $("room-go").disabled = !comfyInfo.configured || !comfyInfo.reachable;
  $("room-cancel").hidden = !room.sending;
  $("room-hint").textContent = room.refs.length
    ? "The next request edits the attached picture" + (comfyInfo.reachable ? "." : "; ComfyUI is not answering yet.")
    : !comfyInfo.configured
    ? "Images need a ComfyUI: press Setup, then point it at one."
    : !comfyInfo.reachable ? "ComfyUI is not answering: press Setup and check, or start it there."
    : "The agent writes the prompt and picks the workflow. Say what to change, or attach a picture to edit it.";
  roomRenderRefs();
  roomRenderChat();
  roomRenderGallery();
}
function roomRenderRefs() {
  const box = $("room-refs");
  box.replaceChildren();
  box.hidden = !room.refs.length;
  for (const [i, ref] of room.refs.entries()) {
    const chip = document.createElement("span");
    chip.className = "room-ref";
    chip.innerHTML = `<img alt="" src="${esc(ref.url)}"><button type="button" class="st-btn st-btn--icon" ` +
      `aria-label="Remove the reference">${icon("x", "st-icon st-icon--sm")}</button>`;
    chip.querySelector("button").onclick = () => { room.refs.splice(i, 1); roomRender(); };
    box.append(chip);
  }
}
function roomRenderChat() {
  const box = $("room-chat");
  box.replaceChildren();
  if (!room.messages.length) {
    const empty = document.createElement("div");
    empty.className = "st-empty room__empty";
    empty.innerHTML = `<span class="st-empty__title">What should I picture?</span><span>` +
      `Describe it however you like - "a warm poster for my coffee shop, 1:1" - and I'll write the prompt, pick the ` +
      `workflow and make it. Ask for changes afterwards and I'll work from the last one.</span>`;
    box.append(empty);
    return;
  }
  room.messages.forEach((m, i) => box.append(roomMessage(m, i)));
  const scroller = box.closest(".room__body") || box;      // the pane scrolls, not the thread
  scroller.scrollTop = scroller.scrollHeight;
}
function roomMessage(m, i) {
  const row = document.createElement("div");
  row.className = `room-msg room-msg--${m.role}`;
  if (m.role === "user") {
    row.innerHTML = `<div class="room-bubble"><div class="room-bubble__refs" hidden></div>` +
      `<span class="room-bubble__text"></span></div>`;
    row.querySelector(".room-bubble__text").textContent = m.text;
    const refs = (m.refs || []).filter((r) => r && r.url);
    const box = row.querySelector(".room-bubble__refs");
    box.hidden = !refs.length;
    for (const ref of refs) {
      const pic = document.createElement("img");
      pic.alt = "The picture this request edits";
      pic.title = "The picture this request edits";
      pic.src = ref.url;
      pic.className = "room-bubble__ref";
      box.append(pic);
    }
    return row;
  }
  const wrap = document.createElement("div");
  wrap.className = "room-bubble";
  if (m.reasoning) {
    const det = document.createElement("details");
    det.className = "think room-think";
    det.innerHTML = `<summary class="think-title">Thought${m.thinkSecs ? ` for ${fmt(m.thinkSecs, 1)} s` : ""}</summary>` +
      `<div class="thinking"></div>`;
    det.querySelector(".thinking").textContent = m.reasoning;
    wrap.append(det);
  }
  const body = document.createElement("div");
  body.className = "room-bubble__body";
  const busy = room.sending && i === room.messages.length - 1;
  if (m.error) {
    body.innerHTML = `<div class="msg-error"></div>`;
    body.firstChild.textContent = m.error;
  } else if (!m.text && !(m.tools && m.tools.length)) {
    body.innerHTML = busy ? `<span class="cursor"></span>` : "";
  } else {
    body.innerHTML = answerHtml(m);
    if (busy) body.classList.add("cursor");
  }
  wrap.append(body);
  if (m.meta) {
    const meta = document.createElement("p");
    meta.className = "muted small room-msg__meta";
    meta.textContent = m.meta;
    wrap.append(meta);
  }
  row.append(wrap);
  return row;
}
// one request to this server, streamed the way the chat is: text, reasoning, and the tool's pictures as they come
async function roomStream(body, m, signal) {
  let frame = 0, thinkStart = 0, usage = null;
  const paint = () => { frame = 0; roomRenderChat(); };
  const r = await fetch("v1/chat/completions", {method: "POST", headers: headers(true),
                                                 body: JSON.stringify(body), signal});
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { msg = (await r.json()).error.message || msg; } catch (e) { /* not json */ }
    if (r.status === 401) msg = "This server needs an API key: add it under About > Settings.";
    throw new Error(msg);
  }
  const reader = r.body.getReader(), dec = new TextDecoder();
  let buf = "", meta = null;
  for (;;) {
    const {value, done} = await reader.read();
    if (done) break;
    buf += dec.decode(value, {stream: true});
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (data === "[DONE]") continue;
      let j;
      try { j = JSON.parse(data); } catch (e) { continue; }
      if (j.error) throw new Error(j.error.message || "the engine reported an error");
      if (j.usage) usage = j.usage;
      if (j.strata_mcp) onTool(m, j.strata_mcp);
      const d = (j.choices && j.choices[0] && j.choices[0].delta) || {};
      if (d.reasoning_content) {
        if (!thinkStart) thinkStart = performance.now();
        m.reasoning = (m.reasoning || "") + d.reasoning_content;
      }
      if (d.content) {
        if (thinkStart && m.thinkSecs == null) m.thinkSecs = (performance.now() - thinkStart) / 1000;
        m.text = (m.text || "") + d.content;
      }
      if (!frame) frame = requestAnimationFrame(paint);
    }
  }
  if (frame) cancelAnimationFrame(frame);
  if (thinkStart && m.thinkSecs == null) m.thinkSecs = (performance.now() - thinkStart) / 1000;
  if (usage && usage.completion_tokens) m.meta = `${fmt(usage.completion_tokens)} tokens`;
  roomRenderChat();
}
async function roomSend(event) {
  if (event) event.preventDefault();
  const text = $("room-prompt").value.trim();
  if (!text || room.sending) return;
  if (!comfyInfo.configured) { toast("info", "ComfyUI is not set up yet", "Press Setup and add its address first."); return; }
  // The attached pictures ride with this request, not just in the instructions: the server edits the first one even
  // when the model forgets reference_id, and a text-to-image choice is replaced by the default edit workflow.
  const attached = room.refs.map((r) => ({id: r.id, url: r.url})).filter((r) => r.id);
  room.messages.push({role: "user", text, refs: attached});
  const m = {role: "assistant", text: "", reasoning: ""};
  room.messages.push(m);
  $("room-prompt").value = "";
  room.sending = true;
  roomRender();
  const history = room.messages.slice(0, -1).map((x) => ({role: x.role, content: x.text}));
  const body = {model: health.model, stream: true, reasoning_effort: settings.thinking, max_tokens: 1600,
                messages: [{role: "system", content: await roomSystem()}, ...history]};
  if (settings.images !== false && comfyInfo.configured) {
    body.strata_images = attached.length ? {references: attached.map((r) => r.id)} : true;
  }
  if (settings.search !== false && searchInfo.configured) body.strata_search = true;
  room.abort = new AbortController();
  try {
    await roomStream(body, m, room.abort.signal);
  } catch (e) {
    if (e.name === "AbortError") { m.stopped = true; m.meta = "Stopped"; }
    else m.error = e.message;
  } finally {
    room.sending = false;
    room.abort = null;
    roomRemember(m);
    roomAvoidBlank();
    if (!m.error && !m.stopped) {
      room.refs = [];                    // the picture just made is the subject now ("make it darker")
      $("room-prompt").placeholder = "Ask for a picture, or say what to change\u2026";
    }
    roomPersist();
    roomRender();
  }
}
function roomCancel() {
  if (room.abort) room.abort.abort();
}
// the last picture a turn made (for "change that one" and for the viewer's next Edit)
function roomRemember(m) {
  const made = (m.tools || []).flatMap((t) => t.images || []);
  if (made.length) {
    const last = made[made.length - 1];
    room.last = {id: last.id, url: last.url, prompt: last.prompt, workflow: last.workflow,
                 width: last.width, height: last.height, seed: last.seed};
  }
}
// a turn that ended without any words or picture should still say something happened
function roomAvoidBlank() {
  const m = room.messages[room.messages.length - 1];
  if (!m || m.role !== "assistant") return;
  if (!m.error && !m.text && !(m.tools && m.tools.length) && !m.stopped) {
    m.error = "The model answered with nothing. Try asking again, or check Monitor for the engine's state.";
  }
}
function roomPersist() {
  try {
    store.set(ROOM_KEY, {messages: room.messages.slice(-40).map((m) => ({
      role: m.role, text: m.text || "", reasoning: m.reasoning || "", tools: m.tools || [], meta: m.meta || "",
      error: m.error || "",
      refs: (m.refs || []).map((r) => ({id: r.id, url: r.url}))})), last: room.last});
  } catch (e) { /* a full storage keeps this visit's thread only */ }
}
// Every picture this room made, newest first: the transcript is the memory, and the gallery backs it when a phone
// evicts the browser's storage between visits.
function roomMade() {
  const out = [], seen = new Set();
  const add = (image, workflow) => {
    if (!image || !image.id || seen.has(image.id)) return;
    seen.add(image.id);
    out.push({id: image.id, workflow: workflow || image.workflow || "", url: image.url,
              width: image.width, height: image.height, seed: image.seed, prompt: image.prompt});
  };
  if (room.last) add(room.last, room.last.workflow);
  for (let i = room.messages.length - 1; i >= 0 && out.length < 5; i -= 1) {
    const m = room.messages[i];
    if (!m || m.role !== "assistant") continue;
    for (const t of (m.tools || []).slice().reverse()) {
      for (const image of (t.images || []).slice().reverse()) add(image, t.tool);
    }
  }
  return out.slice(0, 5);
}
function roomRestore() {
  const saved = store.get(ROOM_KEY, null);
  if (!saved || !Array.isArray(saved.messages)) return;
  room.messages = saved.messages.filter((m) => m && (m.role === "user" || m.role === "assistant"));
  room.last = saved.last || null;
  if (!room.last) {
    const made = roomMade();
    if (made.length) room.last = made[0];
  }
}
function roomNew() {
  if (room.messages.length && !confirm("Start a new picture conversation? The pictures stay in My images.")) return;
  room.messages = [];
  room.last = null;
  room.refs = [];
  roomPersist();
  roomRender();
  $("room-prompt").focus();
}
async function roomLoadGallery(reset) {
  if (reset) room.page = null;
  if (!comfyInfo.configured) { room.page = {items: [], total: 0, more: false}; roomRenderGallery(); return; }
  const query = new URLSearchParams({gallery: "1", limit: "48"});
  if (room.query) query.set("q", room.query);
  if (room.favs) query.set("favorites", "1");
  if (room.page && room.page.items.length) {
    const last = room.page.items[room.page.items.length - 1];
    if (last && last.created) query.set("before", String(last.created));
  }
  try {
    const j = await (await fetch(`comfy?${query}`, {headers: headers()})).json();
    const page = j.page || {items: [], total: 0, more: false};
    room.page = reset || !room.page ? page : {...page, items: [...room.page.items, ...page.items]};
  } catch (e) {
    room.page = {items: [], total: 0, more: false};
  }
  roomRenderGallery();
}
function roomRenderGallery() {
  const grid = $("room-grid");
  const page = room.page;
  if (!grid) return;
  $("room-count-note").textContent = page ? `${page.total} image${page.total === 1 ? "" : "s"}` : "";
  $("room-more").hidden = !(page && page.more);
  $("room-favs").setAttribute("aria-pressed", String(room.favs));
  if (!page) { grid.replaceChildren(); return; }
  if (!page.items.length) {
    grid.innerHTML = `<div class="st-empty"><span class="st-empty__title">` +
      `${room.query ? "Nothing matches" : "No images yet"}</span><span>` +
      `${room.query ? "Try another word." : "What you make appears here, newest first."}</span></div>`;
    return;
  }
  grid.replaceChildren();
  for (const item of page.items) {
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "room-card";
    tile.dataset.id = item.id;
    tile.innerHTML = `<img alt="" loading="lazy" src="${esc(item.url)}">` +
      `<span class="room-card__prompt"></span>` +
      (item.favorite ? `<span class="room-card__star" aria-label="Favourite">â˜…</span>` : "");
    tile.querySelector(".room-card__prompt").textContent = item.prompt || item.workflow || "";
    tile.onclick = () => roomViewerOpen(item.id, page.items);
    grid.append(tile);
  }
}
function roomRenderTemplates() {
  const box = $("room-templates");
  box.replaceChildren();
  for (const tpl of window.COMFY_TEMPLATES || []) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "room-template";
    card.innerHTML = `<span class="room-template__head"><span class="room-template__title"></span>` +
      `<span class="mcp-chip"></span></span><span class="room-template__prompt"></span>`;
    card.querySelector(".room-template__title").textContent = tpl.title;
    card.querySelector(".mcp-chip").textContent = tpl.tag;
    card.querySelector(".room-template__prompt").textContent = tpl.prompt;
    card.onclick = () => {
      roomTab("create");
      $("room-prompt").value = tpl.prompt;
      $("room-prompt").focus();
    };
    box.append(card);
  }
}
function roomViewerOpen(id, list) {
  const items = (list || (room.page ? room.page.items : [])).filter((x) => x && x.id);
  room.viewer = {id, items};
  $("room-viewer").hidden = false;
  roomViewerRender();
}
function roomViewerRender() {
  if (!room.viewer) return;
  const items = room.viewer.items;
  const at = items.findIndex((x) => x.id === room.viewer.id);
  const item = items[at] || items[0];
  if (!item) { roomViewerClose(); return; }
  room.viewer.id = item.id;
  $("room-viewer-img").src = item.url;
  $("room-viewer-count").textContent = `${at + 1} of ${items.length}`;
  $("room-viewer-prev").disabled = at <= 0;
  $("room-viewer-next").disabled = at >= items.length - 1;
  const bits = [item.workflow, item.width && item.height ? `${item.width}Ã—${item.height}` : "",
                item.seed != null ? `seed ${item.seed}` : "", item.created ? roomWhen(item.created) : ""].filter(Boolean);
  $("room-viewer-meta").innerHTML = `<p class="room-viewer__prompt"></p><p class="muted small"></p>`;
  $("room-viewer-meta").querySelector(".room-viewer__prompt").textContent = item.prompt || "(no prompt)";
  $("room-viewer-meta").querySelector(".muted").textContent = bits.join(" Â· ");
  const actions = $("room-viewer-actions");
  actions.replaceChildren();
  const add = (label, act, primary) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `st-btn ${primary ? "st-btn--primary" : "st-btn--secondary"}`;
    b.textContent = label;
    b.onclick = () => act(item);
    actions.append(b);
  };
  add("Edit it", () => roomEdit(item), true);
  add("Ask for a change", () => roomAskChange(item));
  add("Download", () => {
    const link = document.createElement("a");
    link.href = item.url;
    link.download = `arya-${item.id}.png`;
    link.click();
  });
  add(item.favorite ? "â˜… Favourite" : "â˜† Favourite", async () => {
    try {
      await comfyPost({favorite: {id: item.id}});
      item.favorite = !item.favorite;
      roomViewerRender();
      roomLoadGallery(true);
    } catch (e) { toast("error", "The favourite was not saved", e.message, 6000); }
  });
  add("Delete", async () => {
    if (!confirm("Delete this image? The file goes too.")) return;
    try {
      await comfyPost({delete: [item.id]});
      roomViewerClose();
      roomLoadGallery(true);
      toast("success", "Image deleted");
    } catch (e) { toast("error", "The image was not deleted", e.message, 6000); }
  });
}
function roomViewerClose() {
  $("room-viewer").hidden = true;
  room.viewer = null;
}
// "Edit it": put the picture in this room's hands and let the agent take it from there - the last picture it saw
function roomEdit(item) {
  roomViewerClose();
  room.last = {id: item.id, url: item.url, prompt: item.prompt, workflow: item.workflow,
               width: item.width, height: item.height, seed: item.seed};
  roomTab("create");
  $("room-prompt").value = "Change this picture: ";
  $("room-prompt").focus();
  roomPersist();
}
function roomAskChange(item) {
  roomEdit(item);
  $("room-prompt").value = "";
  $("room-prompt").placeholder = "What should change about this picture?";
  $("room-prompt").focus();
}
function roomWhen(seconds) {
  return new Date(seconds * 1000).toLocaleString(undefined,
    {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
}
function roomDebounce(fn, ms) {
  let timer = 0;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}
// --- the room's controls
for (const b of $("room-tabs").children) b.onclick = () => roomTab(b.dataset.roomTab);
$("room-form").onsubmit = roomSend;
$("room-cancel").onclick = roomCancel;
$("room-new").onclick = roomNew;
$("room-settings").onclick = () => openImagesDialog();
$("room-prompt").onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); roomSend(); }
};
$("room-search").oninput = roomDebounce(() => { room.query = $("room-search").value.trim(); roomLoadGallery(true); }, 250);
$("room-favs").onclick = () => { room.favs = !room.favs; roomLoadGallery(true); };
$("room-more").onclick = () => roomLoadGallery(false);
$("room-ref-btn").onclick = () => $("room-ref-file").click();
setupVoice($("room-voice-btn"), $("room-prompt"));      // the same dictation as the chat's box
$("room-ref-file").onchange = async () => {
  const file = $("room-ref-file").files[0];
  if (!file) return;
  try {
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error("The picture could not be read"));
      reader.readAsDataURL(file);
    });
    const answer = await comfyPost({upload: {data_url: dataUrl, prompt: file.name}});
    room.refs.push({id: answer.item.id, url: answer.item.url, prompt: answer.item.prompt});
    roomRender();
    roomLoadGallery(true);
    toast("success", "Picture attached", "Ask for a change and the agent will use it as the reference.");
  } catch (e) {
    toast("error", "That picture was not added", e.message, 7000);
  } finally {
    $("room-ref-file").value = "";
  }
};
$("room-viewer-close").onclick = roomViewerClose;
$("room-viewer-prev").onclick = () => {
  const items = room.viewer.items, at = items.findIndex((x) => x.id === room.viewer.id);
  if (at > 0) { room.viewer.id = items[at - 1].id; roomViewerRender(); }
};
$("room-viewer-next").onclick = () => {
  const items = room.viewer.items, at = items.findIndex((x) => x.id === room.viewer.id);
  if (at >= 0 && at < items.length - 1) { room.viewer.id = items[at + 1].id; roomViewerRender(); }
};
$("room-viewer").onclick = (e) => { if (e.target === $("room-viewer")) roomViewerClose(); };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("room-viewer").hidden) roomViewerClose();
  if (e.key === "ArrowLeft" && !$("room-viewer").hidden) $("room-viewer-prev").click();
  if (e.key === "ArrowRight" && !$("room-viewer").hidden) $("room-viewer-next").click();
});
roomRestore();
roomRenderChat();

