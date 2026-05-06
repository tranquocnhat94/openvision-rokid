const SIMULATOR_ASSET_VERSION = "20260424-browser-harness15";
const GLASSES_LIKE_DEFAULT_PRESET = "720x960";
const GLASSES_LIKE_DEFAULT_FRAME_RATE = 15;

const state = {
  ws: null,
  sessionId: "",
  connected: false,
  running: false,
  starting: false,
  secureContext: window.isSecureContext,
  mediaStream: null,
  publishStream: null,
  publishCleanup: null,
  publishMetricsTimer: null,
  pc: null,
  webrtcStatsTimers: [],
  webrtcConnected: false,
  latestHudScene: null,
  latestSpeechState: null,
  latestVisionResult: null,
  latestNodeTelemetry: null,
  detailTimer: null,
  latestSkillTrace: [],
  selectedTarget: null,
  recommendedSecureUrl: "",
};

const dom = {
  connectionBadge: document.getElementById("connectionBadge"),
  secureHint: document.getElementById("secureHint"),
  captureStatus: document.getElementById("captureStatus"),
  startButton: document.getElementById("startButton"),
  stopButton: document.getElementById("stopButton"),
  sendCommandButton: document.getElementById("sendCommandButton"),
  applyModeButton: document.getElementById("applyModeButton"),
  manualCommand: document.getElementById("manualCommand"),
  modeSelect: document.getElementById("modeSelect"),
  cameraFacing: document.getElementById("cameraFacing"),
  videoPreset: document.getElementById("videoPreset"),
  frameRate: document.getElementById("frameRate"),
  enableVideo: document.getElementById("enableVideo"),
  enableAudio: document.getElementById("enableAudio"),
  cameraPreview: document.getElementById("cameraPreview"),
  sessionLabel: document.getElementById("sessionLabel"),
  speechLabel: document.getElementById("speechLabel"),
  speechHint: document.getElementById("speechHint"),
  modeLabel: document.getElementById("modeLabel"),
  visionLabel: document.getElementById("visionLabel"),
  visionHint: document.getElementById("visionHint"),
  fpsLabel: document.getElementById("fpsLabel"),
  hudTopCenter: document.getElementById("hudTopCenter"),
  hudGallery: document.getElementById("hudGallery"),
  hudMarker: document.getElementById("hudMarker"),
  hudLowerStrip: document.getElementById("hudLowerStrip"),
  selectedTarget: document.getElementById("selectedTarget"),
  skillTrace: document.getElementById("skillTrace"),
  traceBadge: document.getElementById("traceBadge"),
};

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

function wsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/ws/browser`;
}

function webrtcOfferUrl() {
  return `${window.location.origin}/api/browser/webrtc/offer`;
}

function browserTraceUrl() {
  return `${window.location.origin}/api/browser/trace`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload?.detail?.reason || payload?.detail?.error || payload?.error || response.statusText);
    error.name = payload?.detail?.error || payload?.error || "http_error";
    error.payload = payload;
    throw error;
  }
  return payload;
}

function updateConnectionBadge(label, tone = "") {
  dom.connectionBadge.textContent = label;
  dom.connectionBadge.className = `sim-pill ${tone}`.trim();
}

function setCaptureStatus(message) {
  dom.captureStatus.textContent = message;
}

function applyGlassesLikeDefaults() {
  if (dom.videoPreset) {
    dom.videoPreset.value = GLASSES_LIKE_DEFAULT_PRESET;
  }
  if (dom.frameRate) {
    dom.frameRate.value = String(GLASSES_LIKE_DEFAULT_FRAME_RATE);
  }
}

function normalizeFrameRate(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return GLASSES_LIKE_DEFAULT_FRAME_RATE;
  }
  return Math.max(1, Math.round(parsed));
}

function safeTrackSettings(track) {
  if (!track || typeof track.getSettings !== "function") {
    return {};
  }
  try {
    return track.getSettings() || {};
  } catch (error) {
    return { error: error?.name || "settings_unavailable" };
  }
}

function mediaTrackSummary(stream) {
  return (stream?.getTracks?.() || []).map((track) => ({
    kind: track.kind,
    readyState: track.readyState,
    enabled: track.enabled,
    settings: safeTrackSettings(track),
  }));
}

function updateSecureHint() {
  const secureTarget = state.recommendedSecureUrl ? ` Open ${state.recommendedSecureUrl} on iPhone.` : " Open the browser harness over HTTPS.";
  if (!navigator.mediaDevices?.getUserMedia) {
    dom.secureHint.textContent = `Camera/mic APIs are unavailable here.${secureTarget}`;
    return;
  }
  if (!state.secureContext) {
    dom.secureHint.textContent = `This origin is not secure. iPhone Safari blocks getUserMedia unless the page is served over HTTPS.${secureTarget}`;
    return;
  }
  dom.secureHint.textContent = "Secure context ready. Tap Start to grant camera + mic, then Safari will publish them to Jetson over WebRTC while HUD/control stay on this browser harness websocket.";
}

async function loadSecureRecommendation() {
  try {
    const health = await fetchJson("/health");
    const controlHost = String(health?.control?.host || "").trim();
    const controlPort = Number(health?.control?.port || 0);
    if (controlHost) {
      const implicitTls = controlHost.endsWith(".ts.net") || controlPort === 443 || controlPort === 0;
      state.recommendedSecureUrl = implicitTls
        ? `https://${controlHost}/simulator`
        : `https://${controlHost}:${controlPort}/simulator`;
    } else {
      const payload = await fetchJson("/");
      const simulatorPage = String(payload?.simulator?.page || "");
      if (simulatorPage.startsWith("https://")) {
        state.recommendedSecureUrl = simulatorPage;
      }
    }
  } catch (error) {
    console.warn("secure recommendation lookup failed", error);
  }
  updateSecureHint();
}

