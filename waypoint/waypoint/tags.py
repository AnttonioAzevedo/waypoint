import re
from dataclasses import dataclass, field
from typing import Union

_TAG_PATTERN = re.compile(r"\[(POINT|HIGHLIGHT|ANNOTATE):([^\]]+)\]")


@dataclass
class PointTag:
    x: float
    y: float
    label: str
    screen: int


@dataclass
class HighlightTag:
    x: float
    y: float
    w: float
    h: float
    screen: int


@dataclass
class AnnotateTag:
    shape: str
    params: list[float] = field(default_factory=list)
    screen: int = 0


Tag = Union[PointTag, HighlightTag, AnnotateTag]


def _parse_screen(token: str) -> int:
    return int(token.replace("screen", ""))


def parse_tags(text: str) -> list[Tag]:
    tags: list[Tag] = []
    for match in _TAG_PATTERN.finditer(text):
        kind, body = match.group(1), match.group(2)
        parts = body.split(":")

        if kind == "POINT":
            x_str, y_str = parts[0].split(",")
            tags.append(PointTag(x=float(x_str), y=float(y_str), label=parts[1], screen=_parse_screen(parts[2])))

        elif kind == "HIGHLIGHT":
            x_str, y_str, w_str, h_str = parts[0].split(",")
            tags.append(HighlightTag(x=float(x_str), y=float(y_str), w=float(w_str), h=float(h_str), screen=_parse_screen(parts[1])))

        elif kind == "ANNOTATE":
            shape = parts[0]
            params = [float(p) for p in parts[1].split(",")]
            tags.append(AnnotateTag(shape=shape, params=params, screen=_parse_screen(parts[2])))

    return tags


def strip_tags(text: str) -> str:
    return _TAG_PATTERN.sub("", text).strip()
