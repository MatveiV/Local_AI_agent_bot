"""
agent.py — логика AI-агента с поддержкой инструментов (tool calling).
Использует OpenAI-совместимый API через выбранного провайдера.
"""
import json
import logging
import os
from datetime import datetime
from openai import OpenAI
from dotenv import load_dotenv
from tools import TOOLS_REGISTRY

load_dotenv()

logger = logging.getLogger(__name__)

MEMORY_FILE = os.path.join(os.path.dirname(__file__), "memory.json")

# ─── Провайдеры (из ai_direct.py / openai_client.py) ─────────────────────────

PROVIDERS = {
    "1": {
        "name": "Z.AI",
        "api_key_env": "ZAI_API_KEY",
        "base_url": "https://api.z.ai/api/paas/v4/",
        "models": {
            "1": {"id": "glm-4.7-flash", "label": "GLM-4.7-Flash", "free": True,  "temp_range": (0.0, 1.0), "max_tokens": 4096},
            "2": {"id": "glm-4.5-flash", "label": "GLM-4.5-Flash", "free": True,  "temp_range": (0.0, 1.0), "max_tokens": 4096},
            "3": {"id": "glm-4.7",       "label": "GLM-4.7",       "free": False, "temp_range": (0.0, 1.0), "max_tokens": 8192},
            "4": {"id": "glm-4.5",       "label": "GLM-4.5",       "free": False, "temp_range": (0.0, 1.0), "max_tokens": 8192},
        },
    },
    "2": {
        "name": "ProxyAPI (OpenAI)",
        "api_key_env": "PROXY_API_KEY",
        "base_url": "https://api.proxyapi.ru/openai/v1",
        "models": {
            "1": {"id": "gpt-4.1-nano",  "label": "GPT-4.1 Nano",  "free": False, "temp_range": (0.0, 2.0), "max_tokens": 32768},
            "2": {"id": "gpt-4.1-mini",  "label": "GPT-4.1 Mini",  "free": False, "temp_range": (0.0, 2.0), "max_tokens": 32768},
            "3": {"id": "gpt-4o-mini",   "label": "GPT-4o Mini",   "free": False, "temp_range": (0.0, 2.0), "max_tokens": 16384},
            "4": {"id": "gpt-4o",        "label": "GPT-4o",        "free": False, "temp_range": (0.0, 2.0), "max_tokens": 16384},
        },
    },
    "3": {
        "name": "GenAPI",
        "api_key_env": "GEN_API_KEY",
        "base_url": "https://proxy.gen-api.ru/v1",
        "models": {
            "1": {"id": "gpt-4-1-mini",      "label": "GPT-4.1 Mini",      "free": False, "temp_range": (0.0, 2.0), "max_tokens": 32768},
            "2": {"id": "gpt-4o",            "label": "GPT-4o",            "free": False, "temp_range": (0.0, 2.0), "max_tokens": 16384},
            "3": {"id": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5", "free": False, "temp_range": (0.0, 1.0), "max_tokens": 8192},
            "4": {"id": "gemini-2-5-flash",  "label": "Gemini 2.5 Flash",  "free": False, "temp_range": (0.0, 2.0), "max_tokens": 8192},
            "5": {"id": "deepseek-chat",     "label": "DeepSeek Chat",     "free": False, "temp_range": (0.0, 2.0), "max_tokens": 8192},
        },
    },
}

# ─── Описание инструментов для OpenAI function calling ───────────────────────

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Поиск информации в интернете через DuckDuckGo. Используй для актуальных новостей, фактов, информации.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Поисковый запрос"},
                    "max_results": {"type": "integer", "description": "Количество результатов (по умолчанию 5)", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Получить текущую погоду для города. Используй когда пользователь спрашивает о погоде.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "Название города (например: Москва, London, Токио)"},
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_crypto_price",
            "description": "Получить текущий курс криптовалюты. Используй когда спрашивают о цене Bitcoin, Ethereum и т.д.",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin": {"type": "string", "description": "ID монеты: bitcoin, ethereum, solana, dogecoin и т.д."},
                    "currency": {"type": "string", "description": "Валюта: usd, eur, rub (по умолчанию usd)", "default": "usd"},
                },
                "required": ["coin"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_currency_rate",
            "description": "Получить курс обычной валюты (USD, EUR, RUB, GBP, JPY, CNY и др.). Используй когда спрашивают о курсе доллара, евро, рубля и т.д.",
            "parameters": {
                "type": "object",
                "properties": {
                    "base": {"type": "string", "description": "Исходная валюта, например USD, EUR, RUB"},
                    "target": {"type": "string", "description": "Целевая валюта, например RUB, USD, EUR"},
                },
                "required": ["base", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_qr",
            "description": "Сгенерировать QR-код из текста или URL и сохранить в PNG файл.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Текст, URL или данные для кодирования в QR"},
                    "output_path": {"type": "string", "description": "Путь для сохранения PNG файла (по умолчанию qrcode.png)"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_reminder",
            "description": "Добавить напоминание или задачу в расписание с указанием даты и времени.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Текст напоминания"},
                    "remind_at": {"type": "string", "description": "Дата и время в формате 'YYYY-MM-DD HH:MM' или 'YYYY-MM-DD'"},
                },
                "required": ["text", "remind_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "Показать список напоминаний и задач из расписания.",
            "parameters": {
                "type": "object",
                "properties": {
                    "show_done": {"type": "boolean", "description": "Показывать выполненные напоминания (по умолчанию false)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Отметить напоминание выполненным или удалить его по id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "ID напоминания (число из list_reminders)"},
                },
                "required": ["reminder_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Вычислить математическое выражение. Поддерживает: +,-,*,/,**, %, sqrt, sin, cos, tan, log, log2, log10, exp, ceil, floor, factorial, pi, e. Используй для любых вычислений.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Математическое выражение, например: '2**10', 'sqrt(144)', 'sin(pi/2)', 'log(1000, 10)', '(15 * 8) / 3'"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "Прочитать документ (pdf/docx/txt) и загрузить его текст в контекст. Используй когда пользователь загрузил файл и хочет задавать по нему вопросы.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Путь к файлу документа"},
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_document",
            "description": "Задать вопрос по загруженному документу. Возвращает релевантные фрагменты для ответа.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_name": {"type": "string", "description": "Имя файла документа"},
                    "question": {"type": "string", "description": "Вопрос по содержимому документа"},
                },
                "required": ["document_name", "question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": "Показать список загруженных документов.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Прочитать содержимое файла по указанному пути.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Записать текст в файл по указанному пути.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"},
                    "content": {"type": "string", "description": "Содержимое для записи"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Выполнить терминальную команду. Разрешены только безопасные команды: ls, dir, echo, python, pip, whoami, date, time, cat, type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Команда для выполнения"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "http_request",
            "description": "Выполнить HTTP запрос к внешнему API.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL запроса"},
                    "method": {"type": "string", "description": "HTTP метод: GET или POST", "default": "GET"},
                    "params": {"type": "object", "description": "Query параметры (для GET)"},
                    "body": {"type": "object", "description": "Тело запроса (для POST)"},
                },
                "required": ["url"],
            },
        },
    },
]

