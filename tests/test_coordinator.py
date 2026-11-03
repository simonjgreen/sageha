"""Tests for the coordinator's device state parsing and auth error detection.

Malformed device payloads have crashed the WebSocket listener before (#36),
so `_update_state_from_device` is exercised against the messy shapes the
device is known to send.
"""

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from sagecoffee.models import DeviceState

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sagecoffee import SageCoffeeCoordinator, _is_auth_error
from custom_components.sagecoffee.const import DOMAIN

from .conftest import MOCK_SERIAL


def make_coordinator(hass: HomeAssistant) -> SageCoffeeCoordinator:
    """Build a coordinator with a mocked client and no appliances."""
    entry = MockConfigEntry(domain=DOMAIN, version=2)
    entry.add_to_hass(hass)
    return SageCoffeeCoordinator(hass, MagicMock(), [], entry)


def make_device_state(reported: dict[str, Any]) -> DeviceState:
    """Build a DeviceState with the given reported payload."""
    return DeviceState(
        raw_data={
            "reported": {"state": "ready", "grind.size_setting": 15, **reported},
            "desired": {"state": "ready"},
        },
        serial_number=MOCK_SERIAL,
        version=7,
    )


WELL_FORMED_REPORTED = {
    "version": "1.2.3",
    "model": "BES995",
    "cfg": {
        "default": {
            "theme": "dark",
            "brightness": 80,
            "work_light_brightness": 50,
            "vol": 60,
            "idle_time": 20,
            "temp_unit": 0,
            "timezone": "Europe/London",
            "wake_schedule": [{"cron": "30 6 * * *", "on": True}],
        }
    },
    "pairing": {"remote_wake": True, "last_paired": 1755100800},
    "firmware": {"appVersion": "2.0.1"},
    "errors": [],
    "signal_strength": -55,
}


async def test_well_formed_payload_maps_all_keys(hass: HomeAssistant) -> None:
    """A well-formed payload is mapped to the state dict every entity reads."""
    coordinator = make_coordinator(hass)
    boiler = {"cur_temp": 93.0, "temp_sp": 93.5}
    state = make_device_state({**WELL_FORMED_REPORTED, "boiler": [boiler]})

    coordinator._update_state_from_device(state)

    parsed = coordinator.get_state(MOCK_SERIAL)
    assert parsed == {
        "reported_state": "ready",
        "desired_state": "ready",
        "state_report_version": 7,
        "reported_version": "1.2.3",
        "model": "BES995",
        "boiler_temps": [
            {"id": "0", "role": "brew", "cur_temp": 93.0, "temp_sp": 93.5}
        ],
        "single_boiler": True,
        "grind_size": 15,
        "theme": "dark",
        "brightness": 80,
        "work_light_brightness": 50,
        "volume": 60,
        "idle_time": 20,
        "temperature_unit": 0,
        "timezone": "Europe/London",
        "remote_wake": True,
        "last_paired": 1755100800,
        "wake_schedule_raw": [{"cron": "30 6 * * *", "on": True}],
        "wake_schedule": [{"cron": "30 6 * * *", "on": True}],
        "firmware": {"appVersion": "2.0.1"},
        "errors": [],
        "signal_strength": -55,
    }


async def test_flattened_cfg_default_key_fallback(hass: HomeAssistant) -> None:
    """Some devices report a flattened "cfg.default" key instead of nested cfg."""
    coordinator = make_coordinator(hass)
    state = make_device_state({"cfg.default": {"theme": "light", "vol": 40}})

    coordinator._update_state_from_device(state)

    parsed = coordinator.get_state(MOCK_SERIAL)
    assert parsed["theme"] == "light"
    assert parsed["volume"] == 40


