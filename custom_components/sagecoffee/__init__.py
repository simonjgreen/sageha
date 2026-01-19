"""The Sage Coffee integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from sagecoffee import SageCoffeeClient
from sagecoffee.auth import DEFAULT_CLIENT_ID

from .const import CONF_REFRESH_TOKEN, DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

type SageCoffeeConfigEntry = ConfigEntry[SageCoffeeCoordinator]


class SageCoffeeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for managing Sage Coffee WebSocket connection and state updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SageCoffeeClient,
        appliances: list[dict[str, Any]],
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # We use WebSocket push, not polling
        )
        self.client = client
        self.appliances = appliances
        self._ws_task: asyncio.Task | None = None
        self._states: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Return the current cached state data."""
        return self._states

    def _update_state_from_device(self, state: Any) -> None:
        """Update internal state from a DeviceState object."""
        serial = state.serial_number
        self._states[serial] = {
            "reported_state": state.reported_state,
            "desired_state": state.desired_state,
            "boiler_temps": [
                {"id": b.id, "cur_temp": b.current_temp, "temp_sp": b.target_temp}
                for b in (state.boiler_temps or [])
            ],
            "grind_size": state.grind_size,
            "theme": state.raw_data.get("reported", {}).get("cfg", {}).get("default", {}).get("theme"),
            "brightness": state.raw_data.get("reported", {}).get("cfg", {}).get("default", {}).get("brightness"),
            "work_light_brightness": state.raw_data.get("reported", {}).get("cfg", {}).get("default", {}).get("work_light_brightness"),
            "volume": state.raw_data.get("reported", {}).get("cfg", {}).get("default", {}).get("vol"),
            "idle_time": state.raw_data.get("reported", {}).get("cfg", {}).get("default", {}).get("idle_time"),
            "timezone": state.raw_data.get("reported", {}).get("cfg", {}).get("default", {}).get("timezone"),
            "firmware": state.raw_data.get("reported", {}).get("firmware", {}),
            "raw": state.raw_data,
        }

    async def async_start_websocket(self) -> None:
        """Start the WebSocket listener task."""
        # Fetch initial state for all appliances
        for appliance in self.appliances:
            serial = appliance.serial_number
            try:
                state = await self.client.get_last_state(serial)
                if state:
                    self._update_state_from_device(state)
                    _LOGGER.debug("Got initial state for %s: %s", serial, state.reported_state)
            except Exception as err:
                _LOGGER.warning("Failed to get initial state for %s: %s", serial, err)

        # Notify entities of initial state
        if self._states:
            self.async_set_updated_data(self._states)

        if self._ws_task is None or self._ws_task.done():
            self._ws_task = self.hass.async_create_task(
                self._websocket_listener(),
                name="sagecoffee_websocket",
            )

    async def _websocket_listener(self) -> None:
        """Listen for WebSocket state updates."""
        _LOGGER.debug("Starting WebSocket listener")
        try:
            async for state in self.client.tail_state():
                _LOGGER.debug(
                    "Received state update for %s: %s",
                    state.serial_number,
                    state.reported_state,
                )
                self._update_state_from_device(state)
                self.async_set_updated_data(self._states)
        except asyncio.CancelledError:
            _LOGGER.debug("WebSocket listener cancelled")
            raise
        except Exception as err:
            _LOGGER.exception("WebSocket error: %s", err)

    async def async_stop_websocket(self) -> None:
        """Stop the WebSocket listener task."""
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

    def get_state(self, serial: str) -> dict[str, Any] | None:
        """Get the current state for an appliance."""
        return self._states.get(serial)


async def async_setup_entry(hass: HomeAssistant, entry: SageCoffeeConfigEntry) -> bool:
    """Set up Sage Coffee from a config entry."""
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)

    if not refresh_token:
        raise ConfigEntryAuthFailed("No refresh token available")

    try:
        client = SageCoffeeClient(
            client_id=DEFAULT_CLIENT_ID,
            refresh_token=refresh_token,
        )
        await client.__aenter__()

        # Discover appliances
        appliances = await client.list_appliances()
        if not appliances:
            raise ConfigEntryNotReady("No appliances found")

        _LOGGER.debug("Found %d appliances", len(appliances))

    except Exception as err:
        _LOGGER.error("Failed to connect to Sage Coffee API: %s", err)
        raise ConfigEntryNotReady from err

    # Create coordinator
    coordinator = SageCoffeeCoordinator(hass, client, appliances)

    # Store coordinator in entry runtime data
    entry.runtime_data = coordinator

    # Start WebSocket listener
    await coordinator.async_start_websocket()

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SageCoffeeConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: SageCoffeeCoordinator = entry.runtime_data

    # Stop WebSocket
    await coordinator.async_stop_websocket()

    # Close client
    try:
        await coordinator.client.__aexit__(None, None, None)
    except Exception as err:
        _LOGGER.warning("Error closing client: %s", err)

    # Unload platforms
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
