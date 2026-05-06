package com.example.cxrservicedemo.videostream.transport

data class JetsonSessionAccept(
    val sessionId: String,
    val controlHeartbeatMs: Int,
    val resultThrottleMs: Int,
    val videoHost: String,
    val videoPort: Int,
    val mediaTransport: String,
    val audioHost: String,
    val audioPort: Int,
    val audioCodec: String
)

data class JetsonVisionResult(
    val mode: String,
    val headline: String,
    val primaryValue: Long,
    val label: String,
    val frameSeq: Long,
    val counts: Map<String, Long>,
    val alertLabel: String?,
    val faceLabel: String?,
    val faceConfidence: Float?,
    val detailLines: List<String>,
    val captureToReceiveMs: Int,
    val inferMs: Int,
    val publishMs: Int,
    val endToEndMs: Int
)

data class JetsonNodeTelemetry(
    val rxFps: Float,
    val gpuPercent: Int,
    val cpuPercent: Int,
    val ramMb: Int,
    val videoFrames: Long,
    val videoBytes: Long
)

data class JetsonSpeechState(
    val listening: Boolean,
    val taskLabel: String?,
    val transcriptHint: String?,
    val stateLabel: String
)

data class JetsonHudGalleryItem(
    val label: String,
    val secondaryText: String?,
    val trackId: String?,
    val selected: Boolean,
    val thumbBase64: String?
)

data class JetsonHudTargetMarker(
    val label: String?,
    val trackId: String?,
    val direction: String?,
    val selected: Boolean,
    val normalizedX: Float?,
    val normalizedY: Float?
)

data class JetsonHudScene(
    val sessionId: String?,
    val sceneId: String,
    val taskChip: String?,
    val micChip: String?,
    val answerText: String?,
    val statusText: String?,
    val galleryLabels: List<String>,
    val galleryItems: List<JetsonHudGalleryItem>,
    val directionHint: String?,
    val targetMarker: JetsonHudTargetMarker?
)

data class JetsonControlStatus(
    val connected: Boolean,
    val targetLabel: String,
    val sessionId: String? = null,
    val lastError: String? = null
)

data class JetsonVideoStatus(
    val connected: Boolean,
    val targetLabel: String,
    val sentSamples: Long,
    val droppedSamples: Long,
    val sentBytes: Long,
    val keyframesSent: Long,
    val lastPayloadBytes: Int,
    val lastError: String? = null
)

data class VideoStreamProfile(
    val label: String,
    val width: Int,
    val height: Int,
    val fps: Int,
    val bitrate: Int,
    val minCameraFps: Int,
    val iFrameIntervalSeconds: Int
)

data class VideoStreamHello(
    val sessionId: String,
    val mode: String,
    val profile: VideoStreamProfile,
    val width: Int,
    val height: Int,
    val rotationDegrees: Int
)

interface JetsonControlListener {
    fun onControlStatus(status: JetsonControlStatus)
    fun onSessionAccepted(session: JetsonSessionAccept)
    fun onVisionResult(result: JetsonVisionResult)
    fun onNodeTelemetry(telemetry: JetsonNodeTelemetry)
    fun onSpeechState(state: JetsonSpeechState)
    fun onHudScene(scene: JetsonHudScene)
    fun onControlError(message: String)
}
