def build_preview_live_page(latest_label: str) -> str:
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Rokid Jetson Live Preview</title>
    <style>
      body {{
        margin: 0;
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        background: #0b1016;
        color: #d8f3dc;
      }}
      main {{
        max-width: 1080px;
        margin: 0 auto;
        padding: 20px;
      }}
      .card {{
        background: #101923;
        border: 1px solid #203040;
        border-radius: 14px;
        padding: 16px;
      }}
      video {{
        width: 100%;
        background: #000;
        border-radius: 12px;
      }}
      img {{
        width: 100%;
        background: #000;
        border-radius: 12px;
      }}
      a {{
        color: #80ed99;
      }}
      .muted {{
        color: #9fb3c8;
      }}
    </style>
  </head>
  <body>
    <main>
      <div class="card">
        <h1>Rokid Jetson Sensor Debug Preview</h1>
        <p class="muted">Latest session: {latest_label}</p>
        <img src="/preview/latest/live.mjpg" alt="Jetson sensor debug preview" />
        <p><a href="/preview/latest/live.mjpg">Open sensor debug stream</a></p>
        <p class="muted">This is a Jetson-side debug view from the frame bus. It is not the glasses media contract.</p>
      </div>
    </main>
  </body>
</html>"""


def build_dashboard_page() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Rokid Jetson Ops Console</title>
    <link rel="stylesheet" href="/admin-static/dashboard.css">
  </head>
  <body>
    <div id="app">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">RK</div>
          <div>
            <h1>Rokid Ops Console</h1>
            <p>Thin-client voice-first control surface</p>
          </div>
        </div>
        <div class="panel">
          <h2>Jetson</h2>
          <div id="healthCards" class="metric-grid"></div>
        </div>
        <div class="panel product-ops-panel">
          <h2>Product Ops</h2>
          <p class="muted">Default console surface: health, sessions, skill trace, HUD scene, simulator link, and sensor preview only.</p>
          <div class="ops-path-card">
            <span>Active backend</span>
            <strong id="activeBackendLabel">openai_realtime_skills</strong>
            <small>Product path: speech -> OpenAI Realtime tool call -> Jetson skill -> thin HUD scene.</small>
          </div>
        </div>
        <details class="advanced-rails ops-config-lab">
          <summary>Advanced Lab: runtime settings and fallback/offline rails</summary>
          <p class="muted">Closed by default on purpose. Use only for explicit debug/offline experiments; this is not the normal product operating surface.</p>
          <form id="openaiForm" class="stack-form">
            <label>Auto wake on session<input type="checkbox" id="autoWakeOnSession"></label>
            <label>Idle unload ms<input type="number" id="backendIdleUnloadMs"></label>
            <label>Startup timeout ms<input type="number" id="backendStartupTimeoutMs"></label>
            <label>Enable API<input type="checkbox" id="enableOpenAI"></label>
            <label>API key<input type="password" id="openaiApiKey" placeholder="sk-..." autocomplete="off"></label>
            <label>Base URL<input type="text" id="openaiBaseUrl"></label>
            <label>Realtime voice model<input type="text" id="openaiRealtimeVoiceModel" placeholder="gpt-realtime-1.5"></label>
            <label>Vision model<input type="text" id="openaiVisionModel" placeholder="gpt-5.4"></label>
            <label>Vision reasoning<input type="checkbox" id="openaiVisionReasoningEnabled"></label>
            <label>Realtime skill turn detection
              <select id="realtimeSkillTurnDetection">
                <option value="semantic_vad">semantic_vad</option>
                <option value="server_vad">server_vad</option>
              </select>
            </label>
            <label>Realtime semantic eagerness<input type="text" id="realtimeSkillSemanticEagerness" placeholder="medium"></label>
            <label>ASR backend
              <select id="asrBackend">
                <option value="openai_realtime_skills">openai_realtime_skills (primary)</option>
                <option value="disabled">disabled</option>
                <option value="hybrid_local_openai">hybrid_local_openai (fallback lab)</option>
                <option value="local_http">local_http (offline lab)</option>
                <option value="local_command">local_command (offline lab)</option>
                <option value="openai">openai (legacy batch lab)</option>
                <option value="openai_realtime">openai_realtime (legacy route lab)</option>
              </select>
            </label>
            <label>Allow STT fallback<input type="checkbox" id="allowOpenAITranscriptionFallback"></label>
            <label>Allow router fallback<input type="checkbox" id="allowOpenAIRouterFallback"></label>
            <label>Local profile<input type="text" id="localBackendProfile" placeholder="vi_small_low_power"></label>
            <label>Local request format
              <select id="localRequestFormat">
                <option value="binary_wav">binary_wav</option>
                <option value="multipart_wav">multipart_wav</option>
                <option value="json_base64">json_base64</option>
              </select>
            </label>
            <label>Local transcribe URL<input type="text" id="localTranscribeUrl" placeholder="http://127.0.0.1:9200/inference"></label>
            <label>Local health URL<input type="text" id="localHealthUrl" placeholder="http://127.0.0.1:9200/health"></label>
            <label>Local start command<textarea id="localStartCommand" rows="3" placeholder="/mnt/ssd/.../scripts/start_local_asr.sh"></textarea></label>
            <label>Local stop command<textarea id="localStopCommand" rows="2" placeholder="/mnt/ssd/.../scripts/stop_local_asr.sh"></textarea></label>
            <label>Local command template<textarea id="localCommandTemplate" rows="2" placeholder="bash /path/transcribe_local.sh {wav_path}"></textarea></label>
            <label>Local response text path<input type="text" id="localResponseTextPath" placeholder="text"></label>
            <label>Realtime skill instructions<textarea id="openaiRealtimeSkillInstructions" rows="5"></textarea></label>
            <label>Transcription model<input type="text" id="transcriptionModel"></label>
            <label>Chat model<input type="text" id="chatModel"></label>
            <label>Language hint<input type="text" id="languageHint"></label>
            <label>Min segment ms<input type="number" id="minSegmentMs"></label>
            <label>Max segment ms<input type="number" id="maxSegmentMs"></label>
            <label>Idle flush ms<input type="number" id="idleFlushMs"></label>
            <label>Silence floor<input type="number" id="silenceFloor"></label>
            <label>Router prompt<textarea id="routerSystemPrompt" rows="5"></textarea></label>
            <button type="submit">Save Advanced Lab settings</button>
          </form>
          <p id="settingsStatus" class="muted"></p>
        </details>
      </aside>
      <main class="main">
        <section class="hero">
          <div class="hero-copy">
            <h2>Thin-client ops console for RV101 and browser harness</h2>
            <p>Jetson stays the HUD authority and skill runtime. The browser path is a secondary debug harness, not a separate product surface.</p>
          </div>
          <div class="hero-actions">
            <a href="/preview/latest/live.mjpg" target="_blank" rel="noreferrer">Open sensor preview</a>
            <a href="/simulator" target="_blank" rel="noreferrer">Open browser harness</a>
            <a href="/health" target="_blank" rel="noreferrer">Health JSON</a>
          </div>
        </section>
        <section class="preview-grid">
          <div class="panel preview-panel">
            <div class="panel-head">
              <h2>Preview</h2>
              <span id="latestSessionBadge" class="badge">waiting</span>
            </div>
            <img id="previewImage" src="/preview/latest/live.mjpg" alt="Jetson preview with bbox">
          </div>
          <div class="panel product-guide-panel">
            <h2>Product Contract</h2>
            <p class="muted">Keep the visible ops loop narrow: live health, sessions, sensor preview, skill trace, and HUD scene. Fallback routers and manual shells stay in Advanced Lab.</p>
          </div>
        </section>
        <section class="content-grid">
          <div class="panel">
            <div class="panel-head">
              <h2>Sessions</h2>
              <span id="sessionCount" class="badge">0</span>
            </div>
            <div id="sessionList" class="session-list"></div>
          </div>
          <div class="panel">
            <div class="panel-head">
              <h2>Selected session</h2>
              <span id="selectedSessionId" class="badge">none</span>
            </div>
            <p class="muted">Product-visible session state only. Manual shell changes and typed command injection are closed under Advanced Lab.</p>
            <div id="sessionDetails" class="detail-grid"></div>
            <div class="panel-section">
              <div class="panel-head panel-subhead">
                <h3>Skill trace</h3>
                <span id="skillTraceBadge" class="badge">0</span>
              </div>
              <div id="skillTrace" class="log-list"></div>
            </div>
            <div class="panel-section">
              <div class="panel-head panel-subhead">
                <h3>HUD mirror</h3>
                <span id="hudSceneBadge" class="badge">idle</span>
              </div>
              <div id="hudPreview" class="hud-preview-empty">Waiting for a HUD scene from the selected session.</div>
              <div id="hudDiagnostics" class="hud-diagnostics"></div>
            </div>
            <details class="advanced-rails session-lab">
              <summary>Advanced Lab: manual session controls and raw traces</summary>
              <p class="muted">Use only when intentionally probing backend behavior. These controls are not part of the product UX.</p>
              <div class="stack-form compact">
                <label>Capability shell (advanced)
                  <select id="manualMode">
                    <option value="standby">standby</option>
                    <option value="scene_monitor">scene_monitor</option>
                    <option value="visual_assistant">visual_assistant</option>
                    <option value="focus_bubble">focus_bubble</option>
                    <option value="ar_radar">ar_radar</option>
                    <option value="alert_burst">alert_burst</option>
                    <option value="traffic_count">traffic_count</option>
                  </select>
                </label>
                <button id="applyModeButton" type="button">Apply shell</button>
                <label>Inject typed command<textarea id="manualCommand" rows="3" placeholder="tim nguoi mac ao vang"></textarea></label>
                <button id="sendCommandButton" type="button">Send typed command</button>
              </div>
              <div class="panel-section">
                <div class="panel-head panel-subhead">
                  <h3>Voice timeline</h3>
                  <span class="badge">auto</span>
                </div>
                <div id="voiceTimeline" class="log-list"></div>
              </div>
              <div class="panel-section">
                <div class="panel-head panel-subhead">
                  <h3>Detections and telemetry</h3>
                </div>
                <pre id="detectionJson" class="code-box"></pre>
              </div>
              <div class="panel-section">
                <div class="panel-head panel-subhead">
                  <h3>Session log tail</h3>
                </div>
                <div id="sessionLogTail" class="log-list"></div>
              </div>
            </details>
          </div>
        </section>
      </main>
    </div>
    <script src="/admin-static/dashboard.js?v=20260424-ops-cleanup"></script>
  </body>
</html>"""