SYSTEM_PROMPT = """Ты — умный AI-агент, работающий в терминале. Ты помогаешь пользователю выполнять задачи.

У тебя есть следующие инструменты:
- web_search: поиск в интернете
- get_weather: погода по городу
- get_crypto_price: курс криптовалюты (bitcoin, ethereum и др.)
- get_currency_rate: курс обычных валют (USD, EUR, RUB, GBP и др.)
- generate_qr: генерация QR-кода в PNG файл
- add_reminder / list_reminders / delete_reminder: управление расписанием и напоминаниями
- calculate: вычисление математических выражений (sqrt, sin, log, factorial и др.)
- read_document / query_document / list_documents: работа с документами (pdf/docx/txt)
- read_file / write_file: работа с текстовыми файлами
- run_command: выполнение терминальных команд
- http_request: HTTP запросы к API

Правила:
1. Всегда используй инструменты для получения актуальной информации.
2. Если нужна погода — используй get_weather.
3. Если нужен курс крипты — используй get_crypto_price.
4. Если нужен курс валюты (доллар, евро, рубль) — используй get_currency_rate.
5. Если нужно создать QR-код — используй generate_qr.
6. Если нужно добавить/посмотреть напоминание — используй add_reminder / list_reminders.
7. Если нужно что-то посчитать — используй calculate.
8. Если нужна информация из интернета — используй web_search.
9. Если пользователь загрузил документ — используй read_document для загрузки, затем query_document для ответов на вопросы.
10. Отвечай на русском языке, структурированно и понятно.
11. Если задача неясна — уточни у пользователя.
"""

