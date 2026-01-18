import asyncio
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Optional, Protocol

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from app.models import TwoFAMethod, obfuscate_2fa_method
from utils.watcher import load_config
from utils.browser import BrowserFirefox, get_2fa_options


class CaptchaDetectedError(Exception):
    """Raised when a CAPTCHA is detected during authentication."""
    pass


class TwoFAHandler(Protocol):
    """Protocol for two-factor authentication handler."""
    
    def pick_two_fa_option(self, options: list[tuple[str, object]]) -> tuple[str, object]:
        """
        Pick a two-factor authentication option from the available options.
        
        :param options: List of available 2FA options (obfuscated name, element).
        :return: The selected option tuple.
        """
        ...
    
    def get_code(self) -> str:
        """
        Get the two-factor authentication code.
        
        :return: The 2FA code as a string.
        """
        ...


class CaptchaHandler(Protocol):
    """Protocol for CAPTCHA handler during authentication."""
    
    def handle_captcha(self, is_headless: bool) -> None:
        """
        Handle CAPTCHA detection. If headless, should raise an error.
        Otherwise, wait for user confirmation that CAPTCHA is solved.
        
        :param is_headless: Whether the browser is running in headless mode.
        :raises CaptchaDetectedError: If in headless mode or if user decides to stop.
        """
        ...


def authenticate(
    username: str,
    password: str,
    two_fa_handler: TwoFAHandler,
    captcha_handler: CaptchaHandler,
    cookie_path: Path,
    two_fa_method: tuple[TwoFAMethod, str],
    show_browser: bool = False,
    manual_login: bool = False
) -> Optional[str]:
    """
    Authenticate the user and save cookies to a file.
    
    This function first attempts to load existing cookies. If they exist and are valid,
    it returns the auth token immediately. Otherwise, it performs a full login.
    
    :param username: The username to authenticate.
    :param password: The password for the user.
    :param two_fa_handler: A handler object with pick_two_fa_option and get_code methods.
    :param captcha_handler: A handler object for CAPTCHA detection and resolution.
    :param cookie_path: Path to save the authentication cookies.
    :param two_fa_method: Tuple of (TwoFAMethod, 2FA identifier string).
    :param show_browser: Whether to show the browser window (default: False).
    :param manual_login: If True, open browser and wait for manual login (default: False).
    :return: The auth token string if successful, None otherwise.
    :raises Exception: If login fails at any step.
    """
    logging.debug(f"Starting authentication for user: {username}")
    
    # Ensure the cookie directory exists
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Try to reuse existing session (pass actual username instead of a dummy)
    cached_cookies = _try_reuse_session(username, cookie_path, show_browser)
    if cached_cookies:
        auth_token = _extract_auth_token(cached_cookies)
        logging.info(f"Successfully reused existing session for user: {username}")
        return auth_token
    
    # Perform full login if cookies don't exist or are invalid
    browser = BrowserFirefox(headless=not show_browser)
    try:
        browser.start()
        if manual_login:
            cookies = _perform_manual_login(browser, username)
        else:
            cookies = _perform_full_login(browser, username, password, two_fa_handler, captcha_handler, two_fa_method, is_headless=not show_browser)
        
        # Save cookies to file
        _save_cookies(cookies, cookie_path)
        
        # Extract and return auth token
        auth_token = _extract_auth_token(cookies)
        logging.info(f"Successfully authenticated user: {username}")
        return auth_token
        
    except Exception as e:
        logging.error(f"Authentication failed for user {username}: {e}")
        raise
    finally:
        browser.stop()


def _try_reuse_session(username: str, cookie_path: Path, show_browser: bool = False) -> Optional[list[dict]]:
    """
    Try to reuse an existing session from saved cookies.

    Validates cookies by attempting login - if authenticated, the server
    redirects to the logged in page after username entry.

    :param username: The username to use when validating the session (replaces dummy input).
    :param cookie_path: Path to the saved cookies file.
    :param show_browser: Whether to show the browser window.
    :return: Cookies if session is valid, None otherwise.
    """
    existing_cookies = load_cookies(cookie_path)
    if not existing_cookies:
        return None
    
    logging.debug("Found existing cookies, attempting to reuse session")
    browser = BrowserFirefox(headless=not show_browser)
    
    try:
        browser.start()
        
        # Load cookies into browser before navigating to any site
        _load_cookies_into_browser(browser, existing_cookies)
        
        # Navigate to login page
        browser.get_url("https://atoz-login.amazon.work/")
        
        # Try to enter username on the first form - if authenticated,
        # it will redirect to logged in page. Use the real username instead
        # of a dummy value so behavior matches an actual login flow.
        username_field = browser.find_element(By.ID, "associate-login-input")
        username_field.send_keys(username)
        browser.find_element(By.ID, "login-form-login-btn").click()
        
        # If cookies are valid, user is already authenticated and will redirect to logged in page
        if _validate_session(browser):
            logging.debug("Session validation successful - cookies are still valid")
            # Return fresh cookies from browser, not the old ones, in case they were refreshed
            return browser.get_cookies()
        else:
            logging.debug("Existing cookies are invalid")
            return None
            
    except Exception as e:
        logging.debug(f"Failed to reuse cookies: {e}")
        return None
    finally:
        browser.stop()


