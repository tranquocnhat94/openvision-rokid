package com.example.cxrservicedemo.videostream.voice

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.AudioRecordingConfiguration
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.SystemClock
import android.util.Log
import com.example.cxrservicedemo.videostream.newNamedSingleThreadExecutor
import java.io.Closeable
import java.util.concurrent.Executor
import java.util.concurrent.ExecutorService
import java.util.concurrent.atomic.AtomicBoolean

data class AudioPcmChunk(
    val sequence: Long,
    val captureTimestampMs: Long,
    val payload: ByteArray,
    val avgAbs: Int,
    val peakAbs: Int,
    val nonSilentRatio: Float,
    val audioSourceLabel: String
)

data class AudioCaptureState(
    val sourceLabel: String,
    val preferredDeviceLabel: String?,
    val routedDeviceLabel: String?,
    val silenced: Boolean,
    val sourceLocked: Boolean,
    val capturePathSourceLabel: String?,
    val activeConfigCount: Int,
    val activeConfigSummary: String?,
    val activeMicrophoneCount: Int
)

class GlassAudioCapture(
    context: Context,
    private val listener: Listener
) : Closeable {

    interface Listener {
        fun onAudioSourceReady(sourceLabel: String, bufferBytes: Int)
        fun onAudioStateChanged(state: AudioCaptureState, reason: String)
        fun onAudioChunk(chunk: AudioPcmChunk)
        fun onAudioError(message: String, cause: Throwable? = null)
    }

    private val appContext = context.applicationContext
    private val audioManager = appContext.getSystemService(AudioManager::class.java)
    private val preferences by lazy {
        appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }
    private val running = AtomicBoolean(false)
    private val executor: ExecutorService = newNamedSingleThreadExecutor(
        name = "rokid-audio-capture",
        processPriority = android.os.Process.THREAD_PRIORITY_URGENT_AUDIO
    )
    private var audioRecord: AudioRecord? = null
    private var recordingCallback: AudioManager.AudioRecordingCallback? = null
    private var sequence = 0L

    fun start() {
        if (!running.compareAndSet(false, true)) return
        executor.execute {
            try {
                captureLoop()
            } catch (error: Exception) {
                if (running.get()) {
                    listener.onAudioError("audio capture failed", error)
                } else {
                    Log.i(TAG, "audio capture closed during shutdown", error)
                }
            } finally {
                releaseRecord()
                running.set(false)
            }
        }
    }

    fun stop() {
        running.set(false)
        releaseRecord()
    }

    override fun close() {
        stop()
        executor.shutdown()
    }

    private fun captureLoop() {
        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE_HZ,
            CHANNEL_CONFIG,
            AUDIO_ENCODING
        ).coerceAtLeast(PCM_CHUNK_BYTES * 2)
        var rememberedSourceLabel = loadPreferredSourceLabel()
        val candidates = AudioSourcePolicy.sourceCandidates(rememberedSourceLabel)
        val candidateRetryNotBeforeMs = LongArray(candidates.size)
        var candidateIndex = 0
        var recordBundle = openRecord(candidates, candidateIndex, minBuffer)
        var record = recordBundle.record
        var sourceLabel = recordBundle.sourceLabel
        var preferredDeviceLabel = applyPreferredInputDevice(record)
        audioRecord = record
        val buffer = ByteArray(PCM_CHUNK_BYTES)
        listener.onAudioSourceReady(sourceLabel, minBuffer)
        var sourceLocked = false
        var sourceHasProvenVoice = false
        var sourceSilenced = false
        var strongSignalStreak = 0
        var lockedBadStreak = 0
        var lastUsableVoiceAtMs = 0L
        var lastSourceSwitchAtMs = SystemClock.elapsedRealtime()
        attachRecordingCallback(record, sourceLabel, preferredDeviceLabel) { state ->
            sourceSilenced = state.silenced
            listener.onAudioStateChanged(
                state.copy(sourceLocked = sourceLocked),
                reason = "recording_config_changed"
            )
        }
        record.startRecording()
        emitState(
            record = record,
            sourceLabel = sourceLabel,
            preferredDeviceLabel = preferredDeviceLabel,
            silenced = false,
            sourceLocked = sourceLocked,
            reason = "source_ready"
        )
        var silentStreak = 0

        while (running.get()) {
            val readBytes = record.read(buffer, 0, buffer.size)
            if (readBytes <= 0) {
                if (!running.get()) break
                continue
            }
            val nowElapsedMs = SystemClock.elapsedRealtime()
            val captureTimestampMs = System.currentTimeMillis()
            val payload = buffer.copyOf(readBytes)
            val signalStats = AudioSignalAnalyzer.analyzePcm(payload)
            val avgAbs = signalStats.avgAbs
            val peakAbs = signalStats.peakAbs
            val nonSilentRatio = signalStats.nonSilentRatio
            if (AudioSourcePolicy.hasUsableVoice(signalStats)) {
                lastUsableVoiceAtMs = nowElapsedMs
                sourceHasProvenVoice = true
                strongSignalStreak += 1
                silentStreak = 0
                lockedBadStreak = 0
                if (!sourceLocked && strongSignalStreak >= AudioSourcePolicy.SOURCE_LOCK_CHUNKS) {
                    sourceLocked = true
                    if (sourceLabel != rememberedSourceLabel) {
                        savePreferredSourceLabel(sourceLabel)
                        rememberedSourceLabel = sourceLabel
                    }
                    emitState(
                        record = record,
                        sourceLabel = sourceLabel,
                        preferredDeviceLabel = preferredDeviceLabel,
                        silenced = false,
                        sourceLocked = true,
                        reason = "source_locked"
                    )
                }
            } else {
                if (!sourceLocked) {
                    strongSignalStreak = 0
                } else {
                    val lockRecheckGraceMs = AudioSourcePolicy.lockRecheckGraceMs(
                        sourceHasProvenVoice = sourceHasProvenVoice,
                        sourceLabel = sourceLabel,
                        rememberedSourceLabel = rememberedSourceLabel
                    )
                    val staleLockedSource = lastUsableVoiceAtMs <= 0L ||
                        (nowElapsedMs - lastUsableVoiceAtMs) >= lockRecheckGraceMs
                    lockedBadStreak = when {
                        AudioSourcePolicy.isLockedSourceDegraded(signalStats) -> lockedBadStreak + 1
                        else -> 0
                    }
                    if (staleLockedSource && lockedBadStreak >= SOURCE_UNLOCK_BAD_CHUNKS) {
                        sourceLocked = false
                        strongSignalStreak = 0
                        lockedBadStreak = 0
                        emitState(
                            record = record,
                            sourceLabel = sourceLabel,
                            preferredDeviceLabel = preferredDeviceLabel,
                            silenced = sourceSilenced,
                            sourceLocked = false,
                            reason = "source_unlock_degraded"
                        )
                    }
                }
            }
            if (!sourceLocked) {
                val recentlyHadVoice = lastUsableVoiceAtMs > 0L &&
                    (nowElapsedMs - lastUsableVoiceAtMs) < SOURCE_SILENCE_REPROBE_GRACE_MS
                val reprobeCoolingDown =
                    (nowElapsedMs - lastSourceSwitchAtMs) < SOURCE_REPROBE_COOLDOWN_MS
                silentStreak = when {
                    reprobeCoolingDown -> 0
                    AudioSourcePolicy.shouldReprobeSource(signalStats) -> {
                        silentStreak + when {
                            recentlyHadVoice -> 0
                            else -> 1
                        }
                    }
                    else -> 0
                }
            }
            listener.onAudioChunk(
                AudioPcmChunk(
                    sequence = ++sequence,
                    captureTimestampMs = captureTimestampMs,
                    payload = payload,
                    avgAbs = avgAbs,
                    peakAbs = peakAbs,
                    nonSilentRatio = nonSilentRatio,
                    audioSourceLabel = sourceLabel
                )
            )

            val reprobeThreshold = AudioSourcePolicy.reprobeThreshold(
                lastUsableVoiceAtMs = lastUsableVoiceAtMs,
                sourceHasProvenVoice = sourceHasProvenVoice,
                sourceLabel = sourceLabel,
                rememberedSourceLabel = rememberedSourceLabel
            )
            if (silentStreak >= reprobeThreshold) {
                candidateRetryNotBeforeMs[candidateIndex] =
                    nowElapsedMs + if (lastUsableVoiceAtMs <= 0L) {
                        DEAD_SOURCE_RETRY_COOLDOWN_MS
                    } else {
                        SOURCE_REVISIT_COOLDOWN_MS
                    }
                val nextIndex = AudioSourcePolicy.nextCandidateIndex(
                    candidates = candidates,
                    currentIndex = candidateIndex,
                    retryNotBeforeMs = candidateRetryNotBeforeMs,
                    nowElapsedMs = nowElapsedMs
                )
                val reopenIndex = if (nextIndex >= 0) nextIndex else candidateIndex
                if (reopenIndex >= 0) {
                    val restartingSameSource = reopenIndex == candidateIndex
                    Log.i(
                        TAG,
                        if (restartingSameSource) {
                            "audio source $sourceLabel looks silent, restarting same source"
                        } else {
                            "audio source $sourceLabel looks silent, probing next source"
                        }
                    )
                    try {
                        record.stop()
                    } catch (_: Exception) {
                    }
                    unregisterRecordingCallback(record)
                    recordingCallback = null
                    record.release()
                    candidateIndex = reopenIndex
                    recordBundle = openRecord(candidates, candidateIndex, minBuffer)
                    record = recordBundle.record
                    sourceLabel = recordBundle.sourceLabel
                    preferredDeviceLabel = applyPreferredInputDevice(record)
                    audioRecord = record
                    silentStreak = 0
                    strongSignalStreak = 0
                    lockedBadStreak = 0
                    sourceLocked = false
                    sourceHasProvenVoice = false
                    sourceSilenced = false
                    lastUsableVoiceAtMs = 0L
                    lastSourceSwitchAtMs = SystemClock.elapsedRealtime()
                    listener.onAudioSourceReady(sourceLabel, minBuffer)
                    attachRecordingCallback(record, sourceLabel, preferredDeviceLabel) { state ->
                        sourceSilenced = state.silenced
                        listener.onAudioStateChanged(
                            state.copy(sourceLocked = sourceLocked),
                            reason = "recording_config_changed"
                        )
                    }
                    record.startRecording()
                    emitState(
                        record = record,
                        sourceLabel = sourceLabel,
                        preferredDeviceLabel = preferredDeviceLabel,
                        silenced = false,
                        sourceLocked = sourceLocked,
                        reason = if (restartingSameSource) "source_restart" else "source_reprobe"
                    )
                } else {
                    silentStreak = 0
                }
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun openRecord(
        candidates: List<AudioSourceCandidate>,
        startIndex: Int,
        minBuffer: Int
    ): AudioRecordBundle {
        var lastError: Throwable? = null
        if (candidates.isEmpty()) {
            throw IllegalStateException("AudioRecord source list is empty")
        }
        for (offset in candidates.indices) {
            val index = (startIndex + offset) % candidates.size
            val candidate = candidates[index]
            try {
                val record = AudioRecord(
                    candidate.source,
                    SAMPLE_RATE_HZ,
                    CHANNEL_CONFIG,
                    AUDIO_ENCODING,
                    minBuffer
                )
                if (record.state == AudioRecord.STATE_INITIALIZED) {
                    return AudioRecordBundle(record = record, sourceLabel = candidate.label)
                }
                record.release()
            } catch (error: Throwable) {
                lastError = error
            }
        }
        throw IllegalStateException("AudioRecord not initialized for any source", lastError)
    }

    private fun applyPreferredInputDevice(record: AudioRecord): String? {
        val preferred = selectPreferredInputDevice() ?: return null
        return try {
            record.setPreferredDevice(preferred)
            deviceLabel(preferred)
        } catch (_: Exception) {
            null
        }
    }

    private fun selectPreferredInputDevice(): AudioDeviceInfo? {
        val manager = audioManager ?: return null
        val inputs = manager.getDevices(AudioManager.GET_DEVICES_INPUTS).toList()
        return inputs.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_MIC }
            ?: inputs.firstOrNull()
    }

    private fun attachRecordingCallback(
        record: AudioRecord,
        sourceLabel: String,
        preferredDeviceLabel: String?,
        onChanged: (state: AudioCaptureState) -> Unit
    ) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            emitState(
                record = record,
                sourceLabel = sourceLabel,
                preferredDeviceLabel = preferredDeviceLabel ?: deviceLabel(record.preferredDevice),
                silenced = false,
                sourceLocked = false,
                reason = "routing_snapshot"
            )
            return
        }
        recordingCallback?.let {
            audioRecord?.let(::unregisterRecordingCallback)
        }
        val targetAudioSessionId = record.audioSessionId
        val callback = object : AudioManager.AudioRecordingCallback() {
            override fun onRecordingConfigChanged(configs: MutableList<AudioRecordingConfiguration>) {
                val activeConfig = configs.firstOrNull { configuration ->
                    configuration.clientAudioSessionId == targetAudioSessionId
                } ?: return
                onChanged(
                    buildCaptureState(
                        record = record,
                        sourceLabel = sourceLabel,
                        preferredDeviceLabel = preferredDeviceLabel,
                        silenced = activeConfig.isClientSilenced,
                        sourceLocked = false,
                        capturePathSourceLabel = audioSourceLabel(activeConfig.audioSource),
                        activeConfigCount = configs.size,
                        activeConfigSummary = summarizeActiveConfigs(configs)
                    )
                )
            }
        }
        recordingCallback = callback
        try {
            record.registerAudioRecordingCallback(DirectExecutor, callback)
        } catch (_: Exception) {
        }
    }

    private fun emitState(
        record: AudioRecord,
        sourceLabel: String,
        preferredDeviceLabel: String?,
        silenced: Boolean,
        sourceLocked: Boolean,
        reason: String
    ) {
        listener.onAudioStateChanged(
            buildCaptureState(
                record = record,
                sourceLabel = sourceLabel,
                preferredDeviceLabel = preferredDeviceLabel,
                silenced = silenced,
                sourceLocked = sourceLocked
            ),
            reason = reason
        )
    }

    private fun buildCaptureState(
        record: AudioRecord,
        sourceLabel: String,
        preferredDeviceLabel: String?,
        silenced: Boolean,
        sourceLocked: Boolean,
        capturePathSourceLabel: String? = null,
        activeConfigCount: Int = 0,
        activeConfigSummary: String? = null
    ): AudioCaptureState =
        AudioCaptureState(
            sourceLabel = sourceLabel,
            preferredDeviceLabel = preferredDeviceLabel,
            routedDeviceLabel = deviceLabel(record.routedDevice),
            silenced = silenced,
            sourceLocked = sourceLocked,
            capturePathSourceLabel = capturePathSourceLabel,
            activeConfigCount = activeConfigCount,
            activeConfigSummary = activeConfigSummary,
            activeMicrophoneCount = activeMicrophoneCount(record)
        )

    private fun deviceLabel(device: AudioDeviceInfo?): String? {
        if (device == null) return null
        val name = device.productName?.toString()?.trim().orEmpty()
        val typeLabel = when (device.type) {
            AudioDeviceInfo.TYPE_BUILTIN_MIC -> "BUILTIN_MIC"
            AudioDeviceInfo.TYPE_BLE_HEADSET -> "BLE_HEADSET"
            AudioDeviceInfo.TYPE_BLUETOOTH_SCO -> "BLUETOOTH_SCO"
            AudioDeviceInfo.TYPE_USB_DEVICE -> "USB_DEVICE"
            AudioDeviceInfo.TYPE_USB_HEADSET -> "USB_HEADSET"
            AudioDeviceInfo.TYPE_WIRED_HEADSET -> "WIRED_HEADSET"
            else -> "TYPE_${device.type}"
        }
        return if (name.isBlank()) typeLabel else "$typeLabel:$name"
    }

    private fun summarizeActiveConfigs(configs: List<AudioRecordingConfiguration>): String =
        configs.joinToString(";") { configuration ->
            val pathSource = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                audioSourceLabel(configuration.audioSource)
            } else {
                "unknown"
            }
            val silenced = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                configuration.isClientSilenced
            } else {
                false
            }
            "${configuration.clientAudioSessionId}:${audioSourceLabel(configuration.clientAudioSource)}->$pathSource:${if (silenced) "silenced" else "live"}"
        }

    private fun activeMicrophoneCount(record: AudioRecord): Int =
        try {
            record.activeMicrophones?.size ?: 0
        } catch (_: Throwable) {
            0
        }

    private fun audioSourceLabel(source: Int): String =
        when (source) {
            MediaRecorder.AudioSource.DEFAULT -> "DEFAULT"
            MediaRecorder.AudioSource.MIC -> "MIC"
            MediaRecorder.AudioSource.CAMCORDER -> "CAMCORDER"
            MediaRecorder.AudioSource.VOICE_RECOGNITION -> "VOICE_RECOGNITION"
            MediaRecorder.AudioSource.VOICE_COMMUNICATION -> "VOICE_COMMUNICATION"
            MediaRecorder.AudioSource.UNPROCESSED -> "UNPROCESSED"
            MediaRecorder.AudioSource.VOICE_PERFORMANCE -> "VOICE_PERFORMANCE"
            MediaRecorder.AudioSource.VOICE_CALL -> "VOICE_CALL"
            MediaRecorder.AudioSource.VOICE_UPLINK -> "VOICE_UPLINK"
            MediaRecorder.AudioSource.VOICE_DOWNLINK -> "VOICE_DOWNLINK"
            else -> "SRC_$source"
        }

    private fun loadPreferredSourceLabel(): String? =
        preferences.getString(PREF_LAST_GOOD_SOURCE_LABEL, null)?.takeIf { value ->
            value in setOf("MIC", "DEFAULT", "CAMCORDER", "UNPROCESSED")
        }

    private fun savePreferredSourceLabel(sourceLabel: String) {
        preferences.edit().putString(PREF_LAST_GOOD_SOURCE_LABEL, sourceLabel).apply()
    }

    private fun releaseRecord() {
        val current = audioRecord ?: return
        audioRecord = null
        unregisterRecordingCallback(current)
        recordingCallback = null
        try {
            current.stop()
        } catch (error: Exception) {
            Log.w(TAG, "audio stop failed", error)
        }
        current.release()
    }

    private fun unregisterRecordingCallback(record: AudioRecord) {
        val callback = recordingCallback ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                record.unregisterAudioRecordingCallback(callback)
            } catch (_: Exception) {
            }
        }
    }

    companion object {
        const val SAMPLE_RATE_HZ = 16_000
        const val CHANNEL_COUNT = 1
        const val BYTES_PER_SAMPLE = 2
        const val AUDIO_CODEC = "pcm_s16le"
        const val CHUNK_DURATION_MS = 80

        private const val TAG = "GlassAudioCapture"
        private const val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO
        private const val AUDIO_ENCODING = AudioFormat.ENCODING_PCM_16BIT
        private const val PCM_CHUNK_MS = CHUNK_DURATION_MS
        private const val PCM_CHUNK_BYTES =
            SAMPLE_RATE_HZ * BYTES_PER_SAMPLE * PCM_CHUNK_MS / 1000
        private const val SOURCE_SILENCE_REPROBE_GRACE_MS = 1200L
        private const val SOURCE_REPROBE_COOLDOWN_MS = 5000L
        private const val DEAD_SOURCE_RETRY_COOLDOWN_MS = 12_000L
        private const val SOURCE_REVISIT_COOLDOWN_MS = 20_000L
        private const val SOURCE_UNLOCK_BAD_CHUNKS = 18
        private const val PREFS_NAME = "rokid_audio_capture"
        private const val PREF_LAST_GOOD_SOURCE_LABEL = "last_good_source_label"
        private val DirectExecutor = Executor { runnable -> runnable.run() }
    }
}

private data class AudioRecordBundle(
    val record: AudioRecord,
    val sourceLabel: String
)
