"""TEST BUILD ONLY - not part of any upstream change.

Imported first by this test copy of the go2rtc integration.

Stand-ins for two fixes that are submitted upstream but not yet in a release
Home Assistant ships. Delete them once both are released:

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

import json
import os
from pathlib import Path
import platform
import stat
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


# Talk-back to HomeKit cameras needs a go2rtc build with talk-back support,
# shipped in bin/<machine>/ of this test build, and an AAC-ELD encoder, which
# the separate ha-fdk-aac-eld package installs. Both are optional: without the
# go2rtc build Home Assistant's own go2rtc is used, and without the encoder
# cameras stream without talk-back.

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


def talkback_config() -> str:
    """Return go2rtc config enabling talk-back, or "" if it isn't possible."""
    if bundled_go2rtc() is None:
        return ""
    encoder = _executable(
        _COMPONENTS / "fdk_aac_eld" / "bin" / platform.machine() / "eld-enc"
    )
    if encoder is None:
        return ""
    return f"\nhomekit_client:\n  aac_eld_encoder: {json.dumps(encoder)}\n"
