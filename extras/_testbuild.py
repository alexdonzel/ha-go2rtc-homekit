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
   the provider's RTSP restream. Core's camera integration can't be replaced
   by a custom copy, so these few functions are patched in here.
"""

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
    entity as camera_entity,
    webrtc as camera_webrtc,
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

if not hasattr(CameraWebRTCProvider, "async_get_stream_source"):

    async def _provider_stream_source(self: Any, camera: Camera) -> str | None:
        return None

    CameraWebRTCProvider.async_get_stream_source = _provider_stream_source  # type: ignore[attr-defined]

    _create_stream = Camera.async_create_stream

    async def _async_create_stream(self: Camera) -> Any:
        if (
            self.stream is None
            and self.webrtc_provider is not None
            and await type(self).stream_source(self) is None
            and (source := await self.webrtc_provider.async_get_stream_source(self))  # type: ignore[attr-defined]
        ):

            async def _source() -> str:
                return source

            # Only for this call: the camera's own stream_source stays None
            self.stream_source = _source  # type: ignore[method-assign]
            try:
                return await _create_stream(self)
            finally:
                del self.stream_source
        return await _create_stream(self)

    Camera.async_create_stream = _async_create_stream  # type: ignore[method-assign]


# Talk-back to AAC-ELD-only HomeKit cameras (e.g. Aqara G410) goes through
# go2rtc's exec transcoder and an AAC-ELD encoder writing LOAS (eld-enc
# --loas, from the separate ha-fdk-aac-eld package). It needs the go2rtc build
# shipped in bin/<machine>/ of this test build. Both are optional: without
# them cameras stream without talk-back (or with Opus talk-back, if the
# camera supports Opus).

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


def exec_allow_paths() -> str:
    """Return extra exec allow_paths lines for go2rtc's config."""
    if (encoder := _encoder()) is None:
        return ""
    return f"    - {json.dumps(encoder)}\n"


def extra_sources(stream_source: str, identifier: str) -> list[str]:
    """Return the talk-back transcoder source for HomeKit cameras."""
    if not stream_source.startswith("homekit:") or (encoder := _encoder()) is None:
        return []
    return [
        f"exec:{encoder} -r 16000 -f 480 --loas"
        f"#backchannel=1#audio=pcml/16000#play={identifier}"
    ]
