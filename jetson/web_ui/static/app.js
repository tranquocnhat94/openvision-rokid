const state = {
  health: null,
  sessions: [],
  skills: [],
  events: [],
  realtime: [],
  voiceOutput: [],
  media: [],
  preview: [],
  rv101Ingest: null,
  perception: [],
  yolo26: null,
  hudScenes: [],
  debugStt: null,
};

let refreshInFlight = false;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function text(value) {
  if (value === true) return "true";
  if (value === false) return "false";
  if (value === null || value === undefined) return "none";
  return String(value);
}

function renderHealth() {
  const chip = document.querySelector("#healthChip");
  const facts = document.querySelector("#healthFacts");
  if (!state.health) {
    chip.textContent = "Offline";
    chip.className = "chip error";
    return;
  }
  chip.textContent = "Online";
  chip.className = "chip";
  facts.innerHTML = "";
  for (const key of ["service", "version", "environment", "realtime_model", "voice_output", "openai_key_present", "openai_key_source", "debug_stt_enabled", "debug_stt_status", "rv101_tcp_ingest", "yolo26_adapter_status", "sessions", "skills"]) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = key;
    dd.textContent = text(state.health[key]);
    facts.append(dt, dd);
  }
}

function renderSessions() {
  const root = document.querySelector("#sessions");
  root.innerHTML = "";
  if (!state.sessions.length) {
    root.innerHTML = '<div class="item"><div class="item-title">No sessions</div><div class="item-meta">Create RV101 or iPhone sessions.</div></div>';
    return;
  }
  for (const session of state.sessions) {
    const item = document.createElement("article");
    item.className = "item";
    item.innerHTML = `
      <div class="item-title">${session.client_kind}</div>
      <div class="item-meta">${session.session_id}</div>
      <div class="item-meta">status: ${session.status}</div>
    `;
    root.append(item);
  }
}

function firstSessionId() {
  return state.sessions[0]?.session_id || null;
}

function renderRealtime() {
  const root = document.querySelector("#realtimeList");
  root.innerHTML = "";
  if (!state.realtime.length) {
    root.innerHTML = '<div class="item"><div class="item-title">No Realtime session</div><div class="item-meta">Start after creating an RV101 or iPhone session.</div></div>';
    return;
  }
  for (const item of state.realtime) {
    const row = document.createElement("article");
    row.className = "item";
    const statusClass = item.status === "connected" ? "chip" : item.status === "blocked" ? "chip warn" : item.status === "error" ? "chip error" : "chip muted";
    const voice = state.voiceOutput.find((output) => output.session_id === item.session_id);
    row.innerHTML = `
      <div class="item-title">${item.session_id}</div>
      <div class="item-meta"><span class="${statusClass}">${item.status}</span> <span class="chip muted">${item.turn_policy}</span></div>
      <div class="item-meta">model: ${item.model}</div>
      <div class="item-meta">output: ${(item.output_modalities || ["text"]).join(" + ")}</div>
      <div class="item-meta">voice: ${voice ? `${voice.delta_count} chunks · ${voice.subscribers} listeners` : "idle"}</div>
      <div class="item-meta">last: ${item.last_event_type || "none"} · events: ${item.event_count}</div>
      ${item.error ? `<div class="item-meta">${item.error.code}: ${item.error.message}</div>` : ""}
    `;
    root.append(row);
  }
}

