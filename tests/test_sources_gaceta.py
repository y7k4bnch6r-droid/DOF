from datetime import date
from pathlib import Path

from dofwatch.sources import GacetaSource

FIXTURES = Path(__file__).parent / "fixtures"


def _src(cfg, client):
    base = cfg["gaceta"]["base"]
    client.add(
        f"{base}/Gaceta/66/2026/jul/20260702.html", FIXTURES / "gaceta_20260702.html"
    )
    return GacetaSource(cfg, client)


def test_urls_del_dia_usan_legislatura_y_mes_abreviado(cfg, fake_client):
    src = GacetaSource(cfg, fake_client)
    urls = src.day_urls(date(2026, 7, 2))
    assert urls[0].endswith("/Gaceta/66/2026/jul/20260702.html")
    assert urls[1].endswith("/Gaceta/66/2026/jul/20260702-I.html")


def test_fecha_fuera_de_legislaturas_registra_incidencia(cfg, fake_client):
    src = GacetaSource(cfg, fake_client)
    assert src.day_urls(date(2040, 1, 2)) == []
    assert src.errors and "legislatura" in src.errors[0]


def test_extrae_asuntos_con_titulo_del_renglon(cfg, fake_client):
    docs = list(_src(cfg, fake_client).iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    titulos = [d.title for d in docs]
    assert any("Ley de los Derechos de las Personas Adultas Mayores" in t for t in titulos)
    assert any("geriatría ante el envejecimiento poblacional" in t for t in titulos)


def test_asigna_seccion_y_numero_de_gaceta(cfg, fake_client):
    docs = list(_src(cfg, fake_client).iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    iniciativa = next(d for d in docs if "Personas Adultas Mayores" in d.title)
    assert iniciativa.section == "Iniciativas"
    assert iniciativa.extra["gaceta"] == "6890-II"


def test_ignora_navegacion_y_enlaces_externos(cfg, fake_client):
    docs = list(_src(cfg, fake_client).iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    urls = [d.url for d in docs]
    assert not any("senado.gob.mx" in u for u in urls)
    assert not any(u.endswith("/gp_index.html") or u.endswith("/index.html") for u in urls)


def test_deduplica_enlaces_repetidos_conservando_el_titulo_largo(cfg, fake_client):
    docs = list(_src(cfg, fake_client).iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    pdfs = [d for d in docs if d.url.endswith("20260702-II-3.pdf")]
    assert len(pdfs) == 1
    assert "duplicado" not in pdfs[0].title


def test_emite_documento_del_indice_con_el_texto_del_dia(cfg, fake_client):
    docs = list(_src(cfg, fake_client).iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    indice = next(d for d in docs if d.extra.get("tipo") == "indice")
    assert "vejez activa" in indice.body
    assert indice.section == "Índice del día"


def test_dia_sin_gaceta_no_produce_documentos(cfg, fake_client):
    src = GacetaSource(cfg, fake_client)
    assert list(src.iter_documents(date(2026, 7, 3), date(2026, 7, 3))) == []


def test_titulo_no_arrastra_la_etiqueta_del_enlace(cfg, fake_client):
    docs = list(_src(cfg, fake_client).iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    iniciativa = next(d for d in docs if "Personas Adultas Mayores" in d.title)
    assert "Ver documento" not in iniciativa.title
    assert "\n" not in iniciativa.title
    assert iniciativa.title.endswith("en materia de cuidados")


def test_el_indice_pesa_menos_que_los_asuntos(cfg, fake_client):
    docs = list(_src(cfg, fake_client).iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    indice = next(d for d in docs if d.extra.get("tipo") == "indice")
    assert indice.weight < 1.0
