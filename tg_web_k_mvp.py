import time
import re
import threading
import queue
import hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright

# =========================
# CONFIG
# =========================
CHAT_URL = "https://web.telegram.org/k/#@EvgeniiRa"
PROFILE_DIR = Path("./tg_profile")

POLL_INTERVAL = 0.5     # частота опроса
TAIL_K = 10             # сколько последних сообщений читать
MAX_CACHE = 5000        # ограничение кэша seen

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


def _strip_private_use_chars(s: str) -> str:
    # Убирает “иконки” Telegram Web (часто в Private Use Area)
    return re.sub(r"[\uE000-\uF8FF]", "", s)


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = _strip_private_use_chars(text)

    # (опционально) убрать время в конце строк
    text = re.sub(r"\d{1,2}:\d{2}(?::\d{2})?\s*$", "", text, flags=re.MULTILINE)

    # схлопнуть лишние пустые строки
    text = re.sub(r"\n{3,}", "\n\n", text)

    # trim
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


def detect_direction_prefix(msg_loc) -> str:
    """
    Определяем вход/выход по расположению сообщения:
    справа (центр пузыря правее середины окна) -> [you]
    слева -> [in ]
    """
    try:
        side = msg_loc.evaluate(
            """(el) => {
                const r = el.getBoundingClientRect();
                const centerX = r.left + r.width / 2;
                return centerX > (window.innerWidth / 2) ? 'out' : 'in';
            }"""
        )
        return "[you] " if side == "out" else "[in ] "
    except Exception:
        return "[msg] "


def get_message_key(msg_loc) -> str:
    """
    1) Пытаемся достать стабильный message id из DOM (сам элемент/родители/дети).
    2) Если не нашли — хешируем outerHTML.
    Это устраняет повторную печать из-за “смещения индекса” в хвосте.
    """
    try:
        dom_id = msg_loc.evaluate(
            """(el) => {
                const attrs = ['data-mid','data-message-id','data-id','id','data-msg-id','data-messageid'];
                // 1) сам элемент
                for (const a of attrs) {
                    const v = el.getAttribute(a);
                    if (v) return a + ':' + v;
                }
                // 2) родители
                let p = el.parentElement;
                let up = 0;
                while (p && up < 6) {
                    for (const a of attrs) {
                        const v = p.getAttribute(a);
                        if (v) return a + ':' + v;
                    }
                    p = p.parentElement;
                    up++;
                }
                // 3) дети
                for (const a of attrs) {
                    const child = el.querySelector('[' + a + ']');
                    if (child) {
                        const v = child.getAttribute(a);
                        if (v) return a + ':' + v;
                    }
                }
                return null;
            }"""
        )
        if dom_id:
            return f"dom:{dom_id}"
    except Exception:
        pass

    # fallback: outerHTML hash
    try:
        html = msg_loc.evaluate("(el) => el.outerHTML || ''") or ""
    except Exception:
        html = ""

    h = hashlib.sha1(html.encode("utf-8", errors="ignore")).hexdigest()
    return f"html:{h}"


def stdin_reader(out_queue: "queue.Queue[str]"):
    while True:
        try:
            line = input().strip()
        except EOFError:
            break
        out_queue.put(line)


def get_tail_messages(page, k: int):
    loc = get_message_locator(page)
    if not loc:
        return []
    try:
        total = loc.count()
        if total <= 0:
            return []
        start = max(0, total - k)
        return [loc.nth(i) for i in range(start, total)]
    except Exception:
        return []


# =========================
# MAIN
# =========================
def main():
    send_queue: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=stdin_reader, args=(send_queue,), daemon=True).start()

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

        if not get_message_locator(page):
            raise RuntimeError("Не нашёл сообщения в чате. Проверь, что чат реально открыт.")

        # seen cache: key -> last_text
        seen_text: dict[str, str] = {}
        seen_order: list[str] = []

        def remember(key: str, txt: str):
            if key in seen_text:
                seen_text[key] = txt
                return
            seen_text[key] = txt
            seen_order.append(key)
            # ограничение памяти
            while len(seen_order) > MAX_CACHE:
                old = seen_order.pop(0)
                seen_text.pop(old, None)

        # При старте: ничего старого не печатаем, просто помечаем хвост как seen
        startup_tail = get_tail_messages(page, TAIL_K)
        for m in startup_tail:
            key = get_message_key(m)
            try:
                txt = clean_text(m.inner_text())
            except Exception:
                txt = ""
            remember(key, txt)

        print("\nРежим моста включён:")
        print("- в консоль выводятся только новые сообщения после запуска")
        print("- то, что ты вводишь в консоль, отправляется в чат")
        print("Для выхода: Ctrl+C\n")

        while True:
            try:
                # 1) отправка из консоли в чат
                while not send_queue.empty():
                    text = send_queue.get().strip()
                    if not text:
                        continue
                    if text == "/exit":
                        raise KeyboardInterrupt

                    input_box.click()
                    input_box.fill(text)
                    input_box.press("Enter")

                # 2) читаем только хвост (последние TAIL_K сообщений)
                tail = get_tail_messages(page, TAIL_K)

                for m in tail:
                    key = get_message_key(m)

                    try:
                        txt = clean_text(m.inner_text())
                    except Exception:
                        txt = ""

                    if not txt:
                        continue

                    prefix = detect_direction_prefix(m)

                    if key not in seen_text:
                        remember(key, txt)
                        print(f"{prefix}{txt}")
                        continue
                    
                    if txt != seen_text.get(key, ""):
                        remember(key, txt)
                        print(f"{prefix}[edit] {txt}")

                # докрутить вниз
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
