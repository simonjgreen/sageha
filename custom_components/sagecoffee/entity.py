"""Base entity class for Sage Coffee integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SageCoffeeCoordinator
from .const import DOMAIN


class SageCoffeeEntity(CoordinatorEntity[SageCoffeeCoordinator]):
    """Base entity class for Sage Coffee devices."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SageCoffeeCoordinator,
        appliance: Any,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._appliance = appliance
        self._serial = appliance.serial_number
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=appliance.name or f"Sage Coffee {self._serial[-4:]}",
            manufacturer="Sage/Breville",
            model=appliance.model or "Unknown",
            serial_number=self._serial,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
