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

_LOGIN_TOKEN_PATH = "/function_module/login_module/login_page/logintoken_lua.lua"
_WLAN_PAGE_PATH = (
    "/getpage.lua?pid=123&nextpage=Localnet_WlanBasicUser_t.lp&Menu3Location=0"
)
_WLAN_AP_PATH = "/common_page/Localnet_WlanBasicAd_WLANSSIDConf_lua.lua"

_LOGGER = logging.getLogger(__name__)

_LOGIN_FORM_TOKEN_PATTERNS = (
    re.compile(r'LoginFormObj\.addParameter\(["\']_sessionTOKEN["\'],\s*["\']([0-9]+)["\']\)'),
)
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

    _cookies: dict[str, str] = field(default_factory=dict)
    _dump_count: int = 0
    _last_location: str | None = None
    _token: str | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def set_enabled(self, enabled: bool) -> None:
        """Set the WLAN AP enabled flag."""
        async with self._lock:
            await self._set_enabled(enabled)

    async def _set_enabled(self, enabled: bool) -> None:
        await self._login()
        page_text = await self._get(self._cache_busted(_WLAN_PAGE_PATH))
        wlan_page_token = self._extract_wlan_page_token(page_text)
        if not wlan_page_token:
            raise ZteRouterError("Could not find _sessionTmpToken on WLAN page")
        self._token = wlan_page_token

        value = "1" if enabled else "0"
        text = await self._post(
            _WLAN_AP_PATH,
            self._build_apply_payload(value, wlan_page_token),
            _AJAX_HEADERS,
        )
        wlan_page_token = self._update_token(text) or wlan_page_token

        if self.apply_payload:
            text = await self._post(
                _WLAN_AP_PATH,
                self._build_apply_payload(value, wlan_page_token, self.apply_payload),
                _AJAX_HEADERS,
            )
            self._update_token(text)

    async def _login(self) -> str:
        self._token = None
        self._cookies = {"_TESTCOOKIESUPPORT": "1"}
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
        if "SID" not in self._cookies:
            raise ZteRouterError("Router login did not return a SID cookie")
        return login_form_token

    async def _get(self, path: str) -> str:
        request_headers = self._headers_with_cookies(_BROWSER_HEADERS)
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
        request_headers = self._headers_with_cookies(headers)
        _LOGGER.debug("POST %s payload=%s", path, self._redact_payload(payload))
        response = await self._request(
            "POST",
            path,
            request_headers,
            payload=payload,
            allow_redirects=allow_redirects,
        )
        self._last_location = response.location
        if self._last_location:
            _LOGGER.debug("POST %s redirect_location=%s", path, self._last_location)
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
        try:
            async with self.session.request(
                method,
                self._url(path),
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

        self._record_response(method, path, headers, response_data)
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

    def _headers_with_cookies(self, headers: Mapping[str, str]) -> dict[str, str]:
        merged = dict(headers)
        merged.setdefault("referer", self.host.rstrip("/") + "/")
        self._cookies.setdefault("_TESTCOOKIESUPPORT", "1")
        if self._cookies:
            cookie_parts = []
            if "_TESTCOOKIESUPPORT" in self._cookies:
                cookie_parts.append(
                    f"_TESTCOOKIESUPPORT={self._cookies['_TESTCOOKIESUPPORT']}"
                )
            if "SID" in self._cookies:
                cookie_parts.append(f"SID={self._cookies['SID']}")
            cookie_parts.extend(
                f"{key}={value}"
                for key, value in self._cookies.items()
                if key not in {"_TESTCOOKIESUPPORT", "SID"}
            )
            merged["Cookie"] = "; ".join(cookie_parts)
        return merged

    def _build_apply_payload(
        self,
        enabled_value: str,
        session_token: str,
        extra_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(extra_payload or {})
        payload.update(
            {
                "IF_ACTION": "Apply",
                "Enable": enabled_value,
                "_InstID": self.instance_id,
                "_sessionTOKEN": session_token,
            }
        )
        return payload

    def _record_response(
        self,
        method: str,
        path: str,
        request_headers: Mapping[str, str],
        response: _ResponseData,
    ) -> None:
        self._store_cookies(response.set_cookie_headers)
        self._print_diagnostics(
            method,
            path,
            request_headers,
            response.status,
            response.text,
            location=response.location,
            set_cookie_headers=response.set_cookie_headers,
        )
        self._log_response(method, path, response.status, response.text)
        self._dump_response(method, path, response.status, response.text)

    def _update_token(self, text: str) -> str | None:
        token = self._extract_wlan_page_token(text)
        if token:
            self._token = token
            _LOGGER.debug("Updated ZTE router session token")
        return token

    def _store_cookies(self, values: list[str]) -> None:
        for value in values:
            _LOGGER.debug("Router Set-Cookie: %s", value)
            cookie = SimpleCookie(value)
            for key, morsel in cookie.items():
                self._cookies[key] = morsel.value
        self._cookies.setdefault("_TESTCOOKIESUPPORT", "1")
        if values:
            _LOGGER.debug("Stored router cookies: %s", sorted(self._cookies))

    def _print_diagnostics(
        self,
        method: str,
        path: str,
        request_headers: Mapping[str, str],
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
        for pattern in _LOGIN_FORM_TOKEN_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _extract_wlan_page_token(text: str) -> str | None:
        tmp_tokens = _WLAN_PAGE_TOKEN_PATTERN.findall(text)
        if tmp_tokens:
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

    @classmethod
    def _login_error_message(cls, text: str) -> str:
        match = re.search(r"var login_err_msg = [\"']([^\"']*)[\"']", text)
        if match:
            message = cls._decode_js_token(match.group(1))
            if message:
                return f"Router login failed: {message}"
        return "Router login failed"

    @staticmethod
    def _is_login_page(text: str) -> bool:
        return (
            "showloginPage" in text
            or "Please login" in text
            or ZteWifiClient._looks_like_login_page(text)
        )

    @staticmethod
    def _extract_login_token(text: str) -> str:
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as err:
            raise ZteRouterError("Could not parse login token response") from err

        if root.text:
            return root.text.strip()
        raise ZteRouterError("Router returned an empty login token")

    @staticmethod
    def _looks_like_login_page(text: str) -> bool:
        lowered = text.lower()
        return "username" in lowered and "password" in lowered and "login" in lowered
