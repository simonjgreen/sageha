"""Tests for reported low-water and empty-tank faults."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sagecoffee.binary_sensor import (
    SageCoffeeLowWaterSensor,
    _low_water_state,
    async_setup_entry,
)
from custom_components.sagecoffee.const import DOMAIN, PLATFORMS

from .conftest import MOCK_SERIAL


@pytest.mark.parametrize("code", [31102, 29120, "31102", "29120"])
def test_both_water_fault_codes(code: int | str) -> None:
    assert _low_water_state({"errors": [{"code": code}]}) is True


@pytest.mark.parametrize("errors", [[], [{"code": 99999}], [{"code": "99999"}]])
def test_report_without_water_fault_is_clear(errors: list[dict[str, Any]]) -> None:
    assert _low_water_state({"errors": errors}) is False


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"errors": None},
        {"errors": {}},
        {"errors": "[]"},
        {"errors": [None]},
        {"errors": [31102]},
        {"errors": [{}]},
        {"errors": [{"code": None}]},
        {"errors": [{"code": True}]},
        {"errors": [{"code": 31102.5}]},
        {"errors": [{"code": "unknown"}]},
        {"errors": [{"code": 99999}, {}]},
    ],
)
def test_missing_or_malformed_data_is_unknown(state: dict[str, Any] | None) -> None:
    assert _low_water_state(state) is None


@pytest.mark.parametrize(
    "errors", [[None, {"code": 31102}], [{"code": 29120}, None]]
)
def test_conclusive_fault_survives_malformed_entries(errors: list[Any]) -> None:
    assert _low_water_state({"errors": errors}) is True


def test_platform_preserves_existing_platforms() -> None:
    assert "binary_sensor" in PLATFORMS
    assert {"switch", "sensor", "text", "select", "number", "light"} <= set(PLATFORMS)


def test_entity_metadata_and_coordinator_availability(
    mock_appliance: SimpleNamespace,
) -> None:
    coordinator = MagicMock(last_update_success=True)
    coordinator.get_state.return_value = {"errors": []}
    sensor = SageCoffeeLowWaterSensor(coordinator, mock_appliance)

    assert sensor.unique_id == f"{MOCK_SERIAL}_low_water"
    assert sensor.translation_key == "low_water"
    assert sensor.device_class is BinarySensorDeviceClass.PROBLEM
    assert sensor.available is True
    assert sensor.is_on is False
    coordinator.get_state.assert_called_with(MOCK_SERIAL)

    coordinator.last_update_success = False
    assert sensor.available is False


async def test_setup_adds_one_sensor_per_appliance(hass: HomeAssistant) -> None:
    appliances = [
        SimpleNamespace(serial_number=serial, name="Kitchen", model="BES995")
        for serial in ("TEST-ONE", "TEST-TWO")
    ]
    coordinator = MagicMock(appliances=appliances)
    add_entities = MagicMock()

    await async_setup_entry(
        hass, SimpleNamespace(runtime_data=coordinator), add_entities
    )

    sensors = add_entities.call_args.args[0]
    assert [sensor.unique_id for sensor in sensors] == [
        "TEST-ONE_low_water",
        "TEST-TWO_low_water",
    ]
    assert all(sensor.coordinator is coordinator for sensor in sensors)


async def test_entity_registration_and_pushed_state_changes(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
) -> None:
    device_state = SimpleNamespace(
        serial_number=MOCK_SERIAL,
        raw_data={"reported": {"errors": []}},
        reported_state="ready",
        desired_state=None,
        version=1,
        boiler_temps=[],
        grind_size=None,
    )
    mock_client.get_last_state.return_value = device_state

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{MOCK_SERIAL}_low_water"
    )
    assert entity_id is not None
    entity = registry.async_get(entity_id)
    assert entity is not None
    assert entity.device_id is not None
    device = dr.async_get(hass).async_get(entity.device_id)
    assert device is not None
    assert (DOMAIN, MOCK_SERIAL) in device.identifiers
    assert entity.config_entry_id == config_entry.entry_id
    assert hass.states.get(entity_id).state == STATE_OFF
    assert hass.states.get(entity_id).attributes["friendly_name"].endswith("Low Water")

    coordinator = config_entry.runtime_data
    for errors, expected in (
        ([{"code": 29120}], STATE_ON),
        ([], STATE_OFF),
        (None, STATE_UNAVAILABLE),
        ([{"code": "31102"}], STATE_ON),
        ([{}], STATE_UNAVAILABLE),
        ([], STATE_OFF),
    ):
        device_state.raw_data["reported"]["errors"] = errors
        coordinator._update_state_from_device(device_state)
        coordinator.async_set_updated_data(coordinator._states)
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == expected

    coordinator.async_set_update_error(UpdateFailed("Disconnected"))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE