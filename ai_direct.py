"""
ai_direct.py — интерактивный CLI для работы с AI-моделями.
Запуск: python ai_direct.py

Команды в диалоге:
  /model  — сменить провайдера/модель/температуру
  /new    — очистить историю (промпты сохраняются)
  /exit   — выйти и сохранить сессию
"""
import json
import os
import sys
from datetime import datetime

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

SESSION_FILE = "session.json"

# ─── Промпты ─────────────────────────────────────────────────────────────────

def load_prompts(path: str = "prompts.json") -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)["prompts"]

# ─── Провайдеры и модели ──────────────────────────────────────────────────────

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
            "5": {"id": "glm-5",         "label": "GLM-5",         "free": False, "temp_range": (0.0, 1.0), "max_tokens": 8192},
        },
    },
    "2": {
        "name": "ProxyAPI (OpenAI)",
        "api_key_env": "PROXY_API_KEY",
        "base_url": "https://api.proxyapi.ru/openai/v1",
        "models": {
            "1": {"id": "gpt-4.1-nano",  "label": "GPT-4.1 Nano",  "free": False, "temp_range": (0.0, 2.0), "max_tokens": 32768},
            "2": {"id": "gpt-4.1-mini",  "label": "GPT-4.1 Mini",  "free": False, "temp_range": (0.0, 2.0), "max_tokens": 32768},
            "3": {"id": "gpt-4.1",       "label": "GPT-4.1",       "free": False, "temp_range": (0.0, 2.0), "max_tokens": 32768},
            "4": {"id": "gpt-4o-mini",   "label": "GPT-4o Mini",   "free": False, "temp_range": (0.0, 2.0), "max_tokens": 16384},
            "5": {"id": "gpt-4o",        "label": "GPT-4o",        "free": False, "temp_range": (0.0, 2.0), "max_tokens": 16384},
        },
    },
    "3": {
        "name": "GenAPI",
        "api_key_env": "GEN_API_KEY",
        "base_url": "https://proxy.gen-api.ru/v1",
        "models": {
            "1": {"id": "gpt-4-1-mini",      "label": "GPT-4.1 Mini",      "free": False, "temp_range": (0.0, 2.0), "max_tokens": 32768},
            "2": {"id": "gpt-4-1",           "label": "GPT-4.1",           "free": False, "temp_range": (0.0, 2.0), "max_tokens": 32768},
            "3": {"id": "gpt-4o",            "label": "GPT-4o",            "free": False, "temp_range": (0.0, 2.0), "max_tokens": 16384},
            "4": {"id": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5", "free": False, "temp_range": (0.0, 1.0), "max_tokens": 8192},
            "5": {"id": "gemini-2-5-flash",  "label": "Gemini 2.5 Flash",  "free": False, "temp_range": (0.0, 2.0), "max_tokens": 8192},
            "6": {"id": "deepseek-chat",     "label": "DeepSeek Chat",     "free": False, "temp_range": (0.0, 2.0), "max_tokens": 8192},
            "7": {"id": "deepseek-r1",       "label": "DeepSeek R1",       "free": False, "temp_range": (0.0, 2.0), "max_tokens": 16000},
        },
    },
}

# ─── Вспомогательные функции ──────────────────────────────────────────────────

def ask(prompt: str, default: str = "") -> str:
    val = input(prompt).strip()
    return val if val else default

def get_float(prompt: str, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(ask(prompt, str(default)))))
    except ValueError:
        return default

def sep(char: str = "─", width: int = 60) -> None:
    print(char * width)

# ─── Сессия: сохранение и загрузка ───────────────────────────────────────────

def save_session(state: dict) -> None:
    """Сохраняет параметры и историю диалога в session.json."""
    state["saved_at"] = datetime.now().isoformat(timespec="seconds")
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"\n  Сессия сохранена → {SESSION_FILE}")

