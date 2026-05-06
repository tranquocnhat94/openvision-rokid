package com.example.cxrservicedemo.videostream.voice

import android.util.Log
import com.example.cxrservicedemo.videostream.transport.JetsonSessionAccept
import java.io.BufferedOutputStream
import java.io.Closeable
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.charset.StandardCharsets

data class AudioStreamHello(
    val sessionId: String,
    val codec: String,
    val sampleRateHz: Int,
    val channels: Int,
    val bytesPerSample: Int
)

data class JetsonAudioStatus(
    val connected: Boolean,
    val targetLabel: String,
    val sentChunks: Long,
    val sentBytes: Long,
    val lastPayloadBytes: Int,
    val lastError: String? = null
)

class GlassAudioStreamClient(
    private val deviceId: String,
    private val appVersion: String
) : Closeable {

    private var socket: Socket? = null
    private var output: DataOutputStream? = null
    private var connected = false
    private var targetLabel = "--"
    private var sentChunks = 0L
    private var sentBytes = 0L
    private var lastPayloadBytes = 0
    private var lastError: String? = null
    private var helloSent = false
    private var connectedHost: String? = null
    private var connectedPort: Int? = null
    private var connectedSessionId: String? = null
    private var lastFlushAtMs = 0L

    @Synchronized
    fun sendChunk(session: JetsonSessionAccept, hello: AudioStreamHello, chunk: AudioPcmChunk): Boolean {
        return try {
            ensureConnected(session)
            if (!helloSent) {
                writeFrame(TYPE_AUDIO_HELLO, buildHelloHeader(hello), ByteArray(0), forceFlush = true)
                helloSent = true
            }
            val header = mapOf(
                "sessionId" to hello.sessionId,
                "sequence" to chunk.sequence,
                "captureTimestampMs" to chunk.captureTimestampMs,
                "payloadBytes" to chunk.payload.size,
                "avgAbs" to chunk.avgAbs,
                "peakAbs" to chunk.peakAbs,
                "nonSilentRatio" to chunk.nonSilentRatio,
                "audioSource" to chunk.audioSourceLabel
            )
            writeFrame(TYPE_AUDIO_SAMPLE, header, chunk.payload)
            sentChunks++
            sentBytes += chunk.payload.size
            lastPayloadBytes = chunk.payload.size
            true
        } catch (error: Exception) {
            connected = false
            lastError = error.message
            closeSocket()
            false
        }
    }

    @Synchronized
    fun status(): JetsonAudioStatus =
        JetsonAudioStatus(
            connected = connected,
            targetLabel = targetLabel,
            sentChunks = sentChunks,
            sentBytes = sentBytes,
            lastPayloadBytes = lastPayloadBytes,
            lastError = lastError
        )

    @Synchronized
    fun stop() {
        closeSocket()
    }

    @Synchronized
    fun resetStats() {
        sentChunks = 0L
        sentBytes = 0L
        lastPayloadBytes = 0
        lastError = null
    }

    @Synchronized
    override fun close() {
        closeSocket()
    }

    private fun ensureConnected(session: JetsonSessionAccept) {
        targetLabel = "${session.audioHost}:${session.audioPort}"
        val targetChanged =
            connectedHost != session.audioHost ||
                connectedPort != session.audioPort ||
                connectedSessionId != session.sessionId
        if (targetChanged) {
            closeSocket()
        }
        if (socket == null || output == null || !connected) {
            val nextSocket = Socket()
            nextSocket.tcpNoDelay = true
            nextSocket.sendBufferSize = SOCKET_BUFFER_BYTES
            nextSocket.connect(InetSocketAddress(session.audioHost, session.audioPort), CONNECT_TIMEOUT_MS)
            socket = nextSocket
            output = DataOutputStream(BufferedOutputStream(nextSocket.getOutputStream(), SOCKET_BUFFER_BYTES))
            connected = true
            helloSent = false
            lastError = null
            connectedHost = session.audioHost
            connectedPort = session.audioPort
            connectedSessionId = session.sessionId
            lastFlushAtMs = 0L
        }
    }

    private fun buildHelloHeader(hello: AudioStreamHello): Map<String, Any> =
        mapOf(
            "sessionId" to hello.sessionId,
            "deviceId" to deviceId,
            "appVersion" to appVersion,
            "codec" to hello.codec,
            "sampleRateHz" to hello.sampleRateHz,
            "channels" to hello.channels,
            "bytesPerSample" to hello.bytesPerSample
        )

    private fun writeFrame(
        messageType: Int,
        header: Map<String, Any>,
        payload: ByteArray,
        forceFlush: Boolean = false
    ) {
        val sink = output ?: error("audio output unavailable")
        val headerJson = org.json.JSONObject(header).toString().toByteArray(StandardCharsets.UTF_8)
        sink.write(FRAME_MAGIC)
        sink.writeShort(FRAME_VERSION)
        sink.writeShort(messageType)
        sink.writeInt(headerJson.size)
        sink.writeInt(payload.size)
        sink.write(headerJson)
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
        helloSent = false
        connected = false
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
        } catch (error: Exception) {
            Log.w(TAG, "audio close failed", error)
        }
        output = null
        socket = null
        connectedHost = null
        connectedPort = null
        connectedSessionId = null
    }

    companion object {
        private const val TAG = "GlassAudioStreamClient"
        private const val CONNECT_TIMEOUT_MS = 2_500
        private const val SOCKET_BUFFER_BYTES = 64 * 1024
        private const val IMMEDIATE_FLUSH_PAYLOAD_BYTES = 8 * 1024
        private const val FLUSH_INTERVAL_MS = 100L
        private const val FRAME_VERSION = 1
        private const val TYPE_AUDIO_HELLO = 3
        private const val TYPE_AUDIO_SAMPLE = 4
        private val FRAME_MAGIC = byteArrayOf('R'.code.toByte(), 'V'.code.toByte(), 'S'.code.toByte(), '1'.code.toByte())
    }
}
