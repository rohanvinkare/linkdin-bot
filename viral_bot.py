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

# ENVIRONMENT VARIABLES
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_URN", "").strip()
ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# High-Quality Engineering Blogs
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Configure Gemini globally
genai.configure(api_key=GEMINI_API_KEY)

# --- 1. UTILS & SAFETY ---
def mimic_human_timing():
    """Simple check to ensure we don't run too fast in production."""
    # print("🤖 Bot sleeping for safety...")
    # time.sleep(random.randint(60, 300)) # Uncomment for production
    return

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

# --- 2. DEEP FETCHING ---
def get_article_text(url):
    """Visits the site and scrapes real text paragraphs."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # Get paragraphs
        paragraphs = soup.find_all('p')
        
        # Clean the text: remove newlines inside paragraphs and join
        clean_text = " ".join([p.get_text().strip() for p in paragraphs[:20]]) # Increased to 20
        return clean_text
    except Exception as e:
        print(f"Error scraping {url}: {e}")
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
                
                # Validation: If text is too short, the scraper probably failed
                if not full_text or len(full_text) < 300:
                    print("   -> Content too short/unreadable. Skipping.")
                    continue
                
                # Get Image
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

# --- 3. AI GENERATION (THE FIX) ---
def generate_viral_post(news_item):
    """
    Generates content using the Official Gemini SDK.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # A much stricter prompt to force the summary
        prompt_text = f"""
        You are a Tech Influencer and Software Architect on LinkedIn. 
        Write a high-quality LinkedIn post about this article.
        
        ARTICLE TITLE: {news_item['title']}
        ARTICLE CONTENT: "{news_item['full_text'][:4000]}..."
        
        STRICT FORMAT REQUIREMENTS:
        1. **The Hook**: A catchy 1-sentence opening about why this news matters.
        2. **The Summary**: 3 bullet points (use emoji '🔹') summarizing the key technical takeaways.
        3. **The Insight**: A short paragraph (2 sentences) adding your professional opinion.
        4. **Call to Action**: Ask a question to drive comments.
        5. **The Link**: Place this link at the very bottom: {news_item['link']}
        6. **Tags**: #tech #programming #softwareengineering
        
        Tone: Professional, Insightful, yet accessible.
        Do not use markdown bolding (like **text**) for the body text, only for headers.
        """
        
        response = model.generate_content(prompt_text)
        
        if response.text:
            return response.text.strip()
        else:
            raise Exception("Empty response from AI")
            
    except Exception as e:
        print(f"⚠️ AI Generation Failed: {e}")
        # Fallback only if AI crashes
        return f"🔥 Just In: {news_item['title']}\n\nHere is a quick update on this topic.\n\nRead the full story: {news_item['link']}\n\n#tech #news"

# --- 4. LINKEDIN PUBLISHING ---
def post_to_linkedin(content, image_url):
    print("📤 Uploading to LinkedIn...")
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    
    asset = None
    # 1. Image Upload Process
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
            img_data = requests.get(image_url, headers=HEADERS).content
            requests.put(upload_url, data=img_data, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
            print("   -> Image uploaded successfully.")
        except Exception as e:
            print(f"⚠️ Image upload failed: {e}")
            asset = None

    # 2. Post Creation
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
    mimic_human_timing()
    
    history = load_history()
    news = fetch_fresh_news(history)
    
    if not news:
        print("❌ No valid news found today.")
        exit()
        
    print(f"🚀 Drafting post for: {news['title']}")
    
    # Generate the high-quality content
    post_text = generate_viral_post(news)
    print("------------------------------------------------")
    print("📝 GENERATED CONTENT PREVIEW:")
    print(post_text)
    print("------------------------------------------------")
    
    if post_to_linkedin(post_text, news['image_url']):
        print("✅ Posted to LinkedIn Successfully!")
        
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
        print("❌ Final Posting Failed.")