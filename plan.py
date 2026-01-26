import requests
import feedparser
import json
import random
import time
import os
import datetime
import re
import google.generativeai as genai
from bs4 import BeautifulSoup

# --- CONFIGURATION ---
HISTORY_FILE = "history.json"
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_PERSON_URN", "").strip() 
ACCESS_TOKEN = os.environ.get("LINKEDIN_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# High-Quality Sources
RSS_FEEDS = [
    "https://netflixtechblog.com/feed",
    "https://eng.uber.com/feed/",
    "https://engineering.fb.com/feed/",
    "https://aws.amazon.com/blogs/architecture/feed/",
    "https://devblogs.microsoft.com/feed/",
    "https://github.blog/feed/",
    "https://stackoverflow.blog/feed/",
    "https://techcrunch.com/feed/"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Configure Gemini
if not GEMINI_API_KEY:
    print("❌ ERROR: GEMINI_API_KEY is missing from environment variables.")
    exit()

genai.configure(api_key=GEMINI_API_KEY)

# --- 1. DEEP CONTENT SCRAPER ---
def get_article_content(url):
    """
    Visits the link and scrapes the actual P tags to get the full story.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        
        # Fallback for sites that block bots (403/401)
        if r.status_code != 200:
            print(f"⚠️ Access denied or error ({r.status_code}) for: {url}")
            return None
            
        soup = BeautifulSoup(r.content, 'html.parser')
        
        # Find all paragraphs
        paragraphs = soup.find_all('p')
        
        # If <p> tags are empty, try generic divs (fallback)
        if not paragraphs:
            paragraphs = soup.find_all('div', class_=re.compile('(content|post|article|body)'))

        # Join the first 15 paragraphs (approx 1000-1500 words)
        full_text = " ".join([p.get_text() for p in paragraphs[:15]])
        
        if len(full_text) < 300: # If scraping failed or content is too short
            return None
            
        return full_text.strip()
    except Exception as e:
        print(f"⚠️ Scraping failed for {url}: {e}")
        return None

# --- 2. THE AI JUDGE (Quality Control) ---
def evaluate_article(title, text):
    """
    Asks Gemini: 'Is this article actually important?'
    Returns a score (1-10) and a reason.
    Includes Robust JSON Parsing.
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    Act as a Senior Tech Editor. Analyze this article summary:
    
    Title: {title}
    Snippet: {text[:1000]}...
    
    Task: Rate this article for a LinkedIn audience of developers.
    Criteria:
    1. Is it a major tech update or just a small tutorial?
    2. Is it trending or generic?
    
    Return ONLY a JSON string like this:
    {{"score": 8, "reason": "Major release of Python 4.0"}}
    """
    
    try:
        response = model.generate_content(prompt)
        raw_output = response.text
        
        # --- ROBUST JSON PARSING START ---
        # 1. Try stripping markdown
        clean_json = raw_output.replace("```json", "").replace("```", "").strip()
        
        try:
            return json.loads(clean_json)
        except json.JSONDecodeError:
            # 2. Regex Search Fallback (Finds content between first { and last })
            match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            else:
                print(f"⚠️ JSON Parse Fail. Raw Output: {raw_output}")
                return {"score": 5, "reason": "Parsing Error"}
        # --- ROBUST JSON PARSING END ---
        
    except Exception as e:
        print(f"⚠️ AI Evaluation Error: {e}")
        return {"score": 5, "reason": "AI Error"}

# --- 3. SMART FETCHER ---
def fetch_best_article(history_data):
    # Randomize feed order
    random.shuffle(RSS_FEEDS)
    
    print("🔍 Scanning feeds for high-quality news...")
    
    for feed_url in RSS_FEEDS[:5]: # Check 5 random feeds per run
        try:
            feed = feedparser.parse(feed_url)
        except:
            continue
        
        for entry in feed.entries[:2]: # Look at top 2 posts only
            if is_already_posted(entry.link, history_data):
                continue
                
            # 1. Get Content
            full_text = get_article_content(entry.link)
            if not full_text: continue
            
            # Rate Limit Protection
            time.sleep(2) 
            
            # 2. AI Judge
            evaluation = evaluate_article(entry.title, full_text)
            print(f"   -> Evaluated: {entry.title[:30]}... | Score: {evaluation['score']}/10")
            
            if evaluation['score'] >= 7: # Only accept High Quality (7+)
                return {
                    "title": entry.title,
                    "link": entry.link,
                    "full_text": full_text,
                    "reason": evaluation['reason']
                }
                
    return None

# --- 4. FORMATTING UTILS ---
def to_bold(text):
    """Unicode Bold Hack"""
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    bold   = "𝐇𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙𝐡𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"
    trans = str.maketrans(normal, bold)
    return text.translate(trans)

# --- 5. POST GENERATOR ---
def generate_linkedin_post(article):
    model = genai.GenerativeModel('gemini-1.5-flash')
    
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
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        
        if not raw_text:
            return None
        
        # Apply Bold to the first line manually
        lines = raw_text.split('\n')
        if lines:
            lines[0] = to_bold(lines[0].replace("*", "").replace("#", "")) # Remove markdown chars
        
        final_post = "\n".join(lines) + f"\n\n🔗 Read more: {article['link']}"
        return final_post
        
    except Exception as e:
        print(f"⚠️ Generation Error: {e}")
        return None

# --- 6. LINKEDIN API ---
def post_to_linkedin(content):
    if not ACCESS_TOKEN or not LINKEDIN_PERSON_URN:
        print("❌ Error: Missing LinkedIn Credentials in Environment Variables.")
        return False

    url = "https://api.linkedin.com/v2/ugcPosts"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }
    
    # Clean URN to avoid "urn:li:person:urn:li:person:123" error
    clean_urn = LINKEDIN_PERSON_URN.replace("urn:li:person:", "")
    
    payload = {
        "author": f"urn:li:person:{clean_urn}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": content},
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload)
        
        if r.status_code == 201:
            return True
        else:
            print(f"❌ LinkedIn API Error: {r.status_code}")
            print(f"❌ Details: {r.text}") # Print exact error details
            return False
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return False

# --- HISTORY UTILS ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f: return json.load(f)
        except: return []
    return []

def save_history(history, link):
    history.append({"link": link, "date": str(datetime.date.today())})
    if len(history) > 50: history = history[-50:]
    with open(HISTORY_FILE, "w") as f: json.dump(history, f)

def is_already_posted(link, history):
    for h in history:
        if h['link'] == link: return True
    return False

# --- MAIN ---
if __name__ == "__main__":
    print("🎬 LinkedIn Bot Starting...")
    history = load_history()
    
    # 1. Find a worthy article
    best_article = fetch_best_article(history)
    
    if best_article:
        print(f"🚀 Selected: {best_article['title']}")
        
        # 2. Write Post
        post_content = generate_linkedin_post(best_article)
        
        if post_content:
            print("📝 Drafted Post:\n", "-"*20)
            print(post_content)
            print("-"*20)
            
            # 3. Publish
            if post_to_linkedin(post_content):
                print("✅ Published Successfully!")
                save_history(history, best_article['link'])
            else:
                print("❌ Failed to publish.")
        else:
            print("❌ Error generating post content.")
    else:
        print("😴 No articles scored high enough (7/10) to post right now.")