"""TEST BUILD ONLY - not part of any upstream change.

Imported first by this test copy of the go2rtc integration.

Stand-ins for changes that are proposed upstream but not yet in a release
Home Assistant ships. Delete each once it is released:

1. python-go2rtc-client: accept producers that report their url as "source".
   go2rtc does this for connected HomeKit producers, which otherwise makes
   listing streams fail and every WebRTC offer for a HomeKit camera error.

2. go2rtc: the ffmpeg module puts the stream name into its loopback RTSP url
   without escaping it. Home Assistant percent-encodes camera identifiers
   (e.g. "homekit_controller_FD%3A53..."), so the RTSP server decodes the
   path, finds no stream and the "#audio=opus" transcode never starts.
   Until go2rtc escapes the name, replace unsafe characters instead of
   percent-encoding them, so names never contain "%".

3. camera: Camera.webrtc_source() and CameraWebRTCProvider.
   async_get_stream_source() (proposed with the go2rtc changes in this build).
   A camera whose only source is native to go2rtc (HomeKit Controller's
   homekit://) gets live view through its WebRTC provider, and HLS through
   the provider's RTSP restream, offered only when the provider can restream
   it and set up again for a cached stream. Core's camera integration can't
   be replaced by a custom copy, so these few functions are patched in here.
"""

import asyncio
import json
import os
from pathlib import Path
import platform
import stat
from typing import Any

from go2rtc_client import models as go2rtc_models, rest as go2rtc_rest
from mashumaro.codecs.basic import BasicDecoder

from homeassistant.components.camera import Camera, CameraWebRTCProvider
from homeassistant.components.camera import (
    const as camera_const,
    entity as camera_entity,
    media_source as camera_media_source,
    webrtc as camera_webrtc,
)
from homeassistant.components.camera.const import (
    CAMERA_STREAM_SOURCE_TIMEOUT,
    StreamType,
)
from homeassistant.core import HomeAssistant

from . import util


def _producer_pre_deserialize(cls: type, d: dict[Any, Any]) -> dict[Any, Any]:
    if "url" not in d and "source" in d:
        d["url"] = d["source"]
    return d


go2rtc_models.Producer.__pre_deserialize__ = classmethod(_producer_pre_deserialize)  # type: ignore[attr-defined]
# The decoder is compiled when created, so rebuild it to pick up the hook
go2rtc_rest._GET_STREAMS_DECODER = BasicDecoder(dict[str, go2rtc_models.Stream])  # noqa: SLF001


def _get_camera_identifier(camera: Camera) -> str:
    attr = camera.entity_id
    if camera.unique_id is not None:
        attr = f"{camera.platform.platform_name}_{camera.unique_id}"
    return "".join(c if c in util._SAFE_CHARS else "_" for c in attr)  # noqa: SLF001


util.get_camera_identifier = _get_camera_identifier


# 3. Camera WebRTC source and provider restream (stand-in, see above)

if not hasattr(Camera, "webrtc_source"):

    async def _webrtc_source(self: Camera) -> str | None:
        return await self.stream_source()

    Camera.webrtc_source = _webrtc_source  # type: ignore[attr-defined]

    async def _async_get_supported_provider(
        hass: HomeAssistant, camera: Camera
    ) -> CameraWebRTCProvider | None:
        providers = hass.data.get(camera_webrtc.DATA_WEBRTC_PROVIDERS)
        if not providers or not (source := await camera.webrtc_source()):  # type: ignore[attr-defined]
            return None
        for provider in providers:
            if provider.async_is_supported(source):
                return provider
        return None

    camera_webrtc.async_get_supported_provider = _async_get_supported_provider
    camera_entity.async_get_supported_provider = _async_get_supported_provider

def _has_own_webrtc_source(camera: Camera) -> bool:
    return getattr(camera.webrtc_source, "__func__", None) is not Camera.webrtc_source  # type: ignore[attr-defined]


