from apify import Actor
import requests
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import asyncio

# Function to extract emails from text
def extract_emails(text):
    if not text:
        return []
    # Regex for finding emails
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    return list(set(re.findall(email_pattern, text)))

# Function to scrape 'Link in Bio' page
def scrape_bio_link(url):
    try:
        # Add headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 1. Look for mailto links
            mailto_emails = []
            for a in soup.find_all('a', href=True):
                if a['href'].startswith('mailto:'):
                    mailto_emails.append(a['href'].replace('mailto:', '').split('?')[0])
            
            # 2. Look for emails in text
            text_emails = extract_emails(soup.get_text())
            
            return list(set(mailto_emails + text_emails))
    except Exception as e:
        print(f"Failed to scrape {url}: {e}")
    return []

async def main():
    async with Actor:
        Actor.log.info('Starting Creator Email Deep Search...')
        
        # 1. Get Input
        actor_input = await Actor.get_input() or {}
        hashtag = actor_input.get('hashtag', 'mortgage')
        max_posts = actor_input.get('max_posts', 20)
        
        Actor.log.info(f'Searching for hashtag: {hashtag} with limit: {max_posts}')

        # 2. Call Instagram Scraper (using 'apify/instagram-scraper')
        # We start the scraper and wait for it to finish
        try:
            Actor.log.info('Calling apify/instagram-scraper...')
            run = await Actor.call('apify/instagram-scraper', {
                "resultsType": "posts",
                "search": hashtag,
                "searchType": "hashtag",
                "searchLimit": max_posts,
                "proxy": { "useApifyProxy": True }
            })
        except Exception as e:
            Actor.log.error(f'Failed to call instagram-scraper: {e}')
            return

        if run.get('status') != 'SUCCEEDED':
            Actor.log.error(f'Instagram Scraper run failed with status: {run.get("status")}')
            return
        
        # 3. Process Results
        dataset_id = run['defaultDatasetId']
        Actor.log.info(f"Processing results from run {run['id']} (Dataset: {dataset_id})...")
        dataset_client = Actor.new_client().dataset(dataset_id)
        
        profiles_processed = 0
        emails_found = 0
        
        # Fetch all items to avoid async iterator issues if any
        items_page = await dataset_client.list_items()
        item_list = items_page.items
        Actor.log.info(f"Retrieved {len(item_list)} items from Instagram Scraper.")

        if len(item_list) == 0:
            Actor.log.warning("No posts found! The instagram-scraper might have been blocked or returned no results.")
        
        for item in item_list:
            # Get user info from the post object
            owner = item.get('owner', {})
            username = owner.get('username')
            
            # Fallback for different data structures
            if not username:
                username = item.get('username')
            
            if not username:
                continue

            full_name = owner.get('full_name') or item.get('fullName')
            # Note: For 'posts' results, this is usually the POST CAPTION, not the user bio.
            biography = item.get('caption', '') 
            
            Actor.log.info(f"Checking post by @{username}...")

            # Check caption for emails
            emails = extract_emails(biography)
            source = "Caption Text"
            
            # Simple link extraction from caption (since we don't have profile bio link here)
            external_url = None
            if biography:
                urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', biography)
                if urls:
                    external_url = urls[0]
            
            # Deep Search
            if external_url and not emails:
                Actor.log.info(f"Deep searching link for {username}: {external_url}")
                found_emails = scrape_bio_link(external_url)
                if found_emails:
                    emails = found_emails
                    source = f"Link in Caption ({external_url})"
            
            if emails:
                Actor.log.info(f"SUCCESS: Found email for {username}: {emails[0]}")
                result = {
                    "username": username,
                    "full_name": full_name,
                    "profile_url": f"https://instagram.com/{username}",
                    "email": emails[0],
                    "all_emails": emails,
                    "source": source,
                    "hashtag_used": hashtag,
                    "post_url": item.get('url')
                }
                await Actor.push_data(result)
                emails_found += 1
            else:
                Actor.log.info(f"No email found for {username} in this post/caption.")

            profiles_processed += 1
                
        Actor.log.info(f"Done! Scanned {profiles_processed} posts. Found emails for {emails_found} profiles.")

if __name__ == '__main__':
    # This is needed for local execution compatibility
    asyncio.run(main())
