import asyncio
import logging
import pathlib
import re
import time
from asyncio import TaskGroup
from os import PathLike
from typing import Optional

import requests
from httpx import AsyncClient
from selenium.webdriver.common.by import By

from app.models import UserConfig, obfuscate_2fa_method, TwoFAMethod
from two_factor.outlook import authenticate, get_2fa_code
from utils.browser import BrowserFirefox, get_2fa_options
from utils.session import create_httpx_async_client
from utils.time import is_time
from utils.watcher import load_config


class UserSession:
    def __init__(self, config: UserConfig):
        self.__client = AsyncClient(http2=True)
        self.__session = None
        self.__employee_id: Optional[int] = None
        self.__config = config

    def get_config(self) -> UserConfig:
        """
        Get the user session configuration.
        """
        return self.__config

    def get_session(self) -> requests.Session:
        """
        Get the request session.
        """
        return self.__session

    def update_config(self, config: UserConfig):
        """
        Update the user session with the new configuration.
        """
        if self.__config.username != config.username:
            raise ValueError("Cannot change username in session")
        if self.__should_re_login(config):
            # Re-authenticate if the configuration has changed
            # self.__session = requests.Session()
            self.__client = AsyncClient(http2=True)
            self.__employee_id = None
        self.__config = config
        logging.debug("User session config updated: %s", self.__config)

    def __should_re_login(self, new_config: UserConfig) -> bool:
        """
        Check if the session should be re-logged in based on the new configuration.
        """
        return self.__config.username != new_config.username or self.__config.password != new_config.password or self.__config.two_factor_method[0] != new_config.two_factor_method[0] or \
            self.__config.two_factor_method[1] != new_config.two_factor_method[1]

    async def get_employee_id(self) -> int | None:
        """
        Get the employee ID from the session.
        """
        if self.__employee_id is None:
            # Fetch the employee ID from the session
            url = "https://atoz.amazon.work/shifts"

            response = await self.__client.get(url)
            if response.status_code != 200:
                logging.error("Failed to get employee ID from session")
                return None

            text = response.text
            pattern = re.compile(r"""(?<=['\"]employeeId['\"]:['\"])\d{9}(?=['\"])""")
            match = pattern.search(text)
            if match is None:
                logging.error(f"Employee ID not found in response for user session {self}")
                return None

            self.__employee_id = int(match.group())

        return self.__employee_id

    async def authenticate(self, show_browser=False) -> bool:
        """
        Authenticate the user session.
        """
        if self.__is_session_valid() and not self.__is_session_expired():
            return True
        elif self.__is_session_valid() and self.__is_session_expired():
            return await self.__re_authenticate()
        else:
            browser = BrowserFirefox(headless=not show_browser)
            # Perform the login process
            try:
                cookies = await asyncio.to_thread(self.__login, browser)
            except Exception as e:
                logging.error(f"Failed to login: {e}")
                browser.stop()
                return False
            # Create a new session with the cookies
            self.__client = create_httpx_async_client(selenium_cookie_list=cookies)
            # Check if the session is valid
            return self.__is_session_valid()

    def __is_session_valid(self) -> bool:
        """
        Check if the session is valid.
        """
        cookies = self.__client.cookies
        cookies.get("atoz-oauth-token")
        if not cookies:
            return False
        # Check if the session has correct cookies
        if not cookies.get("atoz-oauth-token") or not cookies.get("atoz-refresh-token") or not cookies.get(
                "atoz-auth-session"):
            return False
        return True

    def __is_session_expired(self) -> bool:
        """
        Check if the session is expired.
        """
        expiration_time = self.__client.cookies.get("refresh_session_expiration")
        if expiration_time is None:
            return True
        current_time = time.time()
        return current_time + 60 > int(expiration_time)

    async def logout(self) -> None:
        """
        Logout the user session.
        """
        # Implement logout logic here
        url = "https://atoz-login.amazon.work/logout"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
        }
        response = await self.__client.get(url, headers=headers)
        if response.status_code != 200:
            logging.error(f"Failed to logout: {response.status_code} - {response.text}")

        logging.debug(f"Logged out user session {self}")

    def __str__(self) -> str:
        """
        String representation of the user session.
        """
        return f"UserSession(username={self.__config.username}, employee_id={self.__employee_id})"

    async def __re_authenticate(self) -> bool:
        """
        Re-authenticate the user session.
        """
        logging.debug("Re-authenticating user session")
        # Build the URL and headers for the request
        url = "https://atoz-login.amazon.work/initialize"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
            "anti-csrftoken-a2z-request": "true",
        }
        # Send the request to get the CSRF token
        response = await self.__client.get(url, headers=headers)
        if response.status_code != 200:
            logging.error(f"Failed to get CSRF token: {response.status_code} - {response.text}")
            await self.logout()
            return False

        # Extract CSRF token from header
        csrf_token = response.headers.get("anti-csrftoken-a2z")
        if not csrf_token:
            logging.error(f"CSRF token not found in response headers for user session {self}")
            await self.logout()
            return False
        # Build the URL and headers for the refresh access token request
        url = "https://atoz-login.amazon.work/refresh_access_token"
        headers = {
            "anti-csrftoken-a2z": csrf_token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
        }
        # Send the request to refresh the access token
        response = await self.__client.post(url, headers=headers)
        if response.status_code != 200:
            logging.error(f"Failed to refresh access token: {response.status_code} - {response.text}")
            await self.logout()
            return False

        return True
    def __login(self, browser: BrowserFirefox) -> list:
        logging.debug("Performing login for user session %s", self)
        """
        Perform the login process.

        This method should handle the actual login logic, including
        entering the username and password, and handling two-factor authentication.
        """
        browser.start()
        # Open the login page
        browser.get_url("https://atoz-login.amazon.work/")
        # Enter username
        browser.find_element(By.ID, "associate-login-input").send_keys(self.__config.username)
        browser.find_element(By.ID, "login-form-login-btn").click()
        # Wait for workforce page to load
        browser.wait_for_url("workforce")
        # Enter username again
        browser.find_element(By.ID, "input-id-4").send_keys(self.__config.username)
        browser.find_element(By.CSS_SELECTOR, '[data-testid="submit-username-button"]').click()
        # Enter password
        browser.wait_for_url("SAML2/Unsolicited/SSO")
        browser.find_element(By.ID, "password").send_keys(self.__config.password)
        browser.find_element(By.ID, "buttonLogin").click()
        # Handle two-factor authentication
        browser.wait_for_url("idp/enter?sif_profile=amazon-passport")
        two_2fa_options = get_2fa_options(browser)
        obfuscated_2fa_method = obfuscate_2fa_method(self.__config.two_factor_method[1], method=self.__config.two_factor_method[0])
        for option in two_2fa_options:
            if option[0] == obfuscated_2fa_method:
                option[1].click()
                break
        browser.find_element(By.ID, "buttonContinue").click()
        # Wait for the 2FA code input field to appear
        time.sleep(20)
        browser.find_element(By.ID, "code").send_keys(self.__get_2fa_code())
        browser.find_element(By.ID, "buttonVerifyIdentity").click()
        # Bypass setup Passkey
        browser.find_element(By.CSS_SELECTOR, "button.remind-button[data-target=\"#passkeyConfirmModal\"]").click()
        browser.find_element(By.CSS_SELECTOR, 'button.remind-button[form="passkeyForm"]').click()
        # Ensure that the login was successful
        browser.wait_for_url(regex=r"/shifts|/home", timeout=45)
        # Get the cookies from the browser
        cookies = browser.get_cookies()
        # Stop the browser
        browser.stop()
        # Return the cookies
        if not cookies:
            logging.error("No cookies found after login")
            raise RuntimeError("No cookies found after login")
        return cookies

    def get_client(self) -> AsyncClient:
        """
        Get the HTTPX async client.
        """
        return self.__client

    def __get_2fa_code(self) -> str:
        """
        Get the 2FA code from the user.
        """
        method = self.__config.two_factor_method[0]
        if method == TwoFAMethod.OUTLOOK:
            if not authenticate(self.__config.two_factor_method[1]):
                raise ValueError("Failed to authenticate with the 2FA method")
            return get_2fa_code(self.__config.two_factor_method[1])
        else:
            raise ValueError(f"Unknown 2FA method type: {method}")

