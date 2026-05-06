package com.example.cxrservicedemo.videostream

import android.content.Context
import android.os.SystemClock
import com.example.cxrservicedemo.videostream.transport.JetsonControlClient
import com.example.cxrservicedemo.videostream.transport.JetsonSessionAccept
import com.example.cxrservicedemo.videostream.voice.AudioCaptureState
import com.example.cxrservicedemo.videostream.voice.AudioPcmChunk
import com.example.cxrservicedemo.videostream.voice.AudioStreamHello
import com.example.cxrservicedemo.videostream.voice.GlassAudioCapture
import com.example.cxrservicedemo.videostream.voice.GlassAudioStreamClient
import com.example.cxrservicedemo.videostream.voice.JetsonAudioStatus
import org.json.JSONObject
import java.io.Closeable
import java.util.concurrent.ExecutorService
import java.util.concurrent.LinkedBlockingDeque
import java.util.concurrent.TimeUnit

data class AudioStreamingSnapshot(
    val streaming: Boolean,
    val activeSessionId: String?,
    val lastChunkAtMs: Long,
    val lastStatsSentAtMs: Long,
    val sourceLabel: String,
    val avgAbs: Int,
    val peakAbs: Int,
    val nonSilentRatio: Float,
    val queueDepth: Int,
    val droppedChunks: Long,
    val sendFailures: Long,
)