def _perform_full_login(
    browser: BrowserFirefox,
    username: str,
    password: str,
    two_fa_handler: TwoFAHandler,
    captcha_handler: CaptchaHandler,
    two_fa_method: tuple[TwoFAMethod, str],
    is_headless: bool = False
) -> list[dict]:
    """
    Perform the complete login flow.
    
    :param browser: The browser instance.
    :param username: The username to authenticate.
    :param password: The password for the user.
    :param two_fa_handler: A handler object with pick_two_fa_option and get_code methods.
    :param captcha_handler: A handler object for CAPTCHA detection and resolution.
    :param two_fa_method: Tuple of (TwoFAMethod, 2FA identifier string).
    :param is_headless: Whether the browser is running in headless mode.
    :return: List of cookies from successful login.
    """
    # Step 1: Navigate to login page and enter credentials
    _perform_initial_login(browser, username, password)
    
    # Step 2: Handle two-factor authentication
    _handle_two_factor_auth(browser, two_fa_handler, captcha_handler, two_fa_method, is_headless)
    
    # Step 3: Handle post-login steps (passkey bypass, etc.)
    _handle_post_login_steps(browser)
    
    # Step 4: Validate session to ensure login was successful
    logging.debug("Validating session after login")
    if not _validate_session(browser):
        logging.error("Session validation failed after login")
        raise RuntimeError("Session validation failed after login")
    
    # Step 5: Extract and return cookies
    logging.debug("Extracting cookies from browser")
    cookies = browser.get_cookies()
    
    if not cookies:
        logging.error("No cookies found after login")
        raise RuntimeError("No cookies found after login")
    
    return cookies


def _perform_manual_login(browser: BrowserFirefox, username: str) -> list[dict]:
    """
    Perform manual login - open the browser and wait for the user to login manually.
    
    :param browser: The browser instance.
    :param username: The username (for display purposes).
    :return: List of cookies from successful login.
    """
    logging.info(f"Manual login mode for user: {username}")
    logging.info("Opening login page - please login manually in the browser")
    
    # Open login page
    browser.get_url("https://atoz-login.amazon.work/")
    
    # Wait for user confirmation that they've finished logging in
    print("\n" + "="*60)
    print(f"MANUAL LOGIN MODE for user: {username}")
    print("="*60)
    print("Please complete the login process in the browser window.")
    print("Press Enter when you have successfully logged in...")
    print("="*60 + "\n")
    
    input("Press Enter to continue once login is complete: ")
    
    # Validate session to ensure login was successful
    logging.debug("Validating session after manual login")
    if not _validate_session(browser):
        logging.error("Session validation failed after manual login")
        raise RuntimeError("Session validation failed - please ensure you completed the login successfully")
    
    # Extract and return cookies
    logging.debug("Extracting cookies from browser")
    cookies = browser.get_cookies()
    
    if not cookies:
        logging.error("No cookies found after manual login")
        raise RuntimeError("No cookies found after manual login")
    
    logging.info("Manual login completed successfully")
    return cookies


def _perform_initial_login(browser: BrowserFirefox, username: str, password: str) -> None:
    """
    Perform the initial login steps (username and password entry).
    
    :param browser: The browser instance.
    :param username: The username to authenticate.
    :param password: The password for the user.
    """
    logging.debug("Opening login page")
    browser.get_url("https://atoz-login.amazon.work/")
    
    # Enter username on first form
    logging.debug("Entering username on first form")
    browser.find_element(By.ID, "associate-login-input").send_keys(username)
    browser.find_element(By.ID, "login-form-login-btn").click()
    
    # Wait for workforce page and enter username again
    logging.debug("Waiting for workforce page and entering username again")
    browser.wait_for_url("workforce")
    browser.find_element(By.ID, "input-id-4").send_keys(username)
    browser.find_element(By.CSS_SELECTOR, '[data-testid="submit-username-button"]').click()
    
    # Enter password
    logging.debug("Waiting for SAML2 page and entering password")
    browser.wait_for_url("SAML2/Unsolicited/SSO")
    browser.find_element(By.ID, "password").send_keys(password)
    browser.find_element(By.ID, "buttonLogin").click()


