package com.example.cxrservicedemo.videostream.voice

import kotlin.math.abs

data class AudioSignalStats(
    val avgAbs: Int,
    val peakAbs: Int,
    val nonSilentRatio: Float
)

object AudioSignalAnalyzer {
    private const val NON_SILENT_SAMPLE_THRESHOLD = 64

    fun analyzePcm(payload: ByteArray): AudioSignalStats {
        val usableBytes = payload.size - (payload.size % 2)
        if (usableBytes <= 0) {
            return AudioSignalStats(avgAbs = 0, peakAbs = 0, nonSilentRatio = 0f)
        }
        var total = 0L
        var peak = 0
        var nonSilent = 0
        var count = 0
        var index = 0
        while (index + 1 < usableBytes) {
            val sample = ((payload[index + 1].toInt() shl 8) or (payload[index].toInt() and 0xff)).toShort().toInt()
            val amplitude = abs(sample)
            total += amplitude.toLong()
            if (amplitude > peak) peak = amplitude
            if (amplitude >= NON_SILENT_SAMPLE_THRESHOLD) nonSilent += 1
            count += 1
            index += 2
        }
        if (count == 0) {
            return AudioSignalStats(avgAbs = 0, peakAbs = 0, nonSilentRatio = 0f)
        }
        return AudioSignalStats(
            avgAbs = (total / count).toInt(),
            peakAbs = peak,
            nonSilentRatio = nonSilent.toFloat() / count.toFloat()
        )
    }
}