function waitForVideoMetadata(videoElement, timeoutMs = 1200) {
  if (videoElement.readyState >= HTMLMediaElement.HAVE_METADATA) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      videoElement.removeEventListener("loadedmetadata", finish);
      resolve();
    };
    videoElement.addEventListener("loadedmetadata", finish, { once: true });
    window.setTimeout(finish, timeoutMs);
  });
}

function waitForIceGatheringComplete(pc, timeoutMs = 5000) {
  if (!pc || pc.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      pc.removeEventListener("icegatheringstatechange", onStateChange);
      resolve();
    };
    const onStateChange = () => {
      if (pc.iceGatheringState === "complete") {
        finish();
      }
    };
    pc.addEventListener("icegatheringstatechange", onStateChange);
    window.setTimeout(finish, timeoutMs);
  });
}

function buildMediaConstraints(wantsVideo, wantsAudio, targetWidth, targetHeight, frameRate) {
  const aspectRatio = targetWidth > 0 && targetHeight > 0 ? targetWidth / targetHeight : 0.75;
  return {
    video: wantsVideo
      ? {
          facingMode: { ideal: dom.cameraFacing.value },
          width: { ideal: targetWidth },
          height: { ideal: targetHeight },
          aspectRatio: { ideal: aspectRatio },
          frameRate: { ideal: Math.max(2, frameRate), max: Math.max(4, frameRate + 2) },
        }
      : false,
    audio: wantsAudio
      ? {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        }
      : false,
  };
}

