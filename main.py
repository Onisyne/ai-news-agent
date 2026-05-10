import os
import json
import hashlib
import feedparser
import requests

from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MEMORY_FILE = "seen_news.json"
CONFIG_FILE = "config.json"
PREFERENCES_FILE = "user_preferences.json"
PROMPT_FILE = "system_prompt.txt"
LOG_FILE = "agent.log"


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
            return json.load(f)

    except:
        return []


def save_memory(memory):

    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


def make_news_id(title):

    return hashlib.md5(
        title.lower().encode()
    ).hexdigest()


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

    for feed_url in config["rss_feeds"]:

        log(f"Checking feed: {feed_url}")

        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:8]:

            title = entry.title.strip()
            link = entry.link

            title_lower = title.lower()

            news_id = make_news_id(title)

            # memory filter
            if news_id in memory:
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

            local_score = calculate_local_score(title)

            # ignore weak news
            MIN_SCORE = 1
            
            if len(memory) < 50:
                MIN_SCORE = 0
            
            if local_score < MIN_SCORE:
                continue


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

    return news[:config["max_input_news"]]


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
            f"TITLE: {item['title']}\n"
            f"SCORE: {item['local_score']}\n"
            f"URL: {item['url']}"
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

    response = requests.post(
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

def send_telegram(text):

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text[:4000],
            "disable_web_page_preview": False
        }
    )

    log(f"Telegram status: {response.status_code}")


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

        send_telegram(text)


# =========================
# MAIN
# =========================

def main():

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

    log(f"Analyzed news count: {len(analyzed_news)}")

    send_news(analyzed_news)

    # save memory
    for item in news:
        memory.append(item["id"])

    # limit memory
    memory = memory[-config["max_memory_items"]:]

    save_memory(memory)

    log("=== DONE ===")


if __name__ == "__main__":
    main()