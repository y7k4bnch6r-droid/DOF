from datetime import date

from dofwatch.matching import Match
from dofwatch.models import Document
from dofwatch.store import Store


def _doc(uid_suffix="1", titulo="Personas mayores") -> Document:
    return Document(
        source="dof",
        doc_id=f"57123{uid_suffix}",
        title=titulo,
        url="https://www.dof.gob.mx/nota_detalle.php?codigo=1",
        published=date(2026, 7, 2),
        section="Edición matutina",
        organism="SECRETARÍA DE BIENESTAR",
        matches=[Match("vejez", "Vejez", in_title=True, count=1, snippets=["…vejez…"])],
        score=6,
    )


def test_primera_insercion_es_nueva_y_la_segunda_no(tmp_path):
    with Store(tmp_path / "s.sqlite3") as store:
        assert store.upsert(_doc(), "2026-07") is True
        assert store.upsert(_doc(), "2026-07") is False


def test_upsert_actualiza_titulo_sin_perder_el_mes_original(tmp_path):
    with Store(tmp_path / "s.sqlite3") as store:
        store.upsert(_doc(), "2026-07")
        store.upsert(_doc(titulo="Título corregido"), "2026-08")
        (doc,) = store.documents_between(date(2026, 7, 1), date(2026, 7, 31))
    assert doc.title == "Título corregido"
    assert doc.extra["digest_month"] == "2026-07"


def test_recupera_documentos_con_sus_coincidencias(tmp_path):
    with Store(tmp_path / "s.sqlite3") as store:
        store.upsert(_doc(), "2026-07")
        (doc,) = store.documents_between(date(2026, 7, 1), date(2026, 7, 31))
    assert doc.matches[0].term_label == "Vejez"
    assert doc.matches[0].in_title is True
    assert doc.matches[0].snippets == ["…vejez…"]
    assert doc.organism == "SECRETARÍA DE BIENESTAR"


def test_filtra_por_periodo(tmp_path):
    with Store(tmp_path / "s.sqlite3") as store:
        store.upsert(_doc(), "2026-07")
        assert store.documents_between(date(2026, 8, 1), date(2026, 8, 31)) == []


def test_registro_de_corridas(tmp_path):
    with Store(tmp_path / "s.sqlite3") as store:
        rid = store.start_run(date(2026, 7, 1), date(2026, 7, 31), ["dof", "gaceta"])
        store.finish_run(rid, scanned=120, found=4, new_docs=3, errors=["algo falló"])
        (corrida,) = store.last_runs()
    assert corrida["scanned"] == 120 and corrida["new_docs"] == 3
    assert "algo falló" in corrida["errors"]
