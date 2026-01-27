import requests
import feedparser
import json
import random
import time
import os
import datetime
import re
import logging
from bs4 import BeautifulSoup

# --- LOGGING CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

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

# --- UNICODE TEXT STYLING FOR LINKEDIN ---
def apply_unicode_styling(text):
    """
    Converts text to Unicode styled variants since LinkedIn doesn't support markdown.
    Uses mathematical alphanumeric symbols for bold/italic effects.
    """
    # Unicode character mappings for styled text
    BOLD_MAP = {
        'A': '𝗔', 'B': '𝗕', 'C': '𝗖', 'D': '𝗗', 'E': '𝗘', 'F': '𝗙', 'G': '𝗚', 'H': '𝗛', 'I': '𝗜', 'J': '𝗝',
        'K': '𝗞', 'L': '𝗟', 'M': '𝗠', 'N': '𝗡', 'O': '𝗢', 'P': '𝗣', 'Q': '𝗤', 'R': '𝗥', 'S': '𝗦', 'T': '𝗧',
        'U': '𝗨', 'V': '𝗩', 'W': '𝗪', 'X': '𝗫', 'Y': '𝗬', 'Z': '𝗭',
        'a': '𝗮', 'b': '𝗯', 'c': '𝗰', 'd': '𝗱', 'e': '𝗲', 'f': '𝗳', 'g': '𝗴', 'h': '𝗵', 'i': '𝗶', 'j': '𝗷',
        'k': '𝗸', 'l': '𝗹', 'm': '𝗺', 'n': '𝗻', 'o': '𝗼', 'p': '𝗽', 'q': '𝗾', 'r': '𝗿', 's': '𝘀', 't': '𝘁',
        'u': '𝘂', 'v': '𝘃', 'w': '𝘄', 'x': '𝘅', 'y': '𝘆', 'z': '𝘇',
        '0': '𝟬', '1': '𝟭', '2': '𝟮', '3': '𝟯', '4': '𝟰', '5': '𝟱', '6': '𝟲', '7': '𝟳', '8': '𝟴', '9': '𝟵'
    }
    
    def make_bold(match):
        text = match.group(1)
        return ''.join(BOLD_MAP.get(c, c) for c in text)
    
    # Convert [BOLD:text] markers to Unicode bold
    text = re.sub(r'\[BOLD:(.*?)\]', make_bold, text)
    
    return text

def clean_text_for_linkedin(text):
    """Enhanced text cleaning with Unicode styling support"""
    # Remove markdown artifacts
    text = text.replace("**", "").replace("__", "").replace("##", "")
    
    # Replace bullet points with stylish alternatives
    text = re.sub(r'^[\*\-]\s+', '▸ ', text, flags=re.MULTILINE)
    
    # Clean up excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Apply Unicode styling for emphasis
    text = apply_unicode_styling(text)
    
    return text.strip()

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

