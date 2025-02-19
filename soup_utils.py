import sys
import requests
from bs4 import BeautifulSoup

# -------------------------------------------------
# Cook Soup - Implements Beautiful Soup HTML Parser
# -------------------------------------------------

def cook_soup(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': 'Windows'
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200 or (response.status_code == 500 and "mediux.pro" in url):
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup
    else:
        sys.exit(f"x Failed to retrieve the page. Status code: {response.status_code}")