# telegram_listener.py

import os
import time
import subprocess
import requests
import json

from dotenv import load_dotenv
from main import load_article
from http_client import session

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = str(os.getenv("CHAT_ID"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

LOG_FILE = "agent.log"
LOCK_FILE = "agent.lock"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

LAST_UPDATE_ID = 0

is_running = False

THREADS_DIR = "threads"

os.makedirs(THREADS_DIR, exist_ok=True)

ACTIVE_THREADS = {}


def deep_article_analysis(article):

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    prompt = f"""
Ты аналитик.

Сделай:
- подробное объяснение статьи
- без воды
- выдели главное
- объясни последствия
- объясни скрытый смысл
- если есть маркетинговый булшит — укажи это

Статья:

{article['article_text'][:12000]}
"""

    data = {
        "model": "openai/gpt-oss-20b",
        "temperature": 0.3,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    response = session.post(
        url,
        headers=headers,
        json=data,
        timeout=120
    )

    if response.status_code != 200:
        return f"Groq error: {response.text}"

    try:

        return response.json()["choices"][0]["message"]["content"]

    except:

        return "Ошибка обработки ответа LLM"
        
        
# =========================
# TELEGRAM
# =========================

def send_message(text):

    keyboard = {
        "keyboard": [
            [
                {"text": "🚀 RUN AGENT"},
                {"text": "📄 LAST LOG"}
            ],
            [
                {"text": "📊 STATUS"}
            ]
        ],
        "resize_keyboard": True
    }

    session.post(
        f"{BASE_URL}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": text[:4000],
            "reply_markup": json.dumps(keyboard)
        }
    )


# =========================
# THREAD STORAGE
# =========================

def thread_path(thread_id):

    return os.path.join(
        THREADS_DIR,
        f"{thread_id}.json"
    )


# =========================
# LOAD THREAD
# =========================
def load_thread(thread_id):

    path = thread_path(thread_id)

    if not os.path.exists(path):
        return []

    try:

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except:

        return []


# =========================
# SAVE THREAD
# =========================
def save_thread(thread_id, data):

    path = thread_path(thread_id)

    with open(path, "w", encoding="utf-8") as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================
# GROQ
# =========================

def call_groq(messages):

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "openai/gpt-oss-20b",
        "messages": messages,
        "temperature": 0.3
    }

    response = session.post(
        url,
        headers=headers,
        json=data,
        timeout=120
    )

    if response.status_code != 200:

        return f"❌ Ошибка LLM: {response.text}"

    try:

        return response.json()["choices"][0]["message"]["content"]

    except Exception as e:

        return f"❌ Ошибка парсинга ответа LLM: {e}"


# =========================
# LOGS
# =========================

def get_last_logs(lines=20):

    if not os.path.exists(LOG_FILE):
        return "Лог файл не найден"

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.readlines()

    return "".join(content[-lines:])


# =========================
# LOCK FILE
# =========================

LOCK_TIMEOUT = 60 * 15


def is_locked():

    if not os.path.exists(LOCK_FILE):
        return False

    try:

        lock_time = os.path.getmtime(LOCK_FILE)

        age = time.time() - lock_time

        if age > LOCK_TIMEOUT:

            print("Removing stale lock")

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
# MAIN.PY RUNNER
# =========================

def run_agent():

    global is_running

    if is_locked():

        send_message(
            "⚠️ Агент уже работает"
        )

        return

    is_running = True

    create_lock()

    send_message(
        "🚀 Запускаю AI News Agent..."
    )

    try:

        process = subprocess.Popen(
            ["python3", "main.py"]
        )
        
        send_message(
            "🚀 Агент запущен в фоне"
        )
        
    except Exception as e:

        send_message(f"❌ Exception: {e}")

    finally:

        remove_lock()

        is_running = False


# =========================
# CALLBACK HANDLER
# =========================

def handle_callback(data, chat_id):

    # =====================
    # MORE
    # =====================

    if data.startswith("more:"):

        news_id = data.split(":")[1]

        article = load_article(news_id)

        if not article:

            send_message("❌ Статья не найдена")

            return

        send_message("🧠 Анализирую статью...")

        thread = load_thread(news_id)

        # первый запуск
        if not thread:

            system_prompt = f"""
Ты AI-аналитик новостей.

Ниже полная статья.

ТВОЯ ЗАДАЧА:
- объяснить суть
- убрать воду
- показать последствия
- объяснить почему это важно

СТАТЬЯ:

{article['article_text']}
"""

            thread = [
                {
                    "role": "system",
                    "content": system_prompt
                }
            ]

            summary = call_groq(thread)

            thread.append({
                "role": "assistant",
                "content": summary
            })
            
            MAX_THREAD_MESSAGES = 12
            
            if len(thread) > MAX_THREAD_MESSAGES:
            
                system_message = thread[0]
            
                recent_messages = thread[-11:]
            
                thread = [
                    system_message
                ] + recent_messages
            
            save_thread(news_id, thread)

        else:

            summary = thread[-1]["content"]

        ACTIVE_THREADS[chat_id] = news_id

        send_message(
            f"🧠 Разбор статьи:\n\n{summary}\n\n"
            f"💬 Теперь можешь задавать вопросы по статье."
        )

        return

    # =====================
    # CHAT
    # =====================

    if data.startswith("chat:"):

        news_id = data.split(":")[1]

        ACTIVE_THREADS[chat_id] = news_id

        send_message(
            "💬 Режим обсуждения включён.\n"
            "Теперь можешь задавать вопросы."
        )

        return


# =========================
# COMMAND HANDLER
# =========================

def handle_command(text, chat_id):

    text = text.strip()

    # =====================
    # THREAD CHAT
    # =====================

    if chat_id in ACTIVE_THREADS:
    
        thread_id = ACTIVE_THREADS[chat_id]
    
        thread = load_thread(thread_id)
    
        if not thread:
    
            send_message("❌ Thread не найден")
    
            return
    
        send_message("🧠 Думаю...")
    
        thread.append({
            "role": "user",
            "content": text
        })
    
        answer = call_groq(thread)
    
        thread.append({
            "role": "assistant",
            "content": answer
        })
    
        MAX_THREAD_MESSAGES = 12
    
        if len(thread) > MAX_THREAD_MESSAGES:
    
            system_message = thread[0]
    
            recent_messages = thread[-11:]
    
            thread = [
                system_message
            ] + recent_messages
    
        save_thread(thread_id, thread)
    
        send_message(answer)
    
        return

    # =====================
    # RUN
    # =====================

    if text in ["/run", "🚀 RUN AGENT"]:

        run_agent()

    elif text in ["/status", "📊 STATUS"]:

        if is_running:
            send_message("🟢 Агент сейчас работает")
        else:
            send_message("⚪ Агент сейчас не работает")

    elif text in ["/lastlog", "📄 LAST LOG"]:

        logs = get_last_logs()

        send_message(
            f"📄 Последние строки лога:\n\n{logs}"
        )

    elif text == "/exit":

        if chat_id in ACTIVE_THREADS:

            del ACTIVE_THREADS[chat_id]

            send_message(
                "❌ Режим обсуждения статьи выключен"
            )

        else:

            send_message(
                "ℹ️ Нет активного обсуждения"
            )

    else:

        send_message(
            "🤖 AI News Agent готов."
        )


# =========================
# LISTENER LOOP
# =========================

print("Telegram listener started")

retry_delay = 2

while True:

    try:

        response = session.get(
            f"{BASE_URL}/getUpdates",
            params={
                "offset": LAST_UPDATE_ID + 1,
                "timeout": 30
            },
            timeout=35
        )

        data = response.json()
        
        retry_delay = 2
        
        for update in data.get("result", []):

            LAST_UPDATE_ID = update["update_id"]

            # =====================
            # CALLBACK
            # =====================

            callback = update.get("callback_query")

            if callback:

                data = callback["data"]

                chat_id = str(
                    callback["message"]["chat"]["id"]
                )

                handle_callback(data, chat_id)

                continue

            # =====================
            # MESSAGE
            # =====================

            message = update.get("message")

            if not message:
                continue

            chat_id = str(message["chat"]["id"])

            if chat_id != CHAT_ID:
                continue

            text = message.get("text", "")

            handle_command(text, chat_id)

    except Exception as e:
    
        print("Listener error:", e)
    
        time.sleep(retry_delay)
    
        retry_delay = min(
            retry_delay * 2,
            60
        )

    time.sleep(2)