from datetime import datetime, timezone, timedelta
import parsedatetime


def parse_str_to_time(string: str, timezone = timezone.utc) -> datetime:
    """
    Parse a string to a datetime object.

    :param string: The string to parse.
    :param timezone: The timezone to use for the datetime object.
    :return: A datetime object.
    """
    cal = parsedatetime.Calendar()
    time, _ = cal.parse(string)
    return datetime(*time[:6], tzinfo=timezone)

def parse_str_to_timedelta(string: str) -> timedelta:
    """
    Parse a string to a timedelta object.

    :param string: The string to parse.
    :return: A timedelta object.
    """
    if string == "max":
        return timedelta.max
    elif string == "min":
        return timedelta.min
    else:
        time_parts = string.split(":")
        if len(time_parts) == 3:
            return timedelta(hours=int(time_parts[0]), minutes=int(time_parts[1]), seconds=int(time_parts[2]))
        elif len(time_parts) == 2:
            return timedelta(hours=int(time_parts[0]), minutes=int(time_parts[1]))
        elif len(time_parts) == 1:
            return timedelta(minutes=int(time_parts[0]))
        else:
            raise ValueError(f"Invalid time format: {string}")

def split_time_block(start: datetime, end: datetime, offset: int) -> list[tuple[datetime, datetime]]:
    """
    Split a time block into smaller blocks.

    :param start: The start time of the block.
    :param end: The end time of the block.
    :param offset: The offset to split the block by (in minutes).
    :return: A list of tuples containing the start and end time of each block.
    """
    # Assert that start is less than end
    if start > end:
        raise ValueError("Start time must be less than end time.")
    # Return start and end time if the block is less than the offset
    if (end - start) < timedelta(days=offset):
        return [(start, end)]
    blocks = []
    cursor = start
    while cursor < end:
        block_end_time = cursor + timedelta(days=offset)
        if block_end_time > end:
            block_end_time = end
        blocks.append((cursor, block_end_time))
        cursor = block_end_time
    return blocks

def time_block_in_blocks(
    time_block: tuple[datetime, datetime], blocks: list[tuple[datetime, datetime]]
) -> bool:
    """
    Check if a time block is within the given blocks.

    :param time_block: The time block to check.
    :param blocks: The list of blocks to check against.
    :return: True if the time block is within the blocks, False otherwise.
    """
    for block in blocks:
        if time_block[0] >= block[0] and time_block[1] <= block[1]:
            return True
    return False

from zoneinfo import ZoneInfo

# map informal names to canonical IANA zones
COMMON_TZ_ALIASES = {
    "utc": "UTC",
    "est": "America/New_York",
    "edt": "America/New_York",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "new york": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "tokyo": "Asia/Tokyo",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "dubai": "Asia/Dubai",
}

def parse_str_to_time_zone(tz_str: str) -> ZoneInfo:
    tz_key = tz_str.strip().lower()
    resolved = COMMON_TZ_ALIASES.get(tz_key, tz_str)
    try:
        return ZoneInfo(resolved)
    except Exception:
        raise ValueError(f"Unknown timezone: '{tz_str}' (resolved to '{resolved}')")

def is_time(t: datetime, error_margin: timedelta = timedelta(minutes=5)) -> bool:
    """
    Check if the given time is within the error margin of the current time.

    :param t: The time to check.
    :param error_margin: The error margin to use.
    :return: True if the time is within the error margin, False otherwise.
    """
    now = datetime.now(tz=timezone.utc)
    return now - error_margin <= t <= now + error_margin