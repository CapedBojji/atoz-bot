#!/usr/bin/env python3
"""
Main entry point for the application (bare CLI).
"""
import argparse
import logging
import time
from pathlib import Path
import cmd2

from log import setup_logger
from config import AtozConfig, UserConfig, Settings
from state import get_app_state
from auth import authenticate_user, AuthRefresher


class AppCLI(cmd2.Cmd):
    """Bare application CLI using cmd2."""

    intro = "Bare CLI. Type 'help' or '?' to list commands.\n"
    prompt = "(app) "

    def __init__(self, config_dir: Path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config_dir = config_dir
        self.cookie_dir = self.config_dir / "cookies"
        self.app_state = get_app_state()
        
        # Start high-level Atoz config manager (users + settings)
        def on_user_change(name: str, data: UserConfig | None):
            key = f"users.{name}"
            if data is None:
                self.app_state.delete(key)
                logging.info(f"Removed user config from state: {name}")
            else:
                self.app_state.set(key, data)
                logging.info(f"Updated user config in state: {name} (user: {data.username})")

        def on_settings_change(settings: Settings | None):
            self.app_state.set("settings", settings)
            if settings:
                logging.info("Settings updated")
            else:
                logging.info("Settings cleared (settings.toml missing)")

        self.atoz = AtozConfig(config_dir, on_user_change, on_settings_change)
        self.atoz.start()

        # Start background token refresher
        self.auth_refresher = AuthRefresher(self.app_state, self.cookie_dir)
        self.auth_refresher.start()

        # Store initial loaded configs in state
        for name, data in self.atoz.get_users().items():
            self.app_state.set(f"users.{name}", data)
        self.app_state.set("settings", self.atoz.get_settings())

    loglevel_parser = cmd2.Cmd2ArgumentParser(description="Set logging level at runtime")
    loglevel_parser.add_argument(
        'level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help="Logging level to set"
    )

    @cmd2.with_argparser(loglevel_parser)
    def do_loglevel(self, args):
        """Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""
        level = getattr(logging, args.level)
        logger = logging.getLogger()
        
        # 1. Update the Logger's level (the gatekeeper)
        logger.setLevel(level)
        
        # 2. Update ALL handlers (the workers)
        # This ensures the FileHandler (and any others) lowers its shield
        for handler in logger.handlers:
            handler.setLevel(level)
            
        self.poutput(f"Log level set to {args.level}")
        logging.info(f"Log level changed to {args.level}")

    def do_testlog(self, _):
        """Test logging at all levels with delays."""
        self.poutput("Testing log levels (2 second delays)...")
        
        logging.debug("This is a DEBUG message")
        logging.info("This is an INFO message")
        logging.warning("This is a WARNING message")
        logging.error("This is an ERROR message")
        logging.critical("This is a CRITICAL message")
        
        self.poutput("Test complete!")

    auth_parser = cmd2.Cmd2ArgumentParser(description="Authenticate a user")
    auth_parser.add_argument("username", help="Username to authenticate (must match a loaded config)")
    auth_parser.add_argument("--browser", action="store_true", help="Show browser during auth")
    auth_parser.add_argument("--manual", action="store_true", help="Manual auth (opens browser)")

    @cmd2.with_argparser(auth_parser)
    def do_auth(self, args):
        """Authenticate a user, cache tokens, and store in app state."""
        users = self.app_state.get("users", {}) or {}
        config: UserConfig | None = users.get(args.username)
        if not config:
            self.poutput(f"No config loaded for user '{args.username}'")
            return

        self.poutput(f"Authenticating {args.username}...")
        success, tokens = authenticate_user(
            config,
            cookie_dir=self.cookie_dir,
            show_browser=args.browser,
            manual=args.manual,
        )
        if success:
            self.poutput("Authentication successful")
            self.app_state.set(f"tokens.{args.username}", tokens)
            self.poutput(f"Tokens cached. Expires: {tokens.get('expires')}")
        else:
            self.poutput("Authentication failed")

    def do_status(self, _):
        """Show loaded configs and application status."""
        users = self.atoz.get_users()
        settings = self.atoz.get_settings()
        self.poutput(f"Config directory: {self.config_dir}")
        self.poutput(f"Users: {len(users)}")
        for name in users:
            self.poutput(f"  - {name}")
        self.poutput("Settings:")
        if settings:
            self.poutput(f"  - o365_client_id: {'set' if settings.o365_client_id else 'unset'}")
            self.poutput(f"  - o365_client_secret: {'set' if settings.o365_client_secret else 'unset'}")
        else:
            self.poutput("  - (no settings loaded)")

        tokens = self.app_state.get("tokens", {}) or {}
        self.poutput(f"Tokens cached: {len(tokens)}")
        for name, tok in tokens.items():
            exp = tok.get("expires")
            self.poutput(f"  - {name}: expires={exp}")

    def do_quit(self, _):
        """Exit the application."""
        self.poutput("Shutting down...")
        self.auth_refresher.stop()
        self.atoz.stop()
        self.app_state.cleanup()
        return True

    def do_exit(self, arg):
        """Exit the application."""
        return self.do_quit(arg)


def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(description="Application with config directory watcher")
    parser.add_argument(
        '--config-dir',
        type=Path,
        default=Path.home() / ".config" / "atoz",
        help="Configuration directory to watch (default: ~/.config/atoz)"
    )
    args = parser.parse_args()

    setup_logger(log_dir="logs", retention_days=7, level=logging.INFO)

    logging.info("Application started")
    logging.info(f"Config directory: {args.config_dir}")

    # Ensure config directory exists
    args.config_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Start CLI loop
        app = AppCLI(config_dir=args.config_dir)
        app.cmdloop()

    except KeyboardInterrupt:
        logging.info("Application interrupted by user")
    except Exception as e:
        logging.error(f"Application error: {e}", exc_info=True)
    finally:
        logging.info("Application finished")


if __name__ == "__main__":
    main()
