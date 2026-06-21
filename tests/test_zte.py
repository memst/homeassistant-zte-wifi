"""Tests for the ZTE router client."""

from collections.abc import Mapping
from http.cookies import SimpleCookie
import unittest
from unittest.mock import patch
from typing import Any

from aiohttp import CookieJar
from custom_components.zte_wifi.errors import ZteRouterError
from custom_components.zte_wifi.network import parse_wlan_status
from custom_components.zte_wifi.zte import ZteWifiClient
from yarl import URL


def _cookie_pairs(header: str) -> set[str]:
    return set(header.split("; "))


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

    def __init__(
        self,
        response: FakeResponse,
        cookie_jar: CookieJar,
        url: str,
    ) -> None:
        self._response = response
        self._cookie_jar = cookie_jar
        self._url = URL(url)

    async def __aenter__(self) -> FakeResponse:
        for value in self._response.headers.getall("Set-Cookie", []):
            self._cookie_jar.update_cookies(
                SimpleCookie(value), response_url=self._url
            )
        return self._response

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    """Record requests and return canned router responses."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.cookie_jar = CookieJar(unsafe=True)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeRequestContext:
        headers = dict(kwargs.get("headers") or {})
        cookies = self.cookie_jar.filter_cookies(URL(url))
        if cookies:
            headers["Cookie"] = cookies.output(header="", sep=";").strip()
        kwargs["headers"] = headers
        self.calls.append({"method": method, "url": url, **kwargs})
        return FakeRequestContext(self._responses.pop(0), self.cookie_jar, url)


class ZteWifiClientTest(unittest.TestCase):
    """Tests for ZTE router client helpers."""

    def setUp(self) -> None:
        """Create a lightweight client for helper-level tests."""
        self.client = ZteWifiClient(
            session=None,  # type: ignore[arg-type]
            host="http://192.168.2.1",
            username="admin",
            password="secret",
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

    def test_extract_login_error(self) -> None:
        """Extract login errors from the rendered login page script."""
        text = "<script>var login_err_msg = 'Password is incorrect';</script>"

        self.assertEqual(
            ZteWifiClient._extract_login_error(text),
            "Password is incorrect",
        )

    def test_print_diagnostics_prints_to_stdout_when_enabled(self) -> None:
        """Print diagnostics directly for local diagnostic scripts."""
        self.client.diagnostics = True

        with patch("builtins.print") as mock_print:
            self.client._print_diagnostics(
                "GET",
                "/status",
                {"accept": "text/xml"},
                "",
                200,
                "<ajax_response_xml_root><IF_ERRORSTR>SUCC</IF_ERRORSTR></ajax_response_xml_root>",
            )

        mock_print.assert_called_once()
        diagnostics = mock_print.call_args.args[0]
        self.assertIn("=== GET /status ===", diagnostics)
        self.assertIn("request_headers:\n  accept: text/xml", diagnostics)
        self.assertIn("request_cookies: <none>", diagnostics)
        self.assertIn("response_code: 200", diagnostics)
        self.assertIn("  IF_ERRORSTR: SUCC", diagnostics)

    def test_print_diagnostics_logs_debug_when_disabled(self) -> None:
        """Keep request diagnostics available at debug level by default."""
        with patch("custom_components.zte_wifi.zte._LOGGER.debug") as mock_debug:
            self.client._print_diagnostics(
                "POST",
                "/apply",
                {"content-type": "application/x-www-form-urlencoded"},
                "SID=sid-value",
                302,
                "",
                location="/next",
            )

        mock_debug.assert_called_once()
        self.assertEqual(mock_debug.call_args.args[0], "%s")
        diagnostics = mock_debug.call_args.args[1]
        self.assertIn("=== POST /apply ===", diagnostics)
        self.assertIn(
            "request_headers:\n  content-type: application/x-www-form-urlencoded",
            diagnostics,
        )
        self.assertIn("request_cookies: SID=sid-value", diagnostics)
        self.assertIn("response_code: 302", diagnostics)
        self.assertIn("  location: /next", diagnostics)

    def test_is_login_page_detects_login_form_markup(self) -> None:
        """Treat a rendered login form as a login page."""
        text = "<input name='Username'><input name='Password'><button>Login</button>"

        self.assertTrue(ZteWifiClient._is_login_page(text))

    def test_parse_wlan_status_joins_ap_driver_and_band_instances(self) -> None:
        """Parse the router's alternating ParaName/ParaValue WLAN status XML."""
        text = """
        <ajax_response_xml_root>
            <IF_ERRORSTR>SUCC</IF_ERRORSTR>
            <OBJ_WLANAP_ID>
                <Instance>
                    <ParaName>_InstID</ParaName>
                    <ParaValue>DEV.WIFI.AP1</ParaValue>
                    <ParaName>Enable</ParaName>
                    <ParaValue>1</ParaValue>
                    <ParaName>BeaconType</ParaName>
                    <ParaValue>11i</ParaValue>
                    <ParaName>WLANViewName</ParaName>
                    <ParaValue>DEV.WIFI.RD1</ParaValue>
                    <ParaName>Alias</ParaName>
                    <ParaValue>SSID1</ParaValue>
                    <ParaName>ESSID</ParaName>
                    <ParaValue>NETWORK_NAME</ParaValue>
                </Instance>
            </OBJ_WLANAP_ID>
            <OBJ_WLANCONFIGDRV_ID>
                <Instance>
                    <ParaName>_InstID</ParaName>
                    <ParaValue>DEV.WIFI.AP1</ParaValue>
                    <ParaName>Bssid</ParaName>
                    <ParaValue>MAC_ADDRESS</ParaValue>
                    <ParaName>WLANViewName</ParaName>
                    <ParaValue>DEV.WIFI.RD1</ParaValue>
                    <ParaName>ChannelInUsed</ParaName>
                    <ParaValue>11</ParaValue>
                </Instance>
            </OBJ_WLANCONFIGDRV_ID>
            <OBJ_WLANSETTING_ID>
                <Instance>
                    <ParaName>_InstID</ParaName>
                    <ParaValue>DEV.WIFI.RD1</ParaValue>
                    <ParaName>Band</ParaName>
                    <ParaValue>2.4GHz</ParaValue>
                </Instance>
            </OBJ_WLANSETTING_ID>
        </ajax_response_xml_root>
        """

        networks = parse_wlan_status(text)

        self.assertEqual(len(networks), 1)
        self.assertEqual(networks[0].instance_id, "DEV.WIFI.AP1")
        self.assertTrue(networks[0].enabled)
        self.assertEqual(networks[0].essid, "NETWORK_NAME")
        self.assertEqual(networks[0].alias, "SSID1")
        self.assertEqual(networks[0].band, "2.4GHz")
        self.assertEqual(networks[0].bssid, "MAC_ADDRESS")
        self.assertEqual(networks[0].channel_in_used, "11")
        self.assertEqual(networks[0].beacon_type, "11i")


