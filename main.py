import argparse
import asyncio
import logging
import sys
import time
from asyncio import TaskGroup
from pathlib import Path


from api import pick_shifts
from app.models import UserConfig
from app.session import get_user_session, delete_user_session, create_user_session, authenticate_all_sessions
from utils.logger import setup_logging
from utils.watcher import Watcher, load_config


import dotenv

def on_user_config_change(data: UserConfig, path: str) -> None:
    session = get_user_session(data, Path(path))
    session.update_config(data)


def on_user_config_delete(data: UserConfig, path: str) -> None:
    session = get_user_session(data, Path(path))
    delete_user_session(session)


def on_user_config_create(data: UserConfig, path: str) -> None:
    create_user_session(data, Path(path))


async def start(config_dir: Path, log_file: Path | None = None, debug: bool = False, show_browser=False, single_user=None) -> None:
    """
    Start the application with the given configuration directory.
    :param config_dir: The path to the configuration directory.
    :param log_file: The path to the log file. If None, logs will be printed to stdout.
    :param debug: Enable debug mode.
    :param show_browser: Show the browser window.
    :param single_user: If provided, only this user's config will be used.
    """
    # Initialize the logger
    setup_logging(log_file, level=logging.DEBUG if debug else logging.INFO)
    logging.info("""
        Application started with the following parameters:
        - config_dir: %s
        - log_file: %s
        - debug: %s
    """, config_dir, log_file, debug)
    # Initialize the directory watcher
    watcher = Watcher(config_dir, on_user_config_change, on_user_config_create, on_user_config_delete)
    watcher.start()
    # Load existing user configurations
    load_existing_user_configs(config_dir)
    # Main loop to keep the application running
    try:
        while True:
            try:
                time.sleep(3)
                authenticated_sessions = await authenticate_all_sessions(show_browser, single_user)
                authenticated_sessions.sort(key = lambda x: x.get_config().priority, reverse=True)
                async with TaskGroup() as group:
                    for session in authenticated_sessions:
                        group.create_task(pick_shifts.run(session))
            except Exception as e:
                logging.error(f"Error in TaskGroup: {e}")
    except KeyboardInterrupt:
        watcher.stop()
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        watcher.stop()
        sys.exit(1)


def load_existing_user_configs(config_dir: Path) -> None:
    configs = config_dir.rglob("*.toml")
    for config in configs:
        logging.debug(f"Loading existing config file: {config}")
        data = load_config(config)
        if data:
            create_user_session(data, config)
        else:
            logging.error("Error parsing config file: %s", config)


def dir_path(path: str) -> Path:
    """
    Custom type for argparse to check if the given path is a directory.
    :param path: The path to check.
    :return: The path as a Path object.
    """
    p = Path(path)
    if not p.is_dir():
        raise argparse.ArgumentTypeError(f"{path} is not a valid directory.")
    return p


if __name__ == "__main__":
    dotenv.load_dotenv()
    parser = argparse.ArgumentParser(
        prog="AtoZ Client",
        description="AtoZ Client is a command line tool for AtoZ.",
    )
    parser.add_argument(
        "--config_dir",
        "-cd",
        type=dir_path,
        # required=True,
        default=Path.cwd() / "config",
        help="Path to the configuration directory.",
    )
    parser.add_argument(
        "--show_browser",
        "-sb",
        default=False,
        action="store_true",
        help="Show the browser window.",
    )
    parser.add_argument(
        "--single_user",
        "-su",
        default=None,
        type=str,
        help="Run the application for a single user. If provided, only this user's config will be used.",
    )
    parser.add_argument(
        "--log_file",
        "-lf",
        type=Path,
        default=Path.cwd() / "app.log",
        help="Path to the log file. If not provided, logs will be printed to stdout.",
    )
    parser.add_argument(
        "--debug",
        "-d",
        default=False,
        action="store_true",
        help="Enable debug mode.",
    )
    args = parser.parse_args()
    logging.debug(f"Running with arguments: {args}")
    asyncio.run(start(args.config_dir, args.log_file, args.debug, args.show_browser, args.single_user))