if not hasattr(CameraWebRTCProvider, "async_get_stream_source"):

    def _provider_supports_stream_source(self: Any, camera: Camera) -> bool:
        return False

    async def _provider_stream_source(self: Any, camera: Camera) -> str | None:
        return None

    CameraWebRTCProvider.async_supports_stream_source = _provider_supports_stream_source  # type: ignore[attr-defined]
    CameraWebRTCProvider.async_get_stream_source = _provider_stream_source  # type: ignore[attr-defined]

    _create_stream = Camera.async_create_stream

    async def _async_provider_stream_source(camera: Camera) -> str | None:
        # Only for a camera with its own webrtc_source, as for others a missing
        # stream_source means the camera has no stream right now
        if camera.webrtc_provider is None or not _has_own_webrtc_source(camera):
            return None
        async with asyncio.timeout(CAMERA_STREAM_SOURCE_TIMEOUT):
            return await camera.webrtc_provider.async_get_stream_source(camera)  # type: ignore[attr-defined]

    async def _async_create_stream(self: Camera) -> Any:
        if self.stream is not None:
            if getattr(self, "_testbuild_provider_stream", False):
                # The provider may have lost the restream, e.g. when its
                # server restarted, so let it set the restream up again
                if not (source := await _async_provider_stream_source(self)):
                    # Stops the outputs but keeps the stream: a preloaded worker
                    # keeps running, so it resumes with the restream later
                    await self.stream.stop()
                    return None
                if source != self.stream.source:
                    self.stream.update_source(source)
            return await _create_stream(self)
        if await type(self).stream_source(self) is None and (
            source := await _async_provider_stream_source(self)
        ):

            async def _source() -> str:
                return source

            # Only for this call: the camera's own stream_source stays None
            self.stream_source = _source  # type: ignore[method-assign]
            try:
                stream = await _create_stream(self)
            finally:
                del self.stream_source
            self._testbuild_provider_stream = stream is not None  # type: ignore[attr-defined]
            return stream
        return await _create_stream(self)

    Camera.async_create_stream = _async_create_stream  # type: ignore[method-assign]

    # HLS only with a source FFmpeg can open. Only HomeKit Controller uses its
    # own webrtc_source here, and it never has a stream_source.
    _camera_capabilities = Camera.camera_capabilities.fget  # type: ignore[attr-defined]

    def _capabilities(self: Camera) -> Any:
        capabilities = _camera_capabilities(self)
        if (
            _has_own_webrtc_source(self)
            and StreamType.HLS in capabilities.frontend_stream_types
            and (
                self.webrtc_provider is None
                or not self.webrtc_provider.async_supports_stream_source(self)  # type: ignore[attr-defined]
            )
        ):
            capabilities.frontend_stream_types.discard(StreamType.HLS)
        return capabilities

    Camera.camera_capabilities = property(_capabilities)  # type: ignore[assignment, method-assign]

    # Media players get a camera without HLS through the MJPEG proxy, as they
    # did before it had its own WebRTC source
    _resolve_media = camera_media_source.CameraMediaSource.async_resolve_media
    _browse_media = camera_media_source.CameraMediaSource.async_browse_media

    async def _async_resolve_media(self: Any, item: Any) -> Any:
        camera = self.hass.data[camera_const.DATA_COMPONENT].get_entity(item.identifier)
        if (
            camera is not None
            and _has_own_webrtc_source(camera)
            and StreamType.HLS not in camera.camera_capabilities.frontend_stream_types
        ):
            return camera_media_source.PlayMedia(
                f"/api/camera_proxy_stream/{camera.entity_id}", camera.content_type
            )
        return await _resolve_media(self, item)

    async def _async_browse_media(self: Any, item: Any) -> Any:
        result = await _browse_media(self, item)
        known = {child.identifier for child in result.children or []}
        for camera in self.hass.data[camera_const.DATA_COMPONENT].entities:
            if (
                camera.entity_id not in known
                and _has_own_webrtc_source(camera)
                and StreamType.HLS not in camera.camera_capabilities.frontend_stream_types
            ):
                result.children.append(
                    camera_media_source._media_source_for_camera(  # noqa: SLF001
                        self.hass, camera, camera.content_type
                    )
                )
                result.not_shown = max(0, result.not_shown - 1)
        return result

    camera_media_source.CameraMediaSource.async_resolve_media = _async_resolve_media  # type: ignore[method-assign]
    camera_media_source.CameraMediaSource.async_browse_media = _async_browse_media  # type: ignore[method-assign]


# Talk-back to AAC-ELD-only HomeKit cameras (e.g. Aqara G410) goes through a
# go2rtc transcoder: an AAC-ELD encoder writing LOAS (eld-enc --loas, from the
# separate ha-fdk-aac-eld package), named in go2rtc's config. go2rtc uses it
# automatically when a microphone's codec matches nothing the camera takes.
# It needs the go2rtc build shipped in bin/<machine>/ of this test build. Both
# are optional: without them cameras stream without talk-back (or with Opus
# talk-back, if the camera supports Opus).

_COMPONENTS = Path(__file__).parent.parent


def _executable(path: Path) -> str | None:
    """Return the path if the file exists, made executable if needed.

    Marketplace downloads are unpacked without file permissions.
    """
    if not path.is_file():
        return None
    mode = path.stat().st_mode
    if not mode & stat.S_IXUSR:
        os.chmod(path, mode | stat.S_IXUSR)
    return str(path)


def bundled_go2rtc() -> str | None:
    """Return the go2rtc build shipped with this test build, if any."""
    return _executable(Path(__file__).parent / "bin" / platform.machine() / "go2rtc")


def _encoder() -> str | None:
    if bundled_go2rtc() is None:
        return None
    return _executable(
        _COMPONENTS / "fdk_aac_eld" / "bin" / platform.machine() / "eld-enc"
    )


def transcode_config() -> str:
    """Return go2rtc config naming the AAC-ELD transcoder, or "" without it."""
    if (encoder := _encoder()) is None:
        return ""
    source = f"{encoder} -r 16000 -f 480 --loas#audio=pcml/16000#output=eld/16000"
    return f"\ntranscode:\n  eld: {json.dumps(source)}\n"
