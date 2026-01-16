import datetime
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

import tomli
from dacite import from_dict, Config
from dacite.data import Data
from watchdog.events import FileSystemEventHandler, FileSystemEvent, FileCreatedEvent, FileModifiedEvent, \
    FileDeletedEvent
from watchdog.observers import Observer

from app.models import UserConfig, TwoFAMethod
from utils.time import parse_str_to_time, parse_str_to_time_zone, parse_str_to_timedelta


class Watcher(FileSystemEventHandler):
    """
    Watcher class to monitor a directory for changes.
    """

    def __init__(self, path: Path, on_change: callable, on_create: callable = None, on_delete: callable = None):
        self.__path = path
        self.__observer = Observer()
        self.__on_change = on_change
        self.__on_create = on_create
        self.__on_delete = on_delete

    def on_created(self, event: FileSystemEvent):
        if self.__on_create:
            if isinstance(event, FileCreatedEvent):
                # Check if file is a toml file
                if not event.src_path.endswith(".toml"):
                    return
                logging.debug("Config file created: %s", event.src_path)
                # parse the toml into a user config
                data = load_config(Path(event.src_path))
                if data is None:
                    logging.error("Error parsing config file: %s", event.src_path)
                    return
                self.__on_create(data, event.src_path)

    def on_modified(self, event: FileSystemEvent):
        if self.__on_change:
            if isinstance(event, FileModifiedEvent):
                # Check if file is a toml file
                if not event.src_path.endswith(".toml"):
                    return
                logging.debug("Config file modified: %s", event.src_path)
                # parse the toml into a user config
                data = load_config(Path(event.src_path))
                if data is None:
                    logging.error("Error parsing config file: %s", event.src_path)
                    return
                self.__on_change(data, event.src_path)

    def on_deleted(self, event: FileSystemEvent):
        if self.__on_delete:
            if isinstance(event, FileDeletedEvent):
                # Check if file is a toml file
                if not event.src_path.endswith(".toml"):
                    return
                logging.debug("Config file deleted: %s", event.src_path)
                # parse the toml into a user config
                data = load_config(Path(event.src_path))
                if data is None:
                    logging.error("Error parsing config file: %s", event.src_path)
                    return
                self.__on_delete(data, event.src_path)

    def start(self):
        self.__observer.schedule(self, self.__path, recursive=True)
        self.__observer.start()

    def stop(self):
        self.__observer.stop()
        self.__observer.join()


def load_config(path: Path) -> UserConfig | None:
    """
    Load a config file and return a UserConfig object.
    :param path: The path to the config file.
    :return: A UserConfig object.
    """
    with open(path, "rb") as f:
        try:
            config = Config(type_hooks={tuple[TwoFAMethod, str]: lambda v: (TwoFAMethod(v[0]), v[1]),
                                        datetime.datetime: parse_str_to_time,
                                        datetime.timedelta: parse_str_to_timedelta,
                                        ZoneInfo: parse_str_to_time_zone})
            data = from_dict(
                data_class=UserConfig,
                data=tomli.load(f),
                config=config
            )

            return data
        except Exception as e:
            logging.error("Error parsing config file: %s", e)
            return None
