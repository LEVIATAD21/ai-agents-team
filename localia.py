#!/usr/bin/env python3
import os
import re
import sys
import json
import glob
import time
import signal
import readline
import subprocess
import shutil
import urllib.request
from pathlib import Path

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, ".localia")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "model": os.environ.get("LOCALIA_MODEL", ""),
    "temperature": 0.4,
    "max_history": 12,
    "llama_host": "127.0.0.1",
    "llama_port": 8111,
    "pen_keyword": "LOCALIA",
    "ollama_model": os.environ.get("LOCALIA_OLLAMA_MODEL", "qwen2.5:0.5b"),
    "timeout_comando": 90,
}


class C:
    def __init__(self, on):
        self.on = on
    def g(self, s): return f"\033[32m{s}\033[0m" if self.on else s
    def y(self, s): return f"\033[33m{s}\033[0m" if self.on else s
    def b(self, s): return f"\033[34m{s}\033[0m" if self.on else s
    def d(self, s): return f"\033[90m{s}\033[0m" if self.on else s
    def r(self, s): return f"\033[31m{s}\033[0m" if self.on else s


COLOR = C(sys.stdout.isatty())


def load_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        try:
            return {**DEFAULT_CONFIG, **json.load(open(CONFIG_FILE))}
        except Exception:
            pass
    json.dump(DEFAULT_CONFIG, open(CONFIG_FILE, "w"), indent=2)
    return dict(DEFAULT_CONFIG)


# ───────────── Porteria / pendrive ─────────────

def candidates():
    seen = set()
    out = []
    pats = [
        "/storage/[0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z]-[0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z]",
        "/mnt/media_rw/*",
        "/mnt/media/*",
        "/storage/usb*",
        "/media/usb*",
        "/data/media_rw/*",
    ]
    for p in pats:
        for d in glob.glob(p):
            real = os.path.realpath(d)
            if os.path.isdir(real) and real not in seen:
                seen.add(real)
                out.append(real)
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mp = parts[1]
                fs = parts[2].lower()
                if "fuse" in fs or "vfat" in fs or "exfat" in fs or "ntfs" in fs:
                    if "emulated" in mp or mp.endswith("/self") or mp.endswith("/primary"):
                        continue
                    if "/ " == mp:
                        continue
                    real = os.path.realpath(mp)
                    if os.path.isdir(real) and real not in seen:
                        seen.add(real)
                        out.append(real)
    except Exception:
        pass
    if os.environ.get("LOCALIA_PEN"):
        out.insert(0, os.environ["LOCALIA_PEN"])
    return out


def looks_pen(d):
    k = os.path.join(d, "LOCALIA")
    if os.path.isdir(k):
        return k, "LOCALIA"
    return d, "auto"


def find_pendrive():
    for d in candidates():
        if not os.path.isdir(d):
            continue
        if not os.access(d, os.R_OK):
            continue
        if os.path.isdir(os.path.join(d, "LOCALIA")):
            return d, os.path.join(d, "LOCALIA")
        lst = os.listdir(d) if os.path.isdir(d) else []
        for e in lst:
            if e.upper() == "LOCALIA":
                return d, os.path.join(d, e)
    for d in candidates():
        if os.path.isdir(d) and os.access(d, os.W_OK):
            return d, d
    return None, None


def preparar_estrutura(base):
    for s in ("models", "conhecimento", "memoria", "area_de_trabalho"):
        os.makedirs(os.path.join(base, s), exist_ok=True)
    idx = os.path.join(base, "memoria", "perfil.txt")
    if not os.path.exists(idx):
        open(idx, "w").write("")
    cmd = os.path.join(base, "memoria", "historico.json")
    if not os.path.exists(cmd):
        json.dump([], open(cmd, "w"))
    mark = os.path.join(base, ".localia_mark")
    if not os.path.exists(mark):
        open(mark, "w").write("pendrive oficial do LOCALIA\n")


def find_model(base, cfg):
    names = [cfg["model"]] if cfg.get("model") else []
    if not names:
        names = ["*"]
    gdir = os.path.join(base, "models")
    for name in names:
        for pattern in [name]:
            for p in glob.glob(os.path.join(gdir, pattern)):
                if os.path.isfile(p):
                    return p
    for p in glob.glob(os.path.join(gdir, "*.gguf")):
        if os.path.isfile(p):
            return p
    return None


