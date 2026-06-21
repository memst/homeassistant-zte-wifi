"""Switch platform for the ZTE WiFi integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from aiohttp import CookieJar
from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_INSTANCE_ID,
    DEFAULT_HOST,
    DEFAULT_INSTANCE_ID,
    DEFAULT_NAME,
    DEVICE_MODEL,
    DOMAIN,
)
from .coordinator import ZteWifiDataUpdateCoordinator
from .errors import ZteRouterError
from .network import ZteWifiNetwork
from .zte import ZteWifiClient

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_HOST, default=DEFAULT_HOST): cv.url,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_INSTANCE_ID, default=DEFAULT_INSTANCE_ID): cv.string,
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
    async_add_entities(
        [
            ZteWifiSwitch(
                name=config[CONF_NAME],
                client=client,
                instance_id=config[CONF_INSTANCE_ID],
            )
        ]
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ZTE WiFi switches from a config entry."""
    router_name = entry.data[CONF_NAME]
    client = _build_client(hass, entry.data)
    coordinator = ZteWifiDataUpdateCoordinator(hass, client, router_name)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except Exception as err:
        raise ConfigEntryNotReady(f"Could not set up ZTE WiFi: {err}") from err

    async_add_entities(
        ZteWifiApSwitch(
            coordinator=coordinator,
            router_unique_id=entry.unique_id or router_name.casefold(),
            router_name=router_name,
            host=entry.data[CONF_HOST],
            instance_id=network.instance_id,
        )
        for network in sorted(
            coordinator.data.values(),
            key=lambda item: item.instance_id,
        )
    )


def _build_client(hass: HomeAssistant, config: Mapping[str, Any]) -> ZteWifiClient:
    """Create a router client from integration configuration."""
    return ZteWifiClient(
        session=async_create_clientsession(
            hass,
            cookie_jar=CookieJar(unsafe=True),
        ),
        host=config[CONF_HOST],
        username=config[CONF_USERNAME],
        password=config[CONF_PASSWORD],
    )


class ZteWifiApSwitch(
    CoordinatorEntity[ZteWifiDataUpdateCoordinator],
    SwitchEntity,
):
    """Switch for one ZTE WLAN AP discovered from a router config entry."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: ZteWifiDataUpdateCoordinator,
        router_unique_id: str,
        router_name: str,
        host: str,
        instance_id: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._instance_id = instance_id
        self._attr_unique_id = f"{DOMAIN}_{router_unique_id}_{instance_id}"
        self._attr_name = self._build_name(instance_id, self._network)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, router_unique_id)},
            manufacturer="ZTE",
            name=router_name,
            model=DEVICE_MODEL,
            configuration_url=host,
        )

    @property
    def _network(self) -> ZteWifiNetwork | None:
        return self.coordinator.data.get(self._instance_id)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._network is not None

    @property
    def is_on(self) -> bool | None:
        """Return true if the AP is enabled."""
        network = self._network
        return network.enabled if network else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return extra WLAN AP state attributes."""
        network = self._network
        if network is None:
            return {"instance_id": self._instance_id}

        return {
            "instance_id": network.instance_id,
            "essid": network.essid,
            "alias": network.alias,
            "wlan_view_name": network.wlan_view_name,
            "band": network.band,
            "bssid": network.bssid,
            "channel_in_used": network.channel_in_used,
            "beacon_type": network.beacon_type,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the AP."""
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the AP."""
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        try:
            await self.coordinator.client.set_enabled(enabled, self._instance_id)
        except ZteRouterError as err:
            raise HomeAssistantError(
                f"Could not update ZTE WiFi AP {self._instance_id}: {err}"
            ) from err

        _LOGGER.debug(
            "Set ZTE WiFi AP %s to %s",
            self._instance_id,
            "on" if enabled else "off",
        )
        await self.coordinator.async_request_refresh()

    @staticmethod
    def _build_name(
        instance_id: str,
        network: ZteWifiNetwork | None,
    ) -> str:
        if network is None:
            return instance_id
        return network.essid or network.alias or instance_id


class ZteWifiSwitch(SwitchEntity):
    """Optimistic switch for the second ZTE WiFi AP."""

    _attr_has_entity_name = False

    def __init__(self, name: str, client: ZteWifiClient, instance_id: str) -> None:
        """Initialize the switch."""
        self._attr_name = name
        self._attr_unique_id = self._build_unique_id(client, instance_id)
        self._attr_is_on: bool | None = None
        self._attr_available = True
        self._client = client
        self._instance_id = instance_id

    @staticmethod
    def _build_unique_id(client: ZteWifiClient, instance_id: str) -> str:
        """Build a stable unique ID from the router target."""
        return f"{DOMAIN}_{client.host}_{instance_id}".replace(
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
            await self._client.set_enabled(enabled, self._instance_id)
        except ZteRouterError as err:
            self._attr_available = False
            self.async_write_ha_state()
            raise HomeAssistantError(f"Could not update ZTE WiFi: {err}") from err

        self._attr_available = True
        self._attr_is_on = enabled
        _LOGGER.debug("Set ZTE WiFi to %s", "on" if enabled else "off")
        self.async_write_ha_state()
