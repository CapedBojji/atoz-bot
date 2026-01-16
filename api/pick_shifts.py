import logging
import os
import time
from asyncio import TaskGroup, create_task
from datetime import datetime, timezone

from app.session import UserSession
from utils.nanoid import nanoid
from utils.time import split_time_block, time_block_in_blocks

__pick_shift_window = int(os.getenv("PICK_SHIFT_WINDOW", "120"))


def __can_pick_shift(session: UserSession) -> bool:
    """
    Check if the user can pick a shift.
    :param session: The user session to check.
    :return: True if the user can pick a shift, False otherwise.
    """
    time_to_pick = session.get_config().pick_shift_api_config.time_to_pick.replace(tzinfo=session.get_config().pick_shift_api_config.time_zone)
    time_to_run = session.get_config().pick_shift_api_config.duration
    if time_to_pick is None:
        return True
    if time.time() < time_to_pick.timestamp():
        return False
    try:
        if (time_to_pick + time_to_run).timestamp() > time.time():
            return True
    except OverflowError:
        return True
    return False


async def __get_shifts(session: UserSession, start_time: str, end_time: str) -> list:
    data = {
        "operationName": "FindShiftsPage",
        "query": r"""
query FindShiftsPage(
  $shiftOpportunitiesTimeRange: DateTimeRangeInput!
  $opportunitiesOpportunityTypes: TypeFilter
  $countTypes: TypeFilter
) {
  shiftOpportunities(timeRange: $shiftOpportunitiesTimeRange) {
    opportunities(opportunityTypes: $opportunitiesOpportunityTypes) {
      eligibility {
        isEligible
      }
      id
      skill
      unavailability {
        reasons
      }
      shift {
        duration {
          value
        }
        id
        timeRange {
          end
          start
        }
      }
    }
    counts(countTypes: $countTypes) {
      count
    }
  }
}
        """,
        "variables": {
            "shiftOpportunitiesTimeRange": {
                "start": start_time,
                "end": end_time
            },
            "opportunitiesOpportunityTypes": {
                "types": ["ADD"]
            },
            "countTypes": {
                "types": ["ADD"]
            }
        }
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
        "x-atoz-client-id": "SCHEDULE_MANAGEMENT_SERVICE",
        "x-atoz-client-request-id": nanoid()
    }
    url = f"https://atoz-api-us-east-1.amazon.work/graphql?{await session.get_employee_id()}"
    response = await session.get_client().post(url, headers=headers, json=data)

    async def handle_response():
        if response.status_code != 200:
            logging.error("Failed to get shifts: %s", response.text)
            return []

        response_data = response.json()
        if not __validate_response_data(response_data):
            logging.error("Invalid response data: %s", response_data)
            return []

        if __get_shift_count(response_data) == 0:
            logging.debug(f"No shifts available for {start_time} to {end_time}")
            return []

        return __filter_out_ineligible_shifts(response_data["data"]["shiftOpportunities"]["opportunities"])

    return await create_task(handle_response())


def __validate_response_data(response: dict) -> bool:
    """
    Validate the response data from the API.
    :param response: The response data to validate.
    :return: True if the response data is valid, False otherwise.
    """
    if not "data" in response and "shiftOpportunities" in response["data"]:
        return False
    if not "opportunities" in response["data"]["shiftOpportunities"]:
        return False
    if not "counts" in response["data"]["shiftOpportunities"]:
        return False
    return True


def __get_shift_count(response: dict) -> int:
    """
    Get the count of shifts from the response data.
    :param response: The response data to get the count from.
    :return: The count of shifts.
    """
    if len(response["data"]["shiftOpportunities"]["counts"]) == 0:
        return 0
    counts = response["data"]["shiftOpportunities"]["counts"][0]
    if "count" in counts:
        return counts["count"]
    return 0


def __filter_out_ineligible_shifts(shifts: list) -> list:
    """
    Filter out ineligible shifts from the list of shifts.
    :param shifts: The list of shifts to filter.
    :return: A list of eligible shifts.
    """
    eligible_shifts = []
    for shift in shifts:
        if shift["eligibility"]["isEligible"] and not shift["unavailability"]:
            eligible_shifts.append(shift)
        else:
            logging.debug("Shift is not eligible: %s", shift)
    return eligible_shifts


