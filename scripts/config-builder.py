#!/usr/bin/env python3
import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_TIME_ZONE = "America/New_York"
WEEK_MINUTES = 7 * 24 * 60


DAYS = {
    "monday": "monday",
    "mon": "monday",
    "tuesday": "tuesday",
    "tue": "tuesday",
    "tues": "tuesday",
    "wednesday": "wednesday",
    "wed": "wednesday",
    "thursday": "thursday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "friday": "friday",
    "fri": "friday",
    "saturday": "saturday",
    "sat": "saturday",
    "sunday": "sunday",
    "sun": "sunday",
}

DAY_ORDER = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
DAY_PATTERN = "|".join(sorted(DAYS, key=len, reverse=True))


@dataclass
class ShiftRule:
    day: str
    start: str
    end: str
    end_day: str | None = None
    priority: int = 0


def resolve_config_dir(config_dir: Path | None) -> Path:
    """Resolve config paths against the app, never the caller's working directory."""
    if config_dir is None:
        return DEFAULT_CONFIG_DIR
    if config_dir.is_absolute():
        return config_dir.resolve()
    return (PROJECT_ROOT / config_dir).resolve()


def ask(prompt: str, default: str | None = None) -> str:
    if default is None:
        answer = input(f"{prompt} ").strip()
    else:
        answer = input(f"{prompt} [{default}] ").strip()
    return answer or (default or "")


def ask_required(prompt: str) -> str:
    while True:
        answer = ask(prompt)
        if answer:
            return answer
        print("Please type an answer.")


def toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def safe_file_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "", value.strip().lower())
    return cleaned or "friend"


def normalize_day(value: str) -> str | None:
    return DAYS.get(value.strip().lower())


def normalize_time(value: str) -> str | None:
    value = value.strip().lower().replace(".", "")
    value = re.sub(r"\s+", " ", value)
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)", value)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3).upper()
    if hour < 1 or hour > 12 or minute > 59:
        return None
    return f"{hour}:{minute:02d} {meridiem}"


def parse_pick_time(raw_value: str) -> str | None:
    value = raw_value.strip()
    if not value:
        value = "Friday 5:45 PM"
    if value.lower() == "now":
        return "now"

    match = re.search(
        rf"\b({DAY_PATTERN})\b(?:\s+at)?\s+(\d{{1,2}}(?::\d{{2}})?\s*[ap]m)\b",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    day = normalize_day(match.group(1))
    time_value = normalize_time(match.group(2))
    if day is None or time_value is None:
        return None
    return f"{day} at {time_value}"


def time_sort_key(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,2}):(\d{2}) ([AP]M)", value)
    if not match:
        return (0, 0)
    hour = int(match.group(1))
    minute = int(match.group(2))
    if match.group(3) == "PM" and hour != 12:
        hour += 12
    if match.group(3) == "AM" and hour == 12:
        hour = 0
    return (hour, minute)


def time_minutes(value: str) -> int:
    hour, minute = time_sort_key(value)
    return hour * 60 + minute


def rule_duration_minutes(rule: ShiftRule) -> int:
    start_day = DAY_ORDER.index(rule.day)
    end_day = DAY_ORDER.index(rule.end_day or rule.day)
    start = start_day * 24 * 60 + time_minutes(rule.start)
    end = end_day * 24 * 60 + time_minutes(rule.end)
    if end <= start:
        end += WEEK_MINUTES
    return end - start


def format_duration(minutes: int) -> str:
    hours, remaining_minutes = divmod(minutes, 60)
    if remaining_minutes:
        return f"{hours}h {remaining_minutes}m"
    return f"{hours}h"


def format_rule_summary(rule: ShiftRule) -> str:
    end_day = rule.end_day or rule.day
    return (
        f"{rule.day.title()} {rule.start} → "
        f"{end_day.title()} {rule.end} "
        f"({format_duration(rule_duration_minutes(rule))})"
    )


def validate_rules(rules: list[ShiftRule]) -> None:
    if not rules:
        raise ValueError("Add at least one shift window.")
    for rule in rules:
        if rule.day not in DAY_ORDER or (rule.end_day or rule.day) not in DAY_ORDER:
            raise ValueError("A shift window contains an unknown weekday.")
        if normalize_time(rule.start) != rule.start or normalize_time(rule.end) != rule.end:
            raise ValueError("A shift window contains an invalid time.")
        duration = rule_duration_minutes(rule)
        if duration <= 0 or duration >= WEEK_MINUTES:
            raise ValueError(f"Invalid shift window: {format_rule_summary(rule)}")


