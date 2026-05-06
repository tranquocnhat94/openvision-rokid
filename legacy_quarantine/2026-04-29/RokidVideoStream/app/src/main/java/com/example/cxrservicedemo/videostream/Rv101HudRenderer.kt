package com.example.cxrservicedemo.videostream

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Rect
import android.util.Base64
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.view.updateLayoutParams
import com.example.cxrservicedemo.mousehand.telemetry.MouseHandTelemetrySnapshot
import com.example.cxrservicedemo.videostream.transport.JetsonControlStatus
import com.example.cxrservicedemo.videostream.transport.JetsonHudGalleryItem
import com.example.cxrservicedemo.videostream.transport.JetsonHudScene
import com.example.cxrservicedemo.videostream.transport.JetsonNodeTelemetry
import com.example.cxrservicedemo.videostream.transport.JetsonSpeechState
import com.example.cxrservicedemo.videostream.transport.JetsonVideoStatus
import com.example.cxrservicedemo.videostream.transport.VideoStreamProfile
import com.example.rokidvideostream.R
import com.example.rokidvideostream.databinding.ActivityVideoStreamBinding
import com.google.android.material.card.MaterialCardView
import java.util.Locale

internal data class Rv101HudRenderSnapshot(
    val centerVisible: Boolean,
    val assistantVisible: Boolean,
    val candidateVisible: Boolean,
    val candidateCount: Int,
    val sceneCandidateCount: Int,
    val candidateThumbPayloadCount: Int,
    val candidateThumbDecodedCount: Int,
    val markerVisible: Boolean,
)

