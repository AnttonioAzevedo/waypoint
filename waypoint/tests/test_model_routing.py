from waypoint.model_routing import resolve_model


def test_explicit_fast_phrase_wins():
    assert resolve_model("modo rápido, que dia é hoje?") == "haiku"


def test_explicit_deep_phrase_wins():
    assert resolve_model("pensa com calma nisso: qual a melhor arquitetura aqui?") == "opus"


def test_explicit_phrase_overrides_heuristic_keywords():
    # Contains "explica" (would heuristically route to sonnet) but the
    # explicit phrase takes priority per spec Component 15.
    assert resolve_model("modo rápido, explica isso rapidinho") == "haiku"


def test_heuristic_keyword_routes_to_sonnet():
    assert resolve_model("explica como funciona esse sistema") == "sonnet"


def test_short_transcript_without_signal_routes_to_haiku():
    assert resolve_model("que horas são?") == "haiku"


def test_longer_transcript_without_signal_defaults_to_sonnet():
    assert resolve_model("me conta um pouco sobre a história desse prédio que a gente está vendo aqui na tela") == "sonnet"


def test_never_auto_escalates_to_opus():
    long_text = "explica " * 50
    assert resolve_model(long_text) != "opus"
