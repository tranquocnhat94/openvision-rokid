const ui = {
  preview: document.querySelector("#preview"),
  start: document.querySelector("#startButton"),
  state: document.querySelector("#stateChip"),
  answer: document.querySelector("#hudAnswer"),
  chips: document.querySelector("#hudChips"),
  thumbs: document.querySelector("#hudThumbs"),
  aim: document.querySelector("#hudAim"),
  aimArrow: document.querySelector("#hudAimArrow"),
  zoom: document.querySelector("#hudZoom"),
  voice: document.querySelector("#voiceToggle"),
  voiceStatus: document.querySelector("#voiceStatus"),
};

let sessionId = null;
let peer = null;
let activeAudioMedia = null;
let activeVideoMedia = null;
let videoSender = null;
let activeLiveVideoCommandId = null;
let hudPollTimer = null;
let mediaCommandPollTimer = null;
let lastSceneId = null;
let voiceSocket = null;
let voiceAudioContext = null;
let voicePlayhead = 0;
let voiceStats = {
  deltas: 0,
  dones: 0,
  bytes: 0,
  errors: 0,
  lastLabel: "Voice idle",
};
const handledMediaCommands = new Map();
const mediaCommandTimers = new Map();
const HUD_POLL_MS = 250;
const MEDIA_COMMAND_POLL_MS = 250;
const PREVIEW_POLL_MS = 100;
const PERSON_INFO_SNAPSHOT_SAMPLE_COUNT = 4;
const PERSON_INFO_SNAPSHOT_MIN_NEW_FRAMES = 4;
const PERSON_INFO_SNAPSHOT_MIN_SETTLE_MS = 850;

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

function setState(label) {
  ui.state.textContent = label;
}

function voiceSocketStateName() {
  if (!voiceSocket) return "none";
  const names = ["connecting", "open", "closing", "closed"];
  return names[voiceSocket.readyState] || String(voiceSocket.readyState);
}

function resetVoiceStats() {
  voiceStats = {
    deltas: 0,
    dones: 0,
    bytes: 0,
    errors: 0,
    lastLabel: "Voice starting",
  };
  updateVoiceStatus("Voice starting");
}

function updateVoiceStatus(label) {
  if (label) {
    voiceStats.lastLabel = label;
  }
  if (!ui.voiceStatus) return;
  const audioState = voiceAudioContext?.state || "none";
  const socketState = voiceSocketStateName();
  ui.voiceStatus.textContent = `${voiceStats.lastLabel} · ws ${socketState} · audio ${audioState} · chunks ${voiceStats.deltas}/${voiceStats.dones} · errors ${voiceStats.errors}`;
}

async function primeVoiceAudio() {
  if (!ui.voice?.checked) {
    updateVoiceStatus("Voice off");
    return;
  }
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    throw new Error("Web Audio is not available in this browser.");
  }
  voiceAudioContext = voiceAudioContext || new AudioContextClass();
  if (voiceAudioContext.state === "suspended") {
    await voiceAudioContext.resume();
  }
  updateVoiceStatus("Voice audio ready");
}

function renderHud(scene) {
  ui.answer.textContent = scene.answer_strip || "Ready";
  renderAim(scene.target_hint || null);
  ui.chips.innerHTML = "";
  for (const chip of scene.edge_chips || []) {
    const span = document.createElement("span");
    span.textContent = chip;
    ui.chips.append(span);
  }
  ui.thumbs.innerHTML = "";
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
    ui.thumbs.append(item);
  }
}

