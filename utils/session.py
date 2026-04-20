import logging
from copy import copy
from http.cookiejar import CookieJar, Cookie

import httpx
import requests
from requests.cookies import RequestsCookieJar, create_cookie


def create_session(selenium_cookie_list: list[dict]) -> requests.Session:
    """
    Create a requests session with the given cookies.

    :param selenium_cookie_list : list[dict]
            - A list of dictionaries, each representing a cookie;
            - With required keys - "name" and "value";
            - Optional keys - "path", "domain", "secure", "httpOnly", "expiry", "sameSite"
    :return: A requests session with the cookies set.
    """
    session = requests.Session()
    for cookie in selenium_cookie_list:
        fixed_cookie = {**{k: v for k, v, in cookie.items() if k not in ("expiry", "sameSite", "httpOnly")}}
        if cookie.get("expiry"):
            fixed_cookie["expires"] = cookie["expiry"]
        session.cookies.set_cookie(create_cookie(**fixed_cookie))
    return session

def create_httpx_async_client(selenium_cookie_list: list[dict]) -> httpx.AsyncClient:
    """
    Create an httpx async client with the given cookies.

    :param selenium_cookie_list : list[dict]
            - A list of dictionaries, each representing a cookie;
            - With required keys - "name" and "value";
            - Optional keys - "path", "domain", "secure", "httpOnly", "expiry", "sameSite"
    :return: An httpx async client with the cookies set.
    """
    cookie_jar = selenium_cookies_to_cookiejar(selenium_cookie_list)
    return httpx.AsyncClient(cookies=cookie_jar, http2=True)


def clone_httpx_async_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    """
    Clone an authenticated httpx client into a new isolated async client.
    """
    return httpx.AsyncClient(cookies=copy_cookie_jar(client.cookies.jar), http2=True)


def copy_cookie_jar(cookie_jar: CookieJar) -> CookieJar:
    cloned_jar = CookieJar()
    for cookie in cookie_jar:
        cloned_jar.set_cookie(copy(cookie))
    return cloned_jar


def selenium_cookies_to_cookiejar(selenium_cookies):
    jar = CookieJar()
    for c in selenium_cookies:
        cookie = Cookie(
            version=0,
            name=c['name'],
            value=c['value'],
            port=None,
            port_specified=False,
            domain=c.get('domain', ''),
            domain_specified=bool(c.get('domain')),
            domain_initial_dot=c.get('domain', '').startswith('.'),
            path=c.get('path', '/'),
            path_specified=True,
            secure=c.get('secure', False),
            expires=c.get('expiry'),  # None if not present
            discard=False,
            comment=None,
            comment_url=None,
            rest={},  # Could include 'HttpOnly': None
            rfc2109=False,
        )
        jar.set_cookie(cookie)
    return jar
