from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException


@dataclass
class BrowserWebRTCPeer:
    session_id: str
    peer_label: str
    pc: Any
    video_task: asyncio.Task | None = None
    audio_task: asyncio.Task | None = None


class BrowserWebRTCRuntime:
    def __init__(
        self,
        *,
        peer_connection_factory: Callable[[], Any],
        session_description_factory: Callable[..., Any],
        audio_resampler_factory: Callable[..., Any] | None,
        media_runtime: Any,
        sessions: dict[str, Any],
        append_session_log: Callable[[Any, str, dict[str, Any]], None],
        now_ms_provider: Callable[[], int],
        browser_audio_sample_rate: int,
        browser_audio_channels: int,
    ) -> None:
        self._peer_connection_factory = peer_connection_factory
        self._session_description_factory = session_description_factory
        self._audio_resampler_factory = audio_resampler_factory
        self._media_runtime = media_runtime
        self._sessions = sessions
        self._append_session_log = append_session_log
        self._now_ms_provider = now_ms_provider
        self._browser_audio_sample_rate = browser_audio_sample_rate
        self._browser_audio_channels = browser_audio_channels
        self._peers: dict[str, BrowserWebRTCPeer] = {}

    @property
    def peer_count(self) -> int:
        return len(self._peers)

    @property
    def session_ids(self) -> list[str]:
        return list(self._peers.keys())

    async def close_peer(self, session_id: str, *, reason: str) -> None:
        peer = self._peers.pop(session_id, None)
        if peer is None:
            return
        for task in (peer.video_task, peer.audio_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        with suppress(Exception):
            await peer.pc.close()
        session = self._sessions.get(session_id)
        if session is not None:
            self._media_runtime.set_browser_media_state(
                session,
                video_active=False,
                audio_active=False,
                peer_label=peer.peer_label,
            )
            self._append_session_log(
                session,
                "browser_webrtc_closed",
                {
                    "peer": peer.peer_label,
                    "reason": reason,
                },
            )

    async def handle_offer(
        self,
        session: Any,
        *,
        session_id: str,
        sdp: str,
        offer_type: str,
    ) -> dict[str, str]:
        peer = BrowserWebRTCPeer(
            session_id=session_id,
            peer_label=f"browser-webrtc:{session_id}",
            pc=self._peer_connection_factory(),
        )
        await self.close_peer(session_id, reason="replace_peer")
        self._peers[session_id] = peer

        self._append_session_log(
            session,
            "browser_webrtc_offer",
            {
                "type": offer_type,
                "sdpLength": len(sdp),
            },
        )
        self._register_peer_handlers(session, peer)

        try:
            await peer.pc.setRemoteDescription(self._session_description_factory(sdp=sdp, type=offer_type))
            answer = await peer.pc.createAnswer()
            await peer.pc.setLocalDescription(answer)
            await self._wait_for_ice_gathering_complete(peer.pc)
        except Exception as error:
            await self.close_peer(session_id, reason=f"offer_failed:{error}")
            self._append_session_log(
                session,
                "browser_webrtc_offer_failed",
                {"error": str(error)},
            )
            raise HTTPException(status_code=500, detail={"error": "offer_failed", "reason": str(error)}) from error

        local_description = peer.pc.localDescription
        if local_description is None:
            await self.close_peer(session_id, reason="missing_local_description")
            raise HTTPException(status_code=500, detail={"error": "missing_local_description"})

        self._append_session_log(
            session,
            "browser_webrtc_answer",
            {
                "type": local_description.type,
                "sdpLength": len(local_description.sdp or ""),
            },
        )
        return {
            "type": local_description.type,
            "sdp": local_description.sdp,
        }

    def _register_peer_handlers(self, session: Any, peer: BrowserWebRTCPeer) -> None:
        @peer.pc.on("track")
        def _on_track(track: Any) -> None:
            self._append_session_log(
                session,
                "browser_webrtc_track",
                {
                    "kind": getattr(track, "kind", "unknown"),
                },
            )
            if getattr(track, "kind", "") == "video":
                if peer.video_task is not None:
                    peer.video_task.cancel()
                peer.video_task = asyncio.create_task(
                    self._consume_video_track(session, track, peer_label=peer.peer_label)
                )
            elif getattr(track, "kind", "") == "audio":
                if peer.audio_task is not None:
                    peer.audio_task.cancel()
                peer.audio_task = asyncio.create_task(
                    self._consume_audio_track(session, track, peer_label=peer.peer_label)
                )

            @track.on("ended")
            async def _on_ended() -> None:
                self._append_session_log(
                    session,
                    "browser_webrtc_track_ended",
                    {
                        "kind": getattr(track, "kind", "unknown"),
                    },
                )

        @peer.pc.on("connectionstatechange")
        async def _on_connection_state_change() -> None:
            state_value = str(getattr(peer.pc, "connectionState", "unknown"))
            self._append_session_log(
                session,
                "browser_webrtc_connection_state",
                {"state": state_value},
            )
            if state_value in {"failed", "closed", "disconnected"}:
                await self.close_peer(peer.session_id, reason=f"connection_state:{state_value}")

        @peer.pc.on("iceconnectionstatechange")
        async def _on_ice_connection_state_change() -> None:
            self._append_session_log(
                session,
                "browser_webrtc_ice_state",
                {"state": str(getattr(peer.pc, "iceConnectionState", "unknown"))},
            )

    async def _wait_for_ice_gathering_complete(self, pc: Any, timeout_s: float = 5.0) -> None:
        if pc is None or getattr(pc, "iceGatheringState", None) == "complete":
            return
        loop = asyncio.get_running_loop()
        done = loop.create_future()

        @pc.on("icegatheringstatechange")
        def _on_ice_gathering_state_change() -> None:
            if pc.iceGatheringState == "complete" and not done.done():
                done.set_result(True)

        try:
            await asyncio.wait_for(done, timeout=timeout_s)
        except asyncio.TimeoutError:
            pass

    async def _consume_video_track(self, session: Any, track: Any, *, peer_label: str) -> None:
        while True:
            frame = await track.recv()
            capture_timestamp_ms = self._now_ms_provider()
            try:
                bgr_frame = frame.to_ndarray(format="bgr24")
            except Exception as error:
                self._append_session_log(
                    session,
                    "browser_webrtc_video_invalid",
                    {
                        "peer": peer_label,
                        "reason": str(error),
                    },
                )
                continue
            await self._media_runtime.ingest_browser_video_bgr_frame(
                session,
                bgr_frame,
                peer_label=peer_label,
                sequence=session.video_frames + 1,
                capture_timestamp_ms=capture_timestamp_ms,
                rotation_degrees=session.rotation_degrees,
                event_name="browser_webrtc_video_frame",
            )

    async def _consume_audio_track(self, session: Any, track: Any, *, peer_label: str) -> None:
        if self._audio_resampler_factory is None:
            self._append_session_log(
                session,
                "browser_webrtc_audio_invalid",
                {
                    "peer": peer_label,
                    "reason": "audio_resampler_unavailable",
                },
            )
            return
        resampler = self._audio_resampler_factory(
            format="s16",
            layout="mono",
            rate=self._browser_audio_sample_rate,
        )
        while True:
            frame = await track.recv()
            capture_timestamp_ms = self._now_ms_provider()
            try:
                resampled_frames = resampler.resample(frame)
            except Exception as error:
                self._append_session_log(
                    session,
                    "browser_webrtc_audio_invalid",
                    {
                        "peer": peer_label,
                        "reason": str(error),
                    },
                )
                continue
            if not isinstance(resampled_frames, list):
                resampled_frames = [resampled_frames]
            for resampled in resampled_frames:
                if resampled is None:
                    continue
                pcm_bytes = bytes(resampled.planes[0])
                await self._media_runtime.ingest_browser_audio_pcm(
                    session,
                    pcm_bytes,
                    peer_label=peer_label,
                    sequence=session.audio_packets + 1,
                    capture_timestamp_ms=capture_timestamp_ms,
                    sample_rate_hz=self._browser_audio_sample_rate,
                    channels=self._browser_audio_channels,
                    avg_abs=0,
                    peak_abs=0,
                    non_silent_ratio=0.0,
                    audio_source="browser_webrtc_mic",
                    event_name="browser_webrtc_audio_frame",
                )