async function createGlassesLikePublishStream(rawStream, targetWidth, targetHeight, frameRate) {
  const rawVideoTrack = rawStream?.getVideoTracks?.()[0] || null;
  const requestedFrameRate = normalizeFrameRate(frameRate);
  if (!rawVideoTrack || typeof document.createElement("canvas").captureStream !== "function") {
    return {
      stream: rawStream,
      transformed: false,
      width: targetWidth,
      height: targetHeight,
      requestedFrameRate,
      intervalMs: 0,
      sourceSettings: safeTrackSettings(rawVideoTrack),
      publishSettings: safeTrackSettings(rawVideoTrack),
      constraintApplied: false,
      constraintError: "",
      metrics: () => ({ drawCount: 0, elapsedMs: 0, actualDrawFps: 0 }),
      cleanup: () => {},
    };
  }

  const sourceVideo = document.createElement("video");
  sourceVideo.muted = true;
  sourceVideo.defaultMuted = true;
  sourceVideo.playsInline = true;
  sourceVideo.setAttribute("playsinline", "");
  sourceVideo.srcObject = new MediaStream([rawVideoTrack]);
  await waitForVideoMetadata(sourceVideo);
  await sourceVideo.play().catch(() => {});

  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, targetWidth);
  canvas.height = Math.max(1, targetHeight);
  const ctx = canvas.getContext("2d", { alpha: false });
  let drawCount = 0;
  let firstDrawMs = 0;
  let lastDrawMs = 0;
  const drawFrame = () => {
    if (!ctx || sourceVideo.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
    const nowMs = performance.now();
    if (!firstDrawMs) firstDrawMs = nowMs;
    lastDrawMs = nowMs;
    drawCount += 1;
    const sourceWidth = sourceVideo.videoWidth || targetWidth;
    const sourceHeight = sourceVideo.videoHeight || targetHeight;
    const scale = Math.max(canvas.width / sourceWidth, canvas.height / sourceHeight);
    const drawWidth = sourceWidth * scale;
    const drawHeight = sourceHeight * scale;
    const dx = (canvas.width - drawWidth) / 2;
    const dy = (canvas.height - drawHeight) / 2;
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(sourceVideo, dx, dy, drawWidth, drawHeight);
  };
  drawFrame();
  const intervalMs = Math.max(33, Math.round(1000 / requestedFrameRate));
  const drawTimer = window.setInterval(drawFrame, intervalMs);
  const canvasStream = canvas.captureStream(requestedFrameRate);
  const canvasTrack = canvasStream.getVideoTracks()[0] || null;
  let constraintApplied = false;
  let constraintError = "";
  if (canvasTrack && typeof canvasTrack.applyConstraints === "function") {
    try {
      await canvasTrack.applyConstraints({
        width: canvas.width,
        height: canvas.height,
        frameRate: requestedFrameRate,
      });
      constraintApplied = true;
    } catch (error) {
      constraintError = error?.name || "constraint_failed";
    }
  }
  const outputStream = new MediaStream([
    ...canvasStream.getVideoTracks(),
    ...rawStream.getAudioTracks(),
  ]);
  const metrics = () => {
    const elapsedMs = firstDrawMs && lastDrawMs ? Math.max(0, lastDrawMs - firstDrawMs) : 0;
    const effectiveFrames = drawCount > 1 ? drawCount - 1 : drawCount;
    return {
      drawCount,
      elapsedMs: Math.round(elapsedMs),
      actualDrawFps: elapsedMs > 0 ? Math.round((effectiveFrames * 10000) / elapsedMs) / 10 : 0,
    };
  };
  return {
    stream: outputStream,
    transformed: true,
    width: canvas.width,
    height: canvas.height,
    requestedFrameRate,
    intervalMs,
    sourceSettings: safeTrackSettings(rawVideoTrack),
    publishSettings: safeTrackSettings(canvasTrack),
    constraintApplied,
    constraintError,
    metrics,
    cleanup: () => {
      window.clearInterval(drawTimer);
      canvasStream.getTracks().forEach((track) => track.stop());
      sourceVideo.pause();
      sourceVideo.srcObject = null;
    },
  };
}

async function requestMediaStream(constraints, wantsVideo, wantsAudio) {
  try {
    setCaptureStatus("Requesting camera and microphone permission from Safari...");
    return await navigator.mediaDevices.getUserMedia(constraints);
  } catch (error) {
    if (error?.name !== "OverconstrainedError") {
      throw error;
    }
    const fallback = {
      video: wantsVideo ? { facingMode: dom.cameraFacing.value } : false,
      audio: wantsAudio ? true : false,
    };
    return navigator.mediaDevices.getUserMedia(fallback);
  }
}

function describeMediaError(error) {
  if (!error) return "Could not start browser harness capture.";
  if (error.message === "secure_context_required") {
    return "iPhone camera + mic need the HTTPS harness URL. Open the secure browser harness page and tap Start again.";
  }
  if (error.name === "browser_webrtc_unavailable") {
    return "Jetson browser WebRTC ingest is not ready yet. Check backend dependencies and restart the browser harness session.";
  }
  switch (error.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Camera or microphone permission was denied. In Safari, allow camera and microphone for this site, then tap Start again.";
    case "NotFoundError":
      return "Safari could not find the requested camera or microphone on this device.";
    case "NotReadableError":
    case "AbortError":
      return "Safari opened the device but could not start capture. Close other apps using the camera/mic, then retry.";
    case "OverconstrainedError":
      return "The requested capture preset was too strict for this iPhone. Try again and the harness will fall back to a lighter capture preset.";
    default:
      return `Could not start browser harness capture (${error.name || "unknown_error"}).`;
  }
}

async function prepareMediaForGesture(wantsVideo, wantsAudio) {
  const preset = String(dom.videoPreset.value || GLASSES_LIKE_DEFAULT_PRESET);
  const [targetWidth, targetHeight] = preset.split("x").map((value) => Number(value));
  const frameRate = normalizeFrameRate(dom.frameRate.value);
  const prepared = {
    wantsVideo,
    wantsAudio,
    targetWidth,
    targetHeight,
    frameRate,
    stream: null,
  };

  if (!wantsVideo && !wantsAudio) {
    return prepared;
  }
  if (!state.secureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new Error("secure_context_required");
  }

  try {
    const constraints = buildMediaConstraints(wantsVideo, wantsAudio, targetWidth, targetHeight, frameRate);
    prepared.stream = await requestMediaStream(constraints, wantsVideo, wantsAudio);
    sendBrowserTrace("media_constraints_ready", {
      preset,
      targetWidth,
      targetHeight,
      requestedFrameRate: frameRate,
      tracks: mediaTrackSummary(prepared.stream),
    });
    setCaptureStatus("Safari granted media access. Attaching stream to Jetson session...");
    return prepared;
  } catch (error) {
    throw error;
  }
}

