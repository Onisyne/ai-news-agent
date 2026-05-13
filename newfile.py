# telegram_listener.py

import os
import time
import subprocess
import requests
import json

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = str(os.getenv("CHAT_ID"))

LOG_FILE = "agent.log"
LOCK_FILE = "agent.lock"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

LAST_UPDATE_ID = 0

is_running = False


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

    requests.post(
        f"{BASE_URL}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": text[:4000],
            "reply_markup": json.dumps(keyboard)
        }
    )

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

LOCK_TIMEOUT = 60 * 15  # 15 минут


def is_locked():

    if not os.path.exists(LOCK_FILE):
        return False

    try:

        lock_time = os.path.getmtime(LOCK_FILE)

        age = time.time() - lock_time

        # lock слишком старый
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

        result = subprocess.run(
            ["python3", "main.py"],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:

            send_message(
                "✅ Агент успешно завершил работу"
            )

        else:

            send_message(
                "❌ Ошибка запуска агента"
            )

            if result.stderr:

                send_message(
                    result.stderr[:3500]
                )

    except Exception as e:

        send_message(f"❌ Exception: {e}")

    finally:

        remove_lock()

        is_running = False


# =========================
# COMMAND HANDLER
# =========================

def handle_command(text):

    text = text.strip()

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

    else:

        send_message(
            "🤖 AI News Agent готов."
        )

# =========================
# HANDLE  CALLBACK
# =========================

def handle_callback(data, chat_id):

    if data.startswith("more:"):

        news_id = data.split(":")[1]

        news = load_news_by_id(news_id)

        text = analyze_article_with_llm(news)

        send_message(text)        
# =========================
# LISTENER LOOP
# =========================

print("Telegram listener started")

while True:

    try:

        response = requests.get(
            f"{BASE_URL}/getUpdates",
            params={
                "offset": LAST_UPDATE_ID + 1,
                "timeout": 30
            },
            timeout=35
        )

        data = response.json()

        for update in data.get("result", []):

            LAST_UPDATE_ID = update["update_id"]

            message = update.get("message")

            callback = update.get("callback_query")
            
            if callback:
                data = callback["data"]
                chat_id = str(callback["message"]["chat"]["id"])
            
                handle_callback(data, chat_id)
                continue
            
            if not message:
                continue

            chat_id = str(message["chat"]["id"])

            if chat_id != CHAT_ID:
                continue

            text = message.get("text", "")

            handle_command(text)

    except Exception as e:

        print("Listener error:", e)

    time.sleep(2)