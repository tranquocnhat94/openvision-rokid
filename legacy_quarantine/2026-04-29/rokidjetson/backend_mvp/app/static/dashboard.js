const HUD_PREVIEW_MAX_TILES = 2;
const HUD_KNOWN_KINDS = new Set([
  "chip",
  "answer_strip",
  "status_strip",
  "gallery",
  "direction_hint",
  "target_marker",
]);
const HUD_ZONE_LIMITS = {
  top_center: 2,
  lower_safe: 2,
  upper_right: 2,
  center_overlay: 1,
};

const state = {
  overview: null,
  liveVoice: null,
  selectedSessionId: null,
  overviewInFlight: false,
  liveVoiceInFlight: false,
  sessionDetailInFlight: false,
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case "\"":
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return char;
    }
  });
}

function displayValue(value) {
  if (value == null || value === "") return "--";
  return String(value);
}

function metricCard(label, value) {
  return `<div class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(displayValue(value))}</strong></div>`;
}

function detailCard(label, value) {
  return `<div class="detail-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(displayValue(value))}</strong></div>`;
}

function formatClock(timestampMs) {
  if (!timestampMs) return "--";
  try {
    return new Date(timestampMs).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "--";
  }
}

function sanitizeForDisplay(value, depth = 0) {
  if (value == null || typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") {
    if (value.length <= 220) return value;
    return `${value.slice(0, 160)}... [${value.length} chars]`;
  }
  if (depth >= 5) return "[depth elided]";
  if (Array.isArray(value)) {
    const items = value.slice(0, 16).map((item) => sanitizeForDisplay(item, depth + 1));
    if (value.length > 16) items.push(`[+${value.length - 16} more items]`);
    return items;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value);
    const result = {};
    entries.slice(0, 40).forEach(([key, item]) => {
      if (typeof item === "string" && /thumbB64|imageB64|jpeg|bgr_bytes/i.test(key)) {
        result[key] = `[${key} ${item.length} chars]`;
        return;
      }
      result[key] = sanitizeForDisplay(item, depth + 1);
    });
    if (entries.length > 40) {
      result.__extraKeys = `[+${entries.length - 40} more keys]`;
    }
    return result;
  }
  return String(value);
}

function jsonBlock(value) {
  return JSON.stringify(sanitizeForDisplay(value ?? {}), null, 2);
}

