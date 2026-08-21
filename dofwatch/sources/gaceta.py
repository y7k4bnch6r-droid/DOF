"""Fuente: Gaceta Parlamentaria de la Camara de Diputados.

Recorre la pagina indice de cada dia (y sus anexos) y extrae cada asunto
publicado: iniciativas, dictamenes, proposiciones, comunicaciones, etc.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date
from typing import Iterable, Iterator
from urllib.parse import urljoin, urlparse

from ..config import legislatura_for
from ..http import FetchError, HttpClient
from ..models import Document
from .base import MESES_ABBR, Source, clean, daterange, html_to_text, make_soup

log = logging.getLogger(__name__)

# Sufijos de anexos: 20240201.html, 20240201-I.html, 20240201-II.html, ...
SUFIJOS = ["", "-I", "-II", "-III", "-IV", "-V", "-VI", "-VII", "-VIII"]

DOC_EXT = (".html", ".htm", ".pdf", ".doc", ".docx")

NAV_TEXTS = {
    "inicio", "anterior", "siguiente", "regresar", "volver", "indice", "índice",
    "gaceta parlamentaria", "camara de diputados", "cámara de diputados",
    "buscar", "menu", "menú", "imprimir", "arriba",
}

SECCIONES_CONOCIDAS = (
    "iniciativa", "dictamen", "dictámenes", "dictamenes", "proposicion",
    "proposiciones", "comunicacion", "comunicaciones", "convocatoria",
    "prevencion", "prevenciones", "minuta", "acta", "informe", "opinion",
    "declaratoria", "efemeride", "efemérides", "actas", "votos", "agenda",
    "orden del dia", "orden del día", "acuerdo",
)


def _sin_etiqueta(bloque: str, etiqueta: str) -> str:
    """Quita del renglon la etiqueta corta del enlace ("Ver documento")."""
    texto = clean(bloque)
    if etiqueta and texto.endswith(etiqueta):
        texto = texto[: -len(etiqueta)]
    return texto.strip(" .;:-–—\u00b7")


class GacetaSource(Source):
    name = "gaceta"

    def __init__(self, cfg, client: HttpClient) -> None:
        self.cfg = cfg
        self.client = client
        self.conf = cfg["gaceta"]
        self.base = self.conf["base"].rstrip("/")
        self.errors: list[str] = []
        self.days_with_data = 0

    # -- URLs --------------------------------------------------------------
    def day_urls(self, day: date) -> list[str]:
        leg = legislatura_for(self.cfg, day)
        if leg is None:
            self.errors.append(
                f"Gaceta {day.isoformat()}: sin legislatura configurada para esa fecha"
            )
            return []
        mes = MESES_ABBR[day.month]
        stem = f"{self.base}/Gaceta/{leg}/{day.year}/{mes}/{day.strftime('%Y%m%d')}"
        return [f"{stem}{sufijo}.html" for sufijo in SUFIJOS]

    # -- parseo ------------------------------------------------------------
    def _is_document_link(self, href: str) -> bool:
        if not href:
            return False
        href_l = href.strip().lower()
        if href_l.startswith(("javascript:", "mailto:", "#")):
            return False
        ruta = urlparse(href_l).path
        if not ruta.endswith(DOC_EXT):
            return False
        nombre = ruta.rsplit("/", 1)[-1]
        if nombre.startswith(("index", "gp_", "menu", "inicio")):
            return False
        return True

    @staticmethod
    def _section_for(anchor) -> str | None:
        """Rubro del asunto: el encabezado breve mas cercano antes del enlace."""
        for prev in anchor.find_all_previous(
            ["h1", "h2", "h3", "h4", "b", "strong", "font", "td", "div", "p"], limit=60
        ):
            texto = clean(prev.get_text(" "))
            if not texto or len(texto) > 90 or prev.find("a"):
                continue
            bajo = texto.lower()
            if any(s in bajo for s in SECCIONES_CONOCIDAS):
                return texto
        return None

    @staticmethod
    def _block_text(anchor) -> str:
        """Texto del renglon o parrafo que contiene al enlace."""
        mejor = ""
        for padre in anchor.parents:
            if getattr(padre, "name", None) not in {"li", "tr", "p", "div", "td", "dd"}:
                continue
            texto = clean(padre.get_text(" "))
            if 20 <= len(texto) <= 2000:
                mejor = texto
                if padre.name in {"li", "tr", "p"}:
                    break
        return mejor

    def _parse_page(self, url: str, html: str, day: date) -> Iterator[Document]:
        soup = make_soup(html)
        titulo_pagina = clean(soup.title.get_text(" ") if soup.title else "")
        numero = self._numero_gaceta(titulo_pagina)
        vistos: dict[str, Document] = {}

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not self._is_document_link(href):
                continue
            destino = urljoin(url, href)
            if urlparse(destino).netloc != urlparse(self.base).netloc:
                continue

            texto_enlace = clean(a.get_text(" "))
            if texto_enlace.lower() in NAV_TEXTS:
                continue
            bloque = self._block_text(a)
            if len(texto_enlace) >= 25:
                titulo = texto_enlace
            else:
                # El enlace es una etiqueta corta ("Ver documento"): el título
                # real es el renglón, sin esa etiqueta al final.
                titulo = _sin_etiqueta(bloque, texto_enlace) or texto_enlace
            titulo = clean(titulo)
            if not titulo or titulo.lower() in NAV_TEXTS:
                continue

            doc_id = urlparse(destino).path.lstrip("/")
            anterior = vistos.get(doc_id)
            if anterior and len(anterior.title) >= len(titulo):
                continue

            cuerpo = bloque if bloque != titulo else ""
            if self.conf.get("pdf_full_text") and destino.lower().endswith(".pdf"):
                cuerpo = "\n".join(filter(None, [cuerpo, self._pdf_text(destino)]))

            vistos[doc_id] = Document(
                source=self.name,
                doc_id=doc_id,
                title=titulo[:600],
                url=destino,
                published=day,
                section=self._section_for(a),
                organism=None,
                body=cuerpo,
                extra={"gaceta": numero, "indice": url},
            )

        yield from vistos.values()

        # Mencion suelta en el indice (por ejemplo en el orden del dia sin enlace).
        if self.conf.get("full_text", True):
            texto = html_to_text(html)
            if texto:
                yield Document(
                    source=self.name,
                    weight=0.4,  # el índice repite lo ya listado: pesa menos
                    doc_id=urlparse(url).path.lstrip("/") + "#indice",
                    title=titulo_pagina or f"Gaceta Parlamentaria del {day.isoformat()}",
                    url=url,
                    published=day,
                    section="Índice del día",
                    body=texto,
                    extra={"gaceta": numero, "tipo": "indice"},
                )

    @staticmethod
    def _numero_gaceta(titulo_pagina: str) -> str | None:
        m = re.search(r"n[uú]mero\s+([\w\-]+)", titulo_pagina, re.IGNORECASE)
        return m.group(1) if m else None

    def _pdf_text(self, url: str) -> str:
        """Texto de un PDF enlazado (requiere pypdf; si no esta, se omite)."""
        try:
            from pypdf import PdfReader  # import diferido: dependencia opcional
        except ImportError:
            log.debug("pypdf no instalado; se omite el texto de %s", url)
            return ""
        try:
            resp = self.client.get(url)
        except FetchError as exc:
            self.errors.append(f"Gaceta PDF {url}: {exc}")
            return ""
        if resp.status == 404 or not resp.content:
            return ""
        try:
            lector = PdfReader(io.BytesIO(resp.content))
            return "\n".join((pagina.extract_text() or "") for pagina in lector.pages)
        except Exception as exc:  # noqa: BLE001 - PDFs corruptos son comunes
            self.errors.append(f"Gaceta PDF ilegible {url}: {exc}")
            return ""

    # -- interfaz ----------------------------------------------------------
    def iter_documents(self, start: date, end: date) -> Iterable[Document]:
        for day in daterange(start, end):
            encontrados = 0
            fallos_seguidos = 0
            for url in self.day_urls(day):
                try:
                    html = self.client.get_text(url)
                except FetchError as exc:
                    self.errors.append(f"Gaceta {url}: {exc}")
                    html = None
                if not html:
                    fallos_seguidos += 1
                    # El primer hueco tras un anexo válido suele cerrar el día.
                    if fallos_seguidos >= 2 or encontrados == 0:
                        break
                    continue
                fallos_seguidos = 0
                for doc in self._parse_page(url, html, day):
                    encontrados += 1
                    yield doc
            if encontrados:
                self.days_with_data += 1
                log.info("Gaceta %s: %d asuntos", day.isoformat(), encontrados)