async function releasePreparedMedia(prepared) {
  if (!prepared) return;
  if (prepared.stream) {
    prepared.stream.getTracks().forEach((track) => track.stop());
  }
}

function sendJson(payload) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return false;
  state.ws.send(JSON.stringify(payload));
  return true;
}

function sendBrowserTrace(phase, detail = {}) {
  const payload = {
    type: "browser_client_trace",
    sessionId: state.sessionId,
    phase,
    detail,
    timestampMs: Date.now(),
  };
  const sentViaWs = sendJson(payload);
  const body = JSON.stringify({
    sessionId: state.sessionId,
    phase,
    detail,
  });
  try {
    fetch(browserTraceUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {});
  } catch (error) {
    console.warn("trace fetch failed", error);
  }
  return sentViaWs;
}

async function connectSimulatorSession() {
  if (state.ws && state.ws.readyState === WebSocket.OPEN && state.sessionId) {
    return state.sessionId;
  }
  if (state.ws) {
    try {
      state.ws.close(1000, "restart");
    } catch (error) {
      console.warn(error);
    }
  }

  updateConnectionBadge("connecting", "warn");
  return new Promise((resolve, reject) => {
    let resolved = false;
    const ws = new WebSocket(wsUrl());
    state.ws = ws;

    ws.onopen = () => {
      sendJson({
        type: "client_hello",
        deviceId: `browser-${navigator.platform || "unknown"}`,
        appVersion: `browser-harness/${SIMULATOR_ASSET_VERSION}`,
        selectedMode: dom.modeSelect.value,
        userAgent: navigator.userAgent,
        platform: navigator.platform,
        secureContext: state.secureContext,
        screen: {
          width: window.screen.width,
          height: window.screen.height,
          pixelRatio: window.devicePixelRatio || 1,
        },
      });
    };

    ws.onmessage = async (event) => {
      let payload = null;
      try {
        payload = JSON.parse(event.data);
      } catch (error) {
        console.warn("Invalid browser harness payload", error);
        return;
      }
      const type = payload?.type;
      if (type === "session_accept") {
        state.sessionId = payload.sessionId || "";
        state.connected = true;
        dom.sessionLabel.textContent = state.sessionId || "none";
        updateConnectionBadge("connected", "good");
        setCaptureStatus("Browser harness linked. Start camera and mic.");
        sendBrowserTrace("session_accept", { sessionId: state.sessionId });
        ensureDetailPolling();
        if (!resolved) {
          resolved = true;
          resolve(state.sessionId);
        }
        return;
      }
      if (type === "mode_state") {
        const mode = payload.mode || dom.modeSelect.value;
        dom.modeSelect.value = mode;
        dom.modeLabel.textContent = mode;
        return;
      }
      if (type === "speech_state") {
        state.latestSpeechState = payload;
        renderSpeechState();
        return;
      }
      if (type === "hud_scene") {
        state.latestHudScene = payload;
        renderHudScene();
        return;
      }
      if (type === "vision_result") {
        state.latestVisionResult = payload;
        renderVisionResult();
        return;
      }
      if (type === "node_telemetry") {
        state.latestNodeTelemetry = payload;
        return;
      }
      if (type === "error") {
        setCaptureStatus(payload.message || "Browser harness error");
      }
    };

    ws.onerror = (event) => {
      console.error("Browser harness websocket error", event);
      if (!resolved) {
        reject(new Error("websocket_failed"));
      }
    };

    ws.onclose = () => {
      state.connected = false;
      state.running = false;
      updateConnectionBadge("offline", "warn");
      if (state.sessionId) {
        setCaptureStatus("Browser harness disconnected from Jetson.");
      }
      state.sessionId = "";
      dom.sessionLabel.textContent = "none";
      stopDetailPolling();
    };
  });
}

