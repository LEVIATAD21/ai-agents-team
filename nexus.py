#!/usr/bin/env python3
"""
NEXUS - Autonomous Terminal AI Agent
Adapts to any environment. Plans, executes, verifies, self-corrects.
"""
import platform
import os
import sys
import json
import readline
import subprocess
import socket
import shlex
import re
import textwrap
import urllib.request
import urllib.parse
import ssl
import time
import hashlib
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser

CONFIG_DIR = os.path.expanduser("~/.nexus")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
MEMORY_FILE = os.path.join(CONFIG_DIR, "memory.json")
LOG_FILE = os.path.join(CONFIG_DIR, "session_log.json")
os.makedirs(CONFIG_DIR, exist_ok=True)

DEFAULT_CONFIG = {
    "provider": "gemini",
    "model": "gemini-2.0-flash",
    "api_key": "",
    "max_tokens": 8192,
    "temperature": 0.7,
    "max_iterations": 100,
    "safe_mode": True,
    "auto_install": True,
    "web_search_enabled": True,
}

# ─── Environment Detection ───────────────────────────────────────────────

def detect_environment():
    is_termux = "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux")
    env = {
        "os": "Android (Termux)" if is_termux else platform.system(),
        "os_release": platform.release(),
        "arch": platform.machine(),
        "hostname": socket.gethostname(),
        "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
        "cwd": os.getcwd(),
        "home": os.path.expanduser("~"),
        "python": platform.python_version(),
        "is_termux": is_termux,
        "has_root": False,
        "shell": os.environ.get("SHELL", os.environ.get("COMSPEC", "sh")),
        "terminal": os.environ.get("TERM", ""),
    }

    if is_termux:
        env["pkg_mgr"] = "pkg"
        env["distro"] = "Termux"
        env["has_root"] = False
    else:
        env["pkg_mgr"] = detect_pkg_mgr()
        env["distro"] = detect_distro()
        try: env["has_root"] = os.geteuid() == 0
        except: pass

    # Available tools
    env["tools"] = {}
    for cmd in ["git", "curl", "wget", "node", "npm", "gcc", "make", "docker", "ping", "nmap", "python3", "java", "go", "rustc", "sqlite3"]:
        env["tools"][cmd] = shutil_which(cmd) is not None

    env["display"] = os.environ.get("DISPLAY") is not None
    return env

def shutil_which(cmd):
    try:
        return subprocess.run(["which", cmd], capture_output=True, text=True).returncode == 0
    except: return False

def detect_distro():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except: pass
    try:
        with open("/etc/issue") as f:
            return f.read().strip().split("\n")[0]
    except: pass
    return "unknown"

def detect_pkg_mgr():
    if "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux"):
        if shutil_which("pkg"): return "pkg"
    for mgr in [("apt", "apt-get"), ("pkg", "pkg"), ("apk", "apk"), ("yum", "yum"), ("dnf", "dnf"), ("pacman", "pacman"), ("brew", "brew"), ("choco", "choco")]:
        if shutil_which(mgr[0]):
            return mgr[1]
    return "unknown"

# ─── Config ───────────────────────────────────────────────────────────────

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

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE) as f:
            return json.load(f)
    return {"sessions": [], "learned": {}, "preferences": {}}

def save_memory(mem):
    with open(MEMORY_FILE, "w") as f:
        json.dump(mem, f, indent=2)

def log_session(goal, steps, status):
    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            log = json.load(f)
    log.append({
        "goal": goal,
        "steps": steps,
        "status": status,
        "timestamp": datetime.now().isoformat(),
    })
    with open(LOG_FILE, "w") as f:
        json.dump(log[-50:], f, indent=2)

# ─── API Calls ────────────────────────────────────────────────────────────

def call_gemini(prompt, cfg, system=None):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent?key={cfg['api_key']}"
    parts = [{"text": prompt}]
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": cfg["max_tokens"],
            "temperature": cfg["temperature"],
        }
    }
    if system:
        body["system_instruction"] = {"parts": [{"text": system}]}
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return f"[API ERROR {e.code}: {body[:300]}]"
    except Exception as e:
        return f"[API ERROR: {e}]"

