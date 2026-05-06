package com.example.cxrservicedemo.videostream

import android.view.KeyEvent

internal object GlassesInputController {
    interface Actions {
        fun toggleDeveloperPanel()
        fun hideDeveloperPanel()
        fun toggleProfile()
        fun finishActivity()
    }

    fun handleKeyDown(
        keyCode: Int,
        developerPanelVisible: Boolean,
        actions: Actions,
    ): Boolean {
        when (keyCode) {
            KeyEvent.KEYCODE_DPAD_LEFT,
            KeyEvent.KEYCODE_DPAD_RIGHT,
            KeyEvent.KEYCODE_DPAD_CENTER,
            KeyEvent.KEYCODE_ENTER,
            KeyEvent.KEYCODE_DPAD_DOWN -> return true

            KeyEvent.KEYCODE_TV,
            KeyEvent.KEYCODE_MENU -> {
                actions.toggleDeveloperPanel()
                return true
            }

            KeyEvent.KEYCODE_BACK -> {
                if (developerPanelVisible) {
                    actions.hideDeveloperPanel()
                } else {
                    actions.finishActivity()
                }
                return true
            }

            KeyEvent.KEYCODE_DPAD_UP -> {
                if (developerPanelVisible) {
                    actions.toggleProfile()
                }
                return true
            }
        }
        return false
    }
}
