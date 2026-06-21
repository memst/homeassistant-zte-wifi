# ZTE WiFi Home Assistant integration

Tiny YAML-only custom integration that exposes one Home Assistant `switch` for a
ZTE router WLAN AP instance, such as `DEV.WIFI.AP6`.

It fetches a fresh router `_sessionTOKEN`, logs in, and sends the WLAN
`Enable=1` or `Enable=0` requests each time the switch is toggled.

The router does not submit the plain password. Its login page first fetches a
fresh nonce from `logintoken_lua.lua`, then submits:

```text
sha256(password + nonce)
```

That is why the browser's `Password` value changes on every login.

## Install

Copy the integration folder into Home Assistant as:

```text
config/custom_components/zte_wifi/
```

Then restart Home Assistant.

## Configure

Add this to `configuration.yaml`:

```yaml
switch:
  - platform: zte_wifi
    name: ZTE WiFi
    host: http://192.168.2.1
    username: admin
    password: !secret zte_router_password
    instance_id: DEV.WIFI.AP6
    apply_payload:
      _PSKCONIG: "Y"
      BeaconType: 11i
      WPAAuthMode: PSKAuthentication
      "11iAuthMode": PSKAuthentication
      WPAEncryptType: TKIPandAESEncryption
      "11iEncryptType": AESEncryption
      _InstID_PSK: DEV.WIFI.AP6.PSK1
      ESSID: H298A_5G_SSID2
      ESSIDHideEnable: "0"
      EncryptionType: WPA2-PSK-AES
      KeyPassphrase: "!@#$%12345"
      Switch_KeyPassType: "0"
      VapIsolationEnable: "0"
      Btn_cancel_WLANSSIDConf: ""
      Btn_apply_WLANSSIDConf: ""
```

Replace `ESSID` and `KeyPassphrase` with the values your router UI sends. The
integration automatically adds `IF_ACTION`, `Enable`, `_InstID`, and
`_sessionTOKEN`, so do not put those in `apply_payload`.

If your router accepts the short request only, omit `apply_payload`.

The integration only exposes `host`, `name`, `username`, `password`, and
`instance_id` as configuration. The router page paths are internal details.

## Test locally

The fastest pre-deploy test is to call the router client directly from this
repo. This does not start Home Assistant.

```bash
uv run python scripts/toggle_zte_wifi.py on --prompt-password
uv run python scripts/toggle_zte_wifi.py off --prompt-password
```

If your router needs the long submit payload, put the extra fields in a JSON file
without `IF_ACTION`, `Enable`, `_InstID`, or `_sessionTOKEN`:

```json
{
  "_PSKCONIG": "Y",
  "BeaconType": "11i",
  "WPAAuthMode": "PSKAuthentication",
  "11iAuthMode": "PSKAuthentication",
  "WPAEncryptType": "TKIPandAESEncryption",
  "11iEncryptType": "AESEncryption",
  "_InstID_PSK": "DEV.WIFI.AP6.PSK1",
  "ESSID": "H298A_5G_SSID2",
  "ESSIDHideEnable": "0",
  "EncryptionType": "WPA2-PSK-AES",
  "KeyPassphrase": "!@#$%12345",
  "Switch_KeyPassType": "0",
  "VapIsolationEnable": "0",
  "Btn_cancel_WLANSSIDConf": "",
  "Btn_apply_WLANSSIDConf": ""
}
```

Then run:

```bash
uv run python scripts/toggle_zte_wifi.py on --apply-payload apply_payload.json
```

## Use

After restart, Home Assistant creates `switch.zte_wifi`. You can expose that
entity to Assist/voice assistants and say things like:

- "Turn on ZTE WiFi"
- "Turn off ZTE WiFi"

The switch is optimistic and does not poll the router. That keeps it lightweight,
but the displayed state only reflects the last command sent by Home Assistant.
