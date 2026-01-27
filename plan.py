import requests
import feedparser
import json
import random
import time
import os
import datetime
import re
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
HISTORY_FILE = "history.json"

# Load Environment Variables
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_URN", "").strip()
ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# --- SOURCE MANAGEMENT ---
# Group 1: Breaking News (Trends)
NEWS_FEEDS = [
    "https://feeds.feedburner.com/TheHackersNews", 
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://openai.com/blog/rss/"
]

# Group 2: Deep Engineering Concepts (System Design, DevOps, LLD)
ENGINEERING_FEEDS = [
    "https://netflixtechblog.com/feed",           # System Design at Scale
    "https://eng.uber.com/feed/",                 # High load systems
    "https://aws.amazon.com/blogs/architecture/feed/", # Cloud/DevOps
    "https://github.blog/feed/",                  # DevOps/CI-CD
    "https://blog.bytebytego.com/feed",           # Pure System Design (Alex Xu)
    "https://martinfowler.com/feed.atom",         # Architecture Patterns
    "https://slack.engineering/feed/",            # Real world LLD
    "https://engineering.linkedin.com/blog.rss"   # Data Engineering
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# --- 1. UTILS & HISTORY ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history_data, title, link):
    entry = {
        "title": title,
        "web_link": clean_url(link),
        "date": datetime.datetime.now().strftime("%Y-%m-%d")
    }
    history_data.append(entry)
    if len(history_data) > 200:
        history_data = history_data[-200:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history_data, f, indent=4)

def clean_url(url):
    if "?" in url:
        return url.split("?")[0]
    return url

def is_already_posted(link, title, history_data):
    normalized_link = clean_url(link)
    for entry in history_data:
        if entry.get("web_link") == normalized_link: return True
        if entry.get("title") == title: return True
    return False

# --- 2. INTELLIGENT SCRAPER ---
def get_article_text(url):
    try:
        print(f"   ⬇️  Downloading: {url}")
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # Smart selector for different blog types
        possible_bodies = soup.select(
            'article, .post-content, .entry-content, #article-body, .gh-content, .main-content'
        )
        target = possible_bodies[0] if possible_bodies else soup
        
        paragraphs = target.find_all(['p', 'h2', 'li'])
        text = "\n".join([p.get_text().strip() for p in paragraphs])
        
        if len(text) < 600: return None
        return text[:15000]
    except Exception as e:
        print(f"   ⚠️ Scraping error: {e}")
        return None

def fetch_content(history_data):
    # RANDOM DECISION: 50% News, 50% Engineering Concept
    mode = "CONCEPT" if random.random() > 0.5 else "NEWS"
    sources = ENGINEERING_FEEDS if mode == "CONCEPT" else NEWS_FEEDS
    
    print(f"🎲 Mode Selected: {mode}")
    random.shuffle(sources)
    
    for feed_url in sources:
        print(f"Checking feed: {feed_url}...")
        try:
            feed = feedparser.parse(feed_url)
        except: continue
            
        if not feed.entries: continue
        
        for entry in feed.entries[:5]:
            if not is_already_posted(entry.link, entry.title, history_data):
                print(f"🔍 Found candidate: {entry.title}")
                full_text = get_article_text(entry.link)
                if not full_text: continue
                
                # Try to find image
                image_url = None
                try:
                    if 'media_content' in entry and entry.media_content:
                        image_url = entry.media_content[0]['url']
                    else:
                        r = requests.get(entry.link, headers=HEADERS, timeout=5)
                        s = BeautifulSoup(r.content, 'html.parser')
                        meta = s.find("meta", property="og:image")
                        if meta: image_url = meta["content"]
                except: pass

                return {
                    "type": mode, 
                    "title": entry.title,
                    "link": entry.link,
                    "full_text": full_text,
                    "image_url": image_url
                }
    return None

# --- 3. ROBUST AI ENGINE ---
def fetch_available_models():
    """Dynamically asks Google which models are enabled for this API key."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # Filter for models that support generating content
            models = [
                m['name'].replace('models/', '') 
                for m in data.get('models', []) 
                if 'generateContent' in m.get('supportedGenerationMethods', [])
            ]
            # Sort to prefer flash (faster/cheaper)
            models.sort(key=lambda x: ('flash' not in x, 'pro' in x))
            return models
    except Exception as e:
        print(f"   ⚠️ Could not fetch dynamic models: {e}")
    
    # Fallback list if dynamic fetch fails
    return ["gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-1.0-pro", "gemini-2.0-flash-exp"]

def generate_viral_post(content_item):
    print("   🧠 Asking Gemini to write the post...")
    
    # --- PROMPT SELECTION ---
    if content_item['type'] == "CONCEPT":
        prompt = f"""
        Act as a Principal Software Architect.
        The user is an engineer wanting to learn System Design/DevOps.
        
        TOPIC: {content_item['title']}
        SOURCE TEXT: "{content_item['full_text'][:5000]}..."
        
        GOAL: Simplify this complex concept into a "Cheat Sheet" style post.
        
        RULES:
        1. Start with a "Did you know?" or "Stop doing this" hook.
        2. Use a "Problem -> Solution" structure.
        3. Use Diagrammatic emojis (e.g., 📱 -> ☁️ -> 💾) to explain the flow.
        4. No markdown bold (**). Use 🔹 or 👉.
        
        FORMAT:
        [Hook: One sentence summary of the architecture/concept]
        
        [Blank Line]
        
        How it actually works:
        1️⃣ [Step 1]
        2️⃣ [Step 2]
        3️⃣ [Step 3]
        
        [Blank Line]
        
        💡 Key Takeaway:
        [One powerful insight for interviews or production]
        
        👇 Have you used this pattern?
        
        🔗 {content_item['link']}
        
        #systemdesign #devops #architecture #coding
        """
        
    else: # NEWS MODE
        prompt = f"""
        Act as a Senior Tech Lead giving a "Hot Take" on industry news.
        
        NEWS: {content_item['title']}
        CONTEXT: "{content_item['full_text'][:4000]}..."
        
        GOAL: Spark debate. Don't just report, analyze impact.
        
        RULES:
        1. Short, punchy sentences.
        2. No markdown bold (**).
        3. Focus on "What this means for engineers".
        
        FORMAT:
        [ provocative hook ]
        
        [Blank Line]
        
        [Summary in 1 sentence]
        
        [Blank Line]
        
        👉 Why it matters:
        🔹 [Insight 1]
        🔹 [Insight 2]
        
        [Blank Line]
        
        [Your cynicism/opinion on the future of this]
        
        👇 Thoughts?
        
        🔗 {content_item['link']}
        
        #tech #news #engineering
        """

    # --- EXECUTION ---
    valid_models = fetch_available_models()
    print(f"   ℹ️  Available models from API: {valid_models}")

    for model in valid_models:
        print(f"   👉 Attempting with: {model}")
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            headers = {"Content-Type": "application/json"}
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            
            resp = requests.post(url, headers=headers, json=payload)
            
            if resp.status_code == 200:
                try:
                    text = resp.json()['candidates'][0]['content']['parts'][0]['text']
                    # Sanitize
                    text = text.replace("**", "").replace("##", "")
                    text = re.sub(r'^\* ', '🔹 ', text, flags=re.MULTILINE)
                    return text
                except KeyError:
                    print(f"   ⚠️  Model {model} returned empty content (Safety Filter?). Response: {resp.text}")
                    continue
            else:
                print(f"   ❌ Error {resp.status_code}: {resp.text}")
                
                # Handling Quota Limits (Error 429)
                if resp.status_code == 429:
                    print("   ⏳ Quota exceeded. Waiting 60 seconds before trying next model...")
                    time.sleep(60) 
                continue
                
        except Exception as e:
            print(f"   ⚠️  Exception with {model}: {e}")
            continue

    print("❌ All models failed to generate content.")
    return None

# --- 4. LINKEDIN POSTING ---
def post_to_linkedin(content, image_url):
    print("📤 Uploading to LinkedIn...")
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"}
    
    asset = None
    if image_url:
        try:
            # Register Upload
            reg = requests.post("https://api.linkedin.com/v2/assets?action=registerUpload", headers=headers, json={
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": LINKEDIN_PERSON_URN,
                    "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]
                }
            })
            if reg.status_code == 200:
                upload_url = reg.json()['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
                asset = reg.json()['value']['asset']
                # Upload Image
                requests.put(upload_url, data=requests.get(image_url, headers=HEADERS).content, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
        except: pass

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

# --- MAIN ---
if __name__ == "__main__":
    print("🤖 Bot Started...")
    
    # FIX: Correct sleep range
    print("😴 Simulating human behavior...")
    sleep_time = random.randint(60, 120) 
    print(f"   -> Sleeping for {sleep_time} seconds...")
    time.sleep(sleep_time)
    
    # 2. Load & Fetch
    history = load_history()
    content = fetch_content(history)
    
    if not content:
        print("❌ No content found.")
        exit()
        
    # 3. Generate
    post_text = generate_viral_post(content)
    if not post_text: exit()
    
    # 4. Post
    print("\n--- PREVIEW ---")
    print(post_text)
    if post_to_linkedin(post_text, content['image_url']):
        print("✅ Success!")
        save_history(history, content['title'], content['link'])
    else:
        print("❌ Failed.")