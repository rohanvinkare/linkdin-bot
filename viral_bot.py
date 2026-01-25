import requests
import feedparser
import json
import random
import time
import os
import datetime
import google.generativeai as genai
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
HISTORY_FILE = "history.json"

# ADD .strip() TO ALL OF THESE LINES:
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_URN", "").strip()
ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# High-Quality Engineering Blogs (The "Authentic" Sources)
RSS_FEEDS = [
    "https://netflixtechblog.com/feed",
    "https://eng.uber.com/feed/",
    "https://engineering.fb.com/feed/",
    "https://aws.amazon.com/blogs/architecture/feed/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://devblogs.microsoft.com/feed/",
    "https://github.blog/feed/",
    "https://stackoverflow.blog/feed/",
    "https://techcrunch.com/feed/"
]

# Browser headers so websites don't block our scraper
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

genai.configure(api_key=GEMINI_API_KEY)

# # --- 1. SAFETY: MIMIC HUMAN BEHAVIOR ---
# def mimic_human_timing():
#     """Sleeps for 5-45 minutes to avoid 'bot' patterns."""
#     print("🤖 Bot started. Initiating human mimicry...")
#     sleep_seconds = random.randint(300, 2700) 
#     minutes = sleep_seconds // 60
#     print(f"😴 Sleeping for {minutes} minutes before posting...")
#     time.sleep(sleep_seconds)
#     print("⏰ Waking up! Ready to work.")


# --- 1. SAFETY: MIMIC HUMAN BEHAVIOR ---
def mimic_human_timing():
    """TEST MODE: Sleep disabled."""
    print("🤖 TEST MODE: Skipping sleep to run immediately.")
    # time.sleep(random.randint(300, 2700))  <-- COMMENT THIS OUT
    return


# --- 2. DATABASE: JSON HISTORY ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history_data, new_entry):
    """Adds the new post with Date, Day, and Title."""
    history_data.append(new_entry)
    # Keep file size manageable (last 100 posts)
    if len(history_data) > 100:
        history_data = history_data[-100:]
        
    with open(HISTORY_FILE, "w") as f:
        json.dump(history_data, f, indent=4)

def is_already_posted(link, history_data):
    # Check if this link exists in our JSON list
    for entry in history_data:
        if entry.get("web_link") == link:
            return True
    return False

# --- 3. DEEP FETCHING (The "Pro" Upgrade) ---
def get_article_text(url):
    """Visits the site and scrapes real text paragraphs."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        # Get first 15 paragraphs to ensure we have context
        paragraphs = soup.find_all('p')
        text = " ".join([p.get_text() for p in paragraphs[:15]])
        return text.strip()
    except:
        return None

def fetch_fresh_news(history_data):
    random.shuffle(RSS_FEEDS)
    
    for feed_url in RSS_FEEDS:
        print(f"Checking feed: {feed_url}...")
        feed = feedparser.parse(feed_url)
        if not feed.entries: continue
        
        for entry in feed.entries[:3]:
            if not is_already_posted(entry.link, history_data):
                print(f"🔍 Found candidate: {entry.title}")
                
                # Get the Full Context (Deep Scrape)
                full_text = get_article_text(entry.link)
                if not full_text or len(full_text) < 200:
                    print("   -> Content too short/unreadable. Skipping.")
                    continue
                
                # Get Image (Optional)
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

# --- 4. AI CONTENT GENERATION ---
def generate_viral_post(news_item):
    model = genai.GenerativeModel('gemini-pro')
    
    prompt = f"""
    Act as a Senior Software Architect. Read this technical article context:
    "{news_item['full_text'][:2500]}..."
    
    Write a LinkedIn post.
    Rules:
    1. Start with a Hook (a specific technical insight or "Hot Take").
    2. Explain WHY this matters to developers in 1-2 sentences.
    3. Use bullet points if listing features.
    4. End with a thought-provoking question.
    5. Link: {news_item['link']}
    6. Tags: #tech #engineering #learning
    7. Keep it under 200 words.
    """
    return model.generate_content(prompt).text

# --- 5. LINKEDIN PUBLISHING ---
def post_to_linkedin(content, image_url):
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    
    # Register & Upload Image (If available)
    asset = None
    if image_url:
        try:
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
            
            requests.put(upload_url, data=requests.get(image_url, headers=HEADERS).content, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
        except:
            print("⚠️ Image upload failed. Posting text only.")
            asset = None

    # Create Post
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
    mimic_human_timing()
    
    history = load_history()
    news = fetch_fresh_news(history)
    
    if not news:
        print("❌ No valid news found today.")
        exit()
        
    print(f"🚀 Drafting post for: {news['title']}")
    post_text = generate_viral_post(news)
    
    if post_to_linkedin(post_text, news['image_url']):
        print("✅ Posted to LinkedIn!")
        
        # Create Detailed History Entry
        now = datetime.datetime.now()
        new_record = {
            "date": now.strftime("%Y-%m-%d"),
            "day": now.strftime("%A"),
            "article_name": news['title'],
            "web_link": news['link']
        }
        
        save_history(history, new_record)
        print("📁 History Updated.")
    else:
        print("❌ LinkedIn API Error.")