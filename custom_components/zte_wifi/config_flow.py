"""Config flow for the ZTE WiFi integration."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import CookieJar
import voluptuous as vol
from yarl import URL

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers import selector

from .const import DEFAULT_HOST, DEFAULT_INSTANCE_ID, DEFAULT_NAME, DEFAULT_TIMEOUT, DOMAIN
from .errors import ZteRouterError
from .zte import ZteWifiClient


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""


class ZteWifiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ZTE WiFi."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = dict(user_input)
            try:
                data[CONF_NAME] = _normalize_router_name(user_input[CONF_NAME])
            except vol.Invalid:
                errors[CONF_NAME] = "invalid_name"

            try:
                data[CONF_HOST] = _normalize_host(user_input[CONF_HOST])
            except vol.Invalid:
                errors[CONF_HOST] = "invalid_host"

            if not errors:
                await self.async_set_unique_id(
                    _unique_id_from_router_name(data[CONF_NAME])
                )
                self._abort_if_unique_id_configured()

                try:
                    await _async_validate_input(self.hass, data)
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title=data[CONF_NAME],
                        data=data,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )


async def _async_validate_input(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> None:
    """Validate the user input allows us to connect."""
    client = ZteWifiClient(
        session=async_create_clientsession(
            hass,
            cookie_jar=CookieJar(unsafe=True),
        ),
        host=data[CONF_HOST],
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        instance_id=DEFAULT_INSTANCE_ID,
    )

    try:
        async with asyncio.timeout(DEFAULT_TIMEOUT):
            await client.get_wifi_networks()
    except TimeoutError as err:
        raise CannotConnect from err
    except ZteRouterError as err:
        if "login failed" in str(err).lower():
            raise InvalidAuth from err
        raise CannotConnect from err


def _user_schema(
    user_input: dict[str, Any] | None = None,
) -> vol.Schema:
    """Return the user step schema."""
    suggested = user_input or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME,
                default=suggested.get(CONF_NAME, DEFAULT_NAME),
            ): str,
            vol.Required(
                CONF_HOST,
                default=suggested.get(CONF_HOST, DEFAULT_HOST),
            ): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
        }
    )


def _normalize_router_name(name: str) -> str:
    """Normalize the user-provided router identity."""
    value = " ".join(name.split())
    if not value:
        raise vol.Invalid("invalid router name")
    return value


def _normalize_host(host: str) -> str:
    """Normalize a router host into the base URL expected by the client."""
    value = host.strip()
    if "://" not in value:
        value = f"http://{value}"

    url = URL(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.host
        or url.user
        or url.password
    ):
        raise vol.Invalid("invalid host")

    return str(url.with_path("").with_query(None).with_fragment(None)).rstrip("/")


def _unique_id_from_router_name(name: str) -> str:
    """Build a stable unique ID from the configured router name."""
    return _normalize_router_name(name).casefold()