def call_openai(messages, cfg):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}"
    }
    data = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "max_tokens": cfg["max_tokens"],
        "temperature": cfg["temperature"],
    }).encode()
    req = urllib.request.Request(cfg.get("api_url", "https://api.openai.com/v1/chat/completions"), data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[API ERROR: {e}]"

def call_ai(system, prompt, cfg):
    if cfg["provider"] == "gemini":
        return call_gemini(prompt, cfg, system)
    else:
        return call_openai([{"role": "system", "content": system}, {"role": "user", "content": prompt}], cfg)

def team_mode(cfg):
    """Modo equipe: agentes pensam JUNTOS, vendo e respondendo a fala uns dos outros."""
    import team_brain
    membros = [
        {"nome": "ANALISTA", "personalidade": "entende o problema a fundo, coleta fatos, define o que precisa ser feito"},
        {"nome": "EXECUTOR", "personalidade": "age no terminal: comandos, arquivos, instalações, testes reais"},
        {"nome": "REVISOR", "personalidade": "verifica cada passo, procura erros, valida resultados e alerta riscos"},
    ]
    print("🧠 Modo EQUIPE — NEXUS agora debate com ANALISTA e EXECUTOR antes de agir.")
    while True:
        try:
            pergunta = input("equipe> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not pergunta: continue
        if pergunta.lower() in ("quit", "exit", "/solo"): break
        if pergunta.startswith("/"):
            print("comandos: /solo /quit")
            continue
        try:
            final = team_brain.roda_debate(
                "NEXUS", membros,
                lambda nome, msgs: call_ai(msgs[0]["content"], msgs[-1]["content"], cfg),
                pergunta, max_rodadas=3,
            )
            print("\n🧠 DECISÃO DA EQUIPE:")
            print(final)
            print()
        except Exception as e:
            print(f"[erro no time: {e}]")

# ─── Tool Execution ───────────────────────────────────────────────────────

TOOL_DEFINITIONS = {
    "execute": {
        "desc": "Run a shell command",
        "args": {"command": "string (the command to run)", "timeout": "int (seconds, default 60)"},
    },
    "execute_python": {
        "desc": "Run Python code and return output",
        "args": {"code": "string (Python code to execute)"},
    },
    "write_file": {
        "desc": "Create or overwrite a file",
        "args": {"path": "string", "content": "string"},
    },
    "read_file": {
        "desc": "Read file contents",
        "args": {"path": "string", "max_lines": "int (default 100)"},
    },
    "append_file": {
        "desc": "Append content to a file",
        "args": {"path": "string", "content": "string"},
    },
    "edit_file": {
        "desc": "Make a targeted edit in a file (find and replace)",
        "args": {"path": "string", "old": "string (text to find)", "new": "string (replacement text)"},
    },
    "read_dir": {
        "desc": "List directory contents",
        "args": {"path": "string (default '.')"},
    },
    "search_files": {
        "desc": "Find files matching a pattern (glob)",
        "args": {"pattern": "string (e.g. '**/*.py')", "path": "string (default cwd)"},
    },
    "grep": {
        "desc": "Search for text in files",
        "args": {"pattern": "string (regex)", "path": "string (default cwd)", "include": "string (e.g. '*.py')"},
    },
    "fetch_url": {
        "desc": "Fetch content from a URL",
        "args": {"url": "string"},
    },
    "web_search": {
        "desc": "Search the internet",
        "args": {"query": "string"},
    },
    "install_package": {
        "desc": "Install a system package",
        "args": {"name": "string"},
    },
    "think": {
        "desc": "Internal reasoning step",
        "args": {"thought": "string"},
    },
    "ask": {
        "desc": "Ask the user for input",
        "args": {"question": "string"},
    },
    "plan": {
        "desc": "Create a structured plan before starting",
        "args": {"steps": "array of strings"},
    },
    "verify": {
        "desc": "Verify that requirements are met",
        "args": {"checks": "array of strings describing what to verify"},
    },
    "finalize": {
        "desc": "Mark the goal as complete",
        "args": {"summary": "string", "output": "string (results)"},
    },
}

def build_system_prompt(env):
    tools_text = ""
    for name, t in TOOL_DEFINITIONS.items():
        args_text = ", ".join(f"{k}: {v}" for k, v in t["args"].items())
        tools_text += f"  - {name}: {t['desc']} | args: {{{args_text}}}\n"

    return f"""You are NEXUS, an elite autonomous terminal agent. You adapt to any environment and complete goals intelligently.

ENVIRONMENT:
{json.dumps(env, indent=2)}

TOOLS:
{tools_text}
RULES:
1. Think step by step. Break complex goals into small actions.
2. Use "plan" first for multi-step goals to create a roadmap.
3. Use "think" to reason before acting.
4. If a command fails, try an alternative approach.
5. Use "ask" if you need user input or clarification.
6. Use "verify" to check your work before finishing.
7. Use "finalize" ONLY when the goal is 100% complete.
8. Use "execute" for shell commands, "execute_python" for Python snippets.
9. Use "web_search" or "fetch_url" to gather information when needed.
10. You can install packages with "install_package" if needed.

OUTPUT FORMAT:
Respond with EXACTLY ONE tool call per message in JSON format:
```json
{{"tool": "tool_name", "args": {{...}}}}
```"""

def parse_tool(text):
    # Try json block
    m = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(1).strip())
        except: pass
    # Try bare json
    try: return json.loads(text.strip())
    except: pass
    # Try to find {...} block
    m = re.search(r'\{[^{}]*"tool"[^{}]*\}', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(0))
        except: pass
    return None

def run_tool(tool_name, args, env, cfg):
    result = ""
    try:
        if tool_name == "execute":
            cmd = args.get("command", "")
            timeout = args.get("timeout", 60)
            is_termux = env.get("is_termux", False)
            dangerous = any(x in cmd for x in ["rm -rf /", "dd if=", "mkfs.", "format ", "> /dev/sd"])
            if cfg["safe_mode"] and dangerous and not is_termux:
                return f"[BLOCKED by safe mode: potentially destructive command]"
            try:
                proc = subprocess.run(cmd, shell=True, cwd=env["cwd"], capture_output=True, text=True, timeout=timeout)
                out = proc.stdout or ""
                err = proc.stderr or ""
                result = out[:8000]
                if err: result += f"\n[STDERR]\n{err[:2000]}"
                if proc.returncode != 0: result += f"\n[EXIT: {proc.returncode}]"
                if not result.strip(): result = "(command produced no output)"
            except subprocess.TimeoutExpired:
                result = "[TIMEOUT]"
            except Exception as e:
                result = f"[ERROR: {e}]"

        elif tool_name == "execute_python":
            code = args.get("code", "")
            try:
                local_vars = {"env": env}
                exec(code, local_vars)
                result = local_vars.get("_result", str(local_vars))
            except Exception as e:
                result = f"[PYTHON ERROR: {e}]\n{traceback.format_exc()[:1000]}"

        elif tool_name == "write_file":
            path = os.path.join(env["cwd"], args.get("path", ""))
            content = args.get("content", "")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            result = f"Written {len(content)} bytes to {path}"

        elif tool_name == "read_file":
            path = args.get("path", "")
            if not os.path.isabs(path): path = os.path.join(env["cwd"], path)
            max_lines = args.get("max_lines", 100)
            if os.path.exists(path):
                with open(path) as f:
                    lines = f.readlines()
                result = "".join(lines[:max_lines])
                if len(lines) > max_lines: result += f"\n... ({len(lines) - max_lines} more lines)"
            else:
                result = f"[NOT FOUND: {path}]"

        elif tool_name == "append_file":
            path = args.get("path", "")
            if not os.path.isabs(path): path = os.path.join(env["cwd"], path)
            content = args.get("content", "")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a") as f:
                f.write(content)
            result = f"Appended {len(content)} bytes to {path}"

        elif tool_name == "edit_file":
            path = args.get("path", "")
            if not os.path.isabs(path): path = os.path.join(env["cwd"], path)
            old, new = args.get("old", ""), args.get("new", "")
            if os.path.exists(path):
                with open(path) as f:
                    content = f.read()
                if old in content:
                    content = content.replace(old, new)
                    with open(path, "w") as f:
                        f.write(content)
                    result = f"Replaced '{old[:50]}' -> '{new[:50]}' in {path}"
                else:
                    result = f"[NOT FOUND: '{old[:50]}' not in file]"
            else:
                result = f"[NOT FOUND: {path}]"

        elif tool_name == "read_dir":
            path = args.get("path", ".")
            if not os.path.isabs(path): path = os.path.join(env["cwd"], path)
            try:
                items = os.listdir(path)
                result = "\n".join(sorted(items)[:100])
            except Exception as e:
                result = f"[ERROR: {e}]"

        elif tool_name == "search_files":
            pattern = args.get("pattern", "")
            spath = args.get("path", env["cwd"])
            try:
                import glob as glob_mod
                matches = glob_mod.glob(pattern, root_dir=spath, recursive=True) if hasattr(glob_mod, "glob") else []
                if not matches:
                    result = subprocess.run(f"find . -name '{pattern}' 2>/dev/null | head -50", shell=True, cwd=spath, capture_output=True, text=True, timeout=10).stdout or "(no matches)"
                else:
                    result = "\n".join(matches[:50])
            except:
                result = subprocess.run(f"find . -name '{pattern}' 2>/dev/null | head -50", shell=True, cwd=spath, capture_output=True, text=True, timeout=10).stdout or "(no matches)"

        elif tool_name == "grep":
            pattern = args.get("pattern", "")
            spath = args.get("path", env["cwd"])
            include = args.get("include", "")
            cmd = f"grep -rn '{pattern}' {spath} 2>/dev/null | head -50"
            if include: cmd = f"grep -rn --include='{include}' '{pattern}' {spath} 2>/dev/null | head -50"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10).stdout or "(no matches)"

        elif tool_name == "fetch_url":
            url = args.get("url", "")
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                    content = resp.read().decode("utf-8", errors="replace")
                    # Strip HTML tags for cleaner output
                    content = re.sub(r'<[^>]+>', ' ', content)
                    content = re.sub(r'\s+', ' ', content).strip()
                    result = content[:5000]
            except Exception as e:
                result = f"[FETCH ERROR: {e}]"

        elif tool_name == "web_search":
            query = args.get("query", "")
            if not cfg.get("web_search_enabled", True):
                result = "[Web search disabled in config]"
            else:
                try:
                    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
                        html = resp.read().decode("utf-8", errors="replace")
                    # Extract result snippets
                    snippets = re.findall(r'class="result__snippet">(.*?)</(?:a|span|div)', html, re.DOTALL)
                    links = re.findall(r'class="result__url"[^>]*>(.*?)</a>', html, re.DOTALL)
                    titles = re.findall(r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL)
                    results = []
                    for i in range(min(len(snippets), 10)):
                        title = titles[i] if i < len(titles) else ""
                        link = links[i] if i < len(links) else ""
                        snip = re.sub(r'<[^>]+>', '', snippets[i]).strip()
                        results.append(f"{i+1}. {re.sub(r'<[^>]+>', '', title).strip()}\n   {snip[:200]}")
                    result = "\n\n".join(results) if results else "(no results)"
                except Exception as e:
                    result = f"[SEARCH ERROR: {e}]"

        elif tool_name == "install_package":
            name = args.get("name", "")
            pm = env.get("pkg_mgr", "apt")
            if pm == "pkg":
                cmd = f"pkg install -y {name}"
            elif pm == "apt":
                cmd = f"apt-get install -y {name} 2>/dev/null || apt install -y {name}"
            elif pm == "apk":
                cmd = f"apk add {name}"
            elif pm == "pacman":
                cmd = f"pacman -S --noconfirm {name}"
            elif pm == "brew":
                cmd = f"brew install {name}"
            else:
                cmd = f"apt-get install -y {name} || pkg install -y {name} || apk add {name}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            result = (result.stdout or "")[:1000] + (result.stderr or "")[:500]

        elif tool_name == "think":
            result = f"[THOUGHT] {args.get('thought', '')}"

        elif tool_name == "ask":
            print(f"\n[ASK] {args.get('question', '')}")
            try:
                answer = input("> ").strip()
            except:
                answer = ""
            result = f"[USER ANSWER] {answer}"

        elif tool_name == "plan":
            steps = args.get("steps", [])
            result = f"[PLAN]\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))

        elif tool_name == "verify":
            checks = args.get("checks", [])
            results = []
            for check in checks:
                r = subprocess.run(check, shell=True, capture_output=True, text=True, timeout=10)
                status = "OK" if r.returncode == 0 else "FAIL"
                results.append(f"  [{status}] {check}")
            result = "[VERIFY]\n" + "\n".join(results)

        elif tool_name == "finalize":
            return ("__COMPLETE__", args.get("summary", "Done"), args.get("output", ""))

        else:
            result = f"[UNKNOWN TOOL: {tool_name}]"

    except Exception as e:
        result = f"[TOOL ERROR: {e}]"

    return result

