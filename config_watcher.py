"""
Configuration file watcher that monitors a directory for TOML config files.
"""
import datetime
import logging
import tomli
from pathlib import Path
from typing import Dict, Any, Callable
from zoneinfo import ZoneInfo
from dacite import from_dict, Config
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from app.models import UserConfig, TwoFAMethod
from time import parse_str_to_time, parse_str_to_time_zone, parse_str_to_timedelta

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and manages TOML configuration files."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
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
        
        if not self.config_dir.exists():
            logger.warning(f"Config directory does not exist: {self.config_dir}")
            return self.configs

        for config_file in self.config_dir.glob("*.toml"):
            config_name = config_file.stem
            data = self.load_config(config_file)
            if data:
                self.configs[config_name] = data

        logger.info(f"Loaded {len(self.configs)} config files")
        return self.configs

    def get_config(self, name: str) -> UserConfig | None:
        """Get a specific config by name (without .toml extension)."""
        return self.configs.get(name)


class ConfigFileHandler(FileSystemEventHandler):
    """Handles file system events for config files."""

    def __init__(self, config_dir: Path, on_change_callback: Callable[[str, UserConfig | None], None]):
        self.config_dir = config_dir
        self.on_change = on_change_callback
        self.loader = ConfigLoader(config_dir)

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

    def __init__(self, config_dir: Path, on_change_callback: Callable[[str, UserConfig | None], None]):
        self.config_dir = config_dir
        self.event_handler = ConfigFileHandler(config_dir, on_change_callback)
        self.observer = Observer()

    def start(self):
        """Start watching the config directory."""
        # Load all configs initially
        self.event_handler.loader.load_all()
        
        # Start file watcher
        self.observer.schedule(self.event_handler, str(self.config_dir), recursive=False)
        self.observer.start()
        logger.info(f"Started watching config directory: {self.config_dir}")

    def stop(self):
        """Stop watching the config directory."""
        self.observer.stop()
        self.observer.join()
        logger.info("Stopped config watcher")

    def get_configs(self) -> Dict[str, UserConfig]:
        """Get all currently loaded configs."""
        return self.event_handler.loader.configs
