package com.example.cxrservicedemo.videostream.transport

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.io.Closeable
import java.util.concurrent.TimeUnit

class JetsonControlClient(
    private val host: String,
    private val port: Int,
    private val deviceId: String,
    private val appVersion: String,
    initialSelectedMode: String,
    private val listener: JetsonControlListener
) : Closeable {

    private val httpClient = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private var sessionAccept: JetsonSessionAccept? = null
    private var connected = false
    private var lastError: String? = null
    private var selectedMode: String = initialSelectedMode

    fun start() {
        if (webSocket != null) return
        val request = Request.Builder()
            .url("ws://$host:$port/ws")
            .build()
        webSocket = httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                connected = true
                lastError = null
                listener.onControlStatus(status())
                sendClientHello()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleMessage(text)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                connected = false
                sessionAccept = null
                this@JetsonControlClient.webSocket = null
                listener.onControlStatus(status())
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                connected = false
                lastError = t.message
                sessionAccept = null
                this@JetsonControlClient.webSocket = null
                listener.onControlError("control ws failed: ${t.message}")
                listener.onControlStatus(status())
            }
        })
    }

    fun stop() {
        connected = false
        sessionAccept = null
        webSocket?.close(1000, "pause")
        webSocket = null
        listener.onControlStatus(status())
    }

    override fun close() {
        stop()
        httpClient.dispatcher.executorService.shutdown()
    }

    fun sessionId(): String? = sessionAccept?.sessionId

    fun sessionAccept(): JetsonSessionAccept? = sessionAccept

    fun status(): JetsonControlStatus =
        JetsonControlStatus(
            connected = connected,
            targetLabel = "$host:$port",
            sessionId = sessionAccept?.sessionId,
            lastError = lastError
        )

    fun sendPing() {
        sendJson(
            JSONObject()
                .put("type", "ping")
                .put("sessionId", sessionAccept?.sessionId)
                .put("timestampMs", System.currentTimeMillis())
        )
    }

    fun sendDeviceTelemetry(payload: JSONObject) {
        sendSessionBound("device_telemetry", payload)
    }

    fun sendEncoderStats(payload: JSONObject) {
        sendSessionBound("encoder_stats", payload)
    }

    fun sendModeChange(mode: String) {
        selectedMode = mode
        val sessionId = sessionAccept?.sessionId ?: return
        sendJson(
            JSONObject()
                .put("type", "mode_change")
                .put("sessionId", sessionId)
                .put("mode", mode)
        )
    }

    fun sendPushToTalk(listening: Boolean, transcriptHint: String? = null) {
        val sessionId = sessionAccept?.sessionId ?: return
        val payload = JSONObject()
            .put("type", if (listening) "ptt_down" else "ptt_up")
            .put("sessionId", sessionId)
            .put("timestampMs", System.currentTimeMillis())
        if (!transcriptHint.isNullOrBlank()) {
            payload.put("transcriptHint", transcriptHint)
        }
        sendJson(payload)
    }

    fun sendAudioHello(codec: String, sampleRateHz: Int, channels: Int, bytesPerSample: Int) {
        val payload = JSONObject()
            .put("codec", codec)
            .put("sampleRateHz", sampleRateHz)
            .put("channels", channels)
            .put("bytesPerSample", bytesPerSample)
        sendSessionBound("audio_hello", payload)
    }

    fun sendAudioStats(payload: JSONObject) {
        sendSessionBound("audio_stats", payload)
    }

    fun sendStreamLog(level: String, event: String, message: String, fields: JSONObject? = null) {
        val payload = JSONObject()
            .put("level", level)
            .put("event", event)
            .put("message", message)
        if (fields != null) {
            payload.put("fields", fields)
        }
        sendSessionBound("stream_log", payload)
    }

    private fun sendClientHello() {
        sendJson(
            JSONObject()
                .put("type", "client_hello")
                .put("deviceId", deviceId)
                .put("appVersion", appVersion)
                .put("selectedMode", selectedMode)
                .put(
                    "supportedModes",
                    JSONArray().apply {
                        put("standby")
                        put("face_memory")
                        put("traffic_count")
                        put("visual_assistant")
                        put("focus_bubble")
                        put("ar_radar")
                        put("alert_burst")
                        put("scene_monitor")
                    }
                )
                .put("videoCodec", "h264")
        )
    }

    private fun sendSessionBound(type: String, payload: JSONObject) {
        val sessionId = sessionAccept?.sessionId ?: return
        payload.put("type", type)
        payload.put("sessionId", sessionId)
        payload.put("timestampMs", System.currentTimeMillis())
        sendJson(payload)
    }

    private fun sendJson(payload: JSONObject) {
        webSocket?.send(payload.toString())
    }

    private fun handleMessage(text: String) {
        try {
            val payload = JSONObject(text)
            when (payload.optString("type")) {
                "session_accept" -> {
                    val media = payload.optJSONObject("media")
                    val audio = payload.optJSONObject("audio")
                    val mediaHost = media?.optString("host", host) ?: host
                    val mediaPort = media?.optInt("port", DEFAULT_MEDIA_PORT) ?: DEFAULT_MEDIA_PORT
                    val session = JetsonSessionAccept(
                        sessionId = payload.getString("sessionId"),
                        controlHeartbeatMs = payload.optInt("controlHeartbeatMs", 1000),
                        resultThrottleMs = payload.optInt("resultThrottleMs", 1000),
                        videoHost = mediaHost,
                        videoPort = mediaPort,
                        mediaTransport = media?.optString("transport", "tcp_mux_av") ?: "tcp_mux_av",
                        audioHost = audio?.optString("host", mediaHost) ?: mediaHost,
                        audioPort = audio?.optInt("port", mediaPort) ?: mediaPort,
                        audioCodec = audio?.optString("codec", "pcm_s16le") ?: "pcm_s16le"
                    )
                    sessionAccept = session
                    listener.onControlStatus(status())
                    listener.onSessionAccepted(session)
                }

                "vision_result" -> {
                    val summary = payload.optJSONObject("summary")
                    val latency = payload.optJSONObject("latency")
                    val counts = mutableMapOf<String, Long>()
                    payload.optJSONObject("counts")?.let { countObject ->
                        val iterator = countObject.keys()
                        while (iterator.hasNext()) {
                            val key = iterator.next()
                            counts[key] = countObject.optLong(key)
                        }
                    }
                    val alerts = payload.optJSONArray("alerts")
                    val faces = payload.optJSONArray("faces")
                    val details = mutableListOf<String>()
                    payload.optJSONArray("details")?.let { detailArray ->
                        for (index in 0 until detailArray.length()) {
                            val value = detailArray.optString(index)
                            if (value.isNotBlank()) details += value
                        }
                    }
                    val firstAlert = alerts?.optJSONObject(0)
                    val firstFace = faces?.optJSONObject(0)
                    listener.onVisionResult(
                        JetsonVisionResult(
                            mode = payload.optString("mode", "debug_stream"),
                            headline = payload.optString("headline", "Jetson AI update"),
                            primaryValue = summary?.optLong("primaryValue") ?: 0L,
                            label = summary?.optString("label", "value") ?: "value",
                            frameSeq = payload.optLong("frameSeq"),
                            counts = counts,
                            alertLabel = firstAlert?.optString("label")?.takeIf { it.isNotBlank() },
                            faceLabel = firstFace?.optString("matchLabel")?.takeIf { it.isNotBlank() },
                            faceConfidence = when {
                                firstFace == null -> null
                                firstFace.has("confidence") -> firstFace.optDouble("confidence").toFloat()
                                firstFace.has("matchScore") -> firstFace.optDouble("matchScore").toFloat()
                                else -> null
                            },
                            detailLines = details,
                            captureToReceiveMs = latency?.optInt("captureToReceiveMs") ?: 0,
                            inferMs = latency?.optInt("inferMs") ?: 0,
                            publishMs = latency?.optInt("publishMs") ?: 0,
                            endToEndMs = latency?.optInt("endToEndMs") ?: 0
                        )
                    )
                }

                "node_telemetry" -> {
                    listener.onNodeTelemetry(
                        JetsonNodeTelemetry(
                            rxFps = payload.optDouble("rxFps", 0.0).toFloat(),
                            gpuPercent = payload.optInt("gpuPercent"),
                            cpuPercent = payload.optInt("cpuPercent"),
                            ramMb = payload.optInt("ramMb"),
                            videoFrames = payload.optLong("videoFrames"),
                            videoBytes = payload.optLong("videoBytes")
                        )
                    )
                }

                "speech_state" -> {
                    listener.onSpeechState(
                        JetsonSpeechState(
                            listening = payload.optBoolean("listening", false),
                            taskLabel = payload.optString("taskLabel").takeIf { it.isNotBlank() },
                            transcriptHint = payload.optString("transcriptHint").takeIf { it.isNotBlank() },
                            stateLabel = payload.optString("stateLabel", "idle")
                        )
                    )
                }

                "hud_scene" -> {
                    val components = payload.optJSONArray("components")
                    var taskChip: String? = null
                    var micChip: String? = null
                    var answerText: String? = null
                    var statusText: String? = null
                    var directionHint: String? = null
                    val galleryLabels = mutableListOf<String>()
                    val galleryItems = mutableListOf<JetsonHudGalleryItem>()
                    var targetMarker: JetsonHudTargetMarker? = null
                    for (index in 0 until (components?.length() ?: 0)) {
                        val item = components?.optJSONObject(index) ?: continue
                        when (item.optString("kind")) {
                            "chip" -> {
                                when (item.optString("id")) {
                                    "task_chip" -> taskChip = item.optString("text").takeIf { it.isNotBlank() }
                                    "mic_chip" -> micChip = item.optString("text").takeIf { it.isNotBlank() }
                                }
                            }
                            "answer_strip" -> {
                                answerText = item.optString("text").takeIf { it.isNotBlank() }
                            }
                            "status_strip" -> {
                                statusText = item.optString("text").takeIf { it.isNotBlank() }
                            }
                            "gallery" -> {
                                val items = item.optJSONArray("items")
                                for (galleryIndex in 0 until (items?.length() ?: 0)) {
                                    val galleryItem = items?.optJSONObject(galleryIndex) ?: continue
                                    val label = galleryItem.optString("label").takeIf { it.isNotBlank() } ?: continue
                                    galleryLabels += label
                                    galleryItems += JetsonHudGalleryItem(
                                        label = label,
                                        secondaryText = galleryItem.optString("secondary").takeIf { it.isNotBlank() },
                                        trackId = galleryItem.optString("trackId").takeIf { it.isNotBlank() },
                                        selected = galleryItem.optBoolean("selected", false),
                                        thumbBase64 = galleryItem.optString("thumbB64").takeIf { it.isNotBlank() }
                                    )
                                }
                            }
                            "direction_hint" -> {
                                directionHint = item.optString("text").takeIf { it.isNotBlank() }
                            }
                            "target_marker" -> {
                                targetMarker = JetsonHudTargetMarker(
                                    label = item.optString("label").takeIf { it.isNotBlank() },
                                    trackId = item.optString("trackId").takeIf { it.isNotBlank() },
                                    direction = item.optString("direction").takeIf { it.isNotBlank() },
                                    selected = item.optBoolean("selected", false),
                                    normalizedX = if (item.has("normalizedX")) item.optDouble("normalizedX").toFloat() else null,
                                    normalizedY = if (item.has("normalizedY")) item.optDouble("normalizedY").toFloat() else null
                                )
                            }
                        }
                    }
                    listener.onHudScene(
                        JetsonHudScene(
                            sessionId = payload.optString("sessionId").takeIf { it.isNotBlank() },
                            sceneId = payload.optString("sceneId", "scene"),
                            taskChip = taskChip,
                            micChip = micChip,
                            answerText = answerText,
                            statusText = statusText,
                            galleryLabels = galleryLabels,
                            galleryItems = galleryItems,
                            directionHint = directionHint,
                            targetMarker = targetMarker
                        )
                    )
                }

                "error" -> {
                    val message = payload.optString("message", "unknown control error")
                    lastError = message
                    listener.onControlError(message)
                    listener.onControlStatus(status())
                }
            }
        } catch (error: Exception) {
            lastError = error.message
            listener.onControlError("control parse failed: ${error.message}")
            listener.onControlStatus(status())
        }
    }

    companion object {
        private const val DEFAULT_MEDIA_PORT = 9082
    }
}
