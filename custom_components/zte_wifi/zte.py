"""Small async client for the ZTE router WLAN endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from http.cookies import SimpleCookie
import logging
from pathlib import Path
import re
from time import time
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

from aiohttp import ClientError, ClientSession
from yarl import URL

_LOGIN_TOKEN_PATH = "/function_module/login_module/login_page/logintoken_lua.lua"
_WLAN_PAGE_PATH = (
    "/getpage.lua?pid=123&nextpage=Localnet_WlanBasicUser_t.lp&Menu3Location=0"
)
_LOCALNET_STATUS_PAGE_PATH = (
    "/getpage.lua?pid=123&nextpage=Localnet_LocalnetStatusUser_t.lp&Menu3Location=0"
)
_WLAN_AP_PATH = "/common_page/Localnet_WlanBasicAd_WLANSSIDConf_lua.lua"
_WLAN_STATUS_PATH = "/common_page/wlanStatus_lua.lua"

_LOGGER = logging.getLogger(__name__)

_WLAN_PAGE_TOKEN_PATTERN = re.compile(
    r'_sessionTmpToken\s*=\s*["\']((?:\\x[0-9a-fA-F]{2})+|[0-9]+)["\']'
)

_BROWSER_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "en-GB,en;q=0.9",
    "cache-control": "max-age=0",
    "connection": "keep-alive",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
}

_LOGIN_HEADERS = {
    **_BROWSER_HEADERS,
    "content-type": "application/x-www-form-urlencoded",
}

_AJAX_HEADERS = {
    "accept": "application/xml, text/xml, */*; q=0.01",
    "accept-language": "en-GB,en;q=0.9",
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "pragma": "no-cache",
    "user-agent": _BROWSER_HEADERS["user-agent"],
    "x-requested-with": "XMLHttpRequest",
}

_SECRET_KEYS = {"password", "keypassphrase"}


class ZteRouterError(Exception):
    """Raised when the router rejects or fails a request."""


@dataclass(slots=True)
class _ResponseData:
    """Normalized router response details."""

    status: int
    text: str
    location: str | None = None
    set_cookie_headers: list[str] = field(default_factory=list)


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


@dataclass(slots=True)
class ZteWifiClient:
    """Client for toggling a ZTE WLAN AP instance."""

    session: ClientSession
    host: str
    username: str
    password: str
    instance_id: str
    apply_payload: Mapping[str, Any] = field(default_factory=dict)
    dump_dir: Path | None = None
    diagnostics: bool = False

    _dump_count: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def set_enabled(self, enabled: bool) -> None:
        """Set the WLAN AP enabled flag."""
        async with self._lock:
            await self._set_enabled(enabled)

    async def get_wifi_networks(self) -> list[ZteWifiNetwork]:
        """Log in and fetch the current status for every WLAN AP instance."""
        async with self._lock:
            await self._login()
            await self._get(self._cache_busted(_LOCALNET_STATUS_PAGE_PATH))
            text = await self._get(self._cache_busted(_WLAN_STATUS_PATH))
            return self._parse_wlan_status(text)

    async def _set_enabled(self, enabled: bool) -> None:
        await self._login()
        page_text = await self._get(self._cache_busted(_WLAN_PAGE_PATH))
        wlan_page_token = self._extract_wlan_page_token(page_text)
        if not wlan_page_token:
            raise ZteRouterError("Could not find _sessionTmpToken on WLAN page")

        value = "1" if enabled else "0"
        text = await self._post(
            _WLAN_AP_PATH,
            self._build_apply_payload(value, wlan_page_token),
            _AJAX_HEADERS,
        )
        wlan_page_token = self._extract_wlan_page_token(text) or wlan_page_token

        if self.apply_payload:
            await self._post(
                _WLAN_AP_PATH,
                self._build_apply_payload(value, wlan_page_token, self.apply_payload),
                _AJAX_HEADERS,
            )

    async def _login(self) -> None:
        self.session.cookie_jar.clear()
        text = await self._get("/")
        login_form_token = self._extract_login_form_token(text)
        if not login_form_token:
            raise ZteRouterError("Could not find _sessionTOKEN on login page")

        login_token_text = await self._get(self._cache_busted(_LOGIN_TOKEN_PATH))
        login_token = self._extract_login_token(login_token_text)
        password_hash = self._hash_password(self.password, login_token)

        payload = {
            "Username": self.username,
            "Password": password_hash,
            "action": "login",
            "_sessionTOKEN": login_form_token,
        }
        await self._post("/", payload, _LOGIN_HEADERS, allow_redirects=False)
        if "SID" not in self.session.cookie_jar.filter_cookies(URL(self._url("/"))):
            raise ZteRouterError("Router login did not return a SID cookie")

    async def _get(self, path: str) -> str:
        request_headers = self._request_headers(_BROWSER_HEADERS)
        response = await self._request(
            "GET",
            path,
            request_headers,
        )
        return response.text


    async def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        allow_redirects: bool = False,
    ) -> str:
        request_headers = self._request_headers(headers)
        _LOGGER.debug("POST %s payload=%s", path, self._redact_payload(payload))
        response = await self._request(
            "POST",
            path,
            request_headers,
            payload=payload,
            allow_redirects=allow_redirects,
        )
        if response.location:
            _LOGGER.debug("POST %s redirect_location=%s", path, response.location)
        if "SessionTimeout" in response.text:
            raise ZteRouterError("Router returned SessionTimeout")
        if path != "/" and self._is_login_page(response.text):
            raise ZteRouterError("Router returned the login page")
        return response.text

    async def _request(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        *,
        payload: Mapping[str, Any] | None = None,
        allow_redirects: bool = True,
    ) -> _ResponseData:
        url = self._url(path)
        request_cookies = self._request_cookie_header(url)
        try:
            async with self.session.request(
                method,
                url,
                data=payload,
                headers=headers,
                allow_redirects=allow_redirects,
            ) as response:
                text = await response.text()
                response_data = _ResponseData(
                    status=response.status,
                    text=text,
                    location=response.headers.get("Location"),
                    set_cookie_headers=response.headers.getall("Set-Cookie", []),
                )
        except ClientError as err:
            raise ZteRouterError(f"Router {method} failed: {err}") from err

        self._print_diagnostics(
            method,
            path,
            headers,
            request_cookies,
            response_data.status,
            response_data.text,
            location=response_data.location,
            set_cookie_headers=response_data.set_cookie_headers,
        )
        self._log_response(method, path, response_data.status, response_data.text)
        self._dump_response(method, path, response_data.status, response_data.text)
        if response_data.status >= 400:
            raise ZteRouterError(f"Router {method} returned HTTP {response_data.status}")
        return response_data

    def _url(self, path: str) -> str:
        return urljoin(self.host.rstrip("/") + "/", path.lstrip("/"))

    @staticmethod
    def _cache_busted(path: str) -> str:
        current_ts = int(time() * 1000)
        parts = urlsplit(path)
        query = parts.query
        separator = "&" if query else ""
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                f"{query}{separator}_={current_ts}",
                parts.fragment,
            )
        )

    @staticmethod
    def _hash_password(password: str, login_token: str) -> str:
        return sha256(f"{password}{login_token}".encode()).hexdigest()

    def _request_headers(self, headers: Mapping[str, str]) -> dict[str, str]:
        merged = dict(headers)
        merged.setdefault("referer", self.host.rstrip("/") + "/")
        return merged

    def _request_cookie_header(self, url: str) -> str:
        cookies = self.session.cookie_jar.filter_cookies(URL(url))
        if not cookies:
            return ""
        return cookies.output(header="", sep=";").strip()

    def _build_apply_payload(
        self,
        enabled_value: str,
        session_token: str,
        extra_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            **dict(extra_payload or {}),
            "IF_ACTION": "Apply",
            "Enable": enabled_value,
            "_InstID": self.instance_id,
            "_sessionTOKEN": session_token,
        }

    @classmethod
    def _parse_wlan_status(cls, text: str) -> list[ZteWifiNetwork]:
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as err:
            raise ZteRouterError("Could not parse WLAN status response") from err

        error = root.findtext(".//IF_ERRORSTR")
        if error and error.strip().upper() != "SUCC":
            raise ZteRouterError(f"Router returned WLAN status error: {error.strip()}")

        aps = cls._parse_parameter_instances(root, "OBJ_WLANAP_ID")
        drivers = {
            instance["_InstID"]: instance
            for instance in cls._parse_parameter_instances(
                root,
                "OBJ_WLANCONFIGDRV_ID",
            )
            if "_InstID" in instance
        }
        settings = {
            instance["_InstID"]: instance
            for instance in cls._parse_parameter_instances(
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
            enabled = cls._parse_enabled(ap.get("Enable"))

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

    @staticmethod
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

    @staticmethod
    def _parse_enabled(value: str | None) -> bool | None:
        if value == "1":
            return True
        if value == "0":
            return False
        return None

    def _print_diagnostics(
        self,
        method: str,
        path: str,
        request_headers: Mapping[str, str],
        request_cookies: str,
        status: int,
        text: str,
        location: str | None = None,
        set_cookie_headers: list[str] | None = None,
    ) -> None:
        if not self.diagnostics:
            return

        print(f"\n=== {method} {path} ===")
        print("request_headers:")
        for key, value in request_headers.items():
            print(f"  {key}: {value}")
        print(f"request_cookies: {request_cookies or '<none>'}")
        print(f"response_code: {status}")
        print("parsed_response:")
        for key, value in self._parse_response_parts(
            text, location, set_cookie_headers or []
        ).items():
            print(f"  {key}: {value}")

    @classmethod
    def _parse_response_parts(
        cls,
        text: str,
        location: str | None = None,
        set_cookie_headers: list[str] | None = None,
    ) -> dict[str, str]:
        parts: dict[str, str] = {}
        if location:
            parts["location"] = location
        for set_cookie_header in set_cookie_headers or []:
            cookie = SimpleCookie(set_cookie_header)
            if "SID" in cookie:
                parts["set_cookie_sid"] = cookie["SID"].value
            if "_TESTCOOKIESUPPORT" in cookie:
                parts["set_cookie_test_cookie"] = cookie["_TESTCOOKIESUPPORT"].value
        login_form_token = cls._extract_login_form_token(text)
        if login_form_token:
            parts["login_form_token"] = login_form_token
        wlan_page_token = cls._extract_wlan_page_token(text)
        if wlan_page_token:
            parts["wlan_page_token"] = wlan_page_token

        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            root = None

        if root is not None:
            if root.text and root.text.strip():
                parts["xml_text"] = root.text.strip()
            for name in ("IF_ERRORSTR", "IF_ERRORPARAM", "IF_ERRORTYPE", "CHECK_RESULT"):
                found = root.find(f".//{name}")
                if found is not None and found.text is not None:
                    parts[name] = found.text.strip()

        login_error = re.search(r"var login_err_msg = [\"']([^\"']*)[\"']", text)
        if login_error:
            parts["login_err_msg"] = cls._decode_js_token(login_error.group(1))

        now_status = re.search(r"var NowStatus = [\"']([^\"']*)[\"']", text)
        if now_status:
            parts["NowStatus"] = cls._decode_js_token(now_status.group(1))

        if "window.location.href" in text:
            parts["script_redirect"] = "true"
        return parts or {"summary": "no known markers parsed"}

    def _dump_response(self, method: str, path: str, status: int, text: str) -> None:
        if not self.dump_dir:
            return

        self.dump_dir.mkdir(parents=True, exist_ok=True)
        self._dump_count += 1
        safe_path = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.strip("/") or "root")
        dump_path = self.dump_dir / f"{self._dump_count:02d}_{method}_{status}_{safe_path}.html"
        dump_path.write_text(text)
        _LOGGER.debug("Dumped router response to %s", dump_path)

    @staticmethod
    def _log_response(method: str, path: str, status: int, text: str) -> None:
        snippet = " ".join(text.split())
        _LOGGER.debug("%s %s status=%s body=%s", method, path, status, snippet[:1000])

    @staticmethod
    def _redact_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: "***" if key.lower() in _SECRET_KEYS else value
            for key, value in payload.items()
        }

    @staticmethod
    def _extract_login_form_token(text: str) -> str | None:
        match = re.search(
            r"LoginFormObj\.addParameter"
            r'\(["\']_sessionTOKEN["\'],\s*["\']([0-9]+)["\']\)',
            text,
        )
        return match.group(1) if match else None

    @staticmethod
    def _extract_wlan_page_token(text: str) -> str | None:
        if tmp_tokens := _WLAN_PAGE_TOKEN_PATTERN.findall(text):
            return ZteWifiClient._decode_js_token(tmp_tokens[-1])
        return None

    @classmethod
    def _extract_token(cls, text: str) -> str | None:
        return cls._extract_wlan_page_token(text) or cls._extract_login_form_token(text)

    @staticmethod
    def _decode_js_token(value: str) -> str:
        if "\\x" not in value:
            return value

        return "".join(
            chr(int(match, 16)) for match in re.findall(r"\\x([0-9a-fA-F]{2})", value)
        )

    @staticmethod
    def _is_login_page(text: str) -> bool:
        lowered = text.lower()
        return (
            "showloginPage" in text
            or "Please login" in text
            or (
                "username" in lowered
                and "password" in lowered
                and "login" in lowered
            )
        )

    @staticmethod
    def _extract_login_token(text: str) -> str:
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as err:
            raise ZteRouterError("Could not parse login token response") from err

        if root.text and (token := root.text.strip()):
            return token
        raise ZteRouterError("Router returned an empty login token")
