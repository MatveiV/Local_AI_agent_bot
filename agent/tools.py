"""
tools.py — инструменты агента:
  - web_search        : поиск через DuckDuckGo
  - get_weather       : погода через open-meteo (геокодинг → координаты)
  - get_crypto_price  : курс криптовалюты (CoinGecko + Binance fallback)
  - get_currency_rate : курс обычных валют через open.er-api.com (без ключей)
  - generate_qr       : генерация QR-кода в PNG файл
  - add_reminder      : добавить напоминание в расписание
  - list_reminders    : показать все напоминания
  - delete_reminder   : удалить напоминание по id
  - calculate         : вычислить математическое выражение (безопасно)
  - read_document     : чтение документа pdf/docx/txt и сохранение в контекст
  - query_document    : задать вопрос по загруженному документу
  - read_file         : чтение текстового файла
  - write_file        : запись файла
  - run_command       : выполнение терминальной команды (ограниченно)
  - http_request      : произвольный HTTP GET/POST запрос
"""
import json
import logging
import math
import os
import subprocess
import time
from datetime import datetime

import requests
from ddgs import DDGS

logger = logging.getLogger(__name__)

# ─── Web Search ───────────────────────────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> str:
    """Поиск в интернете через DuckDuckGo."""
    logger.info("[tool] web_search: query=%r max_results=%d", query, max_results)
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"- {r['title']}\n  {r['href']}\n  {r['body']}")
        if not results:
            return "Поиск не дал результатов."
        output = "\n\n".join(results)
        logger.info("[tool] web_search: got %d results", len(results))
        return output
    except Exception as e:
        logger.error("[tool] web_search error: %s", e)
        return f"Ошибка поиска: {e}"

# ─── Weather ──────────────────────────────────────────────────────────────────