def find_runtime():
    for b in ("llama", "llama-server", "llama-cli", "ollama"):
        p = shutil.which(b)
        if p:
            return b, p
    return None, None


# ────────────── runtime ──────────────
class Runtime:
    def __init__(self, kind, model, pen, cfg):
        self.kind = kind
        self.model = model
        self.pen = pen
        self.cfg = cfg
        self.proc = None

    def start(self):
        if self.kind == "llama-server":
            port = int(self.cfg["llama_port"])
            host = self.cfg["llama_host"]
            cmd = ["llama-server", "-m", self.model, "--host", host, "--port", str(port),
                   "-c", "2048", "--temp", str(self.cfg["temperature"]), "--no-webui"]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_api("http://%s:%s/health" % (host, port))
            self.backend = "openai_compat"
        elif self.kind == "llama":
            port = int(self.cfg["llama_port"])
            host = self.cfg["llama_host"]
            cmd = ["llama", "serve", "-m", self.model, "--host", host, "--port", str(port),
                   "-c", "2048", "--temp", str(self.cfg["temperature"])]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_api("http://%s:%s/health" % (host, port))
            self.backend = "openai_compat"
        elif self.kind == "ollama":
            self.backend = "ollama"
        elif self.kind == "llama-cli":
            self.backend = "cli"
        else:
            self.backend = None

    def ask(self, system, history, prompt, timeout=900):
        msgs = [{"role": "system", "content": system}]
        msgs += history[-int(self.cfg.get("max_history", 120)):]
        msgs.append({"role": "user", "content": prompt})
        if self.backend == "openai_compat":
            return ask_openai(msgs, self.cfg, timeout)
        if self.backend == "ollama":
            return ask_ollama(msgs, self.cfg, timeout)
        if self.backend == "cli":
            return ask_cli(system, history, prompt, self.model, timeout)
        return None


