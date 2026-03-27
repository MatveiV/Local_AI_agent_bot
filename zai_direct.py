import os
import sys
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Available Z.AI models (free tier marked)
MODELS = {
    "1": {
        "id": "glm-4.7-flash",
        "name": "GLM-4.7-Flash",
        "context": "200K",
        "free": True,
        "supports_system": True,
        "temp_range": (0.0, 1.0),
        "max_tokens_limit": 4096,
        "description": "Free, lightweight, high-performance, 200K context",
    },
    "2": {
        "id": "glm-4.5-flash",
        "name": "GLM-4.5-Flash",
        "context": "200K",
        "free": True,
        "supports_system": True,
        "temp_range": (0.0, 1.0),
        "max_tokens_limit": 4096,
        "description": "Free, strong reasoning, 200K context",
    },
    "3": {
        "id": "glm-4.5",
        "name": "GLM-4.5",
        "context": "128K",
        "free": False,
        "supports_system": True,
        "temp_range": (0.0, 1.0),
        "max_tokens_limit": 8192,
        "description": "Better performance, strong reasoning, 128K context",
    },
    "4": {
        "id": "glm-4.7",
        "name": "GLM-4.7",
        "context": "200K",
        "free": False,
        "supports_system": True,
        "temp_range": (0.0, 1.0),
        "max_tokens_limit": 8192,
        "description": "SOTA performance, optimized agentic coding, 200K context",
    },
    "5": {
        "id": "glm-5",
        "name": "GLM-5",
        "context": "200K",
        "free": False,
        "supports_system": True,
        "temp_range": (0.0, 1.0),
        "max_tokens_limit": 8192,
        "description": "Flagship model, complex engineering & long-range agent tasks",
    },
}


def pick_model():
    print("Available models:")
    print(f"  {'#':<4} {'Model':<20} {'Context':<10} {'Free':<6} Description")
    print("  " + "-" * 70)
    for key, m in MODELS.items():
        free_tag = "yes" if m["free"] else "no"
        print(f"  {key:<4} {m['name']:<20} {m['context']:<10} {free_tag:<6} {m['description']}")
    choice = input("\nSelect model [1]: ").strip() or "1"
    return MODELS.get(choice, MODELS["1"])


def get_float(prompt, default, lo, hi):
    try:
        val = float(input(prompt).strip() or str(default))
        return max(lo, min(hi, val))
    except ValueError:
        return default


def get_int(prompt, default, lo, hi):
    try:
        val = int(input(prompt).strip() or str(default))
        return max(lo, min(hi, val))
    except ValueError:
        return default


def main():
    print("=== Z.AI Direct API ===\n")

    api_key = os.environ.get("ZAI_API_KEY")
    if not api_key:
        print("Error: ZAI_API_KEY not found in .env")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url="https://api.z.ai/api/paas/v4/")

    model = pick_model()
    tlo, thi = model["temp_range"]

    print(f"\nModel selected: {model['name']} | Context: {model['context']} | Free: {'yes' if model['free'] else 'no'}")
    print(f"Temperature range: {tlo}–{thi} | Max output tokens: up to {model['max_tokens_limit']}\n")

    system_message = ""
    if model["supports_system"]:
        system_message = input("System message (optional, Enter to skip): ").strip()

    user_query = input("Your query: ").strip()
    if not user_query:
        print("Error: query cannot be empty")
        sys.exit(1)

    temperature = get_float(f"Temperature ({tlo}–{thi}, default 0.7): ", 0.7, tlo, thi)
    max_tokens = get_int(f"Max tokens (1–{model['max_tokens_limit']}, default 1024): ", 1024, 1, model["max_tokens_limit"])

    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": user_query})

    print("\nSending request...\n")
    try:
        response = client.chat.completions.create(
            model=model["id"],
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        print("=" * 60)
        print(response.choices[0].message.content)
        print("=" * 60)
        print(f"Model:          {response.model}")
        print(f"Finish reason:  {response.choices[0].finish_reason}")
        if response.usage:
            print(f"Prompt tokens:  {response.usage.prompt_tokens}")
            print(f"Output tokens:  {response.usage.completion_tokens}")
            print(f"Total tokens:   {response.usage.total_tokens}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