def __get_shift_time_block(shift: dict) -> tuple[datetime, datetime]:
    """
    Get the start and end time of the shift.
    :param shift: The shift to get the time block for.
    :return: A tuple containing the start and end time of the shift.
    """
    start_time = datetime.fromisoformat(shift["shift"]["timeRange"]["start"])
    end_time = datetime.fromisoformat(shift["shift"]["timeRange"]["end"])
    return start_time, end_time


async def __pick_shift(session: UserSession, shift: dict) -> bool:
    """
    Pick the given shift.
    :param session: The user session to pick the shift for.
    :param shift: The shift to pick.
    """
    # Build the request
    data = {
        "operationName": "AddShift",
        "query": r"""
mutation AddShift($shiftOpportunityId: AddShiftInput!) {
  addShift(input: $shiftOpportunityId)
}
        """,
        "variables": {
            "shiftOpportunityId": {
                "shiftOpportunityId": shift["id"]
            }
        }
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
        "x-atoz-client-id": "SCHEDULE_MANAGEMENT_SERVICE",
        "x-atoz-client-request-id": nanoid()
    }
    url = f"https://atoz-api-us-east-1.amazon.work/graphql?{await session.get_employee_id()}"

    response = await session.get_client().post(url, headers=headers, json=data)

    async def handle_response():
        if response.status_code != 200:
            logging.error("Failed to pick shift: %s", response.text)
            return False

        response_data = response.json()
        if not __validate_pick_shift_response(response_data, shift):
            logging.error("Invalid response data: %s", response_data)
            return False

        return True

    return await create_task(handle_response())


def __validate_pick_shift_response(response: dict, shift: dict) -> bool:
    """
    Validate the response data from the pick shift API.
    :param response: The response data to validate.
    :param shift: The shift that was picked.
    :return: True if the response data is valid, False otherwise.
    """
    if not "data" in response and not "addShift" in response["data"]:
        return False

    return response["data"]["addShift"] == shift["id"]


async def run(session: UserSession):
    """
    Run the pick shift process for the given session.
    :param session: The user session to run the pick shift process for.
    """
    if not __can_pick_shift(session):
        logging.debug("Not time to pick shift yet")
        return

    logging.debug(f"Running pick shift for {session.get_config().username}")

    rules = session.get_config().pick_shift_api_config.rules
    # Convert rules to list tuple of datetime objects
    rules = [(rule.start, rule.end) for rule in rules]
    # Update the rules to use the user's timezone
    rules = [(rule[0].replace(tzinfo=session.get_config().pick_shift_api_config.time_zone or timezone.utc),
              rule[1].replace(tzinfo=session.get_config().pick_shift_api_config.time_zone or timezone.utc)) for rule in rules]
    # Get the minimum start time and maximum end time from the rules
    min_start = min([rule[0] for rule in rules])
    max_end = max([rule[1] for rule in rules])
    # Split into time blocks of max 7 days
    time_blocks = split_time_block(min_start, max_end, 7)

    # Get the shifts for each time block
    all_shifts = []
    results = []
    async with TaskGroup() as group:
        for time_block in time_blocks:
            start_time_str = time_block[0].astimezone(timezone.utc).isoformat()
            end_time_str = time_block[1].astimezone(timezone.utc).isoformat()
            results.append(group.create_task(__get_shifts(session, start_time_str, end_time_str)))

    for result in results:
        all_shifts += result.result()

    # Remove duplicates
    all_shifts = {shift["id"]: shift for shift in all_shifts}.values()

    # Process each shift
    async with TaskGroup() as group:
        for shift in all_shifts:
            start_time, end_time = __get_shift_time_block(shift)
            # Check if the shift is within any of the rules
            if time_block_in_blocks((start_time, end_time), rules):
                logging.debug(f"Picking shift: {shift}")
                group.create_task(__pick_shift(session, shift))

