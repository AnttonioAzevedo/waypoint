from waypoint.ollama_fallback import is_vision_model, pick_vision_model


def test_is_vision_model_matches_known_families():
    assert is_vision_model("llava:13b") is True
    assert is_vision_model("qwen2.5-vl:7b") is True
    assert is_vision_model("gemma3:27b") is True


def test_is_vision_model_case_insensitive():
    assert is_vision_model("LLaVA:13B") is True


def test_is_vision_model_false_for_non_vision_models():
    assert is_vision_model("llama3:8b") is False
    assert is_vision_model("mistral:7b") is False


def test_pick_vision_model_returns_first_match():
    models = ["llama3:8b", "llava:13b", "mistral:7b"]
    assert pick_vision_model(models) == "llava:13b"


def test_pick_vision_model_returns_none_if_no_vision_model_available():
    models = ["llama3:8b", "mistral:7b"]
    assert pick_vision_model(models) is None