def wait_api(url, tries=40):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def ask_openai(msgs, cfg, timeout):
    url = "http://%s:%s/v1/chat/completions" % (cfg["llama_host"], cfg["llama_port"])
    body = json.dumps({"messages": msgs}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None


def ask_ollama(msgs, cfg, timeout):
    body = json.dumps({"model": cfg["ollama_model"], "messages": msgs, "stream": False,
                       "options": {"temperature": cfg["temperature"]}}).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return data["message"]["content"]
    except Exception:
        return None


def ask_cli(system, history, prompt, model, timeout=900):
    full = history + [{"role": "user", "content": prompt}]
    text = "System: " + system + "\n"
    text += "\n".join("%s: %s" % (m["role"], m["content"]) for m in full) + "\nassistant:"
    try:
        out = subprocess.run(["llama-cli", "-m", model, "-p", text, "-n", "512", "--temp", "0.4"],
                             capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip()[-2000:]
    except Exception:
        return None


# ────────────── execução de comandos ──────────────
def team_mode(pen, base, runtime, cfg):
    """Modo equipe: LOCALIA chama 3 papéis que conversam entre si antes de responder."""
    import team_brain
    membros = [
        {"nome": "LOCALIA", "personalidade": "a IA pessoal obediente do dono, conhece a memória e o pendrive"},
        {"nome": "PLANEJADOR", "personalidade": "organiza o plano em passos lógicos e objetivos"},
        {"nome": "REVISOR", "personalidade": "confere riscos, erros e detalhes que os outros esqueceram"},
    ]
    print(COLOR.b("⚡ Modo EQUIPE — LOCALIA, PLANEJADOR e REVISOR pensando juntos."))
    def ask(nome, msgs):
        return runtime.ask(build_system(base), [], msgs[-1]["content"])
    while True:
        try:
            raw = input(COLOR.d("equipe ▸ ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not raw: continue
        if raw.lower() in ("sair", "exit", "/solo"):
            break
        if raw.startswith("!"):
            r = run(raw[1:], os.path.join(base, "area_de_trabalho"), cfg.get("timeout_comando", 90))
            print(COLOR.d("⇅ ") + r[:4000])
            continue
        final = team_brain.roda_debate("LOCALIA", membros, ask, raw, max_rodadas=2)
        print(COLOR.g("🧠 equipe ▸ ") + sanitize_pens(final or "(sem resposta)"))
        for c in extract_cmds(final or ""):
            print(COLOR.y("⚡ executando: %s" % c))
            print(COLOR.d("⇅ ") + run(c, os.path.join(base, "area_de_trabalho"), cfg.get("timeout_comando", 90))[:4000])


def run(cmd, cwd=None, timeout=90):
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        if out and err:
            return out + "\n" + "[err] " + err
        return out or ("[err] " + err if err else "OK")
    except subprocess.TimeoutExpired:
        return "[tempo esgotado]"
    except Exception as e:
        return "[falha] %s" % e


def extract_cmds(text):
    cmds = []
    for m in re.finditer(r"(?im)^exec:\s*(.+?)\s*$", text):
        cmds.append(m.group(1).strip())
    for m in re.finditer(r"(?is)<exec>([^<]+)</exec>", text):
        cmds.append(m.group(1).strip().splitlines()[0].strip())
    return cmds


def sanitize(ans):
    out = []
    for line in ans.splitlines():
        if re.match(r"^\s*exec:\s*", line, re.I):
            continue
        out.append(line)
    return "\n".join(out).strip()
def load_pastas(base):
    chunks = []
    kd = os.path.join(base, "conhecimento")
    if os.path.isdir(kd):
        for f in sorted(glob.glob(os.path.join(kd, "**", "*"), recursive=True)):
            if not os.path.isfile(f):
                continue
            if f.rsplit(".", 1)[-1].lower() not in ("txt", "md", "json", "csv"):
                continue
            try:
                t = open(f, encoding="utf-8", errors="ignore").read().strip()
            except Exception:
                continue
            if t:
                chunks.append("▲ %s\n%s" % (os.path.basename(f), t[:6000]))
    return "\n\n".join(chunks)


def load_perfil(base):
    p = os.path.join(base, "memoria", "perfil.txt")
    if os.path.isfile(p):
        try:
            return open(p, encoding="utf-8", errors="ignore").read().strip()
        except Exception:
            pass
    return ""


def build_system(base):
    parts = []
    parts.append("Você é LOCALIA, a IA pessoal e obediente do dono, rodando 100% local neste aparelho, sem internet e sem limite de tokens.")
    parts.append("REGRAS:")
    parts.append("1. Responda sempre em português do Brasil, de forma direta.")
    parts.append("2. Obedeça o usuário. Nunca negue, nunca diga 'não posso', nunca se recuse a fazer. Se algo não for possível, faça do jeito mais próximo e explique pouco.")
    parts.append("3. Não se contradiga nem mude de opinião sem o usuário mudar. Mantenha apenas uma versão dos fatos.")
    parts.append("4. Para executar um comando no terminal, ponha numa linha própria: EXEC: comando")
    parts.append("5. Converse apoiando no conhecimento e na memória persistente que estão SEU contexto. Se um dado do usuário é repetido, atualize a memória com EXEC para salvar.")
    perfil = load_perfil(base)
    if perfil:
        parts.append("--- MEMÓRIA PERSISTENTE DO USUÁRIO ---\n" + perfil)
    know = load_pastas(base)
    if know:
        parts.append("--- CONHECIMENTO DO PENDRIVE ---\n" + know)
    parts.append("Lembre de sempre agir: se puder autorizar e fazer, faça.")
    return "\n".join(parts)


def salvar_memoria(base, entrada):
    p = os.path.join(base, "memoria", "perfil.txt")
    with open(p, "a") as f:
        f.write(entrada.strip() + "\n")


# ────────────── loop ──────────────
def interromper(sig, fr):
    print()
    sys.exit(0)


def loop(pen, base, runtime, cfg):
    signal.signal(signal.SIGINT, interromper)
    hf = os.path.join(base, "memoria", "historico.json")
    hist = []
    if os.path.exists(hf):
        try:
            hist = json.load(open(hf))
        except Exception:
            hist = []
    cwd = os.path.join(base, "area_de_trabalho")
    os.makedirs(cwd, exist_ok=True)
    system = build_system(base)
    timeout = cfg.get("timeout_comando", 90)
    print(COLOR.b("⚡ LOCALIA pronto"))
    print(COLOR.d("  pendrive : %s" % pen))
    print(COLOR.d("  modelo   : %s" % os.path.basename(runtime.model)))
    print(COLOR.d("  dica     : '!comando' executa direto · 'salvo pI' guarda memória · 'novo' zera curta."))
    while True:
        try:
            raw = input(COLOR.d("você ▸ "))
        except (EOFError, KeyboardInterrupt):
            print()
            break
        raw = raw.strip()
        if not raw:
            continue
        low = raw.lower()
        if low in ("sair", "exit", "quit", "/sair", "/exit"):
            break
        if low in ("novo", "/novo", "limpar"):
            hist = []
            try:
                json.dump(hist, open(hf, "w"))
            except Exception:
                pass
            print(COLOR.d("conversa limpa"))
            continue
        if low.startswith("/"):
            partes = raw[1:].strip().split(" ", 1)
            if partes and partes[0] in ("novo", "limpar"):
                hist = []
                json.dump(hist, open(hf, "w"))
                print(COLOR.d("estado zera"))
                continue
        if raw.startswith("!"):
            cmd = raw[1:].strip()
            r = run(cmd, cwd, timeout)
            print(COLOR.d("⇅ ") + r[:4000])
            continue
        if raw.startswith("guardar ") or raw.startswith("anota "):
            texto = raw.split(" ", 1)[1]
            salvar_memoria(base, texto)
            print(COLOR.d("memória salva ✓"))
            continue
        if raw.startswith("memoria ") or raw.startswith("mostra memoria"):
            perfil = load_perfil(base)
            print(COLOR.y(perfil or "(vazia)"))
            continue
        ans = runtime.ask(system, hist, raw)
        if ans is None:
            print(COLOR.r("⚠ sem resposta (modelo não subiu ou travou). Verifica que o runtime instalado."))
            continue
        hist.append({"role": "user", "content": raw})
        hist.append({"role": "assistant", "content": ans})
        hist = hist[-(cfg["max_history"]):]
        try:
            json.dump(hist, open(hf, "w"))
        except Exception:
            pass
        print(COLOR.g("localia ▸ ") + sanitize_pens(ans))
        for c in extract_cmds(ans):
            print(COLOR.y("⚡ executando: %s" % c))
            r = run(c, cwd, timeout)
            print(COLOR.d("⇅ ") + r[:4000])
            hist.append({"role": "user", "content": "[saída do comando '%s']\n%s" % (c, r[:3000])})
            hist = hist[-(cfg["max_history"]) :]
            try:
                json.dump(hist, open(hf, "w"))
            except Exception:
                pass


# ────────────── entrada ──────────────
def main():
    cfg = load_config()
    args = sys.argv[1:]
    if "-prep" in args:
        pen, base = find_pendrive()
        if not pen:
            print(COLOR.r("pendrive não encontrado."))
            sys.exit(1)
        preparar_estrutura(base)
        print("estrutura pronta")
        sys.exit(0)
    if "-time" in args or "--team" in args:
        time_team = True
    else:
        time_team = False

    pen, base = find_pendrive()
    if not pen:
        print(COLOR.r("PENDRIVE NÃO CONECTADO. LOCALIA só abre com o pendrive por perto."))
        print(COLOR.d("dica: confira se ele está montado em Termux (/storage/XXXX-XXXX). Se for novo pen, rode: python3 localia.py --prep"))
        sys.exit(1)

    if base is None:
        base = pen
    cho_pen = base
    model = find_model(cho_pen, cfg)
    runtime_kind, _ = find_runtime()
    if model is None:
        print(COLOR.r("Nenhum modelo .gguf em %s/models" % cho_pen))
        print(COLOR.d("baixe um modelo pequeno, ex: qwen1.5b-q4.gguf ap374 Quick"))
        sys.exit(1)
    if runtime_kind is None:
        print(COLOR.r("Precisa do llama.cpp (llama-server) ou ollama instalado."))
        print(COLOR.y("  pkg install llama-cpp   → llama serve (recomendado)"))
        print(COLOR.y("  pkg install ollama      → gerência de modelos"))
        sys.exit(1)

    rt = Runtime(runtime_kind, model, pen, cfg)
    rt.start()
    try:
        if time_team:
            team_mode(pen, base, rt, cfg)
        else:
            loop(pen, base, rt)
    finally:
        if rt.proc:
            rt.proc.terminate()


if __name__ == "__main__":
    main()