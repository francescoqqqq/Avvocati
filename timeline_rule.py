#!/usr/bin/env python3
import argparse
from difflib import get_close_matches
import json
import re
import sys
from datetime import date
from pathlib import Path


RESULTS_DIR_NAME = "results_rule"
TRANSCRIPTS_DIR_NAME = "trascrizioni"

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
    ],
    "facts": [
        re.compile(r"\bSVOLGIMENTO\b", re.IGNORECASE),
        re.compile(r"\bRAGIONI DI FATTO\b", re.IGNORECASE),
        re.compile(r"\bMOTIVI IN FATTO\b", re.IGNORECASE),
    ],
    "law": [
        re.compile(r"\bMOTIVI IN DIRITTO\b", re.IGNORECASE),
        re.compile(r"\bRAGIONI DI DIRITTO\b", re.IGNORECASE),
    ],
    "dispositivo": [
        re.compile(r"\bP\.Q\.M\.\b", re.IGNORECASE),
        re.compile(r"\bcos[iì] provvede\b", re.IGNORECASE),
        re.compile(r"\bdefinitivamente pronunciando\b", re.IGNORECASE),
    ],
}

GENERIC_EVENT_RULES = [
    {
        "event_type": "emissione_decreto",
        "patterns": [
            re.compile(r"\bdecreto ingiuntivo\b.*\bemess\w+\b", re.IGNORECASE),
            re.compile(r"\bemess\w+\b.*\bdecreto ingiuntivo\b", re.IGNORECASE),
        ],
        "label": "Viene emesso il decreto ingiuntivo opposto",
    },
    {
        "event_type": "notifica",
        "patterns": [
            re.compile(r"\bnotificat\w+\b.*\bvia p\.?e\.?c\.?\b", re.IGNORECASE),
            re.compile(r"\bnotificat\w+\b.*\bcitazione\b", re.IGNORECASE),
            re.compile(r"\batto di citazione\b.*\bnotificat\w+\b", re.IGNORECASE),
        ],
        "label": "Viene notificato l'atto introduttivo o il provvedimento",
    },
    {
        "event_type": "deposito_ricorso",
        "patterns": [
            re.compile(r"\bcon ricorso\b", re.IGNORECASE),
            re.compile(r"\bricorso ex art\.", re.IGNORECASE),
            re.compile(r"\bricorso\b.*\bagit\w+\b", re.IGNORECASE),
        ],
        "label": "La parte ricorrente deposita o propone il ricorso",
    },
    {
        "event_type": "costituzione",
        "patterns": [
            re.compile(r"\bsi costituiv\w+\b.*\bgiudizio\b", re.IGNORECASE),
            re.compile(r"\bcomparsa di costituzione\b", re.IGNORECASE),
        ],
        "label": "Una parte si costituisce in giudizio",
    },
    {
        "event_type": "fissazione_udienza",
        "patterns": [
            re.compile(r"\bcon decreto del\b.*\bfissav\w+\b.*\budienza\b", re.IGNORECASE),
            re.compile(r"\bfissav\w+\b.*\bprima udienza\b", re.IGNORECASE),
        ],
        "label": "Il giudice fissa l'udienza con decreto",
    },
    {
        "event_type": "mediazione",
        "patterns": [
            re.compile(r"\bmediazione\b", re.IGNORECASE),
            re.compile(r"\bprocedibilit[aà]\b.*\bmediazione\b", re.IGNORECASE),
        ],
        "label": "Il giudice dispone o valuta il tentativo di mediazione",
    },
    {
        "event_type": "rinvio",
        "patterns": [
            re.compile(r"\brinviat\w+\b", re.IGNORECASE),
            re.compile(r"\brinvio\b", re.IGNORECASE),
        ],
        "label": "La causa viene rinviata",
    },
    {
        "event_type": "precisazione_conclusioni",
        "patterns": [
            re.compile(r"\bprecisavano le conclusioni\b", re.IGNORECASE),
            re.compile(r"\bprecisazione delle conclusioni\b", re.IGNORECASE),
        ],
        "label": "Le parti precisano le conclusioni",
    },
    {
        "event_type": "discussione",
        "patterns": [
            re.compile(r"\bdiscussione?\b.*\bsentenza\b", re.IGNORECASE),
            re.compile(r"\bdiscussione ex art\b", re.IGNORECASE),
            re.compile(r"\bdata lettura della sentenza\b", re.IGNORECASE),
        ],
        "label": "Si tiene l'udienza di discussione e viene letta o depositata la sentenza",
    },
    {
        "event_type": "revoca_mandato",
        "patterns": [
            re.compile(r"\brevocat\w+\b", re.IGNORECASE),
            re.compile(r"\bcessato di essere\b.*\bamministratore\b", re.IGNORECASE),
        ],
        "label": "Interviene la revoca o la cessazione del mandato",
    },
    {
        "event_type": "ctu",
        "patterns": [
            re.compile(r"\bconsulenza tecnico\b", re.IGNORECASE),
            re.compile(r"\bctu\b", re.IGNORECASE),
            re.compile(r"\bconsulente dell['’]ufficio\b", re.IGNORECASE),
        ],
        "label": "Viene disposta o valutata una consulenza tecnica d'ufficio",
    },
    {
        "event_type": "cessazione_materia",
        "patterns": [
            re.compile(r"\bcessazione della materia del contendere\b", re.IGNORECASE),
        ],
        "label": "Il Tribunale dichiara la cessazione della materia del contendere",
    },
    {
        "event_type": "revoca_decreto",
        "patterns": [
            re.compile(r"\brevoca il decreto ingiuntivo\b", re.IGNORECASE),
            re.compile(r"\bdecreto ingiuntivo opposto\b.*\brevocat\w+\b", re.IGNORECASE),
        ],
        "label": "Il Tribunale revoca il decreto ingiuntivo opposto",
    },
    {
        "event_type": "accoglimento",
        "patterns": [
            re.compile(r"\baccoglie\b", re.IGNORECASE),
            re.compile(r"\bin parziale accoglimento\b", re.IGNORECASE),
        ],
        "label": "Il Tribunale accoglie in tutto o in parte le domande",
    },
    {
        "event_type": "rigetto",
        "patterns": [
            re.compile(r"\brigetta\b", re.IGNORECASE),
            re.compile(r"\brespinge\b", re.IGNORECASE),
        ],
        "label": "Il Tribunale rigetta una domanda o eccezione",
    },
    {
        "event_type": "condanna_risarcimento",
        "patterns": [
            re.compile(r"\bcondanna\b.*\brisarciment\w+\b", re.IGNORECASE),
            re.compile(r"\bpagamento\b.*\bsomma di\b", re.IGNORECASE),
        ],
        "label": "Il Tribunale condanna al pagamento di una somma a titolo risarcitorio o restitutorio",
    },
    {
        "event_type": "spese_lite",
        "patterns": [
            re.compile(r"\bspese di lite\b", re.IGNORECASE),
            re.compile(r"\bcondanna\b.*\bspese\b", re.IGNORECASE),
        ],
        "label": "Il Tribunale condanna la parte soccombente al pagamento delle spese di lite",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estrae una timeline rule-based avanzata da un JSON con testo PDF pagina per pagina."
    )
    parser.add_argument("input_json", nargs="?", type=Path)
    return parser.parse_args()


def get_transcripts_dir(working_dir: Path) -> Path:
    candidate = working_dir / TRANSCRIPTS_DIR_NAME
    return candidate if candidate.exists() else working_dir


def get_results_dir(working_dir: Path) -> Path:
    return working_dir / RESULTS_DIR_NAME


def list_local_json(search_dir: Path) -> list[Path]:
    return sorted(
        [
            path for path in search_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".json"
            and not path.name.endswith("_timeline_rule.json")
            and not path.name.endswith("_timeline_hybrid.json")
        ],
        key=lambda path: path.name.lower(),
    )


def prompt_json_path(search_dir: Path) -> Path:
    json_files = list_local_json(search_dir)
    if json_files:
        print(f"JSON trovati in {search_dir}:", file=sys.stderr)
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
            json_path = (search_dir / json_path).resolve()
        else:
            json_path = json_path.resolve()
        if not json_path.exists():
            print(f"File non trovato: {json_path}", file=sys.stderr)
            continue
        if json_path.suffix.lower() != ".json":
            print(f"Il file selezionato non sembra un JSON: {json_path}", file=sys.stderr)
            continue
        return json_path


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
    cleaned = normalize_whitespace(line.replace("\u0000", ""))
    return cleaned


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

    for line in raw_lines:
        matched_section = None
        for section_name, patterns in SECTION_HINTS.items():
            if any(pattern.search(line) for pattern in patterns):
                matched_section = section_name
                break

        if matched_section is not None:
            flush_buffer()
            current_section = matched_section
            buffer.append(line)
            continue

        if re.match(r"^\d+\)", line) or re.match(r"^- ", line):
            flush_buffer()
            buffer.append(line)
            continue

        if len(buffer) >= 1 and buffer[-1].endswith((".", ";", ":")):
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
    for rule in GENERIC_EVENT_RULES:
        if any(pattern.search(text) for pattern in rule["patterns"]):
            score += 3
            break
    for verb in ("condanna", "dichiara", "revoca", "accoglie", "rigetta", "dispone", "fissava", "rinviata"):
        if verb in lowered:
            score += 1
    if len(text) > 500:
        score -= 1
    return score


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


def extract_subjects(text: str, context: dict) -> list[str]:
    subjects = []
    if "tribunale" in text.lower() and context["court_name"] not in subjects:
        subjects.append(context["court_name"])
    if "giudice" in text.lower() and context["judge_name"] not in subjects:
        subjects.append(context["judge_name"])

    tribunal_match = re.search(r"\bTribunale(?: Ordinario)?(?: di)?\s+([A-ZÀ-ÖØ-öø-ÿ' ]+)\b", text, re.IGNORECASE)
    if tribunal_match:
        city = normalize_city_name(tribunal_match.group(1))
        candidate = f"Tribunale di {city}"
        if city in ITALIAN_CITIES and candidate not in subjects:
            subjects.append(candidate)

    ministry_match = re.finditer(r"\bMinistero [A-ZÀ-ÖØ-öø-ÿ' ]+\b", text)
    for match in ministry_match:
        candidate = normalize_whitespace(match.group(0))
        if len(candidate) <= 60 and candidate not in subjects:
            subjects.append(candidate)

    return subjects


def normalize_event_text(text: str) -> str:
    compact = normalize_whitespace(text)
    compact = re.sub(r"^(?:all['’]udienza del|con decreto del|in data)\s+", "", compact, flags=re.IGNORECASE)
    return compact[:220].rstrip(" ,;:.")


def build_event_label(block_text: str, rule: dict, context: dict) -> str:
    label = rule["label"]
    if rule["event_type"] in {"accoglimento", "rigetto", "spese_lite", "revoca_decreto", "cessazione_materia"}:
        return label
    if context["court_name"] != "Tribunale" and "Tribunale" in label:
        return label.replace("Il Tribunale", f"Il {context['court_name']}")
    return label


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


def build_event(event_id: int, block: dict, page_number: int, source_document: str, context: dict, decision_date: str | None) -> list[dict]:
    events = []
    text = block["text"]
    section = block["section"]
    score = score_block(text, section)
    if score < 3:
        return events

    dates = extract_all_dates(text)
    subjects = extract_subjects(text, context)
    event_time = extract_time(text)

    for rule in GENERIC_EVENT_RULES:
        if not any(pattern.search(text) for pattern in rule["patterns"]):
            continue

        event_date = None
        certainty = "assente"
        for candidate_date in dates:
            date_role = classify_date_role(text, candidate_date["raw"])
            if rule["event_type"] == "spese_lite" and decision_date:
                event_date = decision_date
                certainty = "esplicita"
                break
            if rule["event_type"] == "emissione_decreto" and date_role in {"decreto_ingiuntivo", "evento_generico"}:
                event_date = candidate_date["value"]
                certainty = "esplicita"
                break
            if rule["event_type"] == "notifica" and date_role == "notifica":
                event_date = candidate_date["value"]
                certainty = "esplicita"
                break
            if rule["event_type"] in {"fissazione_udienza", "mediazione", "rinvio", "precisazione_conclusioni", "discussione"} and date_role == "udienza":
                event_date = candidate_date["value"]
                certainty = "esplicita"
                break
            if rule["event_type"] in {"costituzione", "deposito_ricorso", "revoca_mandato", "cessazione_materia", "revoca_decreto", "accoglimento", "rigetto", "condanna_risarcimento"} and date_role not in {"citazione_giurisprudenziale", "riferimento_normativo"}:
                event_date = candidate_date["value"]
                certainty = "esplicita"
                break

        if rule["event_type"] == "spese_lite" and not event_date and decision_date:
            event_date = decision_date
            certainty = "esplicita"

        events.append(
            {
                "id": event_id + len(events),
                "data": event_date,
                "ora": event_time,
                "evento": build_event_label(text, rule, context),
                "tipo_evento": rule["event_type"],
                "soggetti": subjects,
                "documento": source_document,
                "pagina": page_number,
                "certezza_data": certainty if event_date else "assente",
                "sezione": section,
                "score": score,
                "testo_origine": normalize_event_text(text),
            }
        )

    if not events and section == "header" and "sentenza" in text.lower():
        events.append(
            {
                "id": event_id,
                "data": decision_date,
                "ora": None,
                "evento": f"Il {context['court_name']} pronuncia la sentenza",
                "tipo_evento": "sentenza_pronunciata",
                "soggetti": [context["court_name"], context["judge_name"]],
                "documento": source_document,
                "pagina": page_number,
                "certezza_data": "esplicita" if decision_date else "assente",
                "sezione": section,
                "score": score,
                "testo_origine": normalize_event_text(text),
            }
        )

    return events


def deduplicate_events(events: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for event in events:
        normalized_text = normalize_whitespace(event["evento"]).lower()
        normalized_text = re.sub(r"\bil tribunale di [a-zà-öø-ÿ' ]+\b", "il tribunale", normalized_text)
        normalized_text = re.sub(r"\bil giudice\b", "giudice", normalized_text)
        key = (
            event["data"],
            event.get("tipo_evento", "altro"),
            normalized_text,
            event["pagina"] if not event["data"] else None,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def sort_events(events: list[dict]) -> list[dict]:
    return sorted(
        events,
        key=lambda event: (
            event["data"] or "9999-12-31",
            event["ora"] or "99:99",
            event["pagina"],
            event["id"],
        ),
    )


def build_timeline_data(source_data: dict, input_name: str) -> dict:
    source_document = Path(source_data.get("source_pdf", input_name)).name
    context = extract_document_context(source_data)
    decision_date = infer_decision_date(source_data)
    all_events = []
    next_id = 1

    for page in source_data.get("pages", []):
        page_number = page.get("page_number")
        page_text = page.get("text", "")
        for block in split_into_blocks(page_text):
            block_events = build_event(next_id, block, page_number, source_document, context, decision_date)
            all_events.extend(block_events)
            next_id += len(block_events)

    unique_events = deduplicate_events(all_events)
    dated_events = sort_events([event for event in unique_events if event["data"]])
    undated_events = sort_events([event for event in unique_events if not event["data"]])

    for index, event in enumerate(dated_events + undated_events, start=1):
        event["id"] = index

    return {
        "source_json": input_name,
        "documento": source_document,
        "contesto_documento": context,
        "eventi": dated_events,
        "eventi_non_datati": undated_events,
        "metriche": {
            "eventi_datati": len(dated_events),
            "eventi_non_datati": len(undated_events),
            "decision_date": decision_date,
            "profile": context["profile"],
        },
    }


def main() -> int:
    args = parse_args()
    working_dir = Path.cwd()
    transcripts_dir = get_transcripts_dir(working_dir)
    input_path = args.input_json.expanduser().resolve() if args.input_json else prompt_json_path(transcripts_dir)
    if not input_path.exists():
        print(f"Errore: JSON non trovato: {input_path}", file=sys.stderr)
        return 1

    source_data = json.loads(input_path.read_text(encoding="utf-8"))
    results_dir = get_results_dir(working_dir)
    results_dir.mkdir(exist_ok=True)

    print(f"Analizzo {input_path.name} con timeline_rule...", file=sys.stderr)
    timeline_data = build_timeline_data(source_data, input_path.name)
    output_path = results_dir / f"{input_path.stem}_timeline_rule.json"
    output_path.write_text(json.dumps(timeline_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Timeline salvata in: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
