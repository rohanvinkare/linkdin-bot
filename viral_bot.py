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
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_URN", "").strip()
LINKEDIN_ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# --- FALLBACK IMAGES ---
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1558494949-ef526b0042a0", 
    "https://images.unsplash.com/photo-1518770660439-4636190af475", 
    "https://images.unsplash.com/photo-1555099962-4199c345e5dd", 
    "https://images.unsplash.com/photo-1531403009284-440f080d1e12", 
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa"  
]

# --- SOURCES ---
NEWS_FEEDS = [
    "https://feeds.feedburner.com/TheHackersNews", 
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml"
]

ENGINEERING_FEEDS = [
    "https://netflixtechblog.com/feed",           
    "https://eng.uber.com/feed/",                 
    "https://aws.amazon.com/blogs/architecture/feed/", 
    "https://blog.bytebytego.com/feed",           
    "https://martinfowler.com/feed.atom",         
    "https://slack.engineering/feed/",            
    "https://engineering.fb.com/feed/",
    "https://shopify.engineering/blog/feed",
    "https://engineering.linkedin.com/blog.rss"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# --- UTILS ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f: return json.load(f)
        except: return []
    return []

def save_history(history_data, title, link):
    entry = {"title": title, "web_link": link.split("?")[0], "date": datetime.datetime.now().strftime("%Y-%m-%d")}
    history_data.append(entry)
    if len(history_data) > 200: history_data = history_data[-200:]
    with open(HISTORY_FILE, "w") as f: json.dump(history_data, f, indent=4)

def is_already_posted(link, title, history_data):
    clean_link = link.split("?")[0]
    for entry in history_data:
        if entry.get("web_link") == clean_link or entry.get("title") == title: return True
    return False

def clean_text_for_linkedin(text):
    text = text.replace("**", "").replace("__", "").replace("##", "")
    text = re.sub(r'^[\*\-]\s+', '🔹 ', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# --- DYNAMIC MODEL SELECTOR (THE FIX) ---
def get_valid_model_name():
    """Asks Google which models are actually available to avoid 404s"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # Find any model that supports 'generateContent'
            available_models = [
                m['name'].replace("models/", "") 
                for m in data.get('models', []) 
                if 'generateContent' in m.get('supportedGenerationMethods', [])
            ]
            
            # Prefer Flash, then Pro, then anything else
            if "gemini-1.5-flash" in available_models: return "gemini-1.5-flash"
            if "gemini-1.5-flash-latest" in available_models: return "gemini-1.5-flash-latest"
            if "gemini-1.0-pro" in available_models: return "gemini-1.0-pro"
            
            # If none of the specific ones exist, return the first available one
            if available_models:
                print(f"   ⚠️ Preferred model not found. Using fallback: {available_models[0]}")
                return available_models[0]
                
    except Exception as e:
        print(f"   ⚠️ Could not fetch model list: {e}")
    
    # Absolute fallback if everything fails
    return "gemini-1.5-flash-latest"

# --- INTELLIGENT SCRAPER ---
def get_article_details(url, mode):
    try:
        print(f"   ⬇️  Scraping: {url}")
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        
        possible_bodies = soup.select('article, .post-content, .entry-content, #article-body, .gh-content')
        target = possible_bodies[0] if possible_bodies else soup
        text = "\n".join([p.get_text().strip() for p in target.find_all(['p', 'h2'])])
        
        if len(text) < 600: return None
        
        image_url = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"): 
            image_url = og_image["content"]
            
        if not image_url:
            first_img = target.find('img')
            if first_img and first_img.get('src'):
                src = first_img['src']
                if src.startswith('http'): 
                    image_url = src
        
        if not image_url and mode == "CONCEPT":
            print("   ⚠️ No image found. Using Fallback.")
            image_url = random.choice(FALLBACK_IMAGES)
        
        if not image_url:
            print("   ⚠️ No image found. SKIP.")
            return None 
            
        return {"text": text[:12000], "image": image_url}
        
    except Exception as e:
        print(f"   ⚠️ Error: {e}")
        return None

def fetch_content(history_data):
    mode = "CONCEPT" if random.random() > 0.15 else "NEWS"
    sources = ENGINEERING_FEEDS if mode == "CONCEPT" else NEWS_FEEDS
    random.shuffle(sources)
    
    print(f"🎲 Mode Selected: {mode}")
    
    for feed_url in sources:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:3]:
                if is_already_posted(entry.link, entry.title, history_data): continue
                details = get_article_details(entry.link, mode)
                if not details: continue 
                return {
                    "type": mode,
                    "title": entry.title,
                    "link": entry.link,
                    "full_text": details["text"],
                    "image_url": details["image"]
                }
        except: continue
    return None

# --- AI WRITER ---
def generate_viral_post(content_item):
    # 1. Dynamically get the correct model name
    valid_model = get_valid_model_name()
    print(f"   🧠 Asking Gemini ({valid_model})...")
    
    if not GEMINI_API_KEY:
        print("   ❌ ERROR: GEMINI_API_KEY is missing!")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{valid_model}:generateContent?key={GEMINI_API_KEY}"
    
    base_structure = """
    STRICT FORMATTING RULES:
    1. NO Markdown bold (**). Use CAPS for emphasis if needed.
    2. NO Paragraph blocks. Use bullet points.
    3. Use these emojis: 🔹, 👉, 🚀, ⚠️.
    """
    
    if content_item['type'] == "CONCEPT":
        prompt = f"""
        Act as a Principal Staff Engineer.
        Topic: {content_item['title']}
        Context: {content_item['full_text'][:5000]}
        {base_structure}
        OUTPUT FORMAT:
        [Counter-intuitive Hook Question]
        
        [Brief Context]
        
        The Architecture:
        🔹 [Point 1]
        🔹 [Point 2]
        
        The Trade-offs:
        ⚠️ [Risk/Con]
        🚀 [Benefit/Pro]
        
        [1-line Conclusion]
        
        🔗 {content_item['link']}
        #systemdesign #engineering
        """
    else: 
        prompt = f"""
        Act as a Cynical Tech Lead.
        News: {content_item['title']}
        Context: {content_item['full_text'][:4000]}
        {base_structure}
        OUTPUT FORMAT:
        [ provocative hook ]
        👉 The TL;DR:
        🔹 [Fact 1]
        🔹 [Fact 2]
        👉 Why it matters:
        🔹 [Engineering Impact 1]
        🔹 [Market Impact 2]
        [Cynical 1-line take]
        🔗 {content_item['link']}
        #tech #news
        """

    try:
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": prompt}]}]})
        
        if resp.status_code != 200:
            print(f"   ❌ GOOGLE API ERROR {resp.status_code}: {resp.text}")
            return None

        text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        return clean_text_for_linkedin(text)

    except Exception as e:
        print(f"   ❌ EXCEPTION: {e}")
    return None

# --- POSTER ---
def post_to_linkedin(content, image_url):
    print(f"   📤 Uploading Image: {image_url}")
    try:
        img_data = requests.get(image_url, headers=HEADERS, timeout=10).content
    except:
        print("   ❌ Failed to download image.")
        return False
    
    reg = requests.post(
        "https://api.linkedin.com/v2/assets?action=registerUpload",
        headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}"},
        json={
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": LINKEDIN_PERSON_URN,
                "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]
            }
        }
    )
    
    if reg.status_code != 200: 
        print(f"   ❌ LinkedIn Upload Error: {reg.text}")
        return False
    
    upload_url = reg.json()['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
    asset = reg.json()['value']['asset']
    
    up = requests.put(upload_url, data=img_data, headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}"})
    if up.status_code != 201: return False
    
    post_body = {
        "author": LINKEDIN_PERSON_URN,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": "IMAGE",
                "media": [{"status": "READY", "media": asset}]
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    
    final = requests.post("https://api.linkedin.com/v2/ugcPosts", headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}"}, json=post_body)
    return final.status_code == 201

# --- MAIN ---
if __name__ == "__main__":
    print("🤖 Bot Started...")
    history = load_history()
    posted_successfully = False
    
    for attempt in range(1, 6):
        if posted_successfully: break
        print(f"\n--- Attempt {attempt}/5 ---")
        
        content = fetch_content(history)
        if not content: 
            print("   -> No content found.")
            continue 
            
        post_text = generate_viral_post(content)
        if not post_text: 
            continue 
        
        print("\n--- PREVIEW ---")
        print(post_text)
        print("--- END PREVIEW ---")
        
        if post_to_linkedin(post_text, content['image_url']):
             print("✅ Posted Successfully!")
             save_history(history, content['title'], content['link'])
             posted_successfully = True
        else:
             print("❌ API Post failed. Retrying...")
             time.sleep(5)