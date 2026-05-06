package com.example.cxrservicedemo.videostream

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import android.util.Range
import android.view.KeyEvent
import android.view.Surface
import android.view.View
import android.view.WindowManager
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.example.cxrservicedemo.mousehand.telemetry.MouseHandTelemetryCollector
import com.example.cxrservicedemo.mousehand.telemetry.MouseHandTelemetrySnapshot
import com.example.cxrservicedemo.videostream.debug.VideoStreamDebugLogger
import com.example.cxrservicedemo.videostream.transport.JetsonControlClient
import com.example.cxrservicedemo.videostream.transport.JetsonControlListener
import com.example.cxrservicedemo.videostream.transport.JetsonControlStatus
import com.example.cxrservicedemo.videostream.transport.JetsonMediaStreamClient
import com.example.cxrservicedemo.videostream.transport.JetsonNodeTelemetry
import com.example.cxrservicedemo.videostream.transport.JetsonSessionAccept
import com.example.cxrservicedemo.videostream.transport.JetsonHudScene
import com.example.cxrservicedemo.videostream.transport.JetsonSpeechState
import com.example.cxrservicedemo.videostream.transport.JetsonVideoStatus
import com.example.cxrservicedemo.videostream.transport.JetsonVisionResult
import com.example.cxrservicedemo.videostream.transport.VideoStreamHello
import com.example.cxrservicedemo.videostream.transport.VideoStreamProfile
import com.example.rokidvideostream.R
import com.example.rokidvideostream.databinding.ActivityVideoStreamBinding
import org.json.JSONObject
import java.util.concurrent.ExecutorService

class VideoStreamActivity : AppCompatActivity(), JetsonControlListener {

    private lateinit var binding: ActivityVideoStreamBinding
    private lateinit var cameraExecutor: ExecutorService
    private lateinit var streamExecutor: ExecutorService
    private lateinit var telemetryCollector: MouseHandTelemetryCollector
    private lateinit var debugLogger: VideoStreamDebugLogger
    private lateinit var controlClient: JetsonControlClient
    private lateinit var mediaClient: JetsonMediaStreamClient
    private lateinit var audioCoordinator: AudioStreamingCoordinator
    private lateinit var hudRenderer: Rv101HudRenderer
    private val mainHandler = Handler(Looper.getMainLooper())
    private val sessionController = GlassesSessionController()
    private val cameraPermission = Manifest.permission.CAMERA
    private val audioPermission = Manifest.permission.RECORD_AUDIO

    private var surfacePipeline: SurfaceVideoStreamPipeline? = null
    private var shouldRunCamera = false
    private var shouldRunAudio = false
    private var encoderWidth = 0
    private var encoderHeight = 0
    private var activeProfile = MEDIUM_PROFILE
    private var jetsonHost = DEFAULT_JETSON_HOST
    private var controlPort = DEFAULT_CONTROL_PORT
    private var selectedMode = DEFAULT_MODE
    private var latestSession: JetsonSessionAccept? = null
    private var latestNodeTelemetry: JetsonNodeTelemetry? = null
    private var latestSpeechState = JetsonSpeechState(
        listening = false,
        taskLabel = null,
        transcriptHint = null,
        stateLabel = "idle"
    )
    private var latestVisionResult: JetsonVisionResult? = null
    private var latestHudScene: JetsonHudScene? = null
    private var latestControlStatus = JetsonControlStatus(false, "--")
    private var latestVideoStatus = JetsonVideoStatus(false, "--", 0, 0, 0, 0, 0)
    private var latestTelemetry: MouseHandTelemetrySnapshot? = null
    private var latestRotationDegrees = 0
    private var lastStatusUpdateTimestampMs = 0L
    private var lastTelemetrySampleTimestampMs = 0L
    private var lastTelemetrySendTimestampMs = 0L
    private var lastDebugLogTimestampMs = 0L
    private var lastEncodeStatSendTimestampMs = 0L
    private var lastHudRenderPostTimestampMs = 0L
    private var lastSpeechHudRenderTimestampMs = 0L
    private var lastHudEventLogTimestampMs = 0L
    private var lastHudEventSignature: String? = null
    private var lastHudRenderLogTimestampMs = 0L
    private var lastHudRenderSignature: String? = null
    private var lastMeaningfulHudSceneTimestampMs = 0L
    private var stableSpeechTranscriptHint: String? = null
    private var stableSpeechTaskLabel: String? = null
    private var stableSpeechUpdatedAtMs = 0L
    private var analyzerDrops = 0L
    private var developerPanelVisible = false
    private var heldHudPresentation: HudPresentation? = null
    private val telemetryRuntime = StreamTelemetryRuntime()

