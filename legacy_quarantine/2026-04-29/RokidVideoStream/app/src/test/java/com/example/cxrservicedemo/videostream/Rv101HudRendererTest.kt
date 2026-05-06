package com.example.cxrservicedemo.videostream

import com.example.cxrservicedemo.videostream.transport.JetsonHudGalleryItem
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Rv101HudRendererTest {
    @Test
    fun blockingHeadlineOnlyCatchesOperationalInterrupts() {
        assertTrue(Rv101HudRenderer.isBlockingHeadline("Camera permission denied"))
        assertTrue(Rv101HudRenderer.isBlockingHeadline("Reconnecting to Jetson"))
        assertFalse(Rv101HudRenderer.isBlockingHeadline("Voice live"))
        assertFalse(Rv101HudRenderer.isBlockingHeadline("Tim nguoi mac ao vang"))
    }

    @Test
    fun gallerySignatureUsesFirstTwoCandidatesAndThumbEdges() {
        val signature = Rv101HudRenderer.buildCandidateGallerySignature(
            galleryItems = listOf(
                JetsonHudGalleryItem(
                    label = "Ao vang",
                    secondaryText = "Ben trai",
                    trackId = "track_1",
                    selected = true,
                    thumbBase64 = "abcdefghijklmnop-qrstu-vwxyz"
                ),
                JetsonHudGalleryItem(
                    label = "Ao do",
                    secondaryText = null,
                    trackId = "track_2",
                    selected = false,
                    thumbBase64 = null
                ),
                JetsonHudGalleryItem(
                    label = "Ao xanh",
                    secondaryText = "Ben phai",
                    trackId = "track_3",
                    selected = false,
                    thumbBase64 = null
                ),
            ),
            directionHint = "Ben trai"
        )

        assertTrue(signature.startsWith("Ben trai|Ao vang:Ben trai:track_1:true:28:abcdefghijklmnop:mnop-qrstu-vwxyz"))
        assertTrue(signature.contains("|Ao do::track_2:false:0"))
        assertFalse(signature.contains("Ao xanh"))
    }
}
