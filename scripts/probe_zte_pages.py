"""Probe authenticated ZTE UI pages for the WLAN config page."""

from __future__ import annotations

import argparse
import asyncio
from getpass import getpass
import logging
import os
from pathlib import Path
import sys

from aiohttp import ClientSession

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.zte_wifi.const import DEFAULT_HOST
from custom_components.zte_wifi.zte import ZteRouterError, ZteWifiClient

DEFAULT_CANDIDATES = (
    "Localnet_WlanBasicAd_t.lp",
    "Localnet_WlanBasicAd_lua.lua",
    "Localnet_WlanBasicAd_WLANSSIDConf_t.lp",
    "Localnet_WlanBasicAd_WLANSSIDConf_lua.lua",
    "Localnet_WlanBasicAd_WLANSSIDConf.lp",
    "Localnet_WlanBasicAd.lp",
    "Localnet_WlanAdvanced_t.lp",
    "Localnet_WlanAdvanced_lua.lua",
    "Localnet_WlanBasic_t.lp",
    "Localnet_WlanBasic_lua.lua",
)


async def _run(args: argparse.Namespace) -> None:
    password = args.password or os.getenv("ZTE_WIFI_PASSWORD")
    if not password:
        password = getpass("Router password: ")

    async with ClientSession() as session:
        client = ZteWifiClient(
            session=session,
            host=args.host,
            username=args.username,
            password=password,
            instance_id="DEV.WIFI.AP6",
            dump_dir=Path(args.dump_dir) if args.dump_dir else None,
        )
        await client._login()
        for candidate in args.candidate or DEFAULT_CANDIDATES:
            path = candidate
            if not path.startswith("/"):
                path = f"/getpage.lua?pid=123&nextpage={candidate}"
            try:
                text = await client._get(path)
            except ZteRouterError as err:
                print(f"FAIL {path}: {err}")
                continue

            token = client._extract_token(text)
            markers = [
                marker
                for marker in ("WLANSSIDConf", "DEV.WIFI.AP6", "ESSID", "Enable")
                if marker in text
            ]
            redirect = "window.location.href" in text
            print(
                f"{'HIT' if markers else 'MISS'} {path} "
                f"len={len(text)} token={token or '-'} redirect={redirect} "
                f"markers={','.join(markers) or '-'}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--dump-dir")
    parser.add_argument("candidate", nargs="*")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:%(name)s:%(message)s")

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
