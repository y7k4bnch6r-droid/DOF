"""Definicion de terminos de busqueda y motor de coincidencias."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalize import collapse, normalize_with_map

# Caracteres que cuentan como parte de una palabra en el texto ya normalizado.
_WORD = "0-9a-z"


@dataclass(frozen=True)
class Term:
    """Un tema a vigilar, con todas sus variantes de escritura."""

    id: str
    label: str
    patterns: tuple[str, ...]
    enabled: bool = True
    weight: int = 1

    @property
    def regex(self) -> re.Pattern[str]:
        return compile_patterns(self.patterns)


@dataclass
class Match:
    """Coincidencias de un termino dentro de un documento."""

    term_id: str
    term_label: str
    in_title: bool = False
    in_body: bool = False
    count: int = 0
    snippets: list[str] = field(default_factory=list)

    @property
    def fields(self) -> str:
        partes = []
        if self.in_title:
            partes.append("titulo")
        if self.in_body:
            partes.append("cuerpo")
        return "+".join(partes) or "-"

    def to_dict(self) -> dict:
        return {
            "term_id": self.term_id,
            "term_label": self.term_label,
            "in_title": self.in_title,
            "in_body": self.in_body,
            "count": self.count,
            "snippets": self.snippets,
        }


def _pattern_to_regex(pattern: str) -> str:
    """Traduce un patron de configuracion a fragmento de expresion regular.

    - ``re:...`` se usa tal cual (ya debe venir en forma normalizada).
    - ``*`` equivale a "resto de la palabra" (``envejec*`` -> envejecimiento).
    - Los espacios aceptan saltos de linea y espacios multiples.
    """
    if pattern.startswith("re:"):
        return f"(?:{pattern[3:]})"

    norm, _ = normalize_with_map(pattern)
    piezas = [re.escape(p) for p in norm.split(" ") if p]
    cuerpo = r"\s+".join(piezas)
    cuerpo = cuerpo.replace(r"\*", rf"[{_WORD}]*")
    # Guiones opcionales: la Gaceta parte palabras al final de renglon.
    return rf"(?<![{_WORD}]){cuerpo}(?![{_WORD}])"


def compile_patterns(patterns: tuple[str, ...] | list[str]) -> re.Pattern[str]:
    alternativas = "|".join(_pattern_to_regex(p) for p in patterns)
    return re.compile(alternativas)


def find_matches(
    terms: list[Term],
    title: str,
    body: str = "",
    snippet_chars: int = 140,
    max_snippets: int = 3,
) -> list[Match]:
    """Busca cada termino en titulo y cuerpo; devuelve solo los que aparecen."""
    title_norm, _ = normalize_with_map(title or "")
    body_norm, body_map = normalize_with_map(body or "")

    resultados: list[Match] = []
    for term in terms:
        if not term.enabled:
            continue
        rx = term.regex
        en_titulo = list(rx.finditer(title_norm))
        en_cuerpo = list(rx.finditer(body_norm))
        if not en_titulo and not en_cuerpo:
            continue

        m = Match(
            term_id=term.id,
            term_label=term.label,
            in_title=bool(en_titulo),
            in_body=bool(en_cuerpo),
            count=len(en_titulo) + len(en_cuerpo),
        )
        for hit in en_cuerpo[:max_snippets]:
            m.snippets.append(
                _snippet(body, body_map, hit.start(), hit.end(), snippet_chars)
            )
        resultados.append(m)

    return resultados


def _snippet(
    original: str, mapa: list[int], start: int, end: int, ancho: int
) -> str:
    """Recorta el texto original alrededor de una coincidencia normalizada."""
    if not mapa:
        return ""
    ini_norm = max(0, start - ancho)
    fin_norm = min(len(mapa) - 1, end + ancho)
    ini = mapa[ini_norm]
    fin = min(len(original), mapa[fin_norm] + 1)
    texto = collapse(original[ini:fin])
    prefijo = "…" if ini > 0 else ""
    sufijo = "…" if fin < len(original) else ""
    return f"{prefijo}{texto}{sufijo}"


def score(matches: list[Match], terms_by_id: dict[str, Term]) -> int:
    """Relevancia simple: el titulo pesa 3, el cuerpo 1, por peso del termino."""
    total = 0
    for m in matches:
        peso = terms_by_id[m.term_id].weight if m.term_id in terms_by_id else 1
        if m.in_title:
            total += 3 * peso
        if m.in_body:
            total += min(m.count, 5) * peso
    return total
