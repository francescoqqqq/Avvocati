#!/usr/bin/env python3
import re
from datetime import date
from difflib import get_close_matches


ITALIAN_CITIES = {
    "Agrigento", "Alessandria", "Ancona", "Aosta", "Arezzo", "Ascoli Piceno", "Asti", "Avellino",
    "Bari", "Barletta", "Belluno", "Benevento", "Bergamo", "Biella", "Bologna", "Bolzano",
    "Brescia", "Brindisi", "Cagliari", "Caltanissetta", "Campobasso", "Caserta", "Catania",
    "Catanzaro", "Chieti", "Como", "Cosenza", "Cremona", "Crotone", "Cuneo", "Enna", "Fermo",
    "Ferrara", "Firenze", "Foggia", "Forlì", "Frosinone", "Genova", "Gorizia", "Grosseto",
    "Imperia", "Isernia", "L'Aquila", "La Spezia", "Latina", "Lecce", "Lecco", "Livorno",
    "Lodi", "Lucca", "Macerata", "Mantova", "Massa", "Matera", "Messina", "Milano", "Modena",
    "Monza", "Napoli", "Novara", "Nuoro", "Oristano", "Padova", "Palermo", "Parma", "Pavia",
    "Perugia", "Pesaro", "Pescara", "Piacenza", "Pisa", "Pistoia", "Pordenone", "Potenza",
    "Prato", "Ragusa", "Ravenna", "Reggio Calabria", "Reggio Emilia", "Rieti", "Rimini", "Roma",
    "Rovigo", "Salerno", "Sassari", "Savona", "Siena", "Siracusa", "Sondrio", "Taranto",
    "Teramo", "Terni", "Torino", "Trapani", "Trento", "Treviso", "Trieste", "Udine", "Varese",
    "Venezia", "Verbano Cusio Ossola", "Vercelli", "Verona", "Vibo Valentia", "Vicenza", "Viterbo",
}

MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}

HEADER_NOISE = [
    re.compile(r"^pagina \d+ di \d+$", re.IGNORECASE),
    re.compile(r"^pag\.\s*\d+/\d+$", re.IGNORECASE),
    re.compile(r"^firmato da:.*", re.IGNORECASE),
    re.compile(r"^sentenza n\..*\bpubbl\.\b.*", re.IGNORECASE),
    re.compile(r"^sentenza n\.\s*cronol\..*", re.IGNORECASE),
    re.compile(r"^rg n\..*", re.IGNORECASE),
    re.compile(r"^repert\. n\..*", re.IGNORECASE),
    re.compile(r"^copia non ufficiale.*", re.IGNORECASE),
]

NEGATIVE_PATTERNS = [
    re.compile(r"\bCass\.", re.IGNORECASE),
    re.compile(r"\bSS\.UU\.", re.IGNORECASE),
    re.compile(r"\bCorte di Cassazione\b", re.IGNORECASE),
    re.compile(r"\bCorte di giustizia\b", re.IGNORECASE),
    re.compile(r"\bCGUE\b", re.IGNORECASE),
    re.compile(r"\bConsiglio di Stato\b", re.IGNORECASE),
    re.compile(r"\bCorte Appello\b", re.IGNORECASE),
    re.compile(r"\bart\.\s*\d+", re.IGNORECASE),
    re.compile(r"\bd\.lgs\.", re.IGNORECASE),
    re.compile(r"\blegge\s+\d+", re.IGNORECASE),
    re.compile(r"\bDirettiva\b", re.IGNORECASE),
]
THIRD_PARTY_DECISION_PATTERN = re.compile(r"\bn\.\s*\d+/\d{2,4}\b", re.IGNORECASE)
NUMERIC_DATE_PATTERN = re.compile(r"\b(\d{1,2})\s*([./-])\s*(\d{1,2})\s*\2\s*(\d{2,4})\b")
DECISION_MENTION_PATTERN = re.compile(
    r"\b(?:sentenza|ordinanza|decisione|pronuncia)\s+n\.\s*\d+/\d{2,4}\b",
    re.IGNORECASE,
)
EXTERNAL_COURT_PATTERN = re.compile(
    r"\b(?:cassazione|corte di cassazione|corte di giustizia|cgue|consiglio di stato|corte costituzionale|tar|t\.a\.r\.)\b",
    re.IGNORECASE,
)

SECTION_HINTS = {
    "header": [
        re.compile(r"\bREPUBBLICA ITALIANA\b", re.IGNORECASE),
        re.compile(r"\bIN NOME DEL POPOLO ITALIANO\b", re.IGNORECASE),
        re.compile(r"^TRIBUNALE(?:\s+ORDINARIO)?(?:\s+DI\s+[A-ZÀ-ÖØ-öø-ÿ' ]+)?$", re.IGNORECASE),
        re.compile(r"^SEZIONE(?:\s+[A-ZÀ-ÖØ-öø-ÿ' ]+)?$", re.IGNORECASE),
    ],
    "conclusioni": [
        re.compile(r"\bCONCLUSIONI(?:\s+DELLE\s+PARTI)?\b", re.IGNORECASE),
        re.compile(r"\bPRECISAZIONE\s+DELLE\s+CONCLUSIONI\b", re.IGNORECASE),
        re.compile(r"\bnota di precisazione delle conclusioni\b", re.IGNORECASE),
    ],
    "facts": [
        re.compile(r"\bSVOLGIMENTO\b", re.IGNORECASE),
        re.compile(r"\bRAGIONI DI FATTO\b", re.IGNORECASE),
        re.compile(r"\bMOTIVI IN FATTO\b", re.IGNORECASE),
        re.compile(r"\bFATTO DEL PROCESSO\b", re.IGNORECASE),
    ],
    "law": [
        re.compile(r"\bMOTIVI IN DIRITTO\b", re.IGNORECASE),
        re.compile(r"\bRAGIONI DI DIRITTO\b", re.IGNORECASE),
        re.compile(r"\bDECISIONE\b", re.IGNORECASE),
    ],
    "dispositivo": [
        re.compile(r"\bP\.Q\.M\.\b", re.IGNORECASE),
        re.compile(r"\bcos[iì] provvede\b", re.IGNORECASE),
        re.compile(r"\bdefinitivamente pronunciando\b", re.IGNORECASE),
        re.compile(r"\bcosì deciso\b", re.IGNORECASE),
    ],
}

