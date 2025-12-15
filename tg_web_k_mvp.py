import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

BOT_URL = "https://web.telegram.org/k/#@Neyroosint_test_bot"
PROFILE_DIR = Path("./tg_profile")  # сохранит сессию (логин останется)

INPUT_SELECTORS = [
    "footer div[contenteditable='true']",
    "div[contenteditable='true'][data-placeholder]",
    "div[contenteditable='true']",
]

MESSAGE_SELECTORS = [
    "div.message",                  # часто встречается
    "div[class*='message']",         # fallback
]

def find_first(page, selectors):
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() > 0 and loc.first.is_visible():
                return loc.first
        except Exception:
            pass
    return None

def get_last_message_text(page) -> str:
    for sel in MESSAGE_SELECTORS:
        loc = page.locator(sel)
        try:
            if loc.count() > 0:
                return loc.last.inner_text().strip()
        except Exception:
            pass
    return ""

def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
        )  # persistent context = хранит логин/куки/сторедж :contentReference[oaicite:2]{index=2}
        page = context.new_page()
        page.goto(BOT_URL, wait_until="domcontentloaded")

        print("\nОткрыл Telegram Web.")
        print("Если ты не залогинен — залогинься (QR/код).")
        print("Если чат с ботом не открылся сам — открой его вручную.")
        input("\nКогда чат с ботом открыт — нажми Enter... ")

        input_box = find_first(page, INPUT_SELECTORS)
        if not input_box:
            raise RuntimeError(
                "Не нашёл поле ввода. Быстрый фикс: сними селектор через playwright codegen (ниже)."
            )

        print("\nГотово. Пиши текст. Выход: Ctrl+C\n")

        while True:
            text = input("> ").strip()
            if not text:
                continue

            before = get_last_message_text(page)

            input_box.click()
            input_box.fill(text)
            input_box.press("Enter")

            # ждём, пока последний message изменится
            deadline = time.time() + 30
            answer = ""
            while time.time() < deadline:
                time.sleep(0.6)
                now = get_last_message_text(page)
                if now and now != before:
                    answer = now
                    break

            print(f"< {answer if answer else '[нет нового ответа за 30 сек]'}")

if __name__ == "__main__":
    main()
