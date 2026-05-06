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
  yolo26Worker: null,
  faceIdentity: null,
  faceIdentityWorker: null,
  identity: null,
  identityContacts: [],
  peopleRegistry: null,
  hudScenes: [],
  debugStt: null,
  perceptionStreamStatus: "idle",
};

let refreshInFlight = false;
let perceptionWs = null;
let perceptionWsReconnectTimer = null;
const DASHBOARD_REFRESH_MS = 1200;
const h264PreviewPlayers = new Map();
const sensorPreviewDisplayState = new Map();

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

function normalized(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase();
}

function setText(parent, selector, value) {
  const node = parent.querySelector(selector);
  if (node) node.textContent = value;
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
  for (const key of ["service", "version", "environment", "realtime_model", "voice_output", "openai_key_present", "openai_key_source", "debug_stt_enabled", "debug_stt_status", "rv101_tcp_ingest", "yolo26_adapter_status", "face_identity_adapter_status", "identity_status", "identity_contacts", "identity_samples", "people_registry_status", "people_count", "people_remembered_captures", "people_pending_face_sync", "people_immich_configured", "sessions", "skills"]) {
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

function mergePerceptionSnapshot(snapshot) {
  if (!snapshot || !snapshot.session_id) return;
  const index = state.perception.findIndex((item) => item.session_id === snapshot.session_id);
  if (index >= 0) {
    state.perception[index] = snapshot;
  } else {
    state.perception.push(snapshot);
  }
}

function perceptionWsUrl() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/perception`;
}

function connectPerceptionStream() {
  if (perceptionWs && (perceptionWs.readyState === WebSocket.OPEN || perceptionWs.readyState === WebSocket.CONNECTING)) {
    return;
  }
  if (perceptionWsReconnectTimer) {
    window.clearTimeout(perceptionWsReconnectTimer);
    perceptionWsReconnectTimer = null;
  }
  try {
    perceptionWs = new WebSocket(perceptionWsUrl());
  } catch (error) {
    state.perceptionStreamStatus = `error:${error.name || "websocket"}`;
    perceptionWsReconnectTimer = window.setTimeout(connectPerceptionStream, 1500);
    return;
  }
  state.perceptionStreamStatus = "connecting";
  perceptionWs.onopen = () => {
    state.perceptionStreamStatus = "live";
  };
  perceptionWs.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.type === "perception_snapshot" && message.snapshot) {
        mergePerceptionSnapshot(message.snapshot);
        renderPerception();
      }
    } catch (_error) {
      state.perceptionStreamStatus = "decode_error";
    }
  };
  perceptionWs.onerror = () => {
    state.perceptionStreamStatus = "error";
  };
  perceptionWs.onclose = () => {
    state.perceptionStreamStatus = "closed";
    perceptionWs = null;
    perceptionWsReconnectTimer = window.setTimeout(connectPerceptionStream, 1500);
  };
}

function objectAttributes(object) {
  return (object && object.attributes && typeof object.attributes === "object") ? object.attributes : {};
}

function objectDisplayLabel(object) {
  const attrs = objectAttributes(object);
  const label = String(object?.label || "object");
  const track = object?.track_id || object?.object_id || "";
  const displayName = object?.display_name || object?.name || attrs.display_name || attrs.identity_name || attrs.known_name || attrs.contact_name;
  if (displayName) return String(displayName);
  const unclassified = attrs.classification_status === "unclassified";
  const hideConfidence = attrs.confidence_display === "hidden" || attrs.confidence_source === "missing";
  const base = unclassified && ["object", "unknown", "obj"].includes(label.toLowerCase())
    ? `YOLO track${track ? ` ${track}` : ""}`
    : label;
  if (hideConfidence) return base;
  const confidence = Number(object?.confidence || 0);
  return `${base} ${confidence ? Math.round(confidence * 100) + "%" : ""}`.trim();
}

function previewMetadata(preview) {
  const route = previewRoute(preview);
  return { ...(preview.metadata || {}), ...(route?.metadata || {}) };
}

function previewRoute(preview) {
  const route = preview?.sensor_preview || preview?.active_route;
  return route && typeof route === "object" ? route : null;
}

function previewRouteKind(preview) {
  return String(previewRoute(preview)?.route_kind || preview.sensor_preview_route_kind || "");
}

function previewRouteIsLive(preview) {
  const route = previewRoute(preview);
  return route?.media_mode === "live_video" || ["raw_h264", "deepstream_osd_h264", "stable_overlay_h264"].includes(previewRouteKind(preview));
}

function previewRouteLabel(preview) {
  const route = previewRoute(preview);
  const kind = previewRouteKind(preview);
  if (route?.desired_route_kind === "deepstream_osd_h264" && kind === "raw_h264") {
    return "DeepStream OSD pending · raw H.264";
  }
  if (kind === "deepstream_osd_h264") return "DeepStream OSD H.264";
  if (kind === "stable_overlay_h264") return "Stable YOLO26 overlay H.264";
  if (kind === "raw_h264") return route?.primary_branch === "face_identity" ? "Face Identity live H.264" : "raw RV101 H.264";
  if (kind === "snapshot_image") return "snapshot evidence";
  return preview.source || "source";
}

function previewResolutionLabel(preview, metadata) {
  const route = previewRoute(preview);
  const width = Number(route?.width || metadata.preview_width || preview.width || 0);
  const height = Number(route?.height || metadata.preview_height || preview.height || 0);
  const sourceWidth = Number(metadata.source_width || 0);
  const sourceHeight = Number(metadata.source_height || 0);
  const resolution = width && height ? `${width}x${height}` : `${preview.width || "?"}x${preview.height || "?"}`;
  const downscaled = !previewRouteIsLive(preview) && (metadata.preview_downscaled === true || metadata.preview_profile === "downscaled");
  if (previewUsesDeepStreamH264(preview)) {
    const source = sourceWidth && sourceHeight ? ` from ${sourceWidth}x${sourceHeight}` : "";
    return `DeepStream OSD H.264 ${resolution}${source}`;
  }
  if (route?.desired_route_kind === "deepstream_osd_h264" && route?.route_kind === "raw_h264") {
    const source = sourceWidth && sourceHeight ? `${sourceWidth}x${sourceHeight}` : `${preview.width || "?"}x${preview.height || "?"}`;
    return `raw H.264 ${source} while OSD warms up`;
  }
  if (preview.h264_ws_url || preview.h264_live?.h264_ws_url) {
    const source = sourceWidth && sourceHeight ? `${sourceWidth}x${sourceHeight}` : `${preview.width || "?"}x${preview.height || "?"}`;
    return downscaled ? `live H.264 ${source} · AI JPEG ${resolution}` : `live H.264 ${source}`;
  }
  if (downscaled) {
    const source = sourceWidth && sourceHeight ? ` from ${sourceWidth}x${sourceHeight}` : "";
    return `preview downscaled ${resolution}${source}`;
  }
  if (metadata.preview_profile === "full_res") {
    return `full-res preview ${resolution}`;
  }
  if (preview.source === "rv101_live_h264" && width === 640 && height === 360) {
    return "preview downscaled 640x360";
  }
  return resolution;
}

function sensorMetadataLabel(metadata) {
  const parts = [];
  if (metadata.preview_stale === true || metadata.preview_status === "stopped") parts.push(`status stopped${metadata.ended_reason ? ` (${metadata.ended_reason})` : ""}`);
  if (metadata.profile) parts.push(`profile ${metadata.profile}`);
  if (metadata.orientation !== undefined && metadata.orientation !== null) parts.push(`orientation ${metadata.orientation}`);
  if (metadata.rotation_degrees !== undefined && metadata.rotation_degrees !== null) parts.push(`rotation ${metadata.rotation_degrees}deg`);
  if (metadata.mirrored !== undefined && metadata.mirrored !== null) parts.push(`mirrored ${metadata.mirrored}`);
  if (metadata.fov_mode) parts.push(`fov ${metadata.fov_mode}`);
  if (metadata.crop_policy) parts.push(`crop ${metadata.crop_policy}`);
  if (metadata.video_stabilization !== undefined && metadata.video_stabilization !== null) parts.push(`stabilization ${metadata.video_stabilization}`);
  if (metadata.zoom_ratio !== undefined && metadata.zoom_ratio !== null) parts.push(`zoom ${metadata.zoom_ratio}`);
  if (metadata.normalized_source && metadata.raw_source) parts.push(`source ${metadata.normalized_source} (raw ${metadata.raw_source})`);
  return parts.join(" · ") || "orientation/profile metadata not reported";
}

function absoluteWsUrl(path) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  if (/^wss?:\/\//i.test(path || "")) return path;
  return `${protocol}//${window.location.host}${path || ""}`;
}

function canUseWebCodecsH264() {
  return "VideoDecoder" in window && "EncodedVideoChunk" in window;
}

function previewDeepStreamH264WsUrl(preview) {
  const route = previewRoute(preview);
  if (route?.route_kind === "deepstream_osd_h264" && route.ws_url) {
    return absoluteWsUrl(route.ws_url);
  }
  if (route && previewRouteIsLive(preview) && route.route_kind !== "deepstream_osd_h264") return "";
  const direct = preview.deepstream_h264_ws_url || preview.deepstream_h264_live?.h264_ws_url;
  if (direct) return absoluteWsUrl(direct);
  if (preview.has_deepstream_h264_live) {
    return absoluteWsUrl(`/ws/preview/${encodeURIComponent(preview.session_id)}/deepstream-h264`);
  }
  return "";
}

function previewUsesDeepStreamH264(preview) {
  const route = previewRoute(preview);
  if (route && previewRouteIsLive(preview)) return route.route_kind === "deepstream_osd_h264";
  return previewRouteKind(preview) === "deepstream_osd_h264" || Boolean(previewDeepStreamH264WsUrl(preview));
}

function previewUsesStableOverlay(preview) {
  const route = previewRoute(preview);
  return route?.overlay_policy === "stable_perception_overlay"
    || route?.bbox_authority === "perception_graph_stable"
    || previewRouteKind(preview) === "stable_overlay_h264";
}

function previewH264WsUrl(preview, metadata) {
  const route = previewRoute(preview);
  if (route && previewRouteIsLive(preview)) {
    return route.ws_url ? absoluteWsUrl(route.ws_url) : "";
  }
  const deepstream = previewDeepStreamH264WsUrl(preview);
  if (deepstream) return deepstream;
  const direct = preview.h264_ws_url || preview.h264_live?.h264_ws_url;
  if (direct) return absoluteWsUrl(direct);
  const codec = String(preview.codec || metadata.codec || preview.h264_live?.codec || "").toLowerCase();
  const source = String(preview.source || metadata.source || preview.transport || "").toLowerCase();
  if (codec.includes("avc") || codec.includes("h264") || source.includes("rv101_tcp")) {
    return absoluteWsUrl(`/ws/preview/${encodeURIComponent(preview.session_id)}/h264`);
  }
  return "";
}

function previewDisplaySize(preview, metadata) {
  const route = previewRoute(preview);
  let width = Number(route?.width || metadata.preview_width || preview.width || metadata.source_width || 0);
  let height = Number(route?.height || metadata.preview_height || preview.height || metadata.source_height || 0);
  const rotation = Number(metadata.rotation_degrees ?? metadata.sensor_orientation_degrees ?? 0);
  if (!metadata.preview_width && !metadata.preview_height && Math.abs(rotation % 180) === 90) {
    [width, height] = [height, width];
  }
  const sessionId = String(preview.session_id || "");
  const routeKind = previewRouteKind(preview);
  const routeIsLive = previewRouteIsLive(preview);
  const source = String(preview.source || metadata.source || "");
  const isStaleDecodedLiveFrame = !routeIsLive && source === "rv101_live_h264";
  const isLiveReviewArtifact = Boolean(preview.review_preview?.available) && !routeIsLive && source.includes("live");
  const previous = sensorPreviewDisplayState.get(sessionId);
  if (sessionId && routeIsLive && width > 0 && height > 0) {
    sensorPreviewDisplayState.set(sessionId, {
      width,
      height,
      routeKind,
      routeId: String(route?.route_id || ""),
      updatedAt: route?.updated_at || preview.updated_at || "",
    });
  } else if (previous && (isStaleDecodedLiveFrame || isLiveReviewArtifact || routeKind === "none")) {
    width = previous.width;
    height = previous.height;
  }
  if (!width || !height) {
    return { width: 4, height: 3 };
  }
  return { width, height };
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
      <canvas class="preview-video-canvas"></canvas>
      <div class="preview-overlay" aria-hidden="true"></div>
    </div>
    <div class="preview-meta">
      <div class="item-title"></div>
      <div class="item-meta preview-size"></div>
      <div class="item-meta preview-mode"></div>
      <div class="item-meta preview-sensor"></div>
      <div class="item-meta preview-time"></div>
      <a class="item-meta preview-inspect" target="_blank" rel="noreferrer">Inspect frame</a>
    </div>
  `;
  root.append(card);
  return card;
}

function previewFrameUrl(preview) {
  const route = previewRoute(preview);
  if (route && previewRouteIsLive(preview)) return "";
  if (route?.route_kind === "snapshot_image" && route.image_url) {
    const version = encodeURIComponent(`${route.frame_count || preview.frame_count || 0}-${route.updated_at || preview.updated_at || ""}`);
    const joiner = route.image_url.includes("?") ? "&" : "?";
    return `${route.image_url}${joiner}v=${version}`;
  }
  if (!preview.has_frame) return "";
  if (!preview.image_url) return "";
  const version = encodeURIComponent(`${preview.frame_count || 0}-${preview.updated_at || ""}`);
  const joiner = preview.image_url.includes("?") ? "&" : "?";
  return `${preview.image_url}${joiner}v=${version}`;
}

function perceptionForPreview(preview) {
  const sessionId = String(preview?.session_id || "");
  if (!sessionId) return null;
  return state.perception.find((item) => item.session_id === sessionId) || null;
}

function previewOverlayObjects(preview) {
  if (!previewUsesStableOverlay(preview)) return [];
  const perception = perceptionForPreview(preview);
  if (!perception) return [];
  return (perception.objects || [])
    .filter((object) => {
      const attrs = objectAttributes(object);
      const source = String(attrs.perception_source || perception.source || "").toLowerCase();
      return attrs.perception_branch === "yolo26_objects"
        || attrs.detector_family === "yolo26"
        || source.includes("yolo26");
    })
    .filter((object) => Array.isArray(object.bbox) && object.bbox.length >= 4)
    .slice(0, 10)
    .map((object) => ({ object, perception }));
}

function normalizedOverlayBox(object, perception, preview, metadata) {
  const bbox = object.bbox.slice(0, 4).map((value) => Number(value));
  if (!bbox.every(Number.isFinite)) return null;
  const absolute = Math.max(...bbox.map((value) => Math.abs(value))) > 1.5;
  const route = previewRoute(preview);
  const frameWidth = Number(object.frame_width || perception.width || route?.width || metadata.detector_width || metadata.source_width || 0);
  const frameHeight = Number(object.frame_height || perception.height || route?.height || metadata.detector_height || metadata.source_height || 0);
  let [x1, y1, x2, y2] = bbox;
  if (absolute) {
    if (!frameWidth || !frameHeight) return null;
    x1 /= frameWidth;
    x2 /= frameWidth;
    y1 /= frameHeight;
    y2 /= frameHeight;
  }
  const left = Math.max(0, Math.min(1, Math.min(x1, x2)));
  const right = Math.max(0, Math.min(1, Math.max(x1, x2)));
  const top = Math.max(0, Math.min(1, Math.min(y1, y2)));
  const bottom = Math.max(0, Math.min(1, Math.max(y1, y2)));
  if (right <= left || bottom <= top) return null;
  return rotateOverlayBox({ left, top, right, bottom }, metadata);
}

function rotateOverlayBox(box, metadata) {
  const rotation = normalizeRotationDegrees(metadata.rotation_degrees ?? metadata.sensor_orientation_degrees);
  if (rotation === 90) {
    return { left: 1 - box.bottom, top: box.left, right: 1 - box.top, bottom: box.right };
  }
  if (rotation === 180) {
    return { left: 1 - box.right, top: 1 - box.bottom, right: 1 - box.left, bottom: 1 - box.top };
  }
  if (rotation === 270) {
    return { left: box.top, top: 1 - box.right, right: box.bottom, bottom: 1 - box.left };
  }
  return box;
}

function renderPreviewStableOverlay(stage, preview, metadata) {
  const overlay = stage.querySelector(".preview-overlay");
  if (!overlay) return;
  overlay.innerHTML = "";
  overlay.style.display = "none";
  const objects = previewOverlayObjects(preview);
  if (!objects.length) return;
  overlay.style.display = "";
  for (const { object, perception } of objects) {
    const box = normalizedOverlayBox(object, perception, preview, metadata);
    if (!box) continue;
    const marker = document.createElement("div");
    const attrs = objectAttributes(object);
    marker.className = `preview-bbox ${attrs.stable_state === "held" ? "preview-bbox-held" : ""}`;
    marker.style.left = `${box.left * 100}%`;
    marker.style.top = `${box.top * 100}%`;
    marker.style.width = `${Math.max(0.5, (box.right - box.left) * 100)}%`;
    marker.style.height = `${Math.max(0.5, (box.bottom - box.top) * 100)}%`;
    const label = document.createElement("span");
    label.textContent = objectDisplayLabel(object);
    marker.append(label);
    overlay.append(marker);
  }
}

function clearPreviewStableOverlay(stage) {
  const overlay = stage.querySelector(".preview-overlay");
  if (!overlay) return;
  overlay.innerHTML = "";
  overlay.style.display = "none";
}

function splitAnnexBNals(bytes) {
  const starts = [];
  for (let index = 0; index < bytes.length - 3; index += 1) {
    if (bytes[index] === 0 && bytes[index + 1] === 0 && bytes[index + 2] === 1) {
      starts.push({ index, length: 3 });
      index += 2;
    } else if (
      index < bytes.length - 4 &&
      bytes[index] === 0 &&
      bytes[index + 1] === 0 &&
      bytes[index + 2] === 0 &&
      bytes[index + 3] === 1
    ) {
      starts.push({ index, length: 4 });
      index += 3;
    }
  }
  if (!starts.length) return bytes.length ? [bytes] : [];
  const nals = [];
  for (let i = 0; i < starts.length; i += 1) {
    const start = starts[i].index + starts[i].length;
    const end = i + 1 < starts.length ? starts[i + 1].index : bytes.length;
    if (end > start) nals.push(bytes.subarray(start, end));
  }
  return nals;
}

function h264NalType(nal) {
  if (!nal || !nal.length) return 0;
  return nal[0] & 0x1f;
}

function h264NalsToAvcc(nals) {
  const size = nals.reduce((total, nal) => total + 4 + nal.length, 0);
  const output = new Uint8Array(size);
  let offset = 0;
  for (const nal of nals) {
    const length = nal.length;
    output[offset] = (length >>> 24) & 0xff;
    output[offset + 1] = (length >>> 16) & 0xff;
    output[offset + 2] = (length >>> 8) & 0xff;
    output[offset + 3] = length & 0xff;
    output.set(nal, offset + 4);
    offset += 4 + length;
  }
  return output;
}

function avcCodecFromSps(sps) {
  if (!sps || sps.length < 4) return "avc1.42E01E";
  return `avc1.${[sps[1], sps[2], sps[3]].map((value) => value.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
}

function avcDecoderConfigRecord(sps, pps) {
  const output = new Uint8Array(11 + sps.length + pps.length);
  let offset = 0;
  output[offset++] = 1;
  output[offset++] = sps[1] || 0x42;
  output[offset++] = sps[2] || 0;
  output[offset++] = sps[3] || 0x1e;
  output[offset++] = 0xff;
  output[offset++] = 0xe1;
  output[offset++] = (sps.length >>> 8) & 0xff;
  output[offset++] = sps.length & 0xff;
  output.set(sps, offset);
  offset += sps.length;
  output[offset++] = 1;
  output[offset++] = (pps.length >>> 8) & 0xff;
  output[offset++] = pps.length & 0xff;
  output.set(pps, offset);
  return output;
}

function h264ConfigSignature(sps, pps) {
  return `${sps.length}:${Array.from(sps.slice(0, 8)).join(",")}|${pps.length}:${Array.from(pps.slice(0, 8)).join(",")}`;
}

function normalizeRotationDegrees(value) {
  const rotation = Number(value || 0);
  if (!Number.isFinite(rotation)) return 0;
  return ((rotation % 360) + 360) % 360;
}

class H264PreviewPlayer {
  constructor({ sessionId, canvas, url, metadata }) {
    this.sessionId = sessionId;
    this.canvas = canvas;
    this.url = url;
    this.metadata = metadata || {};
    this.ws = null;
    this.decoder = null;
    this.pendingMetadata = null;
    this.sps = null;
    this.pps = null;
    this.configSignature = "";
    this.frameCount = 0;
    this.frameTimes = [];
    this.error = "";
    this.closed = false;
    this.pendingFrame = null;
    this.renderScheduled = false;
    this.droppedFrameCount = 0;
  }

  start() {
    if (!canUseWebCodecsH264()) {
      this.error = "webcodecs_unavailable";
      return;
    }
    this.ws = new WebSocket(this.url);
    this.ws.binaryType = "arraybuffer";
    this.ws.onopen = () => {
      this.canvas.dataset.streamStatus = "live H.264 connected";
    };
    this.ws.onclose = () => {
      if (!this.closed) this.canvas.dataset.streamStatus = "live H.264 closed";
    };
    this.ws.onerror = () => {
      this.error = "h264_websocket_error";
      this.canvas.dataset.streamStatus = "live H.264 error";
    };
    this.ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        this.handleMetadata(event.data);
        return;
      }
      this.handlePayload(event.data);
    };
  }

  update(metadata) {
    this.metadata = { ...this.metadata, ...(metadata || {}) };
  }

  close() {
    this.closed = true;
    if (this.ws) {
      try {
        this.ws.close();
      } catch (_error) {
        // Ignore close races while the dashboard is being re-rendered.
      }
      this.ws = null;
    }
    if (this.decoder) {
      try {
        this.decoder.close();
      } catch (_error) {
        // Decoder may already be closed after a stream error.
      }
      this.decoder = null;
    }
    if (this.pendingFrame) {
      try {
        this.pendingFrame.close();
      } catch (_error) {
        // Frame may already be closed by the browser decoder.
      }
      this.pendingFrame = null;
    }
  }

  handleMetadata(raw) {
    try {
      const payload = JSON.parse(raw);
      if (payload.type === "sample") {
        this.pendingMetadata = payload;
        this.metadata = { ...this.metadata, ...(payload.metadata || {}) };
      } else if (payload.type === "closed") {
        this.canvas.dataset.streamStatus = "live H.264 stopped";
      }
    } catch (_error) {
      this.pendingMetadata = null;
    }
  }

  handlePayload(raw) {
    const sampleMetadata = this.pendingMetadata || {};
    this.pendingMetadata = null;
    const bytes = raw instanceof ArrayBuffer ? new Uint8Array(raw) : new Uint8Array();
    if (!bytes.length) return;
    const nals = splitAnnexBNals(bytes).filter((nal) => nal.length);
    if (!nals.length) return;
    for (const nal of nals) {
      const type = h264NalType(nal);
      if (type === 7) this.sps = new Uint8Array(nal);
      if (type === 8) this.pps = new Uint8Array(nal);
    }
    const hasVcl = nals.some((nal) => {
      const type = h264NalType(nal);
      return type >= 1 && type <= 5;
    });
    if (!hasVcl) return;
    if (!this.ensureDecoder()) return;
    const metadataKeyframe = sampleMetadata.is_keyframe === true || sampleMetadata.isKeyframe === true;
    if (this.decoder.decodeQueueSize > 1 && !metadataKeyframe) {
      this.droppedFrameCount += 1;
      return;
    }
    const chunkBytes = h264NalsToAvcc(nals.filter((nal) => ![7, 8, 9].includes(h264NalType(nal))));
    const hasIdr = nals.some((nal) => h264NalType(nal) === 5);
    const timestamp = Number(sampleMetadata.presentation_time_us || sampleMetadata.presentationTimeUs || performance.now() * 1000);
    try {
      this.decoder.decode(new EncodedVideoChunk({
        type: hasIdr || metadataKeyframe ? "key" : "delta",
        timestamp: Number.isFinite(timestamp) ? Math.round(timestamp) : 0,
        data: chunkBytes,
      }));
    } catch (error) {
      this.error = `decode:${error.name || "error"}`;
      this.canvas.dataset.streamStatus = "live H.264 decode error";
    }
  }

  ensureDecoder() {
    if (!this.sps || !this.pps) {
      this.canvas.dataset.streamStatus = "waiting for H.264 keyframe";
      return false;
    }
    const signature = h264ConfigSignature(this.sps, this.pps);
    if (this.decoder && this.configSignature === signature) return true;
    if (this.decoder) {
      try {
        this.decoder.close();
      } catch (_error) {
        // Reconfigure from a new SPS/PPS pair.
      }
    }
    this.configSignature = signature;
    this.decoder = new VideoDecoder({
      output: (frame) => this.queueFrame(frame),
      error: (error) => {
        this.error = `decoder:${error.name || "error"}`;
        this.canvas.dataset.streamStatus = "live H.264 decoder error";
      },
    });
    this.decoder.configure({
      codec: avcCodecFromSps(this.sps),
      description: avcDecoderConfigRecord(this.sps, this.pps),
      hardwareAcceleration: "prefer-hardware",
      optimizeForLatency: true,
    });
    return true;
  }

  queueFrame(frame) {
    if (this.pendingFrame) {
      try {
        this.pendingFrame.close();
      } catch (_error) {
        // Keep only the freshest frame for latency-first preview.
      }
      this.droppedFrameCount += 1;
    }
    this.pendingFrame = frame;
    if (this.renderScheduled) return;
    this.renderScheduled = true;
    requestAnimationFrame(() => this.drawPendingFrame());
  }

  drawPendingFrame() {
    this.renderScheduled = false;
    const frame = this.pendingFrame;
    this.pendingFrame = null;
    if (!frame || this.closed) {
      if (frame) frame.close();
      return;
    }
    const sourceWidth = frame.displayWidth || frame.codedWidth;
    const sourceHeight = frame.displayHeight || frame.codedHeight;
    const rotation = normalizeRotationDegrees(this.metadata.rotation_degrees ?? this.metadata.sensor_orientation_degrees);
    const rotated = rotation === 90 || rotation === 270;
    const targetWidth = rotated ? sourceHeight : sourceWidth;
    const targetHeight = rotated ? sourceWidth : sourceHeight;
    if (this.canvas.width !== targetWidth) this.canvas.width = targetWidth;
    if (this.canvas.height !== targetHeight) this.canvas.height = targetHeight;
    const ctx = this.canvas.getContext("2d");
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.save();
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    if (rotation === 90) {
      ctx.translate(this.canvas.width, 0);
      ctx.rotate(Math.PI / 2);
    } else if (rotation === 180) {
      ctx.translate(this.canvas.width, this.canvas.height);
      ctx.rotate(Math.PI);
    } else if (rotation === 270) {
      ctx.translate(0, this.canvas.height);
      ctx.rotate(-Math.PI / 2);
    }
    ctx.drawImage(frame, 0, 0, sourceWidth, sourceHeight);
    ctx.restore();
    frame.close();
    this.frameCount += 1;
    const now = performance.now();
    this.frameTimes.push(now);
    this.frameTimes = this.frameTimes.filter((value) => now - value <= 3000);
    const fps = this.frameTimes.length > 1
      ? ((this.frameTimes.length - 1) / Math.max(0.001, (this.frameTimes[this.frameTimes.length - 1] - this.frameTimes[0]) / 1000))
      : 0;
    const fpsText = fps ? ` · ${fps.toFixed(1)} fps` : "";
    const dropText = this.droppedFrameCount ? ` · drop ${this.droppedFrameCount}` : "";
    this.canvas.dataset.streamStatus = `live H.264 ${this.frameCount} frames${fpsText}${dropText}`;
  }
}

function stopH264PreviewPlayer(sessionId) {
  const player = h264PreviewPlayers.get(sessionId);
  if (!player) return;
  player.close();
  h264PreviewPlayers.delete(sessionId);
}

function ensureH264PreviewPlayer(sessionId, canvas, url, metadata) {
  const existing = h264PreviewPlayers.get(sessionId);
  if (existing && existing.url === url && existing.canvas === canvas) {
    existing.update(metadata);
    return existing;
  }
  stopH264PreviewPlayer(sessionId);
  const player = new H264PreviewPlayer({ sessionId, canvas, url, metadata });
  h264PreviewPlayers.set(sessionId, player);
  player.start();
  return player;
}

function updatePreviewStage(card, preview) {
  const stage = card.querySelector(".preview-stage");
  const metadata = previewMetadata(preview);
  const displaySize = previewDisplaySize(preview, metadata);
  if (displaySize.width && displaySize.height) {
    stage.style.aspectRatio = `${displaySize.width} / ${displaySize.height}`;
  }
  const h264Url = previewH264WsUrl(preview, metadata);
  const usesDeepStreamH264 = previewUsesDeepStreamH264(preview);
  const streamUrl = previewFrameUrl(preview);
  const canvas = stage.querySelector("canvas.preview-video-canvas");
  let image = stage.querySelector("img.preview-frame");
  let empty = stage.querySelector(".preview-empty");
  if (h264Url && canUseWebCodecsH264() && canvas) {
    stage.classList.toggle("preview-stage-deepstream", usesDeepStreamH264);
    ensureH264PreviewPlayer(preview.session_id, canvas, h264Url, metadata);
    canvas.style.display = "";
    if (image) image.remove();
    if (empty) empty.remove();
    stage.classList.add("preview-stage-live");
    renderPreviewStableOverlay(stage, preview, metadata);
    return;
  }
  stage.classList.remove("preview-stage-deepstream");
  stopH264PreviewPlayer(preview.session_id);
  if (canvas) canvas.style.display = "none";
  stage.classList.remove("preview-stage-live");
  if (!streamUrl) {
    if (image) image.remove();
    if (!empty) {
      empty = document.createElement("div");
      empty.className = "preview-empty";
      stage.prepend(empty);
    }
    const route = previewRoute(preview);
    empty.textContent = route?.status === "pending"
      ? `Waiting for ${previewRouteLabel(preview)}`
      : "No preview route";
    clearPreviewStableOverlay(stage);
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
  renderPreviewStableOverlay(stage, preview, metadata);
}

function updatePreviewCard(card, preview) {
  updatePreviewStage(card, preview);
  const metadata = previewMetadata(preview);
  card.querySelector(".item-title").textContent = preview.session_id;
  const route = previewRoute(preview);
  const frameCount = route?.frame_count ?? preview.frame_count ?? 0;
  card.querySelector(".preview-size").textContent = `${previewRouteLabel(preview)} · ${previewResolutionLabel(preview, metadata)} · frame ${frameCount}`;
  const mode = card.querySelector(".preview-mode");
  const player = h264PreviewPlayers.get(preview.session_id);
  if (mode) {
    if (previewH264WsUrl(preview, metadata) && canUseWebCodecsH264()) {
      const suffix = preview.review_preview?.available ? " · processed recording available for review" : "";
      mode.textContent = `${previewRouteLabel(preview)} · ${player?.canvas?.dataset?.streamStatus || "starting"}${suffix}`;
    } else if (route?.status === "pending") {
      mode.textContent = `${previewRouteLabel(preview)} pending · no JPEG/MJPEG live fallback`;
    } else if (preview.review_preview?.available) {
      mode.textContent = "processed recording available for review; live Sensor Preview stays on routed H.264";
    } else if (preview.mjpeg_url && preview.has_frame) {
      mode.textContent = "snapshot/evidence JPEG";
    } else if (previewH264WsUrl(preview, metadata) && !canUseWebCodecsH264()) {
      mode.textContent = "Browser lacks WebCodecs for routed H.264";
    } else {
      mode.textContent = "waiting for stream";
    }
  }
  card.querySelector(".preview-sensor").textContent = sensorMetadataLabel(metadata);
  card.querySelector(".preview-time").textContent = preview.updated_at || "waiting";
  const inspect = card.querySelector(".preview-inspect");
  const inspectUrl = !previewRouteIsLive(preview) && preview.image_url
    ? preview.image_url
    : preview.review_preview?.image_url || "";
  if (preview.has_frame && inspectUrl) {
    inspect.href = inspectUrl;
    inspect.style.display = "";
  } else {
    inspect.removeAttribute("href");
    inspect.style.display = "none";
  }
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
        codec: item.video.codec,
        transport: item.video.transport,
        frame_count: item.video.frame_count,
        updated_at: item.video.updated_at,
        metadata: item.video.metadata || {},
        h264_ws_url: item.video.codec === "video/avc" ? `/ws/preview/${encodeURIComponent(item.session_id)}/h264` : "",
        has_frame: false,
      });
    }
  }
  if (!cards.length) {
    for (const sessionId of Array.from(h264PreviewPlayers.keys())) {
      stopH264PreviewPlayer(sessionId);
    }
    root.innerHTML = `
      <article class="item">
        <div class="item-title">No decoded preview</div>
        <div class="item-meta">Sensor Preview appears only while snapshot/live video evidence is available. RV101 H.264 preview decode runs on a bounded worker queue.</div>
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
      stopH264PreviewPlayer(card.dataset.sessionId);
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
    root.innerHTML = '<div class="item"><div class="item-title">No perception snapshot</div><div class="item-meta">YOLO26 or Face ID stream bbox output will appear here.</div></div>';
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
    row.append(renderPerceptionObjects(item.objects || []));
    root.append(row);
  }
}

function bboxText(bbox) {
  if (!Array.isArray(bbox) || bbox.length < 4) return "bbox none";
  const values = bbox.slice(0, 4).map((value) => Number(value));
  if (!values.every(Number.isFinite)) return "bbox invalid";
  const absolute = Math.max(...values.map(Math.abs)) > 1.5;
  const formatted = values.map((value) => absolute ? Math.round(value) : value.toFixed(3));
  return `bbox [${formatted.join(", ")}]`;
}

function renderPerceptionObjects(objects) {
  const list = document.createElement("div");
  list.className = "object-list";
  if (!objects.length) {
    const empty = document.createElement("div");
    empty.className = "object-row muted";
    empty.textContent = "No objects in latest frame";
    list.append(empty);
    return list;
  }
  for (const object of objects.slice(0, 12)) {
    const row = document.createElement("div");
    row.className = "object-row";
    const id = object.track_id || object.object_id || "no-id";
    row.textContent = [
      objectDisplayLabel(object),
      `id ${id}`,
      `zone ${object.zone || "unknown"}`,
      bboxText(object.bbox),
    ].join(" · ");
    list.append(row);
  }
  if (objects.length > 12) {
    const more = document.createElement("div");
    more.className = "object-row muted";
    more.textContent = `+${objects.length - 12} more objects`;
    list.append(more);
  }
  return list;
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
  const worker = state.yolo26Worker;
  const workerChip = worker
    ? worker.status === "running" ? "chip" : worker.status === "blocked" ? "chip warn" : worker.status === "disabled" || worker.status === "not_reported" ? "chip muted" : "chip error"
    : "chip muted";
  item.innerHTML = `
    <div class="item-title">YOLO26 Rokid</div>
    <div class="item-meta"><span class="${chipClass}">${adapter.status}</span> <span class="chip muted">${adapter.mode}</span></div>
    <div class="item-meta">${adapter.message}</div>
    <div class="item-meta">ingest: snapshot ${text(adapter.snapshot_ingest_enabled)} · stream ${text(adapter.stream_ingest_enabled)} · min conf ${text(adapter.min_confidence)}</div>
    <div class="item-meta">engine: ${text(adapter.engine_exists)} · labels: ${text(adapter.labels_exists)}</div>
    <div class="item-meta">isolation: ${adapter.isolation}</div>
    <div class="item-meta">worker: <span class="${workerChip}">${worker?.status || "unknown"}</span> ${worker?.message || "No worker status"}</div>
    <div class="item-meta">worker backend: ${worker?.backend || "none"} · source: ${worker?.source || "none"} · model: ${text(worker?.model_exists)}</div>
    <div class="item-meta">worker realtime: ${worker?.target_skill_mode || "unknown"} · classes ${worker?.target_classes_mode || "unknown"} · max ${text(worker?.max_fps)} fps · recent ${text(worker?.recent_post_fps)} fps</div>
    <div class="item-meta">worker latency: fetch ${text(worker?.recent_fetch_latency_ms)}ms · detector ${text(worker?.recent_detector_latency_ms)}ms · post ${text(worker?.recent_post_latency_ms)}ms</div>
    <div class="item-meta">worker accel: ${text(worker?.detector?.accelerator || worker?.accelerator)} · engine ${text(worker?.engine_exists)} · imgsz ${text(worker?.imgsz)} · perception WS ${state.perceptionStreamStatus}</div>
  `;
  root.append(item);
  const face = state.faceIdentity;
  const faceWorker = state.faceIdentityWorker;
  const faceItem = document.createElement("article");
  faceItem.className = "item";
  const faceChip = face?.status === "ready" ? "chip" : face?.status === "disabled" ? "chip muted" : "chip warn";
  const faceWorkerChip = faceWorker
    ? faceWorker.status === "running" ? "chip" : faceWorker.status === "blocked" ? "chip warn" : faceWorker.status === "disabled" || faceWorker.status === "not_reported" ? "chip muted" : "chip error"
    : "chip muted";
  faceItem.innerHTML = `
    <div class="item-title">Face Identity Local</div>
    <div class="item-meta"><span class="${faceChip}">${face?.status || "unknown"}</span> <span class="chip muted">${face?.mode || "none"}</span></div>
    <div class="item-meta">${face?.message || "No adapter status"}</div>
    <div class="item-meta">ingest: stream ${text(face?.stream_ingest_enabled)} · min conf ${text(face?.min_confidence)}</div>
    <div class="item-meta">models: detector ${text(face?.detector_model_exists)} · recognizer ${text(face?.recognizer_model_exists)}</div>
    <div class="item-meta">worker: <span class="${faceWorkerChip}">${faceWorker?.status || "unknown"}</span> ${faceWorker?.message || "No worker status"}</div>
    <div class="item-meta">worker backend: ${faceWorker?.backend || "none"} · source: ${faceWorker?.source || "none"} · fps ${text(faceWorker?.max_fps)}</div>
  `;
  root.append(faceItem);
}

function renderIdentity() {
  const root = document.querySelector("#identityDb");
  if (!root) return;
  root.innerHTML = "";
  const identity = state.identity;
  const statusClass = identity?.status === "ready" ? "chip" : identity?.status === "ready_empty" ? "chip muted" : "chip warn";
  const header = document.createElement("article");
  header.className = "item";
  header.innerHTML = `
    <div class="item-title">Contact Identity DB</div>
    <div class="item-meta"><span class="${statusClass}">${identity?.status || "unknown"}</span> <span class="chip muted">${identity?.provider || "none"}</span></div>
    <div class="item-meta">contacts: ${identity?.contact_count ?? 0} · samples: ${identity?.sample_count ?? 0} · min conf ${identity?.min_confidence ?? "?"}</div>
    <div class="item-meta">${identity?.message || "No identity status yet."}</div>
  `;
  root.append(header);
  if (!state.identityContacts.length) {
    const empty = document.createElement("article");
    empty.className = "item";
    empty.innerHTML = '<div class="item-title">No contacts enrolled</div><div class="item-meta">Use /api/identity/enroll or a saved crop to add known people.</div>';
    root.append(empty);
    return;
  }
  for (const contact of state.identityContacts.slice(0, 8)) {
    const row = document.createElement("article");
    row.className = "item";
    row.innerHTML = `
      <div class="item-title">${contact.display_name || contact.contact_id}</div>
      <div class="item-meta">${contact.contact_id} · samples ${contact.sample_count || 0}</div>
      <div class="item-meta">aliases: ${(contact.aliases || []).join(", ") || "none"}</div>
    `;
    root.append(row);
  }
}

function renderPeopleRegistry() {
  const root = document.querySelector("#peopleRegistry");
  if (!root) return;
  const registry = state.peopleRegistry;
  const statusClass = registry?.status === "ready" ? "chip" : registry?.status === "ready_empty" ? "chip muted" : "chip warn";
  const immichClass = registry?.immich?.configured ? "chip" : "chip muted";
  const lastSync = registry?.last_sync;
  root.innerHTML = "";

  const card = document.createElement("article");
  card.className = "item people-launcher";
  card.innerHTML = `
    <div>
      <div class="item-title">People Registry Status</div>
      <div class="item-meta"><span class="${statusClass}">${registry?.status || "unknown"}</span> <span class="${immichClass}">Immich ${registry?.immich?.configured ? "configured" : "unconfigured"}</span></div>
      <div class="item-meta">people: ${registry?.people_count ?? 0} · linked Immich: ${registry?.linked_immich_count ?? 0} · named: ${registry?.named_count ?? 0} · identity samples: ${state.identity?.sample_count ?? 0}</div>
      <div class="item-meta">remembered captures: ${registry?.remembered_capture_count ?? 0} · pending face sync: ${registry?.pending_face_sync_count ?? 0}</div>
      <div class="item-meta">images: ${registry?.image_storage || "immich_refs_only"} · last sync: ${lastSync?.status || "none"}</div>
    </div>
    <div class="people-actions">
      <a class="link-button" href="/people.html" target="_blank" rel="noreferrer">Open Face UI</a>
      <button id="peopleSyncButton" type="button">Sync Immich</button>
    </div>
  `;
  root.append(card);
  root.querySelector("#peopleSyncButton")?.addEventListener("click", syncPeopleRegistry);
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
  const [
    health,
    sessions,
    skills,
    realtime,
    voiceOutput,
    media,
    preview,
    rv101Ingest,
    perception,
    yolo26,
    yolo26Worker,
    faceIdentity,
    faceIdentityWorker,
    identity,
    identityContacts,
    peopleRegistry,
    hudScenes,
    debugStt,
    events,
  ] = await Promise.all([
    api("/api/health"),
    api("/api/sessions"),
    api("/api/skills"),
    api("/api/realtime"),
    api("/api/realtime/voice-output"),
    api("/api/media"),
    api("/api/preview"),
    api("/api/rv101/ingest"),
    api("/api/perception"),
    api("/api/adapters/yolo26"),
    api("/api/adapters/yolo26/worker"),
    api("/api/adapters/face-identity"),
    api("/api/adapters/face-identity/worker"),
    api("/api/identity/status"),
    api("/api/identity/contacts"),
    api("/api/people/status"),
    api("/api/hud/latest"),
    api("/api/debug-stt?limit=40"),
    api("/api/events?limit=80"),
  ]);
  state.health = health;
  state.sessions = sessions.sessions;
  state.skills = skills.skills;
  state.realtime = realtime.realtime;
  state.voiceOutput = voiceOutput.voice_output;
  state.media = media.media;
  state.preview = preview.preview;
  state.rv101Ingest = rv101Ingest.ingest;
  state.perception = perception.perception;
  state.yolo26 = yolo26.adapter;
  state.yolo26Worker = yolo26Worker.worker;
  state.faceIdentity = faceIdentity.adapter;
  state.faceIdentityWorker = faceIdentityWorker.worker;
  state.identity = identity.identity;
  state.identityContacts = identityContacts.contacts;
  state.peopleRegistry = peopleRegistry.people_registry;
  state.hudScenes = hudScenes.hud_scenes;
  state.debugStt = debugStt;
  state.events = events.events;
  renderHealth();
  renderSessions();
  renderRealtime();
  renderDebugStt();
  renderPreview();
  renderMedia();
  renderRv101Ingest();
  renderPerception();
  renderYolo26Adapter();
  renderIdentity();
  renderPeopleRegistry();
  if (state.hudScenes.length) {
    renderHud(state.hudScenes[state.hudScenes.length - 1]);
  }
  renderSkills();
  renderEvents();
  } finally {
    refreshInFlight = false;
  }
}

async function syncPeopleRegistry() {
  try {
    const result = await api("/api/people/sync", {
      method: "POST",
      body: JSON.stringify({ push_names: false }),
    });
    await refresh();
    alert(`Immich sync: ${result.sync.status} · remote ${result.sync.remote_count ?? 0}`);
  } catch (error) {
    alert(error.message);
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
      turn_policy: "server_vad",
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

connectPerceptionStream();

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
}, DASHBOARD_REFRESH_MS);