function renderAim(targetHint) {
  if (!targetHint || targetHint.mode !== "aim_assist") {
    ui.aim.hidden = true;
    ui.zoom.hidden = true;
    return;
  }
  ui.aim.hidden = false;
  ui.aim.dataset.crosshair = targetHint.crosshair?.style || "tiny_center_reticle";
  const aim = targetHint.aim || {};
  const arrow = aim.arrow || targetHint.status || "search";
  const labels = {
    center: "CENTER",
    left: "LEFT",
    right: "RIGHT",
    up: "UP",
    down: "DOWN",
    up_left: "UP LEFT",
    up_right: "UP RIGHT",
    down_left: "DOWN LEFT",
    down_right: "DOWN RIGHT",
    manual_selection_required: "PICK ID",
    no_candidate: "FIND",
    aim_assist_waiting: "FIND",
    guiding: "FIND",
    search: "FIND",
  };
  const id = targetHint.anonymous_id || targetHint.target_id || "";
  ui.aimArrow.textContent = `${labels[arrow] || labels[targetHint.status] || "TÌM"}${id ? ` · ${id}` : ""}`;
  renderZoom(targetHint.zoom || null);
}

function renderZoom(zoom) {
  ui.zoom.innerHTML = "";
  if (!zoom || !zoom.enabled) {
    ui.zoom.hidden = true;
    return;
  }
  ui.zoom.hidden = false;
  const imageUrl = typeof zoom.image_url === "string" ? zoom.image_url : "";
  if (imageUrl) {
    const image = document.createElement("img");
    image.src = imageUrl;
    image.alt = zoom.label || "zoom";
    image.addEventListener("error", () => {
      const placeholder = document.createElement("div");
      placeholder.className = "hud-zoom-placeholder";
      placeholder.textContent = "zoom";
      image.replaceWith(placeholder);
    }, { once: true });
    ui.zoom.append(image);
  } else {
    const placeholder = document.createElement("div");
    placeholder.className = "hud-zoom-placeholder";
    placeholder.textContent = "zoom";
    ui.zoom.append(placeholder);
  }
  const label = document.createElement("span");
  label.textContent = zoom.label || "zoom";
  ui.zoom.append(label);
}

async function createSession() {
  const result = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({
      client_kind: "iphone_simulator",
      capabilities: {
        video: "webrtc",
        audio: "webrtc",
        hud: "scene_json",
      },
    }),
  });
  sessionId = result.session.session_id;
}

async function startAudio() {
  const media = await navigator.mediaDevices.getUserMedia({
    video: false,
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  activeAudioMedia = media;
  return media;
}

function stopMedia() {
  if (videoSender) {
    videoSender.replaceTrack(null).catch(() => {});
  }
  for (const track of activeAudioMedia?.getTracks() || []) {
    track.stop();
  }
  for (const track of activeVideoMedia?.getTracks() || []) {
    track.stop();
  }
  activeAudioMedia = null;
  activeVideoMedia = null;
  ui.preview.srcObject = null;
}

async function connectWebRtc(media) {
  peer = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  });
  peer.onconnectionstatechange = () => setState(`WebRTC ${peer.connectionState}`);
  peer.createDataChannel("openvision-control");
  for (const track of media.getTracks()) {
    peer.addTrack(track, media);
  }
  videoSender = peer.addTransceiver("video", { direction: "sendonly" }).sender;
  const offer = await peer.createOffer();
  await peer.setLocalDescription(offer);
  const answer = await api("/api/simulator/webrtc/offer", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      type: peer.localDescription.type,
      sdp: peer.localDescription.sdp,
    }),
  });
  await peer.setRemoteDescription(answer);
}

async function startRealtime() {
  await api(`/api/realtime/${sessionId}/start`, {
    method: "POST",
    body: JSON.stringify({
      turn_policy: "server_vad",
      voice_output: Boolean(ui.voice?.checked),
    }),
  });
}

