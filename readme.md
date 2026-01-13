# Telegram Web (k) -> Bot MVP (Python + Playwright)

MVP: пишу текст в терминале -> скрипт отправляет его в чат в Telegram Web -> ждёт ответ -> печатает ответ в терминал.

## Требования
- Python 3.10+
- Аккаунт Telegram (логин в web.telegram.org)

## Установка
```bash
pip install playwright
playwright install chromium
````

## Файлы

* `tg_web_k_mvp.py` — основной скрипт
* `tg_profile/` — папка с сохранённой сессией Telegram Web (создастся сама)

## Запуск

```bash
python tg_web_k_mvp.py
```

## Первый запуск

1. Откроется окно браузера.
2. Если нужно — залогинься в Telegram Web (QR/код).
3. Должен открыться чат по ссылке на бота:
   [https://web.telegram.org/k/#@EvgeniiRa](https://web.telegram.org/k/#@EvgeniiRa)
4. Вернись в терминал и нажми Enter.
5. Пиши сообщения в терминале, ответы будут выводиться строкой ниже.

Выход: `Ctrl+C`.

## Частые проблемы

### 1) Не нашёл поле ввода / сообщения

Telegram Web меняет верстку, иногда надо обновить селекторы.

Самый быстрый способ снять правильные локаторы:

```bash
python -m playwright codegen "https://web.telegram.org/k/#@EvgeniiRa"
```

Кликни по полю ввода — справа появится locator. Его можно вставить в список `INPUT_SELECTORS` в скрипте.

### 2) Каждый раз просит логин

Проверь, что запускаешь скрипт из той же папки и не удаляешь `tg_profile/`.

## Примечания

* Это UI-автоматизация (MVP). Она более хрупкая, чем работа через MTProto (Telethon/Pyrogram).
* Не делай спам/частые запросы — Telegram может ограничить.