HYBRID_SIGNAL_PATTERNS = [
    re.compile(r"\bricorso\b", re.IGNORECASE),
    re.compile(r"\bcostitu", re.IGNORECASE),
    re.compile(r"\budienza\b", re.IGNORECASE),
    re.compile(r"\bmediazione\b", re.IGNORECASE),
    re.compile(r"\bdecreto\b", re.IGNORECASE),
    re.compile(r"\bsentenza\b", re.IGNORECASE),
    re.compile(r"\brigetta\b", re.IGNORECASE),
    re.compile(r"\baccoglie\b", re.IGNORECASE),
    re.compile(r"\bdichiara\b", re.IGNORECASE),
    re.compile(r"\brevoca\b", re.IGNORECASE),
    re.compile(r"\bcondanna\b", re.IGNORECASE),
    re.compile(r"\bspese\b", re.IGNORECASE),
    re.compile(r"\bctu\b", re.IGNORECASE),
    re.compile(r"\bconsulenza\b", re.IGNORECASE),
    re.compile(r"\brinvia", re.IGNORECASE),
    re.compile(r"\bfissava\b", re.IGNORECASE),
    re.compile(r"\bnotificat", re.IGNORECASE),
    re.compile(r"\bpubblicat", re.IGNORECASE),
    re.compile(r"\bprestat\w*", re.IGNORECASE),
    re.compile(r"\bservizio\b", re.IGNORECASE),
    re.compile(r"\bincaric\w*", re.IGNORECASE),
    re.compile(r"\bsupplenz\w*", re.IGNORECASE),
    re.compile(r"\bdiffid\w*", re.IGNORECASE),
    re.compile(r"\bricevut\w*", re.IGNORECASE),
]

SECTION_MULTIPLIERS = {
    "header": 1.0,
    "body": 0.95,
    "facts": 1.25,
    "law": 0.95,
    "dispositivo": 1.35,
    "conclusioni": 0.1,
}

REQUEST_LIKE_PATTERNS = [
    re.compile(r"\b(?:chiede|chiedono|chiedeva|domanda|domandano|invoca|chiest[oa]|richiede|richiedono)\b", re.IGNORECASE),
    re.compile(r"\b(?:voglia|vogliono)\b", re.IGNORECASE),
    re.compile(r"\b(?:annullarsi|revocarsi|dichiararsi|accertarsi|disporsi|condannarsi|rigettarsi|respingersi)\b", re.IGNORECASE),
    re.compile(r"\bin via (?:preliminare|principale|subordinata|istruttoria)\b", re.IGNORECASE),
]

EVENT_TYPE_PATTERNS = [
    ("deposito_ricorso", re.compile(r"\bdepositat\w*(?:\s+telematicamente)?\b.{0,80}\bricorso\b|\bricorso\b.{0,120}\bdepositat\w*", re.IGNORECASE)),
    ("notifica", re.compile(r"\bnotificat\w+\b|\bvia\s+p\.e\.c\.\b", re.IGNORECASE)),
    ("fissazione_udienza", re.compile(r"\bfissav\w+\b.{0,60}\budienza\b|\bcon decreto del\b.{0,100}\bfissav\w+\b", re.IGNORECASE)),
    ("rinvio", re.compile(r"\brinvi\w+\b", re.IGNORECASE)),
    ("mediazione", re.compile(r"\bmediazione\b", re.IGNORECASE)),
    ("precisazione_conclusioni", re.compile(r"\bprecis\w*\b.{0,40}\bconclusion\w*\b", re.IGNORECASE)),
    ("sentenza_pronunciata", re.compile(r"\bha\s+pronunciat\w*\b.{0,80}\bsentenza\b|\bha\s+pronunziat\w*\b.{0,80}\bsentenza\b", re.IGNORECASE)),
    ("decreto_ingiuntivo", re.compile(r"\bdecreto ingiuntivo\b.{0,80}\b(?:emess\w+|pubblicat\w+)\b|\b(?:emess\w+|pubblicat\w+)\b.{0,80}\bdecreto ingiuntivo\b", re.IGNORECASE)),
    ("costituzione", re.compile(r"\bsi costitu\w+\b|\bcomparsa di costituzione\b|\bcostituzione in giudizio\b", re.IGNORECASE)),
    ("verbale_amministrativo", re.compile(r"\bverbale n\.\s*\d+/\d+\b|\bverbali di accertamento\b", re.IGNORECASE)),
    ("diffida", re.compile(r"\bdiffid\w+\b|\batto interruttivo\b|\bricevut\w+\b.{0,60}\bministero\b", re.IGNORECASE)),
    ("periodo_lavorativo", re.compile(r"\b(?:prestat\w+|lavorat\w+|assunt\w+|svolt\w+\s+servizio|supplenz\w+|incaric\w+)\b", re.IGNORECASE)),
]