function renderDebugStt() {
  const root = document.querySelector("#debugStt");
  if (!root) return;
  root.innerHTML = "";
  const status = state.debugStt?.status;
  const transcripts = state.debugStt?.transcripts || [];
  const statusClass = status?.enabled ? "chip" : "chip muted";
  const header = document.createElement("article");
  header.className = "item";
  header.innerHTML = `
    <div class="item-title">Mini PC PhoWhisper</div>
    <div class="item-meta"><span class="${statusClass}">${status?.status || "unknown"}</span> ${status?.transcribe_url || "disabled"}</div>
    <div class="item-meta">turns: ${status?.transcript_count ?? 0} · buffers: ${status?.turn_buffers ?? 0} · window: ${status?.min_audio_ms ?? "?"}-${status?.max_audio_ms ?? "?"}ms</div>
    ${status?.last_error ? `<div class="item-meta">last error: ${status.last_error}</div>` : ""}
  `;
  root.append(header);
  if (!transcripts.length) {
    const empty = document.createElement("article");
    empty.className = "item";
    empty.innerHTML = '<div class="item-title">No completed turns</div><div class="item-meta">Completed Vietnamese sentences from the mini PC STT sidecar will appear here.</div>';
    root.append(empty);
    return;
  }
  for (const transcript of transcripts.slice().reverse().slice(0, 8)) {
    const item = document.createElement("article");
    item.className = "transcript-row";
    const textLine = document.createElement("div");
    textLine.className = "transcript-text";
    textLine.textContent = transcript.text || "(empty)";
    const meta = document.createElement("div");
    meta.className = "item-meta";
    meta.textContent = `${transcript.session_id || ""} · ${transcript.timestamp || ""}`;
    const chipRoot = document.createElement("div");
    chipRoot.className = "transcript-chips";
    for (const chip of [
      transcript.backend || "stt",
      transcript.source || "audio",
      transcript.duration_ms ? `${transcript.duration_ms}ms` : "",
      transcript.wall_ms ? `${transcript.wall_ms}ms wall` : "",
    ].filter(Boolean)) {
      const span = document.createElement("span");
      span.textContent = chip;
      chipRoot.append(span);
    }
    item.append(textLine, meta, chipRoot);
    root.append(item);
  }
}

function matchingPerception(sessionId) {
  return state.perception.find((item) => item.session_id === sessionId) || null;
}

function bboxStyle(bbox, width, height) {
  if (!Array.isArray(bbox) || bbox.length < 4) return null;
  let [x1, y1, x2, y2] = bbox.map(Number);
  if (![x1, y1, x2, y2].every(Number.isFinite)) return null;
  if (Math.max(x1, y1, x2, y2) > 1.5) {
    if (!width || !height) return null;
    x1 /= width;
    x2 /= width;
    y1 /= height;
    y2 /= height;
  }
  const left = Math.max(0, Math.min(100, x1 * 100));
  const top = Math.max(0, Math.min(100, y1 * 100));
  const boxWidth = Math.max(1, Math.min(100 - left, (x2 - x1) * 100));
  const boxHeight = Math.max(1, Math.min(100 - top, (y2 - y1) * 100));
  return `left:${left}%;top:${top}%;width:${boxWidth}%;height:${boxHeight}%;`;
}

function renderPreviewOverlay(root, preview) {
  root.innerHTML = "";
  const perception = matchingPerception(preview.session_id);
  if (!perception) return;
  for (const object of perception.objects || []) {
    const style = bboxStyle(object.bbox, perception.width || preview.width, perception.height || preview.height);
    if (!style) continue;
    const box = document.createElement("div");
    box.className = "bbox";
    box.setAttribute("style", style);
    const confidence = Number(object.confidence || 0);
    box.innerHTML = `<span>${object.label} ${confidence ? Math.round(confidence * 100) + "%" : ""}</span>`;
    root.append(box);
  }
}

function previewCards() {
  return [...document.querySelectorAll(".preview-card[data-session-id]")];
}

function findPreviewCard(root, sessionId) {
  return [...root.querySelectorAll(".preview-card[data-session-id]")]
    .find((card) => card.dataset.sessionId === sessionId) || null;
}

function ensurePreviewCard(root, sessionId) {
  let card = findPreviewCard(root, sessionId);
  if (card) return card;
  card = document.createElement("article");
  card.className = "preview-card";
  card.dataset.sessionId = sessionId;
  card.innerHTML = `
    <div class="preview-stage">
      <div class="preview-empty">No decoded frame</div>
      <div class="bbox-layer"></div>
    </div>
    <div class="preview-meta">
      <div class="item-title"></div>
      <div class="item-meta preview-size"></div>
      <div class="item-meta preview-time"></div>
    </div>
  `;
  root.append(card);
  return card;
}

