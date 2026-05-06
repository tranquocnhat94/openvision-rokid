package com.example.cxrservicedemo.videostream

import android.view.KeyEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GlassesInputControllerTest {
    @Test
    fun backHidesDeveloperPanelBeforeFinishing() {
        val actions = RecordingActions()

        val handled = GlassesInputController.handleKeyDown(
            keyCode = KeyEvent.KEYCODE_BACK,
            developerPanelVisible = true,
            actions = actions
        )

        assertTrue(handled)
        assertEquals(1, actions.hideDeveloperPanelCalls)
        assertEquals(0, actions.finishActivityCalls)
    }

    @Test
    fun dpadUpOnlyTogglesProfileWhenDeveloperPanelIsVisible() {
        val hiddenActions = RecordingActions()
        val visibleActions = RecordingActions()

        val hiddenHandled = GlassesInputController.handleKeyDown(
            keyCode = KeyEvent.KEYCODE_DPAD_UP,
            developerPanelVisible = false,
            actions = hiddenActions
        )
        val visibleHandled = GlassesInputController.handleKeyDown(
            keyCode = KeyEvent.KEYCODE_DPAD_UP,
            developerPanelVisible = true,
            actions = visibleActions
        )

        assertTrue(hiddenHandled)
        assertTrue(visibleHandled)
        assertEquals(0, hiddenActions.toggleProfileCalls)
        assertEquals(1, visibleActions.toggleProfileCalls)
    }

    @Test
    fun unknownKeyFallsThroughToActivity() {
        val handled = GlassesInputController.handleKeyDown(
            keyCode = KeyEvent.KEYCODE_A,
            developerPanelVisible = false,
            actions = RecordingActions()
        )

        assertFalse(handled)
    }

    private class RecordingActions : GlassesInputController.Actions {
        var toggleDeveloperPanelCalls = 0
        var hideDeveloperPanelCalls = 0
        var toggleProfileCalls = 0
        var finishActivityCalls = 0

        override fun toggleDeveloperPanel() {
            toggleDeveloperPanelCalls += 1
        }

        override fun hideDeveloperPanel() {
            hideDeveloperPanelCalls += 1
        }

        override fun toggleProfile() {
            toggleProfileCalls += 1
        }

        override fun finishActivity() {
            finishActivityCalls += 1
        }
    }
}