LEGAL_ROLE_LABELS = {
    "ricorrente": "Ricorrente",
    "ricorrenti": "Ricorrenti",
    "resistente": "Resistente",
    "resistenti": "Resistenti",
    "opponente": "Opponente",
    "opposto": "Opposto",
    "opposti": "Opposti",
    "convenuto": "Convenuto",
    "convenuta": "Convenuta",
    "attore": "Attore",
    "attrice": "Attrice",
    "appellante": "Appellante",
    "appellato": "Appellato",
    "imputato": "Imputato",
    "imputata": "Imputata",
    "parte civile": "Parte civile",
}
ROLE_REFERENCE_PATTERNS = {
    "Opponente": re.compile(r"\bl['’]?\s*opponente\b|\bopponente\b|\bparte opponente\b", re.IGNORECASE),
    "Opposto": re.compile(r"\bl['’]?\s*opposto\b|\bopposto\b|\bparte opposta\b", re.IGNORECASE),
    "Convenuto": re.compile(r"\bil convenuto\b|\bla convenuta\b|\bconvenut[oa]\b|\bparte convenuta\b", re.IGNORECASE),
    "Attore": re.compile(r"\bl['’]?\s*attore\b|\bl['’]?\s*attrice\b|\battore\b|\battrice\b|\bparte attrice\b", re.IGNORECASE),
    "Ricorrente": re.compile(r"\bil ricorrente\b|\bla ricorrente\b|\bricorrent[ei]\b|\bparte ricorrente\b", re.IGNORECASE),
    "Resistente": re.compile(r"\bil resistente\b|\bla resistente\b|\bresistent[ei]\b|\bparte resistente\b", re.IGNORECASE),
    "Imputato": re.compile(r"\bl['’]?\s*imputat[oa]\b|\bimputat[oa]\b", re.IGNORECASE),
}

SUBJECT_STOPWORDS = {
    "il",
    "la",
    "gli",
    "le",
    "i",
    "di",
    "del",
    "della",
    "delle",
    "dei",
    "da",
    "in",
    "con",
    "per",
    "a",
    "al",
    "alla",
    "alle",
    "ai",
    "ed",
    "e",
}


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_event_text(text: str) -> str:
    compact = normalize_whitespace(text)
    compact = re.sub(r"^(?:all['’]udienza del|con decreto del|in data)\s+", "", compact, flags=re.IGNORECASE)
    return compact[:220].rstrip(" ,;:.")


def normalize_city_name(raw_city: str) -> str:
    cleaned = normalize_whitespace(raw_city).strip(" ,.;:-")
    if not cleaned:
        return cleaned
    lowered_map = {city.lower(): city for city in ITALIAN_CITIES}
    if cleaned.lower() in lowered_map:
        return lowered_map[cleaned.lower()]
    matches = get_close_matches(cleaned.lower(), list(lowered_map.keys()), n=1, cutoff=0.72)
    if matches:
        return lowered_map[matches[0]]
    return cleaned.title()


def clean_line(line: str) -> str:
    return normalize_whitespace(line.replace("\u0000", ""))


def clean_page_text(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = clean_line(raw_line)
        if not line:
            continue
        if any(pattern.match(line) for pattern in HEADER_NOISE):
            continue
        lines.append(line)
    return "\n".join(lines)


def infer_macro_section(text: str, current_section: str = "body") -> str:
    normalized = normalize_whitespace(text)
    if current_section != "body":
        return current_section
    for section_name, patterns in SECTION_HINTS.items():
        if section_name == "header":
            continue
        if any(pattern.search(normalized) for pattern in patterns):
            return section_name
    if re.search(r"\b(?:tra|contro|nei confronti di)\b", normalized, re.IGNORECASE):
        return "header"
    return current_section


def is_request_like_block(text: str, section: str) -> bool:
    macro_section = infer_macro_section(text, section)
    if macro_section == "conclusioni":
        return True
    return any(pattern.search(text) for pattern in REQUEST_LIKE_PATTERNS)


def detect_event_type_hint(text: str) -> str | None:
    best_type = None
    best_score = None
    for event_type, pattern in EVENT_TYPE_PATTERNS:
        for match in pattern.finditer(text):
            score = match.start()
            if best_score is None or score < best_score:
                best_type = event_type
                best_score = score
    return best_type


def detect_event_type_near_dates(text: str, dates: list[dict]) -> str | None:
    if not dates:
        return detect_event_type_hint(text)
    best_type = None
    best_distance = None
    for event_type, pattern in EVENT_TYPE_PATTERNS:
        for match in pattern.finditer(text):
            for date_match in re.finditer(r"\b(?:\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}|\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})\b", text, re.IGNORECASE):
                distance = min(abs(match.start() - date_match.start()), abs(match.end() - date_match.end()))
                if best_distance is None or distance < best_distance:
                    best_type = event_type
                    best_distance = distance
    return best_type or detect_event_type_hint(text)


def is_jurisprudential_reference_block(text: str, section: str) -> bool:
    lowered = normalize_whitespace(text.lower())
    if section in {"header", "dispositivo"}:
        return False
    has_external_court = bool(EXTERNAL_COURT_PATTERN.search(lowered) or "giudice del rinvio" in lowered)
    has_third_party_number = bool(THIRD_PARTY_DECISION_PATTERN.search(text))
    has_decision_mention = bool(DECISION_MENTION_PATTERN.search(text))
    has_current_decision_markers = bool(
        re.search(r"\b(?:p\.q\.m\.|cos[iì] deciso|ha pronunciato la seguente sentenza|il tribunale definitivamente pronunciando)\b", lowered)
    )
    if has_current_decision_markers:
        return False
    if has_external_court and (has_third_party_number or has_decision_mention):
        return True
    if has_external_court and re.search(r"\b(?:si richiama|come affermato|secondo|in applicazione di|si veda)\b", lowered):
        return True
    return bool(has_decision_mention and has_third_party_number)


def split_into_blocks(page_text: str) -> list[dict]:
    cleaned = clean_page_text(page_text)
    raw_lines = [line for line in cleaned.splitlines() if line]

    current_section = "body"
    blocks: list[dict] = []
    buffer: list[str] = []

    def flush_buffer() -> None:
        if buffer:
            text = normalize_whitespace(" ".join(buffer)).strip(" -;:,")
            if text:
                blocks.append({"section": infer_macro_section(text, current_section), "text": text})
            buffer.clear()

    def is_header_line(line: str) -> bool:
        return any(pattern.search(line) for pattern in SECTION_HINTS["header"])

    for line in raw_lines:
        matched_section = None
        for section_name, patterns in SECTION_HINTS.items():
            if any(pattern.search(line) for pattern in patterns):
                matched_section = section_name
                break

        if current_section == "header" and buffer and not is_header_line(line):
            flush_buffer()
            current_section = "body"

        if matched_section is not None:
            flush_buffer()
            current_section = matched_section
            buffer.append(line)
            continue

        if re.match(r"^\d+\)", line) or re.match(r"^- ", line):
            flush_buffer()
            buffer.append(line)
            continue

        if buffer and buffer[-1].endswith((".", ";", ":")):
            flush_buffer()
        buffer.append(line)

    flush_buffer()
    return blocks


def parse_numeric_date(day: str, month: str, year: str) -> str | None:
    year_int = int(year)
    if year_int < 100:
        year_int += 2000 if year_int <= 50 else 1900
    try:
        return date(year_int, int(month), int(day)).isoformat()
    except ValueError:
        return None


def extract_all_dates(text: str) -> list[dict]:
    dates = []
    seen = set()
    for match in NUMERIC_DATE_PATTERN.finditer(text):
        iso_date = parse_numeric_date(match.group(1), match.group(3), match.group(4))
        if iso_date:
            key = (iso_date, match.group(0))
            if key not in seen:
                seen.add(key)
                dates.append({"value": iso_date, "raw": match.group(0), "kind": "numeric"})
    for match in re.finditer(
        r"\b(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    ):
        try:
            iso_date = date(int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1))).isoformat()
            key = (iso_date, match.group(0))
            if key not in seen:
                seen.add(key)
                dates.append({"value": iso_date, "raw": match.group(0), "kind": "textual"})
        except ValueError:
            pass
    return dates