async function startSimulator() {
  if (state.starting || state.running) return;
  state.starting = true;
  dom.startButton.disabled = true;
  const wantsVideo = dom.enableVideo.checked;
  const wantsAudio = dom.enableAudio.checked;
  let prepared = null;
  try {
    sendBrowserTrace("start_clicked", { wantsVideo, wantsAudio });
    if (!wantsVideo && !wantsAudio) {
      await connectSimulatorSession();
      sendJson({ type: "browser_media_state", sessionId: state.sessionId, videoActive: false, audioActive: false });
      setCaptureStatus("Harness linked in typed-command mode.");
      state.running = true;
      return;
    }

    prepared = await prepareMediaForGesture(wantsVideo, wantsAudio);
    sendBrowserTrace("media_granted", {
      videoTracks: prepared.stream?.getVideoTracks?.().length || 0,
      audioTracks: prepared.stream?.getAudioTracks?.().length || 0,
    });
    await connectSimulatorSession();
    sendBrowserTrace("session_connected", { sessionId: state.sessionId });
    sendBrowserTrace("attach_begin", {
      wantsVideo,
      wantsAudio,
      videoTracks: prepared.stream?.getVideoTracks?.().length || 0,
      audioTracks: prepared.stream?.getAudioTracks?.().length || 0,
    });
    await attachPreparedMedia(prepared);
    prepared = null;
    state.running = true;
    setCaptureStatus("Browser harness is publishing camera and microphone into the Jetson session.");
  } catch (error) {
    console.error(error);
    await releasePreparedMedia(prepared);
    sendBrowserTrace("fatal_error", {
      name: error?.name || "",
      message: error?.message || String(error || ""),
    });
    setCaptureStatus(describeMediaError(error));
    updateConnectionBadge("error", "bad");
  } finally {
    state.starting = false;
    dom.startButton.disabled = false;
  }
}

async function attachPreparedMedia(prepared) {
  await stopMediaCapture();

  const stream = prepared?.stream || null;
  const wantsVideo = Boolean(prepared?.wantsVideo);
  const wantsAudio = Boolean(prepared?.wantsAudio);
  state.mediaStream = stream;
  state.publishStream = null;

  sendJson({
    type: "browser_media_state",
    sessionId: state.sessionId,
    videoActive: wantsVideo,
    audioActive: wantsAudio,
  });
  sendBrowserTrace("media_state_sent", { wantsVideo, wantsAudio });

  let publishStream = stream;
  if (wantsVideo && stream) {
    const requestedFrameRate = normalizeFrameRate(prepared?.frameRate);
    const publisher = await createGlassesLikePublishStream(
      stream,
      Number(prepared?.targetWidth) || 720,
      Number(prepared?.targetHeight) || 960,
      requestedFrameRate,
    );
    publishStream = publisher.stream;
    state.publishStream = publishStream;
    state.publishCleanup = publisher.cleanup;
    sendBrowserTrace("glasses_publish_stream_ready", {
      transformed: publisher.transformed,
      width: publisher.width,
      height: publisher.height,
      requestedFrameRate: publisher.requestedFrameRate || requestedFrameRate,
      intervalMs: publisher.intervalMs || 0,
      sourceSettings: publisher.sourceSettings || {},
      publishSettings: publisher.publishSettings || {},
      constraintApplied: Boolean(publisher.constraintApplied),
      constraintError: publisher.constraintError || "",
      metrics: typeof publisher.metrics === "function" ? publisher.metrics() : {},
    });
    dom.cameraPreview.muted = true;
    dom.cameraPreview.defaultMuted = true;
    dom.cameraPreview.setAttribute("muted", "");
    dom.cameraPreview.playsInline = true;
    dom.cameraPreview.setAttribute("playsinline", "");
    dom.cameraPreview.setAttribute("autoplay", "");
    dom.cameraPreview.autoplay = true;
    dom.cameraPreview.srcObject = publishStream;
    await waitForVideoMetadata(dom.cameraPreview);
    sendBrowserTrace("video_metadata_ready", {
      readyState: dom.cameraPreview.readyState,
      width: dom.cameraPreview.videoWidth,
      height: dom.cameraPreview.videoHeight,
      requestedFrameRate,
      publishTracks: mediaTrackSummary(publishStream),
    });
    await dom.cameraPreview.play().catch((error) => {
      console.warn("cameraPreview.play() failed", error);
      sendBrowserTrace("preview_play_failed", {
        name: error?.name || "",
        message: error?.message || String(error || ""),
      });
    });
    sendBrowserTrace("preview_play_attempted", {
      readyState: dom.cameraPreview.readyState,
      width: dom.cameraPreview.videoWidth,
      height: dom.cameraPreview.videoHeight,
      requestedFrameRate,
    });
    state.publishMetricsTimer = window.setTimeout(() => {
      sendBrowserTrace("glasses_publish_stream_metrics", {
        requestedFrameRate,
        metrics: typeof publisher.metrics === "function" ? publisher.metrics() : {},
        publishTracks: mediaTrackSummary(publishStream),
      });
    }, 2500);
  } else {
    dom.cameraPreview.srcObject = null;
    state.publishStream = stream;
  }

  if (publishStream && (wantsVideo || wantsAudio)) {
    await startWebRtcPublish(publishStream);
  }
}

