import re
import time
import shutil
import os

from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.wait import WebDriverWait
from selenium import webdriver


class ElementActions:
    def __init__(self, element: WebElement):
        self.element = element

    def click(self):
        if not self.element.is_displayed():
            raise RuntimeError("Element is not displayed.")
        if not self.element.is_enabled():
            raise RuntimeError("Element is not enabled.")
        self.element.click()

    def send_keys(self, keys):
        if not self.element.is_displayed():
            raise RuntimeError("Element is not displayed.")
        if not self.element.is_enabled():
            raise RuntimeError("Element is not enabled.")
        self.element.send_keys(keys)

    def get_text(self):
        if not self.element.is_displayed():
            raise RuntimeError("Element is not displayed.")
        return self.element.text.strip()

    def get_attribute(self, name):
        if not self.element.is_displayed():
            raise RuntimeError("Element is not displayed.")
        return self.element.get_attribute(name).strip() if self.element.get_attribute(name) else None

    def find_element(self, by, value):
        if not self.element.is_displayed():
            raise RuntimeError("Element is not displayed.")
        found_element = self.element.find_element(by, value)
        if not found_element:
            raise RuntimeError(f"Element not found: {by}={value}")
        return ElementActions(found_element)

class BrowserFirefox:
    def __init__(self, options=None, headless=True):
        self.__started = False
        self.gecko_driver_path = self._find_gecko_driver()
        self.options = options or FirefoxOptions()

        # Add this block to check for a custom binary path
        firefox_bin = os.getenv('FIREFOX_BIN')
        if firefox_bin:
            self.options.binary_location = firefox_bin

        if headless:
            self.options.add_argument("--headless")
        self.driver = None

    def _find_gecko_driver(self):
        """
        Find GeckoDriver in the following order:
        1. Environment variable GECKODRIVER_PATH
        2. Check if geckodriver is in PATH
        3. Use webdriver-manager for automatic download
        4. Return None to let Selenium handle it
        """
        # Check environment variable first
        env_path = os.getenv('GECKODRIVER_PATH')
        if env_path and os.path.isfile(env_path):
            return env_path
        
        # Check if geckodriver is in PATH
        gecko_path = shutil.which('geckodriver')
        if gecko_path:
            return gecko_path
        
        # Try webdriver-manager as fallback
        try:
            from webdriver_manager.firefox import GeckoDriverManager
            return GeckoDriverManager().install()
        except ImportError:
            # webdriver-manager not available, let Selenium handle it
            pass
        
        # Let Selenium's built-in driver manager handle it
        return None

    def start(self):
        if self.__started:
            raise RuntimeError("Browser is already running.")
        self.__started = True
        
        # Create Firefox driver with or without explicit GeckoDriver path
        if self.gecko_driver_path:
            from selenium.webdriver.firefox.service import Service
            service = Service(executable_path=self.gecko_driver_path)
            self.driver = webdriver.Firefox(service=service, options=self.options)
        else:
            # Let Selenium find GeckoDriver automatically
            self.driver = webdriver.Firefox(options=self.options)
        
        self.__started = True

    def stop(self):
        if not self.__started:
            return
        if self.driver:
            self.driver.quit()
            self.driver = None


    def get_url(self, url, timeout=10):
        if not self.__started:
            raise RuntimeError("Browser is not started.")
        self.driver.get(url)
        is_url = WebDriverWait(self.driver, timeout).until(lambda d: d.current_url == url)
        while not is_url and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1


    def find_elements(self, by, value, timeout=10):
        if not self.__started:
            raise RuntimeError("Browser is not started.")
        elements_found = WebDriverWait(self.driver, timeout).until(
            lambda d: d.find_elements(by, value)
        )
        while not elements_found and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1
        if not elements_found:
            raise RuntimeError(f"Element not found: {by}={value}")
        return [ElementActions(x) for x in elements_found]

    def find_element(self, by, value, timeout=10):
        return self.find_elements(by, value, timeout=timeout)[0]



    def wait_for_url(self, url = None, regex = None, timeout=10):
        if not self.__started:
            raise RuntimeError("Browser is not started.")
        if not url and not regex:
            raise ValueError("Either url or regex must be provided.")

        if regex is None:
            found = WebDriverWait(self.driver, timeout).until(lambda d: url in d.current_url)
        else:
            found = WebDriverWait(self.driver, timeout).until(lambda d: re.search(regex, d.current_url) is not None)

        while not found and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1
            if regex is None:
                found = WebDriverWait(self.driver, timeout).until(lambda d: url in d.current_url)
            else:
                found = WebDriverWait(self.driver, timeout).until(lambda d: re.search(regex, d.current_url) is not None)

    def wait_for_element(self, by, value, timeout=10):
        if not self.__started:
            raise RuntimeError("Browser is not started.")
        elements_found = WebDriverWait(self.driver, timeout).until(
            lambda d: d.find_elements(by, value)
        )
        while not elements_found and timeout > 0:
            time.sleep(0.1)
            timeout -= 0.1
        if not elements_found:
            raise RuntimeError(f"Element not found: {by}={value}")

    def get_cookies(self):
        if not self.__started:
            raise RuntimeError("Browser is not started.")
        return self.driver.get_cookies()

def get_2fa_options(browser: BrowserFirefox) -> list[tuple[str, ElementActions]]:
    """
    Get the available 2FA options.

    :param browser: The browser instance.
    :return: A list of available 2FA options.
    """
    # Get the 2FA options
    elements = browser.find_elements(By.CSS_SELECTOR, "div.radio")
    values = []
    for element in elements:
        label = element.find_element(By.TAG_NAME, "label")
        values.append((label.get_text(), label))
    return values


if __name__ == "__main__":
    # Example usage with the new convenience function
    browser = BrowserFirefox(headless=False)

    print(f"GeckoDriver path: {browser.gecko_driver_path}")
    
    browser.start()
    browser.get_url("https://httpbin.org/html")
    print("✅ Successfully loaded test page!")
    browser.stop()