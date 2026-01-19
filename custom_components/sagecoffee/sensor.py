"""Sensor platform for Sage Coffee integration."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SageCoffeeConfigEntry, SageCoffeeCoordinator
from .const import BOILER_BREW, BOILER_STEAM, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class SageCoffeeSensorEntityDescription(SensorEntityDescription):
    """Describes a Sage Coffee sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any]


def _get_boiler_temp(state: dict[str, Any], boiler_id: int | str) -> float | None:
    """Get current temperature for a boiler."""
    boilers = state.get("boiler_temps", [])
    for boiler in boilers:
        # Compare as strings since library returns string IDs
        if str(boiler.get("id")) == str(boiler_id):
            return boiler.get("cur_temp")
    return None


def _get_boiler_target(state: dict[str, Any], boiler_id: int | str) -> float | None:
    """Get target temperature for a boiler."""
    boilers = state.get("boiler_temps", [])
    for boiler in boilers:
        # Compare as strings since library returns string IDs
        if str(boiler.get("id")) == str(boiler_id):
            return boiler.get("temp_sp")
    return None


SENSOR_DESCRIPTIONS: tuple[SageCoffeeSensorEntityDescription, ...] = (
    SageCoffeeSensorEntityDescription(
        key="state",
        translation_key="machine_state",
        name="State",
        icon="mdi:coffee-maker",
        value_fn=lambda state: state.get("reported_state"),
    ),
    SageCoffeeSensorEntityDescription(
        key="brew_temp",
        translation_key="brew_temperature",
        name="Brew Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda state: _get_boiler_temp(state, BOILER_BREW),
    ),
    SageCoffeeSensorEntityDescription(
        key="brew_target",
        translation_key="brew_target",
        name="Brew Target Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda state: _get_boiler_target(state, BOILER_BREW),
    ),
    SageCoffeeSensorEntityDescription(
        key="steam_temp",
        translation_key="steam_temperature",
        name="Steam Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda state: _get_boiler_temp(state, BOILER_STEAM),
    ),
    SageCoffeeSensorEntityDescription(
        key="steam_target",
        translation_key="steam_target",
        name="Steam Target Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda state: _get_boiler_target(state, BOILER_STEAM),
    ),
    SageCoffeeSensorEntityDescription(
        key="theme",
        translation_key="theme",
        name="Theme",
        icon="mdi:palette",
        value_fn=lambda state: state.get("theme"),
    ),
    SageCoffeeSensorEntityDescription(
        key="brightness",
        translation_key="brightness",
        name="Display Brightness",
        icon="mdi:brightness-6",
        native_unit_of_measurement="%",
        value_fn=lambda state: state.get("brightness"),
    ),
    SageCoffeeSensorEntityDescription(
        key="work_light",
        translation_key="work_light",
        name="Work Light Brightness",
        icon="mdi:desk-lamp",
        native_unit_of_measurement="%",
        value_fn=lambda state: state.get("work_light_brightness"),
    ),
    SageCoffeeSensorEntityDescription(
        key="grind_size",
        translation_key="grind_size",
        name="Grind Size",
        icon="mdi:grain",
        value_fn=lambda state: state.get("grind_size"),
    ),
    SageCoffeeSensorEntityDescription(
        key="volume",
        translation_key="volume",
        name="Volume",
        icon="mdi:volume-high",
        native_unit_of_measurement="%",
        value_fn=lambda state: state.get("volume"),
    ),
    SageCoffeeSensorEntityDescription(
        key="auto_off",
        translation_key="auto_off",
        name="Auto-off Time",
        icon="mdi:timer-off",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda state: state.get("idle_time"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SageCoffeeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Sage Coffee sensors."""
    coordinator = entry.runtime_data

    entities: list[SageCoffeeSensor] = []

    for appliance in coordinator.appliances:
        for description in SENSOR_DESCRIPTIONS:
            entities.append(
                SageCoffeeSensor(coordinator, appliance, description)
            )

    async_add_entities(entities)


class SageCoffeeSensor(CoordinatorEntity[SageCoffeeCoordinator], SensorEntity):
    """Represents a sensor for a Sage Coffee machine."""

    entity_description: SageCoffeeSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SageCoffeeCoordinator,
        appliance: Any,
        description: SageCoffeeSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
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
    def native_value(self) -> Any:
        """Return the sensor value."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return None
        return self.entity_description.value_fn(state)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
