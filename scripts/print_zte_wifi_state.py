"""Print the current ZTE WiFi SSID state."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys
import traceback

from aiohttp import ClientSession, CookieJar

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.zte_wifi.const import DEFAULT_HOST, DEFAULT_INSTANCE_ID  # noqa: E402
from custom_components.zte_wifi.zte import ZteRouterError, ZteWifiClient  # noqa: E402


def _enabled_label(enabled: bool | None) -> str:
    if enabled is True:
        return "enabled"
    if enabled is False:
        return "disabled"
    return "unknown"


async def _run(args: argparse.Namespace) -> None:
    password = args.password or os.getenv("ZTE_WIFI_PASSWORD")
    if not password and args.prompt_password:
        password = input("Router password: ")
    if not password:
        raise SystemExit(
            "Pass --password, set ZTE_WIFI_PASSWORD, or use --prompt-password"
        )

    async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        client = ZteWifiClient(
            session=session,
            host=args.host,
            username=args.username,
            password=password,
            instance_id=DEFAULT_INSTANCE_ID,
            diagnostics=True,
        )
        networks = await client.get_wifi_networks()

    if not networks:
        print("No WiFi networks found.")
        return

    id_width = max(len("_InstID"), *(len(network.instance_id) for network in networks))
    essid_width = max(
        len("ESSID"),
        *(len(network.essid or "") for network in networks),
    )

    print(f"{'_InstID':<{id_width}}  {'ESSID':<{essid_width}}  Enabled")
    print(f"{'-' * id_width}  {'-' * essid_width}  -------")
    for network in networks:
        print(
            f"{network.instance_id:<{id_width}}  "
            f"{network.essid or '':<{essid_width}}  "
            f"{_enabled_label(network.enabled)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password")
    parser.add_argument("--prompt-password", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    try:
        asyncio.run(_run(args))
    except ZteRouterError as err:
        traceback.print_exc()
        raise SystemExit(f"Router request failed: {err}") from err


if __name__ == "__main__":
    main()
