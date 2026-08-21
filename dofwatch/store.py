"""Persistencia en SQLite: historial de hallazgos y deduplicacion entre corridas."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from .matching import Match
from .models import Document

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    uid           TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    doc_id        TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL,
    published     TEXT NOT NULL,
    section       TEXT,
    organism      TEXT,
    score         INTEGER NOT NULL DEFAULT 0,
    terms         TEXT NOT NULL DEFAULT '[]',
    matches       TEXT NOT NULL DEFAULT '[]',
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    digest_month  TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_published ON documents(published);
CREATE INDEX IF NOT EXISTS idx_documents_month ON documents(digest_month);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started    TEXT NOT NULL,
    finished   TEXT,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    sources    TEXT NOT NULL,
    scanned    INTEGER NOT NULL DEFAULT 0,
    found      INTEGER NOT NULL DEFAULT 0,
    new_docs   INTEGER NOT NULL DEFAULT 0,
    errors     TEXT NOT NULL DEFAULT '[]'
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        with closing(self.conn.cursor()) as cur:
            cur.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- documentos --------------------------------------------------------
    def upsert(self, doc: Document, digest_month: str | None = None) -> bool:
        """Guarda el documento. Devuelve True si es la primera vez que se ve."""
        ahora = _now()
        with closing(self.conn.cursor()) as cur:
            cur.execute("SELECT uid FROM documents WHERE uid = ?", (doc.uid,))
            es_nuevo = cur.fetchone() is None
            cur.execute(
                """
                INSERT INTO documents (uid, source, doc_id, title, url, published, section,
                                       organism, score, terms, matches, first_seen, last_seen,
                                       digest_month)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(uid) DO UPDATE SET
                    title = excluded.title,
                    url = excluded.url,
                    section = excluded.section,
                    organism = excluded.organism,
                    score = excluded.score,
                    terms = excluded.terms,
                    matches = excluded.matches,
                    last_seen = excluded.last_seen,
                    digest_month = COALESCE(documents.digest_month, excluded.digest_month)
                """,
                (
                    doc.uid,
                    doc.source,
                    doc.doc_id,
                    doc.title,
                    doc.url,
                    doc.published.isoformat(),
                    doc.section,
                    doc.organism,
                    doc.score,
                    json.dumps(doc.terms, ensure_ascii=False),
                    json.dumps([m.to_dict() for m in doc.matches], ensure_ascii=False),
                    ahora,
                    ahora,
                    digest_month,
                ),
            )
        self.conn.commit()
        return es_nuevo

    def known_uids(self) -> set[str]:
        with closing(self.conn.cursor()) as cur:
            return {row[0] for row in cur.execute("SELECT uid FROM documents")}

    def documents_between(self, start: date, end: date) -> list[Document]:
        with closing(self.conn.cursor()) as cur:
            filas = cur.execute(
                "SELECT * FROM documents WHERE published BETWEEN ? AND ? ORDER BY published, source, score DESC",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [self._row_to_document(f) for f in filas]

    @staticmethod
    def _row_to_document(row: sqlite3.Row) -> Document:
        matches = [
            Match(
                term_id=m["term_id"],
                term_label=m["term_label"],
                in_title=m.get("in_title", False),
                in_body=m.get("in_body", False),
                count=m.get("count", 0),
                snippets=m.get("snippets", []),
            )
            for m in json.loads(row["matches"])
        ]
        return Document(
            source=row["source"],
            doc_id=row["doc_id"],
            title=row["title"],
            url=row["url"],
            published=date.fromisoformat(row["published"]),
            section=row["section"],
            organism=row["organism"],
            matches=matches,
            score=row["score"],
            extra={"first_seen": row["first_seen"], "digest_month": row["digest_month"]},
        )

    # -- corridas ----------------------------------------------------------
    def start_run(self, start: date, end: date, sources: list[str]) -> int:
        with closing(self.conn.cursor()) as cur:
            cur.execute(
                "INSERT INTO runs (started, start_date, end_date, sources) VALUES (?,?,?,?)",
                (_now(), start.isoformat(), end.isoformat(), json.dumps(sources)),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def finish_run(
        self, run_id: int, scanned: int, found: int, new_docs: int, errors: list[str]
    ) -> None:
        with closing(self.conn.cursor()) as cur:
            cur.execute(
                "UPDATE runs SET finished=?, scanned=?, found=?, new_docs=?, errors=? WHERE id=?",
                (_now(), scanned, found, new_docs, json.dumps(errors, ensure_ascii=False), run_id),
            )
        self.conn.commit()

    def last_runs(self, limit: int = 10) -> list[dict]:
        with closing(self.conn.cursor()) as cur:
            filas = cur.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(f) for f in filas]
