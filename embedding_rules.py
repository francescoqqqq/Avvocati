#!/usr/bin/env python3
from __future__ import annotations

from typing import Callable

from hybrid_rules import *  # noqa: F401,F403
import hybrid_rules as _hybrid_rules


EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
SEMANTIC_DUPLICATE_THRESHOLD = 0.85
EVENT_TYPE_PROTOTYPES = {
    "periodo_lavorativo": "Svolgimento di un rapporto di lavoro, servizio, assunzione o supplenza.",
    "provvedimento_disciplinare": "Contestazione disciplinare o sanzione disciplinare a carico di una parte.",
    "revoca_qualifica": "Revoca di qualifica, titolo o abilitazione da parte di un'autorita'.",
    "modifica_incarico": "Assegnazione, adibizione, spostamento o trasferimento a nuove mansioni o servizio.",
    "aggressione": "Aggressione fisica o violenta subita da una persona durante i fatti di causa.",
    "udienza": "Udienza, trattazione, discussione o decisione della causa davanti al giudice.",
    "deposito_atto": "Deposito, produzione o presentazione di documenti, memorie o atti processuali.",
    "decreto": "Emissione o adozione di un decreto o ordinanza del giudice o dell'autorita'.",
    "chiamata_in_causa": "Autorizzazione o disposizione di chiamata in causa di un terzo.",
    "provvedimento_amministrativo": "Adozione o autorizzazione di un provvedimento amministrativo.",
    "accertamento_medico": "Visita medica, consulenza tecnica o accertamento sanitario o medico legale.",
    "costituzione_in_giudizio": "Costituzione in giudizio di una parte o deposito di comparsa di costituzione.",
    "evento_generico": "Fatto rilevante della causa non classificabile in modo piu' specifico.",
    "altro_fatto_rilevante": "Altro fatto processuale o sostanziale chiaramente descritto ma non tipizzato.",
    "rinvio": "Rinvio della causa o fissazione a una successiva udienza.",
    "sentenza_pronunciata": "Pronuncia o pubblicazione della sentenza da parte del tribunale.",
}

_EMBEDDING_MODEL = None
_TEXT_EMBEDDING_CACHE: dict[str, tuple[float, ...]] = {}
_PROTOTYPE_EMBEDDINGS: dict[str, tuple[float, ...]] = {}


def ensure_embedding_backend():
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL
    try:
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Manca il pacchetto 'sentence-transformers'. Installa prima la dipendenza nel virtualenv, "
            "ad esempio con '.venv/bin/pip install sentence-transformers'."
        ) from exc

    try:
        _EMBEDDING_MODEL = SentenceTransformer(EMBEDDING_MODEL_NAME)
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente locale
        raise RuntimeError(
            f"Impossibile inizializzare il modello di embedding '{EMBEDDING_MODEL_NAME}': {exc}"
        ) from exc
    return _EMBEDDING_MODEL


def _normalize_embedding(vector) -> tuple[float, ...]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return tuple(float(value) for value in vector)


def get_text_embedding(text: str) -> tuple[float, ...]:
    normalized_text = _hybrid_rules.normalize_event_text(text or "")
    if normalized_text in _TEXT_EMBEDDING_CACHE:
        return _TEXT_EMBEDDING_CACHE[normalized_text]

    model = ensure_embedding_backend()
    embedding = model.encode(normalized_text, normalize_embeddings=True)
    normalized_embedding = _normalize_embedding(embedding)
    _TEXT_EMBEDDING_CACHE[normalized_text] = normalized_embedding
    return normalized_embedding


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def get_prototype_embedding(event_type: str) -> tuple[float, ...]:
    if event_type in _PROTOTYPE_EMBEDDINGS:
        return _PROTOTYPE_EMBEDDINGS[event_type]
    prototype = EVENT_TYPE_PROTOTYPES.get(event_type, EVENT_TYPE_PROTOTYPES["evento_generico"])
    embedding = get_text_embedding(prototype)
    _PROTOTYPE_EMBEDDINGS[event_type] = embedding
    return embedding


def classify_factual_event_type(text: str, allowed_types: set[str] | None = None) -> tuple[str, float]:
    candidate_types = [event_type for event_type in (allowed_types or set(EVENT_TYPE_PROTOTYPES)) if event_type in EVENT_TYPE_PROTOTYPES]
    if not candidate_types:
        return "evento_generico", 0.0

    text_embedding = get_text_embedding(text)
    best_type = "evento_generico"
    best_score = -1.0
    for event_type in candidate_types:
        similarity = cosine_similarity(text_embedding, get_prototype_embedding(event_type))
        if similarity > best_score:
            best_type = event_type
            best_score = similarity
    return best_type, best_score


def event_semantic_similarity(left_event: dict, right_event: dict) -> float:
    left_text = f"{left_event.get('tipo_evento', 'altro')}: {left_event.get('evento', '')}"
    right_text = f"{right_event.get('tipo_evento', 'altro')}: {right_event.get('evento', '')}"
    return cosine_similarity(get_text_embedding(left_text), get_text_embedding(right_text))


def deduplicate_same_date_events_semantically(
    events: list[dict],
    similarity_threshold: float = SEMANTIC_DUPLICATE_THRESHOLD,
    priority_fn: Callable[[dict], int] | None = None,
) -> list[dict]:
    by_date: dict[str, list[dict]] = {}
    undated: list[dict] = []
    for event in events:
        if not event.get("data"):
            undated.append(event)
            continue
        by_date.setdefault(event["data"], []).append(event)

    deduped: list[dict] = []
    for same_date_events in by_date.values():
        consumed = [False] * len(same_date_events)
        for index, event in enumerate(same_date_events):
            if consumed[index]:
                continue
            cluster = [event]
            consumed[index] = True
            for other_index in range(index + 1, len(same_date_events)):
                if consumed[other_index]:
                    continue
                other_event = same_date_events[other_index]
                if event_semantic_similarity(event, other_event) >= similarity_threshold:
                    cluster.append(other_event)
                    consumed[other_index] = True

            best_event = max(
                cluster,
                key=lambda item: (
                    item.get("score") or 0,
                    priority_fn(item) if priority_fn else 0,
                    len(str(item.get("evento", "")).split()),
                    -(item.get("pagina") or 0),
                ),
            )
            deduped.append(best_event)

    return deduped + undated
