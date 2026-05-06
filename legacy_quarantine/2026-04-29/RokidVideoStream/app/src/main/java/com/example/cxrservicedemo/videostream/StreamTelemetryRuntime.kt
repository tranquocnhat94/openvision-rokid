package com.example.cxrservicedemo.videostream

import com.example.cxrservicedemo.mousehand.telemetry.MouseHandTelemetrySnapshot
import com.example.cxrservicedemo.videostream.debug.VideoStreamDebugSnapshot
import com.example.cxrservicedemo.videostream.transport.JetsonControlStatus
import com.example.cxrservicedemo.videostream.transport.JetsonNodeTelemetry
import com.example.cxrservicedemo.videostream.transport.JetsonVideoStatus
import com.example.cxrservicedemo.videostream.transport.VideoStreamProfile
import java.util.Locale

class StreamTelemetryRuntime {
    var frameSequence: Long = 0L
        private set
    var captureFps: Float = 0f
        private set
    var encodeFps: Float = 0f
        private set
    var encodeMs: Float = 0f
        private set
    var sendMs: Float = 0f
        private set

    private var lastFrameTimestampMs = 0L
    private var lastEncodedFrameTimestampMs = 0L

    fun recordEncodedSample(sample: EncodedVideoSample) {
        frameSequence = sample.sequence
        updateCaptureFps(sample.captureTimestampMs)
        updateEncodeFps(sample.captureTimestampMs)
        updateEncodeTiming(sample.encodeCostMs)
    }

    fun recordSendDuration(sendDurationMs: Float) {
        sendMs = if (sendMs == 0f) {
            sendDurationMs
        } else {
            sendMs * 0.85f + sendDurationMs * 0.15f
        }
    }

    fun buildDeveloperPanelText(
        sessionId: String?,
        selectedMode: String,
        controlStatus: JetsonControlStatus,
        videoStatus: JetsonVideoStatus,
        telemetry: MouseHandTelemetrySnapshot,
        node: JetsonNodeTelemetry?,
        activeProfile: VideoStreamProfile,
        encoderStats: VideoEncoderRuntimeStats?,
        analyzerDrops: Long,
    ): String =
        listOf(
            "session ${sessionId ?: "--"} | shell $selectedMode | ws=${controlStatus.connected} video=${videoStatus.connected}",
            "fps cap=${formatFloat(captureFps, 1)} enc=${formatFloat(encodeFps, 1)} encode=${formatFloat(encodeMs, 1)}ms send=${formatFloat(sendMs, 1)}ms",
            "jetson rx=${formatFloat(node?.rxFps ?: 0f, 1)} gpu=${node?.gpuPercent ?: 0}% cpu=${node?.cpuPercent ?: 0}% frames=${node?.videoFrames ?: 0}",
            "profile ${activeProfile.label} ${activeProfile.width}x${activeProfile.height}@${activeProfile.fps} | input ${encoderStats?.inputLayout ?: "--"}/${encoderStats?.colorFormat ?: "--"}",
            "net ${telemetry.networkLabel} tx=${formatFloat(telemetry.txKbps, 1)}kbps rx=${formatFloat(telemetry.rxKbps, 1)}kbps | drops a=$analyzerDrops e=${encoderStats?.droppedInputFrames ?: 0}",
            videoStatus.lastError ?: controlStatus.lastError ?: "Long press or TV/Menu to hide"
        ).joinToString("\n")

    fun buildDeviceTelemetryPayload(
        telemetry: MouseHandTelemetrySnapshot,
        videoStatus: JetsonVideoStatus,
        activeProfile: VideoStreamProfile,
        selectedMode: String,
        controlConnected: Boolean,
        audioStreaming: Boolean,
    ): Map<String, Any?> =
        linkedMapOf(
            "batteryPercent" to telemetry.batteryPercent,
            "batteryTempC" to telemetry.batteryTempC,
            "batteryCurrentMa" to telemetry.batteryCurrentMa,
            "thermalStatusLabel" to telemetry.thermalStatusLabel,
            "appCpuPercent" to telemetry.appCpuPercent,
            "javaHeapMb" to telemetry.javaHeapMb,
            "nativeHeapMb" to telemetry.nativeHeapMb,
            "totalPssMb" to telemetry.totalPssMb,
            "availMemMb" to telemetry.availMemMb,
            "rxKbps" to telemetry.rxKbps,
            "txKbps" to telemetry.txKbps,
            "networkLabel" to telemetry.networkLabel,
            "captureFps" to captureFps,
            "encodeFps" to encodeFps,
            "sentSamples" to videoStatus.sentSamples,
            "sentBytes" to videoStatus.sentBytes,
            "keyframesSent" to videoStatus.keyframesSent,
            "profileLabel" to activeProfile.label,
            "appMode" to runtimeModeLabel(audioStreaming, videoStatus.connected, controlConnected),
            "selectedMode" to selectedMode,
        )