internal class Rv101HudRenderer(
    private val context: Context,
    private val binding: ActivityVideoStreamBinding,
    private val layoutInflater: LayoutInflater,
) {
    private var lastCandidateGallerySignature: String? = null
    private var lastGalleryThumbPayloadCount = 0
    private var lastGalleryThumbDecodedCount = 0
    private var lastRenderedCandidateCount = 0
    private var lastSceneCandidateCount = 0
    private var lastRv101ViewportSignature: String? = null
    private var currentRv101Viewport: Rv101HudViewport? = null
    private val candidateThumbCache = object : LinkedHashMap<String, Bitmap>(12, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Bitmap>?): Boolean = size > 12
    }

    fun render(
        headline: String?,
        presentation: HudPresentation?,
        voiceScene: JetsonHudScene?,
        speechState: JetsonSpeechState,
        controlStatus: JetsonControlStatus,
        videoStatus: JetsonVideoStatus,
        sessionActive: Boolean,
        audioStreaming: Boolean,
        developerPanelVisible: Boolean,
    ): Rv101HudRenderSnapshot {
        val connectionLabel = connectionStatusLabel(
            controlStatus = controlStatus,
            videoStatus = videoStatus,
            sessionActive = sessionActive,
        )
        applyRv101ViewportLayout()
        val centerVisible = renderVoiceFirstCenterHud(
            headline = headline,
            presentation = presentation,
            controlConnected = controlStatus.connected,
            sessionActive = sessionActive,
            audioStreaming = audioStreaming,
        )
        val assistantVisible = renderVoiceHud(presentation)
        renderTopStatusChrome(
            presentation = presentation,
            voiceScene = voiceScene,
            speechState = speechState,
            showCenter = centerVisible,
            controlConnected = controlStatus.connected,
            sessionActive = sessionActive,
            developerPanelVisible = developerPanelVisible,
            connectionStatusLabel = connectionLabel,
            connectionStatusColor = connectionStatusColor(connectionLabel),
        )
        val gallerySnapshot = renderTargetGallery(voiceScene)
        val markerVisible = renderTargetMarker(
            voiceScene = voiceScene,
            controlConnected = controlStatus.connected,
            sessionActive = sessionActive,
        )
        return Rv101HudRenderSnapshot(
            centerVisible = centerVisible,
            assistantVisible = assistantVisible,
            candidateVisible = gallerySnapshot.candidateVisible,
            candidateCount = gallerySnapshot.candidateCount,
            sceneCandidateCount = gallerySnapshot.sceneCandidateCount,
            candidateThumbPayloadCount = gallerySnapshot.candidateThumbPayloadCount,
            candidateThumbDecodedCount = gallerySnapshot.candidateThumbDecodedCount,
            markerVisible = markerVisible,
        )
    }

    fun clearTransientState() {
        lastCandidateGallerySignature = null
        lastGalleryThumbPayloadCount = 0
        lastGalleryThumbDecodedCount = 0
        lastRenderedCandidateCount = 0
        lastSceneCandidateCount = 0
        binding.candidateItemsContainer.removeAllViews()
        binding.candidateItemsContainer.visibility = View.GONE
        binding.candidateGalleryCard.visibility = View.GONE
        binding.targetMarkerText.visibility = View.GONE
    }

    fun renderDeveloperPanel(
        visible: Boolean,
        telemetryRuntime: StreamTelemetryRuntime,
        telemetry: MouseHandTelemetrySnapshot,
        node: JetsonNodeTelemetry?,
        encoderStats: VideoEncoderRuntimeStats?,
        sessionId: String?,
        selectedMode: String,
        controlStatus: JetsonControlStatus,
        videoStatus: JetsonVideoStatus,
        activeProfile: VideoStreamProfile,
        analyzerDrops: Long,
    ) {
        binding.developerText.visibility = if (visible) View.VISIBLE else View.GONE
        if (!visible) return

        binding.developerText.text = telemetryRuntime.buildDeveloperPanelText(
            sessionId = sessionId,
            selectedMode = selectedMode,
            controlStatus = controlStatus,
            videoStatus = videoStatus,
            telemetry = telemetry,
            node = node,
            activeProfile = activeProfile,
            encoderStats = encoderStats,
            analyzerDrops = analyzerDrops,
        )
    }

    private fun renderVoiceFirstCenterHud(
        headline: String?,
        presentation: HudPresentation?,
        controlConnected: Boolean,
        sessionActive: Boolean,
        audioStreaming: Boolean,
    ): Boolean {
        val shouldShowCenterCard =
            !controlConnected ||
                !sessionActive ||
                isBlockingHeadline(headline) ||
                (presentation == null && !headline.isNullOrBlank())
        showCenterCard(show = shouldShowCenterCard, framed = controlConnected.not())
        if (!shouldShowCenterCard) return false

        binding.hudModeChip.text = "voice-first"
        binding.hudModeChip.setTextColor(ContextCompat.getColor(context, R.color.text_secondary))
        binding.hudTitleText.text = when {
            !headline.isNullOrBlank() -> "Jetson HUD"
            !presentation?.taskLabel.isNullOrBlank() -> presentation?.taskLabel
            else -> "Jetson HUD"
        }
        binding.hudPrimaryText.text = when {
            !headline.isNullOrBlank() -> "Attention"
            presentation?.isLiveCaption == true -> "Live caption"
            audioStreaming -> "Listening"
            controlConnected -> "Ready"
            else -> "Linking"
        }
        binding.hudPrimaryText.setTextColor(
            ContextCompat.getColor(
                context,
                if (audioStreaming) R.color.signal_amber else R.color.signal_green
            )
        )
        binding.hudBodyText.text = headline
            ?: if (!controlConnected || !sessionActive) {
                "Waiting for Jetson session."
            } else {
                presentation?.answerText ?: "Jetson HUD is active."
            }
        binding.hudMetaText.text = when {
            !controlConnected -> "Reconnecting"
            !sessionActive -> "Opening session"
            !presentation?.metaText.isNullOrBlank() -> presentation?.metaText
            else -> "Thin client overlay"
        }
        return true
    }

    private fun renderVoiceHud(presentation: HudPresentation?): Boolean {
        val answerText = presentation?.answerText
        val showAssistant = !answerText.isNullOrBlank()
        binding.assistantStripCard.visibility = if (showAssistant) View.VISIBLE else View.GONE
        if (!showAssistant) return false
        val taskLabel = presentation?.taskLabel
        val metaText = presentation?.metaText

        binding.assistantTaskText.visibility = if (taskLabel.isNullOrBlank()) View.GONE else View.VISIBLE
        binding.assistantTaskText.text = taskLabel.orEmpty()
        binding.assistantAnswerText.text = answerText
        binding.assistantGalleryText.visibility = if (metaText.isNullOrBlank()) View.GONE else View.VISIBLE
        binding.assistantGalleryText.text = metaText.orEmpty()
        return true
    }

    private fun renderTopStatusChrome(
        presentation: HudPresentation?,
        voiceScene: JetsonHudScene?,
        speechState: JetsonSpeechState,
        showCenter: Boolean,
        controlConnected: Boolean,
        sessionActive: Boolean,
        developerPanelVisible: Boolean,
        connectionStatusLabel: String,
        connectionStatusColor: Int,
    ) {
        val connectionVisible = developerPanelVisible || !controlConnected || !sessionActive
        val sceneMicChip = when {
            !showCenter &&
                presentation?.sourceLabel in TARGET_SOURCE_LABELS &&
                !voiceScene?.micChip.isNullOrBlank() -> voiceScene?.micChip
            else -> null
        }
        val voiceLabel = when {
            !sceneMicChip.isNullOrBlank() -> sceneMicChip
            developerPanelVisible && speechState.listening -> speechState.taskLabel ?: "listening"
            developerPanelVisible && !speechState.taskLabel.isNullOrBlank() -> speechState.taskLabel
            else -> null
        }
        val sceneChipVisible =
            !voiceLabel.isNullOrBlank() &&
                !showCenter &&
                presentation?.sourceLabel in TARGET_SOURCE_LABELS
        val voiceVisible =
            !voiceLabel.isNullOrBlank() &&
                (developerPanelVisible || (presentation == null && !showCenter) || sceneChipVisible)

        binding.topStatusContainer.visibility = if (connectionVisible || voiceVisible) View.VISIBLE else View.GONE

        binding.connectionStatusText.visibility = if (connectionVisible) View.VISIBLE else View.GONE
        if (connectionVisible) {
            binding.connectionStatusText.text = connectionStatusLabel
            binding.connectionStatusText.setTextColor(connectionStatusColor)
        }

        binding.voiceStatusText.visibility = if (voiceVisible) View.VISIBLE else View.GONE
        if (voiceVisible) {
            binding.voiceStatusText.text = voiceLabel
            binding.voiceStatusText.setTextColor(
                ContextCompat.getColor(
                    context,
                    if (speechState.listening) R.color.signal_amber else R.color.text_secondary
                )
            )
        }
    }

    private fun applyRv101ViewportLayout() {
        val rootWidth = binding.root.width
        val rootHeight = binding.root.height
        if (rootWidth <= 0 || rootHeight <= 0) {
            return
        }
        val viewport = Rv101HudViewport.from(
            rootWidthPx = rootWidth,
            rootHeightPx = rootHeight,
            density = context.resources.displayMetrics.density
        )
        if (viewport.signature == lastRv101ViewportSignature) {
            currentRv101Viewport = viewport
            return
        }
        lastRv101ViewportSignature = viewport.signature
        currentRv101Viewport = viewport

        (binding.topStatusContainer.layoutParams as? FrameLayout.LayoutParams)?.let { params ->
            params.gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            params.topMargin = viewport.topMarginPx
            binding.topStatusContainer.layoutParams = params
        }
        binding.voiceStatusText.updateLayoutParams<LinearLayout.LayoutParams> {
            marginStart = viewport.topChipGapPx
        }
        binding.centerHudCard.updateFrameLayoutParams(
            width = viewport.centerCardWidthPx,
            gravity = Gravity.CENTER
        )
        binding.candidateGalleryCard.updateFrameLayoutParams(
            width = viewport.galleryWidthPx,
            gravity = Gravity.TOP or Gravity.END,
            topMargin = viewport.galleryTopMarginPx,
            marginEnd = viewport.sideMarginPx
        )
        binding.assistantStripCard.translationY = 0f
        binding.assistantStripCard.updateFrameLayoutParams(
            width = viewport.assistantStripWidthPx,
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL,
            bottomMargin = viewport.assistantBottomMarginPx
        )
        binding.developerText.updateFrameLayoutParams(
            width = viewport.developerWidthPx,
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL,
            bottomMargin = viewport.developerBottomMarginPx
        )
    }

    private fun renderTargetGallery(voiceScene: JetsonHudScene?): GalleryRenderSnapshot {
        val galleryItems = voiceScene?.galleryItems.orEmpty()
        lastSceneCandidateCount = galleryItems.size
        val directionHint = HudPresentationRuntime.normalizeText(voiceScene?.directionHint)
        val showGallery =
            galleryItems.isNotEmpty() ||
                !directionHint.isNullOrBlank()
        binding.candidateGalleryCard.visibility = if (showGallery) View.VISIBLE else View.GONE
        if (!showGallery) {
            lastCandidateGallerySignature = null
            lastGalleryThumbPayloadCount = 0
            lastGalleryThumbDecodedCount = 0
            lastRenderedCandidateCount = 0
            binding.candidateItemsContainer.removeAllViews()
            binding.candidateItemsContainer.visibility = View.GONE
            return gallerySnapshot(candidateVisible = false)
        }

        binding.candidateGalleryTitleText.text =
            HudPresentationRuntime.normalizeText(voiceScene?.taskChip) ?: "Jetson target"
        binding.candidateDirectionText.text = directionHint
            ?: "Awaiting target guidance"
        binding.candidateItemsContainer.visibility = if (galleryItems.isNotEmpty()) View.VISIBLE else View.GONE
        lastGalleryThumbPayloadCount = galleryItems.take(MAX_HUD_CANDIDATES).count { !it.thumbBase64.isNullOrBlank() }
        val signature = buildCandidateGallerySignature(galleryItems, directionHint)
        if (signature != lastCandidateGallerySignature) {
            lastCandidateGallerySignature = signature
            binding.candidateItemsContainer.removeAllViews()
            var decodedThumbCount = 0
            var renderedCandidateCount = 0
            galleryItems.take(MAX_HUD_CANDIDATES).forEach { item ->
                val (tileView, hasThumbBitmap) = buildCandidateTileView(item)
                if (hasThumbBitmap) {
                    decodedThumbCount += 1
                }
                renderedCandidateCount += 1
                binding.candidateItemsContainer.addView(tileView)
            }
            lastGalleryThumbDecodedCount = decodedThumbCount
            lastRenderedCandidateCount = renderedCandidateCount
        } else {
            lastRenderedCandidateCount = binding.candidateItemsContainer.childCount
        }
        return gallerySnapshot(candidateVisible = true)
    }

    private fun gallerySnapshot(candidateVisible: Boolean): GalleryRenderSnapshot =
        GalleryRenderSnapshot(
            candidateVisible = candidateVisible,
            candidateCount = lastRenderedCandidateCount,
            sceneCandidateCount = lastSceneCandidateCount,
            candidateThumbPayloadCount = lastGalleryThumbPayloadCount,
            candidateThumbDecodedCount = lastGalleryThumbDecodedCount,
        )

    private fun renderTargetMarker(
        voiceScene: JetsonHudScene?,
        controlConnected: Boolean,
        sessionActive: Boolean,
    ): Boolean {
        val marker = voiceScene?.targetMarker
        val normalizedX = marker?.normalizedX
        val normalizedY = marker?.normalizedY
        if (
            marker == null ||
            normalizedX == null ||
            normalizedY == null ||
            !controlConnected ||
            !sessionActive
        ) {
            binding.targetMarkerText.visibility = View.GONE
            return false
        }

        val label = HudPresentationRuntime.normalizeText(marker.label)
            ?: HudPresentationRuntime.normalizeText(marker.trackId)?.let { "Target $it" }
            ?: "Target"
        binding.targetMarkerText.text = "◎ ${label.take(18)}"
        binding.targetMarkerText.visibility = View.VISIBLE
        binding.targetMarkerText.alpha = if (marker.selected) 1.0f else 0.84f
        binding.targetMarkerText.setTextColor(
            ContextCompat.getColor(
                context,
                if (marker.selected) R.color.signal_green else R.color.text_secondary
            )
        )
        positionTargetMarker(normalizedX, normalizedY)
        return true
    }

    private fun positionTargetMarker(normalizedX: Float, normalizedY: Float) {
        val root = binding.root
        val markerView = binding.targetMarkerText
        val rootWidth = root.width
        val rootHeight = root.height
        if (rootWidth <= 0 || rootHeight <= 0) {
            root.post { positionTargetMarker(normalizedX, normalizedY) }
            return
        }

        markerView.measure(
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED),
            View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        )
        val markerWidth = markerView.width.takeIf { it > 0 } ?: markerView.measuredWidth
        val markerHeight = markerView.height.takeIf { it > 0 } ?: markerView.measuredHeight
        val viewport = currentRv101Viewport
            ?: Rv101HudViewport.from(rootWidth, rootHeight, context.resources.displayMetrics.density)
                .also { currentRv101Viewport = it }
        val safeLeft = viewport.markerSideSafePx
        val safeRight = viewport.markerSideSafePx
        val safeTop = viewport.markerTopSafePx
        val safeBottom = if (binding.assistantStripCard.visibility == View.VISIBLE) {
            viewport.markerBottomSafePx
        } else {
            maxOf(dpToPx(28f), viewport.assistantBottomMarginPx)
        }
        val rawX = (rootWidth * normalizedX).toInt() - (markerWidth / 2)
        val rawY = (rootHeight * normalizedY).toInt() - markerHeight - dpToPx(10f)
        val maxX = (rootWidth - markerWidth - safeRight).coerceAtLeast(safeLeft)
        val maxY = (rootHeight - markerHeight - safeBottom).coerceAtLeast(safeTop)
        var clampedX = rawX.coerceIn(safeLeft, maxX)
        var clampedY = rawY.coerceIn(safeTop, maxY)
        val collisionGap = dpToPx(6f)
        val galleryRect = rootRelativeRect(binding.candidateGalleryCard)
        val stripRect = rootRelativeRect(binding.assistantStripCard)
        val markerRect = Rect()

        fun updateMarkerRect() {
            markerRect.set(clampedX, clampedY, clampedX + markerWidth, clampedY + markerHeight)
        }

        updateMarkerRect()
        if (galleryRect != null && Rect.intersects(markerRect, galleryRect)) {
            val aboveGallery = (galleryRect.top - markerHeight - collisionGap).coerceAtLeast(safeTop)
            val leftOfGallery = (galleryRect.left - markerWidth - collisionGap).coerceAtLeast(safeLeft)
            clampedY = if (aboveGallery < galleryRect.top) aboveGallery else clampedY
            updateMarkerRect()
            if (Rect.intersects(markerRect, galleryRect)) {
                clampedX = leftOfGallery
                updateMarkerRect()
            }
        }
        if (stripRect != null && Rect.intersects(markerRect, stripRect)) {
            clampedY = (stripRect.top - markerHeight - collisionGap).coerceAtLeast(safeTop)
            updateMarkerRect()
        }
        markerView.translationX = clampedX.toFloat()
        markerView.translationY = clampedY.toFloat()
    }

    private fun rootRelativeRect(view: View): Rect? {
        if (view.visibility != View.VISIBLE || view.width <= 0 || view.height <= 0) {
            return null
        }
        val left = view.x.toInt()
        val top = view.y.toInt()
        return Rect(left, top, left + view.width, top + view.height)
    }

    private fun View.updateFrameLayoutParams(
        width: Int? = null,
        gravity: Int? = null,
        topMargin: Int? = null,
        bottomMargin: Int? = null,
        marginEnd: Int? = null
    ) {
        val params = layoutParams as? FrameLayout.LayoutParams ?: return
        width?.let { params.width = it }
        gravity?.let { params.gravity = it }
        topMargin?.let { params.topMargin = it }
        bottomMargin?.let { params.bottomMargin = it }
        marginEnd?.let { params.marginEnd = it }
        layoutParams = params
    }

    private fun buildCandidateTileView(item: JetsonHudGalleryItem): Pair<View, Boolean> {
        val tileView = layoutInflater.inflate(
            R.layout.view_hud_candidate_tile,
            binding.candidateItemsContainer,
            false
        )
        val card = tileView.findViewById<MaterialCardView>(R.id.candidateTileCard)
        val imageView = tileView.findViewById<ImageView>(R.id.candidateThumbImage)
        val labelView = tileView.findViewById<TextView>(R.id.candidateLabelText)
        val secondaryView = tileView.findViewById<TextView>(R.id.candidateSecondaryText)

        labelView.text = item.label
        secondaryView.text = item.secondaryText ?: item.trackId ?: ""
        secondaryView.visibility = if (secondaryView.text.isNullOrBlank()) View.GONE else View.VISIBLE
        card.strokeWidth = dpToPx(1f)
        card.strokeColor = ContextCompat.getColor(
            context,
            if (item.selected) R.color.signal_green else R.color.text_muted
        )
        card.alpha = if (item.selected) 1.0f else 0.82f

        val bitmap = decodeCandidateThumb(item.thumbBase64)
        if (bitmap != null) {
            imageView.setImageBitmap(bitmap)
            imageView.visibility = View.VISIBLE
        } else {
            imageView.setImageDrawable(null)
            imageView.visibility = View.GONE
        }

        val params = LinearLayout.LayoutParams(
            0,
            ViewGroup.LayoutParams.WRAP_CONTENT,
            1f
        )
        params.marginEnd = dpToPx(6f)
        tileView.layoutParams = params
        return tileView to (bitmap != null)
    }

    private fun decodeCandidateThumb(thumbBase64: String?): Bitmap? {
        val normalized = HudPresentationRuntime.normalizeText(thumbBase64) ?: return null
        candidateThumbCache[normalized]?.let { return it }
        return runCatching {
            val bytes = Base64.decode(normalized, Base64.DEFAULT)
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        }.getOrNull()?.also { bitmap ->
            candidateThumbCache[normalized] = bitmap
        }
    }

    private fun showCenterCard(show: Boolean, framed: Boolean) {
        binding.centerHudCard.visibility = if (show) View.VISIBLE else View.GONE
        if (!show) return

        binding.centerHudCard.setCardBackgroundColor(
            ContextCompat.getColor(context, if (framed) R.color.panel_black else R.color.clear)
        )
        binding.centerHudCard.strokeWidth = if (framed) dpToPx(1f) else 0
        binding.centerHudCard.strokeColor = ContextCompat.getColor(
            context,
            if (framed) R.color.panel_border else R.color.clear
        )
        binding.centerHudCard.radius = dpToPx(if (framed) 18f else 0f).toFloat()
    }

    private fun dpToPx(value: Float): Int =
        (value * context.resources.displayMetrics.density).toInt().coerceAtLeast(1)

    private fun connectionStatusLabel(
        controlStatus: JetsonControlStatus,
        videoStatus: JetsonVideoStatus,
        sessionActive: Boolean,
    ): String =
        when {
            controlStatus.lastError != null || videoStatus.lastError != null -> "reconnecting"
            !controlStatus.connected -> "connecting"
            !sessionActive -> "opening"
            videoStatus.connected -> "media live"
            else -> "control linked"
        }

    private fun connectionStatusColor(label: String): Int =
        when (label) {
            "media live" -> ContextCompat.getColor(context, R.color.signal_green)
            "control linked" -> ContextCompat.getColor(context, R.color.text_secondary)
            "reconnecting" -> ContextCompat.getColor(context, R.color.text_muted)
            else -> ContextCompat.getColor(context, R.color.signal_amber)
        }

    private data class GalleryRenderSnapshot(
        val candidateVisible: Boolean,
        val candidateCount: Int,
        val sceneCandidateCount: Int,
        val candidateThumbPayloadCount: Int,
        val candidateThumbDecodedCount: Int,
    )

    companion object {
        internal const val MAX_HUD_CANDIDATES = 2

        private val TARGET_SOURCE_LABELS = setOf("scene", "target_search")
        private val BLOCKING_HEADLINE_TERMS = listOf(
            "error",
            "failed",
            "denied",
            "waiting",
            "reconnecting",
            "permission",
            "stopped",
        )

        fun isBlockingHeadline(headline: String?): Boolean {
            val value = headline?.trim()?.lowercase(Locale.US) ?: return false
            if (value.isBlank()) return false
            return BLOCKING_HEADLINE_TERMS.any(value::contains)
        }

        fun buildCandidateGallerySignature(
            galleryItems: List<JetsonHudGalleryItem>,
            directionHint: String?
        ): String =
            buildString {
                append(directionHint.orEmpty())
                galleryItems.take(MAX_HUD_CANDIDATES).forEach { item ->
                    append('|')
                    append(item.label)
                    append(':')
                    append(item.secondaryText.orEmpty())
                    append(':')
                    append(item.trackId.orEmpty())
                    append(':')
                    append(item.selected)
                    append(':')
                    append(thumbSignatureFragment(item.thumbBase64))
                }
            }

        fun thumbSignatureFragment(thumbBase64: String?): String {
            val normalized = HudPresentationRuntime.normalizeText(thumbBase64) ?: return "0"
            val prefix = normalized.take(16)
            val suffix = normalized.takeLast(16)
            return "${normalized.length}:$prefix:$suffix"
        }
    }
}