def _handle_two_factor_auth(
    browser: BrowserFirefox,
    two_fa_handler: TwoFAHandler,
    captcha_handler: CaptchaHandler,
    two_fa_method: tuple[TwoFAMethod, str],
    is_headless: bool = False
) -> None:
    """
    Handle the two-factor authentication process.
    
    :param browser: The browser instance.
    :param two_fa_handler: A handler object with pick_two_fa_option and get_code methods.
    :param captcha_handler: A handler object for CAPTCHA detection and resolution.
    :param two_fa_method: Tuple of (TwoFAMethod, 2FA identifier string).
    :param is_headless: Whether the browser is running in headless mode.
    """
    logging.debug("Waiting for 2FA selection page")
    browser.wait_for_url("idp/enter?sif_profile=amazon-passport")
    
    # Get available 2FA options
    two_fa_options = get_2fa_options(browser)
    obfuscated_2fa_method = obfuscate_2fa_method(two_fa_method[1], method=two_fa_method[0])
    
    # Find and select the matching 2FA option
    selected_option = None
    for option in two_fa_options:
        if option[0] == obfuscated_2fa_method:
            selected_option = option
            break
    
    if selected_option is None:
        logging.error(f"Could not find matching 2FA method: {obfuscated_2fa_method}")
        raise ValueError(f"2FA method not found: {obfuscated_2fa_method}")
    
    # Pick the option using the handler
    picked_option = two_fa_handler.pick_two_fa_option(two_fa_options)
    picked_option[1].click()
    browser.find_element(By.ID, "buttonContinue").click()
    
    # Wait for 2FA code input field
    logging.debug("Waiting for 2FA code input field")
    time.sleep(20)
    
    # Get and enter the 2FA code
    two_fa_code = two_fa_handler.get_code()
    browser.find_element(By.ID, "code").send_keys(two_fa_code)
    
    # Check the "remember this device for 30 days" checkbox
    try:
        logging.debug("Looking for trusted device checkbox")
        trusted_device_checkbox = browser.find_element(By.CSS_SELECTOR, "#trusted-device-option-label")
        if not trusted_device_checkbox.is_selected():
            logging.debug("Checking trusted device checkbox")
            trusted_device_checkbox.click()
    except Exception as e:
        logging.debug(f"Trusted device checkbox not found or already checked: {e}")
    
    browser.find_element(By.ID, "buttonVerifyIdentity").click()
    
    # Check for CAPTCHA
    logging.debug("Checking for CAPTCHA")
    if _is_captcha_showing(browser):
        logging.error("CAPTCHA detected during authentication")
        captcha_handler.handle_captcha(is_headless)


def _handle_post_login_steps(browser: BrowserFirefox) -> None:
    """
    Handle post-login steps like bypassing passkey setup.
    
    :param browser: The browser instance.
    """
    logging.debug("Bypassing Passkey setup")
    browser.find_element(By.CSS_SELECTOR, "button.remind-button[data-target=\"#passkeyConfirmModal\"]").click()
    
    # Wait a moment for the modal to appear and elements to load
    time.sleep(2)
    
    browser.find_element(By.CSS_SELECTOR, 'button.remind-button[form="passkeyForm"]').click()
    
    # Wait for successful login redirect
    logging.debug("Waiting for successful login redirect")
    browser.wait_for_url(regex=r"/shifts|/home", timeout=45)


def _save_cookies(cookies: list[dict], cookie_path: Path) -> None:
    """
    Save cookies to a file using pickle.
    
    :param cookies: List of cookie dictionaries from Selenium.
    :param cookie_path: Path to save the cookies.
    """
    try:
        with open(cookie_path, 'wb') as f:
            pickle.dump(cookies, f)
        logging.debug(f"Cookies saved to {cookie_path}")
    except Exception as e:
        logging.error(f"Failed to save cookies to {cookie_path}: {e}")
        raise


def load_cookies(cookie_path: Path) -> Optional[list[dict]]:
    """
    Load cookies from a file.
    
    :param cookie_path: Path to the cookie file.
    :return: List of cookie dictionaries or None if file doesn't exist.
    """
    if not cookie_path.exists():
        logging.debug(f"Cookie file not found: {cookie_path}")
        return None
    
    try:
        with open(cookie_path, 'rb') as f:
            cookies = pickle.load(f)
        logging.debug(f"Cookies loaded from {cookie_path}")
        return cookies
    except Exception as e:
        logging.error(f"Failed to load cookies from {cookie_path}: {e}")
        return None


def _extract_auth_token(cookies: list[dict]) -> Optional[str]:
    """
    Extract the authorization token from cookies.
    
    :param cookies: List of cookie dictionaries.
    :return: The auth token string or None if not found.
    """
    for cookie in cookies:
        if cookie.get('name') == 'atoz-oauth-token':
            return cookie.get('value')
    return None


