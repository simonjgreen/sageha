"""Tests that boiler sensors follow every state report from the WebSocket stream."""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from sagecoffee.models import DeviceState

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import MOCK_SERIAL


def make_state(
    state: str, steam: tuple[float, float] | None, brew: tuple[float, float] | None
) -> DeviceState:
    """A dual boiler state report; None boilers mean the machine reports none."""
    boilers = []
    if steam is not None and brew is not None:
        boilers = [
            {"cur_temp": steam[0], "temp_sp": steam[1]},
            {"cur_temp": brew[0], "temp_sp": brew[1]},
        ]
    return DeviceState(
        raw_data={"reported": {"state": state, "boiler": boilers}},
        serial_number=MOCK_SERIAL,
        version=1,
    )


async def setup_with_stream(
    hass: HomeAssistant, mock_client: MagicMock, entry: MockConfigEntry
) -> asyncio.Queue[DeviceState]:
    """Set up the entry with a state stream fed from a queue."""
    queue: asyncio.Queue[DeviceState] = asyncio.Queue()

    async def tail_state():
        while True:
            yield await queue.get()

    mock_client.tail_state = tail_state
    # Start with a dual boiler state so the steam sensors are created.
    mock_client.get_last_state.return_value = make_state(
        "asleep", (20.0, 131.0), (20.0, 93.3)
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return queue


def boiler_entity_ids(hass: HomeAssistant) -> dict[str, str]:
    """Map sensor keys to entity IDs."""
    registry = er.async_get(hass)
    keys = ("brew_temp", "brew_target", "steam_temp", "steam_target", "state")
    return {
        key: registry.async_get_entity_id("sensor", "sagecoffee", f"{MOCK_SERIAL}_{key}")
        for key in keys
    }


def read(hass: HomeAssistant, ids: dict[str, str]) -> dict[str, Any]:
    """Read the current sensor states."""
    return {key: hass.states.get(entity_id).state for key, entity_id in ids.items()}


async def push(
    hass: HomeAssistant, queue: asyncio.Queue[DeviceState], state: DeviceState
) -> None:
    """Deliver one state report and let Home Assistant process it."""
    await queue.put(state)
    await hass.async_block_till_done()


async def test_sensors_follow_warm_up_until_target(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Every report updates the sensors, including after the brew target is reached."""
    queue = await setup_with_stream(hass, mock_client, config_entry)
    ids = boiler_entity_ids(hass)

    # Sequence recorded from a BES995 warming up.
    sequence = [
        ("warming", (107.0, 131.0), (87.0, 93.3)),
        ("warming", (109.0, 131.0), (93.0, 93.3)),
        ("ready", (109.0, 131.0), (93.3, 93.3)),
        ("ready", (115.0, 131.0), (93.3, 93.3)),
        ("ready", (127.0, 131.0), (93.3, 93.3)),
        ("ready", (131.0, 131.0), (93.3, 93.3)),
    ]
    for state, steam, brew in sequence:
        await push(hass, queue, make_state(state, steam, brew))
        assert read(hass, ids) == {
            "state": state,
            "steam_temp": str(steam[0]),
            "steam_target": str(steam[1]),
            "brew_temp": str(brew[0]),
            "brew_target": str(brew[1]),
        }


async def test_sensors_follow_increased_target(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """A higher target is shown at once and the current temperature keeps updating."""
    queue = await setup_with_stream(hass, mock_client, config_entry)
    ids = boiler_entity_ids(hass)

    await push(hass, queue, make_state("ready", (131.0, 131.0), (93.3, 93.3)))

    # Targets raised on the machine; the boilers then heat towards them.
    for steam, brew in [
        ((131.0, 135.0), (93.3, 95.0)),
        ((133.0, 135.0), (94.0, 95.0)),
        ((135.0, 135.0), (95.0, 95.0)),
    ]:
        await push(hass, queue, make_state("ready", steam, brew))
        values = read(hass, ids)
        assert values["steam_temp"] == str(steam[0])
        assert values["steam_target"] == str(steam[1])
        assert values["brew_temp"] == str(brew[0])
        assert values["brew_target"] == str(brew[1])

    # A lowered target is followed too.
    await push(hass, queue, make_state("ready", (135.0, 130.0), (95.0, 92.0)))
    values = read(hass, ids)
    assert values["steam_target"] == "130.0"
    assert values["brew_target"] == "92.0"


async def test_sensors_unknown_while_asleep_then_resume(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Asleep reports no boilers; the sensors resume when it wakes again."""
    queue = await setup_with_stream(hass, mock_client, config_entry)
    ids = boiler_entity_ids(hass)

    await push(hass, queue, make_state("asleep", None, None))
    values = read(hass, ids)
    assert values["state"] == "asleep"
    assert values["brew_temp"] == "unknown"
    assert values["steam_temp"] == "unknown"

    await push(hass, queue, make_state("warming", (107.0, 131.0), (87.0, 93.3)))
    values = read(hass, ids)
    assert values["brew_temp"] == "87.0"
    assert values["steam_temp"] == "107.0"


def stream_script(*steps: Any):
    """A tail_state replacement running one step per call.

    Each step is an exception to raise, a list of states to yield before
    staying open until cancelled, or a tuple of states to yield before the
    stream ends. Calls after the last step stay open.
    """
    calls = iter(steps)

    async def tail_state():
        step = next(calls, [])
        if isinstance(step, Exception):
            raise step
        for state in step:
            yield state
        if isinstance(step, list):
            await asyncio.Event().wait()

    return tail_state


async def setup_with_script(
    hass: HomeAssistant,
    mock_client: MagicMock,
    entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    *steps: Any,
) -> None:
    """Set up the entry with a scripted state stream and near-zero restart delays."""
    monkeypatch.setattr("custom_components.sagecoffee.WS_RESTART_DELAY_INITIAL", 0.01)
    monkeypatch.setattr("custom_components.sagecoffee.WS_RESTART_DELAY_MAX", 0.04)
    mock_client.tail_state = stream_script(*steps)
    mock_client.get_last_state.return_value = make_state(
        "asleep", (20.0, 131.0), (20.0, 93.3)
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def wait_for(hass: HomeAssistant, check: Any) -> None:
    """Let the listener run until check() holds."""
    for _ in range(200):
        await hass.async_block_till_done()
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


async def test_listener_restarts_after_stream_error(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed stream is restarted and the sensors update again."""
    await setup_with_script(
        hass,
        mock_client,
        config_entry,
        monkeypatch,
        RuntimeError("cloud hiccup"),
        [make_state("ready", (131.0, 131.0), (93.3, 93.3))],
    )
    ids = boiler_entity_ids(hass)

    await wait_for(hass, lambda: read(hass, ids)["brew_temp"] == "93.3")
    assert read(hass, ids)["steam_temp"] == "131.0"


async def test_entities_unavailable_while_stream_is_down(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale values are shown as unavailable until the stream delivers again."""
    gate = asyncio.Event()

    async def reconnect_later():
        await gate.wait()
        yield make_state("ready", (131.0, 131.0), (93.3, 93.3))
        await asyncio.Event().wait()

    steps = iter(
        [
            [make_state("warming", (107.0, 131.0), (87.0, 93.3))],  # then ends
            None,  # reconnect waits for the gate
        ]
    )
    monkeypatch.setattr("custom_components.sagecoffee.WS_RESTART_DELAY_INITIAL", 0.01)
    monkeypatch.setattr("custom_components.sagecoffee.WS_RESTART_DELAY_MAX", 0.04)

    async def tail_state():
        step = next(steps, None)
        if step is None:
            async for state in reconnect_later():
                yield state
            return
        for state in step:
            yield state

    mock_client.tail_state = tail_state
    mock_client.get_last_state.return_value = None
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    ids = boiler_entity_ids(hass)

    registry = er.async_get(hass)
    volume = registry.async_get_entity_id("number", "sagecoffee", f"{MOCK_SERIAL}_volume")
    theme = registry.async_get_entity_id("select", "sagecoffee", f"{MOCK_SERIAL}_color_theme")

    await wait_for(hass, lambda: read(hass, ids)["brew_temp"] == "unavailable")
    assert read(hass, ids)["steam_temp"] == "unavailable"
    assert hass.states.get(volume).state == "unavailable"
    assert hass.states.get(theme).state == "unavailable"

    gate.set()
    await wait_for(hass, lambda: read(hass, ids)["brew_temp"] == "93.3")
    assert hass.states.get(volume).state != "unavailable"
    assert hass.states.get(theme).state != "unavailable"


async def test_restart_delay_backs_off_and_resets(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Repeated failures double the delay up to the maximum; a report resets it."""
    # After the report the stream ends (0.01 s), then the next failure doubles it.
    failure = RuntimeError("down")
    await setup_with_script(
        hass,
        mock_client,
        config_entry,
        monkeypatch,
        failure,
        failure,
        failure,
        failure,
        (make_state("ready", (131.0, 131.0), (93.3, 93.3)),),
        failure,
    )

    def delays() -> list[str]:
        return [
            r.getMessage().rsplit("restarting in ", 1)[1]
            for r in caplog.records
            if "restarting in" in r.getMessage()
        ]

    await wait_for(hass, lambda: len(delays()) >= 6)
    assert delays()[:6] == ["0.01 s", "0.02 s", "0.04 s", "0.04 s", "0.01 s", "0.02 s"]


async def test_auth_error_starts_reauth_without_restart(
    hass: HomeAssistant,
    mock_client: MagicMock,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An auth failure asks for re-authentication instead of retrying."""
    calls = 0

    async def tail_state():
        nonlocal calls
        calls += 1
        raise httpx.HTTPStatusError(
            "unauthorised", request=MagicMock(), response=MagicMock(status_code=401)
        )
        yield  # pragma: no cover

    monkeypatch.setattr("custom_components.sagecoffee.WS_RESTART_DELAY_INITIAL", 0.01)
    mock_client.tail_state = tail_state
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()

    assert calls == 1
    flows = hass.config_entries.flow.async_progress_by_handler("sagecoffee")
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_report_without_state_field(
    hass: HomeAssistant, mock_client: MagicMock, config_entry: MockConfigEntry
) -> None:
    """A report without a "state" field doesn't break number/select availability."""
    queue = await setup_with_stream(hass, mock_client, config_entry)
    registry = er.async_get(hass)
    volume = registry.async_get_entity_id("number", "sagecoffee", f"{MOCK_SERIAL}_volume")

    await push(
        hass,
        queue,
        DeviceState(
            raw_data={"reported": {"boiler": [{"cur_temp": 131.0}, {"cur_temp": 93.3}]}},
            serial_number=MOCK_SERIAL,
        ),
    )

    assert hass.states.get(volume).state != "unavailable"
    ids = boiler_entity_ids(hass)
    assert read(hass, ids)["brew_temp"] == "93.3"
