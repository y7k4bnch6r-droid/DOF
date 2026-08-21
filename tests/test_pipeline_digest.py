import json
from datetime import date
from pathlib import Path

from dofwatch.digest import render_html, render_json, render_markdown, summarize, write_digest
from dofwatch.pipeline import run as run_pipeline
from dofwatch.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


def _poblar(cfg, client):
    api = cfg["dof"]["api_base"]
    client.add(f"{api}/documentos/completo/02-07-2026", FIXTURES / "dof_20260702.json")
    for cod in ("5712345", "5712346", "5712347", "5712399"):
        client.add(f"{api}/notas/{cod}", FIXTURES / f"dof_nota_{cod}.json")
    gac = cfg["gaceta"]["base"]
    client.add(f"{gac}/Gaceta/66/2026/jul/20260702.html", FIXTURES / "gaceta_20260702.html")


def _run(cfg, client, store=None):
    return run_pipeline(
        cfg, date(2026, 7, 2), date(2026, 7, 2), client, store=store, digest_month="2026-07"
    )


def test_solo_conserva_documentos_con_terminos(cfg, fake_client):
    _poblar(cfg, fake_client)
    r = _run(cfg, fake_client)
    titulos = [d.title for d in r.documents]
    assert r.scanned > len(r.documents)
    assert not any("TIPO de cambio" in t for t in titulos)
    assert any("Pensión para el Bienestar" in t for t in titulos)


def test_encuentra_menciones_en_ambas_fuentes(cfg, fake_client):
    _poblar(cfg, fake_client)
    r = _run(cfg, fake_client)
    assert {d.source for d in r.documents} == {"dof", "gaceta"}


def test_detecta_mencion_solo_en_el_cuerpo(cfg, fake_client):
    _poblar(cfg, fake_client)
    r = _run(cfg, fake_client)
    decreto = next(d for d in r.documents if d.doc_id == "5712346")
    assert [m.in_title for m in decreto.matches] == [False, False]
    assert decreto.matches[0].snippets


def test_no_guarda_el_texto_completo(cfg, fake_client):
    _poblar(cfg, fake_client)
    r = _run(cfg, fake_client)
    assert all(d.body == "" for d in r.documents)


def test_marca_nuevos_solo_la_primera_vez(cfg, fake_client, tmp_path):
    _poblar(cfg, fake_client)
    with Store(tmp_path / "s.sqlite3") as store:
        primera = _run(cfg, fake_client, store)
        segunda = _run(cfg, fake_client, store)
    assert len(primera.new_uids) == len(primera.documents) > 0
    assert segunda.new_uids == set()


def test_limitar_fuentes(cfg, fake_client):
    _poblar(cfg, fake_client)
    r = run_pipeline(
        cfg, date(2026, 7, 2), date(2026, 7, 2), fake_client, only_sources=["gaceta"]
    )
    assert {d.source for d in r.documents} == {"gaceta"}


def test_resumen_cuenta_por_fuente_y_termino(cfg, fake_client):
    _poblar(cfg, fake_client)
    r = _run(cfg, fake_client)
    s = summarize(r)
    assert s["total"] == len(r.documents)
    assert s["por_fuente"]["dof"]["hallazgos"] == 2  # acuerdo y decreto; no el tipo de cambio
    assert s["por_termino"]["envejecimiento"]["total"] >= 1


def test_markdown_tiene_encabezado_tablas_y_enlaces(cfg, fake_client):
    _poblar(cfg, fake_client)
    md = render_markdown(cfg, _run(cfg, fake_client))
    assert md.startswith("# Monitor de vejez y envejecimiento — julio de 2026")
    assert "| Fuente | Revisados | Con menciones | Nuevos |" in md
    assert "https://www.dof.gob.mx/nota_detalle.php?codigo=5712345" in md
    assert "Gaceta Parlamentaria (Cámara de Diputados)" in md


def test_json_es_valido_y_trae_los_terminos(cfg, fake_client):
    _poblar(cfg, fake_client)
    data = json.loads(render_json(cfg, _run(cfg, fake_client)))
    assert data["periodo"] == {"inicio": "2026-07-02", "fin": "2026-07-02"}
    assert {t["id"] for t in data["terminos"]} == {"personas_mayores", "vejez", "envejecimiento"}
    assert data["documentos"][0]["matches"]


def test_html_escapa_contenido(cfg, fake_client):
    _poblar(cfg, fake_client)
    html = render_html(cfg, _run(cfg, fake_client))
    assert html.startswith("<!doctype html>")
    assert "&amp;fecha=" in html


def test_digest_vacio_es_legible(cfg, fake_client):
    r = _run(cfg, fake_client)  # cliente sin fixtures: nada que encontrar
    md = render_markdown(cfg, r)
    assert "Sin menciones en el periodo." in md


def test_write_digest_crea_archivos_y_latest(cfg, fake_client):
    _poblar(cfg, fake_client)
    rutas = write_digest(cfg, _run(cfg, fake_client), "2026-07")
    assert rutas["md"].name == "2026-07.md"
    assert rutas["latest"].read_text(encoding="utf-8") == rutas["md"].read_text(encoding="utf-8")
    assert {p.suffix for p in rutas["md"].parent.iterdir()} == {".md", ".json", ".html"}


def test_el_indice_no_desplaza_a_los_asuntos_en_relevancia(cfg, fake_client):
    _poblar(cfg, fake_client)
    r = _run(cfg, fake_client)
    indice = next(d for d in r.documents if d.extra.get("tipo") == "indice")
    asunto = next(d for d in r.documents if d.doc_id.endswith("20260702-II-1.html"))
    assert indice.score < asunto.score
