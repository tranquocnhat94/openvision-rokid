package com.example.cxrservicedemo.videostream

import com.example.cxrservicedemo.videostream.transport.JetsonHudScene
import com.example.cxrservicedemo.videostream.transport.JetsonSpeechState
import com.example.cxrservicedemo.videostream.transport.JetsonVisionResult
import java.util.Locale

data class HudPresentation(
    val sessionId: String,
    val answerText: String?,
    val taskLabel: String?,
    val metaText: String?,
    val sourceLabel: String,
    val updatedAtMs: Long,
    val isLiveCaption: Boolean
)

object HudPresentationRuntime {
    private val hudWhitespaceRegex = "\\s+".toRegex()

    fun normalizeText(text: String?): String? {
        val normalized = text
            ?.trim()
            ?.replace(hudWhitespaceRegex, " ")
            ?.takeIf { it.isNotEmpty() }
            ?: return null
        return when {
            normalized.equals("null", ignoreCase = true) -> null
            normalized.equals("none", ignoreCase = true) -> null
            else -> normalized
        }
    }

    fun sanitizeText(text: String?): String? =
        normalizeText(text)?.takeUnless(::isGenericText)

    fun isGenericText(text: String?): Boolean {
        val value = text?.trim()?.lowercase(Locale.US) ?: return true
        if (value.isBlank()) return true
        return value in setOf(
            "continuous voice stream active",
            "jetson is receiving continuous voice from the glasses.",
            "feature picker on glasses can now stay disabled.",
            "scene live",
            "voice task ready",
            "voice link stays live",
            "jetson hud is active.",
            "jetson hud ready",
            "waiting for jetson hud",
            "thin client overlay",
            "jetson ready",
            "choose face memory, traffic count, or scene monitor.",
        )
    }

    fun hasMeaningfulScene(scene: JetsonHudScene?): Boolean {
        if (scene == null) return false
        if (!sanitizeText(scene.answerText).isNullOrBlank()) return true
        if (!sanitizeText(scene.statusText).isNullOrBlank()) return true
        if (!normalizeText(scene.directionHint).isNullOrBlank()) return true
        if (scene.targetMarker != null) return true
        if (scene.galleryItems.isNotEmpty()) return true
        return false
    }

    fun isLiveSpeechState(state: JetsonSpeechState): Boolean {
        val taskLabel = normalizeText(state.taskLabel)?.lowercase(Locale.US)
        val stateLabel = state.stateLabel.trim().lowercase(Locale.US)
        return taskLabel == "live caption" ||
            taskLabel == "voice live" ||
            taskLabel == "voice capture" ||
            stateLabel == "capturing" ||
            stateLabel == "captioning" ||
            stateLabel == "transcribing"
    }

    fun chooseStableSpeechTranscript(previous: String?, incoming: String): String {
        val normalizedPrevious = normalizeText(previous) ?: return incoming
        val normalizedIncoming = normalizeText(incoming) ?: return normalizedPrevious
        if (
            normalizedPrevious.length > normalizedIncoming.length + 2 &&
            normalizedPrevious.startsWith(normalizedIncoming, ignoreCase = true)
        ) {
            return normalizedPrevious
        }
        return normalizedIncoming
    }

    fun shouldHoldPresentation(presentation: HudPresentation): Boolean =
        !presentation.answerText.isNullOrBlank() &&
            !presentation.isLiveCaption &&
            presentation.sourceLabel != "speech"

