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
                print(f"   ⚠️ Preferred model not found. Using fallback: {available_models[0]}")
                return available_models[0]
                
    except Exception as e:
        print(f"   ⚠️ Could not fetch model list: {e}")
    
    return "gemini-1.5-flash-latest"

# --- HUMAN-LIKE DELAYS ---
def human_delay(min_seconds=2, max_seconds=5):
    """Simulates human reading/thinking time to avoid bot detection"""
    delay = random.uniform(min_seconds, max_seconds)
    print(f"   ⏳ Pausing {delay:.1f}s (human behavior simulation)...")
    time.sleep(delay)

# --- ENHANCED IMAGE SCRAPER ---
def get_article_details(url, mode):
    try:
        print(f"   ⬇️  Scraping: {url}")
        human_delay(1, 3)  # Delay before scraping
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
            print(f"   🖼️  Found Twitter Card image")
        
        # Strategy 2: Open Graph image
        if not image_url:
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"): 
                image_url = og_image["content"]
                print(f"   🖼️  Found OG image")
        
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
                        print(f"   🖼️  Found hero image")
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
                        print(f"   🖼️  Found content image ({w}x{h})")
                        break
        
        # Strategy 5: Fallback to first valid image
        if not image_url:
            first_img = target.find('img')
            if first_img and first_img.get('src'):
                src = first_img['src']
                if src.startswith('http'): 
                    image_url = src
                    print(f"   🖼️  Using first available image")
        
        # Strategy 6: Use fallback for concepts only
        if not image_url and mode == "CONCEPT":
            print("   ⚠️ No image found. Using Fallback.")
            image_url = random.choice(FALLBACK_IMAGES)
        
        if not image_url:
            print("   ⚠️ No suitable image found. SKIP.")
            return None 
            
        return {"text": text[:12000], "image": image_url}
        
    except Exception as e:
        print(f"   ⚠️ Error: {e}")
        return None

def fetch_content(history_data):
    # CHANGED: Prioritize concepts (85% concepts, 15% news)
    mode = "CONCEPT" if random.random() > 0.15 else "NEWS"
    sources = ENGINEERING_FEEDS if mode == "CONCEPT" else NEWS_FEEDS
    random.shuffle(sources)
    
    print(f"🎲 Mode Selected: {mode}")
    print(f"📚 Available Sources: {len(sources)}")
    
    for idx, feed_url in enumerate(sources, 1):
        try:
            print(f"\n   📡 Checking Feed {idx}/{len(sources)}: {feed_url}")
            feed = feedparser.parse(feed_url)
            print(f"   📄 Found {len(feed.entries)} articles in this feed")
            
            for entry in feed.entries[:3]:
                print(f"   🔍 Checking: {entry.title[:60]}...")
                if is_already_posted(entry.link, entry.title, history_data): 
                    print(f"   ⏭️  Already posted, skipping")
                    continue
                    
                details = get_article_details(entry.link, mode)
                if not details: 
                    print(f"   ❌ Failed to extract details, trying next article")
                    continue
                    
                print(f"   ✅ Valid content found!")
                return {
                    "type": mode,
                    "title": entry.title,
                    "link": entry.link,
                    "full_text": details["text"],
                    "image_url": details["image"]
                }
        except Exception as e:
            print(f"   ⚠️  Feed parsing error: {e}")
            continue
    
    print(f"   ❌ No valid content found after checking all sources")
    return None

# --- AI WRITER WITH UNICODE STYLING ---
def generate_viral_post(content_item):
    valid_model = get_valid_model_name()
    print(f"   🧠 Using AI Model: {valid_model}")
    print(f"   📝 Generating {content_item['type']} post...")
    
    if not GEMINI_API_KEY:
        print("   ❌ ERROR: GEMINI_API_KEY is missing!")
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
        human_delay(3, 6)  # Simulate thinking time before API call
        print(f"   🌐 Calling Gemini API...")
        
        resp = requests.post(url, headers={"Content-Type": "application/json"}, json={"contents": [{"parts": [{"text": prompt}]}]})
        
        if resp.status_code != 200:
            print(f"   ❌ GOOGLE API ERROR {resp.status_code}: {resp.text}")
            return None

        print(f"   ✅ AI response received ({len(resp.text)} chars)")
        text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        
        cleaned_text = clean_text_for_linkedin(text)
        print(f"   🎨 Text formatted with Unicode styling")
        print(f"   📏 Final post length: {len(cleaned_text)} characters")
        
        return cleaned_text

    except Exception as e:
        print(f"   ❌ EXCEPTION during AI generation: {e}")
    return None

