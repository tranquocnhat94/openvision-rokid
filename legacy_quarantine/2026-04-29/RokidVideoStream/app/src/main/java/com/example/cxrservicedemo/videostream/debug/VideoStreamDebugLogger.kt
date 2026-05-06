package com.example.cxrservicedemo.videostream.debug

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.annotation.RequiresApi
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

data class VideoStreamDebugSnapshot(
    val timestampMs: Long,
    val sessionId: String?,
    val sequence: Long,
    val sourceWidth: Int,
    val sourceHeight: Int,
    val rotationDegrees: Int,
    val profileLabel: String,
    val preferredChromaMode: String,
    val inputLayout: String,
    val colorFormat: String,
    val captureFps: Float,
    val encodeFps: Float,
    val encodeMs: Float,
    val sendMs: Float,
    val analyzerDrops: Long,
    val encoderDrops: Long,
    val sentSamples: Long,
    val droppedSamples: Long,
    val sentBytes: Long,
    val keyframesSent: Long,
    val payloadBytes: Int,
    val wsConnected: Boolean,
    val videoConnected: Boolean,
    val wsTarget: String,
    val videoTarget: String,
    val batteryPercent: Int?,
    val batteryTempC: Float?,
    val batteryCurrentMa: Float?,
    val thermalStatusLabel: String,
    val appCpuPercent: Float,
    val javaHeapMb: Float,
    val nativeHeapMb: Float,
    val totalPssMb: Float,
    val availMemMb: Float,
    val rxKbps: Float,
    val txKbps: Float,
    val networkLabel: String,
    val jetsonRxFps: Float,
    val jetsonVideoFrames: Long,
    val jetsonVideoBytes: Long,
    val jetsonGpuPercent: Int,
    val jetsonCpuPercent: Int,
    val lastError: String?
)

class VideoStreamDebugLogger(context: Context) {

    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val sink: LogSink = resolveSink(context)

    val filePath: String
        get() = sink.displayPath

    fun append(snapshot: VideoStreamDebugSnapshot) {
        val line = snapshot.toJsonLine()
        executor.execute { sink.append(line) }
    }

    fun close() {
        executor.shutdown()
    }

    private fun VideoStreamDebugSnapshot.toJsonLine(): String =
        JSONObject()
            .put("timestampMs", timestampMs)
            .put("sessionId", sessionId)
            .put("sequence", sequence)
            .put("sourceWidth", sourceWidth)
            .put("sourceHeight", sourceHeight)
            .put("rotationDegrees", rotationDegrees)
            .put("profileLabel", profileLabel)
            .put("preferredChromaMode", preferredChromaMode)
            .put("inputLayout", inputLayout)
            .put("colorFormat", colorFormat)
            .put("captureFps", captureFps)
            .put("encodeFps", encodeFps)
            .put("encodeMs", encodeMs)
            .put("sendMs", sendMs)
            .put("analyzerDrops", analyzerDrops)
            .put("encoderDrops", encoderDrops)
            .put("sentSamples", sentSamples)
            .put("droppedSamples", droppedSamples)
            .put("sentBytes", sentBytes)
            .put("keyframesSent", keyframesSent)
            .put("payloadBytes", payloadBytes)
            .put("wsConnected", wsConnected)
            .put("videoConnected", videoConnected)
            .put("wsTarget", wsTarget)
            .put("videoTarget", videoTarget)
            .put("batteryPercent", batteryPercent)
            .put("batteryTempC", batteryTempC)
            .put("batteryCurrentMa", batteryCurrentMa)
            .put("thermalStatusLabel", thermalStatusLabel)
            .put("appCpuPercent", appCpuPercent)
            .put("javaHeapMb", javaHeapMb)
            .put("nativeHeapMb", nativeHeapMb)
            .put("totalPssMb", totalPssMb)
            .put("availMemMb", availMemMb)
            .put("rxKbps", rxKbps)
            .put("txKbps", txKbps)
            .put("networkLabel", networkLabel)
            .put("jetsonRxFps", jetsonRxFps)
            .put("jetsonVideoFrames", jetsonVideoFrames)
            .put("jetsonVideoBytes", jetsonVideoBytes)
            .put("jetsonGpuPercent", jetsonGpuPercent)
            .put("jetsonCpuPercent", jetsonCpuPercent)
            .put("lastError", lastError)
            .toString() + "\n"

    private fun resolveSink(context: Context): LogSink {
        val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val displayName = "video_stream_$timestamp.jsonl"

        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                createPublicDownloadsSink(context, displayName)
            } else {
                createLegacyPublicDownloadsSink(displayName)
            }
        } catch (_: Exception) {
            createAppSpecificFallbackSink(context, displayName)
        }
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private fun createPublicDownloadsSink(context: Context, displayName: String): LogSink {
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, displayName)
            put(MediaStore.Downloads.MIME_TYPE, "application/x-ndjson")
            put(
                MediaStore.Downloads.RELATIVE_PATH,
                "${Environment.DIRECTORY_DOWNLOADS}/RokidVideoStream"
            )
        }
        val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            ?: error("Unable to create public downloads log file")

        return MediaStoreLogSink(
            context = context,
            uri = uri,
            displayPath = "Download/RokidVideoStream/$displayName"
        )
    }

    @Suppress("DEPRECATION")
    private fun createLegacyPublicDownloadsSink(displayName: String): LogSink {
        val baseDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
        val logDir = File(baseDir, "RokidVideoStream")
        logDir.mkdirs()
        return FileLogSink(
            file = File(logDir, displayName),
            displayPath = "Download/RokidVideoStream/$displayName"
        )
    }

    private fun createAppSpecificFallbackSink(context: Context, displayName: String): LogSink {
        val baseDir = context.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            ?: context.filesDir
        val logDir = File(baseDir, "video-stream-debug")
        logDir.mkdirs()
        return FileLogSink(
            file = File(logDir, displayName),
            displayPath = "Android/data/${context.packageName}/files/Download/video-stream-debug/$displayName"
        )
    }

    private interface LogSink {
        val displayPath: String
        fun append(line: String)
    }

    private class FileLogSink(
        private val file: File,
        override val displayPath: String
    ) : LogSink {
        override fun append(line: String) {
            file.appendText(line)
        }
    }

    private class MediaStoreLogSink(
        private val context: Context,
        private val uri: Uri,
        override val displayPath: String
    ) : LogSink {
        override fun append(line: String) {
            val stream = context.contentResolver.openOutputStream(uri, "wa")
                ?: error("Unable to append to public downloads log file")
            stream.bufferedWriter().use { writer -> writer.write(line) }
        }
    }
}
