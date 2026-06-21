"""Local smoke tester for the ZTE WiFi router client."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any

from aiohttp import ClientSession

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.zte_wifi.const import (
    DEFAULT_HOST,
    DEFAULT_INSTANCE_ID,
    DEFAULT_LOGIN_TOKEN_PATH,
    DEFAULT_PAGE_PATH,
)
from custom_components.zte_wifi.zte import ZteWifiClient, ZteRouterError


def _load_apply_payload(value: str | None) -> dict[str, Any]:
    if not value:
        return {}

    path = Path(value)
    if path.exists():
        return json.loads(path.read_text())

    return json.loads(value)


async def _run(args: argparse.Namespace) -> None:
    password = args.password or os.getenv("ZTE_WIFI_PASSWORD")
    if not password and args.prompt_password:
        password = input("Router password: ")
    if not password:
        raise SystemExit(
            "Pass --password, set ZTE_WIFI_PASSWORD, or use --prompt-password"
        )

    async with ClientSession() as session:
        client = ZteWifiClient(
            session=session,
            host=args.host,
            username=args.username,
            password=password,
            instance_id=args.instance_id,
            page_path=args.page_path,
            login_token_path=args.login_token_path,
            apply_payload=_load_apply_payload(args.apply_payload),
            dump_dir=Path(args.dump_dir) if args.dump_dir else None,
            diagnostics=True,
        )
        await client.set_enabled(args.state == "on")

    print(f"ZTE WiFi set to {args.state}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", choices=("on", "off"))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password")
    parser.add_argument("--prompt-password", action="store_true")
    parser.add_argument("--instance-id", default=DEFAULT_INSTANCE_ID)
    parser.add_argument("--page-path", default=DEFAULT_PAGE_PATH)
    parser.add_argument("--login-token-path", default=DEFAULT_LOGIN_TOKEN_PATH)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--dump-dir")
    parser.add_argument(
        "--apply-payload",
        help="JSON object or path to a JSON file with the long submit payload",
    )
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s:%(name)s:%(message)s")

    try:
        asyncio.run(_run(args))
    except ZteRouterError as err:
        raise SystemExit(f"Router request failed: {err}") from err


if __name__ == "__main__":
    main()