async function connectVoiceOutput() {
  if (!ui.voice?.checked || !sessionId) {
    updateVoiceStatus("Voice off");
    return;
  }
  await primeVoiceAudio();
  voicePlayhead = Math.max(voiceAudioContext.currentTime, voicePlayhead);
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  voiceSocket = new WebSocket(`${protocol}//${window.location.host}/ws/realtime/${encodeURIComponent(sessionId)}/audio`);
  updateVoiceStatus("Voice socket connecting");
  voiceSocket.addEventListener("open", () => updateVoiceStatus("Voice socket open"));
  voiceSocket.addEventListener("close", () => updateVoiceStatus("Voice socket closed"));
  voiceSocket.addEventListener("error", () => {
    voiceStats.errors += 1;
    updateVoiceStatus("Voice socket error");
  });
  voiceSocket.addEventListener("message", (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_error) {
      voiceStats.errors += 1;
      updateVoiceStatus("Voice message parse error");
      return;
    }
    handleVoiceOutputMessage(message).catch((error) => {
      voiceStats.errors += 1;
      updateVoiceStatus(error?.message || "Voice playback error");
    });
  });
}

function disconnectVoiceOutput() {
  if (voiceSocket) {
    voiceSocket.close();
    voiceSocket = null;
  }
  voicePlayhead = 0;
  updateVoiceStatus("Voice disconnected");
}

async function handleVoiceOutputMessage(message) {
  if (message.type === "voice_config") {
    updateVoiceStatus("Voice configured");
    return;
  }
  if (message.type === "audio_done") {
    voiceStats.dones += 1;
    updateVoiceStatus("Voice audio done");
    return;
  }
  if (message.type !== "audio_delta" || typeof message.audio_base64 !== "string") {
    return;
  }
  voiceStats.deltas += 1;
  voiceStats.bytes += Math.floor((message.audio_base64.length * 3) / 4);
  if (voiceAudioContext?.state === "suspended") {
    await voiceAudioContext.resume();
  }
  if (!playPcm16(message.audio_base64, Number(message.sample_rate) || 24000)) {
    voiceStats.errors += 1;
  }
  updateVoiceStatus("Voice audio chunk");
}

function playPcm16(audioBase64, sampleRate) {
  if (!voiceAudioContext) return false;
  const binary = window.atob(audioBase64);
  const sampleCount = Math.floor(binary.length / 2);
  if (sampleCount <= 0) return false;
  const audioBuffer = voiceAudioContext.createBuffer(1, sampleCount, sampleRate);
  const samples = audioBuffer.getChannelData(0);
  for (let index = 0; index < sampleCount; index += 1) {
    const lo = binary.charCodeAt(index * 2);
    const hi = binary.charCodeAt(index * 2 + 1);
    let value = (hi << 8) | lo;
    if (value >= 0x8000) value -= 0x10000;
    samples[index] = Math.max(-1, Math.min(1, value / 32768));
  }
  const source = voiceAudioContext.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(voiceAudioContext.destination);
  const startAt = Math.max(voiceAudioContext.currentTime + 0.02, voicePlayhead);
  source.start(startAt);
  voicePlayhead = startAt + audioBuffer.duration;
  return true;
}

async function loadHud() {
  const result = await api(`/api/hud/sample?session_id=${encodeURIComponent(sessionId)}`);
  renderHud(result.hud_scene);
}

async function pollHud() {
  if (!sessionId) return;
  try {
    const result = await api(`/api/hud/${encodeURIComponent(sessionId)}/latest`);
    const scene = result.hud_scene;
    if (scene.scene_id !== lastSceneId) {
      lastSceneId = scene.scene_id;
      renderHud(scene);
    }
  } catch (_error) {
  }
}

function startHudPolling() {
  if (hudPollTimer) {
    window.clearInterval(hudPollTimer);
  }
  pollHud();
  hudPollTimer = window.setInterval(pollHud, HUD_POLL_MS);
}

