#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz


OCR_PLACEHOLDER = "[nessun testo selezionabile trovato in questa pagina]"
REDACTED_PLACEHOLDER = "[REDATTO]"
DEFAULT_OCR_LANG = "ita"
DEFAULT_OCR_DPI = 300
PDFS_DIR_NAME = "sentenze"
TRANSCRIPTS_DIR_NAME = "trascrizioni"
LATIN_CORRECTIONS = [
    (re.compile(r"\b(?:ne|me|re)\s+bis\s+i[nm]\s+i[dt]e[mn]\b", re.IGNORECASE), "ne bis in idem"),
    (re.compile(r"\bi[dt]e[mn]\s+fact(?:um|u[mn])\b", re.IGNORECASE), "idem factum"),
    (re.compile(r"\bprima\s+faci[e3]\b", re.IGNORECASE), "prima facie"),
    (re.compile(r"\bius\s+superveniens\b", re.IGNORECASE), "ius superveniens"),
    (re.compile(r"\bfumus\s+boni\s+iuris\b", re.IGNORECASE), "fumus boni iuris"),
    (re.compile(r"\bpericulum\s+in\s+mora\b", re.IGNORECASE), "periculum in mora"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estrae il testo di un PDF e genera un JSON pagina per pagina. Se il testo non è selezionabile, prova automaticamente OCR locale con Tesseract."
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        type=Path,
        help="Percorso del file PDF di input. Se omesso, viene richiesto in modo interattivo.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help=f"Percorso del file JSON di output. Default: {TRANSCRIPTS_DIR_NAME}/<nome_pdf>.json",
    )
    parser.add_argument(
        "--ocr-lang",
        default=DEFAULT_OCR_LANG,
        help=f"Lingua Tesseract per OCR fallback. Default: {DEFAULT_OCR_LANG}",
    )
    parser.add_argument(
        "--ocr-dpi",
        type=int,
        default=DEFAULT_OCR_DPI,
        help=f"DPI usato per il rendering delle pagine in OCR fallback. Default: {DEFAULT_OCR_DPI}",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Disabilita il fallback OCR e usa solo il testo selezionabile.",
    )
    return parser.parse_args()


def get_pdfs_dir(working_dir: Path) -> Path:
    candidate = working_dir / PDFS_DIR_NAME
    return candidate if candidate.exists() else working_dir


def get_transcripts_dir(working_dir: Path) -> Path:
    return working_dir / TRANSCRIPTS_DIR_NAME


def list_local_pdfs(search_dir: Path) -> list[Path]:
    return sorted(
        [path for path in search_dir.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"],
        key=lambda path: path.name.lower(),
    )


def prompt_pdf_path(search_dir: Path) -> Path:
    pdf_files = list_local_pdfs(search_dir)

    if pdf_files:
        print(f"PDF trovati in {search_dir}:", file=sys.stderr)
        for index, pdf_file in enumerate(pdf_files, start=1):
            print(f"  {index}. {pdf_file.name}", file=sys.stderr)
        print(
            "Digita il numero del PDF da analizzare oppure incolla un percorso completo.",
            file=sys.stderr,
        )

    while True:
        user_input = input("Che PDF vuoi analizzare? ").strip().strip('"').strip("'")
        if not user_input:
            print("Inserisci il numero o il percorso di un file PDF.", file=sys.stderr)
            continue

        if user_input.isdigit() and pdf_files:
            selected_index = int(user_input)
            if 1 <= selected_index <= len(pdf_files):
                return pdf_files[selected_index - 1].resolve()
            print("Numero non valido. Scegli uno dei PDF elencati.", file=sys.stderr)
            continue

        pdf_path = Path(user_input).expanduser()
        if not pdf_path.is_absolute():
            pdf_path = (search_dir / pdf_path).resolve()
        else:
            pdf_path = pdf_path.resolve()

        if not pdf_path.exists():
            print(f"File non trovato: {pdf_path}", file=sys.stderr)
            continue
        if pdf_path.suffix.lower() != ".pdf":
            print(f"Il file selezionato non sembra un PDF: {pdf_path}", file=sys.stderr)
            continue
        return pdf_path


def extract_page_text_native(page: fitz.Page) -> str:
    text = post_process_native_text(page.get_text("text"))
    if text:
        return text

    words = page.get_text("words")
    if words:
        sorted_words = sorted(words, key=lambda item: (round(item[1], 1), round(item[0], 1)))
        words_text = " ".join(word[4] for word in sorted_words if len(word) > 4).strip()
        return post_process_native_text(words_text)

    return ""


def ensure_command_available(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def render_page_to_image_pdftoppm(pdf_path: Path, page_number: int, dpi: int, output_path: Path) -> None:
    result = subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-r",
            str(dpi),
            "-singlefile",
            "-png",
            str(pdf_path),
            str(output_path.with_suffix("")),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"pdftoppm ha restituito un errore: {stderr}")
    if not output_path.exists():
        raise RuntimeError("pdftoppm non ha prodotto l'immagine attesa")


def render_page_to_image_mutool(pdf_path: Path, page_number: int, dpi: int, output_path: Path) -> None:
    result = subprocess.run(
        [
            "mutool",
            "draw",
            "-F",
            "pnm",
            "-r",
            str(dpi),
            "-o",
            str(output_path),
            str(pdf_path),
            str(page_number),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"mutool draw ha restituito un errore: {stderr}")
    if not output_path.exists():
        raise RuntimeError("mutool draw non ha prodotto l'immagine attesa")


def ensure_tesseract_available() -> bool:
    return ensure_command_available("tesseract")


def run_tesseract_on_image(image_path: Path, lang: str) -> str:
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", lang],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Tesseract ha restituito un errore: {stderr}")
    return result.stdout.strip()


def extract_page_text_ocr(pdf_path: Path, page_number: int, lang: str, dpi: int) -> str:
    with tempfile.TemporaryDirectory(prefix="pdf_ocr_") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        attempts = []
        if ensure_command_available("pdftoppm"):
            attempts.append(("pdftoppm", tmp_dir / "page.png", render_page_to_image_pdftoppm))
        if ensure_command_available("mutool"):
            attempts.append(("mutool", tmp_dir / "page.pnm", render_page_to_image_mutool))

        if not attempts:
            raise RuntimeError("Nessun renderer OCR disponibile: servono pdftoppm o mutool")

        errors: list[str] = []

        for renderer_name, image_path, renderer in attempts:
            try:
                renderer(pdf_path, page_number, dpi=dpi, output_path=image_path)
                return run_tesseract_on_image(image_path, lang=lang)
            except RuntimeError as exc:
                errors.append(f"{renderer_name}: {exc}")
                continue

        joined_errors = " | ".join(errors)
        raise RuntimeError(f"OCR fallback fallito su tutti i renderer provati: {joined_errors}")


def is_likely_garbage_token(token: str) -> bool:
    stripped = token.strip()
    if not stripped:
        return False

    if stripped in {".", ",", ";", ":", "-", "_"}:
        return False

    if re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ]\.(?:[A-Za-zÀ-ÖØ-öø-ÿ]\.)+[,:;]?", stripped):
        return False

    if re.fullmatch(r"(?:art|n|pag|dott|dott\.ssa|avv|cpc|cpp|cc)\.?", stripped, flags=re.IGNORECASE):
        return False

    allowed_special = set(".,;:!?()[]/%+-€/'\"")
    weird_chars = sum(1 for ch in stripped if not (ch.isalnum() or ch.isspace() or ch in allowed_special))
    punctuation_chars = sum(1 for ch in stripped if not ch.isalnum())
    digit_chars = sum(1 for ch in stripped if ch.isdigit())
    alpha_chars = sum(1 for ch in stripped if ch.isalpha())

    if weird_chars >= 2:
        return True
    if len(stripped) >= 4 and punctuation_chars > alpha_chars + digit_chars:
        return True
    if len(stripped) >= 6 and alpha_chars <= 2 and digit_chars <= 2:
        return True
    if re.search(r"[_|°«»“”©®]", stripped):
        return True

    return False


def is_likely_glyph_chaos_token(token: str) -> bool:
    stripped = token.strip()
    if len(stripped) < 4:
        return False
    special_matches = re.findall(r"[{}\[\]@#]", stripped)
    if len(special_matches) < 2:
        return False
    alpha_chars = sum(1 for ch in stripped if ch.isalpha())
    return alpha_chars <= max(4, len(stripped) // 2)


def normalize_latin_legalisms(text: str) -> str:
    normalized = text
    for pattern, replacement in LATIN_CORRECTIONS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def is_likely_stamp_or_signature_line(line: str) -> bool:
    normalized = re.sub(r"\s+", " ", line).strip()
    if not normalized:
        return False

    if re.fullmatch(r"(?:P\.Q\.M\.|DICHIARA|INDICA|SENTENZA|SEZIONE PENALE|TRIBUNALE DI [A-ZÀ-ÖØ-öø-ÿ' ]+)", normalized, re.IGNORECASE):
        return False

    lowered = normalized.lower()
    if "depositato in cancelleria" in lowered or "funzionario giudiziario" in lowered:
        return True

    words = normalized.split()
    if len(words) > 6:
        return False

    special_chars = sum(1 for ch in normalized if not (ch.isalnum() or ch.isspace() or ch in ".,;:/'-"))
    digits = sum(1 for ch in normalized if ch.isdigit())
    letters = sum(1 for ch in normalized if ch.isalpha())

    if special_chars >= 2 and len(words) <= 4:
        return True
    if letters <= 8 and digits > 0 and special_chars >= 1:
        return True
    if re.search(r"\b(?:firma|timbro|sig\.|sigla)\b", lowered):
        return True
    return False


def is_likely_page_number_line(line: str) -> bool:
    normalized = line.strip()
    return bool(re.fullmatch(r"\d{1,3}", normalized))


def strip_trailing_stamp_lines(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and (is_likely_stamp_or_signature_line(trimmed[-1]) or is_likely_page_number_line(trimmed[-1])):
        trimmed.pop()

    tail_window_start = max(0, len(trimmed) - 8)
    tail_lines = trimmed[tail_window_start:]
    for offset, line in enumerate(tail_lines):
        lowered = line.lower()
        if "depositato in cancelleria" in lowered or "funzionario giudiziario" in lowered:
            trimmed = trimmed[:tail_window_start + offset]
            break
    return trimmed


def clean_ocr_line(line: str) -> str:
    line = line.replace("|", " ").replace("—", "-").replace("“", "\"").replace("”", "\"")
    line = re.sub(r"\b[\w()/.+-]*[{}\[\]@#][\w()/.+\-{}\[\]@#]*[{}\[\]@#][\w()/.+\-{}\[\]@#]*\b", REDACTED_PLACEHOLDER, line)
    line = re.sub(
        r"(?:[A-Za-z0-9]{0,8}[{}\[\]@#][A-Za-z0-9\s()/.+\-]{0,12}){2,}",
        REDACTED_PLACEHOLDER,
        line,
    )
    tokens = line.split()
    if not tokens:
        return ""

    cleaned_tokens: list[str] = []
    redacted_pending = False

    for token in tokens:
        if token == REDACTED_PLACEHOLDER:
            redacted_pending = True
            continue

        if is_likely_glyph_chaos_token(token) or is_likely_garbage_token(token):
            redacted_pending = True
            continue

        normalized_token = token
        if redacted_pending:
            cleaned_tokens.append(REDACTED_PLACEHOLDER)
            redacted_pending = False
        cleaned_tokens.append(normalized_token)

    if redacted_pending:
        cleaned_tokens.append(REDACTED_PLACEHOLDER)

    cleaned_line = " ".join(cleaned_tokens)
    cleaned_line = re.sub(rf"(?:{re.escape(REDACTED_PLACEHOLDER)}\s*){{2,}}", f"{REDACTED_PLACEHOLDER} ", cleaned_line)
    cleaned_line = re.sub(r"\s+([,.;:])", r"\1", cleaned_line)
    cleaned_line = re.sub(r"\s+", " ", cleaned_line).strip()
    cleaned_line = normalize_latin_legalisms(cleaned_line)

    if not cleaned_line:
        return ""

    letters = sum(1 for ch in cleaned_line if ch.isalpha())
    digits = sum(1 for ch in cleaned_line if ch.isdigit())
    if letters == 0 and digits == 0 and REDACTED_PLACEHOLDER not in cleaned_line:
        return ""

    if len(cleaned_line) <= 4 and REDACTED_PLACEHOLDER in cleaned_line:
        return REDACTED_PLACEHOLDER

    return cleaned_line


def post_process_ocr_text(text: str) -> str:
    lines = text.splitlines()
    cleaned_lines: list[str] = []

    for raw_line in lines:
        line = clean_ocr_line(raw_line)
        if not line:
            continue

        if re.fullmatch(rf"(?:{re.escape(REDACTED_PLACEHOLDER)}\s*)+", line):
            if cleaned_lines and cleaned_lines[-1] == REDACTED_PLACEHOLDER:
                continue
            cleaned_lines.append(REDACTED_PLACEHOLDER)
            continue

        cleaned_lines.append(line)

    cleaned_lines = strip_trailing_stamp_lines(cleaned_lines)
    cleaned_text = "\n".join(cleaned_lines).strip()
    cleaned_text = re.sub(rf"(\n{re.escape(REDACTED_PLACEHOLDER)}){{2,}}", f"\n{REDACTED_PLACEHOLDER}", cleaned_text)
    cleaned_text = normalize_latin_legalisms(cleaned_text)
    return cleaned_text


def post_process_native_text(text: str) -> str:
    if not text:
        return ""

    cleaned = text.replace("\u0000", "")
    cleaned = cleaned.replace("\r", "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def extract_page_text(
    page: fitz.Page,
    pdf_path: Path,
    page_number: int,
    allow_ocr: bool,
    ocr_lang: str,
    ocr_dpi: int,
) -> tuple[str, str]:
    native_text = extract_page_text_native(page)
    if native_text:
        return native_text, "native_pdf_text"

    if not allow_ocr:
        return OCR_PLACEHOLDER, "native_pdf_text"

    if not ensure_tesseract_available():
        return OCR_PLACEHOLDER, "native_pdf_text"

    try:
        ocr_text = extract_page_text_ocr(pdf_path, page_number, lang=ocr_lang, dpi=ocr_dpi)
    except RuntimeError as exc:
        print(f"  OCR fallback fallito: {exc}", file=sys.stderr)
        return OCR_PLACEHOLDER, "ocr_tesseract_failed"
    ocr_text = post_process_ocr_text(ocr_text)
    if ocr_text:
        return ocr_text, "ocr_tesseract"

    return OCR_PLACEHOLDER, "ocr_tesseract"


def main() -> int:
    args = parse_args()
    working_dir = Path.cwd()
    pdfs_dir = get_pdfs_dir(working_dir)
    transcripts_dir = get_transcripts_dir(working_dir)

    pdf_path = args.pdf.expanduser().resolve() if args.pdf else prompt_pdf_path(pdfs_dir)
    if not pdf_path.exists():
        print(f"Errore: PDF non trovato: {pdf_path}", file=sys.stderr)
        return 1

    transcripts_dir.mkdir(exist_ok=True)
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else transcripts_dir / f"{pdf_path.stem}.json"
    )

    results = {
        "source_pdf": str(pdf_path),
        "extraction_method": "native_pdf_text",
        "page_count": 0,
        "pages": [],
    }

    with fitz.open(pdf_path) as document:
        results["page_count"] = len(document)

        for index, page in enumerate(document, start=1):
            print(f"Elaboro pagina {index}/{len(document)}...", file=sys.stderr)
            page_text, method = extract_page_text(
                page,
                pdf_path,
                index,
                allow_ocr=not args.no_ocr,
                ocr_lang=args.ocr_lang,
                ocr_dpi=args.ocr_dpi,
            )
            if method == "ocr_tesseract":
                print(f"  OCR fallback usato per pagina {index}", file=sys.stderr)
            elif method == "ocr_tesseract_failed":
                print(f"  OCR fallback non riuscito per pagina {index}, continuo con placeholder", file=sys.stderr)

            if method == "ocr_tesseract" and results["extraction_method"] == "native_pdf_text":
                results["extraction_method"] = "mixed_native_and_ocr"
            elif method == "ocr_tesseract_failed" and results["extraction_method"] == "native_pdf_text":
                results["extraction_method"] = "mixed_native_and_ocr"

            results["pages"].append(
                {
                    "page_number": index,
                    "text": page_text if page_text else OCR_PLACEHOLDER,
                    "extraction_method": method,
                }
            )

    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON salvato in: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
