import os
import json
import hashlib
import feedparser
import requests

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MEMORY_FILE = "seen_news.json"

RSS_FEEDS = [
    "https://hnrss.org/newest?q=AI",
    "https://openai.com/news/rss.xml",
    "https://www.anthropic.com/news/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://huggingface.co/blog/feed.xml",
    "https://www.reddit.com/r/singularity/.rss"
]


# =========================
# MEMORY
# =========================

def load_memory():

    if not os.path.exists(MEMORY_FILE):
        return []

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print("MEMORY LOAD ERROR:", e)
        return []


def save_memory(memory):

    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print("MEMORY SAVE ERROR:", e)


def make_news_id(title):

    return hashlib.md5(title.lower().encode()).hexdigest()


# =========================
# FETCH NEWS
# =========================

def fetch_news(memory):

    news = []

    seen_titles = set()

    bad_words = [
        "hiring",
        "self-promotion",
        "who wants to be hired",
        "monthly thread",
        "career",
        "job"
    ]

    for feed_url in RSS_FEEDS:

        print(f"CHECKING FEED: {feed_url}")

        feed = feedparser.parse(feed_url)

        for entry in feed.entries[:5]:

            title = entry.title.strip()
            link = entry.link

            news_id = make_news_id(title)

            # MEMORY FILTER
            if news_id in memory:
                continue

            # DUPLICATES FILTER
            if title in seen_titles:
                continue

            # TRASH FILTER
            if any(word.lower() in title.lower() for word in bad_words):
                continue

            seen_titles.add(title)

            news.append({
                "id": news_id,
                "title": title,
                "url": link
            })

    return news[:8]


# =========================
# GROQ ANALYSIS
# =========================

def analyze_with_groq(news_list):

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    news_text = "\n\n".join([
        f"{item['title']}\n{item['url']}"
        for item in news_list
    ])

    system_prompt = """
Ты AI-аналитик новостей.

Верни ТОЛЬКО JSON массив.

Для каждой важной новости верни:
- title_ru
- summary_ru
- importance
- category
- url

ПРАВИЛА:
- максимум 4 новости
- только действительно важные новости
- игнорируй Reddit-мусор и слабые новости
- summary_ru максимум 2 коротких предложения
- весь текст только на русском языке
- importance от 1 до 10
- не добавляй markdown
- не добавляй пояснений
- не добавляй текст вне JSON
"""

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

    print("GROQ STATUS:", response.status_code)

    if response.status_code != 200:
        print(response.text)
        return []

    result = response.json()["choices"][0]["message"]["content"]

    print("\n=== RAW LLM RESPONSE ===\n")
    print(result)

    try:
        parsed = json.loads(result)
        return parsed

    except Exception as e:

        print("JSON PARSE ERROR:", e)

        send_telegram(
            "⚠️ Ошибка парсинга JSON от LLM"
        )

        return []


# =========================
# TELEGRAM
# =========================

def send_telegram(text):

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text[:4000],
            "disable_web_page_preview": False
        }
    )

    print("TELEGRAM STATUS:", response.status_code)
    print(response.text)


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

        text = (
            f"🔥 {item['title_ru']}\n\n"
            f"{item['summary_ru']}\n\n"
            f"📊 Важность: {item['importance']}/10\n"
            f"🏷 Категория: {item['category']}\n\n"
            f"🌍 Читать полностью (RU):\n"
            f"{translated_url}"
        )

        send_telegram(text)


# =========================
# MAIN
# =========================

def main():

    print("\n=== AI NEWS AGENT STARTED ===\n")

    memory = load_memory()

    print(f"MEMORY ITEMS: {len(memory)}")

    news = fetch_news(memory)

    print(f"NEW NEWS FOUND: {len(news)}")

    if not news:

        send_telegram(
            "🤖 Новых AI-новостей нет."
        )

        return

    analyzed_news = analyze_with_groq(news)

    print("\n=== PARSED NEWS ===\n")
    print(analyzed_news)

    send_news(analyzed_news)

    # SAVE MEMORY
    for item in news:
        memory.append(item["id"])

    # LIMIT MEMORY SIZE
    memory = memory[-500:]

    save_memory(memory)

    print("\n=== DONE ===\n")


if __name__ == "__main__":
    main()