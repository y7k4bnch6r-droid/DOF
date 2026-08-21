"""Normalizacion de texto para busqueda insensible a acentos y mayusculas."""

from __future__ import annotations

import re
import unicodedata

# Caracteres invisibles que el DOF y la Gaceta insertan al copiar de Word.
_INVISIBLES = {
    "­",  # soft hyphen
    "​",  # zero width space
    "‌",
    "‍",
    "﻿",
    "⁠",
}

_WS_RE = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """Quita diacriticos (a->a, n->n) conservando el resto de los caracteres."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Version normalizada del texto: minusculas, sin acentos, espacios simples."""
    return normalize_with_map(text)[0]


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Normaliza y devuelve tambien el mapa de indices al texto original.

    ``mapa[i]`` es la posicion en ``text`` del caracter que produjo el caracter
    ``i`` del texto normalizado. Sirve para recortar fragmentos legibles (con
    acentos y mayusculas) a partir de una coincidencia hallada en el
    normalizado.
    """
    out: list[str] = []
    idx: list[int] = []
    pending_space = False

    for i, ch in enumerate(text):
        if ch in _INVISIBLES:
            continue
        if ch.isspace() or ch == " ":
            # Los espacios se colapsan y no se emiten al inicio del texto.
            if out:
                pending_space = True
            continue
        if pending_space:
            out.append(" ")
            idx.append(i)
            pending_space = False
        for c in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(c):
                continue
            out.append(c.lower())
            idx.append(i)

    return "".join(out), idx


def collapse(text: str) -> str:
    """Colapsa espacios conservando acentos y mayusculas (para fragmentos)."""
    return _WS_RE.sub(" ", text.replace(" ", " ")).strip()
