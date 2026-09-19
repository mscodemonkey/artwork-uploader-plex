import threading

import requests
from bs4 import BeautifulSoup
from core.exceptions import ScraperException
from utils.utils import is_valid_url

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': 'Windows'
}

# One session per thread, so urllib3 keeps the connection alive between pages of the same host
# and only the first page of a crawl pays for the TCP connection and the TLS handshake. A user
# crawl walks many pages, and a bulk import walks many users. Per thread rather than one shared
# session because requests.Session is documented as not thread safe, and a webhook import can
# run alongside a bulk import. A crawl runs on one thread, so the reuse still covers it.
_sessions = threading.local()


def _session():
    session = getattr(_sessions, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(BROWSER_HEADERS)
        _sessions.session = session
    return session


# -------------------------------------------------
# Cook Soup - Implements Beautiful Soup HTML Parser
# -------------------------------------------------

def cook_soup(url):
    if is_valid_url(url):
        try:
            response = _session().get(url, timeout=5)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            raise ScraperException(f"Connection timed out (5 seconds) for URL: {url}")
        except requests.exceptions.ConnectionError:
            raise ScraperException(f"Could not connect to server, check your internet connection or the site's status")
        except requests.exceptions.HTTPError as e:
            if response.status_code == 500 and "mediux.pro" in url:
                pass
            else:
                raise ScraperException(f"Site returned an error (Status: {response.status_code})")
        except requests.exceptions.RequestException as e:
            raise ScraperException(f"Network error: {type(e).__name__}")
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup

    elif ".html" in url:
        with open(url, 'r', encoding='utf-8') as file:
            html_content = file.read()
            soup = BeautifulSoup(html_content, 'html.parser')

