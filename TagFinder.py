import asyncio
import requests
from bs4 import BeautifulSoup
import logging
import os
import data_manager_json as dm

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Constants
URL_BASE = 'https://nhentai.net/tags/?page='
OUTPUT_FILE = "tags.txt"

def get_last_page():
    """Fetch the last page number of the tags section."""
    try:
        response = requests.get(URL_BASE + '1', timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        last_page = soup.find('a', class_='last').get('href')
        return int(last_page.split('=')[-1])
    except Exception as e:
        logging.error(f"Failed to fetch last page: {e}")
        return 1  # Fallback to single page

async def fetch_tags_from_page(page):
    """Fetch tags from a single page and return them as a dictionary."""
    try:
        url = f"{URL_BASE}{page}"
        response = await asyncio.to_thread(requests.get, url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        tags_container = soup.find('div', id='tag-container')
        tags = tags_container.find_all('a')
        return {
            int(tag.get('class')[-1].split('-')[-1]): tag.find('span').text
            for tag in tags
        }
    except Exception as e:
        logging.error(f"Failed to fetch tags from page {page}: {e}")
        return {}

async def tag_fetch():
    """Main function to fetch and save all tags."""
    last_page = get_last_page()
    logging.info(f"Fetching tags from {last_page} pages...")

    all_tags = {}
    tasks = [fetch_tags_from_page(page) for page in range(1, last_page + 1)]
    results = await asyncio.gather(*tasks)

    for tags in results:
        all_tags.update(tags)

    if all_tags:
        dm.write_tags(all_tags)
    else:
        logging.warning("No tags fetched. Please check the website or your connection.")
