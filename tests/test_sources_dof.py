from datetime import date
from pathlib import Path

from dofwatch.sources import DofSource

FIXTURES = Path(__file__).parent / "fixtures"


def _con_api(cfg, client):
    base = cfg["dof"]["api_base"]
    client.add(f"{base}/documentos/completo/02-07-2026", FIXTURES / "dof_20260702.json")
    for cod in ("5712345", "5712346", "5712347", "5712399"):
        client.add(f"{base}/notas/{cod}", FIXTURES / f"dof_nota_{cod}.json")
    return DofSource(cfg, client)


def test_api_lista_notas_de_ambas_ediciones(cfg, fake_client):
    src = _con_api(cfg, fake_client)
    docs = list(src.iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    assert len(docs) == 4
    assert {d.section for d in docs} == {"Edición matutina", "Edición vespertina"}
    assert all(d.extra["via"] == "api" for d in docs)


def test_api_arma_url_publica_y_metadatos(cfg, fake_client):
    src = _con_api(cfg, fake_client)
    doc = next(iter(src.iter_documents(date(2026, 7, 2), date(2026, 7, 2))))
    assert doc.url == "https://www.dof.gob.mx/nota_detalle.php?codigo=5712345&fecha=02/07/2026"
    assert doc.organism == "SECRETARÍA DE BIENESTAR"
    assert doc.published == date(2026, 7, 2)
    assert doc.uid == "dof:5712345"


def test_api_descarga_texto_completo_sin_scripts(cfg, fake_client):
    src = _con_api(cfg, fake_client)
    doc = next(iter(src.iter_documents(date(2026, 7, 2), date(2026, 7, 2))))
    assert "envejecimiento demográfico" in doc.body
    assert "var x" not in doc.body


def test_modo_solo_titulos_no_pide_notas(cfg, fake_client):
    cfg.data["dof"]["full_text"] = False
    src = _con_api(cfg, fake_client)
    list(src.iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    assert not any("/notas/" in u for u in fake_client.requested)


def test_filtro_de_ediciones(cfg, fake_client):
    cfg.data["dof"]["editions"] = ["MAT"]
    src = _con_api(cfg, fake_client)
    docs = list(src.iter_documents(date(2026, 7, 2), date(2026, 7, 2)))
    assert {d.section for d in docs} == {"Edición matutina"}


def test_salta_fines_de_semana(cfg, fake_client):
    src = DofSource(cfg, fake_client)
    list(src.iter_documents(date(2026, 7, 4), date(2026, 7, 5)))  # sábado y domingo
    assert fake_client.requested == []


def test_respaldo_html_cuando_no_hay_api(cfg, fake_client):
    web = cfg["dof"]["web_base"]
    fake_client.add(
        f"{web}/index.php?year=2026&month=07&day=03", FIXTURES / "dof_index_20260703.html"
    )
    for cod in ("5712500", "5712501"):
        fake_client.add(
            f"{web}/nota_detalle.php?codigo={cod}&fecha=03/07/2026",
            FIXTURES / f"dof_nota_detalle_{cod}.html",
        )
    src = DofSource(cfg, fake_client)
    docs = list(src.iter_documents(date(2026, 7, 3), date(2026, 7, 3)))

    assert [d.doc_id for d in docs] == ["5712500", "5712501"]
    assert docs[0].organism == "SECRETARÍA DE SALUD"
    assert docs[0].extra["via"] == "html"
    assert "vejez digna" in docs[0].body


def test_dia_sin_publicacion_no_produce_documentos(cfg, fake_client):
    src = DofSource(cfg, fake_client)
    assert list(src.iter_documents(date(2026, 7, 6), date(2026, 7, 6))) == []
