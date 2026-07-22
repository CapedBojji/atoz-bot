import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from api import pick_shifts
from app.models import JobConfig, ShiftBlockConfig
from utils.watcher import load_config


NEW_YORK = ZoneInfo("America/New_York")
GET_SHIFT_RULE_PRIORITY = getattr(pick_shifts, "__get_shift_rule_priority")
RUN_JOB = getattr(pick_shifts, "__run_job")


def iso_value(value: datetime | str) -> str:
    return value.isoformat() if isinstance(value, datetime) else value


def make_shift(shift_id: str, start: datetime | str, end: datetime | str) -> dict:
    return {
        "id": shift_id,
        "shift": {
            "timeRange": {
                "start": iso_value(start),
                "end": iso_value(end),
            }
        },
    }


class ConfiguredOvernightWindowTests(unittest.TestCase):
    def test_mixed_case_config_times_load_as_thirteen_hour_window(self):
        config_text = """
manual_login = true
username = "worker"

[[jobs]]
name = "overnight"
time_zone = "America/New_York"
time_to_pick = "now"
duration = "max"

[[jobs.rules]]
start = "monday at 2:00Pm"
end = "tuesday at 3:00Am"
priority = 7
""".lstrip()

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "worker.toml"
            config_path.write_text(config_text, encoding="utf-8")
            loaded = load_config(config_path)

        self.assertIsNotNone(loaded)
        job = loaded.jobs[0]
        rule = job.rules[0]
        self.assertEqual(job.time_zone, NEW_YORK)
        self.assertEqual(rule.start.strftime("%A %H:%M"), "Monday 14:00")
        self.assertEqual(rule.end.strftime("%A %H:%M"), "Tuesday 03:00")
        self.assertEqual(rule.end - rule.start, timedelta(hours=13))


class OvernightShiftContainmentTests(unittest.TestCase):
    def setUp(self):
        self.rule_start = datetime(2026, 7, 27, 14, 0, tzinfo=NEW_YORK)
        self.rule_end = datetime(2026, 7, 28, 3, 0, tzinfo=NEW_YORK)
        self.rules = [(self.rule_start, self.rule_end, 7)]

    def assert_matches(self, shift: dict) -> None:
        self.assertEqual(GET_SHIFT_RULE_PRIORITY(shift, self.rules), 7)

    def assert_does_not_match(self, shift: dict) -> None:
        self.assertIsNone(GET_SHIFT_RULE_PRIORITY(shift, self.rules))

    def test_every_fully_contained_boundary_case_matches(self):
        accepted = [
            make_shift("exact", self.rule_start, self.rule_end),
            make_shift(
                "starts-at-boundary",
                self.rule_start,
                self.rule_start + timedelta(minutes=1),
            ),
            make_shift(
                "ends-at-boundary",
                self.rule_end - timedelta(minutes=1),
                self.rule_end,
            ),
            make_shift(
                "inside-monday",
                self.rule_start + timedelta(minutes=1),
                datetime(2026, 7, 27, 23, 0, tzinfo=NEW_YORK),
            ),
            make_shift(
                "inside-tuesday",
                datetime(2026, 7, 28, 0, 0, tzinfo=NEW_YORK),
                self.rule_end - timedelta(microseconds=1),
            ),
            make_shift(
                "crosses-midnight",
                datetime(2026, 7, 27, 23, 30, tzinfo=NEW_YORK),
                datetime(2026, 7, 28, 2, 30, tzinfo=NEW_YORK),
            ),
            make_shift(
                "same-instants-in-utc",
                datetime(2026, 7, 27, 18, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 28, 7, 0, tzinfo=timezone.utc),
            ),
            make_shift(
                "same-instants-other-offset",
                "2026-07-27T13:00:00-05:00",
                "2026-07-28T02:00:00-05:00",
            ),
        ]

        for shift in accepted:
            with self.subTest(shift=shift["id"]):
                self.assert_matches(shift)

    def test_any_shift_extending_outside_window_is_excluded(self):
        rejected = [
            make_shift(
                "one-microsecond-before",
                self.rule_start - timedelta(microseconds=1),
                self.rule_start + timedelta(hours=1),
            ),
            make_shift(
                "one-minute-before",
                self.rule_start - timedelta(minutes=1),
                self.rule_start + timedelta(hours=1),
            ),
            make_shift(
                "one-microsecond-after",
                self.rule_end - timedelta(hours=1),
                self.rule_end + timedelta(microseconds=1),
            ),
            make_shift(
                "one-minute-after",
                self.rule_end - timedelta(hours=1),
                self.rule_end + timedelta(minutes=1),
            ),
            make_shift(
                "overlaps-start",
                self.rule_start - timedelta(hours=2),
                self.rule_start + timedelta(hours=2),
            ),
            make_shift(
                "overlaps-end",
                self.rule_end - timedelta(hours=2),
                self.rule_end + timedelta(hours=2),
            ),
            make_shift(
                "envelops-rule",
                self.rule_start - timedelta(hours=1),
                self.rule_end + timedelta(hours=1),
            ),
            make_shift(
                "entirely-before",
                self.rule_start - timedelta(hours=2),
                self.rule_start - timedelta(hours=1),
            ),
            make_shift(
                "entirely-after",
                self.rule_end + timedelta(hours=1),
                self.rule_end + timedelta(hours=2),
            ),
        ]

        for shift in rejected:
            with self.subTest(shift=shift["id"]):
                self.assert_does_not_match(shift)

    def test_quarter_hour_grid_obeys_strict_containment_property(self):
        window_minutes = int((self.rule_end - self.rule_start).total_seconds() / 60)
        offsets = range(-60, window_minutes + 61, 15)

        for start_offset in offsets:
            for end_offset in offsets:
                shift = make_shift(
                    f"grid-{start_offset}-{end_offset}",
                    self.rule_start + timedelta(minutes=start_offset),
                    self.rule_start + timedelta(minutes=end_offset),
                )
                expected = 0 <= start_offset < end_offset <= window_minutes
                actual = GET_SHIFT_RULE_PRIORITY(shift, self.rules) == 7
                self.assertEqual(
                    actual,
                    expected,
                    msg=(
                        f"containment mismatch for offsets "
                        f"{start_offset}..{end_offset} minutes"
                    ),
                )

    def test_invalid_or_ambiguous_shift_times_are_excluded(self):
        rejected = [
            make_shift("zero-duration", self.rule_start, self.rule_start),
            make_shift(
                "negative-duration",
                self.rule_start + timedelta(hours=1),
                self.rule_start,
            ),
            make_shift(
                "missing-timezone",
                datetime(2026, 7, 27, 14, 0),
                datetime(2026, 7, 27, 15, 0),
            ),
            make_shift(
                "mixed-timezones",
                self.rule_start,
                datetime(2026, 7, 27, 15, 0),
            ),
            make_shift("malformed", "not-a-time", "also-not-a-time"),
            {"id": "missing-range", "shift": {}},
        ]

        for shift in rejected:
            with self.subTest(shift=shift["id"]):
                self.assert_does_not_match(shift)

    def test_highest_priority_of_containing_rules_is_returned(self):
        shift = make_shift(
            "multi-rule",
            self.rule_start + timedelta(hours=2),
            self.rule_start + timedelta(hours=3),
        )
        rules = [
            (self.rule_start, self.rule_end, 2),
            (
                self.rule_start + timedelta(hours=1),
                self.rule_end - timedelta(hours=1),
                9,
            ),
            (self.rule_end, self.rule_start, 100),
        ]

        self.assertEqual(GET_SHIFT_RULE_PRIORITY(shift, rules), 9)


class FullJobContainmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_only_sends_fully_contained_unique_shifts_to_picker(self):
        rule_start = datetime(2026, 7, 27, 14, 0)
        rule_end = datetime(2026, 7, 28, 3, 0)
        aware_start = rule_start.replace(tzinfo=NEW_YORK)
        aware_end = rule_end.replace(tzinfo=NEW_YORK)
        job = JobConfig(
            time_to_pick=None,
            time_zone=NEW_YORK,
            rules=[ShiftBlockConfig(rule_start, rule_end, priority=7)],
            duration=timedelta.max,
            name="overnight",
        )
        session = SimpleNamespace(
            get_config=lambda: SimpleNamespace(username="worker")
        )
        job_session = SimpleNamespace(client=object(), employee_id=12345)

        candidates = [
            make_shift("exact", aware_start, aware_end),
            make_shift(
                "inside",
                aware_start + timedelta(hours=1),
                aware_end - timedelta(hours=1),
            ),
            make_shift(
                "utc-inside",
                datetime(2026, 7, 27, 20, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 28, 6, 0, tzinfo=timezone.utc),
            ),
            make_shift(
                "starts-before",
                aware_start - timedelta(microseconds=1),
                aware_start + timedelta(hours=1),
            ),
            make_shift(
                "ends-after",
                aware_end - timedelta(hours=1),
                aware_end + timedelta(microseconds=1),
            ),
            make_shift(
                "envelops",
                aware_start - timedelta(hours=1),
                aware_end + timedelta(hours=1),
            ),
            make_shift("zero", aware_start, aware_start),
            make_shift(
                "naive",
                datetime(2026, 7, 27, 15, 0),
                datetime(2026, 7, 27, 16, 0),
            ),
            make_shift("exact", aware_start, aware_end),
        ]

        get_shifts = AsyncMock(return_value=candidates)
        pick_shift = AsyncMock(return_value=True)
        with (
            patch.object(pick_shifts, "__get_shifts", new=get_shifts),
            patch.object(pick_shifts, "__pick_shift", new=pick_shift),
        ):
            await RUN_JOB(session, job_session, job, 1)

        get_shifts.assert_awaited_once()
        _, query_start, query_end = get_shifts.await_args.args
        self.assertEqual(query_start, "2026-07-27T18:00:00+00:00")
        self.assertEqual(query_end, "2026-07-28T07:00:00+00:00")

        picked_ids = [call.args[1]["id"] for call in pick_shift.await_args_list]
        self.assertCountEqual(picked_ids, ["exact", "inside", "utc-inside"])
        self.assertEqual(picked_ids.count("exact"), 1)


if __name__ == "__main__":
    unittest.main()
