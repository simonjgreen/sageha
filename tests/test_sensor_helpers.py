"""Tests for the pure helper functions behind the sensor platform."""

from datetime import datetime, timezone
import zoneinfo

import pytest

from custom_components.sagecoffee.const import BOILER_BREW, BOILER_STEAM
from custom_components.sagecoffee.sensor import (
    _format_remote_wake,
    _format_temperature_unit,
    _format_wake_schedule,
    _get_boiler_target,
    _get_boiler_temp,
    _get_errors_attributes,
    _get_errors_count,
    _get_last_paired,
    _get_next_wake_time,
    _parse_cron_next,
)

UTC = zoneinfo.ZoneInfo("UTC")
LONDON = zoneinfo.ZoneInfo("Europe/London")

# A Wednesday, 10:00 UTC.
WEDNESDAY = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)


class TestParseCronNext:
    """The device cron format is "MM HH * * DAYS" with 1=Mon…7=Sun."""

    def test_later_today(self) -> None:
        result = _parse_cron_next("30 18 * * *", WEDNESDAY, UTC)
        assert result == datetime(2026, 8, 12, 18, 30, tzinfo=UTC)

    def test_time_already_passed_rolls_to_tomorrow(self) -> None:
        result = _parse_cron_next("30 6 * * *", WEDNESDAY, UTC)
        assert result == datetime(2026, 8, 13, 6, 30, tzinfo=UTC)

    def test_specific_day_uses_device_numbering(self) -> None:
        # Device day 6 = Saturday (1=Mon…7=Sun), not Python's 6=Sunday.
        result = _parse_cron_next("0 7 * * 6", WEDNESDAY, UTC)
        assert result == datetime(2026, 8, 15, 7, 0, tzinfo=UTC)
        assert result.weekday() == 5  # Saturday

    def test_sunday_is_day_seven(self) -> None:
        result = _parse_cron_next("0 7 * * 7", WEDNESDAY, UTC)
        assert result == datetime(2026, 8, 16, 7, 0, tzinfo=UTC)
        assert result.weekday() == 6  # Sunday

    def test_day_range(self) -> None:
        # Mon-Fri; from Wednesday 10:00 the next 06:30 slot is Thursday.
        result = _parse_cron_next("30 6 * * 1-5", WEDNESDAY, UTC)
        assert result == datetime(2026, 8, 13, 6, 30, tzinfo=UTC)

    def test_day_list_skips_to_next_allowed_day(self) -> None:
        # Sat,Sun only; from Wednesday the next slot is Saturday.
        result = _parse_cron_next("0 8 * * 6,7", WEDNESDAY, UTC)
        assert result == datetime(2026, 8, 15, 8, 0, tzinfo=UTC)

    @pytest.mark.parametrize(
        "cron",
        ["", "30 6 * *", "aa bb * * *", "30 6 * * x"],
        ids=["empty", "four_fields", "non_numeric_time", "non_numeric_days"],
    )
    def test_malformed_cron_returns_none(self, cron: str) -> None:
        assert _parse_cron_next(cron, WEDNESDAY, UTC) is None

    def test_dst_transition_does_not_crash(self) -> None:
        # UK clocks go forward 29 Mar 2026: 01:30 does not exist that day.
        after = datetime(2026, 3, 28, 23, 0, tzinfo=LONDON)
        result = _parse_cron_next("30 1 * * *", after, LONDON)
        assert result is not None
        assert (result.day, result.hour, result.minute) == (29, 1, 30)


class TestGetNextWakeTime:
    def test_picks_earliest_enabled_entry(self, freezer) -> None:
        freezer.move_to("2026-08-12 10:00:00+00:00")
        state = {
            "timezone": "UTC",
            "wake_schedule": [
                {"cron": "0 18 * * *", "on": True},
                {"cron": "0 6 * * *", "on": False},  # earlier but disabled
                {"cron": "0 15 * * *", "on": True},
            ],
        }
        assert _get_next_wake_time(state) == datetime(
            2026, 8, 12, 15, 0, tzinfo=UTC
        )

    def test_unknown_timezone_falls_back_to_utc(self, freezer) -> None:
        freezer.move_to("2026-08-12 10:00:00+00:00")
        state = {
            "timezone": "Not/AZone",
            "wake_schedule": [{"cron": "0 18 * * *", "on": True}],
        }
        result = _get_next_wake_time(state)
        assert result is not None
        assert result.utcoffset().total_seconds() == 0

    def test_no_enabled_entries_returns_none(self) -> None:
        assert _get_next_wake_time({"wake_schedule": [], "timezone": "UTC"}) is None