function stopMediaCommandPolling() {
  if (mediaCommandPollTimer) {
    window.clearInterval(mediaCommandPollTimer);
    mediaCommandPollTimer = null;
  }
  for (const timer of mediaCommandTimers.values()) {
    window.clearTimeout(timer);
  }
  mediaCommandTimers.clear();
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function requestedVideoBudget(command) {
  const resolution = command?.resolution || {};
  const width = Number(resolution.width) || 1280;
  const height = Number(resolution.height) || 720;
  const fps = Number(command?.fps) || 8;
  return { width, height, fps };
}

function safeTrackSettings(track) {
  if (!track || typeof track.getSettings !== "function") return {};
  try {
    return track.getSettings() || {};
  } catch (_error) {
    return {};
  }
}

function safeTrackConstraints(track) {
  if (!track || typeof track.getConstraints !== "function") return {};
  try {
    return track.getConstraints() || {};
  } catch (_error) {
    return {};
  }
}

function clientVideoPayload(command = null) {
  const tracks = activeVideoMedia
    ? activeVideoMedia.getVideoTracks().map((track) => ({
      label: track.label,
      ready_state: track.readyState,
      enabled: track.enabled,
      settings: safeTrackSettings(track),
      constraints: safeTrackConstraints(track),
    }))
    : [];
  return {
    requested: command ? requestedVideoBudget(command) : null,
    preview_width: ui.preview.videoWidth || null,
    preview_height: ui.preview.videoHeight || null,
    video_track_count: tracks.length,
    video_tracks: tracks,
  };
}

function videoConstraintsFor(command, options = {}) {
  const budget = requestedVideoBudget(command);
  const facingMode = options.exactFacingMode
    ? { exact: "environment" }
    : { ideal: "environment" };
  return {
    facingMode,
    width: { ideal: budget.width, min: Math.min(640, budget.width) },
    height: { ideal: budget.height, min: Math.min(480, budget.height) },
    frameRate: { ideal: budget.fps, max: Math.max(1, budget.fps) },
  };
}

function trackIsUserFacing(track) {
  const settings = safeTrackSettings(track);
  const facingMode = String(settings.facingMode || "").toLowerCase();
  return facingMode === "user";
}

async function openEnvironmentCamera(command) {
  try {
    return await navigator.mediaDevices.getUserMedia({
      video: videoConstraintsFor(command, { exactFacingMode: true }),
      audio: false,
    });
  } catch (error) {
    console.warn("Exact environment camera unavailable, falling back to ideal environment", error);
    return navigator.mediaDevices.getUserMedia({
      video: videoConstraintsFor(command),
      audio: false,
    });
  }
}

async function applyVideoSenderBudget(command, track) {
  if (!videoSender || typeof videoSender.getParameters !== "function" || typeof videoSender.setParameters !== "function") {
    return;
  }
  const budget = requestedVideoBudget(command);
  const params = videoSender.getParameters() || {};
  params.degradationPreference = "maintain-resolution";
  const maxBitrate = Math.max(1500000, Math.min(5000000, budget.width * budget.height * budget.fps));
  const encodings = Array.isArray(params.encodings) && params.encodings.length ? params.encodings : [{}];
  params.encodings = encodings.map((encoding) => ({
    ...encoding,
    active: true,
    maxBitrate,
    maxFramerate: budget.fps,
    scaleResolutionDownBy: 1,
  }));
  try {
    await videoSender.setParameters(params);
  } catch (error) {
    console.warn("Could not apply video sender budget", error);
  }
  if (track && typeof track.applyConstraints === "function") {
    try {
      await track.applyConstraints(videoConstraintsFor(command));
    } catch (error) {
      console.warn("Could not apply video track constraints", error);
    }
  }
}

async function ensureCameraActive(command) {
  const existingTrack = activeVideoMedia?.getVideoTracks()[0];
  if (existingTrack && existingTrack.readyState === "live") {
    if (trackIsUserFacing(existingTrack)) {
      await stopCamera();
    } else {
      if (videoSender && videoSender.track !== existingTrack) {
        await videoSender.replaceTrack(existingTrack);
      }
      await applyVideoSenderBudget(command, existingTrack);
      return;
    }
  }
  const media = await openEnvironmentCamera(command);
  const track = media.getVideoTracks()[0];
  if (!track) {
    throw new Error("Camera did not provide a video track.");
  }
  activeVideoMedia = media;
  ui.preview.srcObject = media;
  if (videoSender) {
    await videoSender.replaceTrack(track);
  } else if (peer) {
    videoSender = peer.addTrack(track, media);
  }
  await applyVideoSenderBudget(command, track);
}

async function stopCamera() {
  if (videoSender) {
    try {
      await videoSender.replaceTrack(null);
    } catch (_error) {
    }
  }
  for (const track of activeVideoMedia?.getTracks() || []) {
    track.stop();
  }
  activeVideoMedia = null;
  ui.preview.srcObject = null;
}

async function previewStatusForSession() {
  const result = await api("/api/preview");
  return (result.preview || []).find((item) => item.session_id === sessionId) || null;
}

function snapshotPreviewWaitOptions(command) {
  if (String(command?.skill_id || "") !== "person_info") {
    return { minNewFrames: 1, minSettleMs: 0, requireSettle: false };
  }
  const qualityGate = command?.params?.quality_gate || {};
  const sampleCount = Math.max(2, Number(qualityGate.sample_count) || PERSON_INFO_SNAPSHOT_SAMPLE_COUNT);
  return {
    sampleCount,
    minNewFrames: Math.max(2, Number(qualityGate.min_new_frames) || PERSON_INFO_SNAPSHOT_MIN_NEW_FRAMES),
    minSettleMs: Math.max(0, Number(qualityGate.settle_ms) || PERSON_INFO_SNAPSHOT_MIN_SETTLE_MS),
    requireSettle: true,
    qualityGateMode: String(qualityGate.mode || "best_of_burst"),
  };
}

async function waitForPreviewFrame(previousFrameCount, timeoutMs, options = {}) {
  const deadline = Date.now() + Math.max(500, timeoutMs || 1500);
  let latest = null;
  let fallback = null;
  let firstUsableAt = null;
  const minNewFrames = Math.max(1, Number(options.minNewFrames) || 1);
  const minSettleMs = Math.max(0, Number(options.minSettleMs) || 0);
  const requireSettle = Boolean(options.requireSettle);
  while (Date.now() < deadline) {
    latest = await previewStatusForSession();
    const frameCount = Number(latest?.frame_count || 0);
    const newFrameCount = previousFrameCount <= 0 ? frameCount : Math.max(0, frameCount - previousFrameCount);
    if (
      latest?.has_frame
      && (previousFrameCount <= 0 || frameCount > previousFrameCount)
    ) {
      fallback = latest;
      firstUsableAt = firstUsableAt || Date.now();
      const hasEnoughFrames = newFrameCount >= minNewFrames;
      const hasSettled = Date.now() - firstUsableAt >= minSettleMs;
      if (requireSettle ? (hasEnoughFrames && hasSettled) : (hasEnoughFrames || hasSettled)) {
        return latest;
      }
    }
    await sleep(PREVIEW_POLL_MS);
  }
  return fallback;
}

function commandAgeMs(command) {
  const createdAt = Date.parse(command?.created_at || "");
  if (!Number.isFinite(createdAt)) return null;
  return Math.max(0, Math.round(Date.now() - createdAt));
}

function captureTimingPayload(command, startedAt, cameraReadyAt, finishedAt) {
  return {
    total_ms: Math.max(0, Math.round(finishedAt - startedAt)),
    camera_open_ms: cameraReadyAt ? Math.max(0, Math.round(cameraReadyAt - startedAt)) : null,
    preview_wait_ms: cameraReadyAt ? Math.max(0, Math.round(finishedAt - cameraReadyAt)) : null,
    server_command_age_ms: commandAgeMs(command),
    media_command_poll_ms: MEDIA_COMMAND_POLL_MS,
    preview_poll_ms: PREVIEW_POLL_MS,
  };
}

async function reportMediaCommand(command, status, payload = {}) {
  return api(`/api/media/commands/${encodeURIComponent(command.command_id)}/events`, {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      status,
      payload,
    }),
  });
}

