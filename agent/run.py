"""
run.py — CLI-интерфейс запуска AI-агента.
Запуск: python run.py

Команды в диалоге:
  /new      — очистить историю диалога
  /memory   — показать последние записи из памяти
  /model    — сменить провайдера/модель
  /help     — список команд
  /exit     — выйти
"""
import json
import logging
import os
import sys

# ─── Проверка версии Python ───────────────────────────────────────────────────
if sys.version_info >= (3, 12):
    print(
        f"\nОШИБКА: Обнаружена Python {sys.version_info.major}.{sys.version_info.minor}.\n"
        "Этот проект требует Python < 3.12 для совместимости с LangChain 0.7.3.\n"
        "\nСоздайте виртуальное окружение с нужной версией:\n"
        "  py -3.11 -m venv venv311\n"
        "  venv311\\Scripts\\activate      # Windows\n"
        "  source venv311/bin/activate   # Linux / macOS\n"
        "  pip install -r requirements.txt\n"
        "  python run.py\n"
    )
    sys.exit(1)

from dotenv import load_dotenv

# Загружаем .env из папки agent/
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from agent import Agent, PROVIDERS, load_memory

# ─── Callback для терминала ───────────────────────────────────────────────────

def terminal_tool_callback(tool_name: str, tool_args: dict, tool_result: str) -> None:
    args_str = ", ".join(f"{k}={v!r}" for k, v in tool_args.items())
    print(f"\n  [инструмент] {tool_name}({args_str})")
    preview = tool_result[:200] + ("..." if len(tool_result) > 200 else "")
    print(f"  [результат] {preview}")

# ─── Логирование ──────────────────────────────────────────────────────────────

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("agent.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout) if verbose else logging.NullHandler(),
        ],
    )

# ─── Вспомогательные функции ──────────────────────────────────────────────────

def sep(char: str = "─", width: int = 60) -> None:
    print(char * width)

def ask(prompt: str, default: str = "") -> str:
    val = input(prompt).strip()
    return val if val else default

def get_float(prompt: str, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(ask(prompt, str(default)))))
    except ValueError:
        return default

# ─── Выбор провайдера и модели ────────────────────────────────────────────────

def pick_provider_and_model() -> tuple[dict, dict]:
    sep("═")
    print("  ВЫБОР ПРОВАЙДЕРА")
    sep("═")
    for key, p in PROVIDERS.items():
        print(f"  {key}. {p['name']}")
    p_key = ask("\nПровайдер [1]: ", "1")
    provider = PROVIDERS.get(p_key, PROVIDERS["1"])

    api_key = os.environ.get(provider["api_key_env"])
    if not api_key:
        print(f"\nОшибка: {provider['api_key_env']} не найден в .env")
        sys.exit(1)

    sep()
    print(f"  МОДЕЛИ — {provider['name']}")
    sep()
    print(f"  {'#':<4} {'Модель':<25} {'Бесплатно':<12} Макс. токенов")
    sep()
    for key, m in provider["models"].items():
        free_tag = "да" if m.get("free") else "нет"
        print(f"  {key:<4} {m['label']:<25} {free_tag:<12} {m['max_tokens']}")

    m_key = ask("\nМодель [1]: ", "1")
    model = provider["models"].get(m_key, list(provider["models"].values())[0])
    return provider, model

def pick_temperature(model: dict) -> float:
    lo, hi = model["temp_range"]
    sep()
    return get_float(f"  Температура ({lo}–{hi}, по умолчанию 0.7): ", 0.7, lo, hi)

# ─── Показать память ──────────────────────────────────────────────────────────

def show_memory(n: int = 5) -> None:
    memory = load_memory()
    if not memory:
        print("  Память пуста.")
        return
    recent = memory[-n:]
    sep()
    print(f"  Последние {len(recent)} записей из памяти:")
    sep()
    for entry in recent:
        print(f"  [{entry.get('timestamp', '?')}] {entry.get('provider', '?')} / {entry.get('model', '?')}")
        print(f"  Вы: {entry.get('user', '')[:80]}")
        print(f"  ИИ: {entry.get('assistant', '')[:120]}")
        sep()

# ─── Главный цикл ─────────────────────────────────────────────────────────────

def print_help() -> None:
    sep()
    print("  Команды:")
    print("    /new     — очистить историю диалога")
    print("    /memory  — показать последние записи из памяти")
    print("    /model   — сменить провайдера/модель/температуру")
    print("    /load <путь> — загрузить документ (pdf/docx/txt)")
    print("    /docs    — список загруженных документов")
    print("    /help    — эта справка")
    print("    /exit    — выйти")
    sep()

def print_status(provider: dict, model: dict, temperature: float) -> None:
    sep("═")
    print(f"  AI-Агент запущен")
    print(f"  Провайдер  : {provider['name']}")
    print(f"  Модель     : {model['label']}")
    print(f"  Температура: {temperature}")
    print(f"  Лог        : agent.log")
    print_help()

def main() -> None:
    print("\n" + "═" * 60)
    print("  LOCAL AI AGENT")
    print("═" * 60)
    print("  Выберите режим запуска:")
    print("  1. Терминал (CLI)")
    print("  2. Telegram бот")
    sep("═")
    mode = ask("\nРежим [1]: ", "1")

    if mode == "2":
        # Запуск Telegram бота
        try:
            import telegram_bot
            telegram_bot.main()
        except ImportError as e:
            print(f"\nОшибка: не удалось импортировать telegram_bot: {e}")
            print("Убедитесь что установлен pyTelegramBotAPI: pip install pyTelegramBotAPI")
        return

    # Режим терминала
    print("\n" + "═" * 60)
    print("  LOCAL AI AGENT — терминальный агент")
    print("═" * 60)

    # Режим логирования
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    setup_logging(verbose=verbose)

    logger = logging.getLogger("run")
    logger.info("=== Agent started ===")

    provider, model = pick_provider_and_model()
    temperature = pick_temperature(model)

    agent = Agent(provider=provider, model=model, temperature=temperature,
                  on_tool_call=terminal_tool_callback)
    print_status(provider, model, temperature)

    while True:
        try:
            user_input = input("\nВы: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nДо встречи.")
            logger.info("=== Agent stopped ===")
            break

        if not user_input:
            continue

        if user_input.lower() == "/exit":
            print("До встречи.")
            logger.info("=== Agent stopped ===")
            break

        if user_input.lower() == "/new":
            agent.clear_history()
            print("  Контекст очищен.")
            continue

        if user_input.lower() == "/memory":
            show_memory()
            continue

        if user_input.lower() == "/help":
            print_help()
            continue

        if user_input.lower().startswith("/load "):
            file_path = user_input[6:].strip().strip('"').strip("'")
            from tools import read_document
            result = read_document(file_path)
            print(f"\n  {result}\n")
            continue

        if user_input.lower() == "/docs":
            from tools import list_documents
            print(f"\n  {list_documents()}\n")
            continue

        if user_input.lower() == "/model":
            provider, model = pick_provider_and_model()
            temperature = pick_temperature(model)
            agent = Agent(provider=provider, model=model, temperature=temperature,
                          on_tool_call=terminal_tool_callback)
            print_status(provider, model, temperature)
            continue

        print("\n  Думаю...\n")
        logger.info("User input: %r", user_input)

        reply = agent.chat(user_input)

        sep()
        print(f"Агент: {reply}")
        sep()

        logger.info("Agent reply length: %d", len(reply))


if __name__ == "__main__":
    main()
