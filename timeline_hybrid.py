#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import hybrid_rules


RESULTS_DIR_NAME = "results_hybrid"
TRANSCRIPTS_DIR_NAME = "trascrizioni"
DEFAULT_MODEL = "qwen2.5:1.5b"
DEFAULT_MAX_CANDIDATES = 8
DEFAULT_MIN_SCORE = 4
DEFAULT_MAX_REVIEW_EVENTS = 24
DEFAULT_OLLAMA_TIMEOUT = 120
DEFAULT_MAX_DISAMBIGUATIONS = 6
AMBIGUOUS_EVENT_TYPES = {
    "rinvio",
    "fissazione_udienza",
    "mediazione",
    "precisazione_conclusioni",
    "discussione",
    "costituzione",
    "notifica",
}
MULTI_DATE_EVENT_TYPES = {
    "rinvio",
    "precisazione_conclusioni",
    "sentenza_pronunciata",
    "fissazione_udienza",
    "mediazione",
    "costituzione",
    "notifica",
    "deposito_ricorso",
    "atto_contestato",
    "decreto_ingiuntivo",
}
FACTUAL_EVENT_PATTERNS = [
    ("accertamento_fatto", re.compile(r"\breato accertato\b", re.IGNORECASE), "Viene accertato il fatto contestato"),
    ("ispezione", re.compile(r"\b(?:effettuava|effettuato|attivit[aà] di)\s+ispezion\w+\b", re.IGNORECASE), "Viene effettuata un'ispezione sul mezzo o sugli alimenti"),
    ("sequestro", re.compile(r"\bsequestro (?:sanitario|preventivo)\b|\bsottopost\w+\s+a\s+sequestro\b", re.IGNORECASE), "Viene disposto il sequestro sanitario degli alimenti"),
    ("verbale_amministrativo", re.compile(r"\bcon verbale n\.\s*\d+/\d+\b|\bverbali di accertamento di illecito amministrativo\b", re.IGNORECASE), "Vengono elevati verbali amministrativi"),
    (
        "integrazione_ore_sostegno",
        re.compile(
            r"\b(?:allorch[eé]\s+[eè]\s+stata\s+dispost\w+\s+l['’]integrazione|"
            r"[eè]\s+stata\s+dispost\w+\s+l['’]integrazione|"
            r"integrazione\s+a\s+n\.\s*\d+\s+ore\s+di\s+insegnante\s+di\s+sostegno|"
            r"dispost\w+\s+l['’]invocat\w*\s+integrazione)\b",
            re.IGNORECASE,
        ),
        "Viene disposta l'integrazione delle ore di sostegno",
    ),
]
LOW_SCORE_UNDATED_EXEMPT_TYPES = {
    "decreto_penale_condanna",
    "deposito_sentenza",
    "verbale_amministrativo",
    "integrazione_ore_sostegno",
}


def get_transcripts_dir(working_dir: Path) -> Path:
    candidate = working_dir / TRANSCRIPTS_DIR_NAME
    return candidate if candidate.exists() else working_dir


