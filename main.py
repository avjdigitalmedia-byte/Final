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
        
        Actor.log.info(f'Step 1: Searching for hashtag: {hashtag} to find users...')

        # 2. Call Instagram Scraper (to get posts and usernames)
        try:
            run_posts = await Actor.call('apify/instagram-scraper', {
                "resultsType": "posts",
                "search": hashtag,
                "searchType": "hashtag",
                "searchLimit": max_posts,
                "proxy": { "useApifyProxy": True }
            })
        except Exception as e:
            Actor.log.error(f'Failed to call instagram-scraper: {e}')
            return

        if run_posts.status != 'SUCCEEDED':
            Actor.log.error(f'Instagram Scraper run failed with status: {run_posts.status}')
            return
        
        # 3. Extract Usernames
        dataset_client = Actor.new_client().dataset(run_posts.default_dataset_id)
        items_page = await dataset_client.list_items()
        
        usernames = set()
        for item in items_page.items:
            # Try different locations for username
            u = item.get('owner', {}).get('username') or item.get('username')
            if u:
                usernames.add(u)
        
        if not usernames:
            Actor.log.warning("No usernames found in the posts.")
            return

        Actor.log.info(f"Step 2: Found {len(usernames)} unique users. Scraping their profiles now...")

        # 4. Scrape PROFILES (This is the new step)
        # We use 'apify/instagram-profile-scraper' (or similar)
        # Note: We pass the list of usernames directly
        try:
            run_profiles = await Actor.call('apify/instagram-profile-scraper', {
                "usernames": list(usernames),
                "proxy": { "useApifyProxy": True }
            })
        except Exception as e:
            Actor.log.error(f"Failed to scrape profiles: {e}")
            return

        if run_profiles.status != 'SUCCEEDED':
            Actor.log.error(f'Profile Scraper run failed. Status: {run_profiles.status}')
            return

        # 5. Process Profile Results
        profile_dataset_client = Actor.new_client().dataset(run_profiles.default_dataset_id)
        profile_items = await profile_dataset_client.list_items()
        
        emails_found = 0
        
        for profile in profile_items.items:
            username = profile.get('username')
            biography = profile.get('biography', '') or profile.get('highlight_reel_count', '') # Fallback
            full_name = profile.get('fullName')
            # Look for external link in profile
            external_url = profile.get('externalUrl')
            
            Actor.log.info(f"Analyzing profile: @{username}")

            # 1. Emails in Bio
            emails = extract_emails(biography)
            source = "Bio Text"

            # 2. Deep Search (Link in Bio)
            if external_url and not emails:
                Actor.log.info(f"  -> Deep searching Link-in-Bio: {external_url}")
                found_emails = scrape_bio_link(external_url)
                if found_emails:
                    emails = found_emails
                    source = f"Link in Bio ({external_url})"
            
            if emails:
                Actor.log.info(f"SUCCESS: Found ({len(emails)}) email(s) for @{username}!")
                result = {
                    "username": username,
                    "full_name": full_name,
                    "profile_url": f"https://instagram.com/{username}",
                    "email": emails[0],
                    "all_emails": emails,
                    "source": source,
                    "hashtag_searched": hashtag,
                    "followers": profile.get('followersCount'),
                    "bio": biography
                }
                await Actor.push_data(result)
                emails_found += 1
            else:
                Actor.log.info(f"  -> No email found.")

        Actor.log.info(f"Done! Scanned {len(usernames)} profiles. Found emails for {emails_found} creators.")

if __name__ == '__main__':
    # This is needed for local execution compatibility
    asyncio.run(main())
