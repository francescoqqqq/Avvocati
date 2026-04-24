#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import embedding_rules as hybrid_rules


RESULTS_DIR_NAME = "results_embedding"
TRANSCRIPTS_DIR_NAME = "trascrizioni"
DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_MAX_CANDIDATES = 20
DEFAULT_MIN_SCORE = 3
DEFAULT_MAX_SUBJECT_EVENTS = 32
DEFAULT_OLLAMA_TIMEOUT = 120
DEFAULT_MAX_DISAMBIGUATIONS = 6
DATE_DISAMBIGUATION_BATCH_SIZE = 4
SEMANTIC_DEDUPLICATION_THRESHOLD = 0.85
FACTUAL_OLLAMA_EVENT_TYPES = {
    "periodo_lavorativo",
    "provvedimento_disciplinare",
    "revoca_qualifica",
    "modifica_incarico",
    "aggressione",
    "udienza",
    "deposito_atto",
    "decreto",
    "chiamata_in_causa",
    "provvedimento_amministrativo",
    "accertamento_medico",
    "costituzione_in_giudizio",
    "evento_generico",
    "altro_fatto_rilevante",
}
AMBIGUOUS_EVENT_TYPES = {
    "rinvio",
    "fissazione_udienza",
    "mediazione",
    "precisazione_conclusioni",
    "discussione",
    "costituzione",
    "notifica",
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
    (
        "diffida",
        re.compile(r"\bdiffid\w+\b|\batto\s+interruttivo\b|\bricevut\w+\s+dal\s+ministero\b", re.IGNORECASE),
        "Viene notificata o ricevuta la diffida interruttiva",
    ),
    (
        "periodo_lavorativo",
        re.compile(r"\b(?:prestat\w+|lavorat\w+|assunt\w+|svolt\w+\s+servizio|supplenz\w+|incaric\w+)\b", re.IGNORECASE),
        "Viene svolto un periodo di lavoro o supplenza",
    ),
]
PROMOTED_FACTUAL_PATTERNS = [
    ("deposito_ricorso", re.compile(r"\bdepositat\w+\b", re.IGNORECASE), "Viene depositato il ricorso introduttivo"),
    ("notifica", re.compile(r"\bnotificat\w+\b", re.IGNORECASE), "Viene notificato l'atto introduttivo o il provvedimento"),
    ("diffida", re.compile(r"\bdiffid\w+\b|\bricevut\w+\b", re.IGNORECASE), "Viene notificata o ricevuta la diffida interruttiva"),
    ("periodo_lavorativo", re.compile(r"\b(?:prestat\w+|lavorat\w+|assunt\w+|svolt\w+\s+servizio|supplenz\w+|incaric\w+)\b", re.IGNORECASE), "Viene svolto un periodo di lavoro o supplenza"),
    ("atto_contestato", re.compile(r"\b(?:indett\w+|bando di concorso)\b", re.IGNORECASE), "Viene indetto l'atto o il bando contestato"),
]
LOW_SCORE_UNDATED_EXEMPT_TYPES = {
    "decreto_penale_condanna",
    "deposito_sentenza",
    "verbale_amministrativo",
    "integrazione_ore_sostegno",
    "diffida",
    "periodo_lavorativo",
}
EVENT_TYPE_HINT_LABELS = {
    "deposito_ricorso": "Viene depositato il ricorso introduttivo",
    "notifica": "Viene notificato l'atto introduttivo o il provvedimento",
    "fissazione_udienza": "Il giudice fissa l'udienza con decreto",
    "rinvio": "La causa viene rinviata",
    "mediazione": "Il giudice dispone o valuta il tentativo di mediazione",
    "precisazione_conclusioni": "Le parti precisano le conclusioni",
    "sentenza_pronunciata": "Il Tribunale pronuncia la sentenza",
    "decreto_ingiuntivo": "Viene emesso il decreto ingiuntivo",
    "costituzione": "Una parte si costituisce in giudizio",
    "verbale_amministrativo": "Vengono elevati verbali amministrativi",
    "decisione": "Il Tribunale definisce il giudizio nel merito",
    "diffida": "Viene notificata o ricevuta la diffida interruttiva",
    "periodo_lavorativo": "Viene svolto un periodo di lavoro o supplenza",
    "spese_lite": "Il Tribunale condanna la parte soccombente al pagamento delle spese di lite",
    "ordine": "Il Tribunale ordina un adempimento specifico",
    "dichiarazione": "Il Tribunale dichiara un effetto o una situazione giuridica",
    "condanna": "Il Tribunale condanna una parte a un adempimento o pagamento",
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
    parser.add_argument("--max-subject-events", type=int, default=DEFAULT_MAX_SUBJECT_EVENTS)
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
            and not path.name.endswith("_timeline_embedding.json")
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
            section = hybrid_rules.infer_macro_section(text, block["section"])
            if hybrid_rules.is_jurisprudential_reference_block(text, section):
                continue
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


def classify_rule_event(text: str, section: str, context: dict, event_type_hint: str | None = None) -> tuple[str, str] | None:
    lowered = text.lower()
    has_dates = bool(hybrid_rules.extract_all_dates(text))
    if hybrid_rules.is_jurisprudential_reference_block(text, section):
        return None
    if hybrid_rules.is_request_like_block(text, section) and event_type_hint != "precisazione_conclusioni":
        return None
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
    if "così deciso" in lowered or "cosi deciso" in lowered:
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
    if section == "dispositivo" and re.search(r"\b(?:rigetta|accoglie|conferma|annulla|respinge)\b", lowered):
        return "decisione", "Il Tribunale definisce il giudizio nel merito"
    if section == "dispositivo" and re.search(r"\bordina\b|\bdispone\b", lowered):
        return "ordine", "Il Tribunale ordina un adempimento specifico"
    if section == "dispositivo" and re.search(r"\bdichiara\b", lowered):
        return "dichiarazione", "Il Tribunale dichiara un effetto o una situazione giuridica"
    if section == "dispositivo" and re.search(r"\bcondanna\b", lowered):
        return "condanna", "Il Tribunale condanna una parte a un adempimento o pagamento"
    if "diffida" in lowered or "atto interruttivo" in lowered:
        return "diffida", "Viene notificata o ricevuta la diffida interruttiva"
    if section == "dispositivo" and ("spese di lite" in lowered or ("condanna" in lowered and "spese" in lowered)):
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
    if (
        section in {"facts", "law", "body"}
        and has_dates
        and re.search(r"\b(?:prestat\w+|lavorat\w+|assunt\w+|svolt\w+\s+servizio|supplenz\w+|incaric\w+)\b", text, re.IGNORECASE)
        and re.search(r"\b(?:anno scolastic\w+|contratt\w+|tempo determinato|tempo indeterminato|docent\w+)\b", text, re.IGNORECASE)
    ):
        return "periodo_lavorativo", "Viene svolto un periodo di lavoro o supplenza"
    for event_type, pattern, label in FACTUAL_EVENT_PATTERNS:
        if event_type == "periodo_lavorativo":
            continue
        if pattern.search(text):
            return event_type, label
    if event_type_hint:
        if event_type_hint == "periodo_lavorativo" and not (
            section in {"facts", "law", "body"}
            and has_dates
            and re.search(r"\b(?:anno scolastic\w+|contratt\w+|tempo determinato|tempo indeterminato|docent\w+)\b", text, re.IGNORECASE)
        ):
            return None
        label = EVENT_TYPE_HINT_LABELS.get(event_type_hint)
        if label:
            if event_type_hint == "sentenza_pronunciata":
                label = f"Il {context['court_name']} pronuncia la sentenza"
            return event_type_hint, label
    return None


def split_dispositivo_into_commands(text: str) -> list[str]:
    normalized = hybrid_rules.normalize_whitespace(text)
    chunks = re.split(r"(?=(?:\b\d+\)|\b(?:dichiara|condanna|ordina|dispone|accoglie|rigetta|annulla|revoca)\b))", normalized, flags=re.IGNORECASE)
    commands = []
    for chunk in chunks:
        cleaned = hybrid_rules.normalize_whitespace(chunk).strip(" -;:,")
        if not cleaned:
            continue
        if cleaned.lower() in {"p.q.m.", "pq.m."}:
            continue
        commands.append(cleaned)
    return commands or [normalized]


def infer_promoted_factual_event(text: str, context: dict, event_type_hint: str | None = None) -> tuple[str, str] | None:
    lowered = text.lower()
    for event_type, pattern, label in PROMOTED_FACTUAL_PATTERNS:
        if pattern.search(text):
            return event_type, label
    if event_type_hint:
        label = EVENT_TYPE_HINT_LABELS.get(event_type_hint)
        if label:
            if event_type_hint == "sentenza_pronunciata":
                return event_type_hint, f"Il {context['court_name']} pronuncia la sentenza"
            return event_type_hint, label
    if "ricevut" in lowered:
        return "diffida", "Viene notificata o ricevuta la diffida interruttiva"
    return None


def infer_fallback_dispositivo_event(text: str) -> tuple[str, str] | None:
    lowered = text.lower()
    if re.search(r"\b(?:definitivamente pronunciando|cos[iì] provvede|p\.q\.m\.)\b", lowered):
        return "decisione", "Il Tribunale definisce il giudizio nel dispositivo"
    return None


def should_promote_factual_block(
    text: str,
    section: str,
    score: float,
    dates: list[dict],
    event_type_hint: str | None,
) -> bool:
    if section not in {"facts", "body", "law"}:
        return False
    if not dates or score <= 4.0:
        return False
    if hybrid_rules.is_jurisprudential_reference_block(text, section):
        return False
    if not event_type_hint:
        if not re.search(r"\b(?:prestat\w+|lavorat\w+|assunt\w+|depositat\w+|ricevut\w+|notificat\w+|indett\w+|bando)\b", text, re.IGNORECASE):
            return False
    return True


def build_event_entries(
    next_id: int,
    page_number: int,
    source_document: str,
    section: str,
    score: float,
    event_type: str,
    event_text: str,
    segment_text: str,
    event_date: str | None,
    certainty: str,
    subjects: list[str],
) -> list[dict]:
    amount = hybrid_rules.extract_amount(segment_text)
    base_entry = {
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
    if amount:
        base_entry["importo"] = amount
    if event_type == "verbale_amministrativo":
        entries = extract_verbale_entries(segment_text)
        if entries:
            built_entries = []
            for offset, entry in enumerate(entries):
                enriched = dict(base_entry)
                enriched["id"] = next_id + offset
                enriched["data"] = entry["data"]
                enriched["certezza_data"] = "esplicita"
                enriched["evento"] = f"Viene elevato il verbale amministrativo n. {entry['numero']}"
                built_entries.append(enriched)
            return built_entries
    return [base_entry]


def should_split_multi_event_block(text: str) -> bool:
    dates = filter_non_reference_dates(text, hybrid_rules.extract_all_dates(text))
    if len(dates) >= 3:
        return True
    action_markers = sum(len(list(pattern.finditer(text))) for _, pattern in hybrid_rules.EVENT_TYPE_PATTERNS)
    if action_markers >= 2:
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


def split_block_into_event_segments(text: str) -> list[dict]:
    lowered_full = text.lower()
    anchor_pattern = re.compile(
        r"(?=(?:all['’]udienza del|alla fissata udienza del|alla prima udienza|nelle more in data|"
        r"con ricorso\b|premesso che in data|con decreto del|notificat\w+\s+via\s+p\.e\.c\.\s+il|"
        r"emess\w+\s+il|pubblicat\w+\s+il|depositat\w*(?:\s+telematicamente)?\s+in\s+data|"
        r"(?:era\s+stato\s+)?indett\w+\s+in\s+data|\brinvi\w+\b|\bfissav\w+\b|\bsi costitu\w+\b|"
        r"\bcomparsa di costituzione\b|\bprecis\w+\s+le conclusioni\b|\bmediazione\b))",
        re.IGNORECASE,
    )
    matches = list(anchor_pattern.finditer(text))
    if len(matches) <= 1:
        dates = filter_non_reference_dates(text, hybrid_rules.extract_all_dates(text))
        return [{"text": text, "event_type_hint": hybrid_rules.detect_event_type_near_dates(text, dates)}]

    segments: list[dict] = []
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
            dates = filter_non_reference_dates(snippet, hybrid_rules.extract_all_dates(snippet))
            segments.append(
                {
                    "text": snippet,
                    "event_type_hint": hybrid_rules.detect_event_type_near_dates(snippet, dates),
                }
            )

    if not segments:
        dates = filter_non_reference_dates(text, hybrid_rules.extract_all_dates(text))
        return [{"text": text, "event_type_hint": hybrid_rules.detect_event_type_near_dates(text, dates)}]
    return segments


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
    return normalized.startswith(
        (
            "a tale udienza",
            "in tale sede",
            "all'udienza indicata",
            "all’udienza indicata",
            "alla predetta udienza",
            "in detta udienza",
            "nel corso di tale udienza",
        )
    )


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
        if re.search(r"\b(?:in tale sede|all['’]udienza indicata|alla predetta udienza|in detta udienza)\b", text, re.IGNORECASE):
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


def get_subject_cache_path(working_dir: Path) -> Path:
    return get_results_dir(working_dir) / "ollama_subject_cache.json"


def load_json_cache(cache_path: Path) -> dict:
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json_cache(cache_path: Path, cache: dict) -> None:
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
) -> tuple[dict, list[dict], list[dict]]:
    events = []
    disambiguation_tasks = []
    factual_ollama_candidates = []
    next_id = 1
    hearing_context_date = None
    propagated_decision_date = decision_date
    for page in source_data.get("pages", []):
        page_number = page.get("page_number")
        page_text = page.get("text", "")
        for block in hybrid_rules.split_into_blocks(page_text):
            text = block["text"]
            section = hybrid_rules.infer_macro_section(text, block["section"])
            if hybrid_rules.is_jurisprudential_reference_block(text, section):
                continue
            if section == "dispositivo":
                raw_segments = split_dispositivo_into_commands(text)
                block_segments = [
                    {
                        "text": snippet,
                        "event_type_hint": hybrid_rules.detect_event_type_near_dates(
                            snippet,
                            filter_non_reference_dates(snippet, hybrid_rules.extract_all_dates(snippet)),
                        ),
                    }
                    for snippet in raw_segments
                ]
            else:
                block_segments = split_block_into_event_segments(text) if should_split_multi_event_block(text) else [
                    {
                        "text": text,
                        "event_type_hint": hybrid_rules.detect_event_type_near_dates(
                            text, filter_non_reference_dates(text, hybrid_rules.extract_all_dates(text))
                        ),
                    }
                ]
            processed_any_segment = False

            for segment in block_segments:
                segment_text = segment["text"]
                score = hybrid_rules.score_block(segment_text, section)
                dates = hybrid_rules.extract_all_dates(segment_text)
                valid_dates = filter_non_reference_dates(segment_text, dates)
                classification = classify_rule_event(segment_text, section, context, segment.get("event_type_hint"))
                if classification is None and section == "dispositivo" and score >= 8:
                    classification = infer_fallback_dispositivo_event(segment_text)
                if classification is None and should_promote_factual_block(
                    segment_text,
                    section,
                    score,
                    valid_dates,
                    segment.get("event_type_hint"),
                ):
                    classification = infer_promoted_factual_event(segment_text, context, segment.get("event_type_hint"))
                if score < 3 and classification is None:
                    continue
                if classification is None and not hybrid_rules.contains_event_signal(segment_text):
                    continue
                if classification is None:
                    if (
                        score >= 5.0
                        and len(valid_dates) >= 1
                        and section in {"body", "facts"}
                        and not hybrid_rules.is_jurisprudential_reference_block(segment_text, section)
                    ):
                        factual_ollama_candidates.extend(
                            build_factual_candidates_for_segment(
                                page_number=page_number,
                                section=section,
                                score=score,
                                valid_dates=valid_dates,
                                segment_text=segment_text,
                            )
                        )
                    inline_dates = extract_inline_udienza_dates(segment_text)
                    if inline_dates:
                        hearing_context_date = inline_dates[-1]
                    continue

                processed_any_segment = True
                event_type, event_text = classification
                event_date, certainty = choose_event_date_with_context(
                    segment_text,
                    valid_dates,
                    event_type,
                    propagated_decision_date,
                    hearing_context_date,
                )
                subjects = hybrid_rules.extract_subjects(segment_text, context)
                block_event_entries = build_event_entries(
                    next_id=next_id,
                    page_number=page_number,
                    source_document=source_document,
                    section=section,
                    score=score,
                    event_type=event_type,
                    event_text=event_text,
                    segment_text=segment_text,
                    event_date=event_date,
                    certainty=certainty,
                    subjects=subjects,
                )

                event_id = block_event_entries[0]["id"]
                events.extend(block_event_entries)
                if event_type == "sentenza_pronunciata" and event_date and not propagated_decision_date:
                    propagated_decision_date = event_date

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
                inline_dates = extract_inline_udienza_dates(segment_text)
                if inline_dates:
                    hearing_context_date = inline_dates[-1]
                elif rinvio_dates:
                    hearing_context_date = rinvio_dates[-1]
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
    }, disambiguation_tasks, factual_ollama_candidates


