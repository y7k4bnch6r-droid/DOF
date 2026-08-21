"""Utilidades compartidas por las pruebas: cliente HTTP falso y config de prueba."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from dofwatch.config import load_config
from dofwatch.http import Response

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Sustituto de HttpClient que sirve fixtures locales por URL."""

    def __init__(self, mapping: dict[str, str | Path] | None = None) -> None:
        self.mapping = dict(mapping or {})
        self.requested: list[str] = []
        self.stats = {"requests": 0, "cache_hits": 0, "errors": 0}

    def add(self, url: str, contenido: str | Path) -> None:
        self.mapping[url] = contenido

    def get(self, url: str, *, allow_404: bool = True, use_cache: bool = True) -> Response:
        self.requested.append(url)
        self.stats["requests"] += 1
        if url not in self.mapping:
            return Response(url, 404, b"")
        valor = self.mapping[url]
        if isinstance(valor, Path):
            datos = valor.read_bytes()
        else:
            datos = valor.encode("utf-8")
        return Response(url, 200, datos, "utf-8")

    def get_json(self, url: str, **kw):
        r = self.get(url, **kw)
        return None if r.status == 404 else r.json()

    def get_text(self, url: str, **kw):
        r = self.get(url, **kw)
        return None if r.status == 404 else r.text


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Copia la configuración real a un directorio temporal de trabajo."""
    raiz = Path(__file__).resolve().parents[1]
    (tmp_path / "config").mkdir()
    for nombre in ("config.yml", "keywords.yml"):
        shutil.copy(raiz / "config" / nombre, tmp_path / "config" / nombre)
    return tmp_path


@pytest.fixture
def cfg(project: Path):
    c = load_config("config/config.yml", root=project)
    c.data["http"]["delay_seconds"] = 0
    c.data["http"]["cache_enabled"] = False
    return c


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()
