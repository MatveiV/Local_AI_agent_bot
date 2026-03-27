"""
telegram_bot.py — Telegram-интерфейс AI-агента.
Запуск: python run.py → выбрать режим 2

Команды бота:
  /start   — приветствие и выбор провайдера/модели
  /new     — очистить историю диалога
  /memory  — показать последние записи из памяти
  /model   — сменить провайдера/модель
  /help    — список команд
"""
import logging
import os
import sys
import threading

import telebot
from telebot import types
from dotenv import load_dotenv

from agent import Agent, PROVIDERS, load_memory

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger(__name__)


def setup_bot_logging(verbose: bool = False) -> None:
    """Настроить логирование для Telegram-бота в тот же agent.log."""
    # Если basicConfig уже вызван (запуск через run.py) — просто добавляем handler
    root = logging.getLogger()
    if root.handlers:
        return  # уже настроено из run.py

    level = logging.DEBUG if verbose else logging.INFO
    log_file = os.path.join(os.path.dirname(__file__), "agent.log")
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout) if verbose else logging.NullHandler(),
        ],
    )

# ─── Состояние пользователей ──────────────────────────────────────────────────
# user_id → {"agent": Agent, "step": str, "provider_key": str, "model_key": str}
_user_state: dict[int, dict] = {}

# ─── Инициализация бота ───────────────────────────────────────────────────────

def get_bot() -> telebot.TeleBot:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не найден в .env")
    return telebot.TeleBot(token, parse_mode=None)

bot = get_bot()

# ─── Вспомогательные функции ──────────────────────────────────────────────────

def send(chat_id: int, text: str) -> None:
    """Отправить сообщение, разбивая на части если > 4096 символов."""
    max_len = 4096
    for i in range(0, len(text), max_len):
        bot.send_message(chat_id, text[i:i + max_len])

def provider_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    for key, p in PROVIDERS.items():
        kb.add(types.InlineKeyboardButton(p["name"], callback_data=f"provider:{key}"))
    return kb

def model_keyboard(provider_key: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    models = PROVIDERS[provider_key]["models"]
    for key, m in models.items():
        free_tag = " (бесплатно)" if m.get("free") else ""
        label = f"{m['label']}{free_tag} | до {m['max_tokens']} токенов"
        kb.add(types.InlineKeyboardButton(label, callback_data=f"model:{provider_key}:{key}"))
    return kb

def temp_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=4)
    buttons = [
        types.InlineKeyboardButton("0.3", callback_data="temp:0.3"),
        types.InlineKeyboardButton("0.5", callback_data="temp:0.5"),
        types.InlineKeyboardButton("0.7", callback_data="temp:0.7"),
        types.InlineKeyboardButton("1.0", callback_data="temp:1.0"),
    ]
    kb.add(*buttons)
    return kb

def get_state(user_id: int) -> dict:
    if user_id not in _user_state:
        _user_state[user_id] = {"agent": None, "step": "idle"}
    return _user_state[user_id]

# ─── Handlers ─────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "model"])
def cmd_start(message: types.Message) -> None:
    state = get_state(message.from_user.id)
    state["step"] = "pick_provider"
    send(message.chat.id,
         "Выберите AI-провайдера:")
    bot.send_message(message.chat.id, "Провайдер:", reply_markup=provider_keyboard())

@bot.message_handler(commands=["new"])
def cmd_new(message: types.Message) -> None:
    state = get_state(message.from_user.id)
    if state.get("agent"):
        state["agent"].clear_history()
        send(message.chat.id, "Контекст диалога очищен.")
    else:
        send(message.chat.id, "Сначала выберите провайдера командой /start")

@bot.message_handler(commands=["memory"])
def cmd_memory(message: types.Message) -> None:
    memory = load_memory()
    if not memory:
        send(message.chat.id, "Память пуста.")
        return
    recent = memory[-5:]
    lines = [f"Последние {len(recent)} записей:\n"]
    for entry in recent:
        lines.append(
            f"[{entry.get('timestamp', '?')}] {entry.get('provider', '?')} / {entry.get('model', '?')}\n"
            f"Вы: {entry.get('user', '')[:80]}\n"
            f"ИИ: {entry.get('assistant', '')[:120]}\n"
            f"{'─' * 30}"
        )
    send(message.chat.id, "\n".join(lines))

