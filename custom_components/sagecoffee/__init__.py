"""The Sage Coffee integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sagecoffee import SageCoffeeClient
from sagecoffee.auth import DEFAULT_CLIENT_ID

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv, httpx_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import ssl as ssl_util
import voluptuous as vol

from .const import CONF_MACHINE_TYPE, CONF_REFRESH_TOKEN, DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_WAKE_SCHEDULE = "set_wake_schedule"
SERVICE_DISABLE_WAKE_SCHEDULE = "disable_wake_schedule"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_SERIAL = "serial"
ATTR_HOURS = "hours"
ATTR_MINUTES = "minutes"
ATTR_DAYS = "days"
ATTR_ENABLED = "enabled"

SET_WAKE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SERIAL): cv.string,
        vol.Required(ATTR_HOURS): vol.Range(min=0, max=23),
        vol.Required(ATTR_MINUTES): vol.Range(min=0, max=59),
        vol.Optional(ATTR_DAYS): vol.All(
            [vol.In(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])]
        ),
        vol.Optional(ATTR_ENABLED, default=True): cv.boolean,
    }
)

DISABLE_WAKE_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SERIAL): cv.string,
    }
)

type SageCoffeeConfigEntry = ConfigEntry[SageCoffeeCoordinator]


class SageCoffeeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for managing Sage Coffee WebSocket connection and state updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SageCoffeeClient,
        appliances: list[dict[str, Any]],
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # We use WebSocket push, not polling
            config_entry=config_entry,
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
            "theme": state.raw_data.get("reported", {})
            .get("cfg", {})
            .get("default", {})
            .get("theme"),
            "brightness": state.raw_data.get("reported", {})
            .get("cfg", {})
            .get("default", {})
            .get("brightness"),
            "work_light_brightness": state.raw_data.get("reported", {})
            .get("cfg", {})
            .get("default", {})
            .get("work_light_brightness"),
            "volume": state.raw_data.get("reported", {})
            .get("cfg", {})
            .get("default", {})
            .get("vol"),
            "idle_time": state.raw_data.get("reported", {})
            .get("cfg", {})
            .get("default", {})
            .get("idle_time"),
            "timezone": state.raw_data.get("reported", {})
            .get("cfg", {})
            .get("default", {})
            .get("timezone"),
            "firmware": state.raw_data.get("reported", {}).get("firmware", {}),
        }

    async def async_start_websocket(self) -> None:
        """Start the WebSocket listener task."""
        # Fetch initial state for all appliances (get_last_state is NOT async)
        for appliance in self.appliances:
            serial = appliance.serial_number
            try:
                state = self.client.get_last_state(serial)
                if state:
                    self._update_state_from_device(state)
                    _LOGGER.debug(
                        "Got initial state for %s: %s", serial, state.reported_state
                    )
            except Exception as err:
                _LOGGER.warning("Failed to get initial state for %s: %s", serial, err)

        # Notify entities of initial state
        if self._states:
            self.async_set_updated_data(self._states)

        if self._ws_task is None or self._ws_task.done():
            self._ws_task = self.hass.async_create_background_task(
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
        # Clear stored states and appliances to prevent memory leaks
        self._states.clear()
        self.appliances.clear()

    def get_state(self, serial: str) -> dict[str, Any] | None:
        """Get the current state for an appliance."""
        return self._states.get(serial)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Sage Coffee integration."""
    async def set_wake_schedule(call: ServiceCall) -> ServiceResponse:
        """Set wake schedule for an appliance."""
        serial = call.data.get(ATTR_SERIAL)
        hours = call.data.get(ATTR_HOURS)
        minutes = call.data.get(ATTR_MINUTES)
        days = call.data.get(ATTR_DAYS)
        enabled = call.data.get(ATTR_ENABLED, True)

        # Find the config entry with this appliance
        entry: SageCoffeeConfigEntry | None = None
        for config_entry in hass.config_entries.async_entries(DOMAIN):
            if config_entry.state is not ConfigEntryState.LOADED:
                continue
            coordinator: SageCoffeeCoordinator = config_entry.runtime_data
            if any(a.serial_number == serial for a in coordinator.appliances):
                entry = config_entry
                break

        if not entry:
            raise ServiceValidationError(f"Appliance {serial} not found")

        coordinator = entry.runtime_data

        try:
            # Convert days list to the format expected by the API (comma-separated string)
            days_str = ",".join(days) if days else None

            # Call the API to set wake schedule
            await coordinator.client.set_wake_schedule(
                serial=serial,
                hours=hours,
                minutes=minutes,
                days=days_str,
                enabled=enabled,
            )
        except Exception as err:
            raise HomeAssistantError(f"Failed to set wake schedule: {err}") from err

        return None

    async def disable_wake_schedule(call: ServiceCall) -> ServiceResponse:
        """Disable wake schedule for an appliance."""
        serial = call.data.get(ATTR_SERIAL)

        # Find the config entry with this appliance
        entry: SageCoffeeConfigEntry | None = None
        for config_entry in hass.config_entries.async_entries(DOMAIN):
            if config_entry.state is not ConfigEntryState.LOADED:
                continue
            coordinator: SageCoffeeCoordinator = config_entry.runtime_data
            if any(a.serial_number == serial for a in coordinator.appliances):
                entry = config_entry
                break

        if not entry:
            raise ServiceValidationError(f"Appliance {serial} not found")

        coordinator = entry.runtime_data

        try:
            # Call the API to disable wake schedule
            await coordinator.client.disable_wake_schedule(serial=serial)
        except Exception as err:
            raise HomeAssistantError(f"Failed to disable wake schedule: {err}") from err

        return None

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_WAKE_SCHEDULE,
        set_wake_schedule,
        schema=SET_WAKE_SCHEDULE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DISABLE_WAKE_SCHEDULE,
        disable_wake_schedule,
        schema=DISABLE_WAKE_SCHEDULE_SCHEMA,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: SageCoffeeConfigEntry) -> bool:
    """Set up Sage Coffee from a config entry."""
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)

    if not refresh_token:
        raise ConfigEntryAuthFailed("No refresh token available")

    try:
        # Get Home Assistant's pre-configured httpx client and SSL context
        # These are created in the executor to avoid blocking the event loop
        http_client = httpx_client.get_async_client(hass)
        ssl_context = ssl_util.client_context()

        client = SageCoffeeClient(
            client_id=DEFAULT_CLIENT_ID,
            refresh_token=refresh_token,
            app=entry.data.get(CONF_MACHINE_TYPE),
            httpx_client=http_client,
            ssl_context=ssl_context,
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
    coordinator = SageCoffeeCoordinator(hass, client, appliances, entry)

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
