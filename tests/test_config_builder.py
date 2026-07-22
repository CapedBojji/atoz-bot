import importlib.util
import sys
import tempfile
import tomllib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import parsedatetime

from utils.watcher import load_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_BUILDER_PATH = PROJECT_ROOT / "scripts" / "config-builder.py"


def load_config_builder():
    spec = importlib.util.spec_from_file_location("config_builder", CONFIG_BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {CONFIG_BUILDER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


config_builder = load_config_builder()


class ConfigDirectoryTests(unittest.TestCase):
    def test_default_config_folder_is_inside_app(self):
        self.assertEqual(
            config_builder.resolve_config_dir(None),
            PROJECT_ROOT / "config",
        )

    def test_relative_config_folder_is_resolved_inside_app(self):
        self.assertEqual(
            config_builder.resolve_config_dir(Path("custom-config")),
            PROJECT_ROOT / "custom-config",
        )

    def test_absolute_config_folder_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            expected = Path(temp_dir).resolve()
            self.assertEqual(config_builder.resolve_config_dir(expected), expected)


class PickTimeTests(unittest.TestCase):
    def test_pick_time_uses_actual_requested_weekday(self):
        parsed_value = config_builder.parse_pick_time("Friday 5:45 PM")

        self.assertEqual(parsed_value, "friday at 5:45 PM")
        source = datetime(2026, 7, 21, 12, 0).timetuple()
        parsed, parse_status = parsedatetime.Calendar(
            version=parsedatetime.VERSION_CONTEXT_STYLE
        ).parse(
            parsed_value,
            sourceTime=source,
        )
        parsed_datetime = datetime(*parsed[:6])
        self.assertTrue(parse_status)
        self.assertEqual(parsed_datetime.strftime("%A"), "Friday")
        self.assertEqual((parsed_datetime.hour, parsed_datetime.minute), (17, 45))


class ParseShiftPieceTests(unittest.TestCase):
    def test_explicit_overnight_end_day(self):
        rules = config_builder.parse_shift_piece("Monday 2 PM to Tuesday 2 AM")

        self.assertIsNotNone(rules)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].day, "monday")
        self.assertEqual(rules[0].start, "2:00 PM")
        self.assertEqual(rules[0].end_day, "tuesday")
        self.assertEqual(rules[0].end, "2:00 AM")
        self.assertEqual(config_builder.rule_duration_minutes(rules[0]), 12 * 60)
        self.assertEqual(
            config_builder.format_rule_summary(rules[0]),
            "Monday 2:00 PM → Tuesday 2:00 AM (12h)",
        )

    def test_implicit_overnight_end_day(self):
        rules = config_builder.parse_shift_piece("Monday 2 PM to 2 AM")

        self.assertIsNotNone(rules)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].end_day, "tuesday")

    def test_same_day_range_keeps_same_end_day(self):
        rules = config_builder.parse_shift_piece("Monday 2 PM to 8 PM")

        self.assertIsNotNone(rules)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].end_day, "monday")

    def test_multiple_start_days_create_one_rule_per_day(self):
        rules = config_builder.parse_shift_piece(
            "Monday Wednesday Friday 9 AM to 5 PM"
        )

        self.assertIsNotNone(rules)
        self.assertEqual(
            [(rule.day, rule.end_day) for rule in rules],
            [
                ("monday", "monday"),
                ("wednesday", "wednesday"),
                ("friday", "friday"),
            ],
        )


class WriteConfigTests(unittest.TestCase):
    def test_overnight_rule_is_written_with_next_day(self):
        rules = config_builder.parse_shift_piece("Monday 2 PM to Tuesday 2 AM")
        self.assertIsNotNone(rules)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "worker.toml"
            config_builder.write_config(
                output_path=output_path,
                username="worker",
                time_to_pick="now",
                reload_session_on=None,
                rules=rules,
            )

            with output_path.open("rb") as config_file:
                generated = tomllib.load(config_file)

            rule = generated["jobs"][0]["rules"][0]
            self.assertEqual(rule["start"], "monday at 2:00 PM")
            self.assertEqual(rule["end"], "tuesday at 2:00 AM")
            self.assertEqual(output_path.stat().st_mode & 0o777, 0o600)

    def test_selected_timezone_is_written(self):
        rules = config_builder.parse_shift_piece("Monday 2 PM to Tuesday 2 AM")
        self.assertIsNotNone(rules)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "worker.toml"
            config_builder.write_config(
                output_path=output_path,
                username="worker",
                time_to_pick="friday at 5:45 PM",
                reload_session_on=None,
                rules=rules,
                time_zone="America/Los_Angeles",
            )

            with output_path.open("rb") as config_file:
                generated = tomllib.load(config_file)

        self.assertEqual(generated["jobs"][0]["time_zone"], "America/Los_Angeles")

    def test_loading_on_monday_keeps_tuesday_end_after_monday_start(self):
        rules = config_builder.parse_shift_piece("Monday 2 PM to Tuesday 2 AM")
        self.assertIsNotNone(rules)

        parsed_times = {
            "now": datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc),
            "monday at 2:00 PM": datetime(
                2026, 7, 27, 14, 0, tzinfo=timezone.utc
            ),
            "tuesday at 2:00 AM": datetime(
                2026, 7, 21, 2, 0, tzinfo=timezone.utc
            ),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "worker.toml"
            config_builder.write_config(
                output_path=output_path,
                username="worker",
                time_to_pick="now",
                reload_session_on=None,
                rules=rules,
            )

            with patch(
                "utils.watcher.parse_str_to_time",
                side_effect=lambda value: parsed_times[value],
            ):
                loaded = load_config(output_path)

        self.assertIsNotNone(loaded)
        loaded_rule = loaded.jobs[0].rules[0]
        self.assertGreater(loaded_rule.end, loaded_rule.start)
        self.assertEqual(loaded_rule.end - loaded_rule.start, timedelta(hours=12))


if __name__ == "__main__":
    unittest.main()
