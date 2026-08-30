"""Fuente: Diario Oficial de la Federacion.

Usa el servicio JSON del DOF (SIDOF) y, si no responde, cae al HTML publico
de dof.gob.mx. Ambas rutas producen los mismos ``Document``.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qs, urljoin, urlparse

from ..http import FetchError, HttpClient
from ..models import Document
from .base import Source, clean, daterange, html_to_text, make_soup

log = logging.getLogger(__name__)

EDICIONES = {
    "notasmatutinas": ("MAT", "Edición matutina"),
    "notasvespertinas": ("VES", "Edición vespertina"),
    "notasextraordinarias": ("EXT", "Edición extraordinaria"),
    "notasunicas": ("MAT", "Edición única"),
}

# El índice diario de dof.gob.mx está partido por edición: la página muestra
# una y enlaza a la otra con index.php?...&edicion=VES (o MAT, o EXT).
EDICIONES_WEB = {
    "MAT": "Edición matutina",
    "VES": "Edición vespertina",
    "EXT": "Edición extraordinaria",
}
MAX_PAGINAS_POR_DIA = 4


def _pick(d: dict, *nombres: str) -> Any:
    """Lee una clave del JSON sin depender de mayusculas/acentos exactos."""
    if not isinstance(d, dict):
        return None
    lower = {str(k).lower(): v for k, v in d.items()}
    for n in nombres:
        if n.lower() in lower:
            valor = lower[n.lower()]
            if valor not in (None, ""):
                return valor
    return None


class DofSource(Source):
    name = "dof"

    def __init__(self, cfg, client: HttpClient) -> None:
        self.cfg = cfg
        self.client = client
        self.conf = cfg["dof"]
        self.api_base = self.conf["api_base"].rstrip("/")
        self.web_base = self.conf["web_base"].rstrip("/")
        self.errors: list[str] = []
        self.days_with_data = 0

    # -- API ---------------------------------------------------------------
    def _api_day_url(self, day: date) -> str:
        return f"{self.api_base}/documentos/completo/{day.strftime('%d-%m-%Y')}"

    def _api_note_url(self, cod_nota: str) -> str:
        return f"{self.api_base}/notas/{cod_nota}"

    def nota_url(self, cod_nota: str, day: date) -> str:
        return f"{self.web_base}/nota_detalle.php?codigo={cod_nota}&fecha={day.strftime('%d/%m/%Y')}"

    def _fetch_day_api(self, day: date) -> list[dict] | None:
        """Lista de notas del dia via JSON, o None si el servicio no sirve."""
        if not self.conf.get("api_enabled", False):
            return None
        try:
            data = self.client.get_json(self._api_day_url(day))
        except FetchError as exc:
            log.warning("DOF API no disponible para %s: %s", day, exc)
            return None
        if data is None:
            # 404 o cuerpo vacío: no sabemos si el día existe, probamos el HTML.
            return None
        if isinstance(data, dict) and _pick(data, "Existe") is False:
            return []

        ediciones_ok = {e.upper() for e in self.conf.get("editions", [])}
        notas: list[dict] = []
        contenedor = data if isinstance(data, dict) else {}
        for clave, valor in contenedor.items():
            info = EDICIONES.get(str(clave).lower())
            if not info or not isinstance(valor, list):
                continue
            code, etiqueta = info
            if ediciones_ok and code not in ediciones_ok:
                continue
            for nota in valor:
                if isinstance(nota, dict):
                    notas.append({"_edicion": etiqueta, **nota})
        return notas

    def _fetch_body_api(self, cod_nota: str) -> str:
        try:
            data = self.client.get_json(self._api_note_url(cod_nota))
        except FetchError as exc:
            self.errors.append(f"DOF nota {cod_nota}: {exc}")
            return ""
        if not data:
            return ""
        nota = _pick(data, "Nota", "nota") or data
        html = _pick(nota, "cadenaContenido", "contenido", "textoNota") or ""
        return html_to_text(str(html))

    # -- HTML (fuente principal) -------------------------------------------
    def _index_url(self, day: date, edicion: str | None = None) -> str:
        url = (
            f"{self.web_base}/index.php?year={day.year}"
            f"&month={day.month:02d}&day={day.day:02d}"
        )
        return f"{url}&edicion={edicion}" if edicion else url

    def _fetch_day_html(self, day: date) -> list[dict]:
        """Notas del dia recorriendo la pagina del indice y sus ediciones."""
        ediciones_ok = {e.upper() for e in self.conf.get("editions", [])}
        notas: dict[str, dict] = {}
        pendientes = [self._index_url(day)]
        vistas: set[str] = set()

        while pendientes and len(vistas) < MAX_PAGINAS_POR_DIA:
            url = pendientes.pop(0)
            if url in vistas:
                continue
            vistas.add(url)
            try:
                html = self.client.get_text(url)
            except FetchError as exc:
                self.errors.append(f"DOF {day.isoformat()}: {exc}")
                continue
            if not html:
                continue

            soup = make_soup(html)
            otras = self._otras_ediciones(soup, url, day)
            codigo_ed, etiqueta = self._edicion_de(url, otras)
            if not ediciones_ok or codigo_ed in ediciones_ok:
                for cod, nota in self._notas_de_pagina(soup, etiqueta).items():
                    notas.setdefault(cod, nota)
            pendientes.extend(otras)

        return list(notas.values())

    @staticmethod
    def _notas_de_pagina(soup, etiqueta: str) -> dict[str, dict]:
        notas: dict[str, dict] = {}
        for a in soup.select('a[href*="nota_detalle.php"]'):
            qs = parse_qs(urlparse(a.get("href") or "").query)
            cod = (qs.get("codigo") or [""])[0]
            titulo = clean(a.get_text(" "))
            if not cod or not titulo or cod in notas:
                continue
            notas[cod] = {
                "_edicion": etiqueta,
                "codNota": cod,
                "titulo": titulo,
                "nombreCodOrgaUno": DofSource._organismo_html(a),
            }
        return notas

    def _otras_ediciones(self, soup, url: str, day: date) -> list[str]:
        """URLs del mismo dia para las demas ediciones enlazadas en la pagina."""
        destinos: list[str] = []
        for a in soup.select('a[href*="edicion="]'):
            destino = urljoin(url, a.get("href") or "")
            partes = urlparse(destino)
            if "index.php" not in partes.path:
                continue
            qs = parse_qs(partes.query)
            mismo_dia = (
                qs.get("year", [""])[0] == str(day.year)
                and qs.get("month", [""])[0].lstrip("0") == str(day.month)
                and qs.get("day", [""])[0].lstrip("0") == str(day.day)
            )
            if mismo_dia and destino not in destinos:
                destinos.append(destino)
        return destinos

    @staticmethod
    def _edicion_de(url: str, otras: list[str]) -> tuple[str, str]:
        """Codigo y etiqueta de la edicion que muestra una pagina del indice."""
        propia = parse_qs(urlparse(url).query).get("edicion", [""])[0].upper()
        if propia:
            return propia, EDICIONES_WEB.get(propia, f"Edición {propia}")
        # Sin parámetro: la página es la edición que *no* aparece enlazada.
        enlazadas = {
            parse_qs(urlparse(u).query).get("edicion", [""])[0].upper() for u in otras
        }
        if enlazadas == {"MAT"}:
            return "VES", EDICIONES_WEB["VES"]
        return "MAT", EDICIONES_WEB["MAT"]

    @staticmethod
    def _organismo_html(anchor) -> str | None:
        """Dependencia: el encabezado en mayusculas mas cercano antes del enlace."""
        for prev in anchor.find_all_previous(["td", "div", "p", "h2", "h3", "b", "strong"], limit=40):
            texto = clean(prev.get_text(" "))
            if not texto or len(texto) > 120 or prev.find("a"):
                continue
            letras = [c for c in texto if c.isalpha()]
            if letras and all(c.isupper() for c in letras):
                return texto
        return None

    def _fetch_body_html(self, cod_nota: str, day: date) -> str:
        try:
            html = self.client.get_text(self.nota_url(cod_nota, day))
        except FetchError as exc:
            self.errors.append(f"DOF nota {cod_nota}: {exc}")
            return ""
        if not html:
            return ""
        soup = make_soup(html)
        detalle = soup.select_one("#DivDetalleNota") or soup.select_one("#DetalleNota")
        return html_to_text(str(detalle) if detalle else html)

    # -- interfaz ----------------------------------------------------------
    def iter_documents(self, start: date, end: date) -> Iterable[Document]:
        skip_weekends = bool(self.conf.get("skip_weekends", True))
        full_text = bool(self.conf.get("full_text", True))

        for day in daterange(start, end, skip_weekends=skip_weekends):
            notas = self._fetch_day_api(day)
            via_api = bool(notas)
            if not notas:
                # El servicio JSON está apagado (o no respondió): HTML público.
                notas = self._fetch_day_html(day)
            if not notas:
                continue
            self.days_with_data += 1
            log.info("DOF %s: %d notas", day.isoformat(), len(notas))
            yield from self._documents_for_day(day, notas, via_api, full_text)

    def _documents_for_day(
        self, day: date, notas: list[dict], via_api: bool, full_text: bool
    ) -> Iterator[Document]:
        for nota in notas:
            cod = str(_pick(nota, "codNota", "codigoNota", "codigo") or "").strip()
            titulo = clean(str(_pick(nota, "titulo", "tituloNota", "nombreNota") or ""))
            if not cod and not titulo:
                continue
            organismo = clean(
                str(
                    _pick(nota, "nombreCodOrgaUno", "organismoTitulo", "organismo", "dependencia")
                    or ""
                )
            ) or None

            cuerpo = ""
            if full_text and cod:
                cuerpo = self._fetch_body_api(cod) if via_api else self._fetch_body_html(cod, day)
                if via_api and not cuerpo:
                    cuerpo = self._fetch_body_html(cod, day)

            yield Document(
                source=self.name,
                doc_id=cod or re.sub(r"\W+", "-", titulo.lower())[:80],
                title=titulo or f"Nota {cod}",
                url=self.nota_url(cod, day) if cod else f"{self.web_base}/index.php",
                published=day,
                section=nota.get("_edicion"),
                organism=organismo,
                body=cuerpo,
                extra={"via": "api" if via_api else "html"},
            )