function mediaCommandWasHandled(command, phase) {
  return handledMediaCommands.get(command.command_id) === phase;
}

function markMediaCommandHandled(command, phase) {
  handledMediaCommands.set(command.command_id, phase);
}

async function handleSnapshotCommand(command) {
  if (handledMediaCommands.has(command.command_id)) return;
  markMediaCommandHandled(command, "snapshot_running");
  const startedAt = performance.now();
  let cameraReadyAt = null;
  const previous = await previewStatusForSession();
  try {
    setState("Camera snapshot");
    await ensureCameraActive(command);
    cameraReadyAt = performance.now();
    const waitOptions = snapshotPreviewWaitOptions(command);
    const preview = await waitForPreviewFrame(
      Number(previous?.frame_count || 0),
      Number(command.timeout_ms) || 1500,
      waitOptions,
    );
    if (!preview) {
      await reportMediaCommand(command, "timeout", {
        adapter_status: "simulator_snapshot_timeout",
        client_video: clientVideoPayload(command),
        client_timing_ms: captureTimingPayload(command, startedAt, cameraReadyAt, performance.now()),
      });
      markMediaCommandHandled(command, "snapshot_timeout");
      setState("Snapshot timeout");
      return;
    }
    await reportMediaCommand(command, "ok", {
      adapter_status: "simulator_snapshot_ready",
      preview,
      client_video: clientVideoPayload(command),
      client_timing_ms: captureTimingPayload(command, startedAt, cameraReadyAt, performance.now()),
      snapshot_wait_policy: waitOptions,
    });
    markMediaCommandHandled(command, "snapshot_ok");
    setState("Snapshot ready");
  } catch (error) {
    await reportMediaCommand(command, "error", {
      adapter_status: "simulator_camera_error",
      error: error.message,
      client_timing_ms: captureTimingPayload(command, startedAt, cameraReadyAt, performance.now()),
    });
    markMediaCommandHandled(command, "snapshot_error");
    setState("Camera error");
  } finally {
    if (!activeLiveVideoCommandId) {
      await stopCamera();
    }
  }
}

