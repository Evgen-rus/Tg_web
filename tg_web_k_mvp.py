import time
import re
import threading
import queue
from pathlib import Path
from playwright.sync_api import sync_playwright

# =========================
# CONFIG
# =========================
CHAT_URL = "https://web.telegram.org/k/#@EvgeniiRa"
PROFILE_DIR = Path("./tg_profile")  # сохраняет сессию (логин останется)

POLL_INTERVAL = 0.5   # как часто опрашиваем чат на новые сообщения
PRINT_LAST_N = 40     # сколько последних сообщений сканируем (чтобы ловить edits/новые)

INPUT_SELECTORS = [
    "footer div[contenteditable='true']",
    "div[contenteditable='true'][data-placeholder]",
    "div[contenteditable='true']",
]

MESSAGE_SELECTORS = [
    "div.message",
    "div[class*='message']",
    ".message",
]

# =========================
# HELPERS
# =========================
def find_first(page, selectors):
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            pass
    return None


def clean_text(text: str) -> str:
    if not text:
        return ""
    # Убираем время вида HH:MM или HH:MM:SS в конце строк (часто Telegram Web так вставляет)
    text = re.sub(r"\d{1,2}:\d{2}(?::\d{2})?\s*$", "", text, flags=re.MULTILINE)
    # Убираем лишние пустые строки
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Трим строк
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines).strip()
    return text


def get_message_locator(page):
    for sel in MESSAGE_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                return loc
        except Exception:
            pass
    return None


def get_message_key(msg_loc) -> str:
    """
    Пытаемся получить стабильный ключ сообщения из атрибутов.
    Если нет — fallback на hash текста.
    """
    for attr in ("data-mid", "data-message-id", "data-id", "id"):
        try:
            v = msg_loc.get_attribute(attr)
            if v:
                return f"{attr}:{v}"
        except Exception:
            pass

    # fallback: hash текста (может склеить одинаковые сообщения, но для MVP ок)
    try:
        t = msg_loc.inner_text()
    except Exception:
        t = ""
    t = clean_text(t)
    return f"hash:{hash(t)}"


def format_message(msg_loc, text: str) -> str:
    """
    Пытаемся добавить признак исходящее/входящее по классу.
    Если не получилось — просто печатаем текст.
    """
    prefix = ""
    try:
        cls = msg_loc.get_attribute("class") or ""
        cls_low = cls.lower()
        # Telegram Web может по-разному называть, поэтому несколько эвристик
        if "out" in cls_low or "is-out" in cls_low or "message-out" in cls_low:
            prefix = "[you] "
        elif "in" in cls_low or "is-in" in cls_low or "message-in" in cls_low:
            prefix = "[in ] "
    except Exception:
        pass

    return f"{prefix}{text}" if prefix else text


def stdin_reader(out_queue: "queue.Queue[str]"):
    """
    Отдельный поток: читает из консоли и кладёт строки в очередь.
    Playwright трогать нельзя из этого потока.
    """
    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        out_queue.put(line)


# =========================
# MAIN
# =========================
def main():
    send_queue: "queue.Queue[str]" = queue.Queue()

    # поток, который читает консоль
    t = threading.Thread(target=stdin_reader, args=(send_queue,), daemon=True)
    t.start()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
        )
        page = context.new_page()
        page.goto(CHAT_URL, wait_until="domcontentloaded")

        print("Открыл Telegram Web.")
        print("1) Если не залогинен — залогинься.")
        print("2) Открой нужный чат (или проверь CHAT_URL).")
        input("Когда чат открыт — нажми Enter... ")

        input_box = find_first(page, INPUT_SELECTORS)
        if not input_box:
            raise RuntimeError("Не нашёл поле ввода. Обнови селектор через playwright codegen.")

        msg_loc = get_message_locator(page)
        if not msg_loc:
            raise RuntimeError("Не нашёл сообщения в чате. Проверь, что чат реально открыт.")

        printed = set()  # ключи уже распечатанных сообщений

        print("\nРежим моста включён:")
        print("- всё, что пишут в чате, печатается в консоль")
        print("- всё, что ты вводишь в консоль, отправляется в чат")
        print("Для выхода: Ctrl+C\n")

        # первичная печать последних сообщений (по желанию можно выключить)
        try:
            total = msg_loc.count()
            start = max(0, total - min(PRINT_LAST_N, total))
            for i in range(start, total):
                m = msg_loc.nth(i)
                key = get_message_key(m)
                text = clean_text(m.inner_text())
                if text:
                    printed.add(key)
                    print(format_message(m, text))
        except Exception:
            pass

        while True:
            try:
                # 1) отправка всего, что накопилось из консоли
                while not send_queue.empty():
                    text = send_queue.get().strip()
                    if not text:
                        continue
                    if text == "/exit":
                        raise KeyboardInterrupt

                    input_box.click()
                    input_box.fill(text)
                    input_box.press("Enter")

                # 2) печать новых сообщений из чата
                msg_loc = get_message_locator(page)
                if msg_loc:
                    total = msg_loc.count()
                    start = max(0, total - min(PRINT_LAST_N, total))

                    for i in range(start, total):
                        m = msg_loc.nth(i)
                        key = get_message_key(m)

                        if key in printed:
                            continue

                        try:
                            text = clean_text(m.inner_text())
                        except Exception:
                            text = ""

                        if text:
                            printed.add(key)
                            print(format_message(m, text))

                # иногда полезно "доскроллить" вниз, чтобы новые сообщения подгружались корректно
                try:
                    page.keyboard.press("End")
                except Exception:
                    pass

                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                print("\nВыход.")
                break

    try:
        context.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
