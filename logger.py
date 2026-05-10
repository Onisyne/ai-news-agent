from datetime import datetime

def log(message):

    with open("agent.log", "a", encoding="utf-8") as f:

        f.write(
            f"[{datetime.now()}] {message}\n"
        )