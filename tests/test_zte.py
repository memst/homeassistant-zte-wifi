"""Tests for the ZTE router client."""

from collections.abc import Mapping
import unittest
from unittest.mock import patch
from typing import Any

from custom_components.zte_wifi.zte import ZteWifiClient


class FakeHeaders(dict[str, str]):
    """Minimal aiohttp-like headers object for tests."""

    def getall(self, name: str, default: list[str] | None = None) -> list[str]:
        value = self.get(name)
        if value is None:
            return default or []
        return [value]


class FakeResponse:
    """Minimal aiohttp-like response object for tests."""

    def __init__(
        self,
        text: str,
        status: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = FakeHeaders(headers or {})
        self._text = text

    async def text(self) -> str:
        return self._text


class FakeRequestContext:
    """Async context manager returned by the fake session."""

    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> FakeResponse:
        return self._response

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    """Record requests and return canned router responses."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeRequestContext:
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeRequestContext(self._responses.pop(0))


class ZteWifiClientTest(unittest.TestCase):
    """Tests for ZTE router client helpers."""

    def setUp(self) -> None:
        """Create a lightweight client for helper-level tests."""
        self.client = ZteWifiClient(
            session=None,  # type: ignore[arg-type]
            host="http://192.168.2.1",
            username="admin",
            password="secret",
            instance_id="DEV.WIFI.AP6",
        )

    def test_hash_password(self) -> None:
        """Hash the router password the same way as the login page."""
        self.assertEqual(
            ZteWifiClient._hash_password("111111", "17007188"),
            "56a0c29b3bd4a366ea5a43f9ae6d19ea8536ad2c0a2261b453ef44a928ff7c24",
        )

    def test_extract_login_form_token(self) -> None:
        """Extract the login form token only."""
        text = """
        <script>
        var _sessionTmpToken = "999999";
        LoginFormObj.addParameter("_sessionTOKEN", "123456");
        </script>
        """

        self.assertEqual(ZteWifiClient._extract_login_form_token(text), "123456")

    def test_extract_wlan_page_token(self) -> None:
        """Extract the WLAN page token only."""
        text = """
        <script>
        LoginFormObj.addParameter("_sessionTOKEN", "123456");
        _sessionTmpToken = "\\x39\\x38\\x37\\x36";
        </script>
        """

        self.assertEqual(ZteWifiClient._extract_wlan_page_token(text), "9876")

    def test_extract_token_prefers_page_token(self) -> None:
        """Prefer the temporary page token when both token forms exist."""
        text = """
        <script>
        LoginFormObj.addParameter("_sessionTOKEN", "123456");
        _sessionTmpToken = "\\x39\\x38\\x37\\x36";
        </script>
        """

        self.assertEqual(ZteWifiClient._extract_token(text), "9876")

    def test_build_apply_payload_merges_router_fields_last(self) -> None:
        """Always overwrite dynamic router fields in the apply payload."""
        payload = self.client._build_apply_payload(
            enabled_value="1",
            session_token="654321",
            extra_payload={
                "ESSID": "Guest",
                "Enable": "0",
                "_sessionTOKEN": "stale",
            },
        )

        self.assertEqual(
            payload,
            {
                "ESSID": "Guest",
                "IF_ACTION": "Apply",
                "Enable": "1",
                "_InstID": "DEV.WIFI.AP6",
                "_sessionTOKEN": "654321",
            },
        )

    def test_is_login_page_detects_login_form_markup(self) -> None:
        """Treat a rendered login form as a login page."""
        text = "<input name='Username'><input name='Password'><button>Login</button>"

        self.assertTrue(ZteWifiClient._is_login_page(text))

    def test_headers_always_include_test_cookie_first(self) -> None:
        """Always send the router test cookie before SID."""
        self.client._cookies["SID"] = "sid-value"

        headers = self.client._headers_with_cookies({})

        self.assertEqual(headers["Cookie"], "_TESTCOOKIESUPPORT=1; SID=sid-value")


class ZteWifiClientRequestFlowTest(unittest.IsolatedAsyncioTestCase):
    """Tests for the documented router request sequence."""

    async def test_set_enabled_follows_documented_request_order(self) -> None:
        """Use login_form_token for login and wlan_page_token for WLAN apply."""
        session = FakeSession(
            [
                FakeResponse(
                    'LoginFormObj.addParameter("_sessionTOKEN", "111111");'
                ),
                FakeResponse("<token>17007188</token>"),
                FakeResponse("", status=302, headers={"Set-Cookie": "SID=sid-value"}),
                FakeResponse('_sessionTmpToken = "222222";'),
                FakeResponse("<ok/>"),
            ]
        )
        client = ZteWifiClient(
            session=session,  # type: ignore[arg-type]
            host="http://192.168.2.1",
            username="admin",
            password="111111",
            instance_id="DEV.WIFI.AP6",
        )

        with patch("custom_components.zte_wifi.zte.time", return_value=0):
            await client.set_enabled(False)

        self.assertEqual(
            [
                (call["method"], call["url"].split("192.168.2.1", 1)[1])
                for call in session.calls
            ],
            [
                ("GET", "/"),
                (
                    "GET",
                    "/function_module/login_module/login_page/logintoken_lua.lua?_=0",
                ),
                ("POST", "/"),
                (
                    "GET",
                    "/getpage.lua?pid=123&nextpage=Localnet_WlanBasicUser_t.lp&Menu3Location=0&_=0",
                ),
                ("POST", "/common_page/Localnet_WlanBasicAd_WLANSSIDConf_lua.lua"),
            ],
        )
        self.assertEqual(session.calls[0]["headers"]["Cookie"], "_TESTCOOKIESUPPORT=1")
        self.assertEqual(
            session.calls[2]["data"]["_sessionTOKEN"],
            "111111",
        )
        self.assertEqual(session.calls[2]["allow_redirects"], False)
        self.assertEqual(
            session.calls[4]["headers"]["Cookie"],
            "_TESTCOOKIESUPPORT=1; SID=sid-value",
        )
        self.assertEqual(
            session.calls[4]["data"],
            {
                "IF_ACTION": "Apply",
                "Enable": "0",
                "_InstID": "DEV.WIFI.AP6",
                "_sessionTOKEN": "222222",
            },
        )


if __name__ == "__main__":
    unittest.main()
