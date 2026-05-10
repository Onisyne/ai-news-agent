import subprocess
import os
from prompt_toolkit.shortcuts import checkboxlist_dialog, input_dialog, message_dialog, button_dialog

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def run_git(args: list) -> tuple:
    """Запускает git-команду. Возвращает (успех, вывод)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            env=ENV,
            cwd=PROJECT_DIR
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output
    except FileNotFoundError:
        return False, "Error: git не найден в PATH"


def get_tracking_branch():
    """Возвращает upstream-ветку (например, 'original/main')."""
    ok, output = run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if ok and output:
        return output
    ok2, branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if not ok2:
        return None
    ok3, remote = run_git(["config", f"branch.{branch}.remote"])
    remote = remote if (ok3 and remote) else "original"
    return f"{remote}/{branch}"


def get_unpushed_commits():
    """Возвращает список коммитов, которых нет на upstream."""
    upstream = get_tracking_branch()
    if not upstream:
        return ""
    ok, _ = run_git(["rev-parse", "--verify", upstream])
    if not ok:
        return ""
    ok, output = run_git(["log", f"{upstream}..HEAD", "--oneline"])
    if not ok or not output:
        return ""
    return output


def do_push():
    """Выполняет push, при необходимости запрашивает токен."""
    print("🚀 Попытка отправки...")
    ok, push_res = run_git(["push", "original", "main"])

    if not ok and any(
        keyword in push_res
        for keyword in ("Authentication failed", "fatal", "Permission denied",
                        "could not read Username", "terminal prompts disabled")
    ):
        token = input_dialog(
            title="Нужен доступ",
            text="GitHub требует токен.\nОн будет сохранен автоматически:",
            password=True
        ).run()

        if not token:
            print("Push отменен.")
            return

        run_git(["config", "--global", "credential.helper", "store"])

        ok_url, remote_url = run_git(["remote", "get-url", "original"])
        if not ok_url:
            print(f"❌ Не удалось получить URL remote: {remote_url}")
            return

        clean_url = remote_url.replace("https://", "").replace("http://", "")
        auth_url = f"https://x-access-token:{token}@{clean_url}"

        print("🔑 Регистрируем токен...")
        result = subprocess.run(
            ["git", "push", auth_url, "main"],
            capture_output=True,
            text=True,
            env=ENV
        )

        if result.returncode == 0:
            message_dialog(
                title="Успех",
                text="Готово! Токен запомнен.\nБольше вводить его не нужно."
            ).run()
        else:
            error_out = (result.stdout + result.stderr).strip()
            print(f"❌ Ошибка push: {error_out}")
    elif ok:
        print("🚀 Успешно запушено!")
        message_dialog(title="GitHub", text="Все изменения успешно отправлены!").run()
    else:
        print(f"❌ Ошибка push: {push_res}")


def do_gdrive_sync():
    """Синхронизирует проект в папку Hai-project на Google Drive."""
    project_dir = PROJECT_DIR
    project_name = os.path.basename(project_dir)
    dest = f"gdrive:{project_name}"

    print(f"☁️ Синхронизация в {dest} ...")
    try:
        result = subprocess.run(
            [
                "rclone", "sync", project_dir, dest,
                "--exclude", ".git/**",
                "--exclude", "**/__pycache__/**",
                "--progress",
            ],
            text=True,
            env=ENV
        )
        if result.returncode == 0:
            message_dialog(
                title="Google Drive",
                text=f"✅ Проект успешно выгружен в\n{dest}"
            ).run()
        else:
            message_dialog(
                title="Ошибка",
                text="❌ rclone завершился с ошибкой.\nПроверь вывод в терминале."
            ).run()
    except FileNotFoundError:
        message_dialog(
            title="Ошибка",
            text="❌ rclone не найден.\nУстанови: pkg install rclone"
        ).run()


def do_pull():
    """Выполняет pull с upstream."""
    print("⬇️ Скачиваем изменения...")
    ok, out = run_git(["pull", "original", "main"])
    if ok:
        message_dialog(title="Pull", text=f"✅ Готово!\n\n{out}").run()
    else:
        message_dialog(title="Ошибка Pull", text=f"❌ {out}").run()


def is_git_repo() -> bool:
    """Проверяет, является ли текущая папка git-репозиторием."""
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", PROJECT_DIR],
        capture_output=True, env=ENV
    )
    ok, _ = run_git(["rev-parse", "--git-dir"])
    return ok


def init_repo(project_name: str) -> bool:
    """Инициализирует git-репо и подключает к GitHub."""
    # Разрешаем git работать с этой папкой
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", PROJECT_DIR],
        capture_output=True, env=ENV
    )

    # Инициализация
    ok, out = run_git(["init", "-b", "main"])
    if not ok:
        print(f"❌ Ошибка git init: {out}")
        return False

    # Запрашиваем токен для создания репо через API
    token = input_dialog(
        title="GitHub токен",
        text="Введи Personal Access Token\n(нужен scope: repo):",
        password=True
    ).run()
    if not token:
        print("Отмена.")
        return False

    # Создаём репозиторий на GitHub через API
    print(f"📡 Создаём репозиторий {project_name} на GitHub...")
    try:
        result = subprocess.run(
            [
                "curl", "-s", "-X", "POST",
                "-H", f"Authorization: token {token}",
                "-H", "Content-Type: application/json",
                "-d", f'{{"name":"{project_name}","private":false}}',
                "https://api.github.com/user/repos"
            ],
            capture_output=True,
            text=True,
            env=ENV
        )
        if '"full_name"' not in result.stdout:
            # Репо уже существует или ошибка — пробуем подключить как есть
            print("⚠️ Репо уже существует или ошибка API — подключаем существующее.")

        # Получаем имя пользователя
        user_result = subprocess.run(
            [
                "curl", "-s",
                "-H", f"Authorization: token {token}",
                "https://api.github.com/user"
            ],
            capture_output=True,
            text=True,
            env=ENV
        )
        import json
        user_data = json.loads(user_result.stdout)
        username = user_data.get("login", "")
        if not username:
            print("❌ Не удалось получить имя пользователя GitHub.")
            return False

        # Сохраняем токен и подключаем remote
        run_git(["config", "--global", "credential.helper", "store"])
        remote_url = f"https://x-access-token:{token}@github.com/{username}/{project_name}.git"
        run_git(["remote", "add", "original", remote_url])

        # Первый коммит
        run_git(["add", "."])
        ok, out = run_git(["commit", "-m", "init"])
        if not ok and "nothing to commit" not in out:
            print(f"❌ Ошибка коммита: {out}")
            return False

        # Push
        print("🚀 Отправляем...")
        ok, out = run_git(["push", "-u", "original", "main"])
        if not ok:
            print(f"❌ Ошибка push: {out}")
            return False

        message_dialog(
            title="Готово!",
            text=f"✅ Репозиторий создан и подключен:\ngithub.com/{username}/{project_name}"
        ).run()
        return True

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


def main():
    # --- ПРОВЕРКА: является ли папка git-репозиторием ---
    if not is_git_repo():
        project_dir = PROJECT_DIR
        project_name = os.path.basename(project_dir)

        action = button_dialog(
            title="Не git-репозиторий",
            text=f"Папка «{project_name}» не подключена к GitHub.\n\nСоздать репозиторий?",
            buttons=[
                ("Создать", "create"),
                ("Выход", "exit"),
            ]
        ).run()

        if action != "create":
            return

        if not init_repo(project_name):
            return
        # После успешной инициализации продолжаем как обычно
    # --- ШАГ 1: СТАРТОВОЕ МЕНЮ ---
    unpushed = get_unpushed_commits()

    if unpushed:
        text = f"Коммиты ожидают отправки:\n\n{unpushed}\n\nЧто делаем?"
        action = button_dialog(
            title="Git — Старт",
            text=text,
            buttons=[
                ("Запушить", "push"),
                ("Скачать", "pull"),
                ("Drive", "drive"),
                ("Продолжить", "continue"),
                ("Выход", "exit"),
            ]
        ).run()
    else:
        action = button_dialog(
            title="Git — Старт",
            text="Незапушенных коммитов нет.\n\nЧто делаем?",
            buttons=[
                ("Скачать", "pull"),
                ("Drive", "drive"),
                ("Продолжить", "continue"),
                ("Выход", "exit"),
            ]
        ).run()

    if action == "exit" or action is None:
        return
    if action == "push":
        do_push()
        return
    if action == "pull":
        do_pull()
        return
    if action == "drive":
        do_gdrive_sync()
        return
    # action == "continue" — идём дальше к выбору файлов

    # --- ШАГ 2: ВЫБОР ФАЙЛОВ ---
    ok, status = run_git(["status", "--short"])
    files_to_add = []

    if ok and status:
        choices = []
        for line in status.split('\n'):
            if len(line) < 3:
                continue
            state = line[:2].strip()
            path = line[2:].strip()
            choices.append((path, f"[{state}] {path}"))

        if choices:
            files_to_add = checkboxlist_dialog(
                title="Выбор файлов",
                text="Выбери файлы для добавления (Space - выбор, Enter - OK):",
                values=choices
            ).run() or []

    # --- ШАГ 3: КОММИТ (НОВЫЙ ИЛИ ДОПОЛНЕНИЕ) ---
    if files_to_add:
        for f in files_to_add:
            ok, out = run_git(["add", "--", f])
            if not ok:
                print(f"⚠️ Не удалось добавить {f}: {out}")

        commit_action = "new"
        if unpushed:
            commit_action = button_dialog(
                title="Тип коммита",
                text="Создать новый коммит или дополнить последний?",
                buttons=[
                    ("Новый", "new"),
                    ("Дополнить", "amend"),
                    ("Отмена", "cancel")
                ]
            ).run()

        if commit_action == "cancel" or commit_action is None:
            return

        if commit_action == "amend":
            ok, out = run_git(["commit", "--amend", "--no-edit"])
            if ok:
                print("✅ Последний коммит обновлен.")
            else:
                print(f"❌ Ошибка amend: {out}")
                return
        else:
            msg = input_dialog(title="Commit", text="Введите описание изменений:").run()
            if not msg:
                print("Отмена: описание не введено.")
                return
            ok, out = run_git(["commit", "-m", msg])
            if ok:
                print(f"✅ Создан коммит: {msg}")
            else:
                print(f"❌ Ошибка коммита: {out}")
                return

    # --- ШАГ 4: ФИНАЛЬНАЯ ПРОВЕРКА И PUSH ---
    final_unpushed = get_unpushed_commits()
    if not final_unpushed:
        if not files_to_add:
            message_dialog(title="Git", text="Никаких изменений не найдено.").run()
        return

    do_push_now = button_dialog(
        title="Финальный Push",
        text=f"Будут отправлены:\n\n{final_unpushed}\n\nОтправить?",
        buttons=[
            ("Отправить", True),
            ("Отмена", False),
        ]
    ).run()

    if do_push_now:
        do_push()


if __name__ == "__main__":
    main()