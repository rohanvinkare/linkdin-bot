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
# selected ONLY blogs known for technical depth to ensure accuracy
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
        
        # QUALITY GATE 1: If text is too short, it's likely not a deep concept. Skip.
        if len(text) < 1000: 
            print("   ⚠️ Text too short (low quality). Skipping.")
            return None
        return text[:15000] 
    except Exception as e:
        print(f"   ⚠️ Scraping error: {e}")
        return None

def fetch_content(history_data):
    # --- 70% / 30% LOGIC ---
    # random.random() gives a number between 0.0 and 1.0
    # If number is > 0.3 (0.31 to 1.0), that is a 70% range -> Choose CONCEPT
    # If number is <= 0.3 (0.0 to 0.30), that is a 30% range -> Choose NEWS
    mode = "CONCEPT" if random.random() > 0.3 else "NEWS"
    sources = ENGINEERING_FEEDS if mode == "CONCEPT" else NEWS_FEEDS
    
    print(f"🎲 Probability Roll: Selected {mode} Mode")
    random.shuffle(sources)
    
    for feed_url in sources:
        try:
            feed = feedparser.parse(feed_url)
            if not feed.entries: continue
        except: continue
        
        for entry in feed.entries[:3]: # Only check fresh 3 posts
            if not is_already_posted(entry.link, entry.title, history_data):
                full_text = get_article_text(entry.link)
                if not full_text: continue
                
                image_url = None
                try:
                    if 'media_content' in entry: image_url = entry.media_content[0]['url']
                except: pass

                return {
                    "type": mode, 
                    "title": entry.title,
                    "link": entry.link,
                    "full_text": full_text,
                    "image_url": image_url
                }
    return None

# --- AI ENGINE WITH "STAFF ENGINEER" PERSONA ---
def generate_viral_post(content_item):
    print("   🧠 Asking Gemini to write (and verify) the post...")
    
    # 1. Fetch Models
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    models = ["gemini-1.5-flash"] # Default
    try:
        data = requests.get(url).json()
        models = [m['name'].replace('models/', '') for m in data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        models.sort(key=lambda x: ('flash' not in x, 'pro' in x))
    except: pass

    # --- PROMPTS ---
    if content_item['type'] == "CONCEPT":
        # QUALITY GATE 2: The "SKIP" Instruction
        prompt = f"""
        Act as a Principal Staff Engineer at a FAANG company.
        
        TASK: Review this article and write a LinkedIn post about the System Design concept.
        ARTICLE: "{content_item['title']}"
        TEXT SAMPLE: "{content_item['full_text'][:6000]}..."
        
        CRITICAL INSTRUCTIONS FOR ACCURACY:
        1. VALIDATION: If this article is just "Marketing Fluff" (e.g. "We launched a new UI"), output exactly the word: SKIP.
        2. If the concept is valid, explain the *Architecture* and *Trade-offs*.
        3. Do not just summarize. Add "Senior Engineer Intuition" - why did they choose this? 
        4. Be 100% technically accurate. Do not hallucinate.
        
        FORMATTING:
        - NO Markdown Bold (**). Use Capital letters for emphasis.
        - NO Headers (##).
        - Use emojis: 🔹, ⚙️, 🚀, 👉, 🔥, ⭐, 🌐, 💥.
        
        OUTPUT TEMPLATE:
        [One sentence hook about a common misconception]
        
        [The "Aha!" moment about how this ACTUALLY works]
        
        The Trade-offs:
        🔹 [Pro: e.g. High Throughput]
        🔹 [Con: e.g. Eventual Consistency]
        
        [One sentence conclusion on when to use this]
        
        👇 Thoughts?
        
        🔗 {content_item['link']}
        
        #systemdesign #engineering #backend
        """
    else:
        prompt = f"""
        Act as a Tech Lead. Write a short, punchy reaction to this news.
        NEWS: "{content_item['title']}"
        TEXT: "{content_item['full_text'][:4000]}..."
        
        If this is boring news, output: SKIP.
        
        FORMAT:
        [Provocative Hook]
        [Why this matters for engineers]
        [Cynical/Realist take]
        
        🔗 {content_item['link']}
        #tech #news
        """

    # --- GENERATION LOOP ---
    for model in models:
        try:
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            resp = requests.post(api_url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": prompt}]}]})
            
            if resp.status_code == 200:
                text = resp.json()['candidates'][0]['content']['parts'][0]['text']
                
                # QUALITY GATE 3: Handling the SKIP command
                if "SKIP" in text or len(text) < 50:
                    print(f"   ⚠️ AI decided this article is low quality (SKIP).")
                    return "SKIP"
                
                # Cleaning
                text = text.replace("**", "").replace("##", "")
                text = re.sub(r'^\* ', '🔹 ', text, flags=re.MULTILINE)
                return text
        except: continue
        
    return None

# --- LINKEDIN POSTER ---
def post_to_linkedin(content, image_url):
    print("📤 Uploading to LinkedIn...")
    # (Same posting logic as previous script - kept standard)
    # Note: Ensure you have your TOKEN ready
    headers = {"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"}
    
    asset = None
    # Image upload logic (omitted for brevity, same as previous)
    
    post_body = {
        "author": LINKEDIN_PERSON_URN,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": "NONE", # Default to text/link only for safety
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    
    r = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=post_body)
    return r.status_code == 201

# --- MAIN EXECUTION BLOCK ---
if __name__ == "__main__":
    print("🤖 Bot Started...")
    
    # Retry Loop: If AI returns SKIP, try the next article
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
            # Mark as "read" in history so we don't pick it again
            save_history(history, content['title'], content['link']) 
            continue
            
        if post_text:
            print("\n--- FINAL POST PREVIEW ---")
            print(post_text)
            print("--------------------------")
            
            # UNCOMMENT TO ENABLE POSTING
            if post_to_linkedin(post_text, content['image_url']):
                print("✅ Successfully Posted!")
                save_history(history, content['title'], content['link'])
                posted = True
            else:
                print("❌ LinkedIn API Error.")
            
            # For testing, break after preview
            break