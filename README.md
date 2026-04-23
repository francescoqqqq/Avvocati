# Estrazione Testo PDF

Script Python che prende un PDF dalla cartella `sentenze/` e genera un file `.json` nella cartella `trascrizioni/` con il testo estratto pagina per pagina.

Questo progetto non usa API esterne: funziona solo se il PDF contiene testo selezionabile.

## Estrazione testo

```bash
python3 extract_pdf_text.py
```

Se trovi errori sulle dipendenze:

```bash
python3 -m pip install -r requirements.txt
```

## Timeline Rule-Based

Per provare l'estrazione degli eventi da un JSON già creato:

```bash
python3 timeline_rule.py
```

Per provare una versione rule-based più avanzata e generale:

```bash
python3 timeline_rule.py
```

Per provare una versione ibrida con preselezione rule-based e revisione Ollama:

```bash
python3 timeline_hybrid.py
```

L'output del motore ibrido viene salvato in:

```bash
results_hybrid/<nomefile>_timeline_hybrid.json
```

La versione ibrida fa:

1. preselezione dei blocchi con regole
2. estrazione/miglioramento mirato con Ollama solo sui blocchi candidati
3. revisione finale opzionale del JSON eventi per deduplica e pulizia

Per disattivare la revisione finale:

```bash
python3 timeline_hybrid.py --no-post-review
```

Lo script rule-based ti mostra i file `.json` presenti in `trascrizioni/`, ti fa scegliere con un numero e salva il risultato in:

```bash
results_rule/<nomefile>_timeline_rule.json
```

## Uso

Quando lanci l'estrazione testo, se trova PDF in `sentenze/` te li mostra numerati:

```text
PDF trovati nella cartella corrente:
  1. sentensa.pdf
  2. contratto.pdf
Che PDF vuoi analizzare? 1
```

Puoi anche scrivere direttamente un percorso completo.

## Output

Di default crea un file JSON con lo stesso nome del PDF in `trascrizioni/`:

```bash
trascrizioni/sentensa.json
```

## Formato JSON

```json
{
  "source_pdf": "/percorso/assoluto/documento.pdf",
  "extraction_method": "native_pdf_text",
  "page_count": 2,
  "pages": [
    {
      "page_number": 1,
      "text": "Testo pagina 1"
    },
    {
      "page_number": 2,
      "text": "Testo pagina 2"
    }
  ]
}
```

## Note

- Se una pagina non contiene testo selezionabile, nel JSON troverai: `[nessun testo selezionabile trovato in questa pagina]`.
- Script principale: `extract_pdf_text.py`
- Estrattore testo PDF: `extract_pdf_text.py`
- Estrattore timeline rule-based: `timeline_rule.py`
- Estrattore timeline ibrido regole + Ollama: `timeline_hybrid.py`