@bot.message_handler(commands=["help"])
def cmd_help(message: types.Message) -> None:
    text = (
        "Команды:\n"
        "/start  — выбрать провайдера и модель\n"
        "/model  — сменить провайдера/модель\n"
        "/new    — очистить историю диалога\n"
        "/memory — последние записи из памяти\n"
        "/help   — эта справка\n\n"
        "Просто напишите любой вопрос или задачу — агент ответит."
    )
    send(message.chat.id, text)

# ─── Inline callbacks (выбор провайдера / модели / температуры) ───────────────

@bot.callback_query_handler(func=lambda c: c.data.startswith("provider:"))
def cb_provider(call: types.CallbackQuery) -> None:
    provider_key = call.data.split(":")[1]
    state = get_state(call.from_user.id)
    state["provider_key"] = provider_key
    state["step"] = "pick_model"
    provider_name = PROVIDERS[provider_key]["name"]
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"Провайдер: {provider_name}\nВыберите модель:",
                          call.message.chat.id, call.message.message_id,
                          reply_markup=model_keyboard(provider_key))

@bot.callback_query_handler(func=lambda c: c.data.startswith("model:"))
def cb_model(call: types.CallbackQuery) -> None:
    _, provider_key, model_key = call.data.split(":")
    state = get_state(call.from_user.id)
    state["model_key"] = model_key
    state["step"] = "pick_temp"
    model_label = PROVIDERS[provider_key]["models"][model_key]["label"]
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"Модель: {model_label}\nВыберите температуру:",
                          call.message.chat.id, call.message.message_id,
                          reply_markup=temp_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("temp:"))
def cb_temp(call: types.CallbackQuery) -> None:
    temperature = float(call.data.split(":")[1])
    state = get_state(call.from_user.id)
    provider_key = state.get("provider_key", "1")
    model_key = state.get("model_key", "1")
    provider = PROVIDERS[provider_key]
    model = provider["models"][model_key]

    # Зажимаем температуру в допустимый диапазон модели
    lo, hi = model["temp_range"]
    temperature = max(lo, min(hi, temperature))

    def tool_callback(tool_name: str, tool_args: dict, tool_result: str) -> None:
        args_str = ", ".join(f"{k}={v!r}" for k, v in tool_args.items())
        preview = tool_result[:200] + ("..." if len(tool_result) > 200 else "")
        bot.send_message(call.message.chat.id,
                         f"[инструмент] {tool_name}({args_str})\n[результат] {preview}")

    state["agent"] = Agent(
        provider=provider,
        model=model,
        temperature=temperature,
        on_tool_call=tool_callback,
    )
    state["step"] = "idle"

    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"Готово!\n"
        f"Провайдер : {provider['name']}\n"
        f"Модель    : {model['label']}\n"
        f"Температура: {temperature}\n\n"
        f"Задайте любой вопрос.",
        call.message.chat.id, call.message.message_id,
    )
    logger.info("[bot] agent created for user=%d provider=%s model=%s temp=%.1f",
                call.from_user.id, provider["name"], model["id"], temperature)

# ─── Обработка входящих файлов (документы) ───────────────────────────────────

def _save_telegram_file(file_info, file_name: str) -> str:
    """Скачать файл из Telegram и сохранить в uploads/."""
    from tools import UPLOADS_DIR
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    dest = os.path.join(UPLOADS_DIR, file_name)
    downloaded = bot.download_file(file_info.file_path)
    with open(dest, "wb") as f:
        f.write(downloaded)
    return dest

