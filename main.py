# main.py

import os
import json
import hashlib
import feedparser
import requests
import time

from dotenv import load_dotenv
from datetime import datetime
from article_extractor import extract_article
from http_client import session

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MEMORY_FILE = "seen_news.json"
CONFIG_FILE = "config.json"
PREFERENCES_FILE = "user_preferences.json"
PROMPT_FILE = "system_prompt.txt"
LOG_FILE = "agent.log"
LOCK_FILE = "main.lock"

MAX_ARTICLE_FOR_LLM = 1200


# =========================
# MAKE ARTICLE PREVIEW
# =========================

def make_article_preview(text, max_chars=1200):

    paragraphs = text.split("\n")

    result = []

    total = 0

    for p in paragraphs:

        if total + len(p) > max_chars:
            break

        result.append(p)

        total += len(p)

    return "\n".join(result)
    
    
# =========================
# LOGGER
# =========================

def log(message):

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    line = f"[{timestamp}] {message}"

    print(line)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# =========================
# LOAD JSON FILES
# =========================

def load_json(path):

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_prompt():

    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()


config = load_json(CONFIG_FILE)
preferences = load_json(PREFERENCES_FILE)
system_prompt = load_prompt()


# =========================
# MEMORY
# =========================

def load_memory():

    if not os.path.exists(MEMORY_FILE):
        return []

    try:

        with open(MEMORY_FILE, "r", encoding="utf-8") as f:

            data = json.load(f)

            # старый формат
            if data and isinstance(data[0], str):

                return [
                    {
                        "id": x,
                        "timestamp": None
                    }
                    for x in data
                ]

            return data

    except:
        return []

def save_memory(memory):

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def make_news_id(title, url):

    raw = f"{title}::{url}"

    return hashlib.md5(
        raw.lower().encode()
    ).hexdigest()


# =========================
# ARTICLE STORAGE
# =========================

ARTICLES_DIR = "articles"


def save_article(article_data):

    # создать папку если нет
    os.makedirs(ARTICLES_DIR, exist_ok=True)

    article_id = article_data["id"]

    path = os.path.join(
        ARTICLES_DIR,
        f"{article_id}.json"
    )

    with open(path, "w", encoding="utf-8") as f:

        json.dump(
            article_data,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_article(article_id):

    path = os.path.join(
        ARTICLES_DIR,
        f"{article_id}.json"
    )

    if not os.path.exists(path):
        return None

    try:

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except:

        return None
        
        
# =========================
# LOCAL SCORING
# =========================

def calculate_local_score(title):

    score = 0

    title_lower = title.lower()

    # keyword scoring
    for keyword in config["good_keywords"]:

        if keyword.lower() in title_lower:
            score += 2

    # company preference scoring
    for company in preferences["important_companies"]:

        if company.lower() in title_lower:
            score += 3

    # liked topics
    for topic in preferences["liked_topics"]:

        normalized = topic.replace("_", " ")

        if normalized.lower() in title_lower:
            score += 2

    # disliked topics
    for topic in preferences["disliked_topics"]:

        normalized = topic.replace("_", " ")

        if normalized.lower() in title_lower:
            score -= 3

    return score


# =========================
# FETCH NEWS
# =========================

def fetch_news(memory):

    news = []

    seen_titles = set()

    feeds = config.get("rss_feeds", []) + config.get("extra_feeds", [])
    log(f"Total feeds: {len(feeds)}")
    feeds = list(set(feeds))  # убираем дубли

    for feed_url in feeds:

        log(f"Checking feed: {feed_url}")

        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:8]:

            title = entry.title.strip()
            link = entry.link

            title_lower = title.lower()

            news_id = make_news_id(title, link)

            # memory filter
            seen_ids = {
                item["id"]
                for item in memory
            }
            
            if news_id in seen_ids:
                continue

            # duplicates
            if title in seen_titles:
                continue

            # trash filter
            if any(
                word.lower() in title_lower
                for word in config["bad_words"]
            ):
                continue

            local_score = 3 + calculate_local_score(title)

            log(f"SCORE: {title} -> {local_score}")
            
            # soft penalty
            if any(word.lower() in title.lower() for word in config["bad_words"]):
                local_score = max(0, local_score - config["penalty"])
                log(f"Penalty applied: {title} score={local_score}")
                            
            seen_titles.add(title)
            
            news.append({
                "id": news_id,
                "title": title,
                "url": link,
                "local_score": local_score
            })

    news.sort(
        key=lambda x: x["local_score"],
        reverse=True
    )

    TOP_FETCH = config.get("TOP_FETCH", 10)

    top_candidates = news[:TOP_FETCH]
    
    final_news = []
    
    for item in top_candidates:
    
        article_text = extract_article(
            item["url"]
        )
    
        if len(article_text) < 500:
    
            log(
                f"SKIP SHORT ARTICLE: {item['title']}"
            )
    
            continue
    
        item["article_text"] = article_text
    
        final_news.append(item)
    
    news = final_news
    
    TOP_N = config.get("TOP_N", 5)
    
    selected = news[:TOP_N]
    
    log("TOP NEWS:")
    for n in selected:
        log(f"{n['local_score']} -> {n['title']}")
    
    return selected


# =========================
# GROQ
# =========================