# ─── Память ───────────────────────────────────────────────────────────────────

def load_memory() -> list[dict]:
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_memory(entry: dict) -> None:
    memory = load_memory()
    memory.append(entry)
    # Храним последние 100 записей
    if len(memory) > 100:
        memory = memory[-100:]
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)
    logger.info("[memory] saved entry, total=%d", len(memory))

# ─── Выполнение инструмента ───────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_args: dict) -> str:
    logger.info("[agent] executing tool: %s args=%s", tool_name, tool_args)
    tool = TOOLS_REGISTRY.get(tool_name)
    if not tool:
        return f"Инструмент '{tool_name}' не найден."
    try:
        result = tool["fn"](**tool_args)
        logger.info("[agent] tool result length: %d", len(str(result)))
        return str(result)
    except TypeError as e:
        logger.error("[agent] tool call error: %s", e)
        return f"Ошибка вызова инструмента {tool_name}: {e}"

# ─── Основной класс агента ────────────────────────────────────────────────────

class Agent:
    def __init__(self, provider: dict, model: dict, temperature: float,
                 on_tool_call=None):
        """
        on_tool_call(tool_name, tool_args, tool_result) — опциональный callback
        для отображения хода выполнения инструментов (терминал, Telegram и т.д.)
        """
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.on_tool_call = on_tool_call
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.client = OpenAI(
            api_key=os.environ.get(provider["api_key_env"]),
            base_url=provider["base_url"],
        )
        logger.info("[agent] initialized: provider=%s model=%s temp=%.2f",
                    provider["name"], model["id"], temperature)

    def chat(self, user_message: str) -> str:
        self.history.append({"role": "user", "content": user_message})
        logger.info("[agent] user message: %r", user_message[:100])

        for iteration in range(5):
            logger.info("[agent] LLM call iteration=%d", iteration)
            try:
                response = self.client.chat.completions.create(
                    model=self.model["id"],
                    messages=self.history,
                    temperature=self.temperature,
                    max_tokens=self.model["max_tokens"],
                    tools=OPENAI_TOOLS,
                    tool_choice="auto",
                )
            except Exception as e:
                logger.error("[agent] LLM error: %s", e)
                return f"Ошибка LLM: {e}"

            msg = response.choices[0].message
            finish_reason = response.choices[0].finish_reason
            logger.info("[agent] finish_reason=%s tool_calls=%s",
                        finish_reason, bool(msg.tool_calls))

            if not msg.tool_calls:
                reply = msg.content or ""
                self.history.append({"role": "assistant", "content": reply})
                save_memory({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "user": user_message,
                    "assistant": reply[:500],
                    "model": self.model["id"],
                    "provider": self.provider["name"],
                })
                return reply

            self.history.append(msg)

            for tc in msg.tool_calls:
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                logger.info("[agent] tool_call: %s(%s)", tool_name, tool_args)
                tool_result = execute_tool(tool_name, tool_args)

                # Уведомляем через callback (терминал / Telegram / другое)
                if self.on_tool_call:
                    self.on_tool_call(tool_name, tool_args, tool_result)

                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })

        logger.warning("[agent] max iterations reached")
        return "Агент достиг максимального числа итераций. Попробуйте переформулировать запрос."

    def clear_history(self) -> None:
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        logger.info("[agent] history cleared")