    private val heartbeatRunnable = object : Runnable {
        override fun run() {
            if (!shouldRunCamera && !shouldRunAudio) return
            if (!latestControlStatus.connected) {
                controlClient.start()
            }
            controlClient.sendPing()
            val now = SystemClock.uptimeMillis()
            val telemetry = sampleTelemetryIfDue(now, force = developerPanelVisible)
            maybeSendTelemetry(now, telemetry, force = false)
            maybeSendAudioStats(now)
            if (needsBackgroundHudRefresh()) {
                renderHud()
            }
            mainHandler.postDelayed(this, HEARTBEAT_INTERVAL_MS)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        RokidGlassWindowChrome.configure(window)
        binding = ActivityVideoStreamBinding.inflate(layoutInflater)
        setContentView(binding.root)
        hudRenderer = Rv101HudRenderer(
            context = this,
            binding = binding,
            layoutInflater = layoutInflater
        )
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        configureTargets(intent)
        cameraExecutor = newNamedSingleThreadExecutor(
            name = "rokid-camera",
            processPriority = android.os.Process.THREAD_PRIORITY_DISPLAY
        )
        streamExecutor = newNamedSingleThreadExecutor(
            name = "rokid-stream",
            processPriority = android.os.Process.THREAD_PRIORITY_URGENT_DISPLAY
        )
        telemetryCollector = MouseHandTelemetryCollector(this)
        debugLogger = VideoStreamDebugLogger(this)
        latestTelemetry = telemetryCollector.sample()

        controlClient = JetsonControlClient(
            host = jetsonHost,
            port = controlPort,
            deviceId = deviceId(),
            appVersion = appVersionName(),
            initialSelectedMode = selectedMode,
            listener = this
        )
        mediaClient = JetsonMediaStreamClient(
            deviceId = deviceId(),
            appVersion = appVersionName()
        )
        audioCoordinator = AudioStreamingCoordinator(
            applicationContext = applicationContext,
            deviceId = deviceId(),
            appVersion = appVersionName(),
            controlClient = controlClient,
            callbacks = object : AudioStreamingCoordinator.Callbacks {
                override fun onStreamingStateChanged(streaming: Boolean) {
                    latestSpeechState = latestSpeechState.copy(
                        listening = streaming,
                        stateLabel = if (streaming) "always_on" else "idle"
                    )
                    maybePostHudRender(force = true, headline = if (streaming) "Voice live" else null)
                }
            }
        )

        bindStaticUiHandlers()
        renderHud(force = true, headline = "Starting Rokid Vision")
        if (!hasCameraPermission() || !hasAudioPermission()) {
            requestRuntimePermissions()
        }
    }

    override fun onResume() {
        super.onResume()
        shouldRunCamera = true
        shouldRunAudio = true
        controlClient.start()
        mainHandler.removeCallbacks(heartbeatRunnable)
        mainHandler.post(heartbeatRunnable)
        if (hasCameraPermission()) {
            startCamera()
        }
        if (hasAudioPermission()) {
            startAudioStreaming()
        }
    }

    override fun onPause() {
        mainHandler.removeCallbacks(heartbeatRunnable)
        super.onPause()
    }

    override fun onStop() {
        shouldRunCamera = false
        shouldRunAudio = false
        stopCamera()
        stopAudioStreaming()
        mediaClient.stop()
        controlClient.stop()
        super.onStop()
    }

    override fun onDestroy() {
        stopCamera()
        stopAudioStreaming()
        mediaClient.close()
        audioCoordinator.close()
        controlClient.close()
        debugLogger.close()
        cameraExecutor.shutdown()
        streamExecutor.shutdown()
        super.onDestroy()
    }

    override fun onControlStatus(status: JetsonControlStatus) {
        latestControlStatus = status
        val transition = sessionController.onControlStatus(status)
        latestSession = transition.nextSession
        if (transition.shouldClearHud) {
            latestVisionResult = null
            if (transition.shouldResetSpeech) {
                latestSpeechState = latestSpeechState.copy(taskLabel = null, transcriptHint = null, stateLabel = "idle")
            }
            clearHudTransientState(clearSpeechState = true)
        }
        if (transition.shouldStopMedia) {
            stopCamera()
            stopAudioStreaming()
            mediaClient.stop()
            latestVideoStatus = mediaClient.videoStatus()
        }
        runOnUiThread { renderHud(force = true) }
    }

    override fun onSessionAccepted(session: JetsonSessionAccept) {
        val transition = sessionController.onSessionAccepted(session)
        val previousSessionId = transition.previousSession?.sessionId
        latestSession = transition.nextSession
        latestVisionResult = null
        if (transition.shouldClearHud) {
            clearHudTransientState(clearSpeechState = true)
        }
        latestSpeechState = JetsonSpeechState(
            listening = audioCoordinator.isStreaming(),
            taskLabel = null,
            transcriptHint = null,
            stateLabel = if (audioCoordinator.isStreaming()) "always_on" else "idle"
        )
        controlClient.sendStreamLog(
            level = "info",
            event = "session_accepted",
            message = "session ready on jetson",
            fields = JSONObject()
                .put("sessionId", session.sessionId)
                .put("videoHost", session.videoHost)
                .put("videoPort", session.videoPort)
        )
        if (transition.shouldStopMedia) {
            mediaClient.stop()
            latestVideoStatus = mediaClient.videoStatus()
        }
        if (hasCameraPermission() && shouldRunCamera) {
            startCamera()
        }
        if (hasAudioPermission() && shouldRunAudio) {
            if (audioCoordinator.isStreaming() && transition.transportChanged) {
                controlClient.sendStreamLog(
                    level = "info",
                    event = "audio_session_restart",
                    message = "restarting dedicated audio socket for new session",
                    fields = JSONObject()
                        .put("previousSessionId", previousSessionId ?: "")
                        .put("nextSessionId", session.sessionId)
                        .put("audioHost", session.audioHost)
                        .put("audioPort", session.audioPort)
                )
                stopAudioStreaming()
            }
            startAudioStreaming()
        }
        runOnUiThread { renderHud(force = true, headline = "Jetson ready") }
    }

    override fun onVisionResult(result: JetsonVisionResult) {
        latestVisionResult = result
        rememberCurrentHudPresentation()
        reportHudEvent(
            kind = "vision_result",
            primaryText = result.headline,
            secondaryText = result.detailLines.firstOrNull()
        )
        maybePostHudRender()
    }

    override fun onNodeTelemetry(telemetry: JetsonNodeTelemetry) {
        latestNodeTelemetry = telemetry
        maybePostHudRender()
    }

    override fun onSpeechState(state: JetsonSpeechState) {
        val now = SystemClock.uptimeMillis()
        val stateLabelChanged = state.stateLabel != latestSpeechState.stateLabel
        val taskLabelChanged = state.taskLabel != latestSpeechState.taskLabel
        val transcriptChanged = state.transcriptHint != latestSpeechState.transcriptHint
        val transcriptRequiresImmediateRender =
            transcriptChanged && (
                state.transcriptHint.isNullOrBlank() ||
                    latestSpeechState.transcriptHint.isNullOrBlank() ||
                    now - lastSpeechHudRenderTimestampMs >= SPEECH_HUD_FORCE_RENDER_INTERVAL_MS
                )
        val shouldForceRender = stateLabelChanged || taskLabelChanged || transcriptRequiresImmediateRender
        rememberStableSpeechState(state, now)
        latestSpeechState = state
        rememberCurrentHudPresentation()
        reportHudEvent(
            kind = "speech_state",
            primaryText = state.transcriptHint,
            secondaryText = state.taskLabel ?: state.stateLabel
        )
        if (shouldForceRender) {
            lastSpeechHudRenderTimestampMs = now
        }
        maybePostHudRender(force = shouldForceRender)
    }

    override fun onHudScene(scene: JetsonHudScene) {
        val activeSessionId = latestSession?.sessionId
        if (!activeSessionId.isNullOrBlank() && !scene.sessionId.isNullOrBlank() && scene.sessionId != activeSessionId) {
            controlClient.sendStreamLog(
                level = "warn",
                event = "hud_scene_ignored",
                message = "ignored stale hud scene from different session",
                fields = JSONObject()
                    .put("activeSessionId", activeSessionId)
                    .put("sceneSessionId", scene.sessionId ?: "")
                    .put("sceneId", scene.sceneId)
            )
            return
        }
        latestHudScene = scene
        if (HudPresentationRuntime.hasMeaningfulScene(scene)) {
            lastMeaningfulHudSceneTimestampMs = SystemClock.uptimeMillis()
        }
        rememberCurrentHudPresentation()
        reportHudEvent(
            kind = "hud_scene",
            primaryText = scene.answerText ?: scene.statusText,
            secondaryText = scene.taskChip ?: scene.micChip
        )
        maybePostHudRender()
    }

    override fun onControlError(message: String) {
        Log.w(TAG, message)
        runOnUiThread { renderHud(force = true, headline = message) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        configureTargets(intent)
        renderHud(force = true, headline = "VPN target updated")
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) return
        WindowInsetsControllerCompat(window, binding.root).hide(WindowInsetsCompat.Type.systemBars())
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        val handled = GlassesInputController.handleKeyDown(
            keyCode = keyCode,
            developerPanelVisible = developerPanelVisible,
            actions = object : GlassesInputController.Actions {
                override fun toggleDeveloperPanel() {
                    this@VideoStreamActivity.toggleDeveloperPanel()
                }

                override fun hideDeveloperPanel() {
                    this@VideoStreamActivity.hideDeveloperPanel()
                }

                override fun toggleProfile() {
                    this@VideoStreamActivity.toggleProfile()
                }

                override fun finishActivity() {
                    finish()
                }
            }
        )
        if (handled) {
            return true
        }
        return super.onKeyDown(keyCode, event)
    }

    private fun bindStaticUiHandlers() {
        binding.root.setOnLongClickListener {
            toggleDeveloperPanel()
            true
        }
    }

    private fun toggleDeveloperPanel() {
        developerPanelVisible = !developerPanelVisible
        renderHud(force = true, headline = if (developerPanelVisible) "Developer panel on" else "Developer panel off")
    }

    private fun hideDeveloperPanel() {
        developerPanelVisible = false
        renderHud(force = true, headline = "Developer panel off")
    }

    private fun startCamera() {
        if (!shouldRunCamera || !hasCameraPermission() || isDestroyed || isFinishing) return
        if (!latestControlStatus.connected || latestSession == null) {
            renderHud(force = true, headline = "Waiting for Jetson")
            return
        }
        if (surfacePipeline != null) return

        val displayRotation = binding.root.display?.rotation ?: Surface.ROTATION_0
        val pipeline = SurfaceVideoStreamPipeline(
            context = this,
            profile = activeProfile,
            displayRotation = displayRotation,
            cameraExecutor = cameraExecutor,
            listener = object : SurfaceVideoStreamPipeline.Listener {
                override fun onStarted(
                    actualWidth: Int,
                    actualHeight: Int,
                    rotationDegrees: Int,
                    fpsRange: Range<Int>?
                ) {
                    encoderWidth = actualWidth
                    encoderHeight = actualHeight
                    latestRotationDegrees = rotationDegrees
                    resetPerformanceStats()
                    controlClient.sendStreamLog(
                        level = "info",
                        event = "camera_started",
                        message = "camera2 surface pipeline started",
                        fields = JSONObject()
                            .put("width", actualWidth)
                            .put("height", actualHeight)
                            .put("requestedWidth", activeProfile.width)
                            .put("requestedHeight", activeProfile.height)
                            .put("minFps", fpsRange?.lower ?: activeProfile.minCameraFps)
                            .put("fps", fpsRange?.upper ?: activeProfile.fps)
                            .put("previewDisabled", true)
                            .put("pipeline", "camera2_surface")
                    )
                    runOnUiThread { renderHud(force = true, headline = "Camera live") }
                }

                override fun onEncodedSample(sample: EncodedVideoSample) {
                    streamExecutor.execute { handleEncodedSample(sample) }
                }

                override fun onError(message: String, cause: Throwable?) {
                    Log.e(TAG, message, cause)
                    controlClient.sendStreamLog(
                        level = "error",
                        event = "camera_surface_error",
                        message = cause?.message ?: message,
                        fields = JSONObject().put("pipeline", "camera2_surface")
                    )
                    runOnUiThread { renderHud(force = true, headline = "Camera error") }
                }
            }
        )
        surfacePipeline = pipeline
        renderHud(force = true, headline = "Starting camera")
        try {
            pipeline.start()
        } catch (error: Exception) {
            surfacePipeline = null
            Log.e(TAG, "Failed to start camera surface pipeline", error)
            controlClient.sendStreamLog(
                level = "error",
                event = "camera_bind_failed",
                message = error.message ?: "camera surface start failed",
                fields = JSONObject()
                    .put("width", activeProfile.width)
                    .put("height", activeProfile.height)
                    .put("minFps", activeProfile.minCameraFps)
                    .put("fps", activeProfile.fps)
                    .put("pipeline", "camera2_surface")
            )
            renderHud(force = true, headline = "Camera bind failed")
        }
    }

    private fun stopCamera() {
        val hadActiveCamera =
            surfacePipeline != null ||
                encoderWidth > 0 ||
                encoderHeight > 0
        surfacePipeline?.close()
        surfacePipeline = null
        encoderWidth = 0
        encoderHeight = 0
        if (!hadActiveCamera) {
            return
        }
        controlClient.sendStreamLog(
            level = "info",
            event = "camera_stopped",
            message = "camera stopped"
        )
    }

    private fun handleEncodedSample(sample: EncodedVideoSample) {
        val session = latestSession
        if (session == null || !latestControlStatus.connected) {
            return
        }

        val now = SystemClock.uptimeMillis()
        latestRotationDegrees = normalizedRotation(latestRotationDegrees)
        telemetryRuntime.recordEncodedSample(sample)

        val hello = VideoStreamHello(
            sessionId = session.sessionId,
            mode = selectedMode,
            profile = activeProfile,
            width = sample.width,
            height = sample.height,
            rotationDegrees = latestRotationDegrees
        )

        val sendStartNs = System.nanoTime()
        val sent = mediaClient.sendVideoSample(session, hello, sample)
        val sendMs = ((System.nanoTime() - sendStartNs) / 1_000_000.0).toFloat()
        telemetryRuntime.recordSendDuration(sendMs)
        latestVideoStatus = mediaClient.videoStatus()
        if (!sent) {
            controlClient.sendStreamLog(
                level = "warn",
                event = "video_send_failed",
                message = "video sample send failed",
                fields = JSONObject()
                    .put("sequence", sample.sequence)
                    .put("payloadBytes", sample.payload.size)
            )
        }

        val telemetry = sampleTelemetryIfDue(now, force = false)
        maybeSendTelemetry(now, telemetry, force = false)
        val stats = surfacePipeline?.stats()
        if (stats != null) {
            maybeSendEncoderStats(now, stats)
            maybeAppendDebugLog(now, telemetry, stats)
        }
        if (developerPanelVisible && now - lastHudRenderPostTimestampMs >= HUD_RENDER_POST_INTERVAL_MS) {
            lastHudRenderPostTimestampMs = now
            runOnUiThread { renderHud() }
        }
    }

    private fun startAudioStreaming() {
        if (!hasAudioPermission() || !shouldRunAudio) {
            return
        }
        val session = latestSession ?: return
        if (!latestControlStatus.connected && !audioCoordinator.isStreaming()) {
            return
        }
        if (audioCoordinator.isStreaming() && audioCoordinator.activeSessionId() == session.sessionId) {
            return
        }
        if (audioCoordinator.isStreaming()) {
            stopAudioStreaming()
        }
        audioCoordinator.start(session)
        renderHud(force = true, headline = "Voice live")
    }

    private fun stopAudioStreaming() {
        audioCoordinator.stop()
        latestSpeechState = latestSpeechState.copy(listening = false, stateLabel = "idle")
    }

    private fun renderHud(force: Boolean = false, headline: String? = null) {
        val now = SystemClock.uptimeMillis()
        if (!force && now - lastStatusUpdateTimestampMs < STATUS_UPDATE_INTERVAL_MS) return
        lastStatusUpdateTimestampMs = now

        val telemetry = latestTelemetry ?: telemetryCollector.sample().also { latestTelemetry = it }
        latestVideoStatus = mediaClient.videoStatus()
        val encoderStats = surfacePipeline?.stats()
        val node = latestNodeTelemetry

        val presentation = currentHudPresentation()
        val renderSnapshot = hudRenderer.render(
            headline = headline,
            presentation = presentation,
            voiceScene = currentHudScene(),
            speechState = latestSpeechState,
            controlStatus = latestControlStatus,
            videoStatus = latestVideoStatus,
            sessionActive = latestSession != null,
            audioStreaming = audioCoordinator.isStreaming(),
            developerPanelVisible = developerPanelVisible,
        )
        maybeLogHudRender(snapshot = renderSnapshot, presentation = presentation)
        renderDeveloperPanel(telemetry, node, encoderStats)
    }

    private fun currentHudScene(): JetsonHudScene? {
        val scene = latestHudScene ?: return null
        val activeSessionId = latestSession?.sessionId ?: return scene.takeIf { scene.sessionId.isNullOrBlank() }
        return if (scene.sessionId.isNullOrBlank() || scene.sessionId == activeSessionId) {
            scene
        } else {
            null
        }
    }

    private fun currentHudPresentation(): HudPresentation? {
        val livePresentation = resolveLiveHudPresentation()
        if (livePresentation != null) {
            return livePresentation
        }
        if (!latestControlStatus.connected || latestSession == null) {
            return null
        }
        val activeSessionId = latestSession?.sessionId ?: return null
        val heldPresentation = heldHudPresentation
        if (
            heldPresentation == null ||
            heldPresentation.sessionId != activeSessionId ||
            !isHeldHudFresh(heldPresentation)
        ) {
            heldHudPresentation = null
            return null
        }
        return heldPresentation
    }

    private fun resolveLiveHudPresentation(): HudPresentation? {
        val voiceScene = currentHudScene()
        return HudPresentationRuntime.resolvePresentation(
            activeSessionId = latestSession?.sessionId,
            speechState = latestSpeechState,
            voiceScene = voiceScene,
            visionResult = latestVisionResult,
            liveTranscript = effectiveSpeechTranscriptHint(latestSpeechState),
            effectiveSpeechTaskLabel = effectiveSpeechTaskLabel(latestSpeechState),
            meaningfulSceneActive =
                HudPresentationRuntime.hasMeaningfulScene(voiceScene) &&
                    SystemClock.uptimeMillis() - lastMeaningfulHudSceneTimestampMs <= HUD_SCENE_PRIORITY_TTL_MS,
            updatedAtMs = SystemClock.uptimeMillis()
        )
    }

    private fun rememberStableSpeechState(state: JetsonSpeechState, now: Long) {
        val incomingTranscript = HudPresentationRuntime.sanitizeText(state.transcriptHint)
        val liveSpeechState = HudPresentationRuntime.isLiveSpeechState(state)
        if (!incomingTranscript.isNullOrBlank() && liveSpeechState) {
            stableSpeechTranscriptHint = HudPresentationRuntime.chooseStableSpeechTranscript(
                previous = stableSpeechTranscriptHint,
                incoming = incomingTranscript
            )
            stableSpeechTaskLabel = HudPresentationRuntime.normalizeText(state.taskLabel)
            stableSpeechUpdatedAtMs = now
            return
        }
        if (!state.listening && now - stableSpeechUpdatedAtMs > SPEECH_TRANSCRIPT_HOLD_MS) {
            stableSpeechTranscriptHint = null
            stableSpeechTaskLabel = null
            stableSpeechUpdatedAtMs = 0L
        }
    }

    private fun effectiveSpeechTranscriptHint(state: JetsonSpeechState): String? {
        val liveTranscript = HudPresentationRuntime.sanitizeText(state.transcriptHint)
        if (!liveTranscript.isNullOrBlank()) {
            return liveTranscript
        }
        val now = SystemClock.uptimeMillis()
        val stableTranscript = stableSpeechTranscriptHint ?: return null
        return stableTranscript.takeIf {
            now - stableSpeechUpdatedAtMs <= SPEECH_TRANSCRIPT_HOLD_MS &&
                (state.listening || HudPresentationRuntime.isLiveSpeechState(state))
        }
    }

    private fun effectiveSpeechTaskLabel(state: JetsonSpeechState): String? {
        val taskLabel = HudPresentationRuntime.normalizeText(state.taskLabel)
        if (!taskLabel.isNullOrBlank()) {
            return taskLabel
        }
        val now = SystemClock.uptimeMillis()
        return stableSpeechTaskLabel?.takeIf {
            now - stableSpeechUpdatedAtMs <= SPEECH_TRANSCRIPT_HOLD_MS &&
                (state.listening || HudPresentationRuntime.isLiveSpeechState(state))
        }
    }

    private fun rememberCurrentHudPresentation() {
        val activeSessionId = latestSession?.sessionId
        if (!latestControlStatus.connected || activeSessionId.isNullOrBlank()) {
            return
        }
        val livePresentation = resolveLiveHudPresentation() ?: return
        if (!HudPresentationRuntime.shouldHoldPresentation(livePresentation)) {
            return
        }
        heldHudPresentation = livePresentation.copy(sessionId = activeSessionId, updatedAtMs = SystemClock.uptimeMillis())
    }

    private fun isHeldHudFresh(presentation: HudPresentation): Boolean =
        SystemClock.uptimeMillis() - presentation.updatedAtMs <= HUD_PRESENTATION_HOLD_MS

    private fun reportHudEvent(kind: String, primaryText: String?, secondaryText: String?) {
        val primary = HudPresentationRuntime.normalizeText(primaryText).orEmpty().take(120)
        val secondary = HudPresentationRuntime.normalizeText(secondaryText).orEmpty().take(80)
        if (shouldSkipHudEvent(kind, primary, secondary)) {
            return
        }
        val signature = "$kind|$primary|$secondary"
        val now = SystemClock.uptimeMillis()
        if (signature == lastHudEventSignature && now - lastHudEventLogTimestampMs < HUD_EVENT_LOG_INTERVAL_MS) {
            return
        }
        lastHudEventSignature = signature
        lastHudEventLogTimestampMs = now
        controlClient.sendStreamLog(
            level = "info",
            event = "hud_event_received",
            message = "glasses applied hud payload",
            fields = JSONObject()
                .put("kind", kind)
                .put("primaryText", primary)
                .put("secondaryText", secondary)
                .put("sessionId", latestSession?.sessionId ?: "")
        )
    }

    private fun shouldSkipHudEvent(kind: String, primary: String, secondary: String): Boolean =
        when (kind) {
            "speech_state" -> primary.isBlank() && secondary.equals("live caption", ignoreCase = true)
            "vision_result" -> primary.isBlank() || HudPresentationRuntime.isGenericText(primary)
            else -> false
        }

    private fun maybeLogHudRender(snapshot: Rv101HudRenderSnapshot, presentation: HudPresentation?) {
        val answer = presentation?.answerText.orEmpty().take(120)
        val task = presentation?.taskLabel.orEmpty().take(80)
        val signature = listOf(
            snapshot.centerVisible,
            snapshot.assistantVisible,
            snapshot.candidateVisible,
            snapshot.candidateCount,
            snapshot.sceneCandidateCount,
            snapshot.candidateThumbPayloadCount,
            snapshot.candidateThumbDecodedCount,
            snapshot.markerVisible,
            answer,
            task,
            presentation?.sourceLabel.orEmpty()
        ).joinToString("|")
        val now = SystemClock.uptimeMillis()
        if (signature == lastHudRenderSignature && now - lastHudRenderLogTimestampMs < HUD_RENDER_LOG_INTERVAL_MS) {
            return
        }
        lastHudRenderSignature = signature
        lastHudRenderLogTimestampMs = now
        controlClient.sendStreamLog(
            level = "info",
            event = "hud_render_applied",
            message = "glasses rendered hud state",
            fields = JSONObject()
                .put("centerVisible", snapshot.centerVisible)
                .put("assistantVisible", snapshot.assistantVisible)
                .put("answerText", answer)
                .put("taskLabel", task)
                .put("metaText", presentation?.metaText.orEmpty().take(120))
                .put("source", presentation?.sourceLabel ?: "")
                .put("candidateVisible", snapshot.candidateVisible)
                .put("candidateCount", snapshot.candidateCount)
                .put("sceneCandidateCount", snapshot.sceneCandidateCount)
                .put("candidateThumbPayloadCount", snapshot.candidateThumbPayloadCount)
                .put("candidateThumbDecodedCount", snapshot.candidateThumbDecodedCount)
                .put("markerVisible", snapshot.markerVisible)
                .put("sessionId", latestSession?.sessionId ?: "")
        )
    }

    private fun clearHudTransientState(clearSpeechState: Boolean) {
        latestHudScene = null
        heldHudPresentation = null
        lastMeaningfulHudSceneTimestampMs = 0L
        hudRenderer.clearTransientState()
        if (clearSpeechState) {
            stableSpeechTranscriptHint = null
            stableSpeechTaskLabel = null
            stableSpeechUpdatedAtMs = 0L
        }
    }

    private fun renderDeveloperPanel(
        telemetry: MouseHandTelemetrySnapshot,
        node: JetsonNodeTelemetry?,
        encoderStats: VideoEncoderRuntimeStats?
    ) {
        hudRenderer.renderDeveloperPanel(
            visible = developerPanelVisible,
            telemetryRuntime = telemetryRuntime,
            telemetry = telemetry,
            node = node,
            encoderStats = encoderStats,
            sessionId = latestSession?.sessionId,
            selectedMode = selectedMode,
            controlStatus = latestControlStatus,
            videoStatus = latestVideoStatus,
            activeProfile = activeProfile,
            analyzerDrops = analyzerDrops,
        )
    }

    private fun maybeSendTelemetry(
        nowTimestampMs: Long,
        telemetry: MouseHandTelemetrySnapshot,
        force: Boolean
    ) {
        if (!force && nowTimestampMs - lastTelemetrySendTimestampMs < TELEMETRY_SEND_INTERVAL_MS) return
        lastTelemetrySendTimestampMs = nowTimestampMs
        val videoStatus = mediaClient.videoStatus()
        controlClient.sendDeviceTelemetry(
            JSONObject(
                telemetryRuntime.buildDeviceTelemetryPayload(
                    telemetry = telemetry,
                    videoStatus = videoStatus,
                    activeProfile = activeProfile,
                    selectedMode = selectedMode,
                    controlConnected = latestControlStatus.connected,
                    audioStreaming = audioCoordinator.isStreaming(),
                )
            )
        )
    }

    private fun maybeSendEncoderStats(nowTimestampMs: Long, stats: VideoEncoderRuntimeStats) {
        if (nowTimestampMs - lastEncodeStatSendTimestampMs < ENCODER_STAT_SEND_INTERVAL_MS) return
        lastEncodeStatSendTimestampMs = nowTimestampMs
        controlClient.sendEncoderStats(
            JSONObject(
                telemetryRuntime.buildEncoderStatsPayload(
                    stats = stats,
                    activeProfile = activeProfile,
                    encoderWidth = encoderWidth,
                    encoderHeight = encoderHeight,
                    analyzerDrops = analyzerDrops,
                )
            )
        )
    }

    private fun maybeSendAudioStats(nowTimestampMs: Long) {
        audioCoordinator.maybeSendAudioStats(nowTimestampMs, ENCODER_STAT_SEND_INTERVAL_MS)
    }

    private fun maybeAppendDebugLog(
        nowTimestampMs: Long,
        telemetry: MouseHandTelemetrySnapshot,
        encoderStats: VideoEncoderRuntimeStats
    ) {
        if (!ENABLE_BACKGROUND_DEBUG_LOGS && !developerPanelVisible) return
        if (nowTimestampMs - lastDebugLogTimestampMs < DEBUG_LOG_INTERVAL_MS) return
        lastDebugLogTimestampMs = nowTimestampMs
        val node = latestNodeTelemetry
        val videoStatus = mediaClient.videoStatus()
        debugLogger.append(
            telemetryRuntime.buildDebugSnapshot(
                sessionId = latestSession?.sessionId,
                rotationDegrees = latestRotationDegrees,
                activeProfile = activeProfile,
                encoderWidth = encoderWidth,
                encoderHeight = encoderHeight,
                encoderStats = encoderStats,
                videoStatus = videoStatus,
                controlStatus = latestControlStatus,
                telemetry = telemetry,
                node = node,
                analyzerDrops = analyzerDrops,
            )
        )
    }

    private fun needsBackgroundHudRefresh(): Boolean =
        developerPanelVisible || (
            heldHudPresentation != null &&
                latestControlStatus.connected &&
                latestSession != null
            )

    private fun maybePostHudRender(force: Boolean = false, headline: String? = null) {
        val now = SystemClock.uptimeMillis()
        if (!force && now - lastHudRenderPostTimestampMs < STATUS_UPDATE_INTERVAL_MS) {
            return
        }
        lastHudRenderPostTimestampMs = now
        runOnUiThread { renderHud(force = force, headline = headline) }
    }

    private fun sampleTelemetryIfDue(
        nowTimestampMs: Long,
        force: Boolean
    ): MouseHandTelemetrySnapshot {
        if (
            force ||
            latestTelemetry == null ||
            nowTimestampMs - lastTelemetrySampleTimestampMs >= TELEMETRY_SAMPLE_INTERVAL_MS
        ) {
            latestTelemetry = telemetryCollector.sample()
            lastTelemetrySampleTimestampMs = nowTimestampMs
        }
        return latestTelemetry!!
    }

    private fun applyProfile(
        nextProfile: VideoStreamProfile,
        headline: String,
        event: String,
        message: String
    ) {
        if (activeProfile == nextProfile) return
        activeProfile = nextProfile
        controlClient.sendStreamLog(
            level = "info",
            event = event,
            message = message,
            fields = JSONObject()
                .put("profileLabel", activeProfile.label)
                .put("width", activeProfile.width)
                .put("height", activeProfile.height)
                .put("minFps", activeProfile.minCameraFps)
                .put("fps", activeProfile.fps)
                .put("bitrate", activeProfile.bitrate)
                .put("captureFps", telemetryRuntime.captureFps)
                .put("encodeFps", telemetryRuntime.encodeFps)
                .put("encodeMs", telemetryRuntime.encodeMs)
                .put("analyzerDrops", analyzerDrops)
        )
        if (shouldRunCamera) {
            stopCamera()
            startCamera()
        }
        renderHud(force = true, headline = headline)
    }

    private fun toggleProfile() {
        val currentIndex = PROFILE_CYCLE.indexOf(activeProfile).takeIf { it >= 0 } ?: 0
        applyProfile(
            nextProfile = PROFILE_CYCLE[(currentIndex + 1) % PROFILE_CYCLE.size],
            headline = "Profile ${PROFILE_CYCLE[(currentIndex + 1) % PROFILE_CYCLE.size].label}",
            event = "profile_switch",
            message = "switching stream profile"
        )
    }

    private fun configureTargets(intent: Intent?) {
        jetsonHost = intent?.getStringExtra(EXTRA_JETSON_HOST)?.trim()?.takeIf { it.isNotEmpty() }
            ?: DEFAULT_JETSON_HOST
        controlPort = intent?.getIntExtra(EXTRA_CONTROL_PORT, DEFAULT_CONTROL_PORT)
            ?.takeIf { it in 1..65535 }
            ?: DEFAULT_CONTROL_PORT
    }

    private fun resetPerformanceStats() {
        lastStatusUpdateTimestampMs = 0L
        lastTelemetrySampleTimestampMs = 0L
        lastTelemetrySendTimestampMs = 0L
        lastDebugLogTimestampMs = 0L
        lastEncodeStatSendTimestampMs = 0L
        analyzerDrops = 0L
        telemetryRuntime.reset()
        lastHudRenderSignature = null
        lastHudRenderLogTimestampMs = 0L
        hudRenderer.clearTransientState()
    }

    private fun hasCameraPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, cameraPermission) == PackageManager.PERMISSION_GRANTED

