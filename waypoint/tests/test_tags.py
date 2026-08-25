from waypoint.tags import parse_tags, strip_tags, PointTag, HighlightTag, AnnotateTag


def test_parse_point_tag():
    tags = parse_tags("Olha aqui [POINT:120,340:botão salvar:screen1] pra salvar.")
    assert tags == [PointTag(x=120.0, y=340.0, label="botão salvar", screen=1)]


def test_parse_highlight_tag():
    tags = parse_tags("[HIGHLIGHT:10,20,200,50:screen0] essa área")
    assert tags == [HighlightTag(x=10.0, y=20.0, w=200.0, h=50.0, screen=0)]


def test_parse_annotate_arrow():
    tags = parse_tags("[ANNOTATE:arrow:10,10,100,100:screen0]")
    assert tags == [AnnotateTag(shape="arrow", params=[10.0, 10.0, 100.0, 100.0], screen=0)]


def test_parse_annotate_circle():
    tags = parse_tags("[ANNOTATE:circle:50,60,25:screen1]")
    assert tags == [AnnotateTag(shape="circle", params=[50.0, 60.0, 25.0], screen=1)]


def test_parse_multiple_tags_in_order():
    text = "[POINT:1,2:a:screen0] depois [HIGHLIGHT:3,4,5,6:screen0]"
    tags = parse_tags(text)
    assert len(tags) == 2
    assert isinstance(tags[0], PointTag)
    assert isinstance(tags[1], HighlightTag)


def test_parse_no_tags_returns_empty_list():
    assert parse_tags("resposta sem nenhuma tag") == []


def test_strip_tags_removes_all_families():
    text = "Olha [POINT:1,2:x:screen0] e [HIGHLIGHT:1,2,3,4:screen0] e [ANNOTATE:circle:1,2,3:screen0] aqui."
    assert strip_tags(text) == "Olha  e  e  aqui."


def test_strip_tags_no_tags_returns_original_trimmed():
    assert strip_tags("  texto puro  ") == "texto puro"
