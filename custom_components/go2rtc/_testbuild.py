"""TEST BUILD ONLY - not part of any upstream change.

Stand-ins for two fixes that are submitted upstream but not yet in a release
Home Assistant ships. Imported first by this test copy of the go2rtc
integration. Delete this file and its import once both are released:

1. python-go2rtc-client: accept producers that report their url as "source".
   go2rtc does this for connected HomeKit producers, which otherwise makes
   listing streams fail and every WebRTC offer for a HomeKit camera error.

2. go2rtc: the ffmpeg module puts the stream name into its loopback RTSP url
   without escaping it. Home Assistant percent-encodes camera identifiers
   (e.g. "homekit_controller_FD%3A53..."), so the RTSP server decodes the
   path, finds no stream and the "#audio=opus" transcode never starts.
   Until go2rtc escapes the name, replace unsafe characters instead of
   percent-encoding them, so names never contain "%".
"""

from typing import Any

from go2rtc_client import models as go2rtc_models, rest as go2rtc_rest
from mashumaro.codecs.basic import BasicDecoder

from homeassistant.components.camera import Camera

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
