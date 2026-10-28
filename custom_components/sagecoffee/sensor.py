"""Sensor platform for Sage Coffee integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any
import zoneinfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SageCoffeeConfigEntry, SageCoffeeCoordinator
from .const import BOILER_BREW, BOILER_STEAM, MODEL_JET
from .entity import SageCoffeeEntity

_LOGGER = logging.getLogger(__name__)

# Sensors that don't apply to the Oracle Jet: it has no boiler array and its
# firmware does not expose a cfg block (Wi-Fi is for OTA updates only).
JET_EXCLUDED_SENSOR_KEYS = {
    "brew_temp",
    "brew_target",
    "steam_temp",
    "steam_target",
    "auto_off",
    "wake_schedule_next",
    "wake_schedule",
    "temperature_unit",
    "timezone",
}


@dataclass(frozen=True, kw_only=True)
class SageCoffeeSensorEntityDescription(SensorEntityDescription):
    """Describes a Sage Coffee sensor entity."""

    value_fn: Callable[[dict[str, Any]], Any]


def _parse_cron_next(
    cron: str, after: datetime, tz: zoneinfo.ZoneInfo
) -> datetime | None:
    """Return the next occurrence of a cron schedule after `after`.

    Expects the device cron format: "MM HH * * DAYS"
    where DAYS uses 1=Mon through 7=Sun.
    """
    parts = cron.split()
    if len(parts) != 5:
        return None
    try:
        minute = int(parts[0])
        hour = int(parts[1])
        days_str = parts[4]
    except ValueError:
        return None

    # Parse days-of-week into Python weekday set (0=Mon…6=Sun)
    allowed: set[int] = set()
    if days_str == "*":
        allowed = set(range(7))
    else:
        try:
            for part in days_str.split(","):
                if "-" in part:
                    start, end = part.split("-", 1)
                    for d in range(int(start), int(end) + 1):
                        allowed.add((d - 1) % 7)
                else:
                    allowed.add((int(part) - 1) % 7)
        except ValueError:
            return None

    # Walk forward up to 8 days to find the next matching slot
    candidate = after.replace(second=0, microsecond=0)
    for _ in range(8):
        if candidate.weekday() in allowed:
            scheduled = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if scheduled > after:
                return scheduled
        next_date = (candidate + timedelta(days=1)).date()
        candidate = datetime(next_date.year, next_date.month, next_date.day, 0, 0, 0, tzinfo=tz)

    return None


def _get_next_wake_time(state: dict[str, Any]) -> datetime | None:
    """Return the next scheduled wake time across all enabled schedule entries."""
    schedules = state.get("wake_schedule") or []
    tz_name = state.get("timezone") or "UTC"
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        tz = zoneinfo.ZoneInfo("UTC")

    now = datetime.now(tz)
    next_wake: datetime | None = None
    for entry in schedules:
        if not isinstance(entry, dict) or not entry.get("on"):
            continue
        cron = entry.get("cron", "")
        if not isinstance(cron, str):
            continue
        dt = _parse_cron_next(cron, now, tz)
        if dt is not None and (next_wake is None or dt < next_wake):
            next_wake = dt

    return next_wake


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


def _format_temperature_unit(state: dict[str, Any]) -> str | None:
    """Return the configured temperature unit."""
    unit = state.get("temperature_unit")
    if unit == 0:
        return "Celsius"
    if unit == 1:
        return "Fahrenheit"
    if unit is None:
        return None
    return str(unit)


def _format_remote_wake(state: dict[str, Any]) -> str | None:
    """Return whether remote wake is enabled."""
    remote_wake = state.get("remote_wake")
    if remote_wake is True:
        return "enabled"
    if remote_wake is False:
        return "disabled"
    return None


def _get_last_paired(state: dict[str, Any]) -> datetime | None:
    """Return the last paired timestamp from an epoch value."""
    last_paired = state.get("last_paired")
    if last_paired in (None, "", "none"):
        return None
    try:
        timestamp = float(last_paired)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _get_errors_count(state: dict[str, Any]) -> int | None:
    """Return the number of reported appliance errors."""
    errors = state.get("errors")
    if isinstance(errors, list):
        return len(errors)
    return None


def _format_wake_schedule(state: dict[str, Any]) -> str | None:
    """Return a compact wake schedule summary."""
    schedule = state.get("wake_schedule_raw")
    if schedule in (None, "", "none"):
        return "none"
    if isinstance(schedule, list):
        if not schedule:
            return "none"
        entries: list[str] = []
        for entry in schedule:
            if not isinstance(entry, dict):
                continue
            cron = entry.get("cron")
            if not cron:
                continue
            entries.append(f"{cron} ({'on' if entry.get('on') else 'off'})")
        return ", ".join(entries) if entries else None
    return str(schedule)


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
        key="grind_size",
        translation_key="grind_size",
        name="Grind Size",
        icon="mdi:grain",
        value_fn=lambda state: state.get("grind_size"),
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
    SageCoffeeSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        name="Firmware Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: (state.get("firmware") or {}).get("appVersion"),
    ),
    SageCoffeeSensorEntityDescription(
        key="firmware_mcu0",
        translation_key="firmware_mcu0",
        name="MCU Firmware Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: (state.get("firmware") or {}).get("mcu0"),
    ),
    SageCoffeeSensorEntityDescription(
        key="firmware_ota_service",
        translation_key="firmware_ota_service",
        name="OTA Service Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: (state.get("firmware") or {}).get("otaServiceVersion"),
    ),
    SageCoffeeSensorEntityDescription(
        key="firmware_sompro_image",
        translation_key="firmware_sompro_image",
        name="SOM Image Version",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: (state.get("firmware") or {}).get("sompro_image"),
    ),
    SageCoffeeSensorEntityDescription(
        key="wake_schedule_next",
        translation_key="wake_schedule_next",
        name="Next Wake Time",
        icon="mdi:alarm",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_get_next_wake_time,
    ),
    SageCoffeeSensorEntityDescription(
        key="wake_schedule",
        translation_key="wake_schedule",
        name="Wake Schedule",
        icon="mdi:alarm",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_format_wake_schedule,
    ),
    SageCoffeeSensorEntityDescription(
        key="temperature_unit",
        translation_key="temperature_unit",
        name="Temperature Unit",
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_format_temperature_unit,
    ),
    SageCoffeeSensorEntityDescription(
        key="timezone",
        translation_key="timezone",
        name="Timezone",
        icon="mdi:map-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.get("timezone"),
    ),
    SageCoffeeSensorEntityDescription(
        key="remote_wake",
        translation_key="remote_wake",
        name="Remote Wake",
        icon="mdi:power-settings",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_format_remote_wake,
    ),
    SageCoffeeSensorEntityDescription(
        key="last_paired",
        translation_key="last_paired",
        name="Last Paired",
        icon="mdi:link-variant",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_get_last_paired,
    ),
    SageCoffeeSensorEntityDescription(
        key="state_report_version",
        translation_key="state_report_version",
        name="State Report Version",
        icon="mdi:counter",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda state: state.get("state_report_version"),
    ),
    SageCoffeeSensorEntityDescription(
        key="errors_count",
        translation_key="errors_count",
        name="Errors Count",
        icon="mdi:alert-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_get_errors_count,
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
            if (
                appliance.model == MODEL_JET
                and description.key in JET_EXCLUDED_SENSOR_KEYS
            ):
                continue
            entities.append(SageCoffeeSensor(coordinator, appliance, description))

    async_add_entities(entities)


class SageCoffeeSensor(SageCoffeeEntity, SensorEntity):
    """Represents a sensor for a Sage Coffee machine."""

    entity_description: SageCoffeeSensorEntityDescription

    def __init__(
        self,
        coordinator: SageCoffeeCoordinator,
        appliance: Any,
        description: SageCoffeeSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, appliance)
        self.entity_description = description
        self._attr_unique_id = f"{self._serial}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        state = self.coordinator.get_state(self._serial)
        if state is None:
            return None
        return self.entity_description.value_fn(state)