def extract_header_metadata(source_data: dict) -> dict:
    metadata = {
        "decision_date": None,
        "publication_date": None,
        "sentence_number": None,
        "rg_number": None,
    }
    pages = source_data.get("pages", [])
    if not pages:
        return metadata

    search_pages = pages[:2] + pages[-1:]
    search_text = "\n".join(page.get("text", "") for page in search_pages)

    sentence_patterns = (
        re.compile(
            r"\bSentenza\s+n\.\s*([0-9]+/[0-9]{4})\s+del\s+(\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4})\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bSentenza\s+n\.\s*([0-9]+/[0-9]{4})\s+del\s+(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bSentenza\s+(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})\s+n\.\s*([0-9]+(?:/[0-9]{4})?)\b",
            re.IGNORECASE,
        ),
    )
    for pattern in sentence_patterns:
        match = pattern.search(search_text)
        if not match:
            continue
        if pattern.pattern.startswith(r"\bSentenza\s+(\d{1,2}\s+"):
            raw_date = match.group(1)
            metadata["sentence_number"] = match.group(2)
        else:
            metadata["sentence_number"] = match.group(1)
            raw_date = match.group(2)
        values = extract_all_dates(raw_date)
        if values:
            metadata["decision_date"] = values[0]["value"]
        break

    publication_patterns = (
        re.compile(r"\bpubbl\.\s*il\s*(\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4})\b", re.IGNORECASE),
        re.compile(r"\bpubblicat\w*\s+il\s+(\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4})\b", re.IGNORECASE),
        re.compile(r"\bRepert\.\s*n\.\s*[0-9]+/[0-9]{4}\s+del\s+(\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4})\b", re.IGNORECASE),
    )
    for pattern in publication_patterns:
        match = pattern.search(search_text)
        if not match:
            continue
        values = extract_all_dates(match.group(1))
        if values:
            metadata["publication_date"] = values[0]["value"]
            break

    rg_match = re.search(
        r"(?:\bR\.?G\.?\s*n\.\s*([0-9]+/[0-9]{4})\b|\bN\.\s*([0-9]+/[0-9]{4})\s*R\.?G\.?\b)",
        search_text,
        re.IGNORECASE,
    )
    if rg_match:
        metadata["rg_number"] = rg_match.group(1) or rg_match.group(2)

    return metadata


def extract_time(text: str) -> str | None:
    match = re.search(r"(?<![\d./-])(?:ore\s*)?(\d{1,2})[:.](\d{2})(?!\d)(?![./-]\d)(?!,\d)", text, re.IGNORECASE)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def get_date_context_window(text: str, raw_date: str, radius: int = 90) -> str:
    match = re.search(re.escape(raw_date), text, re.IGNORECASE)
    if not match:
        return normalize_whitespace(text.lower())
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return normalize_whitespace(text[start:end].lower())


def classify_date_role(text: str, raw_date: str) -> str:
    window = get_date_context_window(text, raw_date)
    match = re.search(re.escape(raw_date), text, re.IGNORECASE)
    prefix = ""
    suffix = ""
    if match:
        prefix = normalize_whitespace(text[max(0, match.start() - 40):match.start()].lower())
        suffix = normalize_whitespace(text[match.end():min(len(text), match.end() + 40)].lower())
    if (
        re.search(r"(?:\bnat[oa]\s+(?:il|a)\b|\bnascit\w*)", prefix)
        or re.search(r"(?:\(\s*n\.\s*|\bn\.\s*)$", prefix)
        or re.search(r"^\s*\)", suffix)
    ):
        return "data_nascita"
    if EXTERNAL_COURT_PATTERN.search(window) and (
        THIRD_PARTY_DECISION_PATTERN.search(window)
        or DECISION_MENTION_PATTERN.search(window)
        or re.search(r"\b(?:si richiama|come affermato|secondo|conforme a|in applicazione di)\b", window)
    ):
        return "citazione_giurisprudenziale"
    if (
        "art." in window
        or "d.lgs" in window
        or "legge" in window
        or "direttiva" in window
        or "delibera" in window
        or "deliberazione" in window
    ):
        return "riferimento_normativo"
    if "pubblicat" in window or "pubbl." in window:
        return "pubblicazione"
    if "indetto" in window or ("bando" in window and "concorso" in window):
        return "atto_contestato"
    if "udienza" in window:
        return "udienza"
    if "notificat" in window or "pec" in window:
        return "notifica"
    if "deposit" in window and "ricorso" in window:
        return "deposito_ricorso"
    if ("decreto" in window and "ingiuntivo" in window) or ("emess" in window and "decreto" in window):
        return "decreto_ingiuntivo"
    if "sentenza" in window or "così deciso" in window or "cosi deciso" in window or "pubbl." in window:
        return "decisione"
    return "evento_generico"


