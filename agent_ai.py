#!/usr/bin/env python3
"""
Terminal Autonomous AI Agent
Executes commands, creates files, and works until goal is complete.
"""
import platform
import os
import sys
import json
import readline
import subprocess
import socket
import traceback
import shlex
from datetime import datetime
from pathlib import Path

CONFIG_FILE = os.path.expanduser("~/.agent_ai_config.json")
LOG_FILE = os.path.expanduser("~/.agent_ai_log.json")

DEFAULT_CONFIG = {
    "provider": "gemini",
    "api_url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
    "api_key": "",
    "model": "gemini-2.0-flash",
    "max_tokens": 8192,
    "temperature": 0.7,
    "max_iterations": 50,
    "working_directory": os.getcwd(),
    "safe_mode": True
}

TOOLS_DESC = """
You have access to the following tools. Respond with a JSON block:

```json
{
  "tool": "tool_name",
  "args": { ... }
}
```

Tools:
1. **execute** - Run a bash command
   args: { "command": "ls -la" }
   
2. **write_file** - Write content to a file (creates dirs if needed)
   args: { "path": "/path/to/file.py", "content": "print('hello')" }

3. **read_file** - Read a file
   args: { "path": "/path/to/file.txt" }

4. **read_dir** - List directory contents
   args: { "path": "/path/to/dir" }

5. **append_file** - Append content to a file
   args: { "path": "/path/to/file.py", "content": "new line" }

6. **think** - Internal reasoning step
   args: { "thought": "I need to check if the file exists first..." }

7. **finalize** - Task is complete. Provide summary.
   args: { "summary": "What was done", "output": "final result or file paths" }

Rules:
- Think step by step. Break complex goals into smaller steps.
- Use execute to check prerequisites before acting.
- Use write_file/create for generating code.
- Use finalize ONLY when the goal is fully complete.
- Working directory: {workdir}
- Environment: {env_info}
- Package manager is 'pkg' on Termux, not apt/yum.
- No root access available. Commands requiring root will fail.
"""

def get_system_info():
    is_termux = "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux")
    os_name = "Android (Termux)" if is_termux else platform.system()
    info = {
        "os": os_name,
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "hostname": socket.gethostname(),
        "python_version": platform.python_version(),
        "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
        "shell": os.environ.get("SHELL", os.environ.get("COMSPEC", "unknown")),
        "is_termux": is_termux,
        "has_root": os.system("id -u 2>/dev/null") == 0 if not is_termux else False
    }
    info["has_root"] = False
    if is_termux:
        info["distro"] = "Termux (Android)"
        info["package_manager"] = "pkg"
        info["storage_base"] = "/data/data/com.termux/files/home"
    elif platform.system() == "Linux":
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        info["distro"] = line.split("=", 1)[1].strip().strip('"')
                        break
        except: pass
        try:
            info["has_root"] = os.geteuid() == 0
        except: pass
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

def log_step(step_num, tool, args, result, goal):
    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            log = json.load(f)
    log.append({
        "step": step_num,
        "tool": tool,
        "args": args,
        "result_preview": str(result)[:300],
        "goal": goal,
        "timestamp": datetime.now().isoformat()
    })
    with open(LOG_FILE, "w") as f:
        json.dump(log[-200:], f, indent=2)

def safe_execute(command, workdir, timeout=60):
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"[STDERR]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[EXIT CODE: {result.returncode}]"
        return output[:5000] if output else "(empty output)"
    except subprocess.TimeoutExpired:
        return "[TIMEOUT: command exceeded 60s]"
    except Exception as e:
        return f"[ERROR: {e}]"

def call_gemini(prompt, cfg):
    import urllib.request
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent?key={cfg['api_key']}"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": cfg["max_tokens"],
            "temperature": cfg["temperature"]
        }
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return None

