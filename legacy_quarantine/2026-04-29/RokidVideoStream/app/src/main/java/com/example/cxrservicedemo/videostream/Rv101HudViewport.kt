package com.example.cxrservicedemo.videostream

import kotlin.math.roundToInt

internal data class Rv101HudViewport(
    val rootWidthPx: Int,
    val rootHeightPx: Int,
    val sideMarginPx: Int,
    val topMarginPx: Int,
    val topChipGapPx: Int,
    val centerCardWidthPx: Int,
    val galleryWidthPx: Int,
    val galleryTopMarginPx: Int,
    val assistantStripWidthPx: Int,
    val assistantBottomMarginPx: Int,
    val developerWidthPx: Int,
    val developerBottomMarginPx: Int,
    val markerTopSafePx: Int,
    val markerSideSafePx: Int,
    val markerBottomSafePx: Int,
) {
    val signature: String =
        listOf(
            rootWidthPx,
            rootHeightPx,
            sideMarginPx,
            topMarginPx,
            centerCardWidthPx,
            galleryWidthPx,
            galleryTopMarginPx,
            assistantStripWidthPx,
            assistantBottomMarginPx,
            developerWidthPx,
            developerBottomMarginPx,
            markerTopSafePx,
            markerSideSafePx,
            markerBottomSafePx,
        ).joinToString(":")

    companion object {
        fun from(rootWidthPx: Int, rootHeightPx: Int, density: Float): Rv101HudViewport {
            fun dp(value: Float): Int = (value * density).roundToInt().coerceAtLeast(1)
            fun clamp(value: Int, min: Int, max: Int): Int = value.coerceIn(min, max)

            val sideMargin = maxOf(dp(12f), (rootWidthPx * 0.028f).roundToInt())
            val topMargin = maxOf(dp(10f), (rootHeightPx * 0.026f).roundToInt())
            val topChipGap = dp(6f)
            val centerCardWidth = clamp((rootWidthPx * 0.54f).roundToInt(), dp(220f), dp(276f))
            val galleryWidth = clamp((rootWidthPx * 0.35f).roundToInt(), dp(148f), dp(184f))
            val galleryTopMargin = maxOf(topMargin + dp(30f), (rootHeightPx * 0.16f).roundToInt())
            val assistantStripWidth = clamp((rootWidthPx * 0.82f).roundToInt(), dp(254f), dp(316f))
            val assistantBottomMargin = maxOf(dp(28f), (rootHeightPx * 0.05f).roundToInt())
            val developerWidth = clamp((rootWidthPx * 0.84f).roundToInt(), dp(250f), dp(320f))
            val developerBottomMargin = assistantBottomMargin + dp(76f)
            val markerTopSafe = topMargin + dp(28f)
            val markerSideSafe = sideMargin
            val markerBottomSafe = assistantBottomMargin + dp(72f)

            return Rv101HudViewport(
                rootWidthPx = rootWidthPx,
                rootHeightPx = rootHeightPx,
                sideMarginPx = sideMargin,
                topMarginPx = topMargin,
                topChipGapPx = topChipGap,
                centerCardWidthPx = centerCardWidth,
                galleryWidthPx = galleryWidth,
                galleryTopMarginPx = galleryTopMargin,
                assistantStripWidthPx = assistantStripWidth,
                assistantBottomMarginPx = assistantBottomMargin,
                developerWidthPx = developerWidth,
                developerBottomMarginPx = developerBottomMargin,
                markerTopSafePx = markerTopSafe,
                markerSideSafePx = markerSideSafe,
                markerBottomSafePx = markerBottomSafe,
            )
        }
    }
}