# --- POSTER ---
def post_to_linkedin(content, image_url):
    print(f"\n   📤 Preparing to post to LinkedIn...")
    print(f"   🖼️  Image URL: {image_url[:80]}...")
    
    human_delay(2, 4)  # Simulate reviewing the post before publishing
    
    try:
        print(f"   ⬇️  Downloading image...")
        img_data = requests.get(image_url, headers=HEADERS, timeout=10).content
        print(f"   ✅ Image downloaded ({len(img_data)} bytes)")
    except Exception as e:
        print(f"   ❌ Failed to download image: {e}")
        return False
    
    human_delay(1, 3)  # Delay before upload registration
    
    print(f"   📝 Registering image upload with LinkedIn...")
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
        print(f"   ❌ LinkedIn registration failed (Status {reg.status_code})")
        print(f"   ❌ Response: {reg.text[:200]}")
        return False
    
    print(f"   ✅ Upload registered successfully")
    
    upload_url = reg.json()['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
    asset = reg.json()['value']['asset']
    
    human_delay(1, 2)  # Delay before actual upload
    
    print(f"   ⬆️  Uploading image to LinkedIn CDN...")
    up = requests.put(upload_url, data=img_data, headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}"})
    
    if up.status_code != 201: 
        print(f"   ❌ Image upload failed (Status {up.status_code})")
        return False
    
    print(f"   ✅ Image uploaded successfully")
    
    human_delay(2, 5)  # Simulate final review before posting
    
    print(f"   📣 Publishing post to LinkedIn...")
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
    
    if final.status_code == 201:
        print(f"   ✅ Post published successfully!")
        return True
    else:
        print(f"   ❌ Post publication failed (Status {final.status_code})")
        print(f"   ❌ Response: {final.text[:200]}")
        return False

# --- MAIN ---
if __name__ == "__main__":
    print("=" * 60)
    print("🤖 LINKEDIN AUTO-POSTER BOT STARTED")
    print("=" * 60)
    print(f"⏰ Execution Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🌍 Timezone: UTC")
    print("")
    
    # Verify credentials
    print("🔐 Verifying Credentials...")
    if not LINKEDIN_ACCESS_TOKEN:
        print("   ❌ LINKEDIN_TOKEN missing!")
        exit(1)
    if not LINKEDIN_PERSON_URN:
        print("   ❌ LINKEDIN_URN missing!")
        exit(1)
    if not GEMINI_API_KEY:
        print("   ❌ GEMINI_API_KEY missing!")
        exit(1)
    print("   ✅ All credentials present")
    print("")
    
    # Load history
    print("📂 Loading Post History...")
    history = load_history()
    print(f"   📊 Total posts in history: {len(history)}")
    if history:
        last_post = history[-1]
        print(f"   📅 Last post date: {last_post.get('date', 'Unknown')}")
        print(f"   📝 Last post title: {last_post.get('title', 'Unknown')[:60]}...")
    print("")
    
    posted_successfully = False
    
    for attempt in range(1, 6):
        if posted_successfully: 
            break
            
        print("=" * 60)
        print(f"🔄 ATTEMPT {attempt}/5")
        print("=" * 60)
        
        print("🔍 Step 1: Fetching Content...")
        content = fetch_content(history)
        
        if not content: 
            print("   ⚠️  No suitable content found.")
            if attempt < 5:
                print(f"   🔁 Will retry in 10 seconds...")
                time.sleep(10)
            continue 
        
        print(f"\n✅ Content Selected:")
        print(f"   📌 Type: {content['type']}")
        print(f"   📌 Title: {content['title']}")
        print(f"   📌 Source: {content['link'][:60]}...")
        print(f"   📌 Text Length: {len(content['full_text'])} chars")
        print(f"   📌 Image: {content['image_url'][:60]}...")
        print("")
        
        print("🔍 Step 2: Generating AI Post...")
        post_text = generate_viral_post(content)
        
        if not post_text: 
            print("   ⚠️  AI generation failed.")
            if attempt < 5:
                print(f"   🔁 Retrying in 10 seconds...")
                time.sleep(10)
            continue 
        
        print("")
        print("=" * 60)
        print("📄 POST PREVIEW")
        print("=" * 60)
        print(post_text)
        print("=" * 60)
        print("")
        
        print("🔍 Step 3: Publishing to LinkedIn...")
        if post_to_linkedin(post_text, content['image_url']):
            print("")
            print("=" * 60)
            print("🎉 SUCCESS! POST PUBLISHED TO LINKEDIN")
            print("=" * 60)
            save_history(history, content['title'], content['link'])
            print(f"💾 History saved ({len(history)} total posts)")
            posted_successfully = True
        else:
            print("")
            print("=" * 60)
            print(f"❌ ATTEMPT {attempt} FAILED")
            print("=" * 60)
            if attempt < 5:
                retry_delay = random.randint(15, 30)
                print(f"⏳ Waiting {retry_delay} seconds before retry...")
                time.sleep(retry_delay)
    
    print("")
    print("=" * 60)
    if posted_successfully:
        print("✅ BOT EXECUTION COMPLETED SUCCESSFULLY")
    else:
        print("❌ BOT EXECUTION FAILED - All 5 attempts exhausted")
        exit(1)
    print("=" * 60)