async function handleBurstClipCommand(command) {
  if (mediaCommandTimers.has(command.command_id) || handledMediaCommands.has(command.command_id)) return;
  markMediaCommandHandled(command, "burst_running");
  const durationMs = Math.min(Number(command.timeout_ms) || 3000, 5000);
  const timer = window.setTimeout(() => {
    mediaCommandTimers.delete(command.command_id);
  }, durationMs);
  mediaCommandTimers.set(command.command_id, timer);
  const previous = await previewStatusForSession();
  try {
    setState("Burst capture");
    await ensureCameraActive(command);
    await sleep(durationMs);
    const preview = await waitForPreviewFrame(Number(previous?.frame_count || 0), 500);
    await reportMediaCommand(command, "ok", {
      adapter_status: "simulator_burst_ready",
      capture_duration_ms: durationMs,
      sampled_frame_count: Math.max(1, Math.round((Number(command.fps) || 5) * durationMs / 1000)),
      preview,
      client_video: clientVideoPayload(command),
    });
    markMediaCommandHandled(command, "burst_ok");
    setState("Burst ready");
  } catch (error) {
    await reportMediaCommand(command, "error", {
      adapter_status: "simulator_camera_error",
      error: error.message,
    });
    markMediaCommandHandled(command, "burst_error");
    setState("Burst error");
  } finally {
    mediaCommandTimers.delete(command.command_id);
    if (!activeLiveVideoCommandId) {
      await stopCamera();
    }
  }
}

async function handleLiveVideoCommand(command) {
  if (handledMediaCommands.has(command.command_id)) return;
  markMediaCommandHandled(command, "live_starting");
  const previous = await previewStatusForSession();
  try {
    setState("Live video");
    await ensureCameraActive(command);
    const preview = await waitForPreviewFrame(Number(previous?.frame_count || 0), 1500);
    activeLiveVideoCommandId = command.command_id;
    await reportMediaCommand(command, "running", {
      adapter_status: "simulator_live_video_running",
      active_live_video: true,
      preview,
      client_video: clientVideoPayload(command),
    });
    markMediaCommandHandled(command, "live_running");
  } catch (error) {
    await reportMediaCommand(command, "error", {
      adapter_status: "simulator_camera_error",
      error: error.message,
    });
    markMediaCommandHandled(command, "live_error");
    setState("Live error");
  }
}

