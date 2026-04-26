const ui = {
  preview: document.querySelector("#preview"),
  start: document.querySelector("#startButton"),
  state: document.querySelector("#stateChip"),
  answer: document.querySelector("#hudAnswer"),
  chips: document.querySelector("#hudChips"),
  thumbs: document.querySelector("#hudThumbs"),
  voice: document.querySelector("#voiceToggle"),
};

let sessionId = null;
let peer = null;
let activeMedia = null;
let hudPollTimer = null;
let lastSceneId = null;
let voiceSocket = null;
let voiceAudioContext = null;
let voicePlayhead = 0;

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

function renderHud(scene) {
  ui.answer.textContent = scene.answer_strip || "Ready";
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

async function startMedia() {
  const media = await navigator.mediaDevices.getUserMedia({
    video: {
      facingMode: "environment",
      width: { ideal: 1280 },
      height: { ideal: 720 },
    },
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  ui.preview.srcObject = media;
  activeMedia = media;
  return media;
}

function stopMedia() {
  if (!activeMedia) return;
  for (const track of activeMedia.getTracks()) {
    track.stop();
  }
  activeMedia = null;
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
  if (!ui.voice?.checked || !sessionId) return;
  voiceAudioContext = voiceAudioContext || new AudioContext();
  if (voiceAudioContext.state === "suspended") {
    await voiceAudioContext.resume();
  }
  voicePlayhead = Math.max(voiceAudioContext.currentTime, voicePlayhead);
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  voiceSocket = new WebSocket(`${protocol}//${window.location.host}/ws/realtime/${encodeURIComponent(sessionId)}/audio`);
  voiceSocket.addEventListener("message", (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_error) {
      return;
    }
    if (message.type === "audio_delta" && typeof message.audio_base64 === "string") {
      playPcm16(message.audio_base64, Number(message.sample_rate) || 24000);
    }
  });
}

function disconnectVoiceOutput() {
  if (voiceSocket) {
    voiceSocket.close();
    voiceSocket = null;
  }
  voicePlayhead = 0;
}

function playPcm16(audioBase64, sampleRate) {
  if (!voiceAudioContext) return;
  const binary = window.atob(audioBase64);
  const sampleCount = Math.floor(binary.length / 2);
  if (sampleCount <= 0) return;
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
  hudPollTimer = window.setInterval(pollHud, 700);
}

ui.start.addEventListener("click", async () => {
  try {
    ui.start.hidden = true;
    setState("Starting");
    if (!window.isSecureContext) {
      setState("HTTPS required");
      ui.start.hidden = false;
      return;
    }
    setState("Requesting camera");
    const media = await startMedia();
    setState("Creating session");
    await createSession();
    setState("Starting realtime");
    await startRealtime();
    await connectVoiceOutput();
    setState("Connecting media");
    await connectWebRtc(media);
    await loadHud();
    startHudPolling();
    setState("Connected");
  } catch (error) {
    disconnectVoiceOutput();
    stopMedia();
    setState("Error");
    ui.answer.textContent = error.message;
    ui.start.hidden = false;
  }
});
