"""Tests for the ZTE WiFi config flow."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import AbortFlow, FlowResultType

from custom_components.zte_wifi.config_flow import (
    InvalidAuth,
    ZteWifiConfigFlow,
    _async_validate_input,
    _normalize_host,
    _unique_id_from_router_name,
)
from custom_components.zte_wifi.const import DOMAIN
from custom_components.zte_wifi.errors import ZteRouterError


class FakeFlowManager:
    """Minimal config entries flow manager for config-flow tests."""

    def async_progress_by_handler(self, *args: object, **kwargs: object) -> list[dict]:
        """Return no in-progress flows."""
        return []

    def async_abort(self, flow_id: str) -> None:
        """Abort an in-progress flow."""


class FakeConfigEntries:
    """Minimal config entries manager for config-flow tests."""

    def __init__(self, existing_entry: object | None = None) -> None:
        """Initialize fake config entries."""
        self.existing_entry = existing_entry
        self.flow = FakeFlowManager()

    def async_entry_for_domain_unique_id(
        self,
        domain: str,
        unique_id: str,
    ) -> object | None:
        """Return an existing config entry if one has been configured."""
        return self.existing_entry


class FakeHass:
    """Minimal Home Assistant object for config-flow tests."""

    def __init__(self, existing_entry: object | None = None) -> None:
        """Initialize fake Home Assistant object."""
        self.config_entries = FakeConfigEntries(existing_entry)


def _flow(existing_entry: object | None = None) -> ZteWifiConfigFlow:
    """Create an initialized config flow."""
    flow = ZteWifiConfigFlow()
    flow.hass = FakeHass(existing_entry)  # type: ignore[assignment]
    flow.handler = DOMAIN
    flow.flow_id = "test-flow"
    flow.context = {"source": "user"}
    return flow


class ZteWifiConfigFlowTest(unittest.IsolatedAsyncioTestCase):
    """Tests for the ZTE WiFi config flow."""

    async def test_user_step_creates_entry_after_validation(self) -> None:
        """Create an entry with normalized connection data."""
        user_input = {
            CONF_NAME: "Main Router",
            CONF_HOST: "192.168.2.1/",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "secret",
        }

        with patch(
            "custom_components.zte_wifi.config_flow._async_validate_input",
            new=AsyncMock(),
        ) as mock_validate:
            result = await _flow().async_step_user(user_input)

        self.assertEqual(result["type"], FlowResultType.CREATE_ENTRY)
        self.assertEqual(result["title"], "Main Router")
        self.assertEqual(
            result["data"],
            {
                CONF_NAME: "Main Router",
                CONF_HOST: "http://192.168.2.1",
                CONF_USERNAME: "admin",
                CONF_PASSWORD: "secret",
            },
        )
        mock_validate.assert_awaited_once()

    async def test_user_step_shows_invalid_auth_error(self) -> None:
        """Show an invalid_auth form error when login fails."""
        with patch(
            "custom_components.zte_wifi.config_flow._async_validate_input",
            new=AsyncMock(side_effect=InvalidAuth),
        ):
            result = await _flow().async_step_user(
                {
                    CONF_NAME: "Main Router",
                    CONF_HOST: "192.168.2.1",
                    CONF_USERNAME: "admin",
                    CONF_PASSWORD: "bad-secret",
                }
            )

        self.assertEqual(result["type"], FlowResultType.FORM)
        self.assertEqual(result["errors"], {"base": "invalid_auth"})

    async def test_user_step_aborts_existing_router_name(self) -> None:
        """Abort when a normalized router name already has an entry."""
        existing_entry = SimpleNamespace(source="user")

        with (
            patch(
                "custom_components.zte_wifi.config_flow._async_validate_input",
                new=AsyncMock(),
            ) as mock_validate,
            self.assertRaisesRegex(AbortFlow, "already_configured"),
        ):
            await _flow(existing_entry).async_step_user(
                {
                    CONF_NAME: "Main Router",
                    CONF_HOST: "http://192.168.2.1",
                    CONF_USERNAME: "admin",
                    CONF_PASSWORD: "secret",
                }
            )

        mock_validate.assert_not_awaited()

    async def test_user_step_rejects_invalid_host(self) -> None:
        """Show a field error for unsupported host URLs."""
        with patch(
            "custom_components.zte_wifi.config_flow._async_validate_input",
            new=AsyncMock(),
        ) as mock_validate:
            result = await _flow().async_step_user(
                {
                    CONF_NAME: "Main Router",
                    CONF_HOST: "ftp://192.168.2.1",
                    CONF_USERNAME: "admin",
                    CONF_PASSWORD: "secret",
                }
            )

        self.assertEqual(result["type"], FlowResultType.FORM)
        self.assertEqual(result["errors"], {CONF_HOST: "invalid_host"})
        mock_validate.assert_not_awaited()

    async def test_user_step_rejects_empty_router_name(self) -> None:
        """Show a field error for empty router names."""
        with patch(
            "custom_components.zte_wifi.config_flow._async_validate_input",
            new=AsyncMock(),
        ) as mock_validate:
            result = await _flow().async_step_user(
                {
                    CONF_NAME: "  ",
                    CONF_HOST: "192.168.2.1",
                    CONF_USERNAME: "admin",
                    CONF_PASSWORD: "secret",
                }
            )

        self.assertEqual(result["type"], FlowResultType.FORM)
        self.assertEqual(result["errors"], {CONF_NAME: "invalid_name"})
        mock_validate.assert_not_awaited()

    async def test_validate_input_maps_login_failure_to_invalid_auth(self) -> None:
        """Map router login failures to invalid_auth."""
        client = SimpleNamespace(
            get_wifi_networks=AsyncMock(
                side_effect=ZteRouterError("Router login failed: Password is incorrect")
            )
        )

        with (
            patch("custom_components.zte_wifi.config_flow.ZteWifiClient", return_value=client),
            patch("custom_components.zte_wifi.config_flow.async_create_clientsession"),
            self.assertRaises(InvalidAuth),
        ):
            await _async_validate_input(
                FakeHass(),  # type: ignore[arg-type]
                {
                    CONF_NAME: "Main Router",
                    CONF_HOST: "http://192.168.2.1",
                    CONF_USERNAME: "admin",
                    CONF_PASSWORD: "bad-secret",
                },
            )

    def test_normalize_host_accepts_bare_router_address(self) -> None:
        """Normalize bare router addresses to HTTP base URLs."""
        self.assertEqual(_normalize_host("192.168.2.1/"), "http://192.168.2.1")

    def test_unique_id_comes_from_router_name(self) -> None:
        """Build the config entry unique ID from the configured router name."""
        self.assertEqual(_unique_id_from_router_name("  Main   Router "), "main router")


if __name__ == "__main__":
    unittest.main()
