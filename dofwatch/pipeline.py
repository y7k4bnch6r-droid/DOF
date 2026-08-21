"""Orquestacion: recorrer fuentes, filtrar por terminos y guardar resultados."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from .config import Config
from .http import HttpClient
from .matching import find_matches, score
from .models import Document
from .sources import DofSource, GacetaSource
from .store import Store

log = logging.getLogger(__name__)

SOURCE_CLASSES = {"dof": DofSource, "gaceta": GacetaSource}


@dataclass
class RunResult:
    start: date
    end: date
    documents: list[Document] = field(default_factory=list)
    new_uids: set[str] = field(default_factory=set)
    scanned: int = 0
    errors: list[str] = field(default_factory=list)
    per_source_scanned: dict[str, int] = field(default_factory=dict)
    http_stats: dict[str, int] = field(default_factory=dict)

    @property
    def new_documents(self) -> list[Document]:
        return [d for d in self.documents if d.uid in self.new_uids]


def build_sources(cfg: Config, client: HttpClient, only: list[str] | None = None):
    fuentes = []
    for nombre, clase in SOURCE_CLASSES.items():
        if only and nombre not in only:
            continue
        if not cfg[nombre].get("enabled", True):
            log.info("Fuente %s desactivada por configuración", nombre)
            continue
        fuentes.append(clase(cfg, client))
    return fuentes


def run(
    cfg: Config,
    start: date,
    end: date,
    client: HttpClient,
    store: Store | None = None,
    only_sources: list[str] | None = None,
    digest_month: str | None = None,
) -> RunResult:
    """Recorre el periodo, guarda los documentos que mencionan los terminos."""
    resultado = RunResult(start=start, end=end)
    terms = cfg.enabled_terms
    terms_by_id = cfg.terms_by_id
    min_score = int(cfg["matching"].get("min_score", 1))
    fuentes = build_sources(cfg, client, only_sources)

    run_id = store.start_run(start, end, [f.name for f in fuentes]) if store else None

    for fuente in fuentes:
        vistos = 0
        for doc in fuente.iter_documents(start, end):
            vistos += 1
            resultado.scanned += 1
            doc.matches = find_matches(
                terms,
                doc.title,
                doc.body,
                snippet_chars=cfg["matching"]["snippet_chars"],
                max_snippets=cfg["matching"]["max_snippets"],
            )
            if not doc.matches:
                continue
            doc.score = round(score(doc.matches, terms_by_id) * doc.weight)
            if doc.score < min_score:
                continue
            doc.body = ""  # el texto completo no se guarda: sólo fragmentos
            resultado.documents.append(doc)
            if store and store.upsert(doc, digest_month):
                resultado.new_uids.add(doc.uid)
            elif not store:
                resultado.new_uids.add(doc.uid)
        resultado.per_source_scanned[fuente.name] = vistos
        resultado.errors.extend(getattr(fuente, "errors", []))

    resultado.documents.sort(key=lambda d: (d.published, -d.score, d.source))
    resultado.http_stats = dict(client.stats)

    if store and run_id is not None:
        store.finish_run(
            run_id,
            scanned=resultado.scanned,
            found=len(resultado.documents),
            new_docs=len(resultado.new_uids),
            errors=resultado.errors[:200],
        )

    return resultado
