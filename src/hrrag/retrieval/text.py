"""Tokenización léxica para BM25 en español."""
from __future__ import annotations

import re
import unicodedata

STOPWORDS = set(
    """a al algo algun alguna algunas alguno algunos ante antes como con contra cual cuales cuando
    de del desde donde dos el ella ellas ellos en entre era es esa esas ese eso esos esta estas este
    esto estos fue fueron ha han hasta hay la las le les lo los mas me mi mis mucho muy nada ni no
    nos o otra otras otro otros para pero poco por porque que quien se sea segun ser si sin sobre
    son su sus tambien tan te tiene tienen todo todos tu tus un una uno unos y ya yo""".split()
)
TOKEN_RE = re.compile(r"[a-z0-9ñ]+(?:-[a-z0-9]+)*")


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c) or c == "̃")


def tokenize(text: str, stem_len: int = 6) -> list[str]:
    """Minúsculas, sin acentos, sin stopwords y truncamiento a prefijo (stemming ligero).

    Los identificadores (POL-RH-002, RH-F-07, números de artículo) se conservan completos.
    """
    text = strip_accents(text.lower()).replace("ñ", "ñ")
    tokens = []
    for tok in TOKEN_RE.findall(text):
        if tok in STOPWORDS:
            continue
        if "-" in tok or tok.isdigit():
            tokens.append(tok)
            tokens.extend(t for t in tok.split("-") if t and not t.isdigit() and t not in STOPWORDS)
        else:
            tokens.append(tok[:stem_len])
    return tokens
