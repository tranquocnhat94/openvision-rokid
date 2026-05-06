package com.example.cxrservicedemo.videostream

data class EncodedVideoSample(
    val sequence: Long,
    val captureTimestampMs: Long,
    val presentationTimeUs: Long,
    val flags: Int,
    val isKeyframe: Boolean,
    val isCodecConfig: Boolean,
    val width: Int,
    val height: Int,
    val encodeCostMs: Float = 0f,
    val payload: ByteArray
)

data class VideoEncoderRuntimeStats(
    val emittedSamples: Long,
    val emittedKeyframes: Long,
    val outputBytes: Long,
    val lastPayloadBytes: Int,
    val droppedInputFrames: Long,
    val inputLayout: String,
    val colorFormat: String
)