def analyze_with_groq(news_list):

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    news_text = "\n\n".join([
        (
            f"ID: {item['id']}\n"
            f"TITLE: {item['title']}\n"
            f"SCORE: {item['local_score']}\n"
            f"ARTICLE:\n{make_article_preview(item['article_text'])}"
        )
        for item in news_list
    ])

    data = {
        "model": "openai/gpt-oss-20b",
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": news_text
            }
        ]
    }

    response = session.post(
        url,
        headers=headers,
        json=data,
        timeout=60
    )

    log(f"Groq status: {response.status_code}")

    if response.status_code != 200:

        log(response.text)

        return []

    result = response.json()["choices"][0]["message"]["content"]

    try:

        cleaned = result.strip()

        # убрать markdown
        cleaned = cleaned.replace("```json", "")
        cleaned = cleaned.replace("```", "")

        # найти JSON
        start = cleaned.find("[")
        end = cleaned.rfind("]")

        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]

        parsed = json.loads(cleaned)

        if not isinstance(parsed, list):
            raise Exception("LLM did not return list")

        return parsed

    except Exception as e:

        log(f"JSON parse error: {e}")

        log("RAW RESPONSE:")
        log(result)

        send_telegram(
            "⚠️ LLM вернула плохой JSON"
        )

        return []

# =========================
# TELEGRAM
# =========================

def send_telegram(text, reply_markup=None):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text[:4000],
        "disable_web_page_preview": False
    }

    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    response = session.post(url, data=payload)

    log(f"Telegram status: {response.status_code}")

    if response.status_code != 200:
        
        log(response.text)



def send_news(news_json):

    if not news_json:

        send_telegram(
            "🤖 Сегодня AI-индустрия либо спит, либо LLM опять галлюцинирует."
        )

        return

    for item in news_json:

        translated_url = (
            "https://translate.google.com/translate?"
            f"sl=auto&tl=ru&u={item['url']}"
        )

        importance = item.get("importance", 0)

        if importance >= 8:
            emoji = "🚨"

        elif importance >= 6:
            emoji = "🔥"

        else:
            emoji = "📰"

        text = (
            f"{emoji} {item['title_ru']}\n\n"
            f"{item['summary_ru']}\n\n"
            f"💡 Почему важно:\n"
            f"{item['why_relevant']}\n\n"
            f"📊 Важность: {importance}/10\n"
            f"🏷 Категория: {item['category']}\n\n"
            f"🌍 Читать полностью (RU):\n"
            f"{translated_url}"
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "📖 Подробнее",
                        "callback_data": f"more:{item['id']}"
                    },
                    {
                        "text": "💬 Обсудить",
                        "callback_data": f"chat:{item['id']}"
                    }
                ]
            ]
        }
        
        send_telegram(text, reply_markup=keyboard)
        
# =========================
# LOCK FILE
# =========================

LOCK_TIMEOUT = 60 * 15  # 15 минут

def is_locked():

    if not os.path.exists(LOCK_FILE):
        return False

    try:

        lock_time = os.path.getmtime(LOCK_FILE)

        age = time.time() - lock_time

        if age > LOCK_TIMEOUT:

            log("Removing stale lock")

            os.remove(LOCK_FILE)

            return False

        return True

    except:

        return False


def create_lock():

    with open(LOCK_FILE, "w") as f:
        f.write(str(time.time()))


def remove_lock():

    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
        
        
# =========================
# MAIN
# =========================

def main():

    if is_locked():

        log("Another instance already running")

        return

    create_lock()

    try:

        log("=== AI NEWS AGENT STARTED ===")

        memory = load_memory()

        log(f"Memory items: {len(memory)}")

        news = fetch_news(memory)

        log(f"Filtered news: {len(news)}")

        if not news:

            send_telegram(
                "🤖 Новых важных AI-новостей нет."
            )

            return

        analyzed_news = analyze_with_groq(news)

        # save analyzed articles
        for original, analyzed in zip(news, analyzed_news):
        
            article_data = {
        
                "id": original["id"],
        
                "title": original["title"],
        
                "url": original["url"],
        
                "article_text": original["article_text"],
        
                "local_score": original["local_score"],
        
                "title_ru": analyzed.get("title_ru", ""),
        
                "summary_ru": analyzed.get("summary_ru", ""),
        
                "importance": analyzed.get("importance", 0),
        
                "category": analyzed.get("category", ""),
        
                "why_relevant": analyzed.get("why_relevant", ""),
        
                "timestamp": datetime.now().isoformat()
            }
        
            save_article(article_data)

        log(f"Analyzed news count: {len(analyzed_news)}")

        merged_news = []

        for i in range(min(len(news), len(analyzed_news))):
        
            merged_item = analyzed_news[i]
        
            merged_item["id"] = news[i]["id"]
        
            merged_item["url"] = news[i]["url"]
        
            merged_news.append(merged_item)
        
        send_news(merged_news)

        # save memory
        for item in news:
            memory.append({
                "id": item["id"],
                "timestamp": datetime.now().isoformat()
            })

        # limit memory
        memory = memory[-config["max_memory_items"]:]

        save_memory(memory)

        log("=== DONE ===")

    finally:

        remove_lock()


if __name__ == "__main__":
    main()