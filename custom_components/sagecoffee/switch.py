"""Switch platform for Sage Coffee integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SageCoffeeConfigEntry, SageCoffeeCoordinator
from .const import STATE_READY, STATE_WARMING
from .entity import SageCoffeeEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SageCoffeeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sage Coffee switches."""
    coordinator = entry.runtime_data

    entities = [
        SageCoffeePowerSwitch(coordinator, appliance)
        for appliance in coordinator.appliances
    ]

    async_add_entities(entities)


class SageCoffeePowerSwitch(SageCoffeeEntity, SwitchEntity):
    """Represents the power state of a Sage Coffee machine."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_translation_key = "power"

    def __init__(
        self,
        coordinator: SageCoffeeCoordinator,
        appliance: Any,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, appliance)
        self._attr_unique_id = f"{self._serial}_power"

    @property
    def is_on(self) -> bool | None:
        """Return True if the machine is on (ready or warming)."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return None
        reported_state = state.get("reported_state", "").lower()
        return reported_state in (STATE_READY, STATE_WARMING)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return {}
        return {
            "reported_state": state.get("reported_state"),
            "desired_state": state.get("desired_state"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the coffee machine (wake)."""
        _LOGGER.debug("Waking up coffee machine %s", self._serial)
        try:
            await self.coordinator.client.wake()
        except Exception as err:
            _LOGGER.error("Failed to wake coffee machine: %s", err)
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the coffee machine (sleep)."""
        _LOGGER.debug("Putting coffee machine %s to sleep", self._serial)
        try:
            await self.coordinator.client.sleep()
        except Exception as err:
            _LOGGER.error("Failed to put coffee machine to sleep: %s", err)
            raise

