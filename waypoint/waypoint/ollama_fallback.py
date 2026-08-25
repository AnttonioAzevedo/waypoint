# Ported from flicky's ollama-api.ts isVisionModel() family list (spec
# Component 11) - Ollama doesn't self-report vision capability, so
# detection is by name-family match. "devstral" was removed from this
# list after validation (spec stream-json findings) - it's a code model,
# not a vision model.
VISION_FAMILIES: list[str] = [
    "llava", "bakllava", "moondream", "cogvlm", "minicpm-v",
    "llava-llama3", "llava-phi3", "granite3.2-vision",
    "qwen2-vl", "qwen2.5-vl", "qwen3-vl",
    "llava-v1.6", "llava-v1.5", "gemma3", "gemma4",
    "mistral-small3.1",
]


def is_vision_model(model_name: str) -> bool:
    lowered = model_name.lower()
    return any(family in lowered for family in VISION_FAMILIES)


def pick_vision_model(available_models: list[str]) -> str | None:
    for name in available_models:
        if is_vision_model(name):
            return name
    return None
