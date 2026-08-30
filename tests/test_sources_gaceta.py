from datetime import date
from pathlib import Path

from dofwatch.sources import GacetaSource

FIXTURES = Path(__file__).parent / "fixtures"

URL_DIA = "https://gaceta.diputados.gob.mx/Gaceta/66/2026/ago/20260828.html"
DIA = date(2026, 8, 28)


def _src(cfg, client, fixture="gaceta_20260828.html", url=URL_DIA):
    client.add(url, FIXTURES / fixture)
    return GacetaSource(cfg, client)


def _docs(cfg, client, **kw):
    return list(_src(cfg, client, **kw).iter_documents(DIA, DIA))


def test_url_del_dia_usa_legislatura_y_mes_abreviado(cfg, fake_client):
    assert GacetaSource(cfg, fake_client).day_url(DIA) == URL_DIA


def test_fecha_fuera_de_legislaturas_registra_incidencia(cfg, fake_client):
    src = GacetaSource(cfg, fake_client)
    assert src.day_url(date(2040, 1, 2)) is None
    assert src.errors and "legislatura" in src.errors[0]


def test_un_documento_por_asunto_del_indice(cfg, fake_client):
    docs = _docs(cfg, fake_client)
    asuntos = [d for d in docs if d.extra.get("ancla")]
    assert len(asuntos) == 3
    assert asuntos[0].title.startswith("Que reforma el artículo 5o.")
    assert "\n" not in asuntos[0].title


def test_cada_asunto_apunta_a_su_ancla(cfg, fake_client):
    doc = next(d for d in _docs(cfg, fake_client) if d.extra.get("ancla") == "Iniciativa1")
    assert doc.url == f"{URL_DIA}#Iniciativa1"
    assert doc.doc_id.endswith("20260828.html#Iniciativa1")
    assert doc.section == "Iniciativas"
    assert doc.extra["gaceta"] == "7114"


def test_el_cuerpo_es_el_del_ancla_correspondiente(cfg, fake_client):
    docs = {d.extra.get("ancla"): d for d in _docs(cfg, fake_client)}
    assert "envejecimiento poblacional exige garantizar una vejez digna" in docs["Iniciativa1"].body
    assert "envejecimiento" not in docs["Iniciativa2"].body
    assert "notificación" in docs["Iniciativa2"].body


def test_seccion_de_cada_asunto(cfg, fake_client):
    docs = {d.extra.get("ancla"): d for d in _docs(cfg, fake_client)}
    assert docs["Proposicion1"].section == "Proposiciones"


def test_anexos_en_pdf_con_su_descripcion(cfg, fake_client):
    anexos = [d for d in _docs(cfg, fake_client) if d.extra.get("tipo") == "anexo"]
    assert len(anexos) == 2
    assert anexos[0].url == "https://gaceta.diputados.gob.mx/PDF/66/2026/ago/20260828-I.pdf"
    assert anexos[0].title.startswith("Anexo I — Iniciativas recibidas")
    assert anexos[0].section == "Anexos"


def test_no_emite_documento_de_indice_cuando_hay_asuntos(cfg, fake_client):
    assert not [d for d in _docs(cfg, fake_client) if d.extra.get("tipo") == "indice"]


def test_dia_sin_gaceta_no_produce_documentos(cfg, fake_client):
    src = GacetaSource(cfg, fake_client)
    assert list(src.iter_documents(date(2026, 8, 29), date(2026, 8, 29))) == []


def test_respaldo_para_el_formato_antiguo(cfg, fake_client):
    """Sin div#Indice se cae al barrido de enlaces y al texto de la página."""
    url = "https://gaceta.diputados.gob.mx/Gaceta/66/2026/jul/20260702.html"
    docs = list(
        _src(cfg, fake_client, fixture="gaceta_20260702.html", url=url).iter_documents(
            date(2026, 7, 2), date(2026, 7, 2)
        )
    )
    titulos = [d.title for d in docs]
    assert any("Ley de los Derechos de las Personas Adultas Mayores" in t for t in titulos)
    indice = next(d for d in docs if d.extra.get("tipo") == "indice")
    assert "vejez activa" in indice.body
    assert indice.weight < 1.0
