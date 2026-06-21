"""Switch platform for the ZTE WiFi integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from aiohttp import CookieJar
from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_APPLY_PAYLOAD,
    CONF_INSTANCE_ID,
    DEFAULT_HOST,
    DEFAULT_INSTANCE_ID,
    DEFAULT_NAME,
    DOMAIN,
)
from .errors import ZteRouterError
from .zte import ZteWifiClient

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_HOST, default=DEFAULT_HOST): cv.url,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_INSTANCE_ID, default=DEFAULT_INSTANCE_ID): cv.string,
        vol.Optional(CONF_APPLY_PAYLOAD, default={}): dict,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the ZTE WiFi switch from YAML."""
    client = _build_client(hass, config)
    async_add_entities([ZteWifiSwitch(config[CONF_NAME], client)])


def _build_client(hass: HomeAssistant, config: ConfigType) -> ZteWifiClient:
    """Create a router client from platform configuration."""
    return ZteWifiClient(
        session=async_create_clientsession(
            hass,
            cookie_jar=CookieJar(unsafe=True),
        ),
        host=config[CONF_HOST],
        username=config[CONF_USERNAME],
        password=config[CONF_PASSWORD],
        instance_id=config[CONF_INSTANCE_ID],
        apply_payload=config[CONF_APPLY_PAYLOAD],
    )


class ZteWifiSwitch(SwitchEntity):
    """Optimistic switch for the second ZTE WiFi AP."""

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_assumed_state = True

    def __init__(self, name: str, client: ZteWifiClient) -> None:
        """Initialize the switch."""
        self._attr_name = name
        self._attr_unique_id = self._build_unique_id(client)
        self._attr_is_on: bool | None = None
        self._attr_available = True
        self._client = client

    @staticmethod
    def _build_unique_id(client: ZteWifiClient) -> str:
        """Build a stable unique ID from the router target."""
        return f"{DOMAIN}_{client.host}_{client.instance_id}".replace(
            "://", "_"
        ).replace("/", "_")

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the AP."""
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the AP."""
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        try:
            await self._client.set_enabled(enabled)
        except ZteRouterError as err:
            self._attr_available = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Could not update ZTE WiFi: {err}") from err

        self._attr_available = True
        self._attr_is_on = enabled
        _LOGGER.debug("Set ZTE WiFi to %s", "on" if enabled else "off")
        self.async_write_ha_state()
