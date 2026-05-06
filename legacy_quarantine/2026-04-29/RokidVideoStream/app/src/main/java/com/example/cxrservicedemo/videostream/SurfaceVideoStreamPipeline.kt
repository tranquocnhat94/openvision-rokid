package com.example.cxrservicedemo.videostream

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaRecorder
import android.os.SystemClock
import android.util.Range
import android.util.Size
import android.view.Surface
import java.io.Closeable
import java.util.concurrent.Executor
import java.util.concurrent.ExecutorService
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs

class SurfaceVideoStreamPipeline(
    context: Context,
    private val profile: com.example.cxrservicedemo.videostream.transport.VideoStreamProfile,
    private val displayRotation: Int,
    private val cameraExecutor: Executor,
    private val listener: Listener
) : Closeable {

    interface Listener {
        fun onStarted(actualWidth: Int, actualHeight: Int, rotationDegrees: Int, fpsRange: Range<Int>?)
        fun onEncodedSample(sample: EncodedVideoSample)
        fun onError(message: String, cause: Throwable? = null)
    }

    private val appContext = context.applicationContext
    private val cameraManager = appContext.getSystemService(CameraManager::class.java)
    private val codecExecutor: ExecutorService = newNamedSingleThreadExecutor(
        name = "rokid-video-codec",
        processPriority = android.os.Process.THREAD_PRIORITY_URGENT_DISPLAY
    )
    private val isClosed = AtomicBoolean(false)

    private var codec: MediaCodec? = null
    private var inputSurface: Surface? = null
    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null
    private var resolvedConfig: CameraStreamConfig? = null
    private var outputSequence = 0L
    private var emittedSamples = 0L
    private var emittedKeyframes = 0L
    private var outputBytes = 0L
    private var lastPayloadBytes = 0
    private var droppedOutputBuffers = 0L
    private var captureTimestampOffsetMs = 0L

    @Volatile
    private var draining = false

    @SuppressLint("MissingPermission")
    fun start() {
        if (isClosed.get()) return
        val config = resolveCameraConfig()
        resolvedConfig = config
        captureTimestampOffsetMs =
            System.currentTimeMillis() - (SystemClock.elapsedRealtimeNanos() / 1_000_000L)

        val nextCodec = MediaCodec.createEncoderByType(MIME_TYPE).apply {
            val format = MediaFormat.createVideoFormat(MIME_TYPE, config.captureSize.width, config.captureSize.height).apply {
                setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
                setInteger(MediaFormat.KEY_BIT_RATE, profile.bitrate)
                setInteger(MediaFormat.KEY_FRAME_RATE, profile.fps)
                setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, profile.iFrameIntervalSeconds)
                setInteger(
                    MediaFormat.KEY_BITRATE_MODE,
                    MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR
                )
            }
            configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        }
        val nextInputSurface = nextCodec.createInputSurface()
        nextCodec.start()

        codec = nextCodec
        inputSurface = nextInputSurface
        draining = true
        startDrainLoop()

        cameraManager.openCamera(
            config.cameraId,
            cameraExecutor,
            object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    if (isClosed.get()) {
                        camera.close()
                        return
                    }
                    cameraDevice = camera
                    createCaptureSession(camera, config, nextInputSurface)
                }

                override fun onDisconnected(camera: CameraDevice) {
                    camera.close()
                    listener.onError("camera disconnected")
                    close()
                }

                override fun onError(camera: CameraDevice, error: Int) {
                    camera.close()
                    listener.onError("camera open failed ($error)")
                    close()
                }
            }
        )
    }

    fun stats(): VideoEncoderRuntimeStats =
        VideoEncoderRuntimeStats(
            emittedSamples = emittedSamples,
            emittedKeyframes = emittedKeyframes,
            outputBytes = outputBytes,
            lastPayloadBytes = lastPayloadBytes,
            droppedInputFrames = droppedOutputBuffers,
            inputLayout = "Surface",
            colorFormat = "Surface"
        )

    override fun close() {
        if (!isClosed.compareAndSet(false, true)) return
        draining = false
        try {
            captureSession?.stopRepeating()
        } catch (_: Exception) {
        }
        try {
            captureSession?.close()
        } catch (_: Exception) {
        }
        captureSession = null
        try {
            cameraDevice?.close()
        } catch (_: Exception) {
        }
        cameraDevice = null
        try {
            codec?.stop()
        } catch (_: Exception) {
        }
        try {
            codec?.release()
        } catch (_: Exception) {
        }
        codec = null
        try {
            inputSurface?.release()
        } catch (_: Exception) {
        }
        inputSurface = null
        codecExecutor.shutdownNow()
    }

    private fun startDrainLoop() {
        codecExecutor.execute {
            val bufferInfo = MediaCodec.BufferInfo()
            while (draining && !isClosed.get()) {
                val activeCodec = codec ?: break
                try {
                    when (val outputIndex = activeCodec.dequeueOutputBuffer(bufferInfo, OUTPUT_TIMEOUT_US)) {
                        MediaCodec.INFO_TRY_AGAIN_LATER -> continue
                        MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> continue
                        else -> {
                            if (outputIndex < 0) continue
                            val outputStartNs = System.nanoTime()
                            val outputBuffer = activeCodec.getOutputBuffer(outputIndex)
                            if (outputBuffer != null && bufferInfo.size > 0) {
                                val payload = ByteArray(bufferInfo.size)
                                outputBuffer.position(bufferInfo.offset)
                                outputBuffer.limit(bufferInfo.offset + bufferInfo.size)
                                outputBuffer.get(payload)

                                val isCodecConfig =
                                    bufferInfo.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0
                                val isKeyframe =
                                    bufferInfo.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
                                outputSequence++
                                emittedSamples++
                                if (isKeyframe) emittedKeyframes++
                                outputBytes += payload.size.toLong()
                                lastPayloadBytes = payload.size

                                val config = resolvedConfig ?: break
                                val captureTimestampMs =
                                    captureTimestampOffsetMs + (bufferInfo.presentationTimeUs / 1_000L)

                                listener.onEncodedSample(
                                    EncodedVideoSample(
                                        sequence = outputSequence,
                                        captureTimestampMs = captureTimestampMs,
                                        presentationTimeUs = bufferInfo.presentationTimeUs,
                                        flags = bufferInfo.flags,
                                        isKeyframe = isKeyframe,
                                        isCodecConfig = isCodecConfig,
                                        width = config.captureSize.width,
                                        height = config.captureSize.height,
                                        encodeCostMs = ((System.nanoTime() - outputStartNs) / 1_000_000.0).toFloat(),
                                        payload = payload
                                    )
                                )
                            }
                            activeCodec.releaseOutputBuffer(outputIndex, false)
                        }
                    }
                } catch (error: Exception) {
                    if (!isClosed.get()) {
                        listener.onError("encoder drain failed", error)
                    }
                    break
                }
            }
        }
    }

    private fun createCaptureSession(
        camera: CameraDevice,
        config: CameraStreamConfig,
        targetSurface: Surface
    ) {
        val outputConfig = OutputConfiguration(targetSurface)
        val sessionConfig = SessionConfiguration(
            SessionConfiguration.SESSION_REGULAR,
            listOf(outputConfig),
            cameraExecutor,
            object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(session: CameraCaptureSession) {
                    if (isClosed.get()) {
                        session.close()
                        return
                    }
                    captureSession = session
                    try {
                        val request = camera.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply {
                            addTarget(targetSurface)
                            set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO)
                            set(
                                CaptureRequest.CONTROL_AF_MODE,
                                CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO
                            )
                            config.fpsRange?.let {
                                set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, it)
                            }
                        }.build()
                        session.setRepeatingRequest(request, null, null)
                        listener.onStarted(
                            actualWidth = config.captureSize.width,
                            actualHeight = config.captureSize.height,
                            rotationDegrees = config.rotationDegrees,
                            fpsRange = config.fpsRange
                        )
                    } catch (error: Exception) {
                        listener.onError("capture start failed", error)
                        close()
                    }
                }

                override fun onConfigureFailed(session: CameraCaptureSession) {
                    listener.onError("capture session configure failed")
                    session.close()
                    close()
                }
            }
        )
        camera.createCaptureSession(sessionConfig)
    }

    private fun resolveCameraConfig(): CameraStreamConfig {
        val cameraId = cameraManager.cameraIdList.firstOrNull { candidate ->
            cameraManager.getCameraCharacteristics(candidate)
                .get(CameraCharacteristics.LENS_FACING) == CameraCharacteristics.LENS_FACING_BACK
        } ?: error("back camera unavailable")

        val characteristics = cameraManager.getCameraCharacteristics(cameraId)
        val streamConfigMap = characteristics.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?: error("camera stream config unavailable")
        val videoSizes =
            streamConfigMap.getOutputSizes(MediaRecorder::class.java)?.toList()
                ?: streamConfigMap.getOutputSizes(SurfaceTexture::class.java)?.toList()
                ?: emptyList()
        if (videoSizes.isEmpty()) error("camera video sizes unavailable")

        val targetAspect = normalizedAspect(profile.width, profile.height)
        val targetPixels = profile.width * profile.height
        val aspectMatched = videoSizes.filter { size ->
            abs(normalizedAspect(size.width, size.height) - targetAspect) <= ASPECT_TOLERANCE
        }
        val candidates = if (aspectMatched.isNotEmpty()) aspectMatched else videoSizes
        val chosenSize = candidates
            .filter { it.width * it.height <= targetPixels }
            .maxByOrNull { it.width * it.height }
            ?: candidates.minByOrNull { abs((it.width * it.height) - targetPixels) }
            ?: error("no capture size selected")

        val sensorOrientation = characteristics.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0
        val rotationDegrees = normalizedRotation(
            sensorOrientation - surfaceRotationToDegrees(displayRotation)
        )
        val fpsRange = chooseFpsRange(
            characteristics.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
                ?.toList()
                .orEmpty(),
            profile.fps,
            profile.minCameraFps
        )
        return CameraStreamConfig(
            cameraId = cameraId,
            captureSize = chosenSize,
            fpsRange = fpsRange,
            rotationDegrees = rotationDegrees
        )
    }

    private fun chooseFpsRange(
        ranges: List<Range<Int>>,
        targetFps: Int,
        minCameraFps: Int
    ): Range<Int>? {
        if (ranges.isEmpty()) return null
        return ranges
            .filter { it.upper >= targetFps && it.lower <= targetFps }
            .minWithOrNull(
                compareBy<Range<Int>>(
                    { abs(it.upper - targetFps) },
                    { abs(it.lower - minCameraFps) }
                )
            )
            ?: ranges.minWithOrNull(
                compareBy<Range<Int>>(
                    { abs(it.upper - targetFps) },
                    { abs(it.lower - minCameraFps) }
                )
            )
    }

    private fun normalizedAspect(width: Int, height: Int): Float {
        val longer = maxOf(width, height).toFloat()
        val shorter = minOf(width, height).toFloat()
        return shorter / longer
    }

    private fun surfaceRotationToDegrees(rotation: Int): Int =
        when (rotation) {
            Surface.ROTATION_90 -> 90
            Surface.ROTATION_180 -> 180
            Surface.ROTATION_270 -> 270
            else -> 0
        }

    private fun normalizedRotation(rotationDegrees: Int): Int =
        ((rotationDegrees % 360) + 360) % 360

    private data class CameraStreamConfig(
        val cameraId: String,
        val captureSize: Size,
        val fpsRange: Range<Int>?,
        val rotationDegrees: Int
    )

    companion object {
        private const val MIME_TYPE = "video/avc"
        private const val OUTPUT_TIMEOUT_US = 10_000L
        private const val ASPECT_TOLERANCE = 0.03f
    }
}