@bot.message_handler(content_types=["document"])
def handle_document(message: types.Message) -> None:
    state = get_state(message.from_user.id)
    agent = state.get("agent")

    if agent is None:
        send(message.chat.id, "Сначала выберите провайдера командой /start")
        return

    doc = message.document
    file_name = doc.file_name or f"file_{doc.file_id}"
    ext = os.path.splitext(file_name)[1].lower()

    if ext not in (".pdf", ".docx", ".doc", ".txt"):
        send(message.chat.id,
             f"Формат {ext} не поддерживается.\nПоддерживаются: pdf, docx, doc, txt")
        return

    send(message.chat.id, f"Получен файл: {file_name}\nЗагружаю...")
    bot.send_chat_action(message.chat.id, "upload_document")

    def process_file():
        try:
            file_info = bot.get_file(doc.file_id)
            dest = _save_telegram_file(file_info, file_name)

            # Извлекаем текст из документа
            from tools import _extract_text, _document_store
            text = _extract_text(dest)

            if text.startswith("Ошибка") or text.startswith("Неподдерживаемый"):
                send(message.chat.id, text)
                return

            # Сохраняем в глобальное хранилище
            _document_store[file_name] = text
            chars = len(text)
            words = len(text.split())

            # Вставляем текст документа напрямую в историю агента
            # чтобы LLM мог отвечать на вопросы без вызова tool
            doc_context = (
                f"[Документ загружен: {file_name}]\n"
                f"Размер: {chars} символов, ~{words} слов.\n\n"
                f"Содержимое документа:\n{text[:6000]}"
                + (f"\n\n[...документ обрезан, показаны первые 6000 символов из {chars}]"
                   if chars > 6000 else "")
            )
            agent.history.append({"role": "user", "content": doc_context})
            agent.history.append({
                "role": "assistant",
                "content": f"Документ '{file_name}' загружен и прочитан. Готов отвечать на вопросы по его содержимому."
            })

            send(message.chat.id,
                 f"Документ '{file_name}' загружен: {chars} символов, ~{words} слов.\n"
                 f"Задайте вопрос по его содержимому.")
            logger.info("[bot] document loaded into agent history: %s chars=%d", file_name, chars)

            # Если есть подпись к файлу — сразу отвечаем на вопрос
            caption = message.caption
            if caption and caption.strip():
                bot.send_chat_action(message.chat.id, "typing")
                reply = agent.chat(caption.strip())
                send(message.chat.id, reply)

        except Exception as e:
            logger.error("[bot] document error: %s", e, exc_info=True)
            send(message.chat.id, f"Ошибка обработки файла: {e}")

    threading.Thread(target=process_file, daemon=True).start()


# ─── Обработка обычных сообщений ──────────────────────────────────────────────

@bot.message_handler(func=lambda m: True)
def handle_message(message: types.Message) -> None:
    state = get_state(message.from_user.id)
    agent: Agent = state.get("agent")

    if agent is None:
        send(message.chat.id,
             "Сначала выберите провайдера и модель командой /start")
        return

    user_text = message.text.strip()
    logger.info("[bot] user=%d message=%r", message.from_user.id, user_text[:80])

    # Показываем индикатор "печатает..."
    bot.send_chat_action(message.chat.id, "typing")

    # Запускаем агента в отдельном потоке чтобы не блокировать polling
    def run_agent():
        try:
            reply = agent.chat(user_text)
            send(message.chat.id, reply)
            logger.info("[bot] reply sent, len=%d", len(reply))
        except Exception as e:
            logger.error("[bot] agent error: %s", e)
            send(message.chat.id, f"Ошибка агента: {e}")

    threading.Thread(target=run_agent, daemon=True).start()

# ─── Точка входа ──────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("\nОшибка: BOT_TOKEN не найден в .env")
        print("Добавьте в agent/.env строку: BOT_TOKEN=ваш_токен")
        return

    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    setup_bot_logging(verbose=verbose)

    logger.info("[bot] starting polling, token=...%s", token[-6:])
    print(f"\nTelegram бот запущен. Откройте бота и отправьте /start")
    print("Для остановки нажмите Ctrl+C\n")

    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=20)
    except KeyboardInterrupt:
        print("\nБот остановлен.")
        logger.info("[bot] stopped")
