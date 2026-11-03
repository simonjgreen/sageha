"""Tests for the power switch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.sagecoffee.switch import SageCoffeePowerSwitch

from .conftest import MOCK_SERIAL


def make_switch() -> tuple[SageCoffeePowerSwitch, MagicMock]:
    """Build a power switch backed by a mocked coordinator."""
    coordinator = MagicMock()
    coordinator.client.wake = AsyncMock()
    coordinator.client.sleep = AsyncMock()
    appliance = SimpleNamespace(serial_number=MOCK_SERIAL, name="Kitchen", model="X")
    return SageCoffeePowerSwitch(coordinator, appliance), coordinator


async def test_turn_on_wakes_this_appliance() -> None:
    """Waking targets this switch's appliance, not the account's first one."""
    switch, coordinator = make_switch()

    await switch.async_turn_on()

    coordinator.client.wake.assert_awaited_once_with(MOCK_SERIAL)


async def test_turn_off_sleeps_this_appliance() -> None:
    """Sleeping targets this switch's appliance, not the account's first one."""
    switch, coordinator = make_switch()

    await switch.async_turn_off()

    coordinator.client.sleep.assert_awaited_once_with(MOCK_SERIAL)