# --- DYNAMIC MODEL SELECTOR ---
def get_valid_model_name():
    """Asks Google which models are actually available to avoid 404s"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            available_models = [
                m['name'].replace("models/", "") 
                for m in data.get('models', []) 
                if 'generateContent' in m.get('supportedGenerationMethods', [])
            ]
            
            # Prefer Flash, then Pro, then anything else
            if "gemini-1.5-flash" in available_models: return "gemini-1.5-flash"
            if "gemini-1.5-flash-latest" in available_models: return "gemini-1.5-flash-latest"
            if "gemini-1.0-pro" in available_models: return "gemini-1.0-pro"
            
            if available_models:
                logging.warning(f"Preferred model not found. Using fallback: {available_models[0]}")
                return available_models[0]
                
    except Exception as e:
        logging.error(f"Could not fetch model list: {e}")
    
    return "gemini-1.5-flash-latest"

# --- ENHANCED IMAGE SCRAPER ---
def get_article_details(url, mode):
    try:
        logging.info(f"Scraping URL: {url}")
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.content, 'html.parser')
        
        possible_bodies = soup.select('article, .post-content, .entry-content, #article-body, .gh-content')
        target = possible_bodies[0] if possible_bodies else soup
        text = "\n".join([p.get_text().strip() for p in target.find_all(['p', 'h2'])])
        
        if len(text) < 600: return None
        
        # ENHANCED IMAGE EXTRACTION - Multiple strategies
        image_url = None
        
        # Strategy 1: Twitter/X card image (often best quality)
        twitter_img = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_img and twitter_img.get("content"):
            image_url = twitter_img["content"]
            logging.info("Found Twitter Card image")
        
        # Strategy 2: Open Graph image
        if not image_url:
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"): 
                image_url = og_image["content"]
                logging.info("Found OG image")
        
        # Strategy 3: Look for hero/featured images in article
        if not image_url:
            hero_selectors = [
                'img.featured-image', 'img.hero-image', 'img.post-image',
                'figure.featured img', 'div.featured-image img',
                'div.post-thumbnail img', 'div.entry-image img'
            ]
            for selector in hero_selectors:
                hero_img = target.select_one(selector)
                if hero_img and hero_img.get('src'):
                    src = hero_img['src']
                    if src.startswith('http'):
                        image_url = src
                        logging.info("Found hero image")
                        break
        
        # Strategy 4: First large image in content (width/height check)
        if not image_url:
            for img in target.find_all('img'):
                src = img.get('src', '')
                width = img.get('width', '0')
                height = img.get('height', '0')
                
                # Convert to int safely
                try:
                    w = int(width) if width and str(width).isdigit() else 0
                    h = int(height) if height and str(height).isdigit() else 0
                except:
                    w, h = 0, 0
                
                # Prioritize larger images (likely feature images, not icons)
                if src.startswith('http') and (w > 400 or h > 300 or (w == 0 and h == 0)):
                    # Avoid logos, icons, tracking pixels
                    if not any(skip in src.lower() for skip in ['logo', 'icon', 'avatar', 'pixel', 'tracking', '1x1']):
                        image_url = src
                        logging.info(f"Found content image ({w}x{h})")
                        break
        
        # Strategy 5: Fallback to first valid image
        if not image_url:
            first_img = target.find('img')
            if first_img and first_img.get('src'):
                src = first_img['src']
                if src.startswith('http'): 
                    image_url = src
                    logging.info("Using first available image")
        
        # Strategy 6: Use fallback for concepts only
        if not image_url and mode == "CONCEPT":
            logging.warning("No image found. Using Fallback.")
            image_url = random.choice(FALLBACK_IMAGES)
        
        if not image_url:
            logging.warning("No suitable image found. SKIP.")
            return None 
            
        return {"text": text[:12000], "image": image_url}
        
    except Exception as e:
        logging.error(f"Scraping Error: {e}")
        return None

def fetch_content(history_data):
    # CHANGED: Prioritize concepts (85% concepts, 15% news)
    mode = "CONCEPT" if random.random() > 0.15 else "NEWS"
    sources = ENGINEERING_FEEDS if mode == "CONCEPT" else NEWS_FEEDS
    random.shuffle(sources)
    
    logging.info(f"Mode Selected: {mode}")
    
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

# --- AI WRITER WITH UNICODE STYLING ---
def generate_viral_post(content_item):
    valid_model = get_valid_model_name()
    logging.info(f"Asking Gemini ({valid_model})...")
    
    if not GEMINI_API_KEY:
        logging.error("GEMINI_API_KEY is missing!")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{valid_model}:generateContent?key={GEMINI_API_KEY}"
    
    base_structure = """
    CRITICAL FORMATTING RULES FOR LINKEDIN:
    1. NO Markdown syntax (**, __, ##) - LinkedIn doesn't support it
    2. Use [BOLD:text] for emphasis - will be converted to Unicode bold
    3. Use these emojis for structure: 💡 🔹 👉 🚀 ⚠️ ⚡ 🎯
    4. Use line breaks and spacing for readability
    5. Keep it visually clean and scannable
    """
    
    if content_item['type'] == "CONCEPT":
        prompt = f"""
        Act as a Principal Staff Engineer writing for LinkedIn.
        Topic: {content_item['title']}
        Context: {content_item['full_text'][:5000]}
        {base_structure}
        
        OUTPUT FORMAT (use exact structure):
        
        [BOLD:Counter-intuitive Hook Question]
        
        [Brief 2-sentence context explaining the problem/concept]
        
        💡 [BOLD:The Architecture:]
        ▸ [Key architectural decision 1]
        ▸ [Key architectural decision 2]
        ▸ [Key architectural decision 3]
        
        ⚡ [BOLD:The Trade-offs:]
        ⚠️ Risk: [Main challenge/limitation]
        🚀 Benefit: [Main advantage/win]
        
        🎯 [BOLD:Bottom Line:]
        [Sharp 1-line conclusion]
        
        🔗 Read more: {content_item['link']}
        
        #systemdesign #softwarearchitecture #engineering
        """
    else: 
        prompt = f"""
        Act as a Tech Lead writing LinkedIn news commentary.
        News: {content_item['title']}
        Context: {content_item['full_text'][:4000]}
        {base_structure}
        
        OUTPUT FORMAT (use exact structure):
        
        [Provocative hook statement]
        
        👉 [BOLD:The TL;DR:]
        ▸ [Key fact 1]
        ▸ [Key fact 2]
        ▸ [Key fact 3]
        
        🎯 [BOLD:Why Engineers Should Care:]
        ▸ [Engineering impact]
        ▸ [Market/industry impact]
        
        [Sharp cynical 1-line take]
        
        🔗 Source: {content_item['link']}
        
        #tech #technews #engineering
        """

    try:
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": prompt}]}]})
        
        if resp.status_code != 200:
            logging.error(f"GOOGLE API ERROR {resp.status_code}: {resp.text}")
            return None

        text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        return clean_text_for_linkedin(text)

    except Exception as e:
        logging.error(f"EXCEPTION: {e}")
    return None

# --- POSTER ---
def post_to_linkedin(content, image_url):
    logging.info(f"Uploading Image: {image_url}")
    try:
        img_data = requests.get(image_url, headers=HEADERS, timeout=10).content
    except:
        logging.error("Failed to download image.")
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
        logging.error(f"LinkedIn Upload Error: {reg.text}")
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
    logging.info("Bot Started...")
    history = load_history()
    posted_successfully = False
    
    for attempt in range(1, 6):
        if posted_successfully: break
        logging.info(f"--- Attempt {attempt}/5 ---")
        
        content = fetch_content(history)
        if not content: 
            logging.info("-> No content found.")
            continue 
            
        post_text = generate_viral_post(content)
        if not post_text: 
            continue 
        
        logging.info("\n--- PREVIEW ---")
        print(post_text) # Keep print for local debugging visibility only
        logging.info("--- END PREVIEW ---")
        
        # --- HUMAN DELAY LOGIC ---
        # Sleep between 0 and 5 minutes (300 seconds)
        human_delay = random.randint(0, 300)
        minutes = round(human_delay / 60, 2)
        logging.info(f"😴 Simulating human behavior: Sleeping for {human_delay}s ({minutes} mins) before posting...")
        time.sleep(human_delay)
        # -------------------------

        if post_to_linkedin(post_text, content['image_url']):
             logging.info("✅ Posted Successfully!")
             save_history(history, content['title'], content['link'])
             posted_successfully = True
        else:
             logging.error("API Post failed. Retrying...")
             time.sleep(5)