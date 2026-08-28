from dataclasses import dataclass
from enum import Enum, auto


class VerticalAlign(Enum):
    NORMAL = auto()
    SUPERSCRIPT = auto()
    SUBSCRIPT = auto()


class ParagraphAlign(Enum):
    LEFT = auto()
    RIGHT = auto()
    CENTER = auto()
    JUSTIFY = auto()


class ParagraphKind(Enum):
    BODY = auto()
    QUOTE = auto()
    LIST_ITEM_BULLET = auto()
    LIST_ITEM_NUMBER = auto()
    HEADING = auto()


@dataclass(frozen=True)
class CharFormat:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    vertical_align: VerticalAlign = VerticalAlign.NORMAL
    font_name: str | None = None
