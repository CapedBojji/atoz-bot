#!/usr/bin/env python3
import argparse
import re
from dataclasses import dataclass
from pathlib import Path


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
    return f"{day} after sunday at {time_value}"


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


def next_day(day: str) -> str:
    return DAY_ORDER[(DAY_ORDER.index(day) + 1) % len(DAY_ORDER)]


def maybe_expand_time_range(text: str) -> str:
    return text


def parse_shift_piece(piece: str) -> list[ShiftRule] | None:
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
        if start_hour == end_hour:
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

        rules: list[ShiftRule] = []
        unclear: list[str] = []
        for piece in split_shift_answer(answer):
            parsed = parse_shift_piece(piece)
            if parsed is None:
                unclear.append(piece)
            else:
                rules.extend(parsed)

        if rules and not unclear:
            return rules

        if unclear:
            print("I could not understand this part:")
            for piece in unclear:
                print(f"- {piece}")
        print("Please try again using a day, start time, and end time, like: Monday 6 AM to 6 PM.")


def assign_priorities(rules: list[ShiftRule]) -> None:
    days = []
    for rule in rules:
        if rule.day not in days:
            days.append(rule.day)

    print()
    print("For day preference, list the best days first.")
    print("Example: Monday Tuesday Wednesday")
    print("If all days are equally good, just press Enter.")
    answer = ask("Which days do you want most?")
    if not answer:
        return

    ranked_days = []
    for day_match in re.finditer(rf"\b({DAY_PATTERN})\b", answer, flags=re.IGNORECASE):
        day = normalize_day(day_match.group(1))
        if day in days and day not in ranked_days:
            ranked_days.append(day)

    if not ranked_days:
        print("I did not see any matching days there, so I will leave them all equal.")
        return

    priority_by_day = {
        day: len(ranked_days) - index
        for index, day in enumerate(ranked_days)
    }
    for rule in rules:
        rule.priority = priority_by_day.get(rule.day, 0)


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
) -> None:
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
            'time_zone = "America/New_York"',
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    output_path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    args = parser.parse_args()

    print()
    print("AtoZ Bot config builder")
    print("I will ask a few simple questions and make the config file for you.")
    print()

    name = ask_required("What name should I put on this config?")
    config_path = args.config_dir / f"{safe_file_name(name)}.toml"
    if config_path.exists():
        overwrite = ask(f"{config_path} already exists. Type yes to replace it, or press Enter to keep it.", "no")
        if overwrite.lower() not in {"yes", "y"}:
            print(f"Keeping existing config at {config_path}.")
            return

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


if __name__ == "__main__":
    main()
