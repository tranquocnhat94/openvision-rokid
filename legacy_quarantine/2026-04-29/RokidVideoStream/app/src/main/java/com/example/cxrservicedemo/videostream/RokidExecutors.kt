package com.example.cxrservicedemo.videostream

import android.os.Process
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

fun newNamedSingleThreadExecutor(
    name: String,
    processPriority: Int
): ExecutorService =
    Executors.newSingleThreadExecutor { runnable ->
        Thread(
            {
                try {
                    Process.setThreadPriority(processPriority)
                } catch (_: Exception) {
                }
                runnable.run()
            },
            name
        )
    }
