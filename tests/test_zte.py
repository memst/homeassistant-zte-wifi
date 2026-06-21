"""Tests for the ZTE router client."""

import unittest

from custom_components.zte_wifi.zte import ZteWifiClient


class ZteWifiClientTest(unittest.TestCase):
    """Tests for ZTE router client helpers."""

    def test_hash_password(self) -> None:
        """Hash the router password the same way as the login page."""
        self.assertEqual(
            ZteWifiClient._hash_password("111111", "17007188"),
            "56a0c29b3bd4a366ea5a43f9ae6d19ea8536ad2c0a2261b453ef44a928ff7c24",
        )

    def test_extract_session_token_1_from_login_form(self) -> None:
        """Extract the first session token from the login form only."""
        text = """
        <script>
        var _sessionTmpToken = "999999";
        LoginFormObj.addParameter("_sessionTOKEN", "123456");
        </script>
        """

        self.assertEqual(ZteWifiClient._extract_session_token_1(text), "123456")

    def test_extract_session_token_2_from_page_token(self) -> None:
        """Extract the second session token from the page token only."""
        text = """
        <script>
        LoginFormObj.addParameter("_sessionTOKEN", "123456");
        _sessionTmpToken = "\\x39\\x38\\x37\\x36";
        </script>
        """

        self.assertEqual(ZteWifiClient._extract_session_token_2(text), "9876")


if __name__ == "__main__":
    unittest.main()