def choose_event_date(text: str, dates: list[dict], event_type: str, decision_date: str | None = None) -> tuple[str | None, str]:
    if event_type == "spese_lite" and decision_date:
        return decision_date, "esplicita"

    if event_type in {"accertamento_fatto", "ispezione", "sequestro", "verbale_amministrativo"}:
        for candidate_date in dates:
            match = re.search(re.escape(candidate_date["raw"]), text, re.IGNORECASE)
            if not match:
                continue
            prefix = normalize_whitespace(text[max(0, match.start() - 60):match.start()].lower())
            suffix = normalize_whitespace(text[match.end():min(len(text), match.end() + 50)].lower())
            if (
                prefix.endswith("in data")
                or "reato accertato in" in prefix
                or ("ispezion" in suffix and event_type == "ispezione")
                or ("sequestr" in suffix and event_type == "sequestro")
                or (
                    event_type == "verbale_amministrativo"
                    and ("verbale n." in prefix or "con verbale n." in prefix or "verbale" in suffix)
                )
            ):
                return candidate_date["value"], "esplicita"

    preferred_roles = {
        "revoca_decreto": {"evento_generico", "decisione"},
        "cessazione_materia": {"evento_generico", "decisione"},
        "costituzione": {"evento_generico"},
        "mediazione": {"udienza"},
        "fissazione_udienza": {"udienza"},
        "rinvio": {"udienza"},
        "precisazione_conclusioni": {"udienza"},
        "decisione": {"decisione"},
        "diffida": {"evento_generico", "notifica"},
        "notifica": {"notifica"},
        "periodo_lavorativo": {"evento_generico"},
        "deposito_ricorso": {"deposito_ricorso"},
        "atto_contestato": {"atto_contestato"},
        "decreto_ingiuntivo": {"decreto_ingiuntivo", "pubblicazione"},
        "sentenza_pronunciata": {"decisione"},
        "accertamento_fatto": {"evento_generico"},
        "ispezione": {"evento_generico"},
        "sequestro": {"evento_generico"},
        "verbale_amministrativo": {"evento_generico"},
    }.get(event_type, {"evento_generico"})

    fallback_date = None
    for candidate_date in dates:
        date_role = classify_date_role(text, candidate_date["raw"])
        if date_role in {"citazione_giurisprudenziale", "riferimento_normativo", "data_nascita"}:
            continue
        if fallback_date is None:
            fallback_date = candidate_date["value"]
        if date_role in preferred_roles:
            return candidate_date["value"], "esplicita"

    if event_type in {"sentenza_pronunciata", "spese_lite", "cessazione_materia", "revoca_decreto", "decisione"} and decision_date:
        return decision_date, "esplicita"
    if fallback_date:
        return fallback_date, "esplicita"
    return None, "assente"


def score_block(text: str, section: str) -> int:
    macro_section = infer_macro_section(text, section)
    if is_jurisprudential_reference_block(text, macro_section):
        return 0
    score = 0.0
    lowered = text.lower()
    if extract_all_dates(text):
        score += 3
    if any(pattern.search(text) for pattern in NEGATIVE_PATTERNS):
        score -= 4
    if macro_section == "dispositivo":
        score += 3
    if macro_section == "facts":
        score += 2
    if macro_section == "conclusioni":
        score -= 2
    if any(pattern.search(text) for pattern in HYBRID_SIGNAL_PATTERNS):
        score += 3
    for verb in ("condanna", "dichiara", "revoca", "accoglie", "rigetta", "dispone", "fissava", "rinviata"):
        if verb in lowered:
            score += 1
    if len(text) > 500:
        score -= 1
    if is_request_like_block(text, macro_section):
        score *= SECTION_MULTIPLIERS["conclusioni"]
    else:
        score *= SECTION_MULTIPLIERS.get(macro_section, 1.0)
    return round(score, 2)


def contains_event_signal(text: str) -> bool:
    return bool(extract_all_dates(text)) or any(pattern.search(text) for pattern in HYBRID_SIGNAL_PATTERNS)


def detect_profile(source_data: dict) -> str:
    sample = "\n".join(page.get("text", "") for page in source_data.get("pages", [])[:2]).lower()
    if "tribunale" in sample and "sentenza" in sample:
        return "judgment"
    if "ordinanza" in sample:
        return "ordinanza"
    if "decreto" in sample:
        return "decreto"
    return "generic"