def get_results_dir(working_dir: Path) -> Path:
    return working_dir / RESULTS_DIR_NAME


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estrae una timeline ibrida: preselezione rule-based dedicata + revisione mirata con Ollama."
    )
    parser.add_argument("input_json", nargs="?", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modello Ollama da usare. Default: {DEFAULT_MODEL}")
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    parser.add_argument("--max-block-chars", type=int, default=1800)
    parser.add_argument("--no-post-review", action="store_true")
    parser.add_argument("--post-review", action="store_true")
    parser.add_argument("--max-review-events", type=int, default=DEFAULT_MAX_REVIEW_EVENTS)
    parser.add_argument("--ollama-timeout", type=int, default=DEFAULT_OLLAMA_TIMEOUT)
    parser.add_argument("--max-disambiguations", type=int, default=DEFAULT_MAX_DISAMBIGUATIONS)
    return parser.parse_args()


def choose_input_path(arg_path: Path | None, working_dir: Path) -> Path:
    if arg_path:
        return arg_path.expanduser().resolve()

    transcripts_dir = get_transcripts_dir(working_dir)
    json_files = sorted(
        [
            path for path in transcripts_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".json"
            and not path.name.endswith("_timeline_rule.json")
            and not path.name.endswith("_timeline_hybrid.json")
        ],
        key=lambda path: path.name.lower(),
    )
    if json_files:
        print(f"JSON trovati in {transcripts_dir}:", file=sys.stderr)
        for index, json_file in enumerate(json_files, start=1):
            print(f"  {index}. {json_file.name}", file=sys.stderr)
        print("Digita il numero del JSON da analizzare oppure incolla un percorso completo.", file=sys.stderr)

    while True:
        user_input = input("Quale file JSON vuoi usare? ").strip().strip('"').strip("'")
        if not user_input:
            print("Inserisci il numero o il percorso di un file JSON.", file=sys.stderr)
            continue
        if user_input.isdigit() and json_files:
            selected = int(user_input)
            if 1 <= selected <= len(json_files):
                return json_files[selected - 1].resolve()
            print("Numero non valido.", file=sys.stderr)
            continue

        json_path = Path(user_input).expanduser()
        if not json_path.is_absolute():
            json_path = (transcripts_dir / json_path).resolve()
        else:
            json_path = json_path.resolve()
        if not json_path.exists():
            print(f"File non trovato: {json_path}", file=sys.stderr)
            continue
        if json_path.suffix.lower() != ".json":
            print(f"Il file selezionato non sembra un JSON: {json_path}", file=sys.stderr)
            continue
        return json_path


def build_candidate_blocks(source_data: dict, context: dict, max_candidates: int, min_score: int, max_block_chars: int) -> list[dict]:
    candidates: list[dict] = []
    for page in source_data.get("pages", []):
        page_number = page.get("page_number")
        page_text = page.get("text", "")
        for block in hybrid_rules.split_into_blocks(page_text):
            text = block["text"]
            section = block["section"]
            score = hybrid_rules.score_block(text, section)
            if score < min_score:
                continue
            if not hybrid_rules.contains_event_signal(text):
                continue
            candidates.append(
                {
                    "page_number": page_number,
                    "section": section,
                    "score": score,
                    "text": text[:max_block_chars],
                    "dates": filter_non_reference_dates(text, hybrid_rules.extract_all_dates(text)),
                    "subjects": hybrid_rules.extract_subjects(text, context),
                }
            )

    candidates.sort(
        key=lambda item: (-item["score"], 0 if item["section"] == "dispositivo" else 1, item["page_number"])
    )

    deduped: list[dict] = []
    seen = set()
    for candidate in candidates:
        key = (candidate["page_number"], candidate["text"][:160])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
        if len(deduped) >= max_candidates:
            break
    return deduped


def classify_rule_event(text: str, section: str, context: dict) -> tuple[str, str] | None:
    lowered = text.lower()
    is_pronounced_sentence = bool(
        re.search(r"\bha\s+pronunciat\w*\b.{0,80}\bsentenza\b", lowered)
        or re.search(r"\bha\s+pronunziat\w*\b.{0,80}\bsentenza\b", lowered)
        or re.search(r"\bsentenza\b.{0,80}\bha\s+pronunciat\w*\b", lowered)
        or re.search(r"\bsentenza\b.{0,80}\bha\s+pronunziat\w*\b", lowered)
        or ("mediante lettura del dispositivo" in lowered and "sentenza" in lowered)
        or ("decideva la causa pronunciando sentenza" in lowered)
    )
    if (
        ("sentenza" in lowered and section == "header")
        or is_pronounced_sentence
    ):
        return "sentenza_pronunciata", f"Il {context['court_name']} pronuncia la sentenza"
    if re.search(r"\bdecreto penale di condanna\b.*\bemess\w+\b|\bemess\w+\b.*\bdecreto penale di condanna\b", text, re.IGNORECASE):
        return "decreto_penale_condanna", "Viene emesso il decreto penale di condanna"
    if re.search(r"\bdepositat\w+\s+in cancelleria\b", text, re.IGNORECASE):
        return "deposito_sentenza", "La sentenza viene depositata in cancelleria"
    if re.search(r"\bricorso\b.{0,120}\bdepositat\w*(?:\s+telematicamente)?\s+in\s+data\b", text, re.IGNORECASE):
        return "deposito_ricorso", "Viene depositato il ricorso introduttivo"
    if re.search(r"\b(?:era\s+stato\s+)?indett\w+\s+in\s+data\b", text, re.IGNORECASE):
        return "atto_contestato", "Viene indetto l'atto o il bando contestato"
    if re.search(r"\bdecreto ingiuntivo\b.*\bemess\w+\s+il\b|\bemess\w+\s+il\b.*\bdecreto ingiuntivo\b", text, re.IGNORECASE):
        return "decreto_ingiuntivo", "Viene emesso il decreto ingiuntivo"
    if re.search(r"\bdecreto ingiuntivo\b.*\bpubblicat\w+\s+il\b|\bpubblicat\w+\s+il\b.*\bdecreto ingiuntivo\b", text, re.IGNORECASE):
        return "decreto_ingiuntivo", "Viene pubblicato il decreto ingiuntivo"
    if "decreto ingiuntivo" in lowered and "revoca" in lowered:
        return "revoca_decreto", "Il Tribunale revoca il decreto ingiuntivo opposto"
    if "cessazione della materia del contendere" in lowered:
        return "cessazione_materia", "Il Tribunale dichiara la cessazione della materia del contendere"
    if "spese di lite" in lowered or ("condanna" in lowered and "spese" in lowered):
        return "spese_lite", "Il Tribunale condanna la parte soccombente al pagamento delle spese di lite"
    if "si costitu" in lowered or "comparsa di costituzione" in lowered:
        return "costituzione", "Una parte si costituisce in giudizio"
    if "udienza" in lowered and "mediazione" in lowered:
        return "mediazione", "Il giudice dispone o valuta il tentativo di mediazione"
    if ("fissava" in lowered and "udienza" in lowered) or re.search(r"\bcon decreto del\b.{0,100}\bfissav\w+\b", lowered):
        return "fissazione_udienza", "Il giudice fissa l'udienza con decreto"
    if "rinvi" in lowered:
        return "rinvio", "La causa viene rinviata"
    if "precis" in lowered and "conclusion" in lowered:
        return "precisazione_conclusioni", "Le parti precisano le conclusioni"
    if "notificat" in lowered or "via p.e.c." in lowered:
        return "notifica", "Viene notificato l'atto introduttivo o il provvedimento"
    for event_type, pattern, label in FACTUAL_EVENT_PATTERNS:
        if pattern.search(text):
            return event_type, label
    return None


def should_split_multi_event_block(text: str) -> bool:
    dates = filter_non_reference_dates(text, hybrid_rules.extract_all_dates(text))
    if len(dates) >= 3:
        return True
    lowered = text.lower()
    civil_markers = (
        "emesso il",
        "pubblicato il",
        "notificato via p.e.c. il",
        "depositato telematicamente in data",
        "era stato indetto",
        "indetto in data",
    )
    return sum(marker in lowered for marker in civil_markers) >= 2


def split_block_into_event_segments(text: str) -> list[str]:
    lowered_full = text.lower()
    anchor_pattern = re.compile(
        r"(?=(?:all['’]udienza del|alla fissata udienza del|alla prima udienza|nelle more in data|"
        r"con ricorso\b|premesso che in data|con decreto del|notificat\w+\s+via\s+p\.e\.c\.\s+il|"
        r"emess\w+\s+il|pubblicat\w+\s+il|depositat\w*(?:\s+telematicamente)?\s+in\s+data|"
        r"(?:era\s+stato\s+)?indett\w+\s+in\s+data))",
        re.IGNORECASE,
    )
    matches = list(anchor_pattern.finditer(text))
    if len(matches) <= 1:
        return [text]

    segments: list[str] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        snippet = hybrid_rules.normalize_whitespace(text[start:end]).strip(" -;:,")
        lowered_snippet = snippet.lower()
        if "decreto ingiuntivo" in lowered_full and lowered_snippet.startswith(("emess", "pubblicat", "notificat")):
            snippet = f"decreto ingiuntivo {snippet}"
        if "bando" in lowered_full and lowered_snippet.startswith(("indett", "era stato indett")):
            snippet = f"bando di concorso {snippet}"
        if snippet:
            segments.append(snippet)

    return segments or [text]


def extract_inline_udienza_dates(text: str) -> list[str]:
    normalized = hybrid_rules.normalize_whitespace(text)
    if not re.match(r"^(?:all['’]?udienza del|udienza del)\b", normalized, re.IGNORECASE):
        return []
    values = []
    patterns = [
        r"\ball['’]?udienza del\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        r"\ball['’]?udienza del\s+(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            extracted = hybrid_rules.extract_all_dates(match.group(1))
            if extracted:
                values.append(extracted[0]["value"])
    return values


def extract_rinvio_target_dates(text: str) -> list[str]:
    values = []
    patterns = [
        r"\brinvi\w*.*?\ball['’]?udienza del\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        r"\brinvi\w*.*?\ball['’]?udienza del\s+(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            extracted = hybrid_rules.extract_all_dates(match.group(1))
            if extracted:
                values.append(extracted[0]["value"])
    return values


def starts_with_tale_udienza(text: str) -> bool:
    normalized = hybrid_rules.normalize_whitespace(text.lower())
    return normalized.startswith("a tale udienza")


def choose_event_date_with_context(
    text: str,
    dates: list[dict],
    event_type: str,
    decision_date: str | None,
    hearing_context_date: str | None,
) -> tuple[str | None, str]:
    if hearing_context_date and event_type in {
        "rinvio",
        "fissazione_udienza",
        "mediazione",
        "precisazione_conclusioni",
        "discussione",
        "sentenza_pronunciata",
    }:
        if starts_with_tale_udienza(text):
            return hearing_context_date, "implicita"
        if event_type == "rinvio":
            has_inline_udienza = bool(extract_inline_udienza_dates(text))
            has_target_udienza = bool(extract_rinvio_target_dates(text))
            if has_target_udienza and not has_inline_udienza:
                return hearing_context_date, "implicita"
    return hybrid_rules.choose_event_date(text, dates, event_type, decision_date)


def extract_verbale_entries(text: str) -> list[dict]:
    entries = []
    pattern = re.compile(
        r"\bverbale n\.\s*(\d+/\d+)\s+dell?[’']?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b",
        re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        extracted = hybrid_rules.extract_all_dates(match.group(2))
        if not extracted:
            continue
        entries.append(
            {
                "numero": match.group(1),
                "data": extracted[0]["value"],
            }
        )
    return entries


def get_disambiguation_cache_path(working_dir: Path) -> Path:
    return get_results_dir(working_dir) / "ollama_date_cache.json"


def load_disambiguation_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_disambiguation_cache(cache_path: Path, cache: dict) -> None:
    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def filter_non_reference_dates(text: str, dates: list[dict]) -> list[dict]:
    filtered = []
    for candidate_date in dates:
        role = hybrid_rules.classify_date_role(text, candidate_date["raw"])
        if role in {"citazione_giurisprudenziale", "riferimento_normativo", "data_nascita"}:
            continue
        filtered.append(candidate_date)
    return filtered


def build_focus_snippet(text: str, dates: list[dict]) -> str:
    if not dates:
        return hybrid_rules.normalize_event_text(text)

    matches = []
    for candidate_date in dates:
        match = re.search(re.escape(candidate_date["raw"]), text, re.IGNORECASE)
        if match:
            matches.append(match)

    if not matches:
        return hybrid_rules.normalize_event_text(text)

    start = max(0, min(match.start() for match in matches) - 90)
    end = min(len(text), max(match.end() for match in matches) + 90)
    snippet = text[start:end]
    snippet = hybrid_rules.normalize_whitespace(snippet)
    return snippet[:320]


def should_disambiguate(text: str, event_type: str, valid_dates: list[dict]) -> bool:
    if len(valid_dates) >= 3:
        return False
    if event_type not in AMBIGUOUS_EVENT_TYPES:
        return False
    if len(valid_dates) < 2:
        return False
    lowered = text.lower()
    return (
        ("rinvi" in lowered and "udienza" in lowered)
        or ("decreto del" in lowered and "udienza" in lowered)
    )


def build_rule_baseline(
    source_data: dict,
    input_name: str,
    source_document: str,
    context: dict,
    decision_date: str | None,
) -> tuple[dict, list[dict]]:
    events = []
    disambiguation_tasks = []
    next_id = 1
    hearing_context_date = None
    propagated_decision_date = decision_date
    for page in source_data.get("pages", []):
        page_number = page.get("page_number")
        page_text = page.get("text", "")
        for block in hybrid_rules.split_into_blocks(page_text):
            text = block["text"]
            section = block["section"]
            block_segments = split_block_into_event_segments(text) if should_split_multi_event_block(text) else [text]
            processed_any_segment = False

            for segment_text in block_segments:
                score = hybrid_rules.score_block(segment_text, section)
                dates = hybrid_rules.extract_all_dates(segment_text)
                classification = classify_rule_event(segment_text, section, context)
                if score < 3 and classification is None:
                    continue
                if classification is None and not hybrid_rules.contains_event_signal(segment_text):
                    continue
                if classification is None:
                    inline_dates = extract_inline_udienza_dates(segment_text)
                    if inline_dates:
                        hearing_context_date = inline_dates[-1]
                    continue

                processed_any_segment = True
                event_type, event_text = classification
                event_date, certainty = choose_event_date_with_context(
                    segment_text,
                    dates,
                    event_type,
                    propagated_decision_date,
                    hearing_context_date,
                )
                subjects = hybrid_rules.extract_subjects(segment_text, context)
                block_event_entries = []
                if event_type == "verbale_amministrativo":
                    entries = extract_verbale_entries(segment_text)
                    if entries:
                        for entry in entries:
                            block_event_entries.append(
                                {
                                    "id": next_id + len(block_event_entries),
                                    "data": entry["data"],
                                    "ora": hybrid_rules.extract_time(segment_text),
                                    "evento": f"Viene elevato il verbale amministrativo n. {entry['numero']}",
                                    "tipo_evento": event_type,
                                    "soggetti": subjects,
                                    "documento": source_document,
                                    "pagina": page_number,
                                    "certezza_data": "esplicita",
                                    "sezione": section,
                                    "score": score,
                                    "testo_origine": hybrid_rules.normalize_event_text(segment_text),
                                    "fonte": "regole_hybrid",
                                }
                            )

                if not block_event_entries:
                    block_event_entries.append(
                        {
                            "id": next_id,
                            "data": event_date,
                            "ora": hybrid_rules.extract_time(segment_text),
                            "evento": event_text,
                            "tipo_evento": event_type,
                            "soggetti": subjects,
                            "documento": source_document,
                            "pagina": page_number,
                            "certezza_data": certainty if event_date else "assente",
                            "sezione": section,
                            "score": score,
                            "testo_origine": hybrid_rules.normalize_event_text(segment_text),
                            "fonte": "regole_hybrid",
                        }
                    )

                event_id = block_event_entries[0]["id"]
                events.extend(block_event_entries)
                if event_type == "sentenza_pronunciata" and event_date and not propagated_decision_date:
                    propagated_decision_date = event_date

                valid_dates = filter_non_reference_dates(segment_text, dates)
                if should_disambiguate(segment_text, event_type, valid_dates):
                    disambiguation_tasks.append(
                        {
                            "event_id": event_id,
                            "page_number": page_number,
                            "section": section,
                            "score": score,
                            "event_type": event_type,
                            "current_date": event_date,
                            "candidate_dates": [item["value"] for item in valid_dates],
                            "focus_text": build_focus_snippet(segment_text, valid_dates),
                            "full_text": segment_text,
                        }
                    )

                rinvio_dates = extract_rinvio_target_dates(segment_text)
                if rinvio_dates:
                    hearing_context_date = rinvio_dates[-1]
                else:
                    inline_dates = extract_inline_udienza_dates(segment_text)
                    if inline_dates:
                        hearing_context_date = inline_dates[-1]
                next_id += len(block_event_entries)

            if not processed_any_segment:
                inline_dates = extract_inline_udienza_dates(text)
                if inline_dates:
                    hearing_context_date = inline_dates[-1]

    unique_events = deduplicate_combined_events(events)
    dated_events = hybrid_rules.sort_events([event for event in unique_events if event.get("data")])
    undated_events = hybrid_rules.sort_events([event for event in unique_events if not event.get("data")])

    return {
        "source_json": input_name,
        "documento": source_document,
        "contesto_documento": context,
        "eventi": dated_events,
        "eventi_non_datati": undated_events,
    }, disambiguation_tasks


def build_date_disambiguation_prompt(candidate: dict) -> str:
    candidate_dates = ", ".join(candidate["candidate_dates"])
    return f"""Nel seguente testo di una sentenza italiana, quale data indica QUANDO e' avvenuto l'evento processuale descritto e non la data di un rinvio futuro o di un riferimento accessorio?

Tipo evento: {candidate["event_type"]}
Date candidate: {candidate_dates}

Testo: "{candidate["focus_text"]}"

Rispondi SOLO con JSON valido in questo formato esatto:
{{"data_evento": "YYYY-MM-DD"}}

Se nessuna data e' chiaramente la data dell'evento, rispondi SOLO con:
{{"data_evento": null}}
"""


def run_ollama(model: str, prompt: str, timeout: int) -> str:
    try:
        result = subprocess.run(
            ["ollama", "run", model],
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"Ollama ha superato il timeout di {timeout} secondi. "
            "Riduci i blocchi candidati, usa un modello piu' leggero o disattiva la revisione finale."
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Ollama ha restituito un errore: {stderr}")
    return result.stdout.strip()


def extract_json_array(text: str) -> list:
    text = text.strip()
    decoder = json.JSONDecoder()
    for start_index, char in enumerate(text):
        if char != "[":
            continue
        try:
            data, _ = decoder.raw_decode(text[start_index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return data
    return []


def extract_json_object(text: str) -> dict | None:
    text = text.strip()
    decoder = json.JSONDecoder()
    for start_index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[start_index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def normalize_disambiguated_date(raw_data: dict, candidate: dict) -> str | None:
    if not isinstance(raw_data, dict):
        return None
    raw_value = raw_data.get("data_evento")
    if raw_value is None:
        return None
    raw_text = hybrid_rules.normalize_whitespace(str(raw_value))
    if not raw_text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_text):
        normalized = raw_text
    else:
        extracted = hybrid_rules.extract_all_dates(raw_text)
        normalized = extracted[0]["value"] if extracted else None
    if normalized not in set(candidate["candidate_dates"]):
        return None
    return normalized


def disambiguation_cache_key(model: str, candidate: dict) -> str:
    payload = {
        "model": model,
        "event_type": candidate["event_type"],
        "candidate_dates": candidate["candidate_dates"],
        "focus_text": candidate["focus_text"],
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def apply_disambiguation_results(events: list[dict], results: list[dict]) -> list[dict]:
    updates = {item["event_id"]: item["resolved_date"] for item in results if item.get("resolved_date")}
    for event in events:
        if event["id"] in updates:
            event["data"] = updates[event["id"]]
            event["certezza_data"] = "esplicita"
            event["fonte"] = "regole_hybrid_ollama_data"
    return events


def filter_low_confidence_undated(events: list[dict]) -> list[dict]:
    filtered = []
    for event in events:
        score = event.get("score")
        if score is None:
            filtered.append(event)
            continue
        if event.get("tipo_evento") in LOW_SCORE_UNDATED_EXEMPT_TYPES:
            filtered.append(event)
            continue
        if score > 3:
            filtered.append(event)
    return filtered


def infer_decision_date_from_events(events: list[dict]) -> str | None:
    for event in reversed(events):
        if event.get("tipo_evento") == "sentenza_pronunciata" and event.get("data"):
            return event["data"]
    return None


def run_date_disambiguations(
    model: str,
    candidates: list[dict],
    timeout: int,
    cache_path: Path,
) -> tuple[list[dict], int, int]:
    cache = load_disambiguation_cache(cache_path)
    resolved = []
    cache_hits = 0
    cache_changed = False

    for index, candidate in enumerate(candidates, start=1):
        print(
            f"  Disambiguazione {index}/{len(candidates)}: pagina {candidate['page_number']}, date {candidate['candidate_dates']}",
            file=sys.stderr,
        )
        cache_key = disambiguation_cache_key(model, candidate)
        cached_value = cache.get(cache_key)
        if cached_value in candidate["candidate_dates"] or cached_value is None:
            if cache_key in cache:
                cache_hits += 1
                resolved.append({"event_id": candidate["event_id"], "resolved_date": cached_value})
                continue

        prompt = build_date_disambiguation_prompt(candidate)
        try:
            raw_output = run_ollama(model, prompt, timeout)
        except RuntimeError as exc:
            print(f"    Ollama errore: {exc}", file=sys.stderr)
            resolved.append({"event_id": candidate["event_id"], "resolved_date": None})
            continue

        parsed = extract_json_object(raw_output)
        resolved_date = normalize_disambiguated_date(parsed, candidate)
        cache[cache_key] = resolved_date
        cache_changed = True
        resolved.append({"event_id": candidate["event_id"], "resolved_date": resolved_date})

    if cache_changed:
        save_disambiguation_cache(cache_path, cache)
    return resolved, len(resolved), cache_hits


def normalize_model_event(raw_event: dict, candidate: dict, source_document: str) -> dict | None:
    if not isinstance(raw_event, dict):
        return None

    event_text = hybrid_rules.normalize_whitespace(str(raw_event.get("evento", "")))
    if len(event_text) < 8:
        return None

    raw_date = raw_event.get("data")
    normalized_date = None
    if isinstance(raw_date, str) and raw_date.strip():
        extracted = hybrid_rules.extract_all_dates(raw_date.strip())
        if extracted:
            normalized_date = extracted[0]["value"]
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date.strip()):
            normalized_date = raw_date.strip()

    raw_time = raw_event.get("ora")
    normalized_time = raw_time if isinstance(raw_time, str) and re.fullmatch(r"\d{2}:\d{2}", raw_time) else None
    subjects = raw_event.get("soggetti") if isinstance(raw_event.get("soggetti"), list) else []
    subjects = [hybrid_rules.normalize_whitespace(str(item)) for item in subjects if str(item).strip()]

    certainty = str(raw_event.get("certezza_data", "assente"))
    if certainty not in {"esplicita", "implicita", "assente"}:
        certainty = "assente"

    event_type = hybrid_rules.normalize_whitespace(str(raw_event.get("tipo_evento", "altro"))).lower() or "altro"

    return {
        "data": normalized_date,
        "ora": normalized_time,
        "evento": event_text,
        "tipo_evento": event_type,
        "soggetti": subjects,
        "documento": source_document,
        "pagina": candidate["page_number"],
        "certezza_data": certainty if normalized_date else "assente",
        "sezione": candidate["section"],
        "score": candidate["score"],
        "testo_origine": hybrid_rules.normalize_event_text(candidate["text"]),
        "fonte": "ollama",
    }


def deduplicate_combined_events(events: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for event in events:
        normalized_text = hybrid_rules.normalize_whitespace(event.get("evento", "")).lower()
        normalized_text = re.sub(r"\bil tribunale di [a-zà-öø-ÿ' ]+\b", "il tribunale", normalized_text)
        normalized_text = re.sub(r"\bil giudice\b", "giudice", normalized_text)
        key = (
            event.get("data"),
            event.get("tipo_evento", "altro"),
            normalized_text,
            event.get("pagina") if not event.get("data") else None,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def merge_rule_and_ollama(rule_data: dict, ollama_events: list[dict]) -> dict:
    merged_events = []
    temp_id = 1
    for event in rule_data["eventi"]:
        enriched = dict(event)
        enriched["id"] = enriched.get("id", temp_id)
        merged_events.append(enriched)
        temp_id += 1
    for event in rule_data["eventi_non_datati"]:
        enriched = dict(event)
        enriched["id"] = enriched.get("id", temp_id)
        merged_events.append(enriched)
        temp_id += 1
    for event in ollama_events:
        enriched = dict(event)
        enriched["id"] = enriched.get("id", temp_id)
        merged_events.append(enriched)
        temp_id += 1

    unique_events = deduplicate_combined_events(merged_events)
    dated_events = hybrid_rules.sort_events([event for event in unique_events if event.get("data")])
    undated_events = hybrid_rules.sort_events([event for event in unique_events if not event.get("data")])

    for index, event in enumerate(dated_events + undated_events, start=1):
        event["id"] = index

    return {
        "source_json": rule_data["source_json"],
        "documento": rule_data["documento"],
        "contesto_documento": rule_data["contesto_documento"],
        "eventi": dated_events,
        "eventi_non_datati": undated_events,
    }


def build_review_payload(merged: dict, max_review_events: int) -> list[dict]:
    candidates = merged["eventi"] + merged["eventi_non_datati"]
    trimmed = candidates[:max_review_events]
    payload = []
    for event in trimmed:
        payload.append(
            {
                "id": event["id"],
                "data": event.get("data"),
                "ora": event.get("ora"),
                "evento": event.get("evento"),
                "tipo_evento": event.get("tipo_evento", "altro"),
                "soggetti": event.get("soggetti", []),
                "documento": event.get("documento"),
                "pagina": event.get("pagina"),
                "certezza_data": event.get("certezza_data", "assente"),
                "fonte": event.get("fonte", "regole_hybrid"),
            }
        )
    return payload


def build_review_prompt(payload: list[dict], context: dict) -> str:
    return (
        "Sei un revisore conservativo di timeline giuridiche.\n"
        "Ricevi un array JSON di eventi gia' estratti.\n"
        "Il tuo compito e' SOLO:\n"
        "- unire duplicati evidenti\n"
        "- eliminare eventi chiaramente ridondanti o incoerenti\n"
        "- migliorare descrizioni troppo generiche quando il significato e' gia' chiaro nell'evento stesso\n"
        "- mantenere le date gia' presenti se plausibili\n"
        "- non inventare eventi nuovi\n"
        "- non cambiare pagina o documento senza motivo evidente\n"
        "- restituisci SOLO un array JSON valido\n"
        "- usa le stesse chiavi: id, data, ora, evento, tipo_evento, soggetti, documento, pagina, certezza_data, fonte\n"
        f"- tribunale di riferimento: {context['court_name']}\n"
        f"- giudice di riferimento: {context['judge_name']}\n\n"
        "Array da revisionare:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def normalize_reviewed_event(raw_event: dict) -> dict | None:
    if not isinstance(raw_event, dict):
        return None
    event_text = hybrid_rules.normalize_whitespace(str(raw_event.get("evento", "")))
    if len(event_text) < 8:
        return None

    raw_date = raw_event.get("data")
    normalized_date = None
    if isinstance(raw_date, str) and raw_date.strip():
        extracted = hybrid_rules.extract_all_dates(raw_date.strip())
        if extracted:
            normalized_date = extracted[0]["value"]
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date.strip()):
            normalized_date = raw_date.strip()

    raw_time = raw_event.get("ora")
    normalized_time = raw_time if isinstance(raw_time, str) and re.fullmatch(r"\d{2}:\d{2}", raw_time) else None
    subjects = raw_event.get("soggetti") if isinstance(raw_event.get("soggetti"), list) else []
    subjects = [hybrid_rules.normalize_whitespace(str(item)) for item in subjects if str(item).strip()]
    certainty = str(raw_event.get("certezza_data", "assente"))
    if certainty not in {"esplicita", "implicita", "assente"}:
        certainty = "assente"
    source = hybrid_rules.normalize_whitespace(str(raw_event.get("fonte", "ollama_review"))) or "ollama_review"

    return {
        "id": int(raw_event.get("id", 0)) if str(raw_event.get("id", "")).isdigit() else 0,
        "data": normalized_date,
        "ora": normalized_time,
        "evento": event_text,
        "tipo_evento": hybrid_rules.normalize_whitespace(str(raw_event.get("tipo_evento", "altro"))).lower() or "altro",
        "soggetti": subjects,
        "documento": hybrid_rules.normalize_whitespace(str(raw_event.get("documento", ""))),
        "pagina": int(raw_event.get("pagina", 0)) if str(raw_event.get("pagina", "")).isdigit() else 0,
        "certezza_data": certainty if normalized_date else "assente",
        "fonte": source,
    }


def review_events_with_ollama(
    model: str, merged: dict, context: dict, max_review_events: int, timeout: int
) -> tuple[dict, int]:
    payload = build_review_payload(merged, max_review_events)
    if not payload:
        return merged, 0

    prompt = build_review_prompt(payload, context)
    raw_output = run_ollama(model, prompt, timeout)
    parsed_events = extract_json_array(raw_output)
    reviewed = []
    for raw_event in parsed_events:
        event = normalize_reviewed_event(raw_event)
        if event is not None:
            reviewed.append(event)

    if not reviewed:
        return merged, 0

    untouched = []
    reviewed_ids = {event["id"] for event in reviewed if event["id"] > 0}
    for event in merged["eventi"] + merged["eventi_non_datati"]:
        if event["id"] not in reviewed_ids:
            untouched.append(event)

    combined = reviewed + untouched
    unique = deduplicate_combined_events(combined)
    dated_events = hybrid_rules.sort_events([event for event in unique if event.get("data")])
    undated_events = hybrid_rules.sort_events([event for event in unique if not event.get("data")])
    for index, event in enumerate(dated_events + undated_events, start=1):
        event["id"] = index

    merged["eventi"] = dated_events
    merged["eventi_non_datati"] = undated_events
    return merged, len(reviewed)


def main() -> int:
    args = parse_args()
    working_dir = Path.cwd()
    input_path = choose_input_path(args.input_json, working_dir)
    if not input_path.exists():
        print(f"Errore: JSON non trovato: {input_path}", file=sys.stderr)
        return 1

    source_data = json.loads(input_path.read_text(encoding="utf-8"))
    source_document = Path(source_data.get("source_pdf", input_path.name)).name
    context = hybrid_rules.extract_document_context(source_data)
    header_metadata = hybrid_rules.extract_header_metadata(source_data)
    if header_metadata.get("sentence_number"):
        context["sentence_number"] = header_metadata["sentence_number"]
    if header_metadata.get("rg_number"):
        context["rg_number"] = header_metadata["rg_number"]
    decision_date = header_metadata.get("decision_date") or hybrid_rules.infer_decision_date(source_data)
    rule_baseline, disambiguation_tasks = build_rule_baseline(
        source_data,
        input_path.name,
        source_document,
        context,
        decision_date,
    )
    rule_baseline["eventi_non_datati"] = hybrid_rules.sort_events(
        filter_low_confidence_undated(rule_baseline["eventi_non_datati"])
    )
    for index, event in enumerate(rule_baseline["eventi"] + rule_baseline["eventi_non_datati"], start=1):
        event["id"] = index

    candidates = build_candidate_blocks(
        source_data=source_data,
        context=context,
        max_candidates=args.max_candidates,
        min_score=args.min_score,
        max_block_chars=args.max_block_chars,
    )
    difficult_candidates = sorted(
        disambiguation_tasks,
        key=lambda item: (-len(item["candidate_dates"]), -item["score"], item["page_number"]),
    )[: args.max_disambiguations]

    print(
        f"Analizzo {input_path.name} con timeline_hybrid: {len(candidates)} blocchi candidati, {len(difficult_candidates)} ambigui da disambiguare...",
        file=sys.stderr,
    )

    results_dir = get_results_dir(working_dir)
    results_dir.mkdir(exist_ok=True)
    cache_path = get_disambiguation_cache_path(working_dir)
    disambiguated_count = 0
    cache_hits = 0
    if difficult_candidates:
        try:
            resolved_dates, disambiguated_count, cache_hits = run_date_disambiguations(
                args.model,
                difficult_candidates,
                args.ollama_timeout,
                cache_path,
            )
            all_events = rule_baseline["eventi"] + rule_baseline["eventi_non_datati"]
            updated_events = apply_disambiguation_results(all_events, resolved_dates)
            unique_events = deduplicate_combined_events(updated_events)
            rule_baseline["eventi"] = hybrid_rules.sort_events([event for event in unique_events if event.get("data")])
            rule_baseline["eventi_non_datati"] = hybrid_rules.sort_events(
                filter_low_confidence_undated([event for event in unique_events if not event.get("data")])
            )
            for index, event in enumerate(rule_baseline["eventi"] + rule_baseline["eventi_non_datati"], start=1):
                event["id"] = index
        except RuntimeError as exc:
            print(f"Disambiguazione Ollama non riuscita: {exc}", file=sys.stderr)

    merged = merge_rule_and_ollama(rule_baseline, [])
    reviewed_events_count = 0
    post_review_enabled = args.post_review and not args.no_post_review
    if post_review_enabled:
        try:
            merged, reviewed_events_count = review_events_with_ollama(
                args.model,
                merged,
                context,
                args.max_review_events,
                args.ollama_timeout,
            )
        except RuntimeError as exc:
            print(f"Revisione finale Ollama non riuscita: {exc}", file=sys.stderr)

    merged["eventi_non_datati"] = hybrid_rules.sort_events(filter_low_confidence_undated(merged["eventi_non_datati"]))
    for index, event in enumerate(merged["eventi"] + merged["eventi_non_datati"], start=1):
        event["id"] = index

    final_decision_date = decision_date or infer_decision_date_from_events(merged["eventi"])

    merged["metriche"] = {
        "modello_ollama": args.model,
        "blocchi_candidati": len(candidates),
        "blocchi_ambigui": len(difficult_candidates),
        "eventi_regole_datati": len(rule_baseline["eventi"]),
        "eventi_regole_non_datati": len(rule_baseline["eventi_non_datati"]),
        "eventi_ollama": 0,
        "disambiguazioni_ollama": disambiguated_count,
        "cache_hit_disambiguazioni": cache_hits,
        "eventi_revisionati_ollama": reviewed_events_count,
        "eventi_finali_datati": len(merged["eventi"]),
        "eventi_finali_non_datati": len(merged["eventi_non_datati"]),
        "decision_date": final_decision_date,
        "post_review_attivo": post_review_enabled,
    }
    merged["blocchi_analizzati"] = [
        {
            "page_number": candidate["page_number"],
            "section": candidate["section"],
            "score": candidate["score"],
            "dates": [item["value"] for item in candidate["dates"]],
            "text_preview": candidate["text"][:280],
        }
        for candidate in candidates
    ]
    merged["blocchi_ambigui_analizzati"] = [
        {
            "event_id": candidate["event_id"],
            "page_number": candidate["page_number"],
            "section": candidate["section"],
            "score": candidate["score"],
            "event_type": candidate["event_type"],
            "candidate_dates": candidate["candidate_dates"],
            "focus_text": candidate["focus_text"],
        }
        for candidate in difficult_candidates
    ]
    output_path = results_dir / f"{input_path.stem}_timeline_hybrid.json"
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Timeline salvata in: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