function humanUptime(seconds) {
  if (seconds == null) return "--";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function formatZone(zone) {
  return String(zone || "unknown").replace(/_/g, " ");
}

function clamp(min, value, max) {
  return Math.min(max, Math.max(min, value));
}

function sessionTags(session) {
  const tags = [];
  tags.push(`<span class="tag ${session.active ? "good" : "warn"}">${session.active ? "active" : "idle"}</span>`);
  tags.push(`<span class="tag ${session.video_connected ? "good" : "warn"}">video ${session.video_connected ? "up" : "down"}</span>`);
  tags.push(`<span class="tag ${session.audio_connected ? "good" : "warn"}">audio ${session.audio_connected ? "up" : "down"}</span>`);
  tags.push(`<span class="tag ${session.control_connected ? "good" : "bad"}">control ${session.control_connected ? "up" : "down"}</span>`);
  if (session.mode && session.mode !== "standby") {
    tags.push(`<span class="tag">shell ${escapeHtml(session.mode)}</span>`);
  }
  if (session.active_target_query) tags.push(`<span class="tag good">target ${escapeHtml(session.active_target_query)}</span>`);
  return tags.join("");
}

function sessionIdOf(session) {
  return session?.session_id || session?.sessionId || null;
}

function pickLiveSession(sessions, preferredSessionId = null) {
  const items = sessions || [];
  const preferred = items.find((session) => sessionIdOf(session) === preferredSessionId) || null;
  const activeWithSpeech = items.find((session) => session.active && session.latestSpeechState?.transcriptHint) || null;
  const anyWithSpeech = items.find((session) => session.latestSpeechState?.transcriptHint) || null;
  if (activeWithSpeech && sessionIdOf(activeWithSpeech) !== preferredSessionId) {
    return activeWithSpeech;
  }
  return preferred || activeWithSpeech || anyWithSpeech || items[0] || null;
}

function sceneComponents(scene) {
  if (!scene || !Array.isArray(scene.components)) return [];
  return scene.components.filter((item) => item && typeof item === "object");
}

function findHudComponent(scene, kind, id = null) {
  return sceneComponents(scene).find((component) => {
    if (component.kind !== kind) return false;
    if (id != null) return component.id === id;
    return true;
  }) || null;
}

function hudGalleryItems(scene) {
  const gallery = findHudComponent(scene, "gallery");
  if (!gallery || !Array.isArray(gallery.items)) return [];
  return gallery.items.filter((item) => item && typeof item === "object");
}

function hudMarkerPosition(marker) {
  const rawX = typeof marker?.normalizedX === "number" ? marker.normalizedX * 100 : 50;
  const rawY = typeof marker?.normalizedY === "number" ? marker.normalizedY * 100 - 6 : 42;
  return {
    x: clamp(12, rawX, 88),
    y: clamp(18, rawY, 74),
  };
}

function renderHudDiagnostics(scene) {
  const container = document.getElementById("hudDiagnostics");
  const components = sceneComponents(scene);
  if (!components.length) {
    container.innerHTML = `<div class="empty">No HUD components in the selected session yet.</div>`;
    return;
  }

  const tags = [];
  const warnings = [];
  const zoneCounts = new Map();
  const unknownKinds = [];

  tags.push({ label: `layout ${scene.layout || "rokid_hud_v1"}`, tone: "good" });
  tags.push({ label: `scene ${scene.sceneId || "--"}`, tone: "" });
  tags.push({ label: `components ${components.length}`, tone: "" });

  components.forEach((component) => {
    const zone = component.zone || "unknown";
    zoneCounts.set(zone, (zoneCounts.get(zone) || 0) + 1);
    if (!HUD_KNOWN_KINDS.has(component.kind)) {
      unknownKinds.push(component.kind || "unknown");
    }
  });

  Array.from(zoneCounts.entries()).forEach(([zone, count]) => {
    tags.push({ label: `${formatZone(zone)} ${count}`, tone: "" });
    const limit = HUD_ZONE_LIMITS[zone];
    if (limit && count > limit) {
      warnings.push(`Zone ${formatZone(zone)} has ${count} components. Current glasses renderer is tuned for <= ${limit}.`);
    }
  });

  const gallery = findHudComponent(scene, "gallery");
  const galleryItems = hudGalleryItems(scene);
  if (gallery) {
    tags.push({
      label: `gallery ${Math.min(galleryItems.length, HUD_PREVIEW_MAX_TILES)}/${galleryItems.length}`,
      tone: galleryItems.length > HUD_PREVIEW_MAX_TILES ? "warn" : "good",
    });
    if (!galleryItems.length) {
      warnings.push("Gallery component exists but has no usable items.");
    }
    if (galleryItems.length > HUD_PREVIEW_MAX_TILES) {
      warnings.push(`Glasses currently render only the first ${HUD_PREVIEW_MAX_TILES} gallery tiles.`);
    }
  }

  const marker = findHudComponent(scene, "target_marker");
  if (marker) {
    const validX = typeof marker.normalizedX === "number" && marker.normalizedX >= 0 && marker.normalizedX <= 1;
    const validY = typeof marker.normalizedY === "number" && marker.normalizedY >= 0 && marker.normalizedY <= 1;
    if (validX && validY) {
      tags.push({
        label: `marker ${Math.round(marker.normalizedX * 100)}%,${Math.round(marker.normalizedY * 100)}%`,
        tone: marker.selected ? "good" : "",
      });
    } else {
      warnings.push("target_marker is present but coordinates are missing or outside 0..1.");
    }
  }

  if (unknownKinds.length) {
    warnings.push(`Dashboard preview does not know these component kinds yet: ${unknownKinds.join(", ")}.`);
  }

  const tagMarkup = `<div class="hud-pill-row">${tags.map((item) => (
    `<span class="hud-pill ${item.tone}">${escapeHtml(item.label)}</span>`
  )).join("")}</div>`;
  const messageMarkup = warnings.length
    ? warnings.map((message) => `<div class="hud-warning">${escapeHtml(message)}</div>`).join("")
    : `<div class="hud-note">Scene stays within the current glasses renderer limits.</div>`;
  container.innerHTML = `${tagMarkup}${messageMarkup}`;
}

function renderHudPreview(scene, speechState) {
  const previewNode = document.getElementById("hudPreview");
  const badgeNode = document.getElementById("hudSceneBadge");
  const components = sceneComponents(scene);

  if (!components.length) {
    badgeNode.textContent = speechState?.transcriptHint ? "voice state" : "idle";
    const caption = speechState?.transcriptHint
      ? `<div><strong>${escapeHtml(speechState.taskLabel || "voice state")}</strong></div><div class="muted">${escapeHtml(speechState.transcriptHint)}</div>`
      : `<div>No HUD scene from Jetson for this session yet.</div>`;
    previewNode.innerHTML = `<div class="hud-preview-empty">${caption}</div>`;
    renderHudDiagnostics(scene);
    return;
  }

  const taskChip = findHudComponent(scene, "chip", "task_chip");
  const micChip = findHudComponent(scene, "chip", "mic_chip");
  const answer = findHudComponent(scene, "answer_strip");
  const status = findHudComponent(scene, "status_strip");
  const direction = findHudComponent(scene, "direction_hint");
  const gallery = findHudComponent(scene, "gallery");
  const galleryItems = hudGalleryItems(scene);
  const visibleGalleryItems = galleryItems.slice(0, HUD_PREVIEW_MAX_TILES);
  const extraGalleryCount = Math.max(0, galleryItems.length - visibleGalleryItems.length);
  const marker = findHudComponent(scene, "target_marker");
  const markerPosition = hudMarkerPosition(marker);

  const chips = [taskChip, micChip]
    .filter(Boolean)
    .map((component) => `<div class="hud-chip ${component.id === "task_chip" ? "active" : "status"}">${escapeHtml(component.text || component.id)}</div>`)
    .join("");

  const galleryMarkup = (gallery || direction || marker)
    ? `
        <div class="hud-layer hud-gallery-card">
          <div class="hud-gallery-title">${escapeHtml(taskChip?.text || "Jetson target")}</div>
          <div class="hud-gallery-direction">${escapeHtml(direction?.text || marker?.direction || "Selected target")}</div>
          ${visibleGalleryItems.length ? `
            <div class="hud-gallery-items">
              ${visibleGalleryItems.map((item) => `
                <div class="hud-gallery-item ${item.selected ? "selected" : ""}">
                  ${item.thumbB64
                    ? `<img src="data:image/jpeg;base64,${item.thumbB64}" alt="${escapeHtml(item.label || "candidate")}">`
                    : `<div class="hud-thumb-placeholder">${escapeHtml((item.label || "?").slice(0, 2))}</div>`}
                  <div class="hud-gallery-label">${escapeHtml(item.label || "candidate")}</div>
                  <div class="hud-gallery-secondary">${escapeHtml(item.secondary || item.trackId || "--")}</div>
                </div>
              `).join("")}
            </div>
          ` : ""}
          ${extraGalleryCount > 0 ? `<div class="hud-gallery-more">+${extraGalleryCount} more hidden on glasses</div>` : ""}
        </div>
      `
    : "";

  const markerMarkup = marker
    ? `
        <div
          class="hud-marker ${marker.selected ? "selected" : ""}"
          style="left:${markerPosition.x}%; top:${markerPosition.y}%;">
          ${escapeHtml(`◎ ${(marker.label || marker.trackId || "Target").slice(0, 18)}`)}
        </div>
      `
    : "";

  const answerMarkup = (answer || status || speechState?.transcriptHint)
    ? `
        <div class="hud-answer-card">
          <div class="hud-answer-text">${escapeHtml(answer?.text || speechState?.transcriptHint || "Jetson HUD ready.")}</div>
          ${status?.text ? `<div class="hud-answer-status">${escapeHtml(status.text)}</div>` : ""}
          ${speechState?.transcriptHint && !answer?.text ? `<div class="hud-answer-caption">voice-state mirror</div>` : ""}
        </div>
      `
    : "";

  previewNode.innerHTML = `
    <div class="hud-preview-shell">
      <div class="hud-preview-meta">
        <span class="hud-pill good">${escapeHtml(scene.sceneId || "scene")}</span>
        <span class="hud-pill">${escapeHtml(scene.layout || "rokid_hud_v1")}</span>
      </div>
      <div class="hud-stage">
        ${chips ? `<div class="hud-layer hud-top-center">${chips}</div>` : ""}
        ${galleryMarkup}
        ${markerMarkup}
        ${answerMarkup}
      </div>
    </div>
  `;
  badgeNode.textContent = scene.layout || "rokid_hud_v1";
  renderHudDiagnostics(scene);
}

function renderVoiceTimeline(data) {
  const sessions = data?.sessions || [];
  const selectedSession = pickLiveSession(sessions, state.selectedSessionId);
  const liveSpeech = selectedSession?.latestSpeechState || null;
  const recentCommands = data?.voice?.recentCommands || [];
  const liveSpeechTranscript = (liveSpeech?.transcriptHint || "").trim();
  const latestCommandTranscript = (recentCommands[0]?.transcript || "").trim();
  const showLiveSpeechCard = Boolean(
    liveSpeechTranscript &&
    liveSpeechTranscript !== latestCommandTranscript
  );
  const liveCaptionCard = showLiveSpeechCard
    ? `
        <div class="log-row">
          <strong>${escapeHtml(`${sessionIdOf(selectedSession) || data?.latestSessionId || "--"} · ${liveSpeech.taskLabel || "voice state"}`)}</strong>
          <div>${escapeHtml(liveSpeechTranscript)}</div>
          <div class="muted">${escapeHtml(`${liveSpeech.stateLabel || "listening"} · live voice state`)}</div>
        </div>
      `
    : "";
  const recentCommandRows = recentCommands.length
    ? recentCommands.map((item) => `
        <div class="log-row">
          <strong>${escapeHtml(`${item.session_id} · ${item.intent}`)}</strong>
          <div>${escapeHtml(item.transcript || "--")}</div>
          <div class="muted">${escapeHtml(item.status_text || item.statusText || item.answer || "--")}</div>
        </div>
      `).join("")
    : `<div class="empty">No voice commands captured yet.</div>`;
  document.getElementById("voiceTimeline").innerHTML = `${liveCaptionCard}${recentCommandRows}`;
}

function renderSkillTrace(trace) {
  const items = Array.isArray(trace) ? trace.slice().reverse() : [];
  document.getElementById("skillTraceBadge").textContent = String(items.length);
  document.getElementById("skillTrace").innerHTML = items.length
    ? items.map((item) => `
        <div class="log-row">
          <strong>${escapeHtml(`${formatClock(item.timestampMs)} · ${item.title || item.kind || "skill"}`)}</strong>
          <div>${escapeHtml(item.summary || "--")}</div>
          <div class="muted">${escapeHtml(item.kind || "--")}</div>
        </div>
      `).join("")
    : `<div class="empty">No skill trace yet for this session.</div>`;
}

function renderOverview(data) {
  state.overview = data;
  const health = data.health || {};
  const voiceBackend = health.voice?.backend || {};
  document.getElementById("healthCards").innerHTML = [
    metricCard("Active sessions", health.activeSessions ?? 0),
    metricCard("Video sessions", health.activeVideoSessions ?? 0),
    metricCard("Perception", health.ai?.mode ?? "--"),
    metricCard("Voice runtime", `${voiceBackend.kind || "--"} / ${voiceBackend.state || "sleeping"}`),
  ].join("");

  const sessions = data.sessions || [];
  document.getElementById("sessionCount").textContent = String(sessions.length);
  document.getElementById("latestSessionBadge").textContent = data.latestSessionId || "idle";

  if (state.selectedSessionId && !sessions.some((session) => sessionIdOf(session) === state.selectedSessionId)) {
    state.selectedSessionId = null;
  }
  if (!state.selectedSessionId && sessions.length) {
    state.selectedSessionId = sessionIdOf(sessions[0]);
  }

  document.getElementById("sessionList").innerHTML = sessions.length
    ? sessions.map((session) => `
        <div class="session-card ${session.session_id === state.selectedSessionId ? "active" : ""}" data-session-id="${escapeHtml(session.session_id)}">
          <small>${escapeHtml(session.device_id || "unknown-device")}</small>
          <strong>${escapeHtml(session.session_id)}</strong>
          <div class="session-tags">${sessionTags(session)}</div>
          <div class="session-tags">
            <span class="tag">uptime ${escapeHtml(humanUptime(session.uptime_sec))}</span>
            <span class="tag">fps ${escapeHtml(Number(session.rx_fps || 0).toFixed(1))}</span>
            <span class="tag">audio ${escapeHtml(session.audio_packets || 0)}</span>
          </div>
        </div>
      `).join("")
    : `<div class="empty">No thin-client sessions yet.</div>`;

  document.querySelectorAll("[data-session-id]").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedSessionId = node.dataset.sessionId;
      renderOverview(state.overview);
      refreshSessionDetail();
    });
  });

  renderVoiceConfig(data.voiceConfig || data.openaiConfig || {});
  renderVoiceTimeline(state.liveVoice || data);
}