    fun buildEncoderStatsPayload(
        stats: VideoEncoderRuntimeStats,
        activeProfile: VideoStreamProfile,
        encoderWidth: Int,
        encoderHeight: Int,
        analyzerDrops: Long,
    ): Map<String, Any?> =
        linkedMapOf(
            "profileLabel" to activeProfile.label,
            "width" to if (encoderWidth > 0) encoderWidth else activeProfile.width,
            "height" to if (encoderHeight > 0) encoderHeight else activeProfile.height,
            "targetFps" to activeProfile.fps,
            "targetBitrate" to activeProfile.bitrate,
            "minCameraFps" to activeProfile.minCameraFps,
            "captureFps" to captureFps,
            "encodeFps" to encodeFps,
            "encodeMs" to encodeMs,
            "sendMs" to sendMs,
            "analyzerDrops" to analyzerDrops,
            "encoderDrops" to stats.droppedInputFrames,
            "emittedSamples" to stats.emittedSamples,
            "emittedKeyframes" to stats.emittedKeyframes,
            "outputBytes" to stats.outputBytes,
            "lastPayloadBytes" to stats.lastPayloadBytes,
            "inputLayout" to stats.inputLayout,
            "colorFormat" to stats.colorFormat,
        )

    fun buildDebugSnapshot(
        sessionId: String?,
        rotationDegrees: Int,
        activeProfile: VideoStreamProfile,
        encoderWidth: Int,
        encoderHeight: Int,
        encoderStats: VideoEncoderRuntimeStats,
        videoStatus: JetsonVideoStatus,
        controlStatus: JetsonControlStatus,
        telemetry: MouseHandTelemetrySnapshot,
        node: JetsonNodeTelemetry?,
        analyzerDrops: Long,
    ): VideoStreamDebugSnapshot =
        VideoStreamDebugSnapshot(
            timestampMs = System.currentTimeMillis(),
            sessionId = sessionId,
            sequence = frameSequence,
            sourceWidth = if (encoderWidth > 0) encoderWidth else activeProfile.width,
            sourceHeight = if (encoderHeight > 0) encoderHeight else activeProfile.height,
            rotationDegrees = rotationDegrees,
            profileLabel = activeProfile.label,
            preferredChromaMode = "surface-fixed",
            inputLayout = encoderStats.inputLayout,
            colorFormat = encoderStats.colorFormat,
            captureFps = captureFps,
            encodeFps = encodeFps,
            encodeMs = encodeMs,
            sendMs = sendMs,
            analyzerDrops = analyzerDrops,
            encoderDrops = encoderStats.droppedInputFrames,
            sentSamples = videoStatus.sentSamples,
            droppedSamples = videoStatus.droppedSamples,
            sentBytes = videoStatus.sentBytes,
            keyframesSent = videoStatus.keyframesSent,
            payloadBytes = videoStatus.lastPayloadBytes,
            wsConnected = controlStatus.connected,
            videoConnected = videoStatus.connected,
            wsTarget = controlStatus.targetLabel,
            videoTarget = videoStatus.targetLabel,
            batteryPercent = telemetry.batteryPercent,
            batteryTempC = telemetry.batteryTempC,
            batteryCurrentMa = telemetry.batteryCurrentMa,
            thermalStatusLabel = telemetry.thermalStatusLabel,
            appCpuPercent = telemetry.appCpuPercent,
            javaHeapMb = telemetry.javaHeapMb,
            nativeHeapMb = telemetry.nativeHeapMb,
            totalPssMb = telemetry.totalPssMb,
            availMemMb = telemetry.availMemMb,
            rxKbps = telemetry.rxKbps,
            txKbps = telemetry.txKbps,
            networkLabel = telemetry.networkLabel,
            jetsonRxFps = node?.rxFps ?: 0f,
            jetsonVideoFrames = node?.videoFrames ?: 0L,
            jetsonVideoBytes = node?.videoBytes ?: 0L,
            jetsonGpuPercent = node?.gpuPercent ?: 0,
            jetsonCpuPercent = node?.cpuPercent ?: 0,
            lastError = videoStatus.lastError ?: controlStatus.lastError
        )

    fun runtimeModeLabel(
        audioStreaming: Boolean,
        videoConnected: Boolean,
        controlConnected: Boolean,
    ): String =
        when {
            audioStreaming && videoConnected -> "streaming_av"
            videoConnected -> "streaming_video"
            audioStreaming -> "voice_live"
            controlConnected -> "linked_idle"
            else -> "standby"
        }

    fun reset() {
        frameSequence = 0L
        captureFps = 0f
        encodeFps = 0f
        encodeMs = 0f
        sendMs = 0f
        lastFrameTimestampMs = 0L
        lastEncodedFrameTimestampMs = 0L
    }

    private fun updateCaptureFps(frameTimestampMs: Long) {
        if (lastFrameTimestampMs != 0L) {
            val deltaMs = (frameTimestampMs - lastFrameTimestampMs).coerceAtLeast(1L)
            val instantFps = 1000f / deltaMs.toFloat()
            captureFps = if (captureFps == 0f) {
                instantFps
            } else {
                captureFps * 0.8f + instantFps * 0.2f
            }
        }
        lastFrameTimestampMs = frameTimestampMs
    }

    private fun updateEncodeFps(frameTimestampMs: Long) {
        if (lastEncodedFrameTimestampMs != 0L) {
            val deltaMs = (frameTimestampMs - lastEncodedFrameTimestampMs).coerceAtLeast(1L)
            val instantFps = 1000f / deltaMs.toFloat()
            encodeFps = if (encodeFps == 0f) {
                instantFps
            } else {
                encodeFps * 0.8f + instantFps * 0.2f
            }
        }
        lastEncodedFrameTimestampMs = frameTimestampMs
    }

    private fun updateEncodeTiming(latencyMs: Float) {
        encodeMs = if (encodeMs == 0f) {
            latencyMs
        } else {
            encodeMs * 0.85f + latencyMs * 0.15f
        }
    }

    private fun formatFloat(value: Float, decimals: Int): String =
        String.format(Locale.US, "%.${decimals}f", value)
}