class TestBoilerLookup:
    STATE = {
        "boiler_temps": [
            {"id": "0", "cur_temp": 135.0, "temp_sp": 135.5},
            {"id": "1", "cur_temp": 93.0, "temp_sp": 93.5},
        ]
    }

    def test_matches_int_id_against_string_id(self) -> None:
        # The library reports string IDs; lookups use int constants.
        assert _get_boiler_temp(self.STATE, BOILER_STEAM) == 135.0
        assert _get_boiler_target(self.STATE, BOILER_STEAM) == 135.5
        assert _get_boiler_temp(self.STATE, BOILER_BREW) == 93.0

    def test_unknown_boiler_returns_none(self) -> None:
        assert _get_boiler_temp(self.STATE, 2) is None
        assert _get_boiler_target(self.STATE, 2) is None

    def test_single_boiler_is_the_brew_boiler(self) -> None:
        state = {"boiler_temps": [{"id": "0", "cur_temp": 92.0, "temp_sp": 93.0}]}
        assert _get_boiler_temp(state, BOILER_BREW) == 92.0
        assert _get_boiler_target(state, BOILER_BREW) == 93.0
        assert _get_boiler_temp(state, BOILER_STEAM) is None
        assert _get_boiler_target(state, BOILER_STEAM) is None


class TestErrorsAttributes:
    def test_lists_reported_errors(self) -> None:
        state = {"errors": ["WaterTankEmpty"]}
        assert _get_errors_attributes(state) == {"errors": ["WaterTankEmpty"]}

    def test_missing_errors_is_empty_list(self) -> None:
        assert _get_errors_attributes({}) == {"errors": []}


class TestGetLastPaired:
    EXPECTED = datetime(2025, 8, 13, 16, 0, tzinfo=timezone.utc)

    def test_epoch_seconds(self) -> None:
        assert _get_last_paired({"last_paired": 1755100800}) == self.EXPECTED

    def test_epoch_milliseconds_are_scaled(self) -> None:
        assert _get_last_paired({"last_paired": 1755100800000}) == self.EXPECTED

    def test_string_epoch(self) -> None:
        assert _get_last_paired({"last_paired": "1755100800"}) == self.EXPECTED

    @pytest.mark.parametrize(
        "value",
        [None, "", "none", "not-a-number", {}],
        ids=["none", "empty", "none_sentinel", "garbage", "dict"],
    )
    def test_unparseable_returns_none(self, value) -> None:
        assert _get_last_paired({"last_paired": value}) is None


class TestFormatters:
    def test_temperature_unit(self) -> None:
        assert _format_temperature_unit({"temperature_unit": 0}) == "Celsius"
        assert _format_temperature_unit({"temperature_unit": 1}) == "Fahrenheit"
        assert _format_temperature_unit({"temperature_unit": None}) is None
        assert _format_temperature_unit({"temperature_unit": 2}) == "2"

    def test_remote_wake(self) -> None:
        assert _format_remote_wake({"remote_wake": True}) == "enabled"
        assert _format_remote_wake({"remote_wake": False}) == "disabled"
        assert _format_remote_wake({"remote_wake": None}) is None

    def test_errors_count(self) -> None:
        assert _get_errors_count({"errors": ["e1", "e2"]}) == 2
        assert _get_errors_count({"errors": []}) == 0
        assert _get_errors_count({"errors": None}) is None
        assert _get_errors_count({"errors": "oops"}) is None

    def test_wake_schedule_summary(self) -> None:
        schedule = [
            {"cron": "30 6 * * *", "on": True},
            {"cron": "0 8 * * 6", "on": False},
            "bogus",
        ]
        assert (
            _format_wake_schedule({"wake_schedule_raw": schedule})
            == "30 6 * * * (on), 0 8 * * 6 (off)"
        )
        assert _format_wake_schedule({"wake_schedule_raw": []}) == "none"
        assert _format_wake_schedule({"wake_schedule_raw": None}) == "none"
        assert _format_wake_schedule({"wake_schedule_raw": [{"on": True}]}) is None
