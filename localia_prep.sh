#!/bin/bash
# LOCALIA --prep: roda no TERMUX REAL (fora do proot)
# Uso: bash localia_prep.sh
set -u

AQUI="$(cd "$(dirname "$0")" && pwd)"
LOG="localia_prep.log"

log() { echo -e "$*"; echo -e "$*" >> "$LOG"; }

log "== LOCALIA preparação do pendrive =="
log "quando: $(date)"

# 1. detectar o pendrive
PEN=""
for p in /storage/[0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z]-[0-9A-Z][0-9A-Z][0-9A-Z][0-9A-Z] /mnt/media_rw/* /storage/usb*; do
    [ -d "$p" ] && PEN="$p" && break
done
if [ -z "$PEN" ]; then
    log "ERRO: pendrive não detectado. Conecte o pen e dê permissão de armazenamento ao Termux (termux-setup-storage)."
    exit 1
fi
log "pendrive detectado: $PEN"

# 2. verificar escrita
T="$PEN/.teste_escrita_$$"
if ! touch "$T" 2>/dev/null; then
    log "ERRO: sem permissão de escrita em $PEN"
    exit 1
fi
rm -f "$T"
log "escrita OK"

# 3. estrutura LOCALIA
mkdir -p "$PEN/LOCALIA/models" "$PEN/LOCALIA/conhecimento" "$PEN/LOCALIA/memoria" "$PEN/LOCALIA/area_de_trabalho"
[ -f "$PEN/LOCALIA/memoria/perfil.txt" ] || echo "" > "$PEN/LOCALIA/memoria/perfil.txt"
[ -f "$PEN/LOCALIA/memoria/historico.json" ] || echo "[]" > "$PEN/LOCALIA/memoria/historico.json"
[ -f "$PEN/LOCALIA/.localia_mark" ] || echo "pendrive oficial do LOCALIA" > "$PEN/LOCALIA/.localia_mark"
log "estrutura criada:"
ls -la "$PEN/LOCALIA/"

# 4. copiar script e modelo (se existirem localmente)
SCRIPT_SRC="$AQUI/localia.py"
if [ -f "$SCRIPT_SRC" ]; then
    cp "$SCRIPT_SRC" "$PEN/LOCALIA/localia.py" && log "localia.py copiado p/ o pen"
fi

for m in "$AQUI"/qwen-0.5b-q4.gguf "$AQUI"/qwen-1.5b-q4.gguf /root/qwen-0.5b-q4.gguf /root/ai_local/models/qwen-1.5b-q4.gguf; do
    if [ -f "$m" ] && [ ! -f "$PEN/LOCALIA/models/$(basename "$m")" ]; then
        log "copiando modelo $(basename "$m") ... (pode demorar)"
        cp "$m" "$PEN/LOCALIA/models/" && log "  -> modelo $(basename "$m") OK ($(du -h "$m" | cut -f1))"
    fi
done

# 5. resumo
log ""
log "== PRONTO =="
log "pen: $PEN/LOCALIA"
ls -la "$PEN/LOCALIA/models/" 2>/dev/null | grep gguf || log "ATENÇÃO: nenhum modelo no pen ainda. Baixe um GGUF e copie pra $PEN/LOCALIA/models/"
log ""
log "Para iniciar a IA (com o pen conectado):"
log "  cd ~/LOCALIA && python3 localia.py"
log "(detalhes no log: $LOG)"
