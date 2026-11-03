"""Tests for integration setup, config entry migration, and services."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sagecoffee import async_migrate_entry
from custom_components.sagecoffee.const import (
    CONF_BRAND,
    CONF_MACHINE_TYPE_LEGACY,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    MACHINE_TYPE_BREVILLE,
    MACHINE_TYPE_SAGE,
)

from .conftest import MOCK_SERIAL


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
    """Set up the given entry and settle the event loop."""
    result = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return result


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """A successful setup loads the entry, creates entities, and unloads cleanly."""
    assert await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    # Each platform registered entities with the serial-prefixed unique ID scheme.
    registry = er.async_get(hass)
    unique_ids = {
        e.unique_id
        for e in er.async_entries_for_config_entry(registry, config_entry.entry_id)
    }
    assert f"{MOCK_SERIAL}_power" in unique_ids
    assert f"{MOCK_SERIAL}_state" in unique_ids
    assert f"{MOCK_SERIAL}_work_light" in unique_ids
    assert len(unique_ids) == len(
        er.async_entries_for_config_entry(registry, config_entry.entry_id)
    ), "duplicate unique IDs registered"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    mock_client.__aexit__.assert_awaited()


def make_device_state(boiler_count: int) -> SimpleNamespace:
    """A device state as returned by the sagecoffee client."""
    return SimpleNamespace(
        serial_number=MOCK_SERIAL,
        raw_data={"reported": {"state": "ready"}},
        reported_state="ready",
        desired_state="ready",
        version=1,
        boiler_temps=[
            SimpleNamespace(id=str(i), current_temp=90.0, target_temp=93.0)
            for i in range(boiler_count)
        ],
        grind_size=None,
    )


@pytest.mark.parametrize(
    ("boiler_count", "has_steam_sensors"), [(1, False), (2, True)]
)
async def test_steam_sensors_only_for_dual_boiler_machines(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    boiler_count: int,
    has_steam_sensors: bool,
) -> None:
    """Single-boiler machines have no steam boiler, so get no steam sensors."""
    mock_client.get_last_state.return_value = make_device_state(boiler_count)
    assert await setup_entry(hass, config_entry)

    registry = er.async_get(hass)
    unique_ids = {
        e.unique_id
        for e in er.async_entries_for_config_entry(registry, config_entry.entry_id)
    }
    assert f"{MOCK_SERIAL}_brew_temp" in unique_ids
    assert (f"{MOCK_SERIAL}_steam_temp" in unique_ids) is has_steam_sensors
    assert (f"{MOCK_SERIAL}_steam_target" in unique_ids) is has_steam_sensors


async def test_setup_without_refresh_token_starts_reauth(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    """A stored entry with no refresh token fails auth rather than retrying."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, data={CONF_BRAND: MACHINE_TYPE_SAGE}
    )
    entry.add_to_hass(hass)

    assert not await setup_entry(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(
        flow["context"]["source"] == "reauth"
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_connection_failure_retries(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """A generic API failure is a retry (ConfigEntryNotReady), and closes the client."""
    mock_client.list_appliances.side_effect = Exception("connection refused")

    assert not await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_client.__aexit__.assert_awaited_once()


async def test_auth_failure_is_not_relabelled_as_retry(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """ConfigEntryAuthFailed from the client passes through untouched (#56)."""
    mock_client.list_appliances.side_effect = ConfigEntryAuthFailed("token revoked")

    assert not await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    mock_client.__aexit__.assert_awaited_once()


async def test_no_appliances_is_not_a_connection_failure(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """An empty appliance list retries with the brand-mismatch reason (#56)."""
    mock_client.list_appliances.side_effect = None
    mock_client.list_appliances.return_value = []

    assert not await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert "No appliances found" in str(config_entry.reason)
    mock_client.__aexit__.assert_awaited_once()


async def test_migrate_v1_machine_type_to_brand(hass: HomeAssistant) -> None:
    """Version 1 entries storing machine_type are migrated to brand (#54)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={
            CONF_REFRESH_TOKEN: "token",
            CONF_MACHINE_TYPE_LEGACY: MACHINE_TYPE_BREVILLE,
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.data == {
        CONF_REFRESH_TOKEN: "token",
        CONF_BRAND: MACHINE_TYPE_BREVILLE,
    }


async def test_migrate_v1_without_brand_defaults_to_sage(hass: HomeAssistant) -> None:
    """Version 1 entries with neither key default to Sage rather than None (#54)."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, data={CONF_REFRESH_TOKEN: "token"}
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.data[CONF_BRAND] == MACHINE_TYPE_SAGE


async def test_migrate_from_newer_version_fails(hass: HomeAssistant) -> None:
    """Entries from a newer integration version cannot be migrated down."""
    entry = MockConfigEntry(domain=DOMAIN, version=3, data={})
    entry.add_to_hass(hass)

    assert not await async_migrate_entry(hass, entry)
    assert entry.version == 3


async def test_migrate_current_version_is_untouched(hass: HomeAssistant) -> None:
    """Current-version entries pass through migration unchanged."""
    data = {CONF_REFRESH_TOKEN: "token", CONF_BRAND: MACHINE_TYPE_SAGE}
    entry = MockConfigEntry(domain=DOMAIN, version=2, data=data)
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.data == data


async def test_set_wake_schedule_builds_cron(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Day names are converted to the device's 1=Mon…7=Sun cron numbering."""
    assert await setup_entry(hass, config_entry)

    await hass.services.async_call(
        DOMAIN,
        "set_wake_schedule",
        {
            "serial": MOCK_SERIAL,
            "hours": 6,
            "minutes": 30,
            "days": ["mon", "sat", "sun"],
        },
        blocking=True,
    )

    mock_client.set_coffee_params.assert_awaited_once_with(
        {"cfg": {"wake_schedule": [{"cron": "30 6 * * 1,6,7", "on": True}]}},
        serial=MOCK_SERIAL,
    )


async def test_set_wake_schedule_without_days_means_every_day(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Omitting days produces a wildcard day field."""
    assert await setup_entry(hass, config_entry)

    await hass.services.async_call(
        DOMAIN,
        "set_wake_schedule",
        {"serial": MOCK_SERIAL, "hours": 7, "minutes": 0, "enabled": False},
        blocking=True,
    )

    mock_client.set_coffee_params.assert_awaited_once_with(
        {"cfg": {"wake_schedule": [{"cron": "0 7 * * *", "on": False}]}},
        serial=MOCK_SERIAL,
    )


async def test_set_wake_schedule_keeps_existing_schedules(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Schedules created in the app are kept and a new one is appended."""
    assert await setup_entry(hass, config_entry)

    coordinator = config_entry.runtime_data
    coordinator._states[MOCK_SERIAL] = {
        "wake_schedule": [{"cron": "0 8 * * 6,7", "on": True, "d": 1}]
    }

    await hass.services.async_call(
        DOMAIN,
        "set_wake_schedule",
        {"serial": MOCK_SERIAL, "hours": 6, "minutes": 30, "days": ["mon"]},
        blocking=True,
    )

    mock_client.set_coffee_params.assert_awaited_once_with(
        {
            "cfg": {
                "wake_schedule": [
                    {"cron": "0 8 * * 6,7", "on": True, "d": 1},
                    {"cron": "30 6 * * 1", "on": True},
                ]
            }
        },
        serial=MOCK_SERIAL,
    )


async def test_set_wake_schedule_updates_matching_schedule(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """A schedule with the same cron is toggled in place, not duplicated."""
    assert await setup_entry(hass, config_entry)

    coordinator = config_entry.runtime_data
    existing = {"cron": "30 6 * * 1", "on": True, "d": 1}
    coordinator._states[MOCK_SERIAL] = {"wake_schedule": [existing]}

    await hass.services.async_call(
        DOMAIN,
        "set_wake_schedule",
        {
            "serial": MOCK_SERIAL,
            "hours": 6,
            "minutes": 30,
            "days": ["mon"],
            "enabled": False,
        },
        blocking=True,
    )

    mock_client.set_coffee_params.assert_awaited_once_with(
        {"cfg": {"wake_schedule": [{"cron": "30 6 * * 1", "on": False, "d": 1}]}},
        serial=MOCK_SERIAL,
    )
    # The cached state is not mutated before the device confirms the change.
    assert existing["on"] is True


async def test_set_wake_schedule_unknown_serial(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """An unknown serial raises a validation error rather than a crash."""
    assert await setup_entry(hass, config_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_wake_schedule",
            {"serial": "NOPE", "hours": 6, "minutes": 30},
            blocking=True,
        )
    mock_client.set_coffee_params.assert_not_awaited()


async def test_disable_wake_schedule_preserves_entries(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Disabling flips each entry's "on" flag instead of sending an empty list (#47)."""
    assert await setup_entry(hass, config_entry)

    coordinator = config_entry.runtime_data
    coordinator._states[MOCK_SERIAL] = {
        "wake_schedule": [
            {"cron": "30 6 * * 1-5", "on": True, "d": 1},
            {"cron": "0 8 * * 6,7", "on": True, "d": 2},
        ]
    }

    await hass.services.async_call(
        DOMAIN,
        "disable_wake_schedule",
        {"serial": MOCK_SERIAL},
        blocking=True,
    )

    mock_client.set_coffee_params.assert_awaited_once_with(
        {
            "cfg": {
                "wake_schedule": [
                    {"cron": "30 6 * * 1-5", "on": False, "d": 1},
                    {"cron": "0 8 * * 6,7", "on": False, "d": 2},
                ]
            }
        },
        serial=MOCK_SERIAL,
    )


async def test_disable_wake_schedule_with_no_schedule_sends_nothing(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """With no known schedule there is nothing to disable, so no API call is made."""
    assert await setup_entry(hass, config_entry)

    await hass.services.async_call(
        DOMAIN,
        "disable_wake_schedule",
        {"serial": MOCK_SERIAL},
        blocking=True,
    )

    mock_client.set_coffee_params.assert_not_awaited()