def next_day(day: str) -> str:
    return DAY_ORDER[(DAY_ORDER.index(day) + 1) % len(DAY_ORDER)]


def maybe_expand_time_range(text: str) -> str:
    return text


def parse_shift_piece(
    piece: str,
    ask_about_ambiguous: bool = True,
) -> list[ShiftRule] | None:
    piece = maybe_expand_time_range(piece)
    time_match = re.search(
        rf"(?P<start>\d{{1,2}}(?::\d{{2}})?\s*(?:[ap]m)?)"
        rf"\s*(?:to|-)\s*"
        rf"(?:(?P<end_day>{DAY_PATTERN})\s+)?"
        rf"(?P<end>\d{{1,2}}(?::\d{{2}})?\s*(?:[ap]m)?)\b",
        piece,
        flags=re.IGNORECASE,
    )
    if not time_match:
        return None

    day_matches = list(
        re.finditer(
            rf"\b({DAY_PATTERN})\b",
            piece[:time_match.start()],
            flags=re.IGNORECASE,
        )
    )
    days = [normalize_day(match.group(1)) for match in day_matches]
    days = [day for day in days if day is not None]
    if not days:
        return None

    explicit_end_day = time_match.group("end_day")
    if explicit_end_day is not None:
        explicit_end_day = normalize_day(explicit_end_day)
        if explicit_end_day is None or len(days) != 1:
            return None

    start_raw = time_match.group("start").strip()
    end_raw = time_match.group("end").strip()
    start_has_meridiem = re.search(r"[ap]m", start_raw, flags=re.IGNORECASE) is not None
    end_has_meridiem = re.search(r"[ap]m", end_raw, flags=re.IGNORECASE) is not None

    if not start_has_meridiem and not end_has_meridiem:
        start_hour = int(re.match(r"\d{1,2}", start_raw).group(0))
        end_hour = int(re.match(r"\d{1,2}", end_raw).group(0))
        if start_hour == end_hour and ask_about_ambiguous:
            confirmation = ask(f"For {piece}, do you mean {start_raw} AM to {end_raw} PM?", "yes")
            if confirmation.lower() in {"yes", "y"}:
                start_raw = f"{start_raw} AM"
                end_raw = f"{end_raw} PM"
            else:
                return None
        else:
            return None

    if not re.search(r"[ap]m", start_raw, flags=re.IGNORECASE) and re.search(r"[ap]m", end_raw, flags=re.IGNORECASE):
        end_meridiem = re.search(r"([ap]m)", end_raw, flags=re.IGNORECASE).group(1).lower()
        start_meridiem = "am" if end_meridiem == "pm" else end_meridiem
        start_raw = f"{start_raw} {start_meridiem}"
    if re.search(r"[ap]m", start_raw, flags=re.IGNORECASE) and not re.search(r"[ap]m", end_raw, flags=re.IGNORECASE):
        start_meridiem = re.search(r"([ap]m)", start_raw, flags=re.IGNORECASE).group(1).lower()
        end_raw = f"{end_raw} {start_meridiem}"

    start = normalize_time(start_raw)
    end = normalize_time(end_raw)
    if start is None or end is None:
        return None

    wraps_to_next_day = time_sort_key(end) <= time_sort_key(start)
    if explicit_end_day == days[0] and wraps_to_next_day:
        return None

    return [
        ShiftRule(
            day=day,
            start=start,
            end=end,
            end_day=(
                explicit_end_day
                if explicit_end_day is not None
                else next_day(day) if wraps_to_next_day else day
            ),
        )
        for day in days
    ]


def split_shift_answer(answer: str) -> list[str]:
    pieces = re.split(r"[,;\n]+", answer)
    return [piece.strip() for piece in pieces if piece.strip()]


def parse_shift_rules(
    answer: str,
    ask_about_ambiguous: bool = True,
) -> tuple[list[ShiftRule], list[str]]:
    rules: list[ShiftRule] = []
    unclear: list[str] = []
    for piece in split_shift_answer(answer):
        parsed = parse_shift_piece(piece, ask_about_ambiguous=ask_about_ambiguous)
        if parsed is None:
            unclear.append(piece)
        else:
            rules.extend(parsed)
    return rules, unclear


