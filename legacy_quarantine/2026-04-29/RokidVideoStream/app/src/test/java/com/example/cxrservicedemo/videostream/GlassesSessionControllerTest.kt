package com.example.cxrservicedemo.videostream

import com.example.cxrservicedemo.videostream.transport.JetsonControlStatus
import com.example.cxrservicedemo.videostream.transport.JetsonSessionAccept
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class GlassesSessionControllerTest {
    @Test
    fun controlStatusWithoutSessionClearsMediaAndHud() {
        val controller = GlassesSessionController()
        controller.onSessionAccepted(session("sess_a"))

        val transition = controller.onControlStatus(
            JetsonControlStatus(
                connected = true,
                targetLabel = "jetson",
                sessionId = null
            )
        )

        assertNull(transition.nextSession)
        assertTrue(transition.shouldClearHud)
        assertTrue(transition.shouldStopMedia)
        assertTrue(transition.shouldResetSpeech)
    }

    @Test
    fun acceptedSessionTracksTransportChanges() {
        val controller = GlassesSessionController()
        val first = controller.onSessionAccepted(session("sess_a", videoPort = 5001))
        val same = controller.onSessionAccepted(session("sess_a", videoPort = 5001))
        val moved = controller.onSessionAccepted(session("sess_a", videoPort = 5002))

        assertTrue(first.transportChanged)
        assertTrue(first.shouldClearHud)
        assertFalse(same.transportChanged)
        assertFalse(same.shouldClearHud)
        assertTrue(moved.transportChanged)
        assertTrue(moved.shouldStopMedia)
        assertFalse(moved.sessionChanged)
    }

    private fun session(
        sessionId: String,
        videoPort: Int = 5001,
    ): JetsonSessionAccept =
        JetsonSessionAccept(
            sessionId = sessionId,
            controlHeartbeatMs = 1000,
            resultThrottleMs = 150,
            videoHost = "jetson",
            videoPort = videoPort,
            mediaTransport = "tcp_h264",
            audioHost = "jetson",
            audioPort = 6001,
            audioCodec = "pcm_s16le"
        )
}
