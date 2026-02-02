"""Text platform for Sage Coffee integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SageCoffeeConfigEntry, SageCoffeeCoordinator
from .const import DOMAIN, STATE_ASLEEP

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SageCoffeeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sage Coffee text entities."""
    coordinator = entry.runtime_data

    entities = [
        SageCoffeeApplianceNameText(coordinator, appliance)
        for appliance in coordinator.appliances
    ]

    async_add_entities(entities)


class SageCoffeeApplianceNameText(CoordinatorEntity[SageCoffeeCoordinator], TextEntity):
    """Represents the appliance name text input."""

    _attr_has_entity_name = True
    _attr_translation_key = "appliance_name"
    _attr_native_max = 20

    def __init__(
        self,
        coordinator: SageCoffeeCoordinator,
        appliance: Any,
    ) -> None:
        """Initialize the text entity."""
        super().__init__(coordinator)
        self._appliance = appliance
        self._serial = appliance.serial_number
        self._attr_unique_id = f"{self._serial}_appliance_name"

        # Device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=appliance.name or f"Sage Coffee {self._serial[-4:]}",
            manufacturer="Sage/Breville",
            model=appliance.model or "Unknown",
            serial_number=self._serial,
        )

    @property
    def native_value(self) -> str | None:
        """Return the current appliance name."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return None
        return self._appliance.name or ""

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        # Appliance name can be set regardless of machine state
        return True

    async def async_set_value(self, value: str) -> None:
        """Set the appliance name."""
        try:
            # Client expects (name, serial)
            await self.coordinator.client.set_appliance_name(value, self._serial)
            # Update local appliance object
            self._appliance.name = value
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Failed to set appliance name: %s", err)
            raise
