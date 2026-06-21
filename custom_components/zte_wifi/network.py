"""ZTE WiFi network status parsing."""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree

from .errors import ZteRouterError


@dataclass(frozen=True, slots=True)
class ZteWifiNetwork:
    """Parsed status for one ZTE WLAN AP instance."""

    instance_id: str
    enabled: bool | None
    essid: str | None
    alias: str | None
    wlan_view_name: str | None
    band: str | None
    bssid: str | None
    channel_in_used: str | None
    beacon_type: str | None


def parse_wlan_status(text: str) -> list[ZteWifiNetwork]:
    """Parse the router's WLAN status XML response."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as err:
        raise ZteRouterError("Could not parse WLAN status response") from err

    error = root.findtext(".//IF_ERRORSTR")
    if error and error.strip().upper() != "SUCC":
        raise ZteRouterError(f"Router returned WLAN status error: {error.strip()}")

    aps = _parse_parameter_instances(root, "OBJ_WLANAP_ID")
    drivers = {
        instance["_InstID"]: instance
        for instance in _parse_parameter_instances(
            root,
            "OBJ_WLANCONFIGDRV_ID",
        )
        if "_InstID" in instance
    }
    settings = {
        instance["_InstID"]: instance
        for instance in _parse_parameter_instances(
            root,
            "OBJ_WLANSETTING_ID",
        )
        if "_InstID" in instance
    }

    networks: list[ZteWifiNetwork] = []
    for ap in aps:
        instance_id = ap.get("_InstID")
        if not instance_id:
            continue

        driver = drivers.get(instance_id, {})
        wlan_view_name = ap.get("WLANViewName") or driver.get("WLANViewName")
        setting = settings.get(wlan_view_name or "", {})
        enabled = _parse_enabled(ap.get("Enable"))

        networks.append(
            ZteWifiNetwork(
                instance_id=instance_id,
                enabled=enabled,
                essid=ap.get("ESSID"),
                alias=ap.get("Alias"),
                wlan_view_name=wlan_view_name,
                band=setting.get("Band"),
                bssid=driver.get("Bssid"),
                channel_in_used=driver.get("ChannelInUsed"),
                beacon_type=ap.get("BeaconType"),
            )
        )

    return networks


def _parse_parameter_instances(
    root: ElementTree.Element,
    section_name: str,
) -> list[dict[str, str]]:
    instances: list[dict[str, str]] = []
    for instance in root.findall(f".//{section_name}/Instance"):
        parsed: dict[str, str] = {}
        current_name: str | None = None
        for child in instance:
            text = (child.text or "").strip()
            if child.tag == "ParaName":
                current_name = text
            elif child.tag == "ParaValue" and current_name:
                parsed[current_name] = text
                current_name = None
        instances.append(parsed)
    return instances


def _parse_enabled(value: str | None) -> bool | None:
    if value == "1":
        return True
    if value == "0":
        return False
    return None