def _geocode(city: str) -> tuple[float, float]:
    """Получить координаты города через Open-Meteo geocoding API."""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    resp = requests.get(url, params={"name": city, "count": 1, "language": "ru"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results")
    if not results:
        raise ValueError(f"Город не найден: {city}")
    r = results[0]
    return r["latitude"], r["longitude"]

def get_weather(city: str) -> str:
    """Получить текущую погоду для города."""
    logger.info("[tool] get_weather: city=%r", city)
    try:
        lat, lon = _geocode(city)
        url = "https://api.open-meteo.com/v1/forecast"
        resp = requests.get(url, params={
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
        }, timeout=10)
        resp.raise_for_status()
        cw = resp.json().get("current_weather", {})
        temp = cw.get("temperature", "?")
        wind = cw.get("windspeed", "?")
        code = cw.get("weathercode", "?")
        result = (
            f"Погода в {city} (lat={lat:.2f}, lon={lon:.2f}):\n"
            f"  Температура : {temp} °C\n"
            f"  Ветер       : {wind} км/ч\n"
            f"  Код погоды  : {code}"
        )
        logger.info("[tool] get_weather: %s", result)
        return result
    except Exception as e:
        logger.error("[tool] get_weather error: %s", e)
        return f"Ошибка получения погоды: {e}"

# ─── Crypto Price ─────────────────────────────────────────────────────────────

def get_crypto_price(coin: str, currency: str = "usd") -> str:
    """Получить курс криптовалюты.
    Основной источник: CoinGecko. При 429 — fallback на Binance (только USD пары).
    """
    logger.info("[tool] get_crypto_price: coin=%r currency=%r", coin, currency)
    coin = coin.lower().strip()
    currency = currency.lower().strip()

    # ── Попытка 1: CoinGecko с retry ─────────────────────────────────────────
    for attempt in range(3):
        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": coin, "vs_currencies": currency},
                timeout=10,
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning("[tool] get_crypto_price: CoinGecko 429, retry in %ds", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            if coin in data:
                price = data[coin].get(currency, "?")
                result = f"Курс {coin.upper()}: {price} {currency.upper()} (CoinGecko)"
                logger.info("[tool] get_crypto_price: %s", result)
                return result
            break  # ответ получен, но монета не найдена — не ретраим
        except requests.exceptions.HTTPError:
            if attempt == 2:
                break
        except Exception as e:
            logger.warning("[tool] get_crypto_price CoinGecko error: %s", e)
            break

    # ── Fallback: Binance (только USD) ────────────────────────────────────────
    # Маппинг CoinGecko id → Binance symbol
    BINANCE_MAP = {
        "bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "solana": "SOLUSDT",
        "ripple": "XRPUSDT", "dogecoin": "DOGEUSDT", "litecoin": "LTCUSDT",
        "cardano": "ADAUSDT", "polkadot": "DOTUSDT", "chainlink": "LINKUSDT",
        "avalanche-2": "AVAXUSDT", "matic-network": "MATICUSDT",
        "tron": "TRXUSDT", "stellar": "XLMUSDT", "uniswap": "UNIUSDT",
    }
    symbol = BINANCE_MAP.get(coin)
    if symbol:
        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": symbol},
                timeout=10,
            )
            resp.raise_for_status()
            price = float(resp.json().get("price", 0))
            # Конвертируем если нужна не USD
            if currency == "usd":
                result = f"Курс {coin.upper()}: {price:.4f} USD (Binance)"
            else:
                result = f"Курс {coin.upper()}: {price:.4f} USD (Binance, конвертация в {currency.upper()} недоступна)"
            logger.info("[tool] get_crypto_price fallback: %s", result)
            return result
        except Exception as e:
            logger.error("[tool] get_crypto_price Binance error: %s", e)

    return (f"Не удалось получить курс '{coin}'. "
            f"Попробуйте позже или уточните название (bitcoin, ethereum, solana, ripple...)")

# ─── Document Reader ──────────────────────────────────────────────────────────

# Хранилище загруженных документов: имя → текст
_document_store: dict[str, str] = {}
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def _extract_text(file_path: str) -> str:
    """Извлечь текст из pdf / docx / txt файла."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".txt":
        with open(file_path, encoding="utf-8", errors="replace") as f:
            return f.read()

    if ext == ".pdf":
        try:
            import pdfplumber  # type: ignore
            text_parts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return "\n\n".join(text_parts)
        except ImportError:
            return "Ошибка: установите pdfplumber: pip install pdfplumber"

    if ext in (".docx", ".doc"):
        try:
            import docx  # type: ignore
            doc = docx.Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            return "Ошибка: установите python-docx: pip install python-docx"

    return f"Неподдерживаемый формат файла: {ext}. Поддерживаются: pdf, docx, txt"


def read_document(file_path: str) -> str:
    """Прочитать документ (pdf/docx/txt), сохранить текст в контекст агента.
    После загрузки можно задавать вопросы по документу через query_document.
    """
    logger.info("[tool] read_document: path=%r", file_path)
    try:
        if not os.path.exists(file_path):
            return f"Файл не найден: {file_path}"

        text = _extract_text(file_path)
        if text.startswith("Ошибка") or text.startswith("Неподдерживаемый"):
            return text

        name = os.path.basename(file_path)
        _document_store[name] = text
        chars = len(text)
        words = len(text.split())
        result = (f"Документ '{name}' загружен: {chars} символов, ~{words} слов.\n"
                  f"Теперь вы можете задавать вопросы по его содержимому.")
        logger.info("[tool] read_document: loaded %r chars=%d", name, chars)
        return result
    except Exception as e:
        logger.error("[tool] read_document error: %s", e)
        return f"Ошибка чтения документа: {e}"


def query_document(document_name: str, question: str) -> str:
    """Получить фрагмент документа, релевантный вопросу.
    Возвращает до 3000 символов контекста для ответа агента.
    """
    logger.info("[tool] query_document: doc=%r question=%r", document_name, question[:60])

    # Ищем документ по точному имени или частичному совпадению
    text = _document_store.get(document_name)
    if text is None:
        # Попробуем найти по частичному имени
        for name, content in _document_store.items():
            if document_name.lower() in name.lower():
                text = content
                document_name = name
                break

    if text is None:
        available = list(_document_store.keys())
        if not available:
            return "Нет загруженных документов. Сначала загрузите файл."
        return f"Документ '{document_name}' не найден. Загруженные: {', '.join(available)}"

    # Простой поиск релевантных абзацев по ключевым словам вопроса
    keywords = [w.lower() for w in question.split() if len(w) > 3]
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    scored = []
    for para in paragraphs:
        para_lower = para.lower()
        score = sum(1 for kw in keywords if kw in para_lower)
        scored.append((score, para))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Берём топ абзацы до 3000 символов
    selected = []
    total = 0
    for score, para in scored:
        if total + len(para) > 3000:
            break
        selected.append(para)
        total += len(para)

    if not selected:
        # Если ничего не нашли — возвращаем начало документа
        selected = [text[:3000]]

    context = "\n\n".join(selected)
    result = f"[Документ: {document_name}]\n\n{context}"
    logger.info("[tool] query_document: returned %d chars", len(result))
    return result


def list_documents() -> str:
    """Показать список загруженных документов."""
    if not _document_store:
        return "Нет загруженных документов."
    lines = ["Загруженные документы:"]
    for name, text in _document_store.items():
        lines.append(f"  - {name} ({len(text)} символов)")
    return "\n".join(lines)


# ─── File I/O ─────────────────────────────────────────────────────────────────

def read_file(path: str) -> str:
    """Прочитать содержимое файла."""
    logger.info("[tool] read_file: path=%r", path)
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        logger.info("[tool] read_file: read %d chars", len(content))
        return content
    except Exception as e:
        logger.error("[tool] read_file error: %s", e)
        return f"Ошибка чтения файла: {e}"

def write_file(path: str, content: str) -> str:
    """Записать содержимое в файл."""
    logger.info("[tool] write_file: path=%r len=%d", path, len(content))
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Файл '{path}' успешно записан ({len(content)} символов)."
    except Exception as e:
        logger.error("[tool] write_file error: %s", e)
        return f"Ошибка записи файла: {e}"

# ─── Terminal Command ─────────────────────────────────────────────────────────

# Белый список разрешённых команд (безопасность)
ALLOWED_COMMANDS = {"dir", "ls", "pwd", "echo", "python", "pip", "whoami", "date", "time", "cat", "type"}

def run_command(command: str) -> str:
    """Выполнить терминальную команду (только из белого списка)."""
    logger.info("[tool] run_command: command=%r", command)
    base_cmd = command.strip().split()[0].lower()
    if base_cmd not in ALLOWED_COMMANDS:
        msg = f"Команда '{base_cmd}' не разрешена. Разрешены: {', '.join(sorted(ALLOWED_COMMANDS))}"
        logger.warning("[tool] run_command blocked: %s", msg)
        return msg
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=15
        )
        output = result.stdout or result.stderr or "(нет вывода)"
        logger.info("[tool] run_command: returncode=%d output_len=%d", result.returncode, len(output))
        return output.strip()
    except subprocess.TimeoutExpired:
        return "Ошибка: команда превысила таймаут (15 сек)."
    except Exception as e:
        logger.error("[tool] run_command error: %s", e)
        return f"Ошибка выполнения команды: {e}"

# ─── Currency Rate ────────────────────────────────────────────────────────────

def get_currency_rate(base: str, target: str) -> str:
    """Получить курс обычной валюты через exchangerate-api (без ключей).
    Использует open.er-api.com — поддерживает RUB и большинство мировых валют.
    Примеры: base='USD', target='RUB' | base='EUR', target='USD'
    """
    logger.info("[tool] get_currency_rate: %s → %s", base, target)
    try:
        base = base.upper().strip()
        target = target.upper().strip()
        # open.er-api.com — бесплатный, поддерживает RUB
        url = f"https://open.er-api.com/v6/latest/{base}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") == "error":
            return f"Ошибка API: {data.get('error-type', 'unknown')}. Проверьте код валюты."
        rates = data.get("rates", {})
        rate = rates.get(target)
        if rate is None:
            available = ", ".join(sorted(rates.keys())[:20])
            return f"Валюта '{target}' не найдена. Примеры доступных: {available}..."
        date = data.get("time_last_update_utc", "?")[:16]
        result = f"Курс {base} → {target}: {rate} (обновлено: {date})"
        logger.info("[tool] get_currency_rate: %s", result)
        return result
    except Exception as e:
        logger.error("[tool] get_currency_rate error: %s", e)
        return f"Ошибка получения курса валюты: {e}"

# ─── QR Code ──────────────────────────────────────────────────────────────────

def generate_qr(text: str, output_path: str = "qrcode.png") -> str:
    """Сгенерировать QR-код и сохранить в PNG файл."""
    logger.info("[tool] generate_qr: text=%r output=%r", text[:50], output_path)
    try:
        import qrcode  # type: ignore
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(output_path)
        abs_path = os.path.abspath(output_path)
        result = f"QR-код сохранён: {abs_path}\nСодержимое: {text[:80]}{'...' if len(text) > 80 else ''}"
        logger.info("[tool] generate_qr: saved to %s", abs_path)
        return result
    except ImportError:
        return "Ошибка: установите библиотеку qrcode: pip install qrcode[pil]"
    except Exception as e:
        logger.error("[tool] generate_qr error: %s", e)
        return f"Ошибка генерации QR-кода: {e}"

# ─── Reminders / Schedule ─────────────────────────────────────────────────────

REMINDERS_FILE = os.path.join(os.path.dirname(__file__), "reminders.json")

def _load_reminders() -> list[dict]:
    if not os.path.exists(REMINDERS_FILE):
        return []
    try:
        with open(REMINDERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_reminders(reminders: list[dict]) -> None:
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(reminders, f, ensure_ascii=False, indent=2)

def add_reminder(text: str, remind_at: str) -> str:
    """Добавить напоминание.
    remind_at — дата/время в формате 'YYYY-MM-DD HH:MM' или 'YYYY-MM-DD'.
    """
    logger.info("[tool] add_reminder: text=%r remind_at=%r", text, remind_at)
    try:
        # Валидация формата
        fmt = "%Y-%m-%d %H:%M" if " " in remind_at else "%Y-%m-%d"
        dt = datetime.strptime(remind_at, fmt)
        reminders = _load_reminders()
        new_id = max((r["id"] for r in reminders), default=0) + 1
        entry = {
            "id": new_id,
            "text": text,
            "remind_at": remind_at,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "done": False,
        }
        reminders.append(entry)
        _save_reminders(reminders)
        result = f"Напоминание #{new_id} добавлено: '{text}' на {remind_at}"
        logger.info("[tool] add_reminder: %s", result)
        return result
    except ValueError as e:
        return f"Ошибка формата даты: {e}. Используйте 'YYYY-MM-DD HH:MM' или 'YYYY-MM-DD'."
    except Exception as e:
        logger.error("[tool] add_reminder error: %s", e)
        return f"Ошибка добавления напоминания: {e}"

def list_reminders(show_done: bool = False) -> str:
    """Показать список напоминаний."""
    logger.info("[tool] list_reminders: show_done=%s", show_done)
    reminders = _load_reminders()
    if not reminders:
        return "Напоминаний нет."
    filtered = reminders if show_done else [r for r in reminders if not r["done"]]
    if not filtered:
        return "Активных напоминаний нет."
    now = datetime.now()
    lines = []
    for r in sorted(filtered, key=lambda x: x["remind_at"]):
        status = "✓" if r["done"] else "○"
        try:
            fmt = "%Y-%m-%d %H:%M" if " " in r["remind_at"] else "%Y-%m-%d"
            dt = datetime.strptime(r["remind_at"], fmt)
            overdue = " [ПРОСРОЧЕНО]" if dt < now and not r["done"] else ""
        except Exception:
            overdue = ""
        lines.append(f"  [{status}] #{r['id']} {r['remind_at']}{overdue} — {r['text']}")
    return "Напоминания:\n" + "\n".join(lines)

def delete_reminder(reminder_id: int) -> str:
    """Удалить или отметить напоминание выполненным по id."""
    logger.info("[tool] delete_reminder: id=%d", reminder_id)
    reminders = _load_reminders()
    for r in reminders:
        if r["id"] == reminder_id:
            r["done"] = True
            _save_reminders(reminders)
            result = f"Напоминание #{reminder_id} отмечено выполненным: '{r['text']}'"
            logger.info("[tool] delete_reminder: %s", result)
            return result
    return f"Напоминание #{reminder_id} не найдено."

# ─── Calculator ───────────────────────────────────────────────────────────────

# Безопасное пространство имён для eval
_SAFE_MATH_NS = {
    "__builtins__": {},
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "pow": pow, "divmod": divmod,
    # math functions
    "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp, "ceil": math.ceil, "floor": math.floor,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "degrees": math.degrees, "radians": math.radians,
    "factorial": math.factorial, "gcd": math.gcd,
    "pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf,
}

def calculate(expression: str) -> str:
    """Вычислить математическое выражение безопасно.
    Поддерживает: +, -, *, /, **, %, sqrt, sin, cos, log, pi, e и др.
    Примеры: '2**10', 'sqrt(144)', 'sin(pi/2)', 'log(1000, 10)'
    """
    logger.info("[tool] calculate: expression=%r", expression)
    # Базовая санитизация — запрещаем опасные конструкции
    forbidden = ["import", "exec", "eval", "open", "os", "sys", "__", "getattr", "setattr"]
    expr_lower = expression.lower()
    for token in forbidden:
        if token in expr_lower:
            return f"Ошибка: выражение содержит запрещённый токен '{token}'."
    try:
        result = eval(expression, _SAFE_MATH_NS)  # noqa: S307
        # Форматируем: целые числа без .0
        if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
            result = int(result)
        output = f"{expression} = {result}"
        logger.info("[tool] calculate: %s", output)
        return output
    except ZeroDivisionError:
        return "Ошибка: деление на ноль."
    except Exception as e:
        logger.error("[tool] calculate error: %s", e)
        return f"Ошибка вычисления: {e}"

# ─── HTTP Request ─────────────────────────────────────────────────────────────

def http_request(url: str, method: str = "GET", params: dict = None, body: dict = None) -> str:
    """Выполнить HTTP запрос и вернуть ответ."""
    logger.info("[tool] http_request: method=%s url=%r", method, url)
    try:
        resp = requests.request(method.upper(), url, params=params, json=body, timeout=15)
        resp.raise_for_status()
        try:
            data = resp.json()
            import json
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            return resp.text[:2000]
    except Exception as e:
        logger.error("[tool] http_request error: %s", e)
        return f"Ошибка HTTP запроса: {e}"

# ─── Реестр инструментов для агента ──────────────────────────────────────────

TOOLS_REGISTRY = {
    "web_search": {
        "fn": web_search,
        "description": "Поиск информации в интернете через DuckDuckGo",
        "params": {"query": "str", "max_results": "int (optional, default 5)"},
    },
    "get_weather": {
        "fn": get_weather,
        "description": "Получить текущую погоду для города",
        "params": {"city": "str — название города на русском или английском"},
    },
    "get_crypto_price": {
        "fn": get_crypto_price,
        "description": "Получить курс криптовалюты (bitcoin, ethereum, solana и т.д.)",
        "params": {"coin": "str — id монеты (bitcoin, ethereum...)", "currency": "str — валюта (usd, eur, rub)"},
    },
    "get_currency_rate": {
        "fn": get_currency_rate,
        "description": "Получить курс обычной валюты (USD, EUR, RUB, GBP, JPY и др.)",
        "params": {"base": "str — исходная валюта (USD)", "target": "str — целевая валюта (RUB)"},
    },
    "generate_qr": {
        "fn": generate_qr,
        "description": "Сгенерировать QR-код и сохранить в PNG файл",
        "params": {"text": "str — текст или URL для QR", "output_path": "str — путь к файлу (default: qrcode.png)"},
    },
    "add_reminder": {
        "fn": add_reminder,
        "description": "Добавить напоминание в расписание",
        "params": {"text": "str — текст напоминания", "remind_at": "str — дата/время 'YYYY-MM-DD HH:MM'"},
    },
    "list_reminders": {
        "fn": list_reminders,
        "description": "Показать список напоминаний",
        "params": {"show_done": "bool — показывать выполненные (default: False)"},
    },
    "delete_reminder": {
        "fn": delete_reminder,
        "description": "Отметить напоминание выполненным по id",
        "params": {"reminder_id": "int — id напоминания"},
    },
    "calculate": {
        "fn": calculate,
        "description": "Вычислить математическое выражение. Поддерживает sqrt, sin, cos, log, pi, e, **, % и др.",
        "params": {"expression": "str — математическое выражение, например '2**10' или 'sqrt(144)'"},
    },
    "read_document": {
        "fn": read_document,
        "description": "Прочитать документ (pdf/docx/txt) и загрузить его текст в контекст. После загрузки можно задавать вопросы по документу.",
        "params": {"file_path": "str — путь к файлу"},
    },
    "query_document": {
        "fn": query_document,
        "description": "Задать вопрос по загруженному документу. Возвращает релевантные фрагменты текста.",
        "params": {"document_name": "str — имя файла", "question": "str — вопрос по документу"},
    },
    "list_documents": {
        "fn": list_documents,
        "description": "Показать список загруженных документов.",
        "params": {},
    },
    "read_file": {
        "fn": read_file,
        "description": "Прочитать содержимое файла по пути",
        "params": {"path": "str — путь к файлу"},
    },
    "write_file": {
        "fn": write_file,
        "description": "Записать текст в файл",
        "params": {"path": "str — путь к файлу", "content": "str — содержимое"},
    },
    "run_command": {
        "fn": run_command,
        "description": "Выполнить терминальную команду (ограниченный список: ls, dir, echo, python, pip, whoami, date, time, cat, type)",
        "params": {"command": "str — команда"},
    },
    "http_request": {
        "fn": http_request,
        "description": "Выполнить HTTP GET/POST запрос к API",
        "params": {"url": "str", "method": "str (GET/POST)", "params": "dict (optional)", "body": "dict (optional)"},
    },
}
