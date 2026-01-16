from dataclasses import dataclass
from datetime import timezone, datetime, timedelta
from enum import Enum
from typing import TypedDict, Tuple, Optional, List
from zoneinfo import ZoneInfo


class TwoFAMethod(Enum):
    OUTLOOK = "OUTLOOK"

class SkillType(Enum):
    INBOUND = "Inbound"
    SHIP_DOCK = "Ship Dock"
    SORT = "Sort"

@dataclass
class ShiftBlockConfig:
    start: datetime
    end: datetime

@dataclass
class PickShiftApiConfig:
    time_to_pick: Optional[datetime]
    time_zone: Optional[ZoneInfo]
    rules: list[ShiftBlockConfig]
    duration: timedelta = timedelta(hours=1)

@dataclass
class UserConfig:
    username: str
    password: str
    two_factor_method: tuple[TwoFAMethod, str]
    pick_shift_api_config: Optional[PickShiftApiConfig]
    reload_session_on: Optional[datetime]
    priority: int = 0
    skills: Optional[List[SkillType]] = None




def obfuscate_2fa_method(string: str, method: TwoFAMethod) -> str:
    """
    Obfuscate the 2FA method.

    :param string: The 2FA method string.
    :param method: The type of the 2FA method.
    :return: The obfuscated 2FA method.
    """
    if method == TwoFAMethod.OUTLOOK:
        return string[0] + '*' * (string.index('@') - 1) + string[string.index('@'):]
    else:
        raise ValueError(f"Unknown 2FA method type: {method}")