def collect_shift_rules() -> list[ShiftRule]:
    while True:
        print()
        print("For shift times, type the days and hours you want.")
        print("Good examples:")
        print("- Monday 6 AM to 6 PM, Tuesday 6 AM to 6 PM")
        print("- Monday 2 PM to 2 AM")
        print("- Saturday 10 AM to 2 PM")
        print("If you type something like Monday 6 to 6, I will ask if you mean 6 AM to 6 PM.")
        answer = ask_required(
            "What shift times do you want the bot to look for?"
        )

        rules, unclear = parse_shift_rules(answer)

        if rules and not unclear:
            validate_rules(rules)
            return rules

        if unclear:
            print("I could not understand this part:")
            for piece in unclear:
                print(f"- {piece}")
        print("Please try again using a day, start time, and end time, like: Monday 6 AM to 6 PM.")


def apply_priorities(rules: list[ShiftRule], answer: str) -> bool:
    days = list(dict.fromkeys(rule.day for rule in rules))
    if not answer:
        return True

    ranked_days = []
    for day_match in re.finditer(rf"\b({DAY_PATTERN})\b", answer, flags=re.IGNORECASE):
        day = normalize_day(day_match.group(1))
        if day in days and day not in ranked_days:
            ranked_days.append(day)

    if not ranked_days:
        return False

    priority_by_day = {
        day: len(ranked_days) - index
        for index, day in enumerate(ranked_days)
    }
    for rule in rules:
        rule.priority = priority_by_day.get(rule.day, 0)
    return True


def assign_priorities(rules: list[ShiftRule]) -> None:
    print()
    print("For day preference, list the best days first.")
    print("Example: Monday Tuesday Wednesday")
    print("If all days are equally good, just press Enter.")
    answer = ask("Which days do you want most?")
    if not apply_priorities(rules, answer):
        print("I did not see any matching days there, so I will leave them all equal.")


def grouped_rules(rules: list[ShiftRule]) -> dict[tuple[str, str], list[ShiftRule]]:
    groups: dict[tuple[str, str], list[ShiftRule]] = {}
    for rule in rules:
        groups.setdefault((rule.start, rule.end), []).append(rule)
    return groups


def job_name(start: str, end: str, total_groups: int) -> str:
    if total_groups == 1:
        return "Preferred shifts"
    return f"{start} to {end}"


def write_config(
    output_path: Path,
    username: str,
    time_to_pick: str,
    reload_session_on: str | None,
    rules: list[ShiftRule],
    time_zone: str = DEFAULT_TIME_ZONE,
) -> None:
    validate_rules(rules)
    try:
        ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {time_zone}") from exc

    groups = grouped_rules(rules)
    lines = [
        "# AtoZ Bot config",
        "manual_login = true",
        f'username = "{toml_escape(username)}"',
        "priority = 0",
    ]
    if reload_session_on:
        lines.append(f'reload_session_on = "{toml_escape(reload_session_on)}"')
    lines.append("")

    for index, ((start, end), grouped) in enumerate(groups.items()):
        if index:
            lines.append("")
        lines.extend([
            "[[jobs]]",
            f'name = "{toml_escape(job_name(start, end, len(groups)))}"',
            f'time_zone = "{toml_escape(time_zone)}"',
            f'time_to_pick = "{toml_escape(time_to_pick)}"',
            'duration = "max"',
        ])
        lines.append("")

        for rule in grouped:
            lines.extend([
                "[[jobs.rules]]",
                f'start = "{rule.day} at {rule.start}"',
                f'end = "{(rule.end_day or rule.day)} at {rule.end}"',
                f"priority = {rule.priority}",
                "",
            ])

    content = "\n".join(lines).rstrip() + "\n"
    tomllib.loads(content)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    output_path.chmod(0o600)