# ─── Main Agent Loop ──────────────────────────────────────────────────────

def agent_loop(goal, cfg):
    env = detect_environment()
    system_prompt = build_system_prompt(env)
    history = []
    step = 1
    max_steps = cfg["max_iterations"]
    complete = False
    summary = ""
    output = ""

    print(f"\n{'='*60}")
    print(f"  NEXUS Autonomous Agent")
    print(f"  OS: {env['os']} | Arch: {env['arch']}")
    print(f"  Model: {cfg['model']}")
    print(f"  Goal: {goal}")
    print(f"{'='*60}\n")

    while step <= max_steps and not complete:
        # Build context
        context = f"GOAL: {goal}\n\nYou are on step {step}/{max_steps}.\n\n"
        if history:
            context += "RECENT HISTORY:\n" + "\n".join(history[-8:]) + "\n\n"

        context += "What is your next action? Respond with a single JSON tool call."

        print(f"[Step {step}] ", end="", flush=True)
        response = call_ai(system_prompt, context, cfg)

        if not response or response.startswith("[API ERROR"):
            print(f"API error: {response}")
            if step > 1:
                print("Retrying with simpler prompt...")
                response = call_ai(system_prompt, f"GOAL: {goal}\nStep {step}. What next?\nRespond with a single JSON tool call.", cfg)
                if not response or response.startswith("[API ERROR"):
                    break
            else:
                break

        parsed = parse_tool(response)
        if not parsed:
            print(f"Couldn't parse. Raw response:")
            print(response[:300])
            history.append(f"Step {step}: [PARSE ERROR]")
            step += 1
            continue

        tool = parsed.get("tool", "")
        args = parsed.get("args", {})

        print(f"{tool} {str(args)[:80]}")

        result = run_tool(tool, args, env, cfg)

        if isinstance(result, tuple) and result[0] == "__COMPLETE__":
            complete = True
            summary = result[1]
            output = result[2]
            print(f"\n✓ {summary}")
            if output: print(f"  {output[:500]}")
            break

        result_str = str(result)[:500]
        print(f"  → {result_str[:200]}")

        history.append(f"Step {step}: [{tool}] {result_str[:150]}")

        # Store in memory
        mem = load_memory()
        mem["learned"][f"tool_{tool}_count"] = mem["learned"].get(f"tool_{tool}_count", 0) + 1
        save_memory(mem)

        step += 1

    if not complete:
        print(f"\n[Stopped after {step-1} steps without completion]")

    log_session(goal, step-1, "complete" if complete else "incomplete")
    return complete, summary, output, step-1