    private fun hasAudioPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, audioPermission) == PackageManager.PERMISSION_GRANTED

    private fun requestRuntimePermissions() {
        val permissions = buildList {
            if (!hasCameraPermission()) add(cameraPermission)
            if (!hasAudioPermission()) add(audioPermission)
        }
        if (permissions.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, permissions.toTypedArray(), REQUEST_RUNTIME_PERMISSIONS)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_RUNTIME_PERMISSIONS) {
            if (hasCameraPermission()) {
                startCamera()
            }
            if (hasAudioPermission()) {
                startAudioStreaming()
            }
            if (!hasCameraPermission()) {
                renderHud(force = true, headline = "Camera permission denied")
            }
            if (!hasAudioPermission()) {
                renderHud(force = true, headline = "Mic permission denied")
            }
        }
    }

    private fun deviceId(): String {
        val androidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
        val model = Build.MODEL ?: "rokid"
        return "$model-${androidId ?: "unknown"}"
    }

    private fun appVersionName(): String =
        try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "0.0.0"
        } catch (_: Exception) {
            "0.0.0"
        }

    private fun normalizedRotation(rotationDegrees: Int): Int =
        ((rotationDegrees % 360) + 360) % 360

    companion object {
        private const val TAG = "VideoStreamActivity"
        private const val REQUEST_RUNTIME_PERMISSIONS = 3001
        private const val DEFAULT_JETSON_HOST = "192.168.1.100"
        private const val DEFAULT_CONTROL_PORT = 9080
        private const val DEFAULT_MODE = "standby"
        private const val STATUS_UPDATE_INTERVAL_MS = 300L
        private const val TELEMETRY_SAMPLE_INTERVAL_MS = 5000L
        private const val TELEMETRY_SEND_INTERVAL_MS = 5000L
        private const val ENCODER_STAT_SEND_INTERVAL_MS = 5000L
        private const val DEBUG_LOG_INTERVAL_MS = 5000L
        private const val HEARTBEAT_INTERVAL_MS = 1000L
        private const val HUD_RENDER_POST_INTERVAL_MS = 500L
        private const val SPEECH_HUD_FORCE_RENDER_INTERVAL_MS = 180L
        private const val SPEECH_TRANSCRIPT_HOLD_MS = 1200L
        private const val HUD_EVENT_LOG_INTERVAL_MS = 2000L
        private const val HUD_RENDER_LOG_INTERVAL_MS = 2500L
        private const val HUD_SCENE_PRIORITY_TTL_MS = 4500L
        private const val HUD_PRESENTATION_HOLD_MS = 6000L
        private const val ENABLE_BACKGROUND_DEBUG_LOGS = false
        private val LOW_PROFILE = VideoStreamProfile(
            label = "LOW",
            width = 480,
            height = 640,
            fps = 8,
            bitrate = 650_000,
            minCameraFps = 5,
            iFrameIntervalSeconds = 2
        )
        private val MEDIUM_PROFILE = VideoStreamProfile(
            label = "MEDIUM",
            width = 720,
            height = 960,
            fps = 10,
            bitrate = 1_100_000,
            minCameraFps = 7,
            iFrameIntervalSeconds = 2
        )
        private val HIGH_PROFILE = VideoStreamProfile(
            label = "HIGH",
            width = 960,
            height = 1280,
            fps = 12,
            bitrate = 1_600_000,
            minCameraFps = 8,
            iFrameIntervalSeconds = 1
        )
        private val PROFILE_CYCLE = listOf(LOW_PROFILE, MEDIUM_PROFILE, HIGH_PROFILE)

        const val EXTRA_JETSON_HOST = "jetson_host"
        const val EXTRA_CONTROL_PORT = "jetson_control_port"
    }
}
