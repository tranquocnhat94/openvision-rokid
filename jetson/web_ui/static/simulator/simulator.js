const ui = {
  preview: document.querySelector("#preview"),
  start: document.querySelector("#startButton"),
  state: document.querySelector("#stateChip"),
  answer: document.querySelector("#hudAnswer"),
  chips: document.querySelector("#hudChips"),
  thumbs: document.querySelector("#hudThumbs"),
};

let sessionId = null;
let peer = null;
let hudPollTimer = null;
let lastSceneId = null;

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
  return media;
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
    body: JSON.stringify({ turn_policy: "server_vad", output_modalities: ["text"] }),
  });
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
    await createSession();
    await startRealtime();
    const media = await startMedia();
    await connectWebRtc(media);
    await loadHud();
    startHudPolling();
    setState("Connected");
  } catch (error) {
    setState("Error");
    ui.answer.textContent = error.message;
    ui.start.hidden = false;
  }
});