function updatePreviewStage(card, preview) {
  const stage = card.querySelector(".preview-stage");
  const streamUrl = preview.has_frame ? preview.mjpeg_url || preview.image_url : "";
  let image = stage.querySelector("img.preview-frame");
  let empty = stage.querySelector(".preview-empty");
  if (!streamUrl) {
    if (image) image.remove();
    if (!empty) {
      empty = document.createElement("div");
      empty.className = "preview-empty";
      empty.textContent = "No decoded frame";
      stage.prepend(empty);
    }
    return;
  }
  if (empty) empty.remove();
  if (!image) {
    image = document.createElement("img");
    image.className = "preview-frame";
    image.alt = `Preview ${preview.session_id}`;
    image.decoding = "async";
    stage.prepend(image);
  }
  if (image.getAttribute("src") !== streamUrl) {
    image.src = streamUrl;
  }
}

function updatePreviewCard(card, preview) {
  updatePreviewStage(card, preview);
  card.querySelector(".item-title").textContent = preview.session_id;
  card.querySelector(".preview-size").textContent = `${preview.source || "source"} · ${preview.width || "?"}x${preview.height || "?"} · frame ${preview.frame_count || 0}`;
  card.querySelector(".preview-time").textContent = preview.updated_at || "waiting";
  renderPreviewOverlay(card.querySelector(".bbox-layer"), preview);
}

function renderPreview() {
  const root = document.querySelector("#previewList");
  if (!root) return;
  const previewBySession = new Map(state.preview.map((item) => [item.session_id, item]));
  const sessionsWithMedia = state.media.filter((item) => item.video.state === "receiving");
  const cards = [...state.preview];
  for (const item of sessionsWithMedia) {
    if (!previewBySession.has(item.session_id)) {
      cards.push({
        session_id: item.session_id,
        source: item.video.transport || "media",
        width: item.video.width,
        height: item.video.height,
        frame_count: item.video.frame_count,
        updated_at: item.video.updated_at,
        has_frame: false,
      });
    }
  }
  if (!cards.length) {
    root.innerHTML = `
      <article class="item">
        <div class="item-title">No decoded preview</div>
        <div class="item-meta">iPhone WebRTC frames will appear here. RV101 H.264 needs a decoder hook before image preview is available.</div>
      </article>
    `;
    return;
  }
  if (root.querySelector(".item:not(.preview-card)")) {
    root.innerHTML = "";
  }
  const activeSessionIds = new Set(cards.map((preview) => preview.session_id));
  for (const card of previewCards()) {
    if (!activeSessionIds.has(card.dataset.sessionId)) {
      card.remove();
    }
  }
  for (const preview of cards) {
    const card = ensurePreviewCard(root, preview.session_id);
    updatePreviewCard(card, preview);
  }
}

function renderMedia() {
  const root = document.querySelector("#mediaList");
  root.innerHTML = "";
  if (!state.media.length) {
    root.innerHTML = '<div class="item"><div class="item-title">No media yet</div><div class="item-meta">RV101 heartbeats and iPhone WebRTC tracks will appear here.</div></div>';
    return;
  }
  for (const item of state.media) {
    const row = document.createElement("article");
    row.className = "item";
    const videoFps = item.video.estimated_fps ?? item.video.fps ?? 0;
    const frameAge = item.video.last_frame_age_ms ?? null;
    const frameAgeText = frameAge === null ? "no frame" : `${frameAge}ms`;
    const resolution = item.video.width && item.video.height ? `${item.video.width}x${item.video.height}` : "unknown";
    row.innerHTML = `
      <div class="item-title">${item.session_id}</div>
      <div class="item-meta">video: ${item.video.state} · ${item.video.transport || "none"} · ${item.video.codec || "track"}</div>
      <div class="item-meta">stream: ${videoFps ? videoFps.toFixed(1) : "?"} fps · age ${frameAgeText} · ${resolution} · frames ${item.video.frame_count || 0}</div>
      <div class="item-meta">audio: ${item.audio.state} · ${item.audio.transport || "none"} · strong ${(item.audio.strong_chunk_ratio * 100).toFixed(1)}%</div>
      <div class="item-meta">signal: avg ${Math.round(item.audio.avg_abs || 0)} · peak ${item.audio.peak_abs || 0} · non-silent ${((item.audio.non_silent_ratio || 0) * 100).toFixed(1)}% · gate ${item.audio.gate_state || "idle"} ${item.audio.gate_open_count || 0}/${item.audio.gate_close_count || 0}</div>
      <div class="item-meta">source: ${item.audio.source || "unknown"}</div>
    `;
    root.append(row);
  }
}