    fun resolvePresentation(
        activeSessionId: String?,
        speechState: JetsonSpeechState,
        voiceScene: JetsonHudScene?,
        visionResult: JetsonVisionResult?,
        liveTranscript: String?,
        effectiveSpeechTaskLabel: String?,
        meaningfulSceneActive: Boolean,
        updatedAtMs: Long,
    ): HudPresentation? {
        val sceneAnswer = sanitizeText(voiceScene?.answerText)
        val sceneStatus = sanitizeText(voiceScene?.statusText)
        val sceneMicChip = normalizeText(voiceScene?.micChip)
        val visionAnswer = sanitizeText(visionResult?.headline)
            ?: visionResult?.detailLines?.mapNotNull(::sanitizeText)?.firstOrNull()
        val normalizedTaskLabel = effectiveSpeechTaskLabel?.lowercase(Locale.US)
        val normalizedStateLabel = speechState.stateLabel.trim().lowercase(Locale.US)
        val targetSearchScene =
            !voiceScene?.galleryItems.isNullOrEmpty() ||
                !normalizeText(voiceScene?.directionHint).isNullOrBlank() ||
                voiceScene?.targetMarker != null
        val isLiveCaption =
            !liveTranscript.isNullOrBlank() && (
                normalizedTaskLabel == "live caption" ||
                    normalizedStateLabel == "capturing" ||
                    normalizedStateLabel == "captioning" ||
                    normalizedStateLabel == "transcribing"
                )
        val commandOnlySpeech =
            !liveTranscript.isNullOrBlank() &&
                !isLiveCaption &&
                sceneAnswer.isNullOrBlank() &&
                sceneStatus.isNullOrBlank() &&
                !targetSearchScene
        val speechDriven =
            !liveTranscript.isNullOrBlank() && (
                isLiveCaption ||
                    normalizedTaskLabel == "assistant query" ||
                    normalizedTaskLabel == "transcript only" ||
                    normalizedTaskLabel == "voice request" ||
                    normalizedTaskLabel == "voice capture" ||
                    normalizedTaskLabel == "voice live"
                )
        val passiveSpeechState =
            speechState.listening &&
                liveTranscript.isNullOrBlank() &&
                sceneAnswer.isNullOrBlank() &&
                sceneStatus.isNullOrBlank() &&
                !targetSearchScene
        if (passiveSpeechState || commandOnlySpeech) {
            return null
        }
        val answer = when {
            meaningfulSceneActive && !sceneAnswer.isNullOrBlank() -> sceneAnswer
            targetSearchScene && !sceneAnswer.isNullOrBlank() -> sceneAnswer
            targetSearchScene && !sceneStatus.isNullOrBlank() -> sceneStatus
            isLiveCaption -> liveTranscript ?: sceneAnswer ?: sceneStatus ?: visionAnswer
            !sceneAnswer.isNullOrBlank() -> sceneAnswer
            !sceneStatus.isNullOrBlank() -> sceneStatus
            else -> visionAnswer
        }
        val taskLabel = normalizeText(
            if (meaningfulSceneActive || targetSearchScene) {
                voiceScene?.taskChip ?: effectiveSpeechTaskLabel
            } else if (isLiveCaption) {
                effectiveSpeechTaskLabel ?: voiceScene?.taskChip
            } else {
                voiceScene?.taskChip ?: effectiveSpeechTaskLabel
            }
        )
        val metaText = normalizeText(
            when {
                targetSearchScene -> normalizeText(voiceScene?.directionHint)
                    ?: voiceScene?.galleryItems?.map { item ->
                        listOfNotNull(item.label, item.secondaryText).joinToString(" ")
                    }?.take(2)?.joinToString(" | ")
                isLiveCaption -> sceneMicChip ?: if (speechState.listening) "Listening" else null
                meaningfulSceneActive && !sceneAnswer.isNullOrBlank() -> sceneStatus ?: sceneMicChip
                meaningfulSceneActive && !sceneStatus.isNullOrBlank() -> sceneMicChip
                speechDriven -> sceneMicChip
                !voiceScene?.galleryLabels.isNullOrEmpty() -> voiceScene!!.galleryLabels.joinToString(" | ")
                !visionResult?.detailLines.isNullOrEmpty() -> visionResult!!.detailLines
                    .mapNotNull(::sanitizeText)
                    .take(2)
                    .joinToString(" | ")
                speechState.listening -> "Listening via Jetson"
                else -> null
            }
        )
        if (answer.isNullOrBlank() && taskLabel.isNullOrBlank() && metaText.isNullOrBlank()) {
            return null
        }
        val sessionId = activeSessionId ?: return null
        return HudPresentation(
            sessionId = sessionId,
            answerText = answer,
            taskLabel = taskLabel,
            metaText = metaText,
            sourceLabel = when {
                meaningfulSceneActive -> "scene"
                targetSearchScene -> "target_search"
                isLiveCaption -> "speech"
                speechDriven -> "speech"
                !sceneAnswer.isNullOrBlank() -> "scene"
                !sceneStatus.isNullOrBlank() -> "scene"
                !visionAnswer.isNullOrBlank() -> "vision"
                else -> "mixed"
            },
            updatedAtMs = updatedAtMs,
            isLiveCaption = isLiveCaption
        )
    }
}
