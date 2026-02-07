"""Select platform for Sage Coffee integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SageCoffeeConfigEntry, SageCoffeeCoordinator
from .const import DOMAIN, STATE_ASLEEP

_LOGGER = logging.getLogger(__name__)

# Available themes based on Sage Coffee API
AVAILABLE_THEMES = ["dark", "light"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SageCoffeeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sage Coffee select entities."""
    coordinator = entry.runtime_data

    entities = [
        SageCoffeeThemeSelect(coordinator, appliance)
        for appliance in coordinator.appliances
    ]

    async_add_entities(entities)


class SageCoffeeThemeSelect(CoordinatorEntity[SageCoffeeCoordinator], SelectEntity):
    """Represents the color theme select."""

    _attr_has_entity_name = True
    _attr_translation_key = "color_theme"
    _attr_options = AVAILABLE_THEMES

    def __init__(
        self,
        coordinator: SageCoffeeCoordinator,
        appliance: Any,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._appliance = appliance
        self._serial = appliance.serial_number
        self._attr_unique_id = f"{self._serial}_color_theme"

        # Device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=appliance.name or f"Sage Coffee {self._serial[-4:]}",
            manufacturer="Sage/Breville",
            model=appliance.model or "Unknown",
            serial_number=self._serial,
        )

    @property
    def current_option(self) -> str | None:
        """Return the current theme."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return None
        theme = state.get("theme")
        if theme and theme in self._attr_options:
            return theme
        return None

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return False
        reported_state = state.get("reported_state", "").lower()
        return reported_state != STATE_ASLEEP

    async def async_select_option(self, option: str) -> None:
        """Set the color theme."""
        if option not in self._attr_options:
            raise ValueError(f"Invalid theme: {option}")

        try:
            await self.coordinator.client.set_color_theme(option, self._serial)
            # Update the state through coordinator
            state = self.coordinator.get_state(self._serial)
            if state:
                state["theme"] = option
                self.coordinator.async_set_updated_data(self.coordinator.data)
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Failed to set color theme: %s", err)
            raise