def run_cli(config_dir: Path) -> int:
    print()
    print("AtoZ Bot config builder")
    print("I will ask a few simple questions and make the config file for you.")
    print(f"Configs save to {config_dir}.")
    print()

    name = ask_required("What name should I put on this config?")
    config_path = config_dir / f"{safe_file_name(name)}.toml"
    if config_path.exists():
        overwrite = ask(f"{config_path} already exists. Type yes to replace it, or press Enter to keep it.", "no")
        if overwrite.lower() not in {"yes", "y"}:
            print(f"Keeping existing config at {config_path}.")
            return 0

    while True:
        print()
        print("For the shift drop time, most people can just press Enter to use Friday 5:45 PM.")
        print("Other examples: Thursday 5 PM, Friday 5:45 PM, or now.")
        raw_pick_time = ask(
            "What day and time do shifts drop, or when should the bot start trying to pick? Say now to start right away.",
            "Friday 5:45 PM",
        )
        time_to_pick = parse_pick_time(raw_pick_time)
        if time_to_pick is not None:
            break
        print("Please type it like: Friday 5:45 PM, or type now.")

    rules = collect_shift_rules()
    assign_priorities(rules)

    reload_answer = ask("Do you want the bot to refresh the login session on a certain day? Most people can say no.", "no")
    reload_session_on = None
    if reload_answer.lower() not in {"", "no", "n"}:
        if reload_answer.lower() in {"yes", "y"}:
            reload_session_on = ask("What day should it refresh?", "next sunday")
        else:
            reload_session_on = reload_answer

    write_config(
        output_path=config_path,
        username=name,
        time_to_pick=time_to_pick,
        reload_session_on=reload_session_on,
        rules=rules,
    )
    print(f"Config saved to {config_path}.")
    return 0


