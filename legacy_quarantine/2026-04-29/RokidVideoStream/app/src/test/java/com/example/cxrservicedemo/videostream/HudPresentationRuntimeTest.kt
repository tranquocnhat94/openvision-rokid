package com.example.cxrservicedemo.videostream

import com.example.cxrservicedemo.videostream.transport.JetsonHudGalleryItem
import com.example.cxrservicedemo.videostream.transport.JetsonHudScene
import com.example.cxrservicedemo.videostream.transport.JetsonSpeechState
import com.example.cxrservicedemo.videostream.transport.JetsonVisionResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HudPresentationRuntimeTest {
    @Test
    fun genericHudTextIsFiltered() {
        assertNull(HudPresentationRuntime.sanitizeText("Jetson ready"))
        assertEquals("Target found", HudPresentationRuntime.sanitizeText("Target found"))
    }

    @Test
    fun targetSearchScenePrefersSceneStatusOverPassiveSpeech() {
        val speechState = JetsonSpeechState(
            listening = true,
            taskLabel = "voice live",
            transcriptHint = null,
            stateLabel = "listening"
        )
        val scene = JetsonHudScene(
            sessionId = "sess_demo",
            sceneId = "scene_1",
            taskChip = "Tim nguoi ao vang",
            micChip = "target search",
            answerText = null,
            statusText = "Dang quet khung hinh",
            galleryLabels = emptyList(),
            galleryItems = listOf(
                JetsonHudGalleryItem(
                    label = "Ao vang",
                    secondaryText = "Ben trai",
                    trackId = "12",
                    selected = true,
                    thumbBase64 = null
                )
            ),
            directionHint = "Ben trai",
            targetMarker = null
        )

        val presentation = HudPresentationRuntime.resolvePresentation(
            activeSessionId = "sess_demo",
            speechState = speechState,
            voiceScene = scene,
            visionResult = null,
            liveTranscript = null,
            effectiveSpeechTaskLabel = "voice live",
            meaningfulSceneActive = false,
            updatedAtMs = 1234L
        )

        assertNotNull(presentation)
        assertEquals("Dang quet khung hinh", presentation?.answerText)
        assertEquals("target_search", presentation?.sourceLabel)
    }

    @Test
    fun commandOnlySpeechDoesNotCreateCenterPresentation() {
        val presentation = HudPresentationRuntime.resolvePresentation(
            activeSessionId = "sess_demo",
            speechState = JetsonSpeechState(
                listening = true,
                taskLabel = "assistant query",
                transcriptHint = "tim nguoi ao vang",
                stateLabel = "routed"
            ),
            voiceScene = null,
            visionResult = null,
            liveTranscript = "tim nguoi ao vang",
            effectiveSpeechTaskLabel = "assistant query",
            meaningfulSceneActive = false,
            updatedAtMs = 1234L
        )

        assertNull(presentation)
    }

    @Test
    fun longerStableTranscriptWinsOverShorterFragment() {
        assertEquals(
            "nguoi mac ao vang",
            HudPresentationRuntime.chooseStableSpeechTranscript(
                previous = "nguoi mac ao vang",
                incoming = "nguoi"
            )
        )
    }

    @Test
    fun visionSummaryStillRendersWhenSceneIsEmpty() {
        val presentation = HudPresentationRuntime.resolvePresentation(
            activeSessionId = "sess_demo",
            speechState = JetsonSpeechState(
                listening = false,
                taskLabel = null,
                transcriptHint = null,
                stateLabel = "idle"
            ),
            voiceScene = null,
            visionResult = JetsonVisionResult(
                mode = "scene_monitor",
                headline = "Co 2 nguoi phia truoc",
                primaryValue = 2,
                label = "person",
                frameSeq = 1L,
                counts = mapOf("person" to 2L),
                alertLabel = null,
                faceLabel = null,
                faceConfidence = null,
                detailLines = listOf("2 people", "left side"),
                captureToReceiveMs = 10,
                inferMs = 12,
                publishMs = 5,
                endToEndMs = 27
            ),
            liveTranscript = null,
            effectiveSpeechTaskLabel = null,
            meaningfulSceneActive = false,
            updatedAtMs = 1234L
        )

        assertNotNull(presentation)
        assertEquals("vision", presentation?.sourceLabel)
        assertFalse(presentation?.answerText.isNullOrBlank())
        assertTrue(HudPresentationRuntime.shouldHoldPresentation(presentation!!))
    }
}