function renderRv101Ingest() {
  const root = document.querySelector("#rv101Ingest");
  if (!root) return;
  const ingest = state.rv101Ingest;
  if (!ingest) {
    root.innerHTML = '<div class="item"><div class="item-title">RV101 ingest</div><div class="item-meta">No status yet.</div></div>';
    return;
  }
  const chipClass = ingest.status === "running" ? "chip" : ingest.status === "disabled" ? "chip muted" : "chip warn";
  root.innerHTML = `
    <article class="item">
      <div class="item-title">RV101 TCP</div>
      <div class="item-meta"><span class="${chipClass}">${ingest.status}</span> <span class="chip muted">${ingest.protocol}</span></div>
      <div class="item-meta">video: ${ingest.advertised_host}:${ingest.video_port}</div>
      <div class="item-meta">audio: ${ingest.advertised_host}:${ingest.audio_port}</div>
    </article>
  `;
}

function renderPerception() {
  const root = document.querySelector("#perceptionList");
  root.innerHTML = "";
  if (!state.perception.length) {
    root.innerHTML = '<div class="item"><div class="item-title">No perception snapshot</div><div class="item-meta">YOLO26 adapter snapshots will appear here.</div></div>';
    return;
  }
  for (const item of state.perception) {
    const people = item.objects.filter((object) => object.label === "person" || object.label === "people").length;
    const row = document.createElement("article");
    row.className = "item";
    row.innerHTML = `
      <div class="item-title">${item.session_id}</div>
      <div class="item-meta">${item.source} · ${item.objects.length} objects · ${people} people</div>
      <div class="item-meta">${item.snapshot_id}</div>
    `;
    root.append(row);
  }
}

function renderYolo26Adapter() {
  const root = document.querySelector("#yolo26Adapter");
  if (!root) return;
  root.innerHTML = "";
  const adapter = state.yolo26;
  if (!adapter) {
    root.innerHTML = '<div class="item"><div class="item-title">YOLO26 adapter</div><div class="item-meta">No status yet.</div></div>';
    return;
  }
  const chipClass = adapter.status === "ready" || adapter.status === "configured" ? "chip" : adapter.status === "disabled" ? "chip muted" : "chip error";
  const item = document.createElement("article");
  item.className = "item";
  item.innerHTML = `
    <div class="item-title">YOLO26 Rokid</div>
    <div class="item-meta"><span class="${chipClass}">${adapter.status}</span> <span class="chip muted">${adapter.mode}</span></div>
    <div class="item-meta">${adapter.message}</div>
    <div class="item-meta">engine: ${text(adapter.engine_exists)} · labels: ${text(adapter.labels_exists)}</div>
    <div class="item-meta">isolation: ${adapter.isolation}</div>
  `;
  root.append(item);
}

function renderSkills() {
  const root = document.querySelector("#skills");
  root.innerHTML = "";
  for (const skill of state.skills) {
    const item = document.createElement("article");
    item.className = "item";
    const cloud = skill.cloud_allowed ? '<span class="chip warn">cloud</span>' : '<span class="chip muted">local</span>';
    item.innerHTML = `
      <div class="item-title">${skill.name}</div>
      <div class="item-meta">${skill.description}</div>
      <div class="item-meta">${cloud} <span class="chip muted">${skill.hud_policy}</span></div>
    `;
    root.append(item);
  }
}