def extract_document_context(source_data: dict) -> dict:
    context = {
        "profile": detect_profile(source_data),
        "court_name": "Tribunale",
        "judge_name": "Il Giudice",
        "party_map": {},
    }
    pages = source_data.get("pages", [])
    first_page = clean_page_text(pages[0].get("text", "")) if pages else ""
    first_lines = [line for line in first_page.splitlines() if line][:20]

    for line in first_lines:
        candidates = [
            re.search(r"\bTribunale Ordinario di ([A-ZÀ-ÖØ-öø-ÿ' ]+)\b", line, re.IGNORECASE),
            re.search(r"\bTribunale di ([A-ZÀ-ÖØ-öø-ÿ' ]+)\b", line, re.IGNORECASE),
            re.search(r"\bTribunale ([A-ZÀ-ÖØ-öø-ÿ' ]+)\b", line, re.IGNORECASE),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            city = normalize_city_name(candidate.group(1))
            if city in ITALIAN_CITIES:
                context["court_name"] = f"Tribunale di {city}"
                break
        if context["court_name"] != "Tribunale":
            break

    if context["court_name"] == "Tribunale":
        search_pages = pages[:3] + pages[-2:] if len(pages) > 3 else pages
        search_text = "\n".join(page.get("text", "") for page in search_pages)
        for city in ITALIAN_CITIES:
            if re.search(rf"\bTribunale(?: Ordinario)?(?: di)?\s+{re.escape(city)}\b", search_text, re.IGNORECASE):
                context["court_name"] = f"Tribunale di {city}"
                break

    for line in first_lines:
        match = re.search(
            r"\b(?:Giudice|giudice)\s+(dott\.ssa|Dott\.ssa|dott\.|Dott\.)\s+([A-Z][A-Za-zÀ-ÖØ-öø-ÿ' ]+?)(?:\s+ha pronunciat\w+|\s+in funzione|\s+la seguente|\s+ex art|\s*,|$)",
            line,
        )
        if not match:
            continue
        title = "Dott.ssa" if "ssa" in match.group(1).lower() else "Dott."
        context["judge_name"] = f"{title} {normalize_whitespace(match.group(2)).title()}"
        break

    context["party_map"] = extract_party_map(source_data, context)
    return context


def infer_decision_date(source_data: dict) -> str | None:
    metadata = extract_header_metadata(source_data)
    if metadata["decision_date"]:
        return metadata["decision_date"]
    if metadata["publication_date"]:
        return metadata["publication_date"]

    pages = source_data.get("pages", [])
    if pages:
        first_text = pages[0].get("text", "")
        match = re.search(
            r"\bSentenza\s+(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})\b",
            first_text,
            re.IGNORECASE,
        )
        if match:
            values = extract_all_dates(match.group(1))
            if values:
                return values[0]["value"]
    for page in reversed(pages):
        text = page.get("text", "")
        for pattern in (
            r"\bCos[iì] deciso in [A-ZÀ-ÖØ-öø-ÿ' ]+,?\s+il\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b",
            r"\bCos[iì] deciso in [A-ZÀ-ÖØ-öø-ÿ' ]+,?\s+il\s+(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})\b",
            r"\bCos[iì] deciso in [A-ZÀ-ÖØ-öø-ÿ' ]+,?\s+in\s+data\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b",
            r"\bCos[iì] deciso in [A-ZÀ-ÖØ-öø-ÿ' ]+,?\s+in\s+data\s+(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})\b",
            r"\bpubbl\.\s*il\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b",
            r"\bpubblicat\w*\s+il\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b",
            r"\bdepositat\w*\s+il\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b",
        ):
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            raw_date = match.group(1)
            values = extract_all_dates(raw_date)
            if values:
                return values[0]["value"]
    return None


def normalize_subject_candidate(text: str) -> str:
    candidate = normalize_whitespace(text)
    candidate = re.sub(r"\([^)]*\)", "", candidate)
    candidate = re.sub(r"\b(?:C\.?F\.?|cod\. fisc\.?|P\.?I\.?va)\b.*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\b(?:con il patrocinio|rappresentat\w* e difes\w*|difes\w*|elettivamente domiciliat\w*|domiciliat\w*)\b.*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\b(?:conveniv\w+\s+in\s+giudizio|agiva\s+in\s+giudizio|ricorrev\w+\s+avverso)\b.*", "", candidate, flags=re.IGNORECASE)
    candidate = candidate.strip(" ,;:.()-")
    return normalize_whitespace(candidate)


def soft_normalize_entity_name(text: str) -> str:
    candidate = normalize_subject_candidate(text)
    candidate = re.sub(r"\b(?:arch\.?|architetto|avv\.?|avvocato|ing\.?|ingegnere|dott\.ssa|dott\.|dottore|dottor)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\b(?:sig\.ra|sig\.|sig.ra|sig)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ0-9' ]+", " ", candidate)
    candidate = normalize_whitespace(candidate).casefold()
    return candidate


def is_valid_subject_candidate(candidate: str) -> bool:
    if not candidate or len(candidate) < 3 or len(candidate) > 120:
        return False
    lowered = candidate.casefold()
    legal_role_values = {value.casefold() for value in LEGAL_ROLE_LABELS.values()}
    if lowered in SUBJECT_STOPWORDS:
        return False
    if lowered in legal_role_values:
        return True
    if re.search(r"\b(?:fisc|person:|persona del|c04\.|procura|patrocinio)\b", lowered, re.IGNORECASE):
        return False
    if re.fullmatch(r"[A-Z0-9 .'\-]+", candidate) and "[REDATTO]" in candidate:
        return False
    if re.search(r"\b(?:avv\.|nota di|procura|giudicare|motivi di cui in atti)\b", candidate, re.IGNORECASE):
        return False
    if "," in candidate and not re.search(r"\b(?:s\.r\.l\.|s\.p\.a\.|studio|condominio|comune|ministero|agenzia|societ[aà])\b", candidate, re.IGNORECASE):
        return False
    if not candidate[0].isupper() and not re.search(r"\b(?:condominio|comune|ministero|agenzia|societ[aà]|impresa|cooperativa|architetto|avvocato|ingegnere)\b", candidate, re.IGNORECASE):
        return False
    return True


def extract_header_lines(source_data: dict) -> list[str]:
    header_lines = []
    for page in source_data.get("pages", [])[:3]:
        for line in clean_page_text(page.get("text", "")).splitlines():
            cleaned = normalize_whitespace(line)
            if not cleaned:
                continue
            if re.search(r"\bCONCLUSIONI(?:\s+DELLE\s+PARTI)?\b", cleaned, re.IGNORECASE):
                return header_lines
            header_lines.append(cleaned)
    return header_lines


def remove_party_noise(text: str) -> str:
    cleaned = normalize_whitespace(text)
    cleaned = re.sub(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{11}\b", " ", cleaned)
    cleaned = re.sub(r"\b(?:C\.?\s*F\.?|C0?4\.?\s*Fisc\.?|Cod\.?\s*Fisc\.?|codice fiscale|P\.?\s*IVA|P\.?\s*Iva|partita iva)\b.*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:rappresentat\w*\s+e\s+difes\w*|difes\w*|con il patrocinio di|con il patrocinio degli|con il patrocinio delle|patrocinio degli|patrocinio delle|patrocinio dell['’])\b.*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:elettivamente domiciliat\w*|domiciliat\w*|presso cui ha eletto domicilio)\b.*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bgiusta procura in atti\b.*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bin persona del(?:l['’])?\s+legale rappresentante pro tempore\b.*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\blegale rappresentante pro tempore\b.*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:conveniv\w+\s+in\s+giudizio|agiva\s+in\s+giudizio|ricorrev\w+\s+avverso|chiedev\w+|domandav\w+)\b.*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bperson:\b.*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:con sede in|residente in|domicilio in|via|viale|piazza|corso)\b.*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    cleaned = re.sub(r"\b(?:TRA|CONTRO|E|OGGETTO)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:Parte|Controparte|CP)_\d+\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:\[REDATTO\]|P\.IVA_\d+|C\.F\._\d+|\[\.\.\.\])\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[,;:\- ]+|[,;:\- ]+$", "", cleaned)
    return normalize_whitespace(cleaned)


def clean_party_name(block_lines: list[str]) -> str | None:
    merged = remove_party_noise(" ".join(block_lines))
    if not merged:
        return None
    chunks = re.split(
        r"\b(?:presso cui|giusta procura|rappresentat\w*|difes\w*|domiciliat\w*|con il patrocinio|conveniv\w+\s+in\s+giudizio|agiva\s+in\s+giudizio)\b",
        merged,
        flags=re.IGNORECASE,
    )
    for chunk in chunks:
        candidate = normalize_subject_candidate(chunk)
        if is_valid_subject_candidate(candidate):
            return candidate
    return None


def extract_uppercase_party_after_anchor(header_lines: list[str], anchor_word: str) -> str | None:
    joined = " ".join(header_lines)
    ministry_pattern = re.compile(
        rf"\b{re.escape(anchor_word)}\b\s+(MINISTERO(?:\s+[A-ZÀ-ÖØ-Þ#']+){{0,6}})",
        re.IGNORECASE,
    )
    ministry_match = ministry_pattern.search(joined)
    if ministry_match:
        ministry_candidate = normalize_subject_candidate(ministry_match.group(1).replace("#", ""))
        if ministry_candidate and ministry_candidate.upper().startswith("MINISTERO"):
            return ministry_candidate
        return "Ministero"
    for index, line in enumerate(header_lines):
        if normalize_whitespace(line).casefold() != anchor_word.casefold():
            continue
        collected = []
        for next_line in header_lines[index + 1:index + 10]:
            cleaned_line = normalize_whitespace(next_line).strip(" -")
            if not cleaned_line:
                continue
            if re.search(r"\b(?:patrocinio|difes\w*|domiciliat\w*|oggetto|svolgimento del processo|ricorrente|resistente|convenut[oa]|opponente|opposto)\b", cleaned_line, re.IGNORECASE):
                break
            if re.search(r"[a-zà-öø-ÿ]{3,}", cleaned_line) and not cleaned_line.isupper():
                break
            if cleaned_line in {"-", "E"}:
                continue
            collected.append(cleaned_line.replace("#", ""))
        if collected:
            candidate = normalize_subject_candidate(" ".join(collected))
            if candidate.startswith("MAECI"):
                candidate = candidate.replace("MAECI", "Ministero degli Affari Esteri e della Cooperazione Internazionale", 1)
            candidate = re.sub(
                r"(Ministero degli Affari Esteri e della Cooperazione Internazionale)\s+MINISTERO DEGLI AFFARI ESTERI(?: DELLA COOPERAZIONE)?",
                r"\1",
                candidate,
                flags=re.IGNORECASE,
            )
            if is_valid_subject_candidate(candidate):
                return candidate
    pattern = re.compile(
        rf"\b{re.escape(anchor_word)}\b\s+([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ' ]{{5,}}?)(?=\s+(?:\(|C\.?F\.?|P\.?\s*IVA|con il patrocinio|in proprio|CONVENUT[OA]|RICORRENTE|RESISTENT[EI]|OPPOSTO|OPPONENTE)\b)",
        re.IGNORECASE,
    )
    match = pattern.search(joined)
    if not match:
        return None
    candidate = normalize_subject_candidate(match.group(1))
    if is_valid_subject_candidate(candidate):
        return candidate
    return None


def extract_uppercase_party_after_label(header_lines: list[str], role_label: str) -> str | None:
    joined = " ".join(header_lines)
    pattern = re.compile(
        rf"\b{re.escape(role_label)}\b\s+([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ'# ]+[A-ZÀ-ÖØ-Þ#'])",
        re.IGNORECASE,
    )
    match = pattern.search(joined)
    if not match:
        return None
    candidate = normalize_subject_candidate(match.group(1).replace("#", ""))
    if candidate.lower().startswith("e "):
        return None
    if candidate.count(" ") >= 1 and is_valid_subject_candidate(candidate):
        return candidate
    return None


def extract_parties_from_header(source_data: dict, context: dict) -> dict[str, str]:
    header_lines = extract_header_lines(source_data)
    party_map: dict[str, str] = {}
    uppercase_after_tra = extract_uppercase_party_after_anchor(header_lines, "tra")
    uppercase_after_e = extract_uppercase_party_after_anchor(header_lines, "e")
    uppercase_after_contro = extract_uppercase_party_after_anchor(header_lines, "contro")
    uppercase_after_ricorrente = extract_uppercase_party_after_label(header_lines, "RICORRENTE")
    uppercase_after_ricorrenti = extract_uppercase_party_after_label(header_lines, "RICORRENTI")
    uppercase_after_convenuto = extract_uppercase_party_after_label(header_lines, "CONVENUTO")
    uppercase_after_convenuta = extract_uppercase_party_after_label(header_lines, "CONVENUTA")
    joined_header = " ".join(header_lines)
    separator_pattern = re.compile(r"^(TRA|E|CONTRO)$", re.IGNORECASE)
    role_pattern = re.compile(
        r"^(OPPONENTE|OPPOSTO|CONVENUTO|CONVENUTA|ATTORE|ATTRICE|RICORRENTE|RICORRENTI|RESISTENTE|RESISTENTI|IMPUTATO|IMPUTATA)\b",
        re.IGNORECASE,
    )

    current_segment: list[str] = []
    for line in header_lines:
        if separator_pattern.match(line):
            current_segment = []
            continue
        role_match = role_pattern.match(line)
        if role_match:
            role_key = role_match.group(1).casefold()
            role_label = LEGAL_ROLE_LABELS.get(role_key, role_match.group(1).title())
            cleaned_name = clean_party_name(current_segment)
            party_map[role_label] = cleaned_name or role_label
            current_segment = []
            continue
        current_segment.append(line)

    if not party_map:
        for role_label in ("Ricorrente", "Resistente", "Opponente", "Opposto", "Convenuto", "Attore", "Imputato"):
            if re.search(rf"\b{re.escape(role_label)}\b", " ".join(header_lines), re.IGNORECASE):
                party_map[role_label] = role_label
    if uppercase_after_contro and "Convenuto" in party_map and party_map["Convenuto"] == "Convenuto":
        party_map["Convenuto"] = uppercase_after_contro
    if uppercase_after_contro and "Opposto" in party_map and party_map["Opposto"] == "Opposto":
        party_map["Opposto"] = uppercase_after_contro
    if uppercase_after_ricorrente and "Ricorrente" in party_map and party_map["Ricorrente"] == "Ricorrente":
        party_map["Ricorrente"] = uppercase_after_ricorrente
    if uppercase_after_ricorrenti and "Ricorrenti" in party_map and party_map["Ricorrenti"] == "Ricorrenti":
        party_map["Ricorrenti"] = uppercase_after_ricorrenti
    if uppercase_after_convenuto and "Convenuto" in party_map and party_map["Convenuto"] == "Convenuto":
        party_map["Convenuto"] = uppercase_after_convenuto
    if uppercase_after_convenuta and "Convenuta" in party_map and party_map["Convenuta"] == "Convenuta":
        party_map["Convenuta"] = uppercase_after_convenuta
    if uppercase_after_tra:
        for role_label in ("Ricorrente", "Ricorrenti", "Attore", "Attrice", "Opponente"):
            if role_label in party_map and party_map[role_label] == role_label:
                party_map[role_label] = uppercase_after_tra
                break
    if uppercase_after_contro:
        for role_label in ("Convenuto", "Convenuta", "Resistente", "Resistenti", "Opposto"):
            if role_label in party_map and party_map[role_label] == role_label:
                party_map[role_label] = uppercase_after_contro
                break
    elif uppercase_after_e:
        for role_label in ("Convenuto", "Convenuta", "Resistente", "Resistenti", "Opposto"):
            if role_label in party_map and party_map[role_label] == role_label:
                party_map[role_label] = uppercase_after_e
                break
    if re.search(r"\bMINISTERO\b", joined_header, re.IGNORECASE):
        if "Convenuto" in party_map and party_map["Convenuto"] == "Convenuto":
            party_map["Convenuto"] = "Ministero"
        if "Opposto" in party_map and party_map["Opposto"] == "Opposto":
            party_map["Opposto"] = "Ministero"
    return party_map


def extract_party_map(source_data: dict, context: dict) -> dict:
    party_map = extract_parties_from_header(source_data, context)
    normalized_party_map = {}
    for role, name in party_map.items():
        cleaned_name = normalize_subject_candidate(name)
        normalized_party_map[role] = cleaned_name if is_valid_subject_candidate(cleaned_name) else role
    return normalized_party_map


def deduplicate_subject_list(subjects: list[str]) -> list[str]:
    unique = []
    seen = set()
    for subject in subjects:
        candidate = normalize_subject_candidate(subject)
        if not is_valid_subject_candidate(candidate):
            continue
        key = soft_normalize_entity_name(candidate) or candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def extract_subjects(text: str, context: dict) -> list[str]:
    subjects = []
    lowered = text.lower()
    if "tribunale" in lowered and context["court_name"] not in subjects:
        subjects.append(context["court_name"])
    if "giudice" in lowered and context["judge_name"] not in subjects:
        subjects.append(context["judge_name"])

    tribunal_match = re.search(r"\bTribunale(?: Ordinario)?(?: di)?\s+([A-ZÀ-ÖØ-öø-ÿ' ]+)\b", text, re.IGNORECASE)
    if tribunal_match:
        city = normalize_city_name(tribunal_match.group(1))
        candidate = f"Tribunale di {city}"
        if city in ITALIAN_CITIES and candidate not in subjects:
            subjects.append(candidate)

    ministry_matches = re.finditer(r"\bMinistero [A-ZÀ-ÖØ-öø-ÿ' ]+\b", text)
    for match in ministry_matches:
        candidate = normalize_whitespace(match.group(0))
        if len(candidate) <= 60 and candidate not in subjects:
            subjects.append(candidate)

    party_map = context.get("party_map", {})
    for role, party_name in party_map.items():
        if party_name and re.search(rf"(?<!\w){re.escape(party_name)}(?!\w)", text, re.IGNORECASE):
            subjects.append(party_name)
        role_pattern = ROLE_REFERENCE_PATTERNS.get(role)
        if role_pattern and role_pattern.search(text):
            subjects.append(party_name or role)
        elif role.casefold() in lowered:
            subjects.append(party_name or role)

    return deduplicate_subject_list(subjects)


def extract_amount(text: str) -> str | None:
    match = re.search(
        r"(?:€|euro)\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?|[0-9]+(?:,[0-9]{2})?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return f"€ {match.group(1)}"


def sort_events(events: list[dict]) -> list[dict]:
    return sorted(
        events,
        key=lambda event: (
            event.get("data") or "9999-12-31",
            event.get("ora") or "99:99",
            event.get("pagina") or 0,
            event.get("id", 0),
        ),
    )