def load_session() -> dict | None:
    """Загружает сессию из session.json, если файл существует."""
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def session_to_state(provider: dict, model: dict, temperature: float,
                     selected_prompts: list[dict], history: list[dict]) -> dict:
    """Упаковывает текущее состояние в сериализуемый словарь."""
    # Найдём ключи провайдера и модели для восстановления
    p_key = next(k for k, v in PROVIDERS.items() if v["name"] == provider["name"])
    m_key = next(k for k, v in PROVIDERS[p_key]["models"].items() if v["id"] == model["id"])
    return {
        "provider_key": p_key,
        "model_key": m_key,
        "temperature": temperature,
        "prompt_ids": [p["id"] for p in selected_prompts],
        "history": history,
    }

def restore_session(state: dict, all_prompts: list[dict]) -> tuple[dict, dict, float, list[dict], list[dict]]:
    """Восстанавливает объекты из сохранённого состояния."""
    provider = PROVIDERS[state["provider_key"]]
    model = provider["models"][state["model_key"]]
    temperature = state["temperature"]
    selected_prompts = [p for p in all_prompts if p["id"] in state["prompt_ids"]]
    history = state["history"]
    return provider, model, temperature, selected_prompts, history

# ─── Выбор провайдера и модели ────────────────────────────────────────────────

def pick_provider_and_model() -> tuple[dict, dict]:
    sep("═")
    print("  ВЫБОР ПРОВАЙДЕРА")
    sep("═")
    for key, p in PROVIDERS.items():
        print(f"  {key}. {p['name']}")
    p_key = ask("\nПровайдер [1]: ", "1")
    provider = PROVIDERS.get(p_key, PROVIDERS["1"])

    if not os.environ.get(provider["api_key_env"]):
        print(f"\nОшибка: {provider['api_key_env']} не найден в .env")
        sys.exit(1)

    sep()
    print(f"  МОДЕЛИ — {provider['name']}")
    sep()
    print(f"  {'#':<4} {'Модель':<25} {'Бесплатно':<12} Макс. токенов")
    sep()
    for key, m in provider["models"].items():
        print(f"  {key:<4} {m['label']:<25} {'да' if m['free'] else 'нет':<12} {m['max_tokens']}")

    m_key = ask("\nМодель [1]: ", "1")
    model = provider["models"].get(m_key, list(provider["models"].values())[0])
    return provider, model

def pick_temperature(model: dict) -> float:
    lo, hi = model["temp_range"]
    sep()
    return get_float(f"  Температура ({lo}–{hi}, по умолчанию 0.7): ", 0.7, lo, hi)

# ─── Выбор системных промптов ─────────────────────────────────────────────────

def pick_prompts(prompts: list[dict]) -> list[dict]:
    sep()
    print("  СИСТЕМНЫЕ ПРОМПТЫ (можно выбрать несколько)")
    sep()
    for p in prompts:
        print(f"  {p['id']:>2}. {p['name']}")
    print(f"  {'0':>2}. Без системного промпта")
    sep()
    raw = ask("  Номера через запятую (например: 1,3) или 0: ", "0")
    if raw == "0":
        return []
    selected = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            match = next((p for p in prompts if p["id"] == int(part)), None)
            if match:
                selected.append(match)
    return selected

def build_system_message(selected: list[dict]) -> str:
    if not selected:
        return ""
    return "\n\n".join(
        f"[{p['name']}]\nРоль: {p['role']}\nКонтекст: {p['context']}"
        for p in selected
    )

# ─── Вывод текущих параметров ─────────────────────────────────────────────────

def print_status(provider: dict, model: dict, temperature: float, selected_prompts: list[dict]) -> None:
    sep("═")
    print(f"  Провайдер : {provider['name']}")
    print(f"  Модель    : {model['label']}")
    print(f"  Температура: {temperature}")
    if selected_prompts:
        names = ", ".join(p["name"] for p in selected_prompts)
        print(f"  Промпты   : {names}")
    else:
        print("  Промпты   : нет")
    print("  Команды   : /model  /new  /exit")
    sep("═")

