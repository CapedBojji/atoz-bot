import logging
import os
import time
import asyncio
from asyncio import TaskGroup
from dataclasses import dataclass
from datetime import datetime, timezone

from httpx import AsyncClient

from app.models import JobConfig
from app.session import JobSession
from app.session import UserSession
from utils.nanoid import nanoid
from utils.time import split_time_block

__pick_time_block_days = int(os.getenv("PICK_TIME_BLOCK_DAYS", "14"))


@dataclass
class JobRunnerContext:
    client: AsyncClient
    employee_id: int
    job: JobConfig
    username: str
    job_index: int


def __job_label(context: JobRunnerContext) -> str:
    job_name = (context.job.name or "").strip()
    if job_name:
        return f"{context.username} job #{context.job_index} [{job_name}]"
    return f"{context.username} job #{context.job_index}"


def __format_time(value: datetime | None, fallback_tz=timezone.utc) -> str:
    if value is None:
        return "immediate"
    if value.tzinfo is None:
        value = value.replace(tzinfo=fallback_tz)
    return value.isoformat()


def __can_pick_shift(job: JobConfig) -> bool:
    """
    Check if the job is currently in its picking window.
    :param job: The job configuration to check.
    :return: True if the user can pick a shift, False otherwise.
    """
    time_to_pick = job.time_to_pick
    time_to_run = job.duration
    if time_to_pick is None:
        return True
    time_to_pick = time_to_pick.replace(tzinfo=job.time_zone or timezone.utc)
    if time.time() < time_to_pick.timestamp():
        return False
    try:
        if (time_to_pick + time_to_run).timestamp() > time.time():
            return True
    except OverflowError:
        return True
    return False


async def __get_shifts(context: JobRunnerContext, start_time: str, end_time: str) -> list:
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
    url = f"https://atoz-api-us-east-1.amazon.work/graphql?{context.employee_id}"
    response = await context.client.post(url, headers=headers, json=data)

    async def handle_response():
        if response.status_code != 200:
            return []

        response_data = response.json()
        if not __validate_response_data(response_data):
            return []

        shift_count = __get_shift_count(response_data)
        if shift_count == 0:
            return []

        return __filter_out_ineligible_shifts(response_data["data"]["shiftOpportunities"]["opportunities"])

    return await handle_response()


def __validate_response_data(response: dict) -> bool:
    """
    Validate the response data from the API.
    :param response: The response data to validate.
    :return: True if the response data is valid, False otherwise.
    """
    if "data" not in response:
        return False
    if "shiftOpportunities" not in response["data"]:
        return False
    if "opportunities" not in response["data"]["shiftOpportunities"]:
        return False
    if "counts" not in response["data"]["shiftOpportunities"]:
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


def __shift_sort_key(shift: dict) -> tuple[datetime, datetime, str]:
    start_time, end_time = __get_shift_time_block(shift)

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)

    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    else:
        end_time = end_time.astimezone(timezone.utc)

    return start_time, end_time, str(shift.get("id", ""))


def __get_shift_rule_priority(
    shift: dict,
    rules: list[tuple[datetime, datetime, int]],
) -> int | None:
    start_time, end_time = __get_shift_time_block(shift)
    best_priority: int | None = None

    for rule_start, rule_end, rule_priority in rules:
        if start_time >= rule_start and end_time <= rule_end:
            if best_priority is None or rule_priority > best_priority:
                best_priority = rule_priority

    return best_priority


async def __pick_shift(context: JobRunnerContext, shift: dict) -> bool:
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
    url = f"https://atoz-api-us-east-1.amazon.work/graphql?{context.employee_id}"

    started_at = time.perf_counter()
    response = await context.client.post(url, headers=headers, json=data)
    latency_ms = (time.perf_counter() - started_at) * 1000

    async def handle_response():
        if response.status_code != 200:
            return False

        try:
            response_data = response.json()
        except ValueError:
            return False

        if not __validate_pick_shift_response(response_data, shift):
            return False

        start_time, end_time = __get_shift_time_block(shift)
        logging.info(
            "%s picked shift id=%s start=%s end=%s latency_ms=%.0f",
            __job_label(context),
            shift["id"],
            start_time.isoformat(),
            end_time.isoformat(),
            latency_ms,
        )

        return True

    return await handle_response()


def __validate_pick_shift_response(response: dict, shift: dict) -> bool:
    """
    Validate the response data from the pick shift API.
    :param response: The response data to validate.
    :param shift: The shift that was picked.
    :return: True if the response data is valid, False otherwise.
    """
    if not isinstance(response, dict):
        return False

    data = response.get("data")
    if not isinstance(data, dict):
        return False
    if "addShift" not in data:
        return False

    return data["addShift"] == shift["id"]


async def __run_job(session: UserSession, job_session: JobSession, job: JobConfig, job_index: int) -> None:
    context = JobRunnerContext(
        client=job_session.client,
        employee_id=job_session.employee_id,
        job=job,
        username=session.get_config().username,
        job_index=job_index,
    )

    rules = [
        (
            rule.start.replace(tzinfo=job.time_zone or timezone.utc),
            rule.end.replace(tzinfo=job.time_zone or timezone.utc),
            int(getattr(rule, "priority", 0)),
        )
        for rule in job.rules
    ]
    if not rules:
        return

    min_start = min([rule[0] for rule in rules])
    max_end = max([rule[1] for rule in rules])
    time_blocks = split_time_block(min_start, max_end, __pick_time_block_days)

    # Start pick attempts as soon as each search block returns,
    # instead of waiting for all search requests to complete.
    fetch_tasks = []
    for time_block in time_blocks:
        start_time_str = time_block[0].astimezone(timezone.utc).isoformat()
        end_time_str = time_block[1].astimezone(timezone.utc).isoformat()
        fetch_tasks.append(asyncio.create_task(__get_shifts(context, start_time_str, end_time_str)))

    seen_shift_ids: set[str] = set()
    async with TaskGroup() as group:
        for completed in asyncio.as_completed(fetch_tasks):
            shifts = await completed
            for shift in shifts:
                shift_id = str(shift["id"])
                if shift_id in seen_shift_ids:
                    continue

                priority = __get_shift_rule_priority(shift, rules)
                if priority is None:
                    continue

                seen_shift_ids.add(shift_id)
                group.create_task(__pick_shift(context, shift))


async def run(session: UserSession, manual_login: bool = False):
    """
    Run the pick shift process for the given session.
    :param session: The user session to run the pick shift process for.
    :param manual_login: Use manual browser login if the session needs authentication.
    """
    jobs = session.get_config().jobs or []
    if not jobs:
        return

    job_session = await session.create_job_session(manual_login=manual_login)

    async with TaskGroup() as group:
        for job_index, job in enumerate(jobs, start=1):
            if not __can_pick_shift(job):
                continue
            group.create_task(__run_job(session, job_session, job, job_index))
