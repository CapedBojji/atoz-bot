"""
Configuration management: models, loading, and file watching.
"""
import datetime
import logging
import tomli
from dataclasses import dataclass
from datetime import timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, Callable, Optional, List
from zoneinfo import ZoneInfo
from dacite import from_dict, Config
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from utils.time import parse_str_to_time, parse_str_to_time_zone, parse_str_to_timedelta

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration Models
# ============================================================================

class TwoFAMethod(Enum):
    """Two-factor authentication method."""
    OUTLOOK = "OUTLOOK"


class SkillType(Enum):
    """Available skill types."""
    INBOUND = "Inbound"
    SHIP_DOCK = "Ship Dock"
    SORT = "Sort"


@dataclass
class ShiftBlockConfig:
    """Shift time block configuration."""
    start: datetime.datetime
    end: datetime.datetime


@dataclass
class PickShiftApiConfig:
    """Pick shift API configuration."""
    time_to_pick: Optional[datetime.datetime]
    time_zone: Optional[ZoneInfo]
    rules: list[ShiftBlockConfig]
    duration: timedelta = timedelta(hours=1)


@dataclass
class UserConfig:
    """User configuration from TOML file."""
    username: str
    password: str
    two_factor_method: tuple[TwoFAMethod, str]
    pick_shift_api_config: Optional[PickShiftApiConfig]
    reload_session_on: Optional[datetime.datetime]
    priority: int = 0
    skills: Optional[List[SkillType]] = None


def obfuscate_2fa_method(string: str, method: TwoFAMethod) -> str:
    """
    Obfuscate the 2FA method for logging/display.

    :param string: The 2FA method string.
    :param method: The type of the 2FA method.
    :return: The obfuscated 2FA method.
    """
    if method == TwoFAMethod.OUTLOOK:
        return string[0] + '*' * (string.index('@') - 1) + string[string.index('@'):]
    else:
        raise ValueError(f"Unknown 2FA method type: {method}")


# ============================================================================
# Configuration Loader
# ============================================================================

class ConfigLoader:
    """Loads and manages TOML configuration files."""

    def __init__(self, users_dir: Path):
        self.users_dir = users_dir
        self.configs: Dict[str, UserConfig] = {}

    def load_config(self, config_path: Path) -> UserConfig | None:
        """Load a single TOML config file and parse into UserConfig."""
        try:
            with open(config_path, "rb") as f:
                raw_data = tomli.load(f)
                
                # Use dacite to convert TOML dict to UserConfig with type hooks
                config = Config(
                    type_hooks={
                        tuple[TwoFAMethod, str]: lambda v: (TwoFAMethod(v[0]), v[1]),
                        datetime.datetime: parse_str_to_time,
                        datetime.timedelta: parse_str_to_timedelta,
                        ZoneInfo: parse_str_to_time_zone
                    }
                )
                
                user_config = from_dict(
                    data_class=UserConfig,
                    data=raw_data,
                    config=config
                )
                
                logger.info(f"Loaded config: {config_path.name}")
                return user_config
        except Exception as e:
            logger.error(f"Failed to load config {config_path.name}: {e}")
            return None

    def load_all(self) -> Dict[str, UserConfig]:
        """Load all .toml files from the config directory."""
        self.configs.clear()
        
        if not self.users_dir.exists():
            logger.warning(f"Users directory does not exist: {self.users_dir}")
            return self.configs

        for config_file in self.users_dir.glob("*.toml"):
            config_name = config_file.stem
            data = self.load_config(config_file)
            if data:
                self.configs[config_name] = data

        logger.info(f"Loaded {len(self.configs)} config files")
        return self.configs

    def get_config(self, name: str) -> UserConfig | None:
        """Get a specific config by name (without .toml extension)."""
        return self.configs.get(name)


# ============================================================================
# File Watcher
# ============================================================================

