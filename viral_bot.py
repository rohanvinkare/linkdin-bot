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
LINKEDIN_ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# --- SOURCE MANAGEMENT ---
# Group 1: News (30% Chance)
NEWS_FEEDS = [
    "https://feeds.feedburner.com/TheHackersNews", 
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://openai.com/blog/rss/"
]

# Group 2: High-Quality Engineering (70% Chance)
ENGINEERING_FEEDS = [
    "https://netflixtechblog.com/feed",           
    "https://eng.uber.com/feed/",                 
    "https://aws.amazon.com/blogs/architecture/feed/", 
    "https://blog.bytebytego.com/feed",           
    "https://martinfowler.com/feed.atom",         
    "https://slack.engineering/feed/",            
    "https://discord.com/blog/rss",               
    "https://engineering.fb.com/feed/"
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
    """
    LinkedIn does not support Markdown. This function:
    1. Removes **bold** and ## Headers
    2. Converts * bullets to emojis
    3. Ensures spacing is correct
    """
    # Remove Bold/Italic markers
    text = text.replace("**", "").replace("__", "")
    
    # Remove Markdown headers (## Title)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    
    # Convert standard bullet points (* or -) to Emojis
    text = re.sub(r'^[\*\-]\s+', '🔹 ', text, flags=re.MULTILINE)
    
    # Ensure hashtags have a space before them if they are stuck to text
    text = text.replace("#", " #")
    text = re.sub(r'\s+#', ' #', text) # Fix double spaces
    
    return text.strip()

# --- INTELLIGENT SCRAPER ---
def get_article_text(url):
    try:
        print(f"   ⬇️  Downloading: {url}")
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        possible_bodies = soup.select('article, .post-content, .entry-content, #article-body, .gh-content, .main-content')
        target = possible_bodies[0] if possible_bodies else soup
        paragraphs = target.find_all(['p', 'h2', 'li'])
        text = "\n".join([p.get_text().strip() for p in paragraphs])
        
        # QUALITY GATE 1: If text is too short, it's likely not a deep concept.
        if len(text) < 1000: 
            print("   ⚠️ Text too short (low quality). Skipping.")
            return None
        return text[:15000] 
    except Exception as e:
        print(f"   ⚠️ Scraping error: {e}")
        return None

def fetch_content(history_data):
    # --- 70% / 30% LOGIC ---
    # Random > 0.3 means 70% chance (Concepts)
    # Random <= 0.3 means 30% chance (News)
    mode = "CONCEPT" if random.random() > 0.3 else "NEWS"
    sources = ENGINEERING_FEEDS if mode == "CONCEPT" else NEWS_FEEDS
    
    print(f"🎲 Probability Roll: Selected {mode} Mode")
    random.shuffle(sources)
    
    for feed_url in sources:
        try:
            feed = feedparser.parse(feed_url)
            if not feed.entries: continue
        except: continue
        
        for entry in feed.entries[:3]: # Check top 3 posts
            if not is_already_posted(entry.link, entry.title, history_data):
                full_text = get_article_text(entry.link)
                if not full_text: continue
                
                image_url = None
                try:
                    if 'media_content' in entry: image_url = entry.media_content[0]['url']
                    # Fallback to Media Thumbnail if available
                    elif 'media_thumbnail' in entry: image_url = entry.media_thumbnail[0]['url']
                except: pass

                return {
                    "type": mode, 
                    "title": entry.title,
                    "link": entry.link,
                    "full_text": full_text,
                    "image_url": image_url
                }
    return None

# --- AI ENGINE ---
def generate_viral_post(content_item):
    print("   🧠 Asking Gemini to write...")
    
    # 1. Fetch Models
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    models = ["gemini-1.5-flash"]
    try:
        data = requests.get(url).json()
        models = [m['name'].replace('models/', '') for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        models.sort(key=lambda x: ('flash' not in x, 'pro' in x))
    except: pass

    # --- PROMPTS ---
    if content_item['type'] == "CONCEPT":
        prompt = f"""
        Act as a Principal Staff Engineer at a FAANG company.
        
        TASK: Review this article and write a LinkedIn post.
        ARTICLE: "{content_item['title']}"
        TEXT SAMPLE: "{content_item['full_text'][:6000]}..."
        
        INSTRUCTIONS:
        1. If this is marketing fluff, output: SKIP.
        2. Explain the Architecture and Trade-offs.
        3. Be 100% technically accurate.
        
        FORMATTING:
        - NO Markdown (**). 
        - Use these emojis: 🔹, ⚙️, 🚀, 👉.
        
        OUTPUT TEMPLATE:
        [Hook about a misconception]
        
        [The "Aha!" moment]
        
        The Trade-offs:
        🔹 [Pro]
        🔹 [Con]
        
        [Conclusion]
        
        👇 Thoughts?
        
        🔗 {content_item['link']}
        
        #systemdesign #engineering #backend
        """
    else:
        prompt = f"""
        Act as a Tech Lead. Write a short reaction to this news.
        NEWS: "{content_item['title']}"
        TEXT: "{content_item['full_text'][:4000]}..."
        
        If this is boring, output: SKIP.
        
        FORMAT:
        [Provocative Hook]
        [Why this matters for engineers]
        [Cynical/Realist take]
        
        🔗 {content_item['link']}
        #tech #news
        """

    for model in models:
        try:
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            resp = requests.post(api_url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": prompt}]}]})
            
            if resp.status_code == 200:
                text = resp.json()['candidates'][0]['content']['parts'][0]['text']
                if "SKIP" in text or len(text) < 50:
                    print(f"   ⚠️ AI decided this article is low quality (SKIP).")
                    return "SKIP"
                
                return clean_text_for_linkedin(text)
        except: continue
        
    return None

# --- LINKEDIN POSTER (FIXED IMAGE UPLOAD) ---
def post_to_linkedin(content, image_url):
    print("📤 Uploading to LinkedIn...")
    headers = {"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"}
    
    asset = None
    
    # 1. Handle Image Upload if URL exists
    if image_url:
        print(f"   🖼️  Found Image: {image_url}")
        try:
            # Step A: Register the upload
            reg_body = {
                "registerUploadRequest": {
                    "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                    "owner": LINKEDIN_PERSON_URN,
                    "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]
                }
            }
            reg = requests.post("https://api.linkedin.com/v2/assets?action=registerUpload", headers=headers, json=reg_body)
            
            if reg.status_code == 200:
                upload_url = reg.json()['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
                asset = reg.json()['value']['asset']
                
                # Step B: Download Image & Upload to LinkedIn
                # Note: We use a stream to handle binary data correctly
                img_data = requests.get(image_url, headers=HEADERS, stream=True)
                if img_data.status_code == 200:
                    up = requests.put(upload_url, data=img_data.content, headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}"})
                    if up.status_code != 201:
                        print(f"   ⚠️ Image upload binary failed. Status: {up.status_code}")
                        asset = None
                else:
                    print("   ⚠️ Could not download image from source.")
                    asset = None
            else:
                print(f"   ⚠️ Image registration failed: {reg.text}")
        except Exception as e:
            print(f"   ⚠️ Image Error: {e}")
            asset = None

    # 2. Construct the Post
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
    
    # --- HUMAN DELAY ---
    wait_minutes = random.randint(1, 5)
    print(f"😴 Waiting for {wait_minutes} minutes to simulate human behavior...")
    time.sleep(wait_minutes * 60)
    
    attempts = 0
    posted = False
    history = load_history()
    
    while attempts < 5 and not posted:
        attempts += 1
        print(f"\n--- Attempt {attempts} ---")
        
        content = fetch_content(history)
        if not content: break
        
        post_text = generate_viral_post(content)
        
        if post_text == "SKIP":
            print("   -> Skipping this article, fetching another...")
            save_history(history, content['title'], content['link']) 
            continue
            
        if post_text:
            print("\n--- FINAL POST PREVIEW ---")
            print(post_text)
            print("--------------------------")
            
            # Uncomment below to go live
            if post_to_linkedin(post_text, content['image_url']):
                 print("✅ Successfully Posted!")
                 save_history(history, content['title'], content['link'])
                 posted = True
            else:
                 print("❌ LinkedIn API Error.")
            
            break