function renderEvents() {
  const root = document.querySelector("#events");
  root.innerHTML = "";
  for (const event of state.events.slice().reverse()) {
    const item = document.createElement("div");
    item.className = "event";
    const timestamp = document.createElement("code");
    timestamp.className = "event-time";
    timestamp.textContent = event.timestamp || "";
    const name = document.createElement("code");
    name.className = "event-name";
    name.textContent = `${event.module || "event"}:${event.event_type || "unknown"}`;
    const payload = document.createElement("code");
    payload.className = "event-payload";
    payload.textContent = JSON.stringify(event.payload || {});
    item.append(timestamp, name, payload);
    root.append(item);
  }
}

function renderHud(scene) {
  document.querySelector("#hudAnswer").textContent = scene.answer_strip || "No HUD scene";
  const chips = document.querySelector("#hudChips");
  chips.innerHTML = "";
  for (const chip of scene.edge_chips || []) {
    const span = document.createElement("span");
    span.textContent = chip;
    chips.append(span);
  }
  const thumbs = document.querySelector("#hudThumbs");
  if (!thumbs) return;
  thumbs.innerHTML = "";
  for (const thumbnail of (scene.thumbnails || []).slice(0, 4)) {
    const item = document.createElement("div");
    item.className = "hud-thumb";
    const imageUrl = typeof thumbnail.image_url === "string" ? thumbnail.image_url : "";
    if (imageUrl) {
      const image = document.createElement("img");
      image.src = imageUrl;
      image.alt = thumbnail.caption || thumbnail.label || thumbnail.target_id || "target";
      image.addEventListener("error", () => {
        const placeholder = document.createElement("div");
        placeholder.className = "hud-thumb-placeholder";
        placeholder.textContent = thumbnail.label || "target";
        image.replaceWith(placeholder);
      }, { once: true });
      item.append(image);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "hud-thumb-placeholder";
      placeholder.textContent = thumbnail.label || "target";
      item.append(placeholder);
    }
    const caption = document.createElement("span");
    caption.textContent = thumbnail.caption || thumbnail.target_id || thumbnail.label || "candidate";
    item.append(caption);
    thumbs.append(item);
  }
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
  state.health = await api("/api/health");
  state.sessions = (await api("/api/sessions")).sessions;
  state.skills = (await api("/api/skills")).skills;
  state.realtime = (await api("/api/realtime")).realtime;
  state.voiceOutput = (await api("/api/realtime/voice-output")).voice_output;
  state.media = (await api("/api/media")).media;
  state.preview = (await api("/api/preview")).preview;
  state.rv101Ingest = (await api("/api/rv101/ingest")).ingest;
  state.perception = (await api("/api/perception")).perception;
  state.yolo26 = (await api("/api/adapters/yolo26")).adapter;
  state.hudScenes = (await api("/api/hud/latest")).hud_scenes;
  state.debugStt = await api("/api/debug-stt?limit=40");
  state.events = (await api("/api/events?limit=80")).events;
  renderHealth();
  renderSessions();
  renderRealtime();
  renderDebugStt();
  renderPreview();
  renderMedia();
  renderRv101Ingest();
  renderPerception();
  renderYolo26Adapter();
  if (state.hudScenes.length) {
    renderHud(state.hudScenes[state.hudScenes.length - 1]);
  }
  renderSkills();
  renderEvents();
  } finally {
    refreshInFlight = false;
  }
}

async function createSession(clientKind, capabilities) {
  await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ client_kind: clientKind, capabilities }),
  });
  await refresh();
}

async function dryRunCount() {
  const result = await api("/api/skills/count_people/dry-run", {
    method: "POST",
    body: JSON.stringify({ args: { frame_window_ms: 1000, min_confidence: 0.4 } }),
  });
  await refresh();
  alert(`count_people: ${result.status}`);
}

