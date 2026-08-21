"""Fuente: Diario Oficial de la Federacion.

Usa el servicio JSON del DOF (SIDOF) y, si no responde, cae al HTML publico
de dof.gob.mx. Ambas rutas producen los mismos ``Document``.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Iterable, Iterator
from urllib.parse import parse_qs, urlparse

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

    # -- HTML (respaldo) ---------------------------------------------------
    def _fetch_day_html(self, day: date) -> list[dict]:
        url = f"{self.web_base}/index.php?year={day.year}&month={day.month:02d}&day={day.day:02d}"
        try:
            html = self.client.get_text(url)
        except FetchError as exc:
            self.errors.append(f"DOF {day.isoformat()}: {exc}")
            return []
        if not html:
            return []

        soup = make_soup(html)
        notas: list[dict] = []
        vistos: set[str] = set()
        for a in soup.select('a[href*="nota_detalle.php"]'):
            href = a.get("href") or ""
            qs = parse_qs(urlparse(href).query)
            cod = (qs.get("codigo") or [""])[0]
            titulo = clean(a.get_text(" "))
            if not cod or not titulo or cod in vistos:
                continue
            vistos.add(cod)
            notas.append(
                {
                    "_edicion": self._edicion_html(a),
                    "codNota": cod,
                    "titulo": titulo,
                    "nombreCodOrgaUno": self._organismo_html(a),
                }
            )
        return notas

    @staticmethod
    def _edicion_html(anchor) -> str:
        texto = " ".join(
            clean(p.get_text(" "))[:200] for p in anchor.parents if getattr(p, "name", None) == "table"
        ).lower()
        if "vespertina" in texto:
            return "Edición vespertina"
        if "extraordinaria" in texto:
            return "Edición extraordinaria"
        return "Edición matutina"

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
                # Sin respuesta del servicio JSON (o vacía): vamos al HTML público.
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