def _load_cookies_into_browser(browser: BrowserFirefox, cookies: list[dict]) -> None:
    """
    Load cookies into the browser session.
    
    :param browser: The BrowserFirefox instance.
    :param cookies: List of cookie dictionaries to load.
    """
    for cookie in cookies:
        try:
            # Remove keys that Selenium doesn't accept
            cookie_copy = cookie.copy()
            if 'expiry' in cookie_copy:
                # Selenium expects 'expiry' as int, ensure it's converted
                cookie_copy['expiry'] = int(cookie_copy['expiry'])
            
            browser.driver.add_cookie(cookie_copy)
        except Exception as e:
            logging.debug(f"Failed to add cookie {cookie.get('name')}: {e}")


def _validate_session(browser: BrowserFirefox) -> bool:
    """
    Validate if the current session is still valid.
    
    :param browser: The BrowserFirefox instance.
    :return: True if session is valid, False otherwise.
    """
    try:
        # Check if we're on the shifts/home page (logged in)
        current_url = browser.driver.current_url
        if "/shifts" in current_url or "/home" in current_url:
            logging.debug("Session validation successful - user is logged in")
            return True
        else:
            logging.debug(f"Session validation failed - unexpected URL: {current_url}")
            return False
    except Exception as e:
        logging.debug(f"Session validation error: {e}")
        return False


def _is_captcha_showing(browser: BrowserFirefox) -> bool:
    """
    Check if a CAPTCHA is currently showing on the page.
    
    This function looks for the <awswaf-captcha> tag inside the #captcha-container
    using a short timeout so it doesn't block if the CAPTCHA isn't present.
    
    :param browser: The BrowserFirefox instance.
    :return: True if CAPTCHA is detected, False otherwise.
    """
    try:
        # Look for the <awswaf-captcha> tag inside the #captcha-container
        # Use a short timeout (5 seconds) so we don't block the script forever
        captcha_element = WebDriverWait(browser.driver, 5).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, "#captcha-container awswaf-captcha"))
        )
        logging.warning("CAPTCHA detected on page!")
        return True
    except TimeoutException:
        logging.debug("No CAPTCHA detected")
        return False


class ConsoleTwoFAHandler(TwoFAHandler):
    """Console-based 2FA handler for manual selection and code entry."""

    def pick_two_fa_option(self, options: list[tuple[str, object]]) -> tuple[str, object]:
        for idx, option in enumerate(options):
            print(f"[{idx}] {option[0]}")
        while True:
            choice = input("Select 2FA option number: ").strip()
            if choice.isdigit() and 0 <= int(choice) < len(options):
                return options[int(choice)]
            print("Invalid choice, try again.")

    def get_code(self) -> str:
        return input("Enter 2FA code: ").strip()


class ConsoleCaptchaHandler(CaptchaHandler):
    """Console-based CAPTCHA handler that waits for user confirmation."""

    def handle_captcha(self, is_headless: bool) -> None:
        """
        Handle CAPTCHA by waiting for user confirmation.
        
        :param is_headless: Whether the browser is running in headless mode.
        :raises CaptchaDetectedError: If in headless mode or user decides to stop.
        """
        if is_headless:
            logging.error("CAPTCHA detected but browser is in headless mode - cannot continue")
            raise CaptchaDetectedError("CAPTCHA detected in headless mode - manual intervention required")
        
        logging.warning("CAPTCHA page is showing - please solve it manually in the browser")
        response = input("Press Enter once you've solved the CAPTCHA, or type 'stop' to abort: ").strip().lower()
        
        if response == "stop":
            logging.error("User chose to stop at CAPTCHA page")
            raise CaptchaDetectedError("User chose to stop at CAPTCHA page")
        
        logging.debug("Continuing after CAPTCHA resolution")


def example_authenticate_laudboat(show_browser: bool = False) -> Optional[str]:
    """Authenticate using config/laudboat.toml with manual 2FA input."""
    config_path = Path("config/laudboat.toml")
    user_config = load_config(config_path)
    if user_config is None:
        logging.error(f"Failed to load config from {config_path}")
        return None

    two_fa_handler = ConsoleTwoFAHandler()
    captcha_handler = ConsoleCaptchaHandler()
    cookie_path = Path("cookies") / f"{user_config.username}.pkl"

    token = authenticate(
        username=user_config.username,
        password=user_config.password,
        two_fa_handler=two_fa_handler,
        captcha_handler=captcha_handler,
        cookie_path=cookie_path,
        two_fa_method=user_config.two_factor_method,
        show_browser=show_browser,
    )

    if token:
        print(f"Auth success for {user_config.username}. Token prefix: {token[:12]}...")
    else:
        print("Authentication returned no token.")
    return token


if __name__ == "__main__":
    example_authenticate_laudboat(show_browser=True)
