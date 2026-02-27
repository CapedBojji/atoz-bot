import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from asyncio import TaskGroup
from pathlib import Path


from api import pick_shifts
from app.models import UserConfig
from app.session import get_user_session, delete_user_session, create_user_session, authenticate_all_sessions, close_all_sessions
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


async def start(
    config_dir: Path,
    log_file: Path | None = None,
    debug: bool = False,
    show_browser: bool = False,
    single_user: str | None = None,
    shutdown_after_minutes: float | None = None,
) -> None:
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
    stop_event = asyncio.Event()

    def request_shutdown(reason: str) -> None:
        if not stop_event.is_set():
            logging.info("Shutdown requested (%s)", reason)
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown, sig.name)
        except (NotImplementedError, RuntimeError):
            # Some platforms/event loops don't support signal handlers.
            pass

    if shutdown_after_minutes is None:
        shutdown_after_minutes_env = os.getenv("SHUTDOWN_AFTER_MINUTES")
        if shutdown_after_minutes_env:
            try:
                shutdown_after_minutes = float(shutdown_after_minutes_env)
            except ValueError:
                logging.warning(
                    "Invalid SHUTDOWN_AFTER_MINUTES=%r (expected a number); ignoring",
                    shutdown_after_minutes_env,
                )

    shutdown_task: asyncio.Task[None] | None = None
    if shutdown_after_minutes is not None and shutdown_after_minutes > 0:
        async def _shutdown_timer() -> None:
            await asyncio.sleep(shutdown_after_minutes * 60)
            request_shutdown(f"timer:{shutdown_after_minutes}m")

        shutdown_task = asyncio.create_task(_shutdown_timer(), name="shutdown_timer")

    try:
        while not stop_event.is_set():
            try:
                await asyncio.sleep(3)
                authenticated_sessions = await authenticate_all_sessions(show_browser, single_user)
                authenticated_sessions.sort(key = lambda x: x.get_config().priority, reverse=True)
                async with TaskGroup() as group:
                    for session in authenticated_sessions:
                        group.create_task(pick_shifts.run(session))
            except Exception as e:
                logging.error(f"Error in TaskGroup: {e}")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        raise
    finally:
        try:
            if shutdown_task:
                shutdown_task.cancel()
        except Exception:
            pass
        try:
            watcher.stop()
        except Exception as e:
            logging.error("Failed to stop watcher: %s", e)
        try:
            await close_all_sessions()
        except Exception as e:
            logging.error("Failed to close sessions: %s", e)


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


def non_negative_minutes(value: str) -> float:
    """Argparse type: a non-negative number of minutes (float allowed)."""
    try:
        minutes = float(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"{value} is not a valid number of minutes") from e

    if minutes < 0:
        raise argparse.ArgumentTypeError("start delay minutes must be >= 0")
    return minutes


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
    parser.add_argument(
        "--start_delay_minutes",
        "-sd",
        type=non_negative_minutes,
        default=0,
        help="Delay application start by N minutes.",
    )
    parser.add_argument(
        "--shutdown_after_minutes",
        "-sam",
        type=non_negative_minutes,
        default=0,
        help="Automatically shut down after N minutes (0 disables). Can also be set via SHUTDOWN_AFTER_MINUTES.",
    )
    args = parser.parse_args()
    logging.debug(f"Running with arguments: {args}")

    if args.start_delay_minutes:
        delay_seconds = args.start_delay_minutes * 60
        print(f"Delaying start for {args.start_delay_minutes} minute(s)...")
        try:
            time.sleep(delay_seconds)
        except KeyboardInterrupt:
            print("Startup cancelled.")
            raise SystemExit(130)

    try:
        asyncio.run(
            start(
                args.config_dir,
                args.log_file,
                args.debug,
                args.show_browser,
                args.single_user,
                shutdown_after_minutes=args.shutdown_after_minutes or None,
            )
        )
    except KeyboardInterrupt:
        raise SystemExit(130)