def build_simulator_page() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>Rokid Browser Debug Harness</title>
    <meta name="theme-color" content="#03110b">
    <link rel="stylesheet" href="/admin-static/simulator.css?v=20260424-browser-harness15">
  </head>
  <body>
    <div id="simApp" class="sim-app">
      <header class="sim-topbar">
        <div>
          <div class="sim-brand">Rokid Browser Debug Harness</div>
          <div id="secureHint" class="sim-subtitle">Secondary thin-client harness. Keep behavior aligned with RV101, including portrait capture and glasses-like frame pacing.</div>
        </div>
        <div class="sim-top-actions">
          <span id="connectionBadge" class="sim-pill warn">offline</span>
          <a class="sim-link" href="/dashboard" target="_blank" rel="noreferrer">Ops console</a>
        </div>
      </header>

      <section class="sim-quick-bar">
        <div class="sim-quick-copy">
          <strong>Attach media from here</strong>
          <small>Tap once to grant camera + mic, then only use lower controls when tuning capture or testing advanced shell rails.</small>
        </div>
        <div class="sim-button-row">
          <button id="startButton" type="button">Start harness</button>
          <button id="stopButton" type="button" class="secondary">Stop</button>
        </div>
        <p id="captureStatus" class="sim-muted">Waiting for user gesture.</p>
      </section>

      <section class="sim-mirror-shell">
        <div class="sim-mirror-head">
          <div>
            <div class="sim-mirror-title">Glasses HUD mirror</div>
            <div class="sim-mirror-subtitle">Mirror the RV101 contract: center mostly clear, compact top chips, upper-right target gallery, and a lower-safe answer strip.</div>
          </div>
          <span class="sim-pill">rokid_hud_v1</span>
        </div>

        <main class="sim-stage-shell">
          <section class="sim-stage">
            <video id="cameraPreview" class="sim-camera" playsinline autoplay muted></video>
            <div class="sim-vignette"></div>
            <div class="sim-stage-guides" aria-hidden="true">
              <div class="sim-guide sim-guide-top">top chips</div>
              <div class="sim-guide sim-guide-gallery">target gallery</div>
              <div class="sim-guide sim-guide-lower">lower-safe answer</div>
            </div>
            <div id="hudLayer" class="hud-layer">
              <div id="hudTopCenter" class="hud-top-center"></div>
              <div id="hudGallery" class="hud-gallery"></div>
              <div id="hudMarker" class="hud-marker hidden"></div>
              <div id="hudLowerStrip" class="hud-lower-strip"></div>
            </div>
          </section>
        </main>
      </section>

      <section class="sim-glasses-diagnostics">
        <div class="sim-card">
          <span class="sim-label">Session</span>
          <strong id="sessionLabel">none</strong>
        </div>
        <div class="sim-card">
          <span class="sim-label">Voice state</span>
          <strong id="speechLabel">idle</strong>
          <small id="speechHint">No voice state yet</small>
        </div>
        <div class="sim-card">
          <span class="sim-label">Perception</span>
          <strong id="visionLabel">waiting</strong>
          <small id="visionHint">No perception updates yet</small>
        </div>
        <div class="sim-card">
          <span class="sim-label">Shell debug rail</span>
          <strong id="modeLabel">standby</strong>
          <small>Advanced only</small>
        </div>
        <div class="sim-card sim-preview-card">
          <div class="sim-inset-head">
            <span>Jetson sensor preview</span>
            <span id="fpsLabel">0 fps</span>
          </div>
          <img id="jetsonPreview" src="/preview/latest/live.mjpg" alt="Jetson sensor preview">
        </div>
      </section>

      <details class="sim-controls" open>
        <summary>Harness settings and trace</summary>
        <div class="sim-controls-grid">
          <section class="sim-panel">
            <h2>Capture harness</h2>
            <label>Camera facing
              <select id="cameraFacing">
                <option value="environment">environment</option>
                <option value="user">user</option>
              </select>
            </label>
            <label>Resolution
              <select id="videoPreset">
                <option value="720x960">720 x 960 (glasses-like default)</option>
                <option value="540x720">540 x 720 (lighter)</option>
                <option value="960x1280">960 x 1280 (higher detail)</option>
              </select>
            </label>
            <label>Frame rate
              <select id="frameRate">
                <option value="15" selected>15 fps (glasses-like default)</option>
                <option value="12">12 fps (low-load debug)</option>
                <option value="18">18 fps</option>
                <option value="24">24 fps</option>
              </select>
            </label>
            <label class="inline-check"><input id="enableVideo" type="checkbox" checked>Publish camera</label>
            <label class="inline-check"><input id="enableAudio" type="checkbox" checked>Publish microphone</label>
            <label>Advanced shell override
              <select id="modeSelect">
                <option value="standby">standby</option>
                <option value="scene_monitor">scene_monitor</option>
                <option value="traffic_count">traffic_count</option>
                <option value="visual_assistant">visual_assistant</option>
                <option value="focus_bubble">focus_bubble</option>
                <option value="alert_burst">alert_burst</option>
                <option value="ar_radar">ar_radar</option>
              </select>
            </label>
            <p class="sim-muted">Default browser capture now mirrors the glasses loop more closely: portrait framing at 15 fps. Keep shell override for targeted debugging only. The product path remains Jetson intent routing plus thin HUD updates.</p>
          </section>

          <section class="sim-panel">
            <h2>Typed command</h2>
            <label>Inject text directly into the Jetson skill path
              <textarea id="manualCommand" rows="3" placeholder="Tìm người áo vàng đeo kính"></textarea>
            </label>
            <div class="sim-button-row">
              <button id="sendCommandButton" type="button">Send typed command</button>
              <button id="applyModeButton" type="button" class="secondary">Apply shell</button>
            </div>
            <p class="sim-muted">Use this to exercise Jetson skills quickly. Treat shell override as an advanced debug rail, not the product UX.</p>
          </section>

          <section class="sim-panel">
            <h2>Selected target</h2>
            <div id="selectedTarget" class="sim-empty">No selected target yet.</div>
          </section>
        </div>
        <section class="sim-panel wide">
          <div class="sim-panel-head">
            <h2>Skill trace</h2>
            <span id="traceBadge" class="sim-pill">0</span>
          </div>
          <div id="skillTrace" class="sim-log-list"></div>
        </section>
      </details>
    </div>
    <script src="/admin-static/simulator.js?v=20260424-browser-harness15"></script>
  </body>
</html>"""


def simulator_page_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
