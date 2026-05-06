package com.example.cxrservicedemo.videostream.transport

import android.util.Log
import com.example.cxrservicedemo.videostream.EncodedVideoSample
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.Closeable
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.charset.StandardCharsets

class JetsonMediaStreamClient(
    private val deviceId: String,
    private val appVersion: String
) : Closeable {

    private var socket: Socket? = null
    private var output: DataOutputStream? = null
    private var connected = false
    private var targetLabel = "--"
    private var videoSentSamples = 0L
    private var videoDroppedSamples = 0L
    private var videoSentBytes = 0L
    private var videoKeyframesSent = 0L
    private var videoLastPayloadBytes = 0
    private var lastError: String? = null
    private var lastVideoHelloSignature: VideoHelloSignature? = null
    private var lastVideoHelloSentAtMs = 0L
    private var lastFlushAtMs = 0L
    private var connectedHost: String? = null
    private var connectedPort: Int? = null
    private var connectedSessionId: String? = null

    @Synchronized
    fun sendVideoSample(
        session: JetsonSessionAccept,
        hello: VideoStreamHello,
        sample: EncodedVideoSample
    ): Boolean {
        return try {
            ensureConnected(session)
            ensureVideoHello(hello)
            writeVideoSample(hello, sample)
            true
        } catch (error: Exception) {
            videoDroppedSamples++
            connected = false
            lastError = error.message
            Log.w(TAG, "media video send failed", error)
            closeSocket()
            false
        }
    }

    @Synchronized
    fun videoStatus(): JetsonVideoStatus =
        JetsonVideoStatus(
            connected = connected,
            targetLabel = targetLabel,
            sentSamples = videoSentSamples,
            droppedSamples = videoDroppedSamples,
            sentBytes = videoSentBytes,
            keyframesSent = videoKeyframesSent,
            lastPayloadBytes = videoLastPayloadBytes,
            lastError = lastError
        )

    @Synchronized
    fun stop() {
        closeSocket()
    }

    @Synchronized
    override fun close() {
        closeSocket()
    }

    private fun ensureConnected(session: JetsonSessionAccept) {
        targetLabel = "${session.videoHost}:${session.videoPort}"
        val targetChanged =
            connectedHost != session.videoHost ||
                connectedPort != session.videoPort ||
                connectedSessionId != session.sessionId
        if (targetChanged) {
            closeSocket()
        }
        if (socket == null || output == null || !connected) {
            val nextSocket = Socket()
            nextSocket.tcpNoDelay = true
            nextSocket.sendBufferSize = SOCKET_BUFFER_BYTES
            nextSocket.connect(InetSocketAddress(session.videoHost, session.videoPort), CONNECT_TIMEOUT_MS)
            socket = nextSocket
            output = DataOutputStream(BufferedOutputStream(nextSocket.getOutputStream(), SOCKET_BUFFER_BYTES))
            connected = true
            lastError = null
            lastVideoHelloSignature = null
            connectedHost = session.videoHost
            connectedPort = session.videoPort
            connectedSessionId = session.sessionId
        }
    }

    private fun ensureVideoHello(hello: VideoStreamHello) {
        val nextSignature = VideoHelloSignature.from(hello)
        val nowMs = System.currentTimeMillis()
        val shouldSendHello = lastVideoHelloSignature != nextSignature ||
            nowMs - lastVideoHelloSentAtMs >= HELLO_REFRESH_INTERVAL_MS
        if (!shouldSendHello) {
            return
        }
        writePacket(
            type = TYPE_HELLO,
            header = JSONObject()
                .put("sessionId", hello.sessionId)
                .put("deviceId", deviceId)
                .put("appVersion", appVersion)
                .put("mode", hello.mode)
                .put("codec", "video/avc")
                .put("width", hello.width)
                .put("height", hello.height)
                .put("targetFps", hello.profile.fps)
                .put("targetBitrate", hello.profile.bitrate)
                .put("profileLabel", hello.profile.label)
                .put("rotationDegrees", hello.rotationDegrees),
            payload = ByteArray(0),
            forceFlush = true
        )
        lastVideoHelloSignature = nextSignature
        lastVideoHelloSentAtMs = nowMs
    }

    private fun writeVideoSample(hello: VideoStreamHello, sample: EncodedVideoSample) {
        val header = JSONObject()
            .put("sessionId", hello.sessionId)
            .put("deviceId", deviceId)
            .put("sequence", sample.sequence)
            .put("captureTimestampMs", sample.captureTimestampMs)
            .put("presentationTimeUs", sample.presentationTimeUs)
            .put("flags", sample.flags)
            .put("isKeyframe", sample.isKeyframe)
            .put("isCodecConfig", sample.isCodecConfig)
            .put("width", sample.width)
            .put("height", sample.height)
            .put("mode", hello.mode)
            .put("profileLabel", hello.profile.label)
            .put("rotationDegrees", hello.rotationDegrees)

        writePacket(
            type = TYPE_VIDEO_SAMPLE,
            header = header,
            payload = sample.payload,
            forceFlush = sample.isCodecConfig || sample.isKeyframe
        )
        videoSentSamples++
        videoSentBytes += sample.payload.size.toLong()
        if (sample.isKeyframe) videoKeyframesSent++
        videoLastPayloadBytes = sample.payload.size
        lastError = null
    }

    private fun writePacket(type: Int, header: JSONObject, payload: ByteArray, forceFlush: Boolean = false) {
        val sink = output ?: error("media socket not connected")
        val headerBytes = header.toString().toByteArray(StandardCharsets.UTF_8)
        sink.write(FRAME_MAGIC)
        sink.writeShort(PROTOCOL_VERSION)
        sink.writeShort(type)
        sink.writeInt(headerBytes.size)
        sink.writeInt(payload.size)
        sink.write(headerBytes)
        if (payload.isNotEmpty()) {
            sink.write(payload)
        }
        val nowMs = System.currentTimeMillis()
        if (
            forceFlush ||
            payload.isEmpty() ||
            payload.size >= IMMEDIATE_FLUSH_PAYLOAD_BYTES ||
            nowMs - lastFlushAtMs >= FLUSH_INTERVAL_MS
        ) {
            sink.flush()
            lastFlushAtMs = nowMs
        }
    }

    private fun closeSocket() {
        connected = false
        lastVideoHelloSignature = null
        lastFlushAtMs = 0L
        try {
            output?.flush()
        } catch (_: Exception) {
        }
        try {
            output?.close()
        } catch (_: Exception) {
        }
        try {
            socket?.close()
        } catch (_: Exception) {
        }
        output = null
        socket = null
        connectedHost = null
        connectedPort = null
        connectedSessionId = null
    }

    companion object {
        private const val TAG = "JetsonMediaClient"
        private const val CONNECT_TIMEOUT_MS = 1500
        private const val SOCKET_BUFFER_BYTES = 128 * 1024
        private const val HELLO_REFRESH_INTERVAL_MS = 15_000L
        private const val IMMEDIATE_FLUSH_PAYLOAD_BYTES = 16 * 1024
        private const val FLUSH_INTERVAL_MS = 24L
        private const val PROTOCOL_VERSION = 1
        private const val TYPE_HELLO = 1
        private const val TYPE_VIDEO_SAMPLE = 2
        private val FRAME_MAGIC = "RVS1".toByteArray(StandardCharsets.US_ASCII)
    }
}

private data class VideoHelloSignature(
    val sessionId: String,
    val width: Int,
    val height: Int,
    val targetFps: Int,
    val targetBitrate: Int,
    val profileLabel: String,
    val rotationDegrees: Int
) {
    companion object {
        fun from(hello: VideoStreamHello): VideoHelloSignature =
            VideoHelloSignature(
                sessionId = hello.sessionId,
                width = hello.width,
                height = hello.height,
                targetFps = hello.profile.fps,
                targetBitrate = hello.profile.bitrate,
                profileLabel = hello.profile.label,
                rotationDegrees = hello.rotationDegrees
            )
    }
}
