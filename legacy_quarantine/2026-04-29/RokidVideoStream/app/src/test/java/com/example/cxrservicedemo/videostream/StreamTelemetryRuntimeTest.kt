package com.example.cxrservicedemo.videostream

import com.example.cxrservicedemo.mousehand.telemetry.MouseHandTelemetrySnapshot
import com.example.cxrservicedemo.videostream.transport.JetsonControlStatus
import com.example.cxrservicedemo.videostream.transport.JetsonNodeTelemetry
import com.example.cxrservicedemo.videostream.transport.JetsonVideoStatus
import com.example.cxrservicedemo.videostream.transport.VideoStreamProfile
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StreamTelemetryRuntimeTest {
    private val profile = VideoStreamProfile(
        label = "MEDIUM",
        width = 720,
        height = 960,
        fps = 10,
        bitrate = 1_100_000,
        minCameraFps = 7,
        iFrameIntervalSeconds = 2
    )

    private val telemetry = MouseHandTelemetrySnapshot(
        timestampMs = 1000L,
        batteryPercent = 75,
        batteryTempC = 31.5f,
        batteryCurrentMa = -210f,
        thermalStatusLabel = "LIGHT",
        appCpuPercent = 12.5f,
        javaHeapMb = 64f,
        nativeHeapMb = 12f,
        totalPssMb = 90f,
        availMemMb = 512f,
        rxKbps = 24f,
        txKbps = 18f,
        networkLabel = "WIFI"
    )

    @Test
    fun `record encoded samples smooths fps and latency`() {
        val runtime = StreamTelemetryRuntime()

        runtime.recordEncodedSample(
            EncodedVideoSample(
                sequence = 1L,
                captureTimestampMs = 1000L,
                presentationTimeUs = 0L,
                flags = 0,
                isKeyframe = false,
                isCodecConfig = false,
                width = 720,
                height = 960,
                encodeCostMs = 8f,
                payload = byteArrayOf(1, 2, 3)
            )
        )
        runtime.recordEncodedSample(
            EncodedVideoSample(
                sequence = 2L,
                captureTimestampMs = 1100L,
                presentationTimeUs = 0L,
                flags = 0,
                isKeyframe = false,
                isCodecConfig = false,
                width = 720,
                height = 960,
                encodeCostMs = 12f,
                payload = byteArrayOf(4, 5, 6)
            )
        )
        runtime.recordSendDuration(20f)

        assertEquals(2L, runtime.frameSequence)
        assertEquals(10f, runtime.captureFps, 0.01f)
        assertEquals(10f, runtime.encodeFps, 0.01f)
        assertTrue(runtime.encodeMs > 8f)
        assertEquals(20f, runtime.sendMs, 0.01f)
    }

    @Test
    fun `runtime mode label follows thin client streaming state`() {
        val runtime = StreamTelemetryRuntime()

        assertEquals("streaming_av", runtime.runtimeModeLabel(audioStreaming = true, videoConnected = true, controlConnected = true))
        assertEquals("streaming_video", runtime.runtimeModeLabel(audioStreaming = false, videoConnected = true, controlConnected = true))
        assertEquals("voice_live", runtime.runtimeModeLabel(audioStreaming = true, videoConnected = false, controlConnected = true))
        assertEquals("linked_idle", runtime.runtimeModeLabel(audioStreaming = false, videoConnected = false, controlConnected = true))
        assertEquals("standby", runtime.runtimeModeLabel(audioStreaming = false, videoConnected = false, controlConnected = false))
    }

    @Test
    fun `json payloads carry smoothed metrics and profile info`() {
        val runtime = StreamTelemetryRuntime().apply {
            recordEncodedSample(
                EncodedVideoSample(
                    sequence = 1L,
                    captureTimestampMs = 1000L,
                    presentationTimeUs = 0L,
                    flags = 0,
                    isKeyframe = false,
                    isCodecConfig = false,
                    width = 720,
                    height = 960,
                    encodeCostMs = 9f,
                    payload = byteArrayOf(1)
                )
            )
            recordEncodedSample(
                EncodedVideoSample(
                    sequence = 2L,
                    captureTimestampMs = 1100L,
                    presentationTimeUs = 0L,
                    flags = 0,
                    isKeyframe = false,
                    isCodecConfig = false,
                    width = 720,
                    height = 960,
                    encodeCostMs = 9f,
                    payload = byteArrayOf(2)
                )
            )
            recordSendDuration(11f)
        }
        val videoStatus = JetsonVideoStatus(
            connected = true,
            targetLabel = "jetson",
            sentSamples = 4,
            droppedSamples = 1,
            sentBytes = 2048,
            keyframesSent = 1,
            lastPayloadBytes = 512
        )
        val encoderStats = VideoEncoderRuntimeStats(
            emittedSamples = 4,
            emittedKeyframes = 1,
            outputBytes = 2048,
            lastPayloadBytes = 512,
            droppedInputFrames = 0,
            inputLayout = "surface",
            colorFormat = "opaque"
        )

        val telemetryPayload = runtime.buildDeviceTelemetryPayload(
            telemetry = telemetry,
            videoStatus = videoStatus,
            activeProfile = profile,
            selectedMode = "standby",
            controlConnected = true,
            audioStreaming = true
        )
        val encoderPayload = runtime.buildEncoderStatsPayload(
            stats = encoderStats,
            activeProfile = profile,
            encoderWidth = 0,
            encoderHeight = 0,
            analyzerDrops = 3
        )
        val debugSnapshot = runtime.buildDebugSnapshot(
            sessionId = "sess_demo",
            rotationDegrees = 90,
            activeProfile = profile,
            encoderWidth = 0,
            encoderHeight = 0,
            encoderStats = encoderStats,
            videoStatus = videoStatus,
            controlStatus = JetsonControlStatus(connected = true, targetLabel = "jetson"),
            telemetry = telemetry,
            node = JetsonNodeTelemetry(rxFps = 8.5f, gpuPercent = 35, cpuPercent = 22, ramMb = 1024, videoFrames = 10, videoBytes = 4096),
            analyzerDrops = 3
        )

        assertEquals("MEDIUM", telemetryPayload["profileLabel"])
        assertEquals("streaming_av", telemetryPayload["appMode"])
        assertEquals(720, encoderPayload["width"])
        assertEquals(960, encoderPayload["height"])
        assertEquals(3L, encoderPayload["analyzerDrops"])
        assertEquals("sess_demo", debugSnapshot.sessionId)
        assertEquals(2L, debugSnapshot.sequence)
        assertEquals(3L, debugSnapshot.analyzerDrops)
    }
}