# ─── Config / CLI ─────────────────────────────────────────────────────────

def config_mode():
    cfg = load_config()
    print("=== NEXUS Configuration ===")
    prov = input(f"Provider (gemini/openai) [{cfg['provider']}]: ").strip() or cfg["provider"]
    cfg["provider"] = prov
    if prov == "gemini":
        cfg["model"] = input(f"Model [{cfg['model']}]: ").strip() or cfg["model"]
    else:
        cfg["api_url"] = input(f"API URL: ").strip() or cfg.get("api_url", "https://api.openai.com/v1/chat/completions")
        cfg["model"] = input(f"Model [{cfg['model']}]: ").strip() or cfg["model"]
    pwd = input("API Key: ").strip()
    if pwd: cfg["api_key"] = pwd
    sm = input(f"Safe mode (y/n) [{'y' if cfg['safe_mode'] else 'n'}]: ").strip().lower()
    if sm: cfg["safe_mode"] = sm == "y"
    ws = input(f"Web search (y/n) [{'y' if cfg['web_search_enabled'] else 'n'}]: ").strip().lower()
    if ws: cfg["web_search_enabled"] = ws == "y"
    save_config(cfg)
    print("Configuration saved.")

def show_env():
    env = detect_environment()
    print(f"\n{'='*50}")
    print("ENVIRONMENT REPORT")
    print(f"{'='*50}")
    for k, v in env.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for sk, sv in v.items():
                print(f"    {sk}: {sv}")
        else:
            print(f"  {k}: {v}")
    print()

