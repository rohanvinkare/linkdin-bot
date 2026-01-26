import requests
import feedparser
import json
import random
import time
import os
import datetime
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
HISTORY_FILE = "history.json"

# Load Environment Variables
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_URN", "").strip()
ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# High-Quality Engineering Blogs
RSS_FEEDS = [
    "https://feeds.feedburner.com/TheHackersNews", 
    "https://netflixtechblog.com/feed",
    "https://eng.uber.com/feed/",
    "https://aws.amazon.com/blogs/architecture/feed/",
    "https://devblogs.microsoft.com/feed/",
    "https://github.blog/feed/",
    "https://techcrunch.com/feed/"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# --- 1. UTILS ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history_data, new_entry):
    history_data.append(new_entry)
    if len(history_data) > 100:
        history_data = history_data[-100:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history_data, f, indent=4)

def is_already_posted(link, history_data):
    for entry in history_data:
        if entry.get("web_link") == link:
            return True
    return False

# --- 2. SMART SCRAPER ---
def get_article_text(url):
    """
    Intelligently finds the main article body.
    """
    try:
        print(f"   ⬇️  Downloading: {url}")
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')

        # Try finding specific "article body" containers
        possible_bodies = soup.select(
            '#articlebody, .article-body, .entry-content, .post-content, article, .main-content'
        )
        target_element = possible_bodies[0] if possible_bodies else soup

        # Extract text
        paragraphs = target_element.find_all('p')
        text = " ".join([p.get_text().strip() for p in paragraphs])
        
        if len(text) < 500:
            print(f"   ⚠️  Warning: Scraped text is too short ({len(text)} chars). Skipping.")
            return None
            
        return text[:15000] 
    except Exception as e:
        print(f"   ❌ Scraping Error: {e}")
        return None

def fetch_fresh_news(history_data):
    random.shuffle(RSS_FEEDS)
    
    for feed_url in RSS_FEEDS:
        print(f"Checking feed: {feed_url}...")
        try:
            feed = feedparser.parse(feed_url)
        except:
            continue
            
        if not feed.entries: continue
        
        for entry in feed.entries[:3]:
            if not is_already_posted(entry.link, history_data):
                print(f"🔍 Found candidate: {entry.title}")
                full_text = get_article_text(entry.link)
                
                if not full_text: continue
                
                image_url = None
                try:
                    r = requests.get(entry.link, headers=HEADERS, timeout=5)
                    soup = BeautifulSoup(r.content, 'html.parser')
                    meta = soup.find("meta", property="og:image")
                    if meta: image_url = meta["content"]
                except: pass

                return {
                    "title": entry.title,
                    "link": entry.link,
                    "full_text": full_text,
                    "image_url": image_url
                }
    return None

# --- 3. AI GENERATION (DIRECT REST API - NO LIBRARY NEEDED) ---
def generate_viral_post(news_item):
    print("   🧠 Asking Gemini to write the post...")
    
    # We use the REST API directly to bypass the library error
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""
    You are a professional Tech Journalist. Write a LinkedIn post summarizing this article.
    
    HEADLINE: {news_item['title']}
    CONTENT: "{news_item['full_text'][:6000]}..."
    
    STRICT OUTPUT FORMAT:
    1. Start with a catchy one-sentence Hook.
    2. Add "💡 The Gist:" followed by 3 short bullet points summarizing the technical details.
    3. Add "📉 Why it Matters:" followed by one sentence on the impact.
    4. End with a Question to the audience.
    5. Place this link at the very end: {news_item['link']}
    6. Tags: #tech #news #engineering
    """
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            result = response.json()
            return result['candidates'][0]['content']['parts'][0]['text']
        else:
            print(f"   🚨 API Error {response.status_code}: {response.text}")
            return None
            
    except Exception as e:
        print(f"   🚨 Connection Error: {e}")
        return None

# --- 4. LINKEDIN PUBLISHING ---
def post_to_linkedin(content, image_url):
    print("📤 Uploading to LinkedIn...")
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    
    asset = None
    if image_url:
        try:
            print("   -> Registering image...")
            reg_resp = requests.post(
                "https://api.linkedin.com/v2/assets?action=registerUpload",
                headers=headers,
                json={
                    "registerUploadRequest": {
                        "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                        "owner": LINKEDIN_PERSON_URN,
                        "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]
                    }
                }
            )
            data = reg_resp.json()
            upload_url = data['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
            asset = data['value']['asset']
            
            print("   -> Uploading image binary...")
            requests.put(upload_url, data=requests.get(image_url, headers=HEADERS).content, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
            print("   -> Image uploaded.")
        except:
            print("⚠️ Image upload failed. Posting text only.")
            asset = None

    post_body = {
        "author": LINKEDIN_PERSON_URN,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": "IMAGE" if asset else "NONE",
                "media": [{"status": "READY", "media": asset}] if asset else []
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    
    r = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=post_body)
    return r.status_code == 201

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print("🤖 Bot Started...")
    
    history = load_history()
    news = fetch_fresh_news(history)
    
    if not news:
        print("❌ No valid news found today.")
        exit()
        
    print(f"🚀 Drafting post for: {news['title']}")
    post_text = generate_viral_post(news)
    
    if not post_text:
        print("❌ Failed to generate text. Exiting.")
        exit()

    print("\n--- POST PREVIEW ---")
    print(post_text)
    print("--------------------\n")
    
    if post_to_linkedin(post_text, news['image_url']):
        print("✅ Posted to LinkedIn!")
        save_history(history, {
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "day": datetime.datetime.now().strftime("%A"),
            "article_name": news['title'],
            "web_link": news['link']
        })
    else:
        print("❌ LinkedIn API Error.")