class ZteWifiClientRequestFlowTest(unittest.IsolatedAsyncioTestCase):
    """Tests for the documented router request sequence."""

    async def test_set_enabled_follows_documented_request_order(self) -> None:
        """Use login_form_token for login and wlan_page_token for WLAN apply."""
        session = FakeSession(
            [
                FakeResponse(
                    'LoginFormObj.addParameter("_sessionTOKEN", "111111");',
                    headers={"Set-Cookie": "_TESTCOOKIESUPPORT=1"},
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
        )

        await client.set_enabled(False, "DEV.WIFI.AP6")

        self.assertEqual(
            [
                (call["method"], call["url"].split("192.168.2.1", 1)[1])
                for call in session.calls
            ],
            [
                ("GET", "/"),
                (
                    "GET",
                    "/function_module/login_module/login_page/logintoken_lua.lua",
                ),
                ("POST", "/"),
                (
                    "GET",
                    "/getpage.lua?pid=123&nextpage=Localnet_WlanBasicUser_t.lp&Menu3Location=0",
                ),
                ("POST", "/common_page/Localnet_WlanBasicAd_WLANSSIDConf_lua.lua"),
            ],
        )
        self.assertNotIn("Cookie", session.calls[0]["headers"])
        self.assertEqual(
            session.calls[1]["headers"]["Cookie"],
            "_TESTCOOKIESUPPORT=1",
        )
        self.assertEqual(
            session.calls[2]["headers"]["Cookie"],
            "_TESTCOOKIESUPPORT=1",
        )
        self.assertEqual(
            session.calls[2]["data"]["_sessionTOKEN"],
            "111111",
        )
        self.assertEqual(session.calls[2]["allow_redirects"], False)
        self.assertEqual(
            _cookie_pairs(session.calls[4]["headers"]["Cookie"]),
            {"_TESTCOOKIESUPPORT=1", "SID=sid-value"},
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

    async def test_get_wifi_networks_logs_in_and_fetches_status(self) -> None:
        """Log in before requesting the WLAN status AJAX endpoint."""
        session = FakeSession(
            [
                FakeResponse(
                    'LoginFormObj.addParameter("_sessionTOKEN", "111111");',
                    headers={"Set-Cookie": "_TESTCOOKIESUPPORT=1"},
                ),
                FakeResponse("<token>17007188</token>"),
                FakeResponse("", status=302, headers={"Set-Cookie": "SID=sid-value"}),
                FakeResponse("<ajax_response_xml_root><IF_ERRORSTR>SUCC</IF_ERRORSTR></ajax_response_xml_root>"),
                FakeResponse(
                    """
                    <ajax_response_xml_root>
                        <IF_ERRORSTR>SUCC</IF_ERRORSTR>
                        <OBJ_WLANAP_ID>
                            <Instance>
                                <ParaName>_InstID</ParaName>
                                <ParaValue>DEV.WIFI.AP1</ParaValue>
                                <ParaName>Enable</ParaName>
                                <ParaValue>0</ParaValue>
                                <ParaName>ESSID</ParaName>
                                <ParaValue>Guest</ParaValue>
                            </Instance>
                        </OBJ_WLANAP_ID>
                    </ajax_response_xml_root>
                    """
                ),
            ]
        )
        client = ZteWifiClient(
            session=session,  # type: ignore[arg-type]
            host="http://192.168.2.1",
            username="admin",
            password="111111",
        )

        networks = await client.get_wifi_networks()

        self.assertEqual(
            [
                (call["method"], call["url"].split("192.168.2.1", 1)[1])
                for call in session.calls
            ],
            [
                ("GET", "/"),
                (
                    "GET",
                    "/function_module/login_module/login_page/logintoken_lua.lua",
                ),
                ("POST", "/"),
                (
                    "GET",
                    "/getpage.lua?pid=123&nextpage=Localnet_LocalnetStatusUser_t.lp&Menu3Location=0",
                ),
                ("GET", "/common_page/wlanStatus_lua.lua"),
            ],
        )
        self.assertEqual(networks[0].instance_id, "DEV.WIFI.AP1")
        self.assertFalse(networks[0].enabled)
        self.assertEqual(networks[0].essid, "Guest")
        self.assertEqual(
            session.calls[3]["headers"]["accept"],
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        )
        self.assertNotIn("x-requested-with", session.calls[3]["headers"])
        self.assertEqual(
            session.calls[4]["headers"]["accept"],
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        )
        self.assertNotIn("x-requested-with", session.calls[4]["headers"])
        self.assertNotIn("content-type", session.calls[4]["headers"])

    async def test_login_raises_router_error_when_sid_does_not_change(self) -> None:
        """Fetch and report the login page error when POST leaves SID unchanged."""
        session = FakeSession(
            [
                FakeResponse(
                    'LoginFormObj.addParameter("_sessionTOKEN", "111111");',
                    headers={"Set-Cookie": "SID=stale-sid"},
                ),
                FakeResponse("<token>17007188</token>"),
                FakeResponse("", status=302, headers={"Set-Cookie": "SID=stale-sid"}),
                FakeResponse("<script>var login_err_msg = 'Password is incorrect';</script>"),
            ]
        )
        client = ZteWifiClient(
            session=session,  # type: ignore[arg-type]
            host="http://192.168.2.1",
            username="admin",
            password="111111",
        )

        with self.assertRaisesRegex(
            ZteRouterError,
            "Router login failed: Password is incorrect",
        ):
            await client.get_wifi_networks()

        self.assertEqual(
            [
                (call["method"], call["url"].split("192.168.2.1", 1)[1])
                for call in session.calls
            ],
            [
                ("GET", "/"),
                (
                    "GET",
                    "/function_module/login_module/login_page/logintoken_lua.lua",
                ),
                ("POST", "/"),
                ("GET", "/"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
