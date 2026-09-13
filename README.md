# ZTE WiFi Home Assistant integration

This is a Home Assistant integration that lets users turn on and off APs inside ZTE ZXHN H298A router (a router used by Hyperoptic ISP).

I am willing to accept PRs to this repository but do not plan on actively maintaining it.

> [!WARNING]
> This integration is mostly vibe-coded and not feature-rich, even though I have read and verified all the non-test-file code. Please feel free to use this as a starting point for figuring out how to interact with the router's web-ui. The rest of the text in this readme is AI-generated with minimal review.

Tiny custom integration that exposes one Home Assistant `switch` for a ZTE
router WLAN AP instance, such as `DEV.WIFI.AP6`.

It fetches a fresh router `_sessionTOKEN`, logs in, and sends the WLAN
`Enable=1` or `Enable=0` requests each time the switch is toggled.

The router does not submit the plain password. Its login page first fetches a
fresh nonce from `logintoken_lua.lua`, then submits:

```text
sha256(password + nonce)
```

That is why the browser's `Password` value changes on every login.

## Install

### HACS (recommended)

1. Make sure you have HACS installed in Home Assistant by following [User documentation - HACS](https://www.hacs.xyz/docs/use/#getting-started-with-hacs).
2. Click the button below and follow the instructions or search for **ZTE WiFi (ZXHN H298A)** in the HACS tab of your Home Assistant.
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=memst&repository=homeassistant-zte-wifi)

### Manual

Copy the integration folder into Home Assistant as:

```text
config/custom_components/zte_wifi/
```

Then restart Home Assistant.

## Configure

The integration supports the UI config flow: go to **Settings → Devices &
services → Add integration** and search for **ZTE WiFi (ZXHN H298A)**.

Alternatively, add this to `configuration.yaml`:

```yaml
switch:
  - platform: zte_wifi
    name: ZTE WiFi
    host: http://192.168.2.1
    username: admin
    password: !secret zte_router_password
    instance_id: DEV.WIFI.AP6
```

The integration only exposes `host`, `name`, `username`, `password`, and
`instance_id` as configuration. The router page paths are internal details.

## Test locally

The fastest pre-deploy test is to call the router client directly from this
repo. This does not start Home Assistant.

```bash
uv run python scripts/toggle_zte_wifi.py on --prompt-password
uv run python scripts/toggle_zte_wifi.py off --prompt-password
```

## Use

After setup, Home Assistant creates a switch entity. You can expose that entity
to Assist/voice assistants and say things like:

- "Turn on ZTE WiFi"
- "Turn off ZTE WiFi"

Home Assistant polls the router for WLAN status, so the displayed state reflects
the router when the status endpoint includes the configured AP instance.
