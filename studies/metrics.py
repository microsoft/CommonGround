"""Lexical proxies for the paper's two coded discourse measures.

The paper had two blinded human coders count spatial deixis and verbal
alignments. These regular-expression counts are only a rough, automatic proxy
for comparing conditions within a run; they are not the paper's coding.
"""
import re

_SPATIAL_TERMS = [
    r'to the (?:right|left) of', r'(?:right|left) of', r'on top of', r'in front of', r'next to',
    r'(?:top|bottom)[ -](?:left|right)', r'above', r'below', r'underneath', r'beside', r'adjacent',
    r'behind', r'under', r'top', r'bottom', r'left', r'right', r'middle', r'centre', r'center', r'corner',
]
_ALIGNMENT_TERMS = [
    r"what'?s next", r'next (?:one|piece)', r'got it', r'all set', r'is that (?:right|correct)',
    r'did you (?:get|place|finish)', r'have you (?:placed|finished)', r'ready', r'done', r'finished',
    r'okay', r'ok',
]
SPATIAL_DEIXIS = re.compile(r'\b(?:' + '|'.join(_SPATIAL_TERMS) + r')\b', re.IGNORECASE)
VERBAL_ALIGNMENT = re.compile(r'\b(?:' + '|'.join(_ALIGNMENT_TERMS) + r')\b', re.IGNORECASE)


def count_spatial_deixis(text: str) -> int:
    return len(SPATIAL_DEIXIS.findall(text or ''))


def count_verbal_alignments(text: str) -> int:
    return len(VERBAL_ALIGNMENT.findall(text or ''))


def count_words(text: str) -> int:
    return len((text or '').split())


# A piece number as the Worker's staging image shows it, e.g. "#3", "piece 3" or "piece #12".
PIECE_NUMBER = re.compile(r'#\s?\d{1,2}\b|\bpiece\s+#?\d{1,2}\b', re.IGNORECASE)


def mentions_piece_number(text: str) -> bool:
    """Whether a message names a piece by its number, which only the Worker can see."""
    return bool(PIECE_NUMBER.search(text or ''))
