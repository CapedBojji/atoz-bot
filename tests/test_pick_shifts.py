import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from api import pick_shifts


NEW_YORK = ZoneInfo("America/New_York")
GET_SHIFT_RULE_PRIORITY = getattr(pick_shifts, "__get_shift_rule_priority")


def make_shift(shift_id: str, start: datetime, end: datetime) -> dict:
    return {
        "id": shift_id,
        "shift": {
            "timeRange": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        },
    }


class OvernightShiftRuleTests(unittest.TestCase):
    def setUp(self):
        self.rule_start = datetime(2026, 7, 27, 14, 0, tzinfo=NEW_YORK)
        self.rule_end = datetime(2026, 7, 28, 2, 0, tzinfo=NEW_YORK)
        self.rules = [(self.rule_start, self.rule_end, 7)]

    def test_exact_monday_afternoon_to_tuesday_morning_shift_matches(self):
        shift = make_shift("overnight", self.rule_start, self.rule_end)

        priority = GET_SHIFT_RULE_PRIORITY(shift, self.rules)

        self.assertEqual(priority, 7)

    def test_equivalent_utc_shift_matches_local_time_rule(self):
        shift = make_shift(
            "overnight-utc",
            datetime.fromisoformat("2026-07-27T18:00:00+00:00"),
            datetime.fromisoformat("2026-07-28T06:00:00+00:00"),
        )

        priority = GET_SHIFT_RULE_PRIORITY(shift, self.rules)

        self.assertEqual(priority, 7)

    def test_shift_ending_after_overnight_window_does_not_match(self):
        shift = make_shift(
            "too-late",
            self.rule_start,
            datetime(2026, 7, 28, 2, 1, tzinfo=NEW_YORK),
        )

        priority = GET_SHIFT_RULE_PRIORITY(shift, self.rules)

        self.assertIsNone(priority)


if __name__ == "__main__":
    unittest.main()
