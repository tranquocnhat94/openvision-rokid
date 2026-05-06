package com.example.cxrservicedemo.videostream.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AudioPolicyRuntimeTest {
    @Test
    fun `signal analyzer reports average peak and ratio`() {
        val pcm = byteArrayOf(
            0x00, 0x00,
            0x40, 0x00,
            0x00, 0x01.toByte(),
            0x00, 0x02.toByte()
        )

        val stats = AudioSignalAnalyzer.analyzePcm(pcm)

        assertEquals(208, stats.avgAbs)
        assertEquals(512, stats.peakAbs)
        assertEquals(0.75f, stats.nonSilentRatio)
    }

    @Test
    fun `source policy stays mic only on current thin client path`() {
        val candidates = AudioSourcePolicy.sourceCandidates(preferredSourceLabel = "CAMCORDER")

        assertEquals(listOf("MIC"), candidates.map { it.label })
    }

    @Test
    fun `voice and reprobe thresholds match current stability policy`() {
        val strongStats = AudioSignalStats(avgAbs = 60, peakAbs = 420, nonSilentRatio = 0.08f)
        val deadStats = AudioSignalStats(avgAbs = 2, peakAbs = 20, nonSilentRatio = 0.0005f)
        val degradedStats = AudioSignalStats(avgAbs = 8, peakAbs = 64, nonSilentRatio = 0.01f)

        assertTrue(AudioSourcePolicy.hasUsableVoice(strongStats))
        assertTrue(AudioSourcePolicy.shouldReprobeSource(deadStats))
        assertTrue(AudioSourcePolicy.isLockedSourceDegraded(degradedStats))
        assertEquals(
            120,
            AudioSourcePolicy.reprobeThreshold(
                lastUsableVoiceAtMs = 10L,
                sourceHasProvenVoice = true,
                sourceLabel = "MIC",
                rememberedSourceLabel = "MIC"
            )
        )
        assertEquals(
            -1,
            AudioSourcePolicy.nextCandidateIndex(
                candidates = AudioSourcePolicy.sourceCandidates(preferredSourceLabel = null),
                currentIndex = 0,
                retryNotBeforeMs = longArrayOf(0L),
                nowElapsedMs = 100L
            )
        )
        assertFalse(AudioSourcePolicy.hasUsableVoice(deadStats))
    }
}
