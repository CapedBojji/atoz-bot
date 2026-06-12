from dataclasses import dataclass
from datetime import timezone, datetime, timedelta
from enum import Enum
from typing import TypedDict, Tuple, Optional, List
from zoneinfo import ZoneInfo


class TwoFAMethod(Enum):
    OUTLOOK = "OUTLOOK"
    GMAIL = "GMAIL"

class SkillType(Enum):
    INBOUND = "Inbound"
    SHIP_DOCK = "Ship Dock"
    SORT = "Sort"


@dataclass
class GmailConfig:
    app_password: Optional[str] = None

@dataclass
class ShiftBlockConfig:
    start: datetime
    end: datetime
    priority: int = 0

@dataclass
class JobConfig:
    time_to_pick: Optional[datetime]
    time_zone: Optional[ZoneInfo]
    rules: list[ShiftBlockConfig]
    duration: timedelta = timedelta(hours=1)
    name: Optional[str] = None

@dataclass
class UserConfig:
    username: Optional[str] = None
    password: Optional[str] = None
    two_factor_method: Optional[tuple[TwoFAMethod, str]] = None
    manual_login: bool = False
    reload_session_on: Optional[datetime] = None
    jobs: Optional[List[JobConfig]] = None
    gmail: Optional[GmailConfig] = None
    priority: int = 0
    skills: Optional[List[SkillType]] = None




def obfuscate_2fa_method(string: str, method: TwoFAMethod) -> str:
    """
    Obfuscate the 2FA method.

    :param string: The 2FA method string.
    :param method: The type of the 2FA method.
    :return: The obfuscated 2FA method.
    """
    if method in (TwoFAMethod.OUTLOOK, TwoFAMethod.GMAIL):
        return string[0] + '*' * (string.index('@') - 1) + string[string.index('@'):]
    raise ValueError(f"Unknown 2FA method type: {method}")
