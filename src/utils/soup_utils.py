import requests
from bs4 import BeautifulSoup

from core.exceptions import ScraperException
from utils.utils import is_valid_url


# -------------------------------------------------
# Cook Soup - Implements Beautiful Soup HTML Parser
# -------------------------------------------------

def cook_soup(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': 'Windows'
    }

    if is_valid_url(url):
        try:
            response = requests.get(url, headers=headers, timeout=5)
        except requests.exceptions.ConnectTimeout as e:
            raise ScraperException(f"Connection timed out: timeout=5 seconds for URL: {url}") from e
        if response.status_code == 200 or (response.status_code == 500 and "mediux.pro" in url):
            soup = BeautifulSoup(response.text, 'html.parser')
            return soup
        else:
            raise ScraperException(f"Failed to retrieve the page. Status code: {response.status_code}")
    elif ".html" in url:
        with open(url, 'r', encoding='utf-8') as file:
            html_content = file.read()
            BeautifulSoup(html_content, 'html.parser')
