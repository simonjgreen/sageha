"""Low-water fault sensor for the Sage Coffee integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SageCoffeeConfigEntry, SageCoffeeCoordinator
from .entity import SageCoffeeEntity

LOW_WATER_ERROR_CODES = frozenset({31102, 29120})


def _low_water_state(state: dict[str, Any] | None) -> bool | None:
    """Decode low-water and empty-tank faults, preserving missing data."""
    if not isinstance(state, dict):
        return None
    errors = state.get("errors")
    if not isinstance(errors, list):
        return None

    malformed = False
    for error in errors:
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str) and code.isascii() and code.isdecimal():
            code = int(code)
        if type(code) is not int:
            malformed = True
            continue
        if code in LOW_WATER_ERROR_CODES:
            return True
    return None if malformed else False


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SageCoffeeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one low-water sensor for each appliance."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            SageCoffeeLowWaterSensor(coordinator, appliance)
            for appliance in coordinator.appliances
        ]
    )


class SageCoffeeLowWaterSensor(SageCoffeeEntity, BinarySensorEntity):
    """Report the machine's water fault without estimating its water level."""

    _attr_translation_key = "low_water"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:water-alert"

    def __init__(
        self, coordinator: SageCoffeeCoordinator, appliance: Any
    ) -> None:
        """Initialize the low-water sensor."""
        super().__init__(coordinator, appliance)
        self._attr_unique_id = f"{self._serial}_low_water"

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        return _low_water_state(self.coordinator.get_state(self._serial))