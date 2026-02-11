"""Number platform for Sage Coffee integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SageCoffeeConfigEntry, SageCoffeeCoordinator
from .const import DOMAIN, STATE_ASLEEP

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SageCoffeeNumberEntityDescription(NumberEntityDescription):
    """Describes a Sage Coffee number entity."""

    value_fn: Callable[[dict[str, Any]], float | None]
    set_fn: Callable[[SageCoffeeCoordinator, str, float], Any]


NUMBER_DESCRIPTIONS: tuple[SageCoffeeNumberEntityDescription, ...] = (
    SageCoffeeNumberEntityDescription(
        key="brightness",
        translation_key="display_brightness",
        native_min_value=1,
        native_max_value=100,
        native_step=10,
        value_fn=lambda state: state.get("brightness"),
        set_fn=lambda coordinator, serial, value: coordinator.client.set_brightness(
            int(value), serial
        ),
    ),
    SageCoffeeNumberEntityDescription(
        key="work_light_brightness",
        translation_key="work_light_brightness",
        native_min_value=1,
        native_max_value=100,
        native_step=10,
        value_fn=lambda state: state.get("work_light_brightness"),
        set_fn=lambda coordinator, serial, value: coordinator.client.set_work_light_brightness(
            int(value), serial
        ),
    ),
    SageCoffeeNumberEntityDescription(
        key="volume",
        translation_key="volume_level",
        native_min_value=1,
        native_max_value=100,
        native_step=10,
        value_fn=lambda state: state.get("volume"),
        set_fn=lambda coordinator, serial, value: coordinator.client.set_volume(
            int(value), serial
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SageCoffeeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sage Coffee number entities."""
    coordinator = entry.runtime_data

    entities = [
        SageCoffeeNumber(coordinator, appliance, description)
        for appliance in coordinator.appliances
        for description in NUMBER_DESCRIPTIONS
    ]

    async_add_entities(entities)


class SageCoffeeNumber(CoordinatorEntity[SageCoffeeCoordinator], NumberEntity):
    """Represents a Sage Coffee number entity."""

    entity_description: SageCoffeeNumberEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SageCoffeeCoordinator,
        appliance: Any,
        description: SageCoffeeNumberEntityDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._appliance = appliance
        self._serial = appliance.serial_number
        self._attr_unique_id = f"{self._serial}_{description.key}"

        # Device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=appliance.name or f"Sage Coffee {self._serial[-4:]}",
            manufacturer="Sage/Breville",
            model=appliance.model or "Unknown",
            serial_number=self._serial,
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return None
        return self.entity_description.value_fn(state)

    @property
    def available(self) -> bool:
        """Return if the entity is available."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return False
        reported_state = state.get("reported_state", "").lower()
        return reported_state != STATE_ASLEEP

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        try:
            await self.entity_description.set_fn(self.coordinator, self._serial, value)
            # Update the state through coordinator
            state = self.coordinator.get_state(self._serial)
            if state:
                state[self.entity_description.key] = value
                self.coordinator.async_set_updated_data(self.coordinator.data)
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error(
                "Failed to set %s: %s", self.entity_description.key, err
            )
            raise
