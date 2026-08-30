"""Fuente: Gaceta Parlamentaria de la Camara de Diputados.

La Gaceta publica cada dia una sola pagina que contiene el indice y el texto
completo de todos los asuntos: iniciativas, dictamenes, proposiciones,
convocatorias, etc. La estructura verificada contra el sitio real es:

    <div id="Anexos">   <p><a href="/PDF/66/2026/ago/20260828-I.pdf">Anexo I</a> …</p>
    <div id="Indice">   <a class="Seccion" href="#Iniciativas">Iniciativas</a>
                        <ul><li><a class="Indice" href="#Iniciativa1">título…</a></li>…
    <div id="Contenido"><a name="Iniciativa1"></a><p class="Versales">…</p><p>cuerpo…</p>

De ahi salen: un documento por asunto (titulo del indice + cuerpo del ancla
correspondiente) y uno por anexo en PDF.
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
from .base import MESES_ABBR, Source, clean, daterange, html_to_text, make_soup, tidy

log = logging.getLogger(__name__)

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
    "orden del dia", "orden del día", "acuerdo", "citatorio",
)


class GacetaSource(Source):
    name = "gaceta"

    def __init__(self, cfg, client: HttpClient) -> None:
        self.cfg = cfg
        self.client = client
        self.conf = cfg["gaceta"]
        self.base = self.conf["base"].rstrip("/")
        self.errors: list[str] = []
        self.days_with_data = 0

    # -- URL del dia -------------------------------------------------------
    def day_url(self, day: date) -> str | None:
        leg = legislatura_for(self.cfg, day)
        if leg is None:
            self.errors.append(
                f"Gaceta {day.isoformat()}: sin legislatura configurada para esa fecha"
            )
            return None
        return (
            f"{self.base}/Gaceta/{leg}/{day.year}/{MESES_ABBR[day.month]}/"
            f"{day.strftime('%Y%m%d')}.html"
        )

    # -- indice y cuerpos --------------------------------------------------
    @staticmethod
    def _index_items(soup) -> list[tuple[str, str, str | None]]:
        """(ancla, titulo, seccion) de cada asunto listado en el indice."""
        indice = soup.select_one("#Indice")
        if not indice:
            return []
        items: list[tuple[str, str, str | None]] = []
        seccion: str | None = None
        for a in indice.find_all("a"):
            clases = a.get("class") or []
            if "Seccion" in clases:
                seccion = clean(a.get_text(" ")) or seccion
            elif "Indice" in clases:
                ancla = (a.get("href") or "").lstrip("#")
                titulo = clean(a.get_text(" "))
                if ancla and titulo:
                    items.append((ancla, titulo, seccion))
        return items

    @staticmethod
    def _bodies_by_anchor(soup) -> dict[str, str]:
        """Texto de cada asunto: de su <a name="…"> hasta el siguiente."""
        contenido = soup.select_one("#Contenido")
        if not contenido:
            return {}
        cuerpos: dict[str, str] = {}
        ancla: str | None = None
        partes: list[str] = []

        def guardar() -> None:
            if ancla:
                cuerpos[ancla] = tidy("\n".join(partes))

        for hijo in contenido.children:
            nombre = getattr(hijo, "name", None)
            if nombre == "a" and hijo.get("name"):
                guardar()
                ancla = hijo.get("name")
                partes = []
                continue
            if ancla is None:
                continue
            # Cada hijo es un bloque (<p>, <div>): dentro se separa con espacio
            # para no partir el texto en cada <span class="Negritas">.
            texto = hijo.get_text(" ") if nombre else str(hijo)
            if texto.strip():
                partes.append(texto)
        guardar()
        return cuerpos

    def _anexos(self, soup, url: str, day: date, numero: str | None) -> Iterator[Document]:
        for a in soup.select("#Anexos a[href]"):
            href = a.get("href") or ""
            destino = urljoin(url, href)
            etiqueta = clean(a.get_text(" ")) or "Anexo"
            parrafo = a.find_parent("p")
            descripcion = clean(parrafo.get_text(" ")) if parrafo else etiqueta
            if descripcion.startswith(etiqueta):
                descripcion = descripcion[len(etiqueta):].strip(" —-–:")
            titulo = f"{etiqueta} — {descripcion}" if descripcion else etiqueta

            cuerpo = descripcion
            if self.conf.get("pdf_full_text") and destino.lower().endswith(".pdf"):
                cuerpo = "\n".join(filter(None, [descripcion, self._pdf_text(destino)]))

            yield Document(
                source=self.name,
                doc_id=urlparse(destino).path.lstrip("/"),
                title=titulo[:600],
                url=destino,
                published=day,
                section="Anexos",
                body=cuerpo,
                extra={"gaceta": numero, "tipo": "anexo"},
            )

    def _parse_page(self, url: str, html: str, day: date) -> Iterator[Document]:
        soup = make_soup(html)
        titulo_pagina = clean(soup.title.get_text(" ") if soup.title else "")
        numero = self._numero_gaceta(titulo_pagina)
        ruta = urlparse(url).path.lstrip("/")

        items = self._index_items(soup)
        cuerpos = self._bodies_by_anchor(soup) if items else {}
        for ancla, titulo, seccion in items:
            yield Document(
                source=self.name,
                doc_id=f"{ruta}#{ancla}",
                title=titulo[:600],
                url=f"{url}#{ancla}",
                published=day,
                section=seccion,
                body=cuerpos.get(ancla, ""),
                extra={"gaceta": numero, "ancla": ancla},
            )

        anexos = list(self._anexos(soup, url, day, numero))
        yield from anexos

        if not items and not anexos:
            # Formato desconocido: se cae al barrido genérico de enlaces.
            log.warning("Gaceta %s: sin índice reconocible, se usa el respaldo", url)
            yield from self._parse_page_generico(url, html, day, soup, numero, ruta)

    # -- respaldo para formatos antiguos o inesperados ---------------------
    def _parse_page_generico(
        self, url: str, html: str, day: date, soup, numero: str | None, ruta: str
    ) -> Iterator[Document]:
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
                titulo = _sin_etiqueta(bloque, texto_enlace) or texto_enlace
            titulo = clean(titulo)
            if not titulo or titulo.lower() in NAV_TEXTS:
                continue
            doc_id = urlparse(destino).path.lstrip("/")
            anterior = vistos.get(doc_id)
            if anterior and len(anterior.title) >= len(titulo):
                continue
            vistos[doc_id] = Document(
                source=self.name,
                doc_id=doc_id,
                title=titulo[:600],
                url=destino,
                published=day,
                section=self._section_for(a),
                body=bloque if bloque != titulo else "",
                extra={"gaceta": numero, "indice": url},
            )
        yield from vistos.values()

        if self.conf.get("full_text", True):
            texto = html_to_text(html)
            if texto:
                yield Document(
                    source=self.name,
                    weight=0.4,  # el índice repite lo ya listado: pesa menos
                    doc_id=f"{ruta}#indice",
                    title=clean(soup.title.get_text(" ")) if soup.title else f"Gaceta del {day}",
                    url=url,
                    published=day,
                    section="Índice del día",
                    body=texto,
                    extra={"gaceta": numero, "tipo": "indice"},
                )

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
        for prev in anchor.find_all_previous(
            ["h1", "h2", "h3", "h4", "b", "strong", "font", "td", "div", "p"], limit=60
        ):
            texto = clean(prev.get_text(" "))
            if not texto or len(texto) > 90 or prev.find("a"):
                continue
            if any(s in texto.lower() for s in SECCIONES_CONOCIDAS):
                return texto
        return None

    @staticmethod
    def _block_text(anchor) -> str:
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
            url = self.day_url(day)
            if not url:
                continue
            try:
                html = self.client.get_text(url)
            except FetchError as exc:
                self.errors.append(f"Gaceta {url}: {exc}")
                continue
            if not html:
                continue  # sin gaceta ese día (fin de semana o receso)

            encontrados = 0
            for doc in self._parse_page(url, html, day):
                encontrados += 1
                yield doc
            if encontrados:
                self.days_with_data += 1
                log.info("Gaceta %s: %d asuntos", day.isoformat(), encontrados)


def _sin_etiqueta(bloque: str, etiqueta: str) -> str:
    """Quita del renglon la etiqueta corta del enlace ("Ver documento")."""
    texto = clean(bloque)
    if etiqueta and texto.endswith(etiqueta):
        texto = texto[: -len(etiqueta)]
    return texto.strip(" .;:-–—·")