function renderVoiceConfig(config) {
  const activeBackendLabel = document.getElementById("activeBackendLabel");
  if (activeBackendLabel) {
    activeBackendLabel.textContent = config.asrBackend || "openai_realtime_skills";
  }
  document.getElementById("asrBackend").value = config.asrBackend || "openai_realtime_skills";
  document.getElementById("autoWakeOnSession").checked = Boolean(config.autoWakeOnSession);
  document.getElementById("backendIdleUnloadMs").value = config.backendIdleUnloadMs || 60000;
  document.getElementById("backendStartupTimeoutMs").value = config.backendStartupTimeoutMs || 15000;
  document.getElementById("localBackendProfile").value = config.localBackendProfile || "";
  document.getElementById("localRequestFormat").value = config.localRequestFormat || "multipart_wav";
  document.getElementById("localTranscribeUrl").value = config.localTranscribeUrl || "";
  document.getElementById("localHealthUrl").value = config.localHealthUrl || "";
  document.getElementById("localStartCommand").value = config.localStartCommand || "";
  document.getElementById("localStopCommand").value = config.localStopCommand || "";
  document.getElementById("localCommandTemplate").value = config.localCommandTemplate || "";
  document.getElementById("localResponseTextPath").value = config.localResponseTextPath || "text";
  document.getElementById("enableOpenAI").checked = Boolean(config.enableOpenAI);
  document.getElementById("allowOpenAITranscriptionFallback").checked = Boolean(config.allowOpenAITranscriptionFallback);
  document.getElementById("allowOpenAIRouterFallback").checked = Boolean(config.allowOpenAIRouterFallback);
  document.getElementById("openaiApiKey").value = config.openaiApiKey || "";
  document.getElementById("openaiBaseUrl").value = config.openaiBaseUrl || "";
  document.getElementById("openaiRealtimeVoiceModel").value = config.openaiRealtimeVoiceModel || "gpt-realtime-1.5";
  document.getElementById("openaiVisionModel").value = config.openaiVisionModel || "gpt-5.4";
  document.getElementById("openaiVisionReasoningEnabled").checked = Boolean(config.openaiVisionReasoningEnabled);
  document.getElementById("openaiRealtimeSkillInstructions").value = config.openaiRealtimeSkillInstructions || "";
  document.getElementById("realtimeSkillTurnDetection").value = config.realtimeSkillTurnDetection || "semantic_vad";
  document.getElementById("realtimeSkillSemanticEagerness").value = config.realtimeSkillSemanticEagerness || "medium";
  document.getElementById("transcriptionModel").value = config.transcriptionModel || "";
  document.getElementById("chatModel").value = config.chatModel || "";
  document.getElementById("languageHint").value = config.languageHint || "";
  document.getElementById("minSegmentMs").value = config.minSegmentMs || 1800;
  document.getElementById("maxSegmentMs").value = config.maxSegmentMs || 4200;
  document.getElementById("idleFlushMs").value = config.idleFlushMs || 900;
  document.getElementById("silenceFloor").value = config.silenceFloor || 320;
  document.getElementById("routerSystemPrompt").value = config.routerSystemPrompt || "";
}

