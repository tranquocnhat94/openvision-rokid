package com.example.cxrservicedemo.videostream

import com.example.cxrservicedemo.videostream.transport.JetsonControlStatus
import com.example.cxrservicedemo.videostream.transport.JetsonSessionAccept

internal data class GlassesSessionTransition(
    val previousSession: JetsonSessionAccept?,
    val nextSession: JetsonSessionAccept?,
    val transportChanged: Boolean,
    val sessionChanged: Boolean,
    val shouldClearHud: Boolean,
    val shouldStopMedia: Boolean,
    val shouldResetSpeech: Boolean,
)

internal class GlassesSessionController {
    private var currentSession: JetsonSessionAccept? = null

    fun onControlStatus(status: JetsonControlStatus): GlassesSessionTransition {
        val previousSession = currentSession
        val shouldClearSession = !status.connected || status.sessionId == null
        if (shouldClearSession) {
            currentSession = null
            return GlassesSessionTransition(
                previousSession = previousSession,
                nextSession = null,
                transportChanged = false,
                sessionChanged = previousSession != null,
                shouldClearHud = true,
                shouldStopMedia = true,
                shouldResetSpeech = true,
            )
        }
        return GlassesSessionTransition(
            previousSession = previousSession,
            nextSession = currentSession,
            transportChanged = false,
            sessionChanged = false,
            shouldClearHud = false,
            shouldStopMedia = false,
            shouldResetSpeech = false,
        )
    }

    fun onSessionAccepted(session: JetsonSessionAccept): GlassesSessionTransition {
        val previousSession = currentSession
        val transportChanged = previousSession == null || sessionTransportChanged(previousSession, session)
        val sessionChanged = previousSession?.sessionId != null && previousSession.sessionId != session.sessionId
        currentSession = session
        return GlassesSessionTransition(
            previousSession = previousSession,
            nextSession = session,
            transportChanged = transportChanged,
            sessionChanged = sessionChanged,
            shouldClearHud = sessionChanged || previousSession == null,
            shouldStopMedia = transportChanged,
            shouldResetSpeech = true,
        )
    }

    private fun sessionTransportChanged(
        previous: JetsonSessionAccept,
        next: JetsonSessionAccept
    ): Boolean =
        previous.sessionId != next.sessionId ||
            previous.videoHost != next.videoHost ||
            previous.videoPort != next.videoPort ||
            previous.audioHost != next.audioHost ||
            previous.audioPort != next.audioPort
}
