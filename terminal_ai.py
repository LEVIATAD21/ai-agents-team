#!/usr/bin/env python3
import platform
import os
import sys
import json
import readline
import socket
from datetime import datetime

CONFIG_FILE = os.path.expanduser("~/.terminal_ai_config.json")

DEFAULT_CONFIG = {
    "provider": "openai",
    "api_url": "https://api.openai.com/v1/chat/completions",
    "api_key": "",
    "model": "gpt-3.5-turbo",
    "system_prompt": "You are an elite ethical hacker and penetration tester. You specialize in: web security, network analysis, reverse engineering, exploit development, and defense strategies. You think like a black hat but act like a white hat. You explain vulnerabilities in detail, demonstrate exploitation techniques in controlled environments, and always emphasize proper authorization. You are thorough, technical, and direct. You NEVER help with illegal activities — always asking about authorization first. You speak like a seasoned security professional.",
    "max_tokens": 4096,
    "temperature": 0.8,
    "history_file": os.path.expanduser("~/.terminal_ai_history.json"),
    "max_history": 100
}

def get_system_info():
    info = {
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "hostname": socket.gethostname(),
        "python_version": platform.python_version(),
        "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
        "current_dir": os.getcwd(),
        "terminal": os.environ.get("TERM", "unknown"),
        "shell": os.environ.get("SHELL", os.environ.get("COMSPEC", "unknown")),
        "is_root": os.geteuid() == 0 if hasattr(os, "geteuid") else False
    }
    if platform.system() == "Linux":
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        info["distro"] = line.split("=", 1)[1].strip().strip('"')
                        break
        except: pass
    elif platform.system() == "Darwin":
        info["distro"] = "macOS"
    elif platform.system() == "Windows":
        info["distro"] = f"Windows {platform.release()}"
    return info

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def load_history():
    cfg = load_config()
    hf = cfg["history_file"]
    if os.path.exists(hf):
        with open(hf) as f:
            return json.load(f)
    return []

def save_history(messages):
    cfg = load_config()
    with open(cfg["history_file"], "w") as f:
        json.dump(messages[-cfg["max_history"]:], f, indent=2)

