"""Pruebas de las utilerías puras de radar/monitor.py.

El módulo importa `ddgs` al cargarse, que es una dependencia sólo del radar
(`radar/requirements.txt`) y no del entorno de pruebas de dofwatch; como nada de
lo que se prueba aquí lo toca, se sustituye por un doble antes de cargarlo.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

RADAR = Path(__file__).resolve().parents[1] / "radar" / "monitor.py"


@pytest.fixture(scope="module")
def monitor():
    if "ddgs" not in sys.modules:
        stub = types.ModuleType("ddgs")
        stub.DDGS = object
        sys.modules["ddgs"] = stub
    spec = importlib.util.spec_from_file_location("radar_monitor", RADAR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("crudo, esperado", [
    ("https://Example.COM/Nota/?utm_source=x&id=7#top",
     "https://example.com/Nota?id=7"),
    ("https://example.com/nota/", "https://example.com/nota"),
    ("https://example.com/?fbclid=abc", "https://example.com/"),
    ("  https://example.com/a?igsh=zz&b=1  ", "https://example.com/a?b=1"),
])
def test_canon_url_normaliza(monitor, crudo, esperado):
    assert monitor.canon_url(crudo) == esperado


def test_canon_url_no_revienta_con_basura(monitor):
    assert monitor.canon_url("no es una url") == "no es una url"


@pytest.mark.parametrize("texto", [
    "Pink Doll, la novela de Juana Inés Dehesa",
    "Reseña del libro Pink Doll",
    "Barbie y Pink Doll de Dehesa",          # ruido, pero menciona dehesa
])
def test_es_relevante_acepta(monitor, texto):
    assert monitor.es_relevante(texto)


@pytest.mark.parametrize("texto", [
    "Pink Doll dress, envío gratis",          # sin ancla
    "Pinkydoll NPC stream libro de trucos",   # ancla + ruido, sin dehesa
    "Barbie novela gráfica",                  # ancla + ruido, sin dehesa
    "muñeca de trapo libro",
])
def test_es_relevante_descarta(monitor, texto):
    assert not monitor.es_relevante(texto)


def test_es_relevante_respeta_fronteras_de_palabra(monitor):
    assert not monitor.es_relevante("librería juanita")


def test_delta_str(monitor):
    assert monitor.delta_str(10, None) == "(primera medición)"
    assert monitor.delta_str(10, 10) == "(sin cambio)"
    assert monitor.delta_str(12, 10) == "(+2 vs. mes anterior)"
    assert monitor.delta_str(8, 10) == "(-2 vs. mes anterior)"
    assert monitor.delta_str(4.5, 4.0) == "(+0.5 vs. mes anterior)"