@pytest.mark.parametrize(
    "wake_schedule",
    ["30 6 * * *", 42, {"cron": "30 6 * * *"}],
    ids=["string", "int", "dict"],
)
async def test_non_list_wake_schedule_does_not_crash(
    hass: HomeAssistant, wake_schedule: Any
) -> None:
    """A non-list wake_schedule is preserved raw but parsed as empty (#36)."""
    coordinator = make_coordinator(hass)
    state = make_device_state(
        {"cfg": {"default": {"wake_schedule": wake_schedule}}}
    )

    coordinator._update_state_from_device(state)

    parsed = coordinator.get_state(MOCK_SERIAL)
    assert parsed["wake_schedule_raw"] == wake_schedule
    assert parsed["wake_schedule"] == []


async def test_wake_schedule_filters_non_dict_entries(hass: HomeAssistant) -> None:
    """Non-dict entries inside the wake_schedule list are dropped (#36)."""
    coordinator = make_coordinator(hass)
    entry = {"cron": "30 6 * * *", "on": True}
    state = make_device_state(
        {"cfg": {"default": {"wake_schedule": ["bogus", entry, None]}}}
    )

    coordinator._update_state_from_device(state)

    assert coordinator.get_state(MOCK_SERIAL)["wake_schedule"] == [entry]


@pytest.mark.parametrize(
    "reported",
    [
        {"cfg": {"default": "not-a-dict"}, "pairing": "not-a-dict"},
        {},
    ],
    ids=["non_dict_sections", "empty"],
)
async def test_malformed_sections_do_not_crash(
    hass: HomeAssistant, reported: dict[str, Any]
) -> None:
    """Non-dict cfg/pairing sections are treated as absent rather than crashing."""
    coordinator = make_coordinator(hass)
    state = make_device_state(reported)

    coordinator._update_state_from_device(state)

    parsed = coordinator.get_state(MOCK_SERIAL)
    assert parsed["theme"] is None
    assert parsed["remote_wake"] is None
    assert parsed["wake_schedule"] == []


async def test_remote_wake_falls_back_to_cfg_default(hass: HomeAssistant) -> None:
    """Without pairing.remote_wake, cfg.default.remote_wake_enable is used."""
    coordinator = make_coordinator(hass)
    state = make_device_state(
        {"cfg": {"default": {"remote_wake_enable": True}}, "pairing": {}}
    )

    coordinator._update_state_from_device(state)

    assert coordinator.get_state(MOCK_SERIAL)["remote_wake"] is True


async def test_none_boiler_temps_does_not_crash(hass: HomeAssistant) -> None:
    """A null boiler list yields an empty list."""
    coordinator = make_coordinator(hass)
    state = make_device_state({"boiler": None})

    coordinator._update_state_from_device(state)

    assert coordinator.get_state(MOCK_SERIAL)["boiler_temps"] == []


@pytest.mark.parametrize(
    ("err", "expected"),
    [
        (
            httpx.HTTPStatusError(
                "unauthorised",
                request=MagicMock(),
                response=MagicMock(status_code=401),
            ),
            True,
        ),
        (
            httpx.HTTPStatusError(
                "forbidden",
                request=MagicMock(),
                response=MagicMock(status_code=403),
            ),
            True,
        ),
        (
            httpx.HTTPStatusError(
                "server error",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            ),
            False,
        ),
        (ValueError("Invalid refresh TOKEN"), True),
        (ValueError("something else"), False),
        (RuntimeError("token gone"), False),
    ],
    ids=["401", "403", "500", "token_value_error", "other_value_error", "other"],
)
def test_is_auth_error(err: Exception, expected: bool) -> None:
    """Auth errors trigger reauth; anything else must not."""
    assert _is_auth_error(err) is expected


async def test_dual_boiler_roles(hass: HomeAssistant) -> None:
    """Dual boiler machines report steam at index 0 and brew at index 1."""
    coordinator = make_coordinator(hass)
    state = make_device_state(
        {"boiler": [{"cur_temp": 135.0, "temp_sp": 135.5}, {"cur_temp": 93.0}]}
    )

    coordinator._update_state_from_device(state)

    parsed = coordinator.get_state(MOCK_SERIAL)
    assert [b["role"] for b in parsed["boiler_temps"]] == ["steam", "brew"]
    assert parsed["single_boiler"] is False
