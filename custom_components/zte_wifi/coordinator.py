"""Data update coordinator for the ZTE WiFi integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .errors import ZteRouterError
from .network import ZteWifiNetwork
from .zte import ZteWifiClient

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=1)


class ZteWifiDataUpdateCoordinator(
    DataUpdateCoordinator[dict[str, ZteWifiNetwork]]
):
    """Coordinate WLAN AP status updates from the router."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ZteWifiClient,
        router_name: str,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        super().__init__(
            hass,
            _LOGGER,
            name=router_name,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, ZteWifiNetwork]:
        """Fetch current WLAN AP data from the router."""
        try:
            networks = await self.client.get_wifi_networks()
        except ZteRouterError as err:
            raise UpdateFailed(f"Could not update ZTE WiFi data: {err}") from err

        return {network.instance_id: network for network in networks}