def build_batched_date_disambiguation_prompt(candidates: list[dict]) -> str:
    payload = [
        {
            "event_id": candidate["event_id"],
            "tipo_evento": candidate["event_type"],
            "date_candidate": candidate["candidate_dates"],
            "testo": candidate["focus_text"],
        }
        for candidate in candidates
    ]
    return (
        "Per ogni elemento dell'array JSON seguente, scegli SOLO la data in cui avviene davvero l'evento processuale. "
        "Non scegliere date di rinvio futuro, di mero riferimento o accessorie.\n"
        "Restituisci SOLO un array JSON valido di oggetti con chiavi event_id e data_evento.\n"
        "Formato esatto:\n"
        '[{"event_id": 1, "data_evento": "YYYY-MM-DD"}, {"event_id": 2, "data_evento": null}]\n'
        "Array da analizzare:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def build_factual_event_prompt(text: str, data: str) -> str:
    return f"""Sei un assistente specializzato nell'analisi di sentenze italiane.
Ti viene fornito un breve estratto di testo da una sentenza e una
data già identificata nel testo. Il tuo compito è descrivere
l'evento accaduto in quella data.

REGOLE FONDAMENTALI:
- Descrivi SOLO eventi esplicitamente menzionati nel testo
- NON inventare dettagli non presenti
- Se il testo non descrive un evento chiaro per quella data,
  restituisci null
- La descrizione deve essere una frase completa in terza persona
- La descrizione deve avere struttura soggetto-verbo-complemento
- La descrizione deve essere max 12 parole
- NON restituire frammenti nominali o titoli di paragrafo
- Scegli tipo_evento tra: periodo_lavorativo, provvedimento_disciplinare,
  revoca_qualifica, modifica_incarico, aggressione, udienza,
  deposito_atto, decreto, chiamata_in_causa, provvedimento_amministrativo,
  accertamento_medico, costituzione_in_giudizio, evento_generico,
  altro_fatto_rilevante

ESEMPI CORRETTI:
- "Il Comandante ritira l'arma di servizio alla ricorrente"
- "Il Prefetto revoca la qualifica di agente di pubblica sicurezza"
- "Il pubblico ministero produce la documentazione in udienza"

ESEMPI ERRATI:
- "La documentazione prodotta"
- "all'udienza del 7.4.2020"
- "viene assegnata"

DATA: {data}

TESTO: {text}

Rispondi ONLY con JSON valido, nessun testo aggiuntivo:
{{"evento": "...", "tipo_evento": "...", "soggetti": ["..."]}}

Se non riesci a identificare un evento chiaro per la data indicata:
{{"evento": null, "tipo_evento": null, "soggetti": []}}"""


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
            "Riduci i blocchi candidati o usa un modello piu' leggero."
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


def normalize_factual_ollama_event(
    raw_data: dict | None,
    candidate: dict,
    context: dict,
    source_document: str,
) -> dict | None:
    if not isinstance(raw_data, dict):
        return None

    raw_event = raw_data.get("evento")
    if raw_event is None:
        return None

    event_text = hybrid_rules.normalize_whitespace(str(raw_event))
    if not event_text or event_text.lower() == "null":
        return None

    event_type, semantic_score = hybrid_rules.classify_factual_event_type(
        candidate["source_text"],
        allowed_types=FACTUAL_OLLAMA_EVENT_TYPES,
    )
    words = event_text.split()
    if len(words) > 20:
        event_text = " ".join(words[:20])
    if len(event_text.split()) > 20:
        return None
    if len(event_text.split()) < 3:
        return None
    if event_text[:1].islower():
        event_text = event_text[:1].upper() + event_text[1:]
    if not re.search(r"\b(?:ha|è|viene|venne|dispone|disponeva|ritira|revoca|produce|autorizza|discute|decide|effettua|assegna|adibisce|subisce)\b", event_text, re.IGNORECASE):
        return None

    normalized_subjects = normalize_subject_enrichment(
        {"soggetti": raw_data.get("soggetti", []) if isinstance(raw_data.get("soggetti"), list) else []},
        {
            "soggetti": [],
            "testo_origine": candidate["source_text"],
            "evento": event_text,
        },
        context,
    )

    return {
        "data": candidate["date"],
        "ora": hybrid_rules.extract_time(candidate["source_text"]),
        "evento": event_text,
        "tipo_evento": event_type,
        "soggetti": normalized_subjects,
        "documento": source_document,
        "pagina": candidate["page_number"],
        "certezza_data": "esplicita",
        "sezione": candidate["section"],
        "score": candidate["score"],
        "score_semantico_tipo": round(semantic_score, 4),
        "testo_origine": hybrid_rules.normalize_event_text(candidate["source_text"]),
        "fonte": "ollama_factual",
    }


def build_factual_candidates_for_segment(
    page_number: int,
    section: str,
    score: float,
    valid_dates: list[dict],
    segment_text: str,
) -> list[dict]:
    candidates = []
    for candidate_date in valid_dates:
        snippet = build_focus_snippet(segment_text, [candidate_date])
        candidates.append(
            {
                "page_number": page_number,
                "section": section,
                "score": score,
                "date": candidate_date["value"],
                "text": snippet,
                "source_text": segment_text,
            }
        )
    return candidates


def disambiguation_cache_key(model: str, candidate: dict) -> str:
    payload = {
        "model": model,
        "event_type": candidate["event_type"],
        "candidate_dates": candidate["candidate_dates"],
        "focus_text": candidate["focus_text"],
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def build_subject_enrichment_prompt(event: dict, context: dict) -> str:
    party_map = context.get("party_map", {})
    valid_subjects = hybrid_rules.deduplicate_subject_list(list(party_map.values()) + list(party_map.keys()))
    return f"""Dato questo testo di una sentenza italiana e questo evento gia' estratto, elenca SOLO i soggetti esplicitamente coinvolti nell'evento.

Regole:
- includi solo soggetti menzionati nel testo
- ammetti parti, giudice, tribunale, enti o amministrazioni
- non inventare nomi o ruoli
- se nessun soggetto e' esplicito, restituisci un array vuoto
- restituisci SOLO JSON valido nel formato: {{"soggetti": ["..."]}}

Tribunale di riferimento: {context["court_name"]}
Giudice di riferimento: {context["judge_name"]}
Soggetti validi di contesto: {json.dumps(valid_subjects, ensure_ascii=False)}
Evento: "{event.get("evento", "")}"
Tipo evento: "{event.get("tipo_evento", "altro")}"
Soggetti gia' trovati: {json.dumps(event.get("soggetti", []), ensure_ascii=False)}
Testo: "{event.get("testo_origine", "")}"
"""


def subject_cache_key(model: str, event: dict) -> str:
    payload = {
        "model": model,
        "evento": event.get("evento"),
        "tipo_evento": event.get("tipo_evento"),
        "testo_origine": event.get("testo_origine"),
        "soggetti": event.get("soggetti", []),
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def deduplicate_subjects(subjects: list[str]) -> list[str]:
    unique = []
    seen = set()
    for subject in subjects:
        normalized = hybrid_rules.normalize_subject_candidate(str(subject))
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def is_clean_final_subject(subject: str) -> bool:
    normalized = hybrid_rules.normalize_subject_candidate(str(subject))
    if not normalized:
        return False
    if re.search(r"[@\[\]{}<>]", normalized):
        return False
    if re.search(r"\d", normalized):
        return False
    if re.search(r"[^A-Za-zÀ-ÖØ-öø-ÿ' .]", normalized):
        return False
    if re.search(r"\b[A-Z]{1,2}\b", normalized) and len(normalized.split()) >= 3:
        return False
    if re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}[@][A-Za-zÀ-ÖØ-öø-ÿ]{2,}", normalized):
        return False
    return True


def sanitize_event_subjects(events: list[dict]) -> list[dict]:
    for event in events:
        subjects = event.get("soggetti", [])
        if not isinstance(subjects, list):
            event["soggetti"] = []
            continue
        cleaned_subjects = []
        for subject in subjects:
            normalized = hybrid_rules.normalize_subject_candidate(str(subject))
            if not is_clean_final_subject(normalized):
                continue
            cleaned_subjects.append(normalized)
        event["soggetti"] = deduplicate_subjects(cleaned_subjects)
    return events


def is_subject_supported_by_text(subject: str, text: str, context: dict) -> bool:
    normalized_subject = hybrid_rules.normalize_subject_candidate(str(subject))
    if not normalized_subject:
        return False
    lowered_subject = normalized_subject.casefold()
    valid_party_subjects = hybrid_rules.deduplicate_subject_list(
        list(context.get("party_map", {}).values()) + list(context.get("party_map", {}).keys())
    )
    if lowered_subject in {
        item.casefold()
        for item in valid_party_subjects
    }:
        return True
    if re.search(rf"(?<!\w){re.escape(normalized_subject)}(?!\w)", text, re.IGNORECASE):
        return True
    return lowered_subject in {
        context["court_name"].casefold(),
        context["judge_name"].casefold(),
    }


def is_plausible_subject_candidate(subject: str) -> bool:
    if not hybrid_rules.is_valid_subject_candidate(subject):
        return False
    lowered = subject.casefold()
    if re.search(r"\b(?:rifondere|pagare|corrispondere|accogliere|rigettare|dichiarare|condannare)\b", lowered):
        return False
    if re.search(r"\b(?:il|la|lo|gli|le)\s+(?:a|di|da|per)\b", lowered):
        return False
    return True


def normalize_subject_enrichment(raw_data: dict | None, event: dict, context: dict) -> list[str]:
    existing = deduplicate_subjects(event.get("soggetti", []))
    if not isinstance(raw_data, dict):
        return existing

    raw_subjects = raw_data.get("soggetti")
    if not isinstance(raw_subjects, list):
        return existing

    source_text = " ".join(
        [
            str(event.get("testo_origine", "")),
            str(event.get("evento", "")),
        ]
    )
    validated = list(existing)
    for raw_subject in raw_subjects:
        candidate = hybrid_rules.normalize_subject_candidate(str(raw_subject))
        if not is_plausible_subject_candidate(candidate):
            continue
        if not is_subject_supported_by_text(candidate, source_text, context):
            continue
        validated.append(candidate)
    return deduplicate_subjects(validated)[:8]


def apply_disambiguation_results(events: list[dict], results: list[dict]) -> list[dict]:
    updates = {item["event_id"]: item["resolved_date"] for item in results if item.get("resolved_date")}
    for event in events:
        if event["id"] in updates:
            event["data"] = updates[event["id"]]
            event["certezza_data"] = "esplicita"
            event["fonte"] = "regole_hybrid_ollama_data"
    return events


def run_factual_ollama_enrichment(
    model: str,
    candidates: list[dict],
    context: dict,
    timeout: int,
    source_document: str,
) -> tuple[list[dict], int]:
    created_events = []
    for index, candidate in enumerate(candidates, start=1):
        print(
            f"  Fatti Ollama {index}/{len(candidates)}: pagina {candidate['page_number']}",
            file=sys.stderr,
        )
        prompt = build_factual_event_prompt(candidate["text"], candidate["date"])
        try:
            raw_output = run_ollama(model, prompt, timeout)
        except RuntimeError as exc:
            print(f"    Ollama errore fatti: {exc}", file=sys.stderr)
            continue

        parsed = extract_json_object(raw_output)
        normalized = normalize_factual_ollama_event(parsed, candidate, context, source_document)
        if normalized is None:
            continue
        created_events.append(normalized)

    return created_events, len(created_events)


def rescue_missing_event_dates(events: list[dict], decision_date: str | None) -> list[dict]:
    for event in events:
        if event.get("data"):
            continue
        source_text = str(event.get("testo_origine", ""))
        valid_dates = filter_non_reference_dates(source_text, hybrid_rules.extract_all_dates(source_text))
        if not valid_dates:
            continue
        recovered_date, certainty = hybrid_rules.choose_event_date(
            source_text,
            valid_dates,
            str(event.get("tipo_evento", "altro")),
            decision_date,
        )
        if recovered_date:
            event["data"] = recovered_date
            event["certezza_data"] = certainty if recovered_date else "assente"
            if event.get("fonte") == "regole_hybrid":
                event["fonte"] = "regole_hybrid_data_rescue"
    return events


def rebuild_rule_event_buckets(events: list[dict], decision_date: str | None = None) -> tuple[list[dict], list[dict]]:
    rescued_events = rescue_missing_event_dates(events, decision_date)
    sanitized_events = sanitize_event_subjects(rescued_events)
    same_date_deduped_events = deduplicate_same_date_events(sanitized_events)
    unique_events = deduplicate_combined_events(same_date_deduped_events)
    dated_events = hybrid_rules.sort_events([event for event in unique_events if event.get("data")])
    undated_events = hybrid_rules.sort_events(
        filter_low_confidence_undated([event for event in unique_events if not event.get("data")])
    )
    for index, event in enumerate(dated_events + undated_events, start=1):
        event["id"] = index
    return dated_events, undated_events


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
    cache = load_json_cache(cache_path)
    resolved = []
    cache_hits = 0
    cache_changed = False
    pending_candidates = []

    for candidate in candidates:
        cache_key = disambiguation_cache_key(model, candidate)
        cached_value = cache.get(cache_key)
        if cached_value in candidate["candidate_dates"] or cached_value is None:
            if cache_key in cache:
                cache_hits += 1
                resolved.append({"event_id": candidate["event_id"], "resolved_date": cached_value})
                continue
        pending_candidates.append(candidate)

    for batch_start in range(0, len(pending_candidates), DATE_DISAMBIGUATION_BATCH_SIZE):
        batch = pending_candidates[batch_start:batch_start + DATE_DISAMBIGUATION_BATCH_SIZE]
        print(
            f"  Disambiguazione batch {batch_start // DATE_DISAMBIGUATION_BATCH_SIZE + 1}: {len(batch)} eventi",
            file=sys.stderr,
        )
        prompt = build_batched_date_disambiguation_prompt(batch)
        try:
            raw_output = run_ollama(model, prompt, timeout)
        except RuntimeError as exc:
            print(f"    Ollama errore: {exc}", file=sys.stderr)
            for candidate in batch:
                resolved.append({"event_id": candidate["event_id"], "resolved_date": None})
            continue

        parsed = extract_json_array(raw_output)
        parsed_by_event_id = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            raw_event_id = item.get("event_id")
            if isinstance(raw_event_id, int):
                parsed_by_event_id[raw_event_id] = item
            elif str(raw_event_id).isdigit():
                parsed_by_event_id[int(raw_event_id)] = item

        for candidate in batch:
            cache_key = disambiguation_cache_key(model, candidate)
            raw_result = parsed_by_event_id.get(candidate["event_id"], {"data_evento": None})
            resolved_date = normalize_disambiguated_date(raw_result, candidate)
            cache[cache_key] = resolved_date
            cache_changed = True
            resolved.append({"event_id": candidate["event_id"], "resolved_date": resolved_date})

    if cache_changed:
        save_json_cache(cache_path, cache)
    return resolved, len(resolved), cache_hits


def select_subject_enrichment_candidates(events: list[dict], max_events: int) -> list[dict]:
    prioritized = sorted(
        events,
        key=lambda event: (
            0 if not event.get("soggetti") else 1,
            -(event.get("score") or 0),
            0 if event.get("data") else 1,
            event.get("pagina") or 0,
            event.get("id", 0),
        ),
    )
    return prioritized[:max_events]


def enrich_subjects_with_ollama(
    model: str,
    events: list[dict],
    context: dict,
    timeout: int,
    cache_path: Path,
    max_events: int,
) -> tuple[list[dict], int, int]:
    candidates = select_subject_enrichment_candidates(events, max_events)
    if not candidates:
        return events, 0, 0

    cache = load_json_cache(cache_path)
    cache_hits = 0
    enriched_count = 0
    cache_changed = False

    for index, event in enumerate(candidates, start=1):
        print(
            f"  Soggetti {index}/{len(candidates)}: evento {event['id']} pagina {event.get('pagina')}",
            file=sys.stderr,
        )
        cache_key = subject_cache_key(model, event)
        cached_value = cache.get(cache_key)
        if isinstance(cached_value, list):
            normalized_subjects = normalize_subject_enrichment({"soggetti": cached_value}, event, context)
            cache_hits += 1
        else:
            prompt = build_subject_enrichment_prompt(event, context)
            try:
                raw_output = run_ollama(model, prompt, timeout)
            except RuntimeError as exc:
                print(f"    Ollama errore soggetti: {exc}", file=sys.stderr)
                continue
            parsed = extract_json_object(raw_output)
            normalized_subjects = normalize_subject_enrichment(parsed, event, context)
            cache[cache_key] = normalized_subjects
            cache_changed = True

        previous_subjects = deduplicate_subjects(event.get("soggetti", []))
        if normalized_subjects != previous_subjects:
            event["soggetti"] = normalized_subjects
            event["fonte"] = f"{event.get('fonte', 'regole_hybrid')}_ollama_soggetti"
            enriched_count += 1

    if cache_changed:
        save_json_cache(cache_path, cache)
    return events, enriched_count, cache_hits


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


def event_source_priority(event: dict) -> int:
    source = str(event.get("fonte", ""))
    if source.startswith("ollama_factual"):
        return 3
    if source.startswith("regole_hybrid_ollama"):
        return 2
    if source.startswith("regole_hybrid"):
        return 1
    return 0


def deduplicate_same_date_events(events: list[dict]) -> list[dict]:
    return hybrid_rules.deduplicate_same_date_events_semantically(
        events,
        similarity_threshold=SEMANTIC_DEDUPLICATION_THRESHOLD,
        priority_fn=event_source_priority,
    )


def main() -> int:
    args = parse_args()
    working_dir = Path.cwd()
    input_path = choose_input_path(args.input_json, working_dir)
    if not input_path.exists():
        print(f"Errore: JSON non trovato: {input_path}", file=sys.stderr)
        return 1
    try:
        hybrid_rules.ensure_embedding_backend()
    except RuntimeError as exc:
        print(f"Errore embedding: {exc}", file=sys.stderr)
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
    rule_baseline, disambiguation_tasks, factual_ollama_candidates = build_rule_baseline(
        source_data,
        input_path.name,
        source_document,
        context,
        decision_date,
    )
    rule_baseline["eventi_non_datati"] = hybrid_rules.sort_events(
        filter_low_confidence_undated(rule_baseline["eventi_non_datati"])
    )
    rule_baseline["eventi"], rule_baseline["eventi_non_datati"] = rebuild_rule_event_buckets(
        rule_baseline["eventi"] + rule_baseline["eventi_non_datati"],
        decision_date,
    )

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
        f"Analizzo {input_path.name} con timeline_embedding: {len(candidates)} blocchi candidati, {len(difficult_candidates)} ambigui da disambiguare...",
        file=sys.stderr,
    )

    results_dir = get_results_dir(working_dir)
    results_dir.mkdir(exist_ok=True)
    cache_path = get_disambiguation_cache_path(working_dir)
    subject_cache_path = get_subject_cache_path(working_dir)
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
            rule_baseline["eventi"], rule_baseline["eventi_non_datati"] = rebuild_rule_event_buckets(
                updated_events,
                decision_date,
            )
        except RuntimeError as exc:
            print(f"Disambiguazione Ollama non riuscita: {exc}", file=sys.stderr)

    subject_enriched_count = 0
    subject_cache_hits = 0
    factual_ollama_count = 0
    all_events = rule_baseline["eventi"] + rule_baseline["eventi_non_datati"]
    try:
        factual_events, factual_ollama_count = run_factual_ollama_enrichment(
            args.model,
            factual_ollama_candidates,
            context,
            args.ollama_timeout,
            source_document,
        )
        if factual_events:
            all_events = all_events + factual_events
            rule_baseline["eventi"], rule_baseline["eventi_non_datati"] = rebuild_rule_event_buckets(
                all_events,
                decision_date,
            )
            all_events = rule_baseline["eventi"] + rule_baseline["eventi_non_datati"]
    except RuntimeError as exc:
        print(f"Arricchimento fatti Ollama non riuscito: {exc}", file=sys.stderr)

    try:
        enriched_events, subject_enriched_count, subject_cache_hits = enrich_subjects_with_ollama(
            args.model,
            all_events,
            context,
            args.ollama_timeout,
            subject_cache_path,
            args.max_subject_events,
        )
        rule_baseline["eventi"], rule_baseline["eventi_non_datati"] = rebuild_rule_event_buckets(
            enriched_events,
            decision_date,
        )
    except RuntimeError as exc:
        print(f"Arricchimento soggetti Ollama non riuscito: {exc}", file=sys.stderr)

    merged = {
        "source_json": rule_baseline["source_json"],
        "documento": rule_baseline["documento"],
        "contesto_documento": rule_baseline["contesto_documento"],
        "eventi": rule_baseline["eventi"],
        "eventi_non_datati": rule_baseline["eventi_non_datati"],
    }

    merged["eventi_non_datati"] = hybrid_rules.sort_events(filter_low_confidence_undated(merged["eventi_non_datati"]))
    for index, event in enumerate(merged["eventi"] + merged["eventi_non_datati"], start=1):
        event["id"] = index

    final_decision_date = decision_date or infer_decision_date_from_events(merged["eventi"])

    merged["metriche"] = {
        "modello_ollama": args.model,
        "modello_embedding": hybrid_rules.EMBEDDING_MODEL_NAME,
        "soglia_deduplica_semantica": SEMANTIC_DEDUPLICATION_THRESHOLD,
        "blocchi_candidati": len(candidates),
        "blocchi_ambigui": len(difficult_candidates),
        "eventi_regole_datati": len(rule_baseline["eventi"]),
        "eventi_regole_non_datati": len(rule_baseline["eventi_non_datati"]),
        "eventi_ollama": factual_ollama_count,
        "disambiguazioni_ollama": disambiguated_count,
        "cache_hit_disambiguazioni": cache_hits,
        "soggetti_arricchiti_ollama": subject_enriched_count,
        "cache_hit_soggetti": subject_cache_hits,
        "eventi_finali_datati": len(merged["eventi"]),
        "eventi_finali_non_datati": len(merged["eventi_non_datati"]),
        "decision_date": final_decision_date,
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
    output_path = results_dir / f"{input_path.stem}_timeline_embedding.json"
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Timeline salvata in: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
