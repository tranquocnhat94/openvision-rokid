const state = {
  recorder: null,
  recordings: [],
  finalizing: new Set(),
};

async function api(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return response.json();
}

async function apiPost(path) {
  const response = await fetch(path, { method: "POST", cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return response.json();
}

function artifactUrl(recordingId, artifact) {
  return `/api/recordings/${encodeURIComponent(recordingId)}/files/${encodeURIComponent(artifact)}`;
}

function artifact(recording, key) {
  return (recording.artifacts || {})[key] || { exists: false, size_bytes: 0 };
}

function hasArtifact(recording, key) {
  return artifact(recording, key).exists === true && Number(artifact(recording, key).size_bytes || 0) > 0;
}

function humanBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatSeconds(value) {
  const seconds = Number(value || 0);
  if (!Number.isFinite(seconds) || seconds <= 0) return "?s";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

function formatFps(value) {
  const fps = Number(value || 0);
  if (!Number.isFinite(fps) || fps <= 0) return "?fps";
  return `${fps.toFixed(1)}fps`;
}

function renderFacts() {
  const facts = document.querySelector("#recordingFacts");
  const chip = document.querySelector("#recordingHealthChip");
  const recorder = state.recorder || {};
  const enabled = recorder.enabled === true;
  chip.className = enabled ? "chip" : "chip warn";
  chip.textContent = enabled ? "Recorder enabled" : "Recorder disabled";
  facts.innerHTML = `
    <div><dt>Root</dt><dd>${recorder.root_dir || "unknown"}</dd></div>
    <div><dt>Queue</dt><dd>${recorder.pending_item_count || 0}/${recorder.queue_size || 0}</dd></div>
    <div><dt>Active</dt><dd>${recorder.active_session_count || 0}</dd></div>
    <div><dt>Playable</dt><dd>${recorder.playable_video_enabled ? "MP4 on close" : "disabled"}</dd></div>
    <div><dt>Dropped</dt><dd>${recorder.total_dropped_item_count || 0}</dd></div>
  `;
}

function recordingSummary(recording) {
  const rawVideo = artifact(recording, "raw_video");
  const rawMp4 = artifact(recording, "raw_video_mp4");
  const rawAudio = artifact(recording, "raw_audio");
  const processed = artifact(recording, "processed_preview");
  const processedMp4 = artifact(recording, "processed_preview_mp4");
  const summary = recording.summary || {};
  const rawSize = summary.raw_video_width && summary.raw_video_height ? `${summary.raw_video_width}x${summary.raw_video_height}` : "?";
  const processedSize = summary.processed_preview_width && summary.processed_preview_height ? `${summary.processed_preview_width}x${summary.processed_preview_height}` : "?";
  return [
    `raw ${rawSize} ${formatFps(summary.raw_video_fps_estimate)} · ${humanBytes(rawVideo.size_bytes)} h264 · ${humanBytes(rawMp4.size_bytes)} mp4`,
    `processed ${processedSize} ${formatFps(summary.processed_fps_estimate)} · ${summary.processed_frame_count || 0} frames · ${humanBytes(processed.size_bytes)} mjpeg · ${humanBytes(processedMp4.size_bytes)} mp4`,
    `voice ${formatSeconds(summary.raw_audio_duration_s)} · ${humanBytes(rawAudio.size_bytes)}`,
  ].join(" · ");
}

function artifactLink(recording, key, artifactName, label) {
  const recordingId = recording.recording_id || "";
  if (!hasArtifact(recording, key)) {
    return `<span class="chip muted">No ${label}</span>`;
  }
  return `<a class="link-button" href="${artifactUrl(recordingId, artifactName)}" target="_blank" rel="noreferrer">${label}</a>`;
}

function videoPanel(recording, options) {
  const recordingId = recording.recording_id || "";
  const { title, key, artifactName, emptyText } = options;
  if (hasArtifact(recording, key)) {
    return `
      <div class="recording-video-panel">
        <div class="item-meta">${title}</div>
        <video class="recording-video" controls preload="metadata" src="${artifactUrl(recordingId, artifactName)}"></video>
      </div>
    `;
  }
  if (options.fallbackImage && hasArtifact(recording, "latest_annotated_preview")) {
    return `
      <div class="recording-video-panel">
        <div class="item-meta">${title}</div>
        <div class="recording-stage">
          <img class="recording-preview-frame" src="${artifactUrl(recordingId, "latest-annotated")}?t=${Date.now()}" alt="Latest processed frame ${recordingId}" />
        </div>
        <div class="item-meta">MP4 is not ready yet. Showing the latest saved frame only.</div>
      </div>
    `;
  }
  return `
    <div class="recording-video-panel">
      <div class="item-meta">${title}</div>
      <div class="recording-stage"><div class="preview-empty">${emptyText}</div></div>
    </div>
  `;
}

function finalizeButton(recording) {
  const recordingId = recording.recording_id || "";
  const canFinalize = hasArtifact(recording, "raw_video") || hasArtifact(recording, "processed_preview");
  const hasMp4 = hasArtifact(recording, "raw_video_mp4") || hasArtifact(recording, "processed_preview_mp4");
  const busy = state.finalizing.has(recordingId);
  const label = busy ? "Creating MP4..." : hasMp4 ? "Refresh MP4" : "Create MP4";
  return `<button type="button" data-action="finalize" ${canFinalize && !busy ? "" : "disabled"}>${label}</button>`;
}

function renderRecordings() {
  const root = document.querySelector("#recordingsList");
  root.innerHTML = "";
  if (!state.recordings.length) {
    root.innerHTML = `
      <article class="item">
        <div class="item-title">No recordings yet</div>
        <div class="item-meta">Wear the glasses or simulator, run a visual/voice session, then refresh this page.</div>
      </article>
    `;
    return;
  }
  for (const recording of state.recordings) {
    const recordingId = recording.recording_id || "";
    const card = document.createElement("article");
    card.className = "recording-card";
    card.dataset.recordingId = recordingId;
    const audioBody = hasArtifact(recording, "raw_audio")
      ? `<audio controls preload="metadata" src="${artifactUrl(recordingId, "raw-audio")}"></audio>`
      : `<div class="item-meta">No voice WAV captured for this recording.</div>`;

    card.innerHTML = `
      <div class="recording-body">
        <div>
          <div class="item-title">${recordingId}</div>
          <div class="item-meta">session ${recording.session_id || "unknown"} · updated ${recording.updated_at || "unknown"}</div>
          <div class="item-meta">${recordingSummary(recording)}</div>
        </div>
        <div class="recording-media-grid">
          ${videoPanel(recording, {
            title: "Processed overlay MP4",
            key: "processed_preview_mp4",
            artifactName: "processed-preview-mp4",
            fallbackImage: true,
            emptyText: "No processed overlay video yet",
          })}
          ${videoPanel(recording, {
            title: "Raw camera MP4",
            key: "raw_video_mp4",
            artifactName: "raw-video-mp4",
            emptyText: "No raw playable MP4 yet",
          })}
        </div>
        <div class="recording-audio">
          <div class="item-meta">Voice WAV</div>
          ${audioBody}
        </div>
        <div class="recording-actions">
          ${finalizeButton(recording)}
          ${artifactLink(recording, "latest_annotated_preview", "latest-annotated", "Latest frame")}
          ${artifactLink(recording, "raw_video", "raw-video", "Raw H.264")}
          ${artifactLink(recording, "processed_preview", "processed-mjpeg", "Processed MJPEG")}
          ${artifactLink(recording, "manifest", "manifest", "Manifest")}
        </div>
      </div>
    `;
    root.append(card);
  }
}

async function refreshRecordings() {
  const payload = await api("/api/recordings?limit=100");
  state.recorder = payload.recorder || {};
  state.recordings = payload.recordings || [];
  renderFacts();
  renderRecordings();
}

async function finalizeRecording(recordingId) {
  state.finalizing.add(recordingId);
  renderRecordings();
  try {
    await apiPost(`/api/recordings/${encodeURIComponent(recordingId)}/finalize`);
    await refreshRecordings();
  } finally {
    state.finalizing.delete(recordingId);
    renderRecordings();
  }
}

function handleRecordingClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const card = button.closest(".recording-card");
  const recordingId = card?.dataset.recordingId;
  if (!recordingId) return;
  if (button.dataset.action === "finalize") {
    finalizeRecording(recordingId).catch((error) => {
      button.textContent = "MP4 failed";
      button.title = error.message;
    });
  }
}

document.querySelector("#refreshRecordingsButton").addEventListener("click", () => {
  refreshRecordings().catch((error) => {
    document.querySelector("#recordingsList").innerHTML = `<article class="item"><div class="item-title">Refresh failed</div><div class="item-meta">${error.message}</div></article>`;
  });
});
document.querySelector("#recordingsList").addEventListener("click", handleRecordingClick);

refreshRecordings().catch((error) => {
  document.querySelector("#recordingHealthChip").className = "chip error";
  document.querySelector("#recordingHealthChip").textContent = "Recordings failed";
  document.querySelector("#recordingsList").innerHTML = `<article class="item"><div class="item-title">Load failed</div><div class="item-meta">${error.message}</div></article>`;
});