class AudioStreamingCoordinator(
    private val applicationContext: Context,
    deviceId: String,
    appVersion: String,
    private val controlClient: JetsonControlClient,
    private val callbacks: Callbacks,
) : Closeable {

    interface Callbacks {
        fun onStreamingStateChanged(streaming: Boolean)
    }

    private val audioClient = GlassAudioStreamClient(
        deviceId = deviceId,
        appVersion = appVersion,
    )
    private var audioCapture: GlassAudioCapture? = null
    private var audioStreamingActive = false
    private var activeAudioSessionId: String? = null
    private var lastAudioChunkAtMs = 0L
    private var lastAudioStatSendTimestampMs = 0L
    private var latestAudioSourceLabel = "unknown"
    private var latestAudioAvgAbs = 0
    private var latestAudioPeakAbs = 0
    private var latestAudioNonSilentRatio = 0f
    private val audioSendQueue = LinkedBlockingDeque<PendingAudioChunk>(AUDIO_SEND_QUEUE_CAPACITY)
    private var audioSendExecutor: ExecutorService? = null
    private var activeAudioHello: AudioStreamHello? = null
    private var audioDroppedChunks = 0L
    private var audioSendFailures = 0L
    private var lastAudioStateSignature: String? = null
    private var lastAudioStateLogTimestampMs = 0L

    @Synchronized
    fun isStreaming(): Boolean = audioStreamingActive

    @Synchronized
    fun activeSessionId(): String? = activeAudioSessionId

    @Synchronized
    fun snapshot(): AudioStreamingSnapshot =
        AudioStreamingSnapshot(
            streaming = audioStreamingActive,
            activeSessionId = activeAudioSessionId,
            lastChunkAtMs = lastAudioChunkAtMs,
            lastStatsSentAtMs = lastAudioStatSendTimestampMs,
            sourceLabel = latestAudioSourceLabel,
            avgAbs = latestAudioAvgAbs,
            peakAbs = latestAudioPeakAbs,
            nonSilentRatio = latestAudioNonSilentRatio,
            queueDepth = audioSendQueue.size,
            droppedChunks = audioDroppedChunks,
            sendFailures = audioSendFailures,
        )

    @Synchronized
    fun start(session: JetsonSessionAccept) {
        if (audioStreamingActive && activeAudioSessionId == session.sessionId) {
            return
        }
        if (audioStreamingActive) {
            stop()
        }
        audioStreamingActive = true
        activeAudioSessionId = session.sessionId
        activeAudioHello = buildAudioHello(session)
        audioClient.resetStats()
        audioSendQueue.clear()
        audioDroppedChunks = 0L
        audioSendFailures = 0L
        lastAudioChunkAtMs = 0L
        lastAudioStatSendTimestampMs = 0L
        lastAudioStateSignature = null
        lastAudioStateLogTimestampMs = 0L
        audioSendExecutor = newNamedSingleThreadExecutor(
            name = "rokid-audio-send",
            processPriority = android.os.Process.THREAD_PRIORITY_DEFAULT,
        ).also { executor ->
            executor.execute { audioSendLoop() }
        }
        callbacks.onStreamingStateChanged(true)
        controlClient.sendAudioHello(
            codec = GlassAudioCapture.AUDIO_CODEC,
            sampleRateHz = GlassAudioCapture.SAMPLE_RATE_HZ,
            channels = GlassAudioCapture.CHANNEL_COUNT,
            bytesPerSample = GlassAudioCapture.BYTES_PER_SAMPLE,
        )
        controlClient.sendStreamLog(
            level = "info",
            event = "audio_stream_started",
            message = "continuous audio streaming started",
            fields = JSONObject()
                .put("sampleRateHz", GlassAudioCapture.SAMPLE_RATE_HZ)
                .put("channels", GlassAudioCapture.CHANNEL_COUNT)
                .put("chunkMs", GlassAudioCapture.CHUNK_DURATION_MS),
        )
        audioCapture = GlassAudioCapture(
            context = applicationContext,
            listener = object : GlassAudioCapture.Listener {
                override fun onAudioSourceReady(sourceLabel: String, bufferBytes: Int) {
                    synchronized(this@AudioStreamingCoordinator) {
                        latestAudioSourceLabel = sourceLabel
                    }
                    controlClient.sendStreamLog(
                        level = "info",
                        event = "audio_capture_ready",
                        message = "audio capture source ready",
                        fields = JSONObject()
                            .put("audioSource", sourceLabel)
                            .put("bufferBytes", bufferBytes),
                    )
                }

                override fun onAudioStateChanged(state: AudioCaptureState, reason: String) {
                    synchronized(this@AudioStreamingCoordinator) {
                        latestAudioSourceLabel = state.sourceLabel
                    }
                    maybeSendAudioCaptureState(state, reason)
                }

                override fun onAudioChunk(chunk: AudioPcmChunk) {
                    synchronized(this@AudioStreamingCoordinator) {
                        latestAudioSourceLabel = chunk.audioSourceLabel
                        latestAudioAvgAbs = chunk.avgAbs
                        latestAudioPeakAbs = chunk.peakAbs
                        latestAudioNonSilentRatio = chunk.nonSilentRatio
                    }
                    enqueueAudioChunk(session, chunk)
                }

                override fun onAudioError(message: String, cause: Throwable?) {
                    controlClient.sendStreamLog(
                        level = "error",
                        event = "audio_capture_error",
                        message = cause?.message ?: message,
                    )
                    stop()
                }
            },
        ).also { it.start() }
    }

    @Synchronized
    fun stop() {
        if (!audioStreamingActive && audioCapture == null && audioSendExecutor == null) return
        val status = audioClient.status()
        audioStreamingActive = false
        activeAudioSessionId = null
        activeAudioHello = null
        audioSendExecutor?.shutdownNow()
        audioSendExecutor = null
        audioCapture?.close()
        audioCapture = null
        audioClient.stop()
        controlClient.sendAudioStats(buildAudioStatsPayload(status))
        audioSendQueue.clear()
        lastAudioStateSignature = null
        lastAudioStateLogTimestampMs = 0L
        lastAudioStatSendTimestampMs = 0L
        controlClient.sendStreamLog(
            level = "info",
            event = "audio_stream_stopped",
            message = "continuous audio streaming stopped",
        )
        callbacks.onStreamingStateChanged(false)
    }

    @Synchronized
    fun maybeSendAudioStats(nowTimestampMs: Long, intervalMs: Long) {
        if (!audioStreamingActive || nowTimestampMs - lastAudioStatSendTimestampMs < intervalMs) {
            return
        }
        lastAudioStatSendTimestampMs = nowTimestampMs
        controlClient.sendAudioStats(
            buildAudioStatsPayload(
                status = audioClient.status(),
                includeLastPayloadBytes = true,
            ),
        )
    }

    override fun close() {
        stop()
        audioClient.close()
    }

    @Synchronized
    private fun buildAudioStatsPayload(
        status: JetsonAudioStatus,
        includeLastPayloadBytes: Boolean = false,
    ): JSONObject {
        val payload = JSONObject()
            .put("sentChunks", status.sentChunks)
            .put("sentBytes", status.sentBytes)
            .put("lastChunkAtMs", lastAudioChunkAtMs)
            .put("connected", status.connected)
            .put("codec", GlassAudioCapture.AUDIO_CODEC)
            .put("sampleRateHz", GlassAudioCapture.SAMPLE_RATE_HZ)
            .put("audioSource", latestAudioSourceLabel)
            .put("avgAbs", latestAudioAvgAbs)
            .put("peakAbs", latestAudioPeakAbs)
            .put("nonSilentRatio", latestAudioNonSilentRatio)
            .put("queueDepth", audioSendQueue.size)
            .put("droppedChunks", audioDroppedChunks)
            .put("sendFailures", audioSendFailures)
        if (includeLastPayloadBytes) {
            payload.put("lastPayloadBytes", status.lastPayloadBytes)
        }
        return payload
    }

    private fun audioSendLoop() {
        var consecutiveFailures = 0
        while (isStreaming()) {
            val pending = try {
                audioSendQueue.pollFirst(AUDIO_SEND_POLL_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            } catch (_: InterruptedException) {
                break
            } ?: continue
            val activeSessionId = synchronized(this) { activeAudioSessionId }
            if (!isStreaming() || activeSessionId == null || activeSessionId != pending.session.sessionId) {
                continue
            }
            val hello = synchronized(this) { activeAudioHello }
            if (hello == null || hello.sessionId != pending.session.sessionId) {
                continue
            }
            val chunkAgeMs = System.currentTimeMillis() - pending.chunk.captureTimestampMs
            if (chunkAgeMs > AUDIO_MAX_CHUNK_AGE_MS) {
                val droppedChunks = synchronized(this) {
                    audioDroppedChunks++
                    audioDroppedChunks
                }
                if (droppedChunks % 20L == 1L) {
                    controlClient.sendStreamLog(
                        level = "warn",
                        event = "audio_chunk_stale",
                        message = "dropping stale audio chunk to keep voice realtime",
                        fields = JSONObject()
                            .put("sequence", pending.chunk.sequence)
                            .put("chunkAgeMs", chunkAgeMs)
                            .put("queueSize", audioSendQueue.size)
                            .put("droppedChunks", droppedChunks),
                    )
                }
                continue
            }
            val sent = audioClient.sendChunk(pending.session, hello, pending.chunk)
            if (sent) {
                synchronized(this) {
                    lastAudioChunkAtMs = SystemClock.uptimeMillis()
                }
                consecutiveFailures = 0
                continue
            }
            val failureCount = synchronized(this) {
                audioSendFailures++
                audioSendFailures
            }
            consecutiveFailures = (consecutiveFailures + 1).coerceAtMost(6)
            if (failureCount % 5L == 1L) {
                controlClient.sendStreamLog(
                    level = "warn",
                    event = "audio_send_failed",
                    message = "audio chunk send failed from send loop",
                    fields = JSONObject()
                        .put("sequence", pending.chunk.sequence)
                        .put("payloadBytes", pending.chunk.payload.size)
                        .put("queueSize", audioSendQueue.size)
                        .put("sendFailures", failureCount),
                )
            }
            val backoffMs = (AUDIO_SEND_BACKOFF_BASE_MS shl (consecutiveFailures - 1))
                .coerceAtMost(AUDIO_SEND_BACKOFF_MAX_MS)
            try {
                Thread.sleep(backoffMs.toLong())
            } catch (_: InterruptedException) {
                break
            }
        }
    }

    private fun enqueueAudioChunk(session: JetsonSessionAccept, chunk: AudioPcmChunk) {
        trimStaleAudioChunks(session.sessionId)
        val pending = PendingAudioChunk(session = session, chunk = chunk)
        val offered = audioSendQueue.offerLast(pending)
        if (offered) {
            return
        }
        audioSendQueue.pollFirst()
        val retried = audioSendQueue.offerLast(pending)
        val droppedChunks = synchronized(this) {
            audioDroppedChunks++
            audioDroppedChunks
        }
        if (!retried || droppedChunks % 20L == 1L) {
            controlClient.sendStreamLog(
                level = "warn",
                event = "audio_queue_backpressure",
                message = "audio send queue saturated, dropping oldest chunk",
                fields = JSONObject()
                    .put("droppedChunks", droppedChunks)
                    .put("queueSize", audioSendQueue.size),
            )
        }
    }

    private fun trimStaleAudioChunks(activeSessionId: String) {
        while (audioSendQueue.size >= AUDIO_QUEUE_SOFT_LIMIT) {
            val oldest = audioSendQueue.peekFirst() ?: break
            if (oldest.session.sessionId != activeSessionId) {
                audioSendQueue.pollFirst()
                synchronized(this) { audioDroppedChunks++ }
                continue
            }
            val ageMs = System.currentTimeMillis() - oldest.chunk.captureTimestampMs
            if (ageMs <= AUDIO_MAX_CHUNK_AGE_MS) {
                break
            }
            audioSendQueue.pollFirst()
            synchronized(this) { audioDroppedChunks++ }
        }
    }

    private fun buildAudioHello(session: JetsonSessionAccept): AudioStreamHello =
        AudioStreamHello(
            sessionId = session.sessionId,
            codec = GlassAudioCapture.AUDIO_CODEC,
            sampleRateHz = GlassAudioCapture.SAMPLE_RATE_HZ,
            channels = GlassAudioCapture.CHANNEL_COUNT,
            bytesPerSample = GlassAudioCapture.BYTES_PER_SAMPLE,
        )

    private fun maybeSendAudioCaptureState(state: AudioCaptureState, reason: String) {
        val now = SystemClock.uptimeMillis()
        val signature = listOf(
            state.sourceLabel,
            state.preferredDeviceLabel ?: "",
            state.routedDeviceLabel ?: "",
            state.silenced.toString(),
            state.sourceLocked.toString(),
            state.capturePathSourceLabel ?: "",
            state.activeConfigCount.toString(),
            state.activeMicrophoneCount.toString(),
        ).joinToString("|")
        val isConfigNoise = reason == "recording_config_changed"
        val shouldSend = synchronized(this) {
            signature != lastAudioStateSignature ||
                !isConfigNoise ||
                now - lastAudioStateLogTimestampMs >= AUDIO_STATE_LOG_INTERVAL_MS
        }
        if (!shouldSend) {
            return
        }
        synchronized(this) {
            lastAudioStateSignature = signature
            lastAudioStateLogTimestampMs = now
        }
        controlClient.sendStreamLog(
            level = "info",
            event = "audio_capture_state",
            message = "audio capture state updated",
            fields = JSONObject()
                .put("reason", reason)
                .put("audioSource", state.sourceLabel)
                .put("preferredDevice", state.preferredDeviceLabel ?: "")
                .put("routedDevice", state.routedDeviceLabel ?: "")
                .put("silenced", state.silenced)
                .put("sourceLocked", state.sourceLocked)
                .put("capturePathSource", state.capturePathSourceLabel ?: "")
                .put("activeConfigCount", state.activeConfigCount)
                .put("activeConfigSummary", state.activeConfigSummary ?: "")
                .put("activeMicrophoneCount", state.activeMicrophoneCount),
        )
    }

    private data class PendingAudioChunk(
        val session: JetsonSessionAccept,
        val chunk: AudioPcmChunk,
    )

    companion object {
        private const val AUDIO_SEND_QUEUE_CAPACITY = 8
        private const val AUDIO_QUEUE_SOFT_LIMIT = 6
        private const val AUDIO_SEND_POLL_TIMEOUT_MS = 120L
        private const val AUDIO_SEND_BACKOFF_BASE_MS = 40
        private const val AUDIO_SEND_BACKOFF_MAX_MS = 320
        private const val AUDIO_MAX_CHUNK_AGE_MS = 700L
        private const val AUDIO_STATE_LOG_INTERVAL_MS = 1500L
    }
}
