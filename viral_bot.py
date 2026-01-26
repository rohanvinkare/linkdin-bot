import requests
import feedparser
import json
import random
import time
import os
import datetime
import re
from google import genai 
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
HISTORY_FILE = "history.json"
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_URN", "").strip() 
ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# High-Quality Sources
RSS_FEEDS = [
    "https://github.blog/feed/",            # Usually easy to scrape
    "https://stackoverflow.blog/feed/",     # Good content
    "https://techcrunch.com/feed/",         # High volume
    "https://aws.amazon.com/blogs/architecture/feed/"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# --- INIT CLIENT ---
if not GEMINI_API_KEY:
    print("❌ ERROR: GEMINI_API_KEY is missing.")
    exit()

client = genai.Client(api_key=GEMINI_API_KEY)

# --- 1. DEEP CONTENT SCRAPER ---
def get_article_content(url):
    print(f"   👀 Trying to scrape: {url[:50]}...")
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200: 
            print(f"   ⚠️ Blocked (Status: {r.status_code})")
            return None
            
        soup = BeautifulSoup(r.content, 'html.parser')
        paragraphs = soup.find_all('p')
        if not paragraphs:
            paragraphs = soup.find_all('div', class_=re.compile('(content|post|article|body)'))
            
        full_text = " ".join([p.get_text() for p in paragraphs[:15]])
        
        if len(full_text) < 200: 
            print(f"   ⚠️ Content too short ({len(full_text)} chars).")
            return None
            
        print("   ✅ Scrape Success!")
        return full_text.strip()
    except Exception as e:
        print(f"   ⚠️ Scraping Error: {e}")
        return None

# --- 2. THE AI JUDGE ---
def evaluate_article(title, text):
    # FOR TESTING: We return a fake high score to FORCE a post
    print("   🤖 Skipping AI Judge for testing... FORCE APPROVING.")
    return {"score": 10, "reason": "Testing Mode"}

# --- 3. SMART FETCHER ---
def fetch_best_article(history_data):
    print("🔍 Scanning feeds...")
    random.shuffle(RSS_FEEDS)
    
    for feed_url in RSS_FEEDS: 
        print(f"\n📡 Checking Feed: {feed_url}")
        try: 
            feed = feedparser.parse(feed_url)
            if not feed.entries:
                print("   ⚠️ No entries found in this feed.")
                continue
        except Exception as e: 
            print(f"   ⚠️ Feed Parse Error: {e}")
            continue
        
        for entry in feed.entries[:1]: # Check only the 1st link of each feed
            # SKIP HISTORY CHECK FOR TESTING
            # if is_already_posted(entry.link, history_data): 
            #     print("   ⏭️ Already posted. Skipping.")
            #     continue
            
            full_text = get_article_content(entry.link)
            if not full_text: continue
            
            return {
                "title": entry.title,
                "link": entry.link,
                "full_text": full_text
            }
    return None

# --- 4. FORMATTING UTILS ---
def to_bold(text):
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    bold   = "𝐇𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝐡𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
    trans = str.maketrans(normal, bold)
    return text.translate(trans)

# --- 5. POST GENERATOR ---
def generate_linkedin_post(article):
    print("📝 Generating Post Content with AI...")
    prompt = f"""
    Write a viral LinkedIn post based on this tech news:
    Title: {article['title']}
    Context: {article['full_text'][:2000]}
    
    Format Guidelines:
    1. First line: A short, bold, attention-grabbing hook (Max 6 words).
    2. Body: Explain WHY this matters to engineers.
    3. Formatting: Use bullet points '⚡' for key takeaways.
    4. Ending: Ask a controversial or engaging question.
    5. Tags: #tech #coding #innovation
    6. Tone: Professional but enthusiastic.
    
    Return pure text.
    """
    try:
        response = client.models.generate_content(
            model='gemini-1.5-flash', 
            contents=prompt
        )
        raw_text = response.text.strip()
        lines = raw_text.split('\n')
        if lines: lines[0] = to_bold(lines[0].replace("*", "").replace("#", "")) 
        return "\n".join(lines) + f"\n\n🔗 Read more: {article['link']}"
    except Exception as e:
        print(f"⚠️ Generation Error: {e}")
        return None

# --- 6. LINKEDIN API ---
def post_to_linkedin(content):
    if not ACCESS_TOKEN or not LINKEDIN_PERSON_URN:
        print("❌ Error: Missing credentials.")
        return False
        
    url = "https://api.linkedin.com/v2/ugcPosts"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json", "X-Restli-Protocol-Version": "2.0.0"}
    clean_urn = LINKEDIN_PERSON_URN.replace("urn:li:person:", "")
    payload = {
        "author": f"urn:li:person:{clean_urn}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": {"shareCommentary": {"text": content}, "shareMediaCategory": "NONE"}},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    try:
        print("🚀 Sending to LinkedIn API...")
        r = requests.post(url, headers=headers, json=payload)
        if r.status_code == 201: return True
        else:
            print(f"❌ LinkedIn Error: {r.status_code} - {r.text}") 
            return False
    except Exception as e: 
        print(f"❌ Network Error: {e}")
        return False

# --- HISTORY UTILS ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try: with open(HISTORY_FILE, "r") as f: return json.load(f)
        except: return []
    return []

def save_history(history, link):
    history.append({"link": link, "date": str(datetime.date.today())})
    if len(history) > 50: history = history[-50:]
    with open(HISTORY_FILE, "w") as f: json.dump(history, f)

# --- MAIN ---
if __name__ == "__main__":
    print("🎬 LinkedIn Bot Starting (TEST MODE)...")
    history = load_history()
    best_article = fetch_best_article(history)
    
    if best_article:
        print(f"✅ Selected Article: {best_article['title']}")
        post_content = generate_linkedin_post(best_article)
        if post_content:
            if post_to_linkedin(post_content):
                print("✅ Published Successfully!")
                save_history(history, best_article['link'])
            else: print("❌ Failed to publish.")
        else: print("❌ Failed to generate content.")
    else: print("😴 No readable articles found (Check 'Blocked' logs).")



    

# import requests
# import feedparser
# import json
# import random
# import time
# import os
# import datetime
# import google.generativeai as genai
# from bs4 import BeautifulSoup

# # --- CONFIGURATION ---
# HISTORY_FILE = "history.json"

# # ADD .strip() TO ALL OF THESE LINES:
# LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_URN", "").strip()
# ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
# GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# # High-Quality Engineering Blogs (The "Authentic" Sources)
# RSS_FEEDS = [
#     "https://netflixtechblog.com/feed",
#     "https://eng.uber.com/feed/",
#     "https://engineering.fb.com/feed/",
#     "https://aws.amazon.com/blogs/architecture/feed/",
#     "https://feeds.feedburner.com/TheHackersNews",
#     "https://devblogs.microsoft.com/feed/",
#     "https://github.blog/feed/",
#     "https://stackoverflow.blog/feed/",
#     "https://techcrunch.com/feed/"
# ]

# # Browser headers so websites don't block our scraper
# HEADERS = {
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
# }

# genai.configure(api_key=GEMINI_API_KEY)

# # # --- 1. SAFETY: MIMIC HUMAN BEHAVIOR ---
# # def mimic_human_timing():
# #     """Sleeps for 5-45 minutes to avoid 'bot' patterns."""
# #     print("🤖 Bot started. Initiating human mimicry...")
# #     sleep_seconds = random.randint(300, 2700) 
# #     minutes = sleep_seconds // 60
# #     print(f"😴 Sleeping for {minutes} minutes before posting...")
# #     time.sleep(sleep_seconds)
# #     print("⏰ Waking up! Ready to work.")


# # --- 1. SAFETY: MIMIC HUMAN BEHAVIOR ---
# def mimic_human_timing():
#     """TEST MODE: Sleep disabled."""
#     print("🤖 TEST MODE: Skipping sleep to run immediately.")
#     # time.sleep(random.randint(300, 2700))  <-- COMMENT THIS OUT
#     return


# # --- 2. DATABASE: JSON HISTORY ---
# def load_history():
#     if os.path.exists(HISTORY_FILE):
#         try:
#             with open(HISTORY_FILE, "r") as f:
#                 return json.load(f)
#         except:
#             return []
#     return []

# def save_history(history_data, new_entry):
#     """Adds the new post with Date, Day, and Title."""
#     history_data.append(new_entry)
#     # Keep file size manageable (last 100 posts)
#     if len(history_data) > 100:
#         history_data = history_data[-100:]
        
#     with open(HISTORY_FILE, "w") as f:
#         json.dump(history_data, f, indent=4)

# def is_already_posted(link, history_data):
#     # Check if this link exists in our JSON list
#     for entry in history_data:
#         if entry.get("web_link") == link:
#             return True
#     return False

# # --- 3. DEEP FETCHING (The "Pro" Upgrade) ---
# def get_article_text(url):
#     """Visits the site and scrapes real text paragraphs."""
#     try:
#         r = requests.get(url, headers=HEADERS, timeout=10)
#         soup = BeautifulSoup(r.content, 'html.parser')
#         # Get first 15 paragraphs to ensure we have context
#         paragraphs = soup.find_all('p')
#         text = " ".join([p.get_text() for p in paragraphs[:15]])
#         return text.strip()
#     except:
#         return None

# def fetch_fresh_news(history_data):
#     random.shuffle(RSS_FEEDS)
    
#     for feed_url in RSS_FEEDS:
#         print(f"Checking feed: {feed_url}...")
#         feed = feedparser.parse(feed_url)
#         if not feed.entries: continue
        
#         for entry in feed.entries[:3]:
#             if not is_already_posted(entry.link, history_data):
#                 print(f"🔍 Found candidate: {entry.title}")
                
#                 # Get the Full Context (Deep Scrape)
#                 full_text = get_article_text(entry.link)
#                 if not full_text or len(full_text) < 200:
#                     print("   -> Content too short/unreadable. Skipping.")
#                     continue
                
#                 # Get Image (Optional)
#                 image_url = None
#                 try:
#                     r = requests.get(entry.link, headers=HEADERS, timeout=5)
#                     soup = BeautifulSoup(r.content, 'html.parser')
#                     meta = soup.find("meta", property="og:image")
#                     if meta: image_url = meta["content"]
#                 except: pass

#                 return {
#                     "title": entry.title,
#                     "link": entry.link,
#                     "full_text": full_text,
#                     "image_url": image_url
#                 }
#     return None


# def generate_viral_post(news_item):
#     """
#     Generates content using the Gemini REST API directly (Bypassing the buggy library).
#     """
#     url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
#     headers = {
#         "Content-Type": "application/json"
#     }
    
#     prompt_text = f"""
#     Act as a Senior Software Architect. Read this technical article context:
#     "{news_item['full_text'][:2500]}..."
    
#     Write a LinkedIn post.
#     Rules:
#     1. Start with a Hook (a specific technical insight or "Hot Take").
#     2. Explain WHY this matters to developers in 1-2 sentences.
#     3. Use bullet points if listing features.
#     4. End with a thought-provoking question.
#     5. Link: {news_item['link']}
#     6. Tags: #tech #engineering #learning
#     7. Keep it under 200 words.
#     """
    
#     payload = {
#         "contents": [{
#             "parts": [{"text": prompt_text}]
#         }]
#     }
    
#     try:
#         response = requests.post(url, headers=headers, json=payload)
        
#         if response.status_code == 200:
#             return response.json()['candidates'][0]['content']['parts'][0]['text']
#         else:
#             print(f"⚠️ AI Error {response.status_code}: {response.text}")
#             # Fallback text if AI fails
#             return f"🔥 Breaking Tech News: {news_item['title']}\n\nRead more here: {news_item['link']}\n\n#tech #news"
            
#     except Exception as e:
#         print(f"⚠️ AI Connection Failed: {e}")
#         return f"Interesting update in tech: {news_item['title']}\n{news_item['link']}"





# # --- 5. LINKEDIN PUBLISHING ---
# def post_to_linkedin(content, image_url):
#     headers = {
#         "Authorization": f"Bearer {ACCESS_TOKEN}",
#         "Content-Type": "application/json",
#         "X-Restli-Protocol-Version": "2.0.0"
#     }
    
#     # Register & Upload Image (If available)
#     asset = None
#     if image_url:
#         try:
#             reg_resp = requests.post(
#                 "https://api.linkedin.com/v2/assets?action=registerUpload",
#                 headers=headers,
#                 json={
#                     "registerUploadRequest": {
#                         "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
#                         "owner": LINKEDIN_PERSON_URN,
#                         "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]
#                     }
#                 }
#             )
#             data = reg_resp.json()
#             upload_url = data['value']['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
#             asset = data['value']['asset']
            
#             requests.put(upload_url, data=requests.get(image_url, headers=HEADERS).content, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
#         except:
#             print("⚠️ Image upload failed. Posting text only.")
#             asset = None

#     # Create Post
#     post_body = {
#         "author": LINKEDIN_PERSON_URN,
#         "lifecycleState": "PUBLISHED",
#         "specificContent": {
#             "com.linkedin.ugc.ShareContent": {
#                 "shareCommentary": {"text": content},
#                 "shareMediaCategory": "IMAGE" if asset else "NONE",
#                 "media": [{"status": "READY", "media": asset}] if asset else []
#             }
#         },
#         "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
#     }
    
#     r = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=post_body)
#     return r.status_code == 201

# # --- MAIN EXECUTION ---
# if __name__ == "__main__":
#     mimic_human_timing()
    
#     history = load_history()
#     news = fetch_fresh_news(history)
    
#     if not news:
#         print("❌ No valid news found today.")
#         exit()
        
#     print(f"🚀 Drafting post for: {news['title']}")
#     post_text = generate_viral_post(news)
    
#     if post_to_linkedin(post_text, news['image_url']):
#         print("✅ Posted to LinkedIn!")
        
#         # Create Detailed History Entry
#         now = datetime.datetime.now()
#         new_record = {
#             "date": now.strftime("%Y-%m-%d"),
#             "day": now.strftime("%A"),
#             "article_name": news['title'],
#             "web_link": news['link']
#         }
        
#         save_history(history, new_record)
#         print("📁 History Updated.")
#     else:
#         print("❌ LinkedIn API Error.")