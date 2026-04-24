# Lexi Timeline

Progetto locale per:

- estrarre testo da PDF giuridici con fallback OCR
- generare timeline rule-based
- generare timeline ibride con regole + Ollama
- sperimentare una pipeline con embedding locali

Non usa API esterne a pagamento. Tutto gira in locale.

## Setup Rapido

Il modo consigliato per inizializzare il repo su una macchina Ubuntu/Debian e' usare lo script di bootstrap:

```bash
bash bootstrap_local.sh
```

Lo script:

- crea `.venv` se manca
- aggiorna `pip`
- installa le dipendenze Python
- installa `torch` CPU-only
- installa `sentence-transformers`
- installa i pacchetti di sistema per OCR:
  - `tesseract-ocr`
  - `tesseract-ocr-ita`
  - `poppler-utils`
  - `mupdf-tools`
  - `curl`
- installa `ollama` se manca
- prova ad avviare il servizio Ollama
- scarica il modello `qwen2.5:3b`

Se vuoi evitare una parte del bootstrap:

```bash
bash bootstrap_local.sh --skip-apt
bash bootstrap_local.sh --skip-ollama
bash bootstrap_local.sh --skip-model
```

## Setup Manuale

Se preferisci fare tutto a mano:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
sudo apt update
sudo apt install -y tesseract-ocr tesseract-ocr-ita poppler-utils mupdf-tools curl
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b
```

## Dipendenze

### Python

Le dipendenze applicative minime sono in `requirements.txt`.

Installazione:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Per la pipeline embedding e' fortemente consigliata l'installazione CPU-only di `torch` prima di `sentence-transformers`.

### Sistema

Dipendenze OCR locali:

```bash
sudo apt install -y tesseract-ocr tesseract-ocr-ita poppler-utils mupdf-tools
```

Questo progetto usa:

- `tesseract` per OCR
- `pdftoppm` da `poppler-utils` per il rendering OCR
- `mutool` da `mupdf-tools` come renderer OCR alternativo
- `ollama` per i passaggi LLM locali

## Verifiche Rapide

### OCR

```bash
tesseract --version
pdftoppm -v
mutool -v
```

### Ollama

```bash
ollama list
ollama run qwen2.5:3b "ok"
```

### Embedding

```bash
python - <<'PY'
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
print("ok")
PY
```

## Estrazione Testo PDF

Script principale:

```bash
python extract_pdf_text.py
```

Oppure su un file specifico:

```bash
python extract_pdf_text.py sentenze/sentenza2.pdf
```

Output:

```bash
trascrizioni/<nomefile>.json
```

## Timeline Rule-Based

```bash
python timeline_rule.py
```

Oppure:

```bash
python timeline_rule.py trascrizioni/sentenza2.json
```

Output:

```bash
results_rule/<nomefile>_timeline_rule.json
```

## Timeline Hybrid

```bash
python timeline_hybrid.py
```

Oppure:

```bash
python timeline_hybrid.py trascrizioni/sentenza2.json
```

Output:

```bash
results_hybrid/<nomefile>_timeline_hybrid.json
```

La pipeline hybrid usa:

1. regole per blocchi e date
2. Ollama per disambiguazioni mirate
3. Ollama per factual mirati
4. Ollama per arricchimento soggetti

## Timeline Embedding

```bash
python timeline_embedding.py
```

Oppure:

```bash
python timeline_embedding.py trascrizioni/sentenza2.json
```

Output:

```bash
results_embedding/<nomefile>_timeline_embedding.json
```

La pipeline embedding mantiene le regole per blocchi e date, ma usa:

- Ollama per descrivere l'evento
- embedding locali per classificare semanticamente `tipo_evento`
- embedding locali per deduplicare eventi molto simili sulla stessa data

## Esecuzione su Tutti i JSON

### Timeline Rule

```bash
for f in trascrizioni/*.json; do
  case "$f" in
    *_timeline_rule.json|*_timeline_hybrid.json|*_timeline_embedding.json) continue ;;
  esac
  python timeline_rule.py "$f"
done
```

### Timeline Hybrid

```bash
for f in trascrizioni/*.json; do
  case "$f" in
    *_timeline_rule.json|*_timeline_hybrid.json|*_timeline_embedding.json) continue ;;
  esac
  python timeline_hybrid.py "$f"
done
```

### Timeline Embedding

```bash
for f in trascrizioni/*.json; do
  case "$f" in
    *_timeline_rule.json|*_timeline_hybrid.json|*_timeline_embedding.json) continue ;;
  esac
  python timeline_embedding.py "$f"
done
```

## Struttura Output

Cartelle principali:

- `sentenze/`: PDF originali
- `trascrizioni/`: testo estratto pagina per pagina
- `results_rule/`: output rule-based
- `results_hybrid/`: output hybrid
- `results_embedding/`: output embedding

## Note

- Se una pagina PDF non contiene testo selezionabile, `extract_pdf_text.py` prova OCR locale.
- Il primo download di `Ollama` e del modello embedding puo' richiedere tempo.
- Hugging Face puo' mostrare un warning su `HF_TOKEN`: non e' un errore.
- I file `timeline_hybrid.py` e `timeline_embedding.py` sono separati di proposito.