async function startWebRtcPublish(stream) {
  if (!stream) {
    return;
  }
  sendBrowserTrace("webrtc_begin", {
    trackKinds: stream.getTracks().map((track) => track.kind),
  });
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }],
  });
  state.pc = pc;
  state.webrtcConnected = false;

  pc.addEventListener("connectionstatechange", () => {
    const connectionState = pc.connectionState || "unknown";
    sendBrowserTrace("webrtc_connection_state", { connectionState });
    if (connectionState === "connected") {
      state.webrtcConnected = true;
      setCaptureStatus("Browser harness is publishing camera and microphone into the Jetson session over WebRTC.");
    } else if (["failed", "disconnected", "closed"].includes(connectionState)) {
      state.webrtcConnected = false;
    }
  });
  pc.addEventListener("iceconnectionstatechange", () => {
    sendBrowserTrace("webrtc_ice_state", { iceConnectionState: pc.iceConnectionState || "unknown" });
  });

  stream.getTracks().forEach((track) => {
    pc.addTrack(track, stream);
    sendBrowserTrace("webrtc_track_added", {
      kind: track.kind,
      readyState: track.readyState,
      enabled: track.enabled,
      settings: safeTrackSettings(track),
    });
  });

  sendBrowserTrace("webrtc_create_offer_begin");
  const offer = await pc.createOffer();
  sendBrowserTrace("webrtc_create_offer_done", {
    type: offer?.type || "",
    sdpLength: offer?.sdp?.length || 0,
  });
  await pc.setLocalDescription(offer);
  await waitForIceGatheringComplete(pc);
  sendBrowserTrace("webrtc_offer_ready", {
    sdpLength: pc.localDescription?.sdp?.length || 0,
  });

  sendBrowserTrace("webrtc_fetch_answer_begin");
  const answer = await fetchJson(webrtcOfferUrl(), {
    method: "POST",
    body: JSON.stringify({
      sessionId: state.sessionId,
      type: pc.localDescription?.type || "offer",
      sdp: pc.localDescription?.sdp || "",
      assetVersion: SIMULATOR_ASSET_VERSION,
    }),
  });
  sendBrowserTrace("webrtc_fetch_answer_done", {
    type: answer?.type || "",
    sdpLength: answer?.sdp?.length || 0,
  });
  await pc.setRemoteDescription(answer);
  sendBrowserTrace("webrtc_answer_applied", {
    type: answer?.type || "",
    sdpLength: answer?.sdp?.length || 0,
  });
  scheduleOutboundVideoStats(pc);
}

async function reportOutboundVideoStats(pc, phase) {
  if (!pc || typeof pc.getStats !== "function") {
    return;
  }
  try {
    const report = await pc.getStats();
    const videoStats = [];
    report.forEach((item) => {
      if (item?.type === "outbound-rtp" && item.kind === "video") {
        videoStats.push({
          framesPerSecond: item.framesPerSecond || 0,
          framesEncoded: item.framesEncoded || 0,
          frameWidth: item.frameWidth || 0,
          frameHeight: item.frameHeight || 0,
          bytesSent: item.bytesSent || 0,
          packetsSent: item.packetsSent || 0,
        });
      }
    });
    sendBrowserTrace(phase, { video: videoStats });
  } catch (error) {
    sendBrowserTrace("webrtc_outbound_video_stats_failed", {
      phase,
      name: error?.name || "",
      message: error?.message || String(error || ""),
    });
  }
}

function scheduleOutboundVideoStats(pc) {
  state.webrtcStatsTimers.forEach((timer) => window.clearTimeout(timer));
  state.webrtcStatsTimers = [2500, 8000].map((delayMs) => window.setTimeout(() => {
    if (pc === state.pc) {
      reportOutboundVideoStats(pc, delayMs < 3000 ? "webrtc_outbound_video_stats_early" : "webrtc_outbound_video_stats_late");
    }
  }, delayMs));
}