class ConfigFileHandler(FileSystemEventHandler):
    """Handles file system events for config files."""

    def __init__(self, users_dir: Path, on_change_callback: Callable[[str, UserConfig | None], None]):
        self.users_dir = users_dir
        self.on_change = on_change_callback
        self.loader = ConfigLoader(users_dir)

    def _is_toml_file(self, path: str) -> bool:
        """Check if the path is a .toml file."""
        return path.endswith(".toml")

    def on_created(self, event: FileSystemEvent):
        """Handle file creation."""
        if event.is_directory or not self._is_toml_file(event.src_path):
            return

        config_path = Path(event.src_path)
        config_name = config_path.stem
        data = self.loader.load_config(config_path)
        
        if data:
            self.loader.configs[config_name] = data
            self.on_change(config_name, data)
            logger.info(f"Config created: {config_name}")

    def on_modified(self, event: FileSystemEvent):
        """Handle file modification."""
        if event.is_directory or not self._is_toml_file(event.src_path):
            return

        config_path = Path(event.src_path)
        config_name = config_path.stem
        data = self.loader.load_config(config_path)
        
        if data:
            self.loader.configs[config_name] = data
            self.on_change(config_name, data)
            logger.info(f"Config modified: {config_name}")

    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion."""
        if event.is_directory or not self._is_toml_file(event.src_path):
            return

        config_path = Path(event.src_path)
        config_name = config_path.stem
        
        if config_name in self.loader.configs:
            del self.loader.configs[config_name]
            self.on_change(config_name, None)
            logger.info(f"Config deleted: {config_name}")


class ConfigWatcher:
    """Watches a directory for config file changes."""

    def __init__(self, users_dir: Path, on_change_callback: Callable[[str, UserConfig | None], None]):
        self.users_dir = users_dir
        self.event_handler = ConfigFileHandler(users_dir, on_change_callback)
        self.observer = Observer()

    def start(self):
        """Start watching the config directory."""
        # Load all configs initially
        self.event_handler.loader.load_all()
        
        # Start file watcher
        self.observer.schedule(self.event_handler, str(self.users_dir), recursive=True)
        self.observer.start()
        logger.info(f"Started watching users directory: {self.users_dir}")

    def stop(self):
        """Stop watching the config directory."""
        self.observer.stop()
        self.observer.join()
        logger.info("Stopped config watcher")

    def get_configs(self) -> Dict[str, UserConfig]:
        """Get all currently loaded configs."""
        return self.event_handler.loader.configs


# ============================================================================
# Settings Models and Loader
# ============================================================================

@dataclass
class Settings:
    """Global application settings stored in ~/.config/atoz/settings.toml."""
    o365_client_id: Optional[str] = None
    o365_client_secret: Optional[str] = None


class SettingsLoader:
    """Loads global settings from settings.toml."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.settings_path = base_dir / "settings.toml"
        self.settings: Optional[Settings] = None

    def load(self) -> Optional[Settings]:
        if not self.settings_path.exists():
            logger.warning(f"Settings file not found: {self.settings_path}")
            self.settings = None
            return None
        try:
            with open(self.settings_path, "rb") as f:
                raw = tomli.load(f)
                # Support either top-level keys or nested [o365] table
                o365_id = raw.get("o365_client_id")
                o365_secret = raw.get("o365_client_secret")
                if not o365_id or not o365_secret:
                    o365_tbl = raw.get("o365", {})
                    o365_id = o365_id or o365_tbl.get("client_id")
                    o365_secret = o365_secret or o365_tbl.get("client_secret")
                self.settings = Settings(
                    o365_client_id=o365_id,
                    o365_client_secret=o365_secret,
                )
                logger.info("Loaded settings.toml")
                return self.settings
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            self.settings = None
            return None


class SettingsFileHandler(FileSystemEventHandler):
    """Watch for changes to settings.toml in base directory."""

    def __init__(self, base_dir: Path, on_change: Callable[[Optional[Settings]], None]):
        self.base_dir = base_dir
        self.loader = SettingsLoader(base_dir)
        self.on_change = on_change

    def on_any_event(self, event: FileSystemEvent):
        # React only to the settings.toml file
        if event.is_directory:
            return
        if not str(event.src_path).endswith("settings.toml"):
            return
        settings = self.loader.load()
        self.on_change(settings)


class SettingsWatcher:
    """Directory watcher for base_dir to capture settings.toml changes."""

    def __init__(self, base_dir: Path, on_change: Callable[[Optional[Settings]], None]):
        self.base_dir = base_dir
        self.event_handler = SettingsFileHandler(base_dir, on_change)
        self.observer = Observer()

    def start(self):
        # Initial load
        self.event_handler.loader.load()
        # Watch base dir for file changes
        self.observer.schedule(self.event_handler, str(self.base_dir), recursive=False)
        self.observer.start()
        logger.info(f"Started watching settings in: {self.base_dir}")

    def stop(self):
        self.observer.stop()
        self.observer.join()
        logger.info("Stopped settings watcher")

    def get_settings(self) -> Optional[Settings]:
        return self.event_handler.loader.settings


# ============================================================================
# Atoz Config Manager (users + settings)
# ============================================================================

class AtozConfig:
    """
    High-level manager for ~/.config/atoz structure:
      - users/** .toml files parsed into UserConfig
      - settings.toml parsed into Settings
    """

    def __init__(
        self,
        base_dir: Path,
        on_user_change: Callable[[str, UserConfig | None], None],
        on_settings_change: Callable[[Optional[Settings]], None],
    ):
        self.base_dir = base_dir
        self.users_dir = base_dir / "users"
        # Ensure directories exist
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.users_watcher = ConfigWatcher(self.users_dir, on_user_change)
        self.settings_watcher = SettingsWatcher(self.base_dir, on_settings_change)

    def start(self):
        self.users_watcher.start()
        self.settings_watcher.start()

    def stop(self):
        self.users_watcher.stop()
        self.settings_watcher.stop()

    def get_users(self) -> Dict[str, UserConfig]:
        return self.users_watcher.get_configs()

    def get_settings(self) -> Optional[Settings]:
        return self.settings_watcher.get_settings()
