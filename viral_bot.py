import requests
import feedparser
import json
import random
import time
import os
import datetime
import re
from bs4 import BeautifulSoup
import time
import random

# --- HUMAN BEHAVIOR SIMULATION ---
print("😴 Simulating human delay...")
# Random sleep between 1 minute (60s) and 5 minutes (300s)
sleep_seconds = random.randint(60, 300)
time.sleep(sleep_seconds)
print(f"⏰ Waking up after {sleep_seconds} seconds!")


# --- CONFIGURATION ---
HISTORY_FILE = "history.json"

# Load Environment Variables
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_URN", "").strip()
ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# High-Quality Engineering Blogs (Curated for tech engagement)
RSS_FEEDS = [
    "https://feeds.feedburner.com/TheHackersNews", 
    "https://netflixtechblog.com/feed",
    "https://eng.uber.com/feed/",
    "https://aws.amazon.com/blogs/architecture/feed/",
    "https://devblogs.microsoft.com/feed/",
    "https://github.blog/feed/",
    "https://techcrunch.com/feed/",
    "https://openai.com/blog/rss/"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# --- 1. ROBUST HISTORY TRACKING ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history_data, title, link):
    """Saves the normalized link and title."""
    entry = {
        "title": title,
        "web_link": clean_url(link),
        "date": datetime.datetime.now().strftime("%Y-%m-%d")
    }
    history_data.append(entry)
    # Keep file size manageable (last 200 posts)
    if len(history_data) > 200:
        history_data = history_data[-200:]
    
    with open(HISTORY_FILE, "w") as f:
        json.dump(history_data, f, indent=4)

def clean_url(url):
    """Removes tracking parameters (?utm_source...) to ensure unique identification."""
    if "?" in url:
        return url.split("?")[0]
    return url

def is_already_posted(link, title, history_data):
    """Checks against both Title and Normalized Link."""
    normalized_link = clean_url(link)
    
    for entry in history_data:
        # Check 1: Did we post this exact URL?
        if entry.get("web_link") == normalized_link:
            return True
        # Check 2: Did we post this exact Title? (Handles URL changes)
        if entry.get("title") == title:
            return True
            
    return False

# --- 2. SMART CONTENT SCRAPER ---
def get_article_text(url):
    try:
        print(f"   ⬇️  Downloading: {url}")
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')

        # Try to find the main article content specifically
        possible_bodies = soup.select(
            '#articlebody, .article-body, .entry-content, .post-content, article, .main-content'
        )
        target_element = possible_bodies[0] if possible_bodies else soup

        # Extract text from paragraphs only to avoid menu items/footers
        paragraphs = target_element.find_all('p')
        text = " ".join([p.get_text().strip() for p in paragraphs])
        
        # Validation: If text is too short, scraping probably failed (captcha/paywall)
        if len(text) < 600:
            return None
            
        return text[:12000] # Limit input to avoid token limits
    except Exception as e:
        print(f"   ⚠️ Scraping error: {e}")
        return None

def fetch_fresh_news(history_data):
    random.shuffle(RSS_FEEDS) # Shuffle to avoid bias toward the first feed
    
    for feed_url in RSS_FEEDS:
        print(f"Checking feed: {feed_url}...")
        try:
            feed = feedparser.parse(feed_url)
        except:
            continue
            
        if not feed.entries: continue
        
        # Check the latest 5 entries from this feed
        for entry in feed.entries[:5]:
            if not is_already_posted(entry.link, entry.title, history_data):
                print(f"🔍 Found candidate: {entry.title}")
                
                full_text = get_article_text(entry.link)
                if not full_text: continue
                
                # Attempt to find a high-res image
                image_url = None
                try:
                    # Look for media_content (standard RSS) or scrape og:image
                    if 'media_content' in entry and len(entry.media_content) > 0:
                        image_url = entry.media_content[0]['url']
                    else:
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

# --- 3. VIRAL AI GENERATION (The "Hot Take" Engine) ---
def get_valid_models():
    """Finds working models automatically."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            valid_models = [
                m['name'].replace('models/', '') 
                for m in data.get('models', []) 
                if 'generateContent' in m.get('supportedGenerationMethods', [])
            ]
            # Prioritize faster/experimental models
            valid_models.sort(key=lambda x: ('flash' not in x, 'pro' not in x))
            return valid_models
        return ["gemini-2.0-flash-exp", "gemini-1.5-flash", "gemini-pro"]
    except:
        return ["gemini-2.0-flash-exp", "gemini-1.5-flash", "gemini-pro"]

def generate_viral_post(news_item):
    print("   🧠 Asking Gemini to write a viral post...")
    
    # --- VIRAL PROMPT ENGINEERING ---
    # We strip the "Journalist" persona and enforce a "Thought Leader" persona.
    prompt = f"""
    Act as a cynical, insightful Senior Staff Engineer at a top tech company.
    
    TASK: Write a LinkedIn post based on the news below.
    
    NEWS TITLE: {news_item['title']}
    NEWS CONTEXT: "{news_item['full_text'][:4000]}..."
    
    GOAL: Maximum engagement. Do not summarize the news. Analyze the *impact*.
    
    STRICT FORMATTING RULES:
    1. NO Markdown Bold (**text**). It breaks LinkedIn.
    2. NO Markdown Lists (- item). Use Emoji bullets (🔹, 👉, ⚡).
    3. Keep paragraphs short (1-2 sentences max).
    
    POST STRUCTURE:
    [Line 1: A short, provocative hook statement. 5-10 words max.]
    
    [Blank Line]
    
    [The "What Happened" - Explain the news in 1 simple sentence.]
    
    [Blank Line]
    
    👉 Why this matters:
    🔹 [Insight 1]
    🔹 [Insight 2]
    
    [Blank Line]
    
    [The "Hot Take" - A strong opinion on whether this is good/bad/overhyped.]
    
    👇 What do you think?
    
    🔗 {news_item['link']}
    
    #tech #engineering #software #news
    """

    available_models = get_valid_models()

    for model_name in available_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        
        try:
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                text = response.json()['candidates'][0]['content']['parts'][0]['text']
                
                # --- FINAL SANITIZATION ---
                # Remove any stray markdown that the AI might have slipped in
                text = text.replace("**", "") # Remove bold markers
                text = text.replace("##", "") # Remove header markers
                text = re.sub(r'^\* ', '🔹 ', text, flags=re.MULTILINE) # Convert bullets to emojis
                return text
                
            elif response.status_code == 429:
                time.sleep(5) # Wait for rate limit
                continue
        except Exception as e:
            print(f"Model {model_name} failed: {e}")
            continue

    return None

# --- 4. LINKEDIN PUBLISHING (With Fallbacks) ---
def post_to_linkedin(content, image_url):
    print("📤 Uploading to LinkedIn...")
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    
    asset = None
    
    # 1. Try to register and upload the image
    if image_url:
        try:
            print("   -> Processing image...")
            # Fetch image first to check size/validity
            img_data = requests.get(image_url, headers=HEADERS, timeout=10).content
            
            # Register
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
            
            if reg_resp.status_code == 200:
                data = reg_resp.json()
                upload_url = data['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
                asset = data['value']['asset']
                
                # Upload Binary
                u_resp = requests.put(upload_url, data=img_data, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
                if u_resp.status_code != 201:
                    print("   ⚠️ Image upload failed (Network/Auth). Posting text only.")
                    asset = None
            else:
                print("   ⚠️ Image registration failed. Posting text only.")
        except Exception as e:
            print(f"   ⚠️ Image processing error: {e}. Posting text only.")
            asset = None

    # 2. Create the Post
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
    
    if r.status_code == 201:
        return True
    else:
        print(f"❌ LinkedIn Error: {r.text}")
        return False

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print("🤖 Bot Started...")
    
    # 1. Load DB
    history = load_history()
    
    # 2. Find Content
    news = fetch_fresh_news(history)
    
    if not news:
        print("❌ No valid, unposted news found today.")
        exit()
        
    print(f"🚀 Drafting post for: {news['title']}")
    
    # 3. Generate AI Content
    post_text = generate_viral_post(news)
    
    if not post_text:
        print("❌ Failed to generate text. Exiting.")
        exit()

    print("\n--- POST PREVIEW (Sanitized) ---")
    print(post_text)
    print("--------------------------------\n")
    
    # 4. Publish & Save
    if post_to_linkedin(post_text, news['image_url']):
        print("✅ Posted to LinkedIn!")
        save_history(history, news['title'], news['link'])
    else:
        print("❌ LinkedIn API Error. History not updated.")