__active_sessions: dict[str, tuple[UserSession, Optional[pathlib.Path]]] = {}


def create_user_session(config: UserConfig, path: Optional[pathlib.Path]) -> UserSession:
    """
    Create a new user session for the given username.
    If the session already exists, return the existing one.
    """
    username = config.username
    if username in __active_sessions:
        logging.warn("User session already exists")
        return __active_sessions[username][0]
    else:
        logging.debug(f"Creating new user session from config: {config}")
        __active_sessions[username] = (UserSession(config), path)
        return __active_sessions[username][0]


def get_user_session(config: UserConfig, path: Optional[pathlib.Path]) -> UserSession:
    """
    Get the user session for the given username.
    """
    username = config.username
    if username not in __active_sessions:
        logging.warn("Trying to get a user session that does not exist: %s. Creating...", username)
        create_user_session(config, path)
    return __active_sessions[username][0]


def delete_user_session(session: UserSession) -> None:
    """
    Delete the user session.
    """
    username = session.get_config().username
    if username in __active_sessions:
        del __active_sessions[username]
        logging.debug("Deleted user session for %s", username)
    else:
        logging.warning("Attempting to delete session for %s, but session doesn't exist", username)

def reload_user_session(session: UserSession) -> None:
    username = session.get_config().username
    if username in __active_sessions:
        # Get the path to the file
        path = __active_sessions[username][1]
        # Delete the session
        delete_user_session(session)
        # Create a new session with the same config
        data = load_config(path)
        if data is None:
            logging.error(f"Failed to load config for user {username} from path {path}")
            return
        create_user_session(data, path)
    else:
        logging.warning("Attempting to reload session for %s, but session doesn't exist", username)

async def authenticate_all_sessions(show_browser = False, single_user = None) -> list[UserSession]:
    """
    Authenticate all user sessions.
    This method will iterate through all active sessions and authenticate them.
    :return: A list of authenticated sessions.
    """
    authenticated = []
    results = {}
    if single_user is not None and single_user in __active_sessions:

        # If a single user is specified, only authenticate that user
        session = __active_sessions[single_user][0]
        # Check to see if session needs to be reloaded
        if session.get_config().reload_session_on is not None and is_time(session.get_config().reload_session_on):
            reload_user_session(session)
        results[session] = await session.authenticate(show_browser)
        if results[session]:
            authenticated.append(session)
            logging.debug(f"Authenticated session for {session.get_config().username}")
        else:
            logging.error(f"Failed to authenticate session for {session.get_config().username}")

        return authenticated

    for username, (session, _) in __active_sessions.items():
        # Check to see if session needs to be reloaded
        if session.get_config().reload_session_on is not None and is_time(session.get_config().reload_session_on):
            reload_user_session(session)

    async with TaskGroup() as group:
        for (session, _) in __active_sessions.values():
            # Create a task for each session
            results[session] = group.create_task(session.authenticate(show_browser))

    for session, task in results.items():
        if task.result():
            authenticated.append(session)
            logging.debug(f"Authenticated session for {session.get_config().username}")
        else:
            logging.error(f"Failed to authenticate session for {session.get_config().username}")

    return authenticated