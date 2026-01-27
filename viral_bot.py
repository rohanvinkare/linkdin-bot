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

# --- FALLBACK IMAGES (For Concepts that lack images) ---
# These are royalty-free Unsplash images of servers, code, and whiteboards.
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1558494949-ef526b0042a0", # Servers
    "https://images.unsplash.com/photo-1518770660439-4636190af475", # Chip/Circuit
    "https://images.unsplash.com/photo-1555099962-4199c345e5dd", # Code screen
    "https://images.unsplash.com/photo-1531403009284-440f080d1e12", # Whiteboarding
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa"  # Abstract Network
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
    # 1. Force remove Markdown Bold/Headers
    text = text.replace("**", "").replace("__", "").replace("##", "")
    # 2. Force convert any bullet-like char to Emoji
    text = re.sub(r'^[\*\-]\s+', '🔹 ', text, flags=re.MULTILINE)
    # 3. Fix double spacing
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# --- INTELLIGENT SCRAPER ---
def get_article_details(url, mode):
    try:
        print(f"   ⬇️  Scraping: {url}")
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # 1. Get Text
        possible_bodies = soup.select('article, .post-content, .entry-content, #article-body, .gh-content')
        target = possible_bodies[0] if possible_bodies else soup
        text = "\n".join([p.get_text().strip() for p in target.find_all(['p', 'h2'])])
        
        if len(text) < 600: return None # Too short
        
        # 2. Get Image (The "Fix" for Concepts)
        image_url = None
        
        # Strategy A: Meta Image (Best)
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"): 
            image_url = og_image["content"]
            
        # Strategy B: Find first image in body (Often the diagram)
        if not image_url:
            first_img = target.find('img')
            if first_img and first_img.get('src'):
                src = first_img['src']
                if src.startswith('http'): # Ensure it's a full link
                    image_url = src
        
        # Strategy C: Fallback (Only for Concepts)
        if not image_url and mode == "CONCEPT":
            print("   ⚠️ No image found. Using Generic System Design Fallback.")
            image_url = random.choice(FALLBACK_IMAGES)
        
        if not image_url:
            print("   ⚠️ No image found and not a concept. SKIP.")
            return None 
            
        return {"text": text[:12000], "image": image_url}
        
    except Exception as e:
        print(f"   ⚠️ Error: {e}")
        return None

def fetch_content(history_data):
    # --- PROBABILITY FIX ---
    # > 0.15 means 85% chance of CONCEPT
    # <= 0.15 means 15% chance of NEWS
    mode = "CONCEPT" if random.random() > 0.15 else "NEWS"
    sources = ENGINEERING_FEEDS if mode == "CONCEPT" else NEWS_FEEDS
    random.shuffle(sources)
    
    print(f"🎲 Mode Selected: {mode}")
    
    for feed_url in sources:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:3]:
                if is_already_posted(entry.link, entry.title, history_data): continue
                
                # Pass 'mode' so we know whether to use fallback images
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
    print("   🧠 asking Gemini...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    # Unified Structure
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
        if resp.status_code == 200:
            text = resp.json()['candidates'][0]['content']['parts'][0]['text']
            return clean_text_for_linkedin(text)
    except Exception as e:
        print(f"AI Error: {e}")
    return None

# --- POSTER ---
def post_to_linkedin(content, image_url):
    print(f"   📤 Uploading Image: {image_url}")
    
    # 1. Download Image
    try:
        img_data = requests.get(image_url, headers=HEADERS, timeout=10).content
    except:
        print("   ❌ Failed to download image.")
        return False
    
    # 2. Register
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
    
    if reg.status_code != 200: return False
    
    upload_url = reg.json()['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
    asset = reg.json()['value']['asset']
    
    # 3. Upload Binary
    up = requests.put(upload_url, data=img_data, headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}"})
    
    if up.status_code != 201: 
        print("❌ Image upload failed. ABORTING POST.")
        return False
    
    # 4. Create Post
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
    
    # RERUN 5 TIMES IF FAILS
    for attempt in range(1, 6):
        if posted_successfully:
            break
            
        print(f"\n--- Attempt {attempt}/5 ---")
        
        # 1. Fetch
        content = fetch_content(history)
        if not content: 
            print("   -> No content found. Retrying...")
            continue # Try next attempt
            
        # 2. Write
        post_text = generate_viral_post(content)
        if not post_text: 
            continue # Try next attempt
        
        print("\n--- PREVIEW ---")
        print(post_text)
        print("--- END PREVIEW ---")
        
        # 3. Post
        # UNCOMMENT BELOW TO ACTUALLY POST
        if post_to_linkedin(post_text, content['image_url']):
             print("✅ Posted Successfully!")
             save_history(history, content['title'], content['link'])
             posted_successfully = True
        else:
             print("❌ API Post failed. Retrying with next article...")
             time.sleep(5) # Short pause before retry