async function handleCameraOffCommand(command, status = "ok") {
  if (mediaCommandWasHandled(command, "camera_off")) return;
  await stopCamera();
  activeLiveVideoCommandId = null;
  if (status === "ok" || status === "cancelled") {
    await reportMediaCommand(command, "ok", {
      adapter_status: "simulator_camera_off",
      active_live_video: false,
      client_video: clientVideoPayload(command),
    });
  }
  markMediaCommandHandled(command, "camera_off");
  setState("Camera off");
}

async function handleExpiredLiveVideoCommand(command, status) {
  if (activeLiveVideoCommandId !== command.command_id || mediaCommandWasHandled(command, `live_${status}`)) return;
  await stopCamera();
  activeLiveVideoCommandId = null;
  await reportMediaCommand(command, status, {
    adapter_status: "simulator_live_video_stopped",
    active_live_video: false,
    client_video: clientVideoPayload(command),
  });
  markMediaCommandHandled(command, `live_${status}`);
  setState("Camera off");
}

async function handleMediaCommand(item) {
  const command = item?.command;
  const event = item?.event || {};
  if (!command || command.session_id !== sessionId) return;
  const status = event.status || "";
  const action = command.params?.action || "capture";
  if (command.mode === "none" && status === "ok") {
    await handleCameraOffCommand(command);
    return;
  }
  if (command.mode === "snapshot" && status === "queued") {
    await handleSnapshotCommand(command);
    return;
  }
  if (command.mode === "burst_clip" && status === "running") {
    await handleBurstClipCommand(command);
    return;
  }
  if (command.mode === "live_video" && action === "stop" && ["ok", "cancelled"].includes(status)) {
    await handleCameraOffCommand(command, status);
    return;
  }
  if (command.mode === "live_video" && action !== "stop" && status === "running") {
    await handleLiveVideoCommand(command);
    return;
  }
  if (command.mode === "live_video" && action !== "stop" && ["timeout", "cancelled", "error"].includes(status)) {
    await handleExpiredLiveVideoCommand(command, status);
  }
}

async function pollMediaCommands() {
  if (!sessionId) return;
  try {
    const result = await api("/api/media/commands");
    for (const item of result.media_commands?.commands || []) {
      await handleMediaCommand(item);
    }
  } catch (_error) {
  }
}

function startMediaCommandPolling() {
  stopMediaCommandPolling();
  pollMediaCommands();
  mediaCommandPollTimer = window.setInterval(pollMediaCommands, MEDIA_COMMAND_POLL_MS);
}

ui.start.addEventListener("click", async () => {
  try {
    ui.start.hidden = true;
    resetVoiceStats();
    setState("Starting");
    if (!window.isSecureContext) {
      setState("HTTPS required");
      ui.start.hidden = false;
      return;
    }
    await primeVoiceAudio();
    setState("Requesting microphone");
    const audioMedia = await startAudio();
    setState("Creating session");
    await createSession();
    setState("Starting realtime");
    await startRealtime();
    await connectVoiceOutput();
    setState("Connecting media");
    await connectWebRtc(audioMedia);
    startMediaCommandPolling();
    await loadHud();
    startHudPolling();
    setState("Connected");
  } catch (error) {
    stopMediaCommandPolling();
    disconnectVoiceOutput();
    stopMedia();
    setState("Error");
    ui.answer.textContent = error.message;
    ui.start.hidden = false;
  }
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden || !voiceAudioContext || voiceAudioContext.state !== "suspended") return;
  voiceAudioContext.resume()
    .then(() => updateVoiceStatus("Voice audio resumed"))
    .catch(() => {
      voiceStats.errors += 1;
      updateVoiceStatus("Voice resume blocked");
    });
});