def show_memory():
    mem = load_memory()
    print(f"\nSessions: {len(mem['sessions'])}")
    print(f"Learned patterns: {len(mem['learned'])}")
    for k, v in sorted(mem['learned'].items()):
        print(f"  {k}: {v}")

def main():
    cfg = load_config()

    if "--config" in sys.argv: config_mode(); return
    if "--env" in sys.argv: show_env(); return
    if "--memory" in sys.argv: show_memory(); return
    if "--team" in sys.argv:
        if not cfg.get("api_key"):
            print("No API key. Run: nexus --config")
            sys.exit(1)
        team_mode(cfg); return
    if "--reset" in sys.argv:
        for f in [MEMORY_FILE, LOG_FILE]:
            if os.path.exists(f): os.remove(f)
        print("Memory reset."); return

    if not cfg.get("api_key"):
        print("No API key. Run: nexus --config")
        sys.exit(1)

    print("NEXUS - Autonomous Terminal Agent")
    print("Commands: /env /config /memory /quit")
    print("Type a goal to begin.\n")

    while True:
        try:
            goal = input("goal> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not goal: continue
        if goal.lower() in ("quit", "exit"): break
        if goal == "/env": show_env(); continue
        if goal == "/config": config_mode(); cfg = load_config(); continue
        if goal == "/memory": show_memory(); continue

        complete, summary, output, steps = agent_loop(goal, cfg)
        print(f"\n[Result] Steps: {steps} | Complete: {complete}")
        if summary: print(f"[Summary] {summary}")
        print()

if __name__ == "__main__":
    main()
