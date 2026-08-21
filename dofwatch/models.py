"""Estructuras de datos compartidas por las fuentes y el digest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

from .matching import Match

SOURCE_LABELS = {
    "dof": "Diario Oficial de la Federación",
    "gaceta": "Gaceta Parlamentaria (Cámara de Diputados)",
}


@dataclass
class Document:
    """Un documento publicado por alguna de las fuentes vigiladas."""

    source: str
    doc_id: str
    title: str
    url: str
    published: date
    section: str | None = None
    organism: str | None = None
    body: str = ""
    matches: list[Match] = field(default_factory=list)
    score: int = 0
    weight: float = 1.0  # atenua la relevancia de documentos de indice
    extra: dict = field(default_factory=dict)

    @property
    def uid(self) -> str:
        """Identificador estable entre corridas (para deduplicar)."""
        base = f"{self.source}:{self.doc_id}"
        if len(base) <= 120:
            return base
        return f"{self.source}:{hashlib.sha1(base.encode('utf-8')).hexdigest()}"

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def terms(self) -> list[str]:
        return [m.term_label for m in self.matches]

    def to_dict(self, include_body: bool = False) -> dict:
        d = {
            "uid": self.uid,
            "source": self.source,
            "source_label": self.source_label,
            "doc_id": self.doc_id,
            "title": self.title,
            "url": self.url,
            "published": self.published.isoformat(),
            "section": self.section,
            "organism": self.organism,
            "score": self.score,
            "matches": [m.to_dict() for m in self.matches],
            "extra": self.extra,
        }
        if include_body:
            d["body"] = self.body
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)