# ─── Диалоговый цикл ──────────────────────────────────────────────────────────

def chat_loop(
    provider: dict,
    model: dict,
    temperature: float,
    selected_prompts: list[dict],
    history: list[dict],
    all_prompts: list[dict],
) -> None:
    """Основной цикл диалога. Возвращает финальное состояние для сохранения."""

    def make_client(p: dict) -> OpenAI:
        return OpenAI(api_key=os.environ.get(p["api_key_env"]), base_url=p["base_url"])

    client = make_client(provider)
    system_message = build_system_message(selected_prompts)

    # Если история пустая — добавим системный промпт
    if not history and system_message:
        history.append({"role": "system", "content": system_message})

    print_status(provider, model, temperature, selected_prompts)

    while True:
        try:
            user_input = input("\nВы: ").strip()
        except (KeyboardInterrupt, EOFError):
            user_input = "/exit"

        if not user_input:
            continue

        # ── /exit ──────────────────────────────────────────────────────────
        if user_input.lower() == "/exit":
            state = session_to_state(provider, model, temperature, selected_prompts, history)
            save_session(state)
            print("До встречи.")
            break

        # ── /new ───────────────────────────────────────────────────────────
        if user_input.lower() == "/new":
            history.clear()
            system_message = build_system_message(selected_prompts)
            if system_message:
                history.append({"role": "system", "content": system_message})
            print("\n  Контекст очищен. Параметры сохранены.")
            print_status(provider, model, temperature, selected_prompts)
            continue

        # ── /model ─────────────────────────────────────────────────────────
        if user_input.lower() == "/model":
            provider, model = pick_provider_and_model()
            temperature = pick_temperature(model)
            client = make_client(provider)
            # Обновляем системный промпт в истории если он есть
            if history and history[0]["role"] == "system":
                history[0]["content"] = build_system_message(selected_prompts)
            print(f"\n  Модель изменена на {model['label']} (температура {temperature})")
            print_status(provider, model, temperature, selected_prompts)
            continue

        # ── обычный запрос ─────────────────────────────────────────────────
        history.append({"role": "user", "content": user_input})
        print("\n  Отправка запроса...\n")
        try:
            response = client.chat.completions.create(
                model=model["id"],
                messages=history,
                temperature=temperature,
                max_tokens=model["max_tokens"],
            )
            reply = response.choices[0].message.content or ""
            history.append({"role": "assistant", "content": reply})

            sep()
            print(f"ИИ: {reply}")
            sep()

            if response.usage:
                u = response.usage
                print(f"  Токены: вход {u.prompt_tokens} | выход {u.completion_tokens} | всего {u.total_tokens}")

        except Exception as e:
            print(f"  Ошибка: {e}")
            history.pop()

# ─── Точка входа ──────────────────────────────────────────────────────────────

def main() -> None:
    print("\n" + "═" * 60)
    print("  AI DIRECT — интерактивный CLI")
    print("═" * 60)

    all_prompts = load_prompts()

    # Предложить восстановить предыдущую сессию
    saved = load_session()
    if saved:
        saved_at = saved.get("saved_at", "неизвестно")
        msg_count = sum(1 for m in saved.get("history", []) if m["role"] == "user")
        print(f"\n  Найдена сохранённая сессия от {saved_at} ({msg_count} сообщений).")
        choice = ask("  Продолжить? (y/n) [y]: ", "y").lower()
        if choice == "y":
            provider, model, temperature, selected_prompts, history = restore_session(saved, all_prompts)
            print(f"\n  Сессия восстановлена.")
            chat_loop(provider, model, temperature, selected_prompts, history, all_prompts)
            return

    # Новая сессия
    provider, model = pick_provider_and_model()
    temperature = pick_temperature(model)
    selected_prompts = pick_prompts(all_prompts)

    chat_loop(provider, model, temperature, selected_prompts, [], all_prompts)


if __name__ == "__main__":
    main()