async function stopMediaCapture() {
  if (state.pc) {
    try {
      state.pc.getSenders().forEach((sender) => {
        try {
          sender.track?.stop?.();
        } catch (error) {
          console.warn(error);
        }
      });
      state.pc.close();
    } catch (error) {
      console.warn(error);
    }
  }
  state.pc = null;
  state.webrtcConnected = false;
  state.webrtcStatsTimers.forEach((timer) => window.clearTimeout(timer));
  state.webrtcStatsTimers = [];
  dom.fpsLabel.textContent = "0 fps";

  if (state.publishMetricsTimer) {
    window.clearTimeout(state.publishMetricsTimer);
    state.publishMetricsTimer = null;
  }

  if (state.publishCleanup) {
    try {
      state.publishCleanup();
    } catch (error) {
      console.warn(error);
    }
    state.publishCleanup = null;
  }
  state.publishStream = null;

  if (state.mediaStream) {
    state.mediaStream.getTracks().forEach((track) => track.stop());
    state.mediaStream = null;
  }
  dom.cameraPreview.srcObject = null;
}

async function stopSimulator() {
  await stopMediaCapture();
  if (state.connected) {
    sendJson({
      type: "browser_media_state",
      sessionId: state.sessionId,
      videoActive: false,
      audioActive: false,
    });
  }
  if (state.ws) {
    try {
      state.ws.close(1000, "stop");
    } catch (error) {
      console.warn(error);
    }
  }
  state.running = false;
  setCaptureStatus("Browser harness stopped.");
}

function sceneComponents(scene) {
  return Array.isArray(scene?.components) ? scene.components.filter(Boolean) : [];
}

function findHudComponent(scene, kind, id = null) {
  return sceneComponents(scene).find((item) => item.kind === kind && (id == null || item.id === id)) || null;
}

function hudGalleryItems(scene) {
  const gallery = findHudComponent(scene, "gallery");
  return Array.isArray(gallery?.items) ? gallery.items.slice(0, 2) : [];
}

function renderSpeechState() {
  const speech = state.latestSpeechState || {};
  dom.speechLabel.textContent = speech.stateLabel || "idle";
  dom.speechHint.textContent = speech.transcriptHint || speech.taskLabel || "No voice state yet";
}

function renderVisionResult() {
  const vision = state.latestVisionResult || {};
  dom.visionLabel.textContent = vision.headline || "waiting";
  const details = Array.isArray(vision.details) ? vision.details.filter(Boolean) : [];
  dom.visionHint.textContent = details[0] || "No perception updates yet";
}

function renderHudScene() {
  const scene = state.latestHudScene || {};
  const topChips = [];
  const taskChip = findHudComponent(scene, "chip", "task_chip");
  const micChip = findHudComponent(scene, "chip", "mic_chip");
  const directionHint = findHudComponent(scene, "direction_hint");
  if (taskChip?.text) topChips.push(`<div class="hud-chip">${escapeHtml(taskChip.text)}</div>`);
  if (micChip?.text) topChips.push(`<div class="hud-chip">${escapeHtml(micChip.text)}</div>`);
  if (directionHint?.text) topChips.push(`<div class="hud-chip">${escapeHtml(directionHint.text)}</div>`);
  dom.hudTopCenter.innerHTML = topChips.join("");

  const gallery = hudGalleryItems(scene);
  dom.hudGallery.innerHTML = gallery.map((item) => {
    const thumb = item.thumbB64
      ? `<img class="hud-gallery-thumb" src="data:image/png;base64,${item.thumbB64}" alt="${escapeHtml(item.label || "target")}">`
      : `<div class="hud-gallery-thumb"></div>`;
    return `
      <div class="hud-gallery-item ${item.selected ? "selected" : ""}">
        ${thumb}
        <div class="hud-gallery-copy">
          <strong>${escapeHtml(item.label || "Target")}</strong>
          <small>${escapeHtml(item.secondary || "")}</small>
        </div>
      </div>
    `;
  }).join("");

  const marker = findHudComponent(scene, "target_marker");
  if (marker && typeof marker.normalizedX === "number" && typeof marker.normalizedY === "number") {
    dom.hudMarker.classList.remove("hidden");
    dom.hudMarker.style.left = `${Math.min(88, Math.max(12, marker.normalizedX * 100))}%`;
    dom.hudMarker.style.top = `${Math.min(74, Math.max(18, marker.normalizedY * 100 - 6))}%`;
    dom.hudMarker.innerHTML = `
      <div class="hud-reticle"></div>
      <div class="hud-marker-label">${escapeHtml(marker.label || marker.trackId || "Target")}</div>
    `;
  } else {
    dom.hudMarker.classList.add("hidden");
    dom.hudMarker.innerHTML = "";
  }

  const answer = findHudComponent(scene, "answer_strip");
  const status = findHudComponent(scene, "status_strip");
  const strips = [];
  if (answer?.text) strips.push(`<div class="hud-strip answer">${escapeHtml(answer.text)}</div>`);
  if (status?.text) strips.push(`<div class="hud-strip status">${escapeHtml(status.text)}</div>`);
  if (!strips.length && state.latestSpeechState?.transcriptHint) {
    strips.push(`<div class="hud-strip status">${escapeHtml(state.latestSpeechState.transcriptHint)}</div>`);
  }
  dom.hudLowerStrip.classList.toggle("hidden", strips.length === 0);
  dom.hudLowerStrip.innerHTML = strips.join("");
}

