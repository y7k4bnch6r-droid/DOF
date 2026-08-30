"""Utilidades comunes a todas las fuentes."""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Iterable, Iterator

from bs4 import BeautifulSoup

from ..models import Document

log = logging.getLogger(__name__)

MESES_ABBR = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}

MESES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre",
    12: "diciembre",
}

_WS = re.compile(r"[ \t\r\f\v]+")
_ALL_WS = re.compile(r"\s+")
_NL = re.compile(r"\n{3,}")
# Los <b>…</b> dejan la puntuación en su propio renglón: "mayores\n." -> "mayores."
_PUNTUACION_SUELTA = re.compile(r"\s+([,.;:])(?=\s|$)")


def daterange(start: date, end: date, skip_weekends: bool = False) -> Iterator[date]:
    """Itera dia por dia entre dos fechas inclusive."""
    day = start
    while day <= end:
        if not (skip_weekends and day.weekday() >= 5):
            yield day
        day += timedelta(days=1)


def make_soup(html: str) -> BeautifulSoup:
    """BeautifulSoup con lxml si esta disponible; si no, el parser estandar."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001 - lxml puede no estar instalado
        return BeautifulSoup(html, "html.parser")


def tidy(texto: str) -> str:
    """Normaliza el texto extraido: renglones limpios, sin lineas vacias de mas."""
    texto = _WS.sub(" ", texto)
    lineas = [ln.strip() for ln in texto.split("\n")]
    texto = "\n".join(ln for ln in lineas if ln)
    texto = _PUNTUACION_SUELTA.sub(r"\1", texto)
    return _NL.sub("\n\n", texto).strip()


def html_to_text(html: str) -> str:
    """Convierte HTML en texto plano legible, sin scripts ni estilos."""
    if not html:
        return ""
    soup = make_soup(html)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return tidy(soup.get_text("\n"))


def clean(texto: str | None) -> str:
    """Colapsa cualquier espacio en blanco (incluidos saltos de linea)."""
    if not texto:
        return ""
    return _ALL_WS.sub(" ", texto.replace("\xa0", " ")).strip()


class Source:
    """Interfaz que implementan DOF y Gaceta."""

    name: str = "base"

    def iter_documents(self, start: date, end: date) -> Iterable[Document]:
        raise NotImplementedError
