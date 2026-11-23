# go2rtc with HomeKit cameras (test build)

Home Assistant's go2rtc integration with support for HomeKit camera streams, for use with [ha-homekit-controller-stream](https://github.com/alexdonzel/ha-homekit-controller-stream).

## Status

A **test build**, not part of Home Assistant and not supported by the Home
Assistant project. It exists so the proposed changes can be used and tested on
real devices before they are released. Once they are in a Home Assistant
release, uninstall this and use the built-in integration again.

## What it changes

- Enables go2rtc's `homekit` module, so it accepts `homekit://` stream sources, and redacts HomeKit pairing keys from go2rtc's log output (proposed upstream: [home-assistant/core#193419](https://github.com/home-assistant/core/pull/193419)).
- `_testbuild.py`: stand-ins for two fixes not yet in a release Home Assistant ships, a python-go2rtc-client fix ([#432](https://github.com/home-assistant-libs/python-go2rtc-client/pull/432)) and a go2rtc fix ([AlexxIT/go2rtc#2596](https://github.com/AlexxIT/go2rtc/pull/2596)). Together they make camera audio work. See the file for details.

- Talk-back (two-way audio) to HomeKit cameras with a speaker. This needs a go2rtc build with talk-back support, which this test build includes in `bin/` (go2rtc, MIT licence, built by this repository's GitHub Action from [alexdonzel/go2rtc](https://github.com/alexdonzel/go2rtc) at the commit in `go2rtc.ref`, i.e. go2rtc 1.9.15 plus the stream-name escape fix (merged upstream), talk-back, and the IPv6 and ONVIF fixes submitted upstream), and an AAC-ELD encoder, which you install separately from [ha-fdk-aac-eld](https://github.com/alexdonzel/ha-fdk-aac-eld) if you want talk-back. Without the encoder, everything else works and talk-back is off. In the Home Assistant UI, talk-back also needs the two-way audio preview (Settings > System > Labs).

Everything else is the built-in integration from the Home Assistant release
named in the version (`<release>.<build>`), unchanged.

## Install

It replaces the built-in `go2rtc` integration, so install it only if you
want the change above.

1. Settings > Marketplace > ⋮ > Custom repositories, add
   `https://github.com/alexdonzel/ha-go2rtc-homekit` as an integration.
2. Install it, then restart Home Assistant.

Home Assistant logs a warning at startup that a custom `go2rtc` integration
is in use; that is expected.

Use it together with [ha-homekit-controller-stream](https://github.com/alexdonzel/ha-homekit-controller-stream).

## Updates

A GitHub Action rebuilds this integration from each new Home Assistant release
within six hours of it, and publishes it as a new version. **After updating
Home Assistant, install the matching update here too**, or this copy keeps
running the previous release's integration code. If the build fails, the
changes no longer apply to the new release: uninstall this until it is fixed.

## Remove

Uninstall it in the Marketplace (or delete `custom_components/go2rtc`) and
restart Home Assistant. Nothing else is changed.

## How it is built

`tools/build.py` takes `homeassistant/components/go2rtc` from the release,
applies `patches/*.patch`, copies `extras/`, generates its translations and sets the
manifest's version, documentation and issue tracker. `custom_components/` is
generated: change the patches, not the output.

## Licence

Apache License 2.0, as Home Assistant. This repository contains Home Assistant
code, modified as described above.

## Security

A `homekit://` stream source contains Home Assistant's HomeKit pairing key for
the accessory, which lets whoever holds it control the accessory from your
network. It is only passed to Home Assistant's local go2rtc and is redacted from
go2rtc's log output, but treat Home Assistant logs as sensitive if you share
them. Re-pairing an accessory replaces its key.
