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
    re.compile(r"^sentenza n\..*", re.IGNORECASE),
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

SECTION_HINTS = {
    "header": [
        re.compile(r"\bREPUBBLICA ITALIANA\b", re.IGNORECASE),
        re.compile(r"\bIN NOME DEL POPOLO ITALIANO\b", re.IGNORECASE),
        re.compile(r"^TRIBUNALE(?:\s+ORDINARIO)?(?:\s+DI\s+[A-ZÀ-ÖØ-öø-ÿ' ]+)?$", re.IGNORECASE),
        re.compile(r"^SEZIONE(?:\s+[A-ZÀ-ÖØ-öø-ÿ' ]+)?$", re.IGNORECASE),
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
]


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
                blocks.append({"section": current_section, "text": text})
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
    for match in re.finditer(r"\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})\b", text):
        iso_date = parse_numeric_date(*match.groups())
        if iso_date:
            dates.append({"value": iso_date, "raw": match.group(0), "kind": "numeric"})
    for match in re.finditer(
        r"\b(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    ):
        try:
            iso_date = date(int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1))).isoformat()
            dates.append({"value": iso_date, "raw": match.group(0), "kind": "textual"})
        except ValueError:
            pass
    return dates


def extract_time(text: str) -> str | None:
    match = re.search(r"(?<![\d./-])(?:ore\s*)?(\d{1,2})[:.](\d{2})(?![./-]\d)", text, re.IGNORECASE)
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
    if "cass." in window or "corte di cassazione" in window or "cgue" in window:
        return "citazione_giurisprudenziale"
    if "art." in window or "d.lgs" in window or "legge" in window or "direttiva" in window:
        return "riferimento_normativo"
    if "udienza" in window:
        return "udienza"
    if "notificat" in window or "pec" in window:
        return "notifica"
    if "deposit" in window or "ricorso" in window:
        return "deposito_ricorso"
    if "decreto" in window and "ingiuntivo" in window:
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
            prefix = normalize_whitespace(text[max(0, match.start() - 30):match.start()].lower())
            suffix = normalize_whitespace(text[match.end():min(len(text), match.end() + 50)].lower())
            if (
                prefix.endswith("in data")
                or "reato accertato in" in prefix
                or ("ispezion" in suffix and event_type == "ispezione")
                or ("sequestr" in suffix and event_type == "sequestro")
                or ("verbale" in suffix and event_type == "verbale_amministrativo")
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
        "notifica": {"notifica"},
        "sentenza_pronunciata": {"decisione"},
        "accertamento_fatto": {"evento_generico"},
        "ispezione": {"evento_generico"},
        "sequestro": {"evento_generico"},
        "verbale_amministrativo": {"evento_generico"},
    }.get(event_type, {"evento_generico"})

    fallback_date = None
    for candidate_date in dates:
        date_role = classify_date_role(text, candidate_date["raw"])
        if date_role in {"citazione_giurisprudenziale", "riferimento_normativo"}:
            continue
        if fallback_date is None:
            fallback_date = candidate_date["value"]
        if date_role in preferred_roles:
            return candidate_date["value"], "esplicita"

    if event_type in {"sentenza_pronunciata", "spese_lite", "cessazione_materia", "revoca_decreto"} and decision_date:
        return decision_date, "esplicita"
    if fallback_date:
        return fallback_date, "esplicita"
    return None, "assente"


def score_block(text: str, section: str) -> int:
    score = 0
    lowered = text.lower()
    if extract_all_dates(text):
        score += 3
    if any(pattern.search(text) for pattern in NEGATIVE_PATTERNS):
        score -= 4
    if section == "dispositivo":
        score += 3
    if section == "facts":
        score += 2
    if any(pattern.search(text) for pattern in HYBRID_SIGNAL_PATTERNS):
        score += 3
    for verb in ("condanna", "dichiara", "revoca", "accoglie", "rigetta", "dispone", "fissava", "rinviata"):
        if verb in lowered:
            score += 1
    if len(text) > 500:
        score -= 1
    return score


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

    return context


def infer_decision_date(source_data: dict) -> str | None:
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

    return subjects


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
