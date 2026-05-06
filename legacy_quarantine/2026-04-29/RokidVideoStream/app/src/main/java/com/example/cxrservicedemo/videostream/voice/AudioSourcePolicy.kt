package com.example.cxrservicedemo.videostream.voice

import android.media.MediaRecorder

data class AudioSourceCandidate(
    val source: Int,
    val label: String
)

object AudioSourcePolicy {
    const val SOURCE_LOCK_CHUNKS = 3

    private const val MIC_ONLY_SOURCE_POLICY = true
    private const val STARTUP_SOURCE_REPROBE_CHUNKS = 8
    private const val SOURCE_REPROBE_CHUNKS = 28
    private const val DEAD_SOURCE_AVG_ABS = 4
    private const val DEAD_SOURCE_PEAK_ABS = 32
    private const val DEAD_SOURCE_RATIO = 0.0015f
    private const val LOCK_SOURCE_AVG_ABS = 48
    private const val LOCK_SOURCE_PEAK_ABS = 384
    private const val LOCK_SOURCE_RATIO = 0.04f
    private const val PREFERRED_SOURCE_REPROBE_CHUNKS = 42
    private const val PROVEN_SOURCE_REPROBE_CHUNKS = 90
    private const val PROVEN_PREFERRED_SOURCE_REPROBE_CHUNKS = 120
    private const val SOURCE_LOCK_RECHECK_GRACE_MS = 4000L
    private const val PROVEN_SOURCE_LOCK_RECHECK_GRACE_MS = 12_000L
    private const val LOCKED_SOURCE_MAX_AVG_ABS = 12
    private const val LOCKED_SOURCE_MAX_PEAK_ABS = 96
    private const val LOCKED_SOURCE_MAX_RATIO = 0.012f

    fun sourceCandidates(preferredSourceLabel: String?): List<AudioSourceCandidate> {
        if (MIC_ONLY_SOURCE_POLICY) {
            return listOf(AudioSourceCandidate(MediaRecorder.AudioSource.MIC, "MIC"))
        }
        val sources = mutableListOf(
            AudioSourceCandidate(MediaRecorder.AudioSource.MIC, "MIC"),
            AudioSourceCandidate(MediaRecorder.AudioSource.DEFAULT, "DEFAULT"),
            AudioSourceCandidate(MediaRecorder.AudioSource.CAMCORDER, "CAMCORDER"),
            AudioSourceCandidate(MediaRecorder.AudioSource.UNPROCESSED, "UNPROCESSED")
        )
        if (!preferredSourceLabel.isNullOrBlank()) {
            sources.sortBy { candidate ->
                if (candidate.label == preferredSourceLabel) 0 else 1
            }
        }
        return sources
    }

    fun shouldReprobeSource(stats: AudioSignalStats): Boolean =
        stats.avgAbs <= DEAD_SOURCE_AVG_ABS &&
            stats.peakAbs <= DEAD_SOURCE_PEAK_ABS &&
            stats.nonSilentRatio <= DEAD_SOURCE_RATIO

    fun hasUsableVoice(stats: AudioSignalStats): Boolean =
        stats.avgAbs >= LOCK_SOURCE_AVG_ABS ||
            (stats.peakAbs >= LOCK_SOURCE_PEAK_ABS && stats.nonSilentRatio >= LOCK_SOURCE_RATIO)

    fun isLockedSourceDegraded(stats: AudioSignalStats): Boolean =
        stats.avgAbs <= LOCKED_SOURCE_MAX_AVG_ABS &&
            stats.peakAbs <= LOCKED_SOURCE_MAX_PEAK_ABS &&
            stats.nonSilentRatio <= LOCKED_SOURCE_MAX_RATIO

    fun lockRecheckGraceMs(
        sourceHasProvenVoice: Boolean,
        sourceLabel: String,
        rememberedSourceLabel: String?,
    ): Long {
        return when {
            sourceHasProvenVoice && sourceLabel == rememberedSourceLabel -> PROVEN_SOURCE_LOCK_RECHECK_GRACE_MS
            sourceHasProvenVoice -> PROVEN_SOURCE_LOCK_RECHECK_GRACE_MS
            else -> SOURCE_LOCK_RECHECK_GRACE_MS
        }
    }

    fun reprobeThreshold(
        lastUsableVoiceAtMs: Long,
        sourceHasProvenVoice: Boolean,
        sourceLabel: String,
        rememberedSourceLabel: String?,
    ): Int {
        return when {
            lastUsableVoiceAtMs <= 0L -> STARTUP_SOURCE_REPROBE_CHUNKS
            sourceHasProvenVoice && sourceLabel == rememberedSourceLabel -> PROVEN_PREFERRED_SOURCE_REPROBE_CHUNKS
            sourceHasProvenVoice -> PROVEN_SOURCE_REPROBE_CHUNKS
            sourceLabel == rememberedSourceLabel -> PREFERRED_SOURCE_REPROBE_CHUNKS
            else -> SOURCE_REPROBE_CHUNKS
        }
    }

    fun nextCandidateIndex(
        candidates: List<AudioSourceCandidate>,
        currentIndex: Int,
        retryNotBeforeMs: LongArray,
        nowElapsedMs: Long,
    ): Int {
        if (candidates.size <= 1) {
            return -1
        }
        for (offset in 1..candidates.size) {
            val index = (currentIndex + offset) % candidates.size
            if (retryNotBeforeMs.getOrNull(index)?.let { nowElapsedMs >= it } != false) {
                return index
            }
        }
        return (currentIndex + 1) % candidates.size
    }
}