function renderTrace(items) {
  state.latestSkillTrace = Array.isArray(items) ? items : [];
  dom.traceBadge.textContent = String(state.latestSkillTrace.length);
  if (!state.latestSkillTrace.length) {
    dom.skillTrace.innerHTML = `<div class="sim-empty">No skill trace yet.</div>`;
    return;
  }
  dom.skillTrace.innerHTML = state.latestSkillTrace.slice().reverse().map((item) => {
    const payload = item.payload ? `<pre>${escapeHtml(JSON.stringify(item.payload, null, 2))}</pre>` : "";
    const when = item.timestampMs ? new Date(item.timestampMs).toLocaleTimeString() : "--";
    return `
      <article class="sim-log-item">
        <strong>${escapeHtml(item.title || item.kind || "trace")}</strong>
        <div class="sim-log-meta">${escapeHtml(when)} · ${escapeHtml(item.summary || "")}</div>
        ${payload}
      </article>
    `;
  }).join("");
}

function renderSelectedTarget(target) {
  state.selectedTarget = target || null;
  if (!target) {
    dom.selectedTarget.innerHTML = "No selected target yet.";
    return;
  }
  dom.selectedTarget.innerHTML = `
    <strong>${escapeHtml(target.label || target.trackId || "Target")}</strong>
    <div class="sim-log-meta">${escapeHtml(target.query || "")}</div>
    <div>${escapeHtml(target.summary || "Awaiting Jetson target context")}</div>
  `;
}

async function refreshSessionDetail() {
  if (!state.sessionId) return;
  try {
    const detail = await fetchJson(`/api/admin/sessions/${encodeURIComponent(state.sessionId)}`);
    if (detail?.session) {
      renderTrace(detail.session.latestSkillTrace || []);
      renderSelectedTarget(detail.session.voiceContext?.selectedTarget || detail.session.selectedTarget || null);
    }
  } catch (error) {
    console.warn("session detail refresh failed", error);
  }
}

function ensureDetailPolling() {
  stopDetailPolling();
  state.detailTimer = window.setInterval(refreshSessionDetail, 1200);
  refreshSessionDetail();
}

function stopDetailPolling() {
  if (state.detailTimer) {
    clearInterval(state.detailTimer);
    state.detailTimer = null;
  }
}

async function sendManualCommand() {
  const text = dom.manualCommand.value.trim();
  if (!text || !state.sessionId) return;
  try {
    await fetchJson(`/api/admin/sessions/${encodeURIComponent(state.sessionId)}/simulate_command`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    dom.manualCommand.value = "";
    setCaptureStatus("Typed command injected into the Jetson skill path.");
    refreshSessionDetail();
  } catch (error) {
    console.error(error);
    setCaptureStatus("Typed command failed.");
  }
}

async function applyModeOnly() {
  if (!state.sessionId) return;
  const mode = dom.modeSelect.value;
  sendJson({ type: "mode_change", sessionId: state.sessionId, mode });
  dom.modeLabel.textContent = mode;
  try {
    await fetchJson(`/api/admin/sessions/${encodeURIComponent(state.sessionId)}/mode`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
  } catch (error) {
    console.warn(error);
  }
}

dom.startButton.addEventListener("click", () => {
  startSimulator();
});

dom.stopButton.addEventListener("click", () => {
  stopSimulator();
});

dom.sendCommandButton.addEventListener("click", () => {
  sendManualCommand();
});

dom.applyModeButton.addEventListener("click", () => {
  applyModeOnly();
});

window.addEventListener("beforeunload", () => {
  stopSimulator();
});

window.addEventListener("error", (event) => {
  sendBrowserTrace("window_error", {
    message: event.message || "",
    source: event.filename || "",
    line: event.lineno || 0,
    column: event.colno || 0,
  });
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  sendBrowserTrace("unhandled_rejection", {
    message: reason?.message || String(reason || ""),
  });
});

applyGlassesLikeDefaults();
loadSecureRecommendation();
renderSpeechState();
renderVisionResult();
renderHudScene();
renderTrace([]);
renderSelectedTarget(null);
