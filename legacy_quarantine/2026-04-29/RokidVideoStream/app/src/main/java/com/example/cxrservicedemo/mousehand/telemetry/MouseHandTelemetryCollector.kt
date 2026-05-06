package com.example.cxrservicedemo.mousehand.telemetry

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.TrafficStats
import android.os.BatteryManager
import android.os.Build
import android.os.Debug
import android.os.PowerManager
import android.os.Process
import android.os.SystemClock
import kotlin.math.max

data class MouseHandTelemetrySnapshot(
    val timestampMs: Long,
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
    val networkLabel: String
)

class MouseHandTelemetryCollector(private val context: Context) {

    private val activityManager =
        context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
    private val batteryManager =
        context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
    private val connectivityManager =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private val powerManager =
        context.getSystemService(Context.POWER_SERVICE) as PowerManager

    private var lastCpuMs = 0L
    private var lastWallMs = 0L
    private var lastCpuPercentSmoothed = 0f
    private var lastNetworkWallMs: Long? = null
    private var lastRxBytes = 0L
    private var lastTxBytes = 0L
    private var lastSlowSampleWallMs = 0L
    private var lastBatteryPercent: Int? = null
    private var lastBatteryTempC: Float? = null
    private var lastBatteryCurrentMa: Float? = null
    private var lastThermalStatusLabel: String = "UNKNOWN"
    private var lastJavaHeapMb = 0f
    private var lastNativeHeapMb = 0f
    private var lastTotalPssMb = 0f
    private var lastAvailMemMb = 0f

    fun sample(): MouseHandTelemetrySnapshot {
        val nowWall = SystemClock.elapsedRealtime()
        val nowCpu = Process.getElapsedCpuTime()

        val cpuPercentInstant = if (lastWallMs == 0L) {
            0f
        } else {
            val wallDelta = max(1L, nowWall - lastWallMs)
            val cpuDelta = max(0L, nowCpu - lastCpuMs)
            (cpuDelta.toFloat() / wallDelta.toFloat()) * 100f
        }
        val cpuPercent = if (lastCpuPercentSmoothed == 0f) {
            cpuPercentInstant
        } else {
            lastCpuPercentSmoothed * 0.7f + cpuPercentInstant * 0.3f
        }
        lastWallMs = nowWall
        lastCpuMs = nowCpu
        lastCpuPercentSmoothed = cpuPercent

        if (lastSlowSampleWallMs == 0L || nowWall - lastSlowSampleWallMs >= SLOW_SAMPLE_INTERVAL_MS) {
            refreshSlowMetrics(nowWall)
        }

        val uid = Process.myUid()
        val rxBytes = TrafficStats.getUidRxBytes(uid).takeIf { it >= 0 } ?: 0L
        val txBytes = TrafficStats.getUidTxBytes(uid).takeIf { it >= 0 } ?: 0L
        val networkDeltaMs = max(1L, nowWall - (lastNetworkWallMs ?: nowWall))
        val rxKbps = if (lastNetworkWallMs == null) 0f else ((rxBytes - lastRxBytes).coerceAtLeast(0L) * 8f) / networkDeltaMs.toFloat()
        val txKbps = if (lastNetworkWallMs == null) 0f else ((txBytes - lastTxBytes).coerceAtLeast(0L) * 8f) / networkDeltaMs.toFloat()
        lastNetworkWallMs = nowWall
        lastRxBytes = rxBytes
        lastTxBytes = txBytes

        val activeNetwork = connectivityManager.activeNetworkInfo
        val networkLabel = if (activeNetwork?.isConnected == true) {
            "${activeNetwork.typeName}:${activeNetwork.subtypeName ?: ""}".trimEnd(':')
        } else {
            "offline"
        }

        return MouseHandTelemetrySnapshot(
            timestampMs = System.currentTimeMillis(),
            batteryPercent = lastBatteryPercent,
            batteryTempC = lastBatteryTempC,
            batteryCurrentMa = lastBatteryCurrentMa,
            thermalStatusLabel = lastThermalStatusLabel,
            appCpuPercent = cpuPercent.coerceAtLeast(0f),
            javaHeapMb = lastJavaHeapMb,
            nativeHeapMb = lastNativeHeapMb,
            totalPssMb = lastTotalPssMb,
            availMemMb = lastAvailMemMb,
            rxKbps = rxKbps.coerceAtLeast(0f),
            txKbps = txKbps.coerceAtLeast(0f),
            networkLabel = networkLabel
        )
    }

    private fun refreshSlowMetrics(nowWall: Long) {
        lastSlowSampleWallMs = nowWall

        val runtime = Runtime.getRuntime()
        lastJavaHeapMb = (runtime.totalMemory() - runtime.freeMemory()) / MB
        lastNativeHeapMb = Debug.getNativeHeapAllocatedSize() / MB

        val memInfo = Debug.MemoryInfo()
        Debug.getMemoryInfo(memInfo)
        lastTotalPssMb = memInfo.totalPss / 1024f

        val systemMem = ActivityManager.MemoryInfo()
        activityManager.getMemoryInfo(systemMem)
        lastAvailMemMb = systemMem.availMem / MB

        val batteryIntent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = batteryIntent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryIntent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        lastBatteryPercent = if (level >= 0 && scale > 0) ((level * 100f) / scale).toInt() else null
        lastBatteryTempC = batteryIntent
            ?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
            ?.takeIf { it != Int.MIN_VALUE }
            ?.div(10f)

        val currentNowUa = batteryManager.getLongProperty(BatteryManager.BATTERY_PROPERTY_CURRENT_NOW)
        lastBatteryCurrentMa = if (currentNowUa == Long.MIN_VALUE.toLong() || currentNowUa == 0L) {
            null
        } else {
            currentNowUa / 1000f
        }

        lastThermalStatusLabel = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            when (powerManager.currentThermalStatus) {
                PowerManager.THERMAL_STATUS_NONE -> "NONE"
                PowerManager.THERMAL_STATUS_LIGHT -> "LIGHT"
                PowerManager.THERMAL_STATUS_MODERATE -> "MODERATE"
                PowerManager.THERMAL_STATUS_SEVERE -> "SEVERE"
                PowerManager.THERMAL_STATUS_CRITICAL -> "CRITICAL"
                PowerManager.THERMAL_STATUS_EMERGENCY -> "EMERGENCY"
                PowerManager.THERMAL_STATUS_SHUTDOWN -> "SHUTDOWN"
                else -> "UNKNOWN"
            }
        } else {
            "N/A"
        }
    }

    companion object {
        private const val MB = 1024f * 1024f
        private const val SLOW_SAMPLE_INTERVAL_MS = 6_000L
    }
}