def run_gui(config_dir: Path) -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QApplication,
            QComboBox,
            QFormLayout,
            QFrame,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QPushButton,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ImportError:
        print(
            "Config builder GUI is missing PySide6. Run setup-mac.sh again, "
            "or use --cli.",
            file=sys.stderr,
        )
        return 1

    class ConfigBuilderWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.saved = False
            self.setWindowTitle("AtoZ Bot Config Builder")
            self.setMinimumSize(720, 820)
            self.resize(760, 820)

            page = QWidget()
            page.setObjectName("page")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(34, 28, 34, 28)
            layout.setSpacing(16)

            title = QLabel("Build your AtoZ Bot config")
            title.setObjectName("title")
            subtitle = QLabel(
                "Choose when shifts drop and which shifts the bot may pick. "
                "Your schedule is checked before anything is saved."
            )
            subtitle.setObjectName("subtitle")
            subtitle.setWordWrap(True)
            save_location = QLabel(f"Save location: {config_dir}")
            save_location.setObjectName("path")
            save_location.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            save_location.setWordWrap(True)

            layout.addWidget(title)
            layout.addWidget(subtitle)
            layout.addWidget(save_location)

            divider = QFrame()
            divider.setFrameShape(QFrame.Shape.HLine)
            layout.addWidget(divider)

            form = QFormLayout()
            form.setVerticalSpacing(12)
            form.setHorizontalSpacing(18)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

            self.name_input = QLineEdit()
            self.name_input.setPlaceholderText("Example: Night Worker")
            form.addRow("Config name", self.name_input)

            self.time_zone_input = QComboBox()
            self.time_zone_input.addItems(
                [
                    "America/New_York",
                    "America/Chicago",
                    "America/Denver",
                    "America/Los_Angeles",
                    "UTC",
                ]
            )
            form.addRow("Timezone", self.time_zone_input)

            self.pick_time_input = QLineEdit("Friday 5:45 PM")
            self.pick_time_input.setPlaceholderText("Friday 5:45 PM, or now")
            form.addRow("Shift drop time", self.pick_time_input)

            self.shift_input = QTextEdit()
            self.shift_input.setPlaceholderText(
                "Monday 2 PM to Tuesday 2 AM\n"
                "Wednesday 9 AM to 5 PM"
            )
            self.shift_input.setFixedHeight(96)
            form.addRow("Allowed shift windows", self.shift_input)

            self.priority_input = QLineEdit()
            self.priority_input.setPlaceholderText(
                "Optional: Monday Wednesday Friday (best first)"
            )
            form.addRow("Preferred days", self.priority_input)

            self.reload_input = QLineEdit()
            self.reload_input.setPlaceholderText("Optional: next sunday")
            form.addRow("Refresh login", self.reload_input)

            layout.addLayout(form)

            preview_label = QLabel("Validated schedule preview")
            preview_label.setObjectName("sectionTitle")
            self.preview = QPlainTextEdit()
            self.preview.setReadOnly(True)
            self.preview.setFixedHeight(108)
            self.preview.setPlaceholderText(
                "Enter shift windows above to see their normalized times and durations."
            )
            layout.addWidget(preview_label)
            layout.addWidget(self.preview)

            self.status = QLabel("Nothing saved yet.")
            self.status.setObjectName("status")
            self.status.setWordWrap(True)
            layout.addWidget(self.status)

            self.save_button = QPushButton("Validate and save config")
            self.save_button.setObjectName("saveButton")
            self.save_button.setMinimumHeight(46)
            layout.addWidget(self.save_button)

            self.setCentralWidget(page)
            self.setStyleSheet(
                """
                QWidget#page { background: #f4f6f8; color: #172033; }
                QLabel#title { font-size: 25px; font-weight: 700; }
                QLabel#subtitle { color: #4d5b70; font-size: 14px; }
                QLabel#path { color: #276749; font-size: 12px; }
                QLabel#sectionTitle { font-size: 14px; font-weight: 650; }
                QLabel#status { color: #4d5b70; }
                QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
                    background: white;
                    border: 1px solid #c8d0dc;
                    border-radius: 7px;
                    padding: 7px;
                    selection-background-color: #3269d8;
                }
                QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
                    border: 2px solid #3269d8;
                }
                QPushButton#saveButton {
                    background: #2463d4;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-size: 15px;
                    font-weight: 700;
                }
                QPushButton#saveButton:hover { background: #174ea6; }
                QPushButton#saveButton:pressed { background: #123d83; }
                """
            )

            self.shift_input.textChanged.connect(self.update_preview)
            self.priority_input.textChanged.connect(self.update_preview)
            self.save_button.clicked.connect(self.save_config)

        def parsed_rules(self) -> list[ShiftRule]:
            rules, unclear = parse_shift_rules(
                self.shift_input.toPlainText(),
                ask_about_ambiguous=False,
            )
            if unclear:
                raise ValueError(
                    "Could not understand: "
                    + "; ".join(unclear)
                    + ". Include AM or PM, like Monday 2 PM to Tuesday 2 AM."
                )
            validate_rules(rules)
            if not apply_priorities(rules, self.priority_input.text()):
                raise ValueError(
                    "Preferred days must match a day used in the shift windows."
                )
            return rules

        def update_preview(self) -> None:
            if not self.shift_input.toPlainText().strip():
                self.preview.clear()
                return
            try:
                rules = self.parsed_rules()
            except ValueError as exc:
                self.preview.setPlainText(str(exc))
                return
            self.preview.setPlainText(
                "\n".join(format_rule_summary(rule) for rule in rules)
            )

        def save_config(self) -> None:
            try:
                name = self.name_input.text().strip()
                if not name:
                    raise ValueError("Enter a config name.")

                time_to_pick = parse_pick_time(self.pick_time_input.text())
                if time_to_pick is None:
                    raise ValueError(
                        "Shift drop time must look like Friday 5:45 PM, or now."
                    )

                rules = self.parsed_rules()
                reload_value = self.reload_input.text().strip()
                if reload_value.lower() in {"", "no", "n"}:
                    reload_session_on = None
                elif reload_value.lower() in {"yes", "y"}:
                    raise ValueError(
                        "Enter a refresh day such as next sunday, or leave it blank."
                    )
                else:
                    reload_session_on = reload_value
                output_path = config_dir / f"{safe_file_name(name)}.toml"

                if output_path.exists():
                    answer = QMessageBox.question(
                        self,
                        "Replace existing config?",
                        f"{output_path.name} already exists in the app config folder. Replace it?",
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        self.status.setText("Existing config kept. Nothing was changed.")
                        return

                write_config(
                    output_path=output_path,
                    username=name,
                    time_to_pick=time_to_pick,
                    reload_session_on=reload_session_on,
                    rules=rules,
                    time_zone=self.time_zone_input.currentText(),
                )
            except (OSError, ValueError) as exc:
                self.status.setText(f"Not saved: {exc}")
                QMessageBox.warning(self, "Check config details", str(exc))
                return

            self.saved = True
            self.status.setText(f"Saved and validated: {output_path}")
            QMessageBox.information(
                self,
                "Config saved",
                f"Config saved inside the app:\n{output_path}",
            )
            self.close()

    config_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AtoZ Bot Config Builder")
    window = ConfigBuilderWindow()
    window.show()
    app.exec()
    return 0 if window.saved or any(config_dir.glob("*.toml")) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Config folder. Relative paths are resolved inside the app folder.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Use terminal prompts instead of the graphical form.",
    )
    args = parser.parse_args()
    config_dir = resolve_config_dir(args.config_dir)
    if args.cli:
        return run_cli(config_dir)
    return run_gui(config_dir)


if __name__ == "__main__":
    raise SystemExit(main())
