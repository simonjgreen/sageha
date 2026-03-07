"""Light platform for Sage Coffee integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.color import brightness_to_value, value_to_brightness

from . import SageCoffeeConfigEntry, SageCoffeeCoordinator
from .const import DOMAIN, STATE_ASLEEP

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SageCoffeeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sage Coffee light entities."""
    coordinator = entry.runtime_data

    async_add_entities(
        SageCoffeeWorkLight(coordinator, appliance)
        for appliance in coordinator.appliances
    )


class SageCoffeeWorkLight(CoordinatorEntity[SageCoffeeCoordinator], LightEntity):
    """Represents the work light (cup warmer illumination) on a Sage Coffee machine."""

    _attr_has_entity_name = True
    _attr_translation_key = "work_light"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(
        self,
        coordinator: SageCoffeeCoordinator,
        appliance: Any,
    ) -> None:
        """Initialize the work light."""
        super().__init__(coordinator)
        self._appliance = appliance
        self._serial = appliance.serial_number
        self._attr_unique_id = f"{self._serial}_work_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=appliance.name or f"Sage Coffee {self._serial[-4:]}",
            manufacturer="Sage/Breville",
            model=appliance.model or "Unknown",
            serial_number=self._serial,
        )

    def _api_brightness(self) -> int | None:
        """Return the current work light brightness from the API (0–100), or None."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return None
        return state.get("work_light_brightness")

    @property
    def is_on(self) -> bool | None:
        """Return True if the work light is on."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return None
        if state.get("reported_state", "").lower() == STATE_ASLEEP:
            return False
        value = state.get("work_light_brightness")
        if value is None:
            return None
        return value > 0

    @property
    def brightness(self) -> int | None:
        """Return the current brightness on the HA 1–255 scale."""
        value = self._api_brightness()
        if not value:
            return None
        return value_to_brightness((1, 100), value)

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode."""
        return ColorMode.BRIGHTNESS

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the work light."""
        ha_brightness = kwargs.get(ATTR_BRIGHTNESS, 255)
        # Convert HA scale (1–255) to API range (1–100), rounded to nearest 10
        raw = brightness_to_value((1, 100), ha_brightness)
        value = round(raw / 10) * 10
        # Ensure turning on always results in a visible brightness
        value = max(10, min(100, value))
        await self.coordinator.client.set_work_light_brightness(
            value, serial=self._serial
        )
        state = self.coordinator.get_state(self._serial)
        if state is not None:
            state["work_light_brightness"] = value
            self.coordinator.async_set_updated_data(self.coordinator.data)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the work light."""
        await self.coordinator.client.set_work_light_brightness(
            0, serial=self._serial
        )
        state = self.coordinator.get_state(self._serial)
        if state is not None:
            state["work_light_brightness"] = 0
            self.coordinator.async_set_updated_data(self.coordinator.data)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
