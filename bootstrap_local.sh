#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"

SKIP_APT=0
SKIP_OLLAMA=0
SKIP_MODEL=0

for arg in "$@"; do
  case "$arg" in
    --skip-apt) SKIP_APT=1 ;;
    --skip-ollama) SKIP_OLLAMA=1 ;;
    --skip-model) SKIP_MODEL=1 ;;
    *)
      echo "Argomento non riconosciuto: $arg" >&2
      echo "Uso: bash bootstrap_local.sh [--skip-apt] [--skip-ollama] [--skip-model]" >&2
      exit 1
      ;;
  esac
done

log() {
  printf '\n[%s] %s\n' "bootstrap" "$1"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Comando richiesto non trovato: $1" >&2
    exit 1
  fi
}

install_system_packages() {
  if [[ "$SKIP_APT" -eq 1 ]]; then
    log "Salto installazione pacchetti di sistema (--skip-apt)."
    return
  fi

  require_command sudo
  require_command apt-get

  log "Aggiorno apt e installo dipendenze di sistema per OCR e bootstrap."
  sudo apt-get update
  sudo apt-get install -y \
    python3-venv \
    python3-pip \
    curl \
    tesseract-ocr \
    tesseract-ocr-ita \
    poppler-utils \
    mupdf-tools
}

ensure_venv() {
  require_command "$PYTHON_BIN"
  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creo il virtualenv in $VENV_DIR."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
}

install_python_dependencies() {
  log "Aggiorno pip nel virtualenv."
  "$VENV_DIR/bin/python" -m pip install --upgrade pip

  log "Installo torch CPU-only."
  "$VENV_DIR/bin/pip" install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

  log "Installo le dipendenze Python del progetto."
  "$VENV_DIR/bin/pip" install -r "$ROOT_DIR/requirements.txt"
}

install_ollama() {
  if [[ "$SKIP_OLLAMA" -eq 1 ]]; then
    log "Salto installazione Ollama (--skip-ollama)."
    return
  fi

  if ! command -v ollama >/dev/null 2>&1; then
    require_command curl
    log "Installo Ollama."
    curl -fsSL https://ollama.com/install.sh | sh
  else
    log "Ollama gia' presente."
  fi

  if command -v systemctl >/dev/null 2>&1; then
    log "Provo ad avviare il servizio Ollama."
    sudo systemctl enable ollama >/dev/null 2>&1 || true
    sudo systemctl start ollama >/dev/null 2>&1 || true
  fi

  if [[ "$SKIP_MODEL" -eq 1 ]]; then
    log "Salto pull del modello Ollama (--skip-model)."
    return
  fi

  log "Scarico il modello Ollama $OLLAMA_MODEL."
  ollama pull "$OLLAMA_MODEL"
}

print_summary() {
  log "Bootstrap completato."
  cat <<EOF

Prossimi comandi utili:

  source .venv/bin/activate
  python extract_pdf_text.py
  python timeline_hybrid.py trascrizioni/sentenza2.json
  python timeline_embedding.py trascrizioni/sentenza2.json

Verifiche:

  tesseract --version
  pdftoppm -v
  mutool -v
  ollama list

EOF
}

install_system_packages
ensure_venv
install_python_dependencies
install_ollama
print_summary