def team_mode(cfg):
    """Modo equipe: agentes conversam entre si antes de agir."""
    import team_brain
    membros = [
        {"nome": "PLANEJADOR", "personalidade": "define objetivos, ordem de passos e critérios de conclusão"},
        {"nome": "EXECUTOR", "personalidade": "pensa em ações de terminal concretas e verificáveis"},
        {"nome": "REVISOR", "personalidade": "procura erros, efeitos colaterais e o que pode dar errado"},
    ]
    print("🧠 Modo EQUIPE — os agentes organizam o plano JUNTOS antes de executar.")
    while True:
        try:
            pergunta = input("equipe> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not pergunta:
            continue
        if pergunta.lower() in ("exit", "quit", "/solo"):
            break
        if pergunta.startswith("/"):
            print("comandos: /solo /quit")
            continue
        try:
            final = team_brain.roda_debate(
                "AGENT TEAM", membros,
                lambda nome, msgs: call_gemini(msgs[-1]["content"], cfg),
                pergunta, max_rodadas=2,
            )
            print("\n🧠 DECISÃO DA EQUIPE:")
            print(final)
            print()
        except Exception as e:
            print(f"[erro no time: {e}]")

def parse_tool_response(text):
    try:
        start = text.index("```json")
        end = text.index("```", start + 7)
        block = text[start+7:end].strip()
        return json.loads(block)
    except (ValueError, json.JSONDecodeError):
        try:
            return json.loads(text)
        except:
            return None

def build_prompt(goal, step, history, workdir, env_info):
    hist_text = ""
    for h in history[-10:]:
        hist_text += f"\n{h['role'].upper()}: {h['content'][:500]}"

    return f"""You are an autonomous terminal agent. Your GOAL is:
{goal}

Working directory: {workdir}
Environment: {json.dumps(env_info)}

{TOOLS_DESC.format(workdir=workdir, env_info=json.dumps(env_info))}

Previous steps:{hist_text}

Current step: {step}

What is your next action?"""

def config_mode():
    cfg = load_config()
    print("=== Agent Configuration ===")
    prov = input(f"Provider (gemini/openai) [{cfg['provider']}]: ").strip() or cfg["provider"]
    cfg["provider"] = prov
    if prov == "gemini":
        cfg["api_url"] = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
        cfg["model"] = input(f"Model [gemini-2.0-flash]: ").strip() or "gemini-2.0-flash"
    else:
        cfg["api_url"] = input(f"API URL [{cfg['api_url']}]: ").strip() or cfg["api_url"]
        cfg["model"] = input(f"Model [{cfg['model']}]: ").strip() or cfg["model"]
    pwd = input("API Key: ").strip()
    if pwd: cfg["api_key"] = pwd
    save_config(cfg)
    print("Saved.")

def main():
    cfg = load_config()

    if "--config" in sys.argv:
        config_mode()
        return

    if "--log" in sys.argv:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                for entry in json.load(f):
                    print(f"[Step {entry['step']}] {entry['tool']} -> {entry['result_preview']}")
        return

    if "--team" in sys.argv:
        if not cfg.get("api_key"):
            print("No API key. Run with --config first.")
            sys.exit(1)
        team_mode(cfg)
        return

    if not cfg.get("api_key"):
        print("No API key. Run with --config first.")
        sys.exit(1)

    print("=== Autonomous Agent ===")
    print(f"Provider: {cfg['provider']} | Model: {cfg['model']}")
    print("Type your goal or 'exit' to quit.")
    print()

    while True:
        try:
            goal = input("Goal: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not goal:
            continue
        if goal.lower() in ("exit", "quit"):
            break

        env_info = get_system_info()
        workdir = cfg["working_directory"]
        history = []
        step = 1
        max_steps = cfg["max_iterations"]
        complete = False

        print(f"\n[Agent] Starting work on: {goal}")
        print(f"[Agent] Working dir: {workdir}")
        print("[Agent] Press Ctrl+C at any time to interrupt.\n")

        try:
            while step <= max_steps and not complete:
                prompt = build_prompt(goal, step, history, workdir, env_info)
                print(f"[Step {step}] Thinking...")

                response = call_gemini(prompt, cfg)
                if not response:
                    print("[Agent] API error. Check key/model.")
                    break

                parsed = parse_tool_response(response)
                if not parsed:
                    print(f"[Agent] Couldn't parse response:")
                    print(response[:500])
                    step += 1
                    continue

                tool = parsed.get("tool")
                args = parsed.get("args", {})
                print(f"[Step {step}] Tool: {tool} | Args: {str(args)[:100]}")

                result = ""
                if tool == "execute":
                    cmd = args.get("command", "")
                    result = safe_execute(cmd, workdir)
                    is_termux = "TERMUX_VERSION" in os.environ
                    dangerous = ("rm -rf " in cmd or cmd.strip().startswith("dd ") or "mkfs" in cmd or "sudo " in cmd or ">" in cmd.strip().split()[:1])
                    if cfg["safe_mode"] and dangerous and not is_termux:
                        print(f"[SAFETY] Command halted: {cmd}")
                        print(f"[SAFETY] Type 'allow' to run or anything else to skip:")
                        try:
                            confirm = input("> ").strip()
                        except: confirm = "n"
                        if confirm.lower() != "allow":
                            result = "[SKIPPED by user]"
                        else:
                            result = safe_execute(cmd, workdir)
                    print(f"[Output] {result[:500]}")
                elif tool == "write_file":
                    path = args.get("path", "")
                    content = args.get("content", "")
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    with open(path, "w") as f:
                        f.write(content)
                    result = f"Written {len(content)} bytes to {path}"
                    print(f"[Output] {result}")
                elif tool == "read_file":
                    path = args.get("path", "")
                    if os.path.exists(path):
                        with open(path) as f:
                            content = f.read()
                        result = content[:2000]
                    else:
                        result = f"[File not found: {path}]"
                    print(f"[Output] {result[:300]}")
                elif tool == "read_dir":
                    path = args.get("path", ".")
                    try:
                        items = os.listdir(path)
                        result = "\n".join(items[:50])
                    except Exception as e:
                        result = f"[Error: {e}]"
                    print(f"[Output] {result[:300]}")
                elif tool == "append_file":
                    path = args.get("path", "")
                    content = args.get("content", "")
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    with open(path, "a") as f:
                        f.write(content)
                    result = f"Appended {len(content)} bytes to {path}"
                    print(f"[Output] {result}")
                elif tool == "think":
                    thought = args.get("thought", "")
                    result = f"[Thinking: {thought}]"
                    print(f"[Thought] {thought}")
                elif tool == "finalize":
                    summary = args.get("summary", "Task completed")
                    output = args.get("output", "")
                    complete = True
                    result = f"[COMPLETE] {summary}"
                    print(f"\n{'='*50}")
                    print(f"[AGENT] GOAL COMPLETE!")
                    print(f"Summary: {summary}")
                    if output: print(f"Output: {output}")
                    print(f"{'='*50}\n")
                else:
                    result = f"[Unknown tool: {tool}]"
                    print(result)

                log_step(step, tool, args, result, goal)
                history.append({"role": "assistant", "content": f"Tool: {tool}, Result: {result[:300]}"})
                step += 1

            if not complete:
                print(f"[Agent] Stopped after {step-1} steps without finalizing.")
        except KeyboardInterrupt:
            print("\n[Agent] Interrupted by user.")
        print()

if __name__ == "__main__":
    main()