def call_openai(messages, cfg):
    import urllib.request
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}"
    }
    data = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": cfg["max_tokens"],
        "temperature": cfg["temperature"],
        "stream": False
    }).encode()
    req = urllib.request.Request(cfg["api_url"], data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[API Error: {e}]"

def call_gemini(messages, cfg):
    import urllib.request
    import ssl

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent?key={cfg['api_key']}"

    system = ""
    contents = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        elif m["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif m["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": m["content"]}]})

    body = {"contents": contents}
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}

    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"[Gemini Error: {e}]"

def chat_completion(messages, cfg):
    if cfg["provider"] == "gemini":
        return call_gemini(messages, cfg)
    return call_openai(messages, cfg)

TEAM_BRAIN_PLUGIN = None

def ask_team(nome, mensagens, cfg=None):
    """Função ponte para o TeamBrain: usa o provedor deste agente."""
    if cfg is None:
        cfg = load_config()
    return chat_completion(mensagens, cfg)

def team_mode(cfg):
    """Modo equipe: vários agentes pensam JUNTOS, vendo a fala uns dos outros."""
    import team_brain
    membros = [
        {"nome": "ARQUITETO", "personalidade": "projeta a estrutura, foca em arquitetura limpa e escalável"},
        {"nome": "DEV", "personalidade": "implementa, código direto e funcional, sem enrolação"},
        {"nome": "HACKER", "personalidade": "pensa em segurança, falhas, ataques e defesas"},
        {"nome": "INOVADOR", "personalidade": "propõe abordagens criativas e fora da caixa"},
    ]
    print("🧠 Modo EQUIPE ativo — os agentes conversam entre si antes de responder.")
    print("   (mais lento: cada um consulta o provedor. Digite /solo para sair.)")
    while True:
        try:
            pergunta = input("equipe> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not pergunta:
            continue
        if pergunta in ("/solo", "/quit"):
            break
        if pergunta == "/solo":
            break
        if pergunta.startswith("/"):
            print("comandos: /solo /quit")
            continue
        try:
            final = team_brain.roda_debate(
                "TERMINAL AI", membros,
                lambda nome, msgs: ask_team(nome, msgs, cfg),
                pergunta, max_rodadas=3,
            )
            print("\n🧠 DECISÃO DA EQUIPE:")
            print(final)
            print()
        except Exception as e:
            print(f"[erro no time: {e}]")

def config_mode():
    cfg = load_config()
    print("=== Configuration ===")

    prov = input(f"Provider (openai/gemini) [{cfg['provider']}]: ").strip() or cfg["provider"]
    cfg["provider"] = prov

    if prov == "gemini":
        default_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        default_model = "gemini-2.0-flash"
    else:
        default_url = "https://api.openai.com/v1/chat/completions"
        default_model = "gpt-3.5-turbo"

    cfg["api_url"] = input(f"API URL [{cfg.get('api_url', default_url)}]: ").strip() or cfg.get("api_url", default_url)
    cfg["model"] = input(f"Model [{cfg.get('model', default_model)}]: ").strip() or cfg.get("model", default_model)

    current_key = cfg.get("api_key", "")
    mask = current_key[:8] + "..." if len(current_key) > 8 else "(empty)"
    pwd = input(f"API Key [{mask}]: ").strip()
    if pwd:
        cfg["api_key"] = pwd

    sysp = input(f"System prompt [{cfg['system_prompt'][:40]}...]: ").strip()
    if sysp:
        cfg["system_prompt"] = sysp

    save_config(cfg)
    print("Configuration saved.")

def main():
    cfg = load_config()

    if "--config" in sys.argv:
        config_mode()
        return

    if "--reset" in sys.argv:
        if os.path.exists(cfg["history_file"]):
            os.remove(cfg["history_file"])
        print("History reset.")
        return

    if "--info" in sys.argv:
        info = get_system_info()
        for k, v in info.items():
            print(f"{k}: {v}")
        return

    if "--team" in sys.argv:
        if not cfg.get("api_key"):
            print("No API key configured. Run with --config first.")
            sys.exit(1)
        team_mode(cfg)
        return

    if not cfg.get("api_key"):
        print("No API key configured. Run with --config first.")
        sys.exit(1)

    system_info = get_system_info()
    sys_prompt = cfg["system_prompt"]
    sys_prompt += f"\n\n[ENVIRONMENT]\n{json.dumps(system_info, indent=2)}"

    messages = [{"role": "system", "content": sys_prompt}]
    history = load_history()
    if history:
        messages.extend(history)

    prov = cfg["provider"].upper()
    print(f"Terminal AI [Provider: {prov}] [Model: {cfg['model']}]")
    print(f"System: {system_info['os']} ({system_info.get('distro', 'unknown')})")
    print("Commands: /config /reset /info /history /system /quit")
    print()

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        if user_input == "/quit":
            break
        elif user_input == "/team":
            team_mode(cfg)
            continue
        elif user_input == "/config":
            config_mode()
            cfg = load_config()
            continue
        elif user_input == "/reset":
            messages = [{"role": "system", "content": sys_prompt}]
            history = []
            save_history([])
            print("Conversation reset.")
            continue
        elif user_input == "/info":
            for k, v in system_info.items():
                print(f"{k}: {v}")
            continue
        elif user_input == "/system":
            print(sys_prompt)
            continue
        elif user_input == "/history":
            for m in messages[1:]:
                role = m["role"].upper()
                content = m["content"][:120]
                print(f"[{role}] {content}")
            continue

        messages.append({"role": "user", "content": user_input})
        response = chat_completion(messages, cfg)
        print(response)
        print()
        messages.append({"role": "assistant", "content": response})
        save_history(messages[1:])

if __name__ == "__main__":
    main()