async function refreshOverview() {
  if (state.overviewInFlight) return;
  state.overviewInFlight = true;
  try {
    const data = await fetchJson("/api/admin/overview");
    renderOverview(data);
  } finally {
    state.overviewInFlight = false;
  }
}

async function refreshLiveVoice() {
  if (state.liveVoiceInFlight) return;
  state.liveVoiceInFlight = true;
  try {
    const data = await fetchJson("/api/admin/voice/live");
    state.liveVoice = data;
    renderVoiceTimeline(data);
  } finally {
    state.liveVoiceInFlight = false;
  }
}

async function refreshSessionDetail() {
  if (!state.selectedSessionId || state.sessionDetailInFlight) return;
  state.sessionDetailInFlight = true;
  try {
    const payload = await fetchJson(`/api/admin/sessions/${state.selectedSessionId}`);
    const session = payload.session;
    document.getElementById("selectedSessionId").textContent = state.selectedSessionId;
    document.getElementById("manualMode").value = session.mode || "standby";

    document.getElementById("sessionDetails").innerHTML = [
      detailCard("Capability shell", session.mode || "standby"),
      detailCard("Active query", session.active_target_query || "--"),
      detailCard("Selected target", session.selected_target_summary || session.selectedTarget?.summary || "--"),
      detailCard("CPU app", `${Number(session.latest_device_telemetry?.appCpuPercent || 0).toFixed(1)}%`),
      detailCard("PSS", `${Number(session.latest_device_telemetry?.totalPssMb || 0).toFixed(1)} MB`),
      detailCard("TX", `${Number(session.latest_device_telemetry?.txKbps || 0).toFixed(1)} kbps`),
      detailCard("Battery", `${session.latest_device_telemetry?.batteryPercent ?? "--"}%`),
      detailCard("Transcript", session.latest_voice_command?.transcript || "--"),
      detailCard("Command status", session.latest_voice_command?.statusText || session.latest_voice_command?.answer || "--"),
    ].join("");

    renderSkillTrace(session.latestSkillTrace || []);
    renderHudPreview(session.latestHudScene, session.latestSpeechState);

    document.getElementById("detectionJson").textContent = jsonBlock({
      latestAiResult: session.latestAiResult,
      latestSpeechState: session.latestSpeechState,
      latestHudScene: session.latestHudScene,
      latestSkillTrace: session.latestSkillTrace,
      selectedTarget: session.selectedTarget,
      telemetry: session.latest_device_telemetry,
      encoder: session.latest_encoder_stats,
      audio: session.latest_audio_stats,
    });

    const logTail = payload.logTail || [];
    document.getElementById("sessionLogTail").innerHTML = logTail.length
      ? logTail.slice().reverse().map((item) => `
          <div class="log-row">
            <strong>${escapeHtml(item.event || "log")}</strong>
            <div>${escapeHtml(JSON.stringify(sanitizeForDisplay(item)))}</div>
          </div>
        `).join("")
      : `<div class="empty">No log lines yet.</div>`;
  } finally {
    state.sessionDetailInFlight = false;
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {
    asrBackend: document.getElementById("asrBackend").value,
    autoWakeOnSession: document.getElementById("autoWakeOnSession").checked,
    backendIdleUnloadMs: Number(document.getElementById("backendIdleUnloadMs").value),
    backendStartupTimeoutMs: Number(document.getElementById("backendStartupTimeoutMs").value),
    localBackendProfile: document.getElementById("localBackendProfile").value,
    localRequestFormat: document.getElementById("localRequestFormat").value,
    localTranscribeUrl: document.getElementById("localTranscribeUrl").value,
    localHealthUrl: document.getElementById("localHealthUrl").value,
    localStartCommand: document.getElementById("localStartCommand").value,
    localStopCommand: document.getElementById("localStopCommand").value,
    localCommandTemplate: document.getElementById("localCommandTemplate").value,
    localResponseTextPath: document.getElementById("localResponseTextPath").value,
    enableOpenAI: document.getElementById("enableOpenAI").checked,
    allowOpenAITranscriptionFallback: document.getElementById("allowOpenAITranscriptionFallback").checked,
    allowOpenAIRouterFallback: document.getElementById("allowOpenAIRouterFallback").checked,
    openaiApiKey: document.getElementById("openaiApiKey").value,
    openaiBaseUrl: document.getElementById("openaiBaseUrl").value,
    openaiRealtimeVoiceModel: document.getElementById("openaiRealtimeVoiceModel").value,
    openaiVisionModel: document.getElementById("openaiVisionModel").value,
    openaiVisionReasoningEnabled: document.getElementById("openaiVisionReasoningEnabled").checked,
    openaiRealtimeSkillInstructions: document.getElementById("openaiRealtimeSkillInstructions").value,
    realtimeSkillTurnDetection: document.getElementById("realtimeSkillTurnDetection").value,
    realtimeSkillSemanticEagerness: document.getElementById("realtimeSkillSemanticEagerness").value,
    transcriptionModel: document.getElementById("transcriptionModel").value,
    chatModel: document.getElementById("chatModel").value,
    languageHint: document.getElementById("languageHint").value,
    minSegmentMs: Number(document.getElementById("minSegmentMs").value),
    maxSegmentMs: Number(document.getElementById("maxSegmentMs").value),
    idleFlushMs: Number(document.getElementById("idleFlushMs").value),
    silenceFloor: Number(document.getElementById("silenceFloor").value),
    routerSystemPrompt: document.getElementById("routerSystemPrompt").value,
  };
  const response = await fetchJson("/api/admin/config/voice", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  document.getElementById("settingsStatus").textContent = response.ok ? "Settings saved." : (response.error || "Failed");
  await refreshOverview();
}

async function sendManualCommand() {
  if (!state.selectedSessionId) return;
  const text = document.getElementById("manualCommand").value.trim();
  if (!text) return;
  await fetchJson(`/api/admin/sessions/${state.selectedSessionId}/simulate_command`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  document.getElementById("manualCommand").value = "";
  await refreshOverview();
  await refreshSessionDetail();
}

async function applyManualMode() {
  if (!state.selectedSessionId) return;
  const mode = document.getElementById("manualMode").value;
  await fetchJson(`/api/admin/sessions/${state.selectedSessionId}/mode`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
  await refreshOverview();
  await refreshSessionDetail();
}

document.getElementById("openaiForm").addEventListener("submit", saveSettings);
document.getElementById("sendCommandButton").addEventListener("click", sendManualCommand);
document.getElementById("applyModeButton").addEventListener("click", applyManualMode);

refreshOverview().then(() => Promise.all([refreshSessionDetail(), refreshLiveVoice()]));
setInterval(refreshOverview, 1800);
setInterval(refreshLiveVoice, 250);
setInterval(refreshSessionDetail, 2000);
