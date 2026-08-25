MODEL_HAIKU = "haiku"
MODEL_SONNET = "sonnet"
MODEL_OPUS = "opus"

# Illustrative per spec Open items — finalize exact PT-BR phrases before
# real-world use.
EXPLICIT_PHRASES: dict[str, str] = {
    "pensa com calma nisso": MODEL_OPUS,
    "pensa com calma": MODEL_OPUS,
    "modo profundo": MODEL_OPUS,
    "modo rápido": MODEL_HAIKU,
    "modo rapido": MODEL_HAIKU,
}

_HEURISTIC_KEYWORDS: tuple[str, ...] = ("explica", "analisa", "compara", "por que", "como funciona")

_SHORT_TRANSCRIPT_WORD_LIMIT = 6


def resolve_model(transcript: str) -> str:
    """Component 15: explicit voice command first, heuristic fallback
    second. Never auto-escalates to Opus without an explicit phrase."""
    lowered = transcript.lower()

    for phrase, model in EXPLICIT_PHRASES.items():
        if phrase in lowered:
            return model

    if any(keyword in lowered for keyword in _HEURISTIC_KEYWORDS):
        return MODEL_SONNET

    if len(transcript.split()) <= _SHORT_TRANSCRIPT_WORD_LIMIT:
        return MODEL_HAIKU

    return MODEL_SONNET