async function samplePerception() {
  let sessionId = firstSessionId();
  if (!sessionId) {
    const created = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ client_kind: "iphone_simulator", capabilities: { video: "webrtc", audio: "webrtc", hud: "scene_json" } }),
    });
    sessionId = created.session.session_id;
  }
  await api(`/api/perception/${sessionId}/detections`, {
    method: "POST",
    body: JSON.stringify({
      source: "sample_operator_snapshot",
      frame_id: "sample_frame",
      width: 1280,
      height: 720,
      detections: [
        { label: "person", confidence: 0.91, bbox: [0.1, 0.1, 0.25, 0.8], track_id: "p1" },
        { label: "person", confidence: 0.87, bbox: [0.5, 0.12, 0.68, 0.82], track_id: "p2" },
      ],
    }),
  });
  await refresh();
}

async function executeCount() {
  const sessionId = firstSessionId();
  if (!sessionId) {
    alert("Create a session first.");
    return;
  }
  const result = await api("/api/skills/count_people/execute", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, args: { min_confidence: 0.25 } }),
  });
  await refresh();
  alert(`count_people: ${result.status} · ${result.result?.count ?? "no count"}`);
}

async function startRealtime() {
  let sessionId = firstSessionId();
  if (!sessionId) {
    const created = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ client_kind: "iphone_simulator", capabilities: { video: "webrtc", audio: "webrtc", hud: "scene_json" } }),
    });
    sessionId = created.session.session_id;
  }
  await api(`/api/realtime/${sessionId}/start`, {
    method: "POST",
    body: JSON.stringify({
      turn_policy: "manual",
      voice_output: Boolean(document.querySelector("#voiceOutputToggle")?.checked),
    }),
  });
  await refresh();
}

async function sendRealtimeText() {
  const sessionId = firstSessionId();
  if (!sessionId) {
    alert("Create a session first.");
    return;
  }
  try {
    await api(`/api/realtime/${sessionId}/text`, {
      method: "POST",
      body: JSON.stringify({ text: "Phía trước có bao nhiêu người?" }),
    });
  } catch (error) {
    alert(error.message);
  }
  await refresh();
}

async function warmDebugStt() {
  try {
    await api("/api/debug-stt/warm", { method: "POST" });
  } catch (error) {
    alert(error.message);
  }
  await refresh();
}

async function loadSampleHud() {
  const sessionId = firstSessionId();
  const result = sessionId
    ? await api(`/api/hud/${sessionId}/test-scene`, { method: "POST" })
    : await api("/api/hud/sample");
  renderHud(result.hud_scene);
  await refresh();
}

document.querySelector("#refreshButton").addEventListener("click", refresh);
document.querySelector("#rv101Button").addEventListener("click", () =>
  createSession("rv101_glasses", { video: "h264_tcp", audio: "pcm_tcp", hud: "scene_json" }),
);
document.querySelector("#iphoneButton").addEventListener("click", () =>
  createSession("iphone_simulator", { video: "webrtc", audio: "webrtc", hud: "scene_json" }),
);
document.querySelector("#dryRunButton").addEventListener("click", dryRunCount);
document.querySelector("#samplePerceptionButton").addEventListener("click", samplePerception);
document.querySelector("#executeCountButton").addEventListener("click", executeCount);
document.querySelector("#hudButton").addEventListener("click", loadSampleHud);
document.querySelector("#startRealtimeButton").addEventListener("click", startRealtime);
document.querySelector("#textRealtimeButton").addEventListener("click", sendRealtimeText);
document.querySelector("#warmDebugSttButton").addEventListener("click", warmDebugStt);

refresh().then(loadSampleHud).catch((error) => {
  state.health = null;
  renderHealth();
  console.error(error);
});

window.setInterval(() => {
  refresh().catch((error) => {
    state.health = null;
    renderHealth();
    console.error(error);
  });
}, 1200);
