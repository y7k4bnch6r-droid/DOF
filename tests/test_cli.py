import json
from datetime import date
from pathlib import Path

import pytest

from dofwatch import cli
from conftest import FakeClient

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_month():
    assert cli.parse_month("2026-07") == (date(2026, 7, 1), date(2026, 7, 31))
    assert cli.parse_month("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))


def test_parse_month_invalido():
    with pytest.raises(Exception):
        cli.parse_month("julio-2026")


def test_previous_month_cruza_el_año():
    assert cli.previous_month(date(2026, 1, 7))[0] == date(2025, 12, 1)


def test_resolve_period_exige_since_y_until():
    args = cli.build_parser().parse_args(["run", "--since", "2026-07-01"])
    with pytest.raises(SystemExit):
        cli.resolve_period(args)


def test_resolve_period_por_rango():
    args = cli.build_parser().parse_args(
        ["run", "--since", "2026-07-01", "--until", "2026-07-15"]
    )
    assert cli.resolve_period(args) == (date(2026, 7, 1), date(2026, 7, 15))


@pytest.fixture
def cliente_con_fixtures(monkeypatch):
    """Escenario realista: DOF por su web pública y Gaceta con el índice del día."""
    client = FakeClient()
    client.add(
        "https://dof.gob.mx/index.php?year=2026&month=07&day=03",
        FIXTURES / "dof_index_20260703.html",
    )
    for cod in ("5712500", "5712501"):
        client.add(
            f"https://dof.gob.mx/nota_detalle.php?codigo={cod}&fecha=03/07/2026",
            FIXTURES / f"dof_nota_detalle_{cod}.html",
        )
    client.add(
        "https://gaceta.diputados.gob.mx/Gaceta/66/2026/ago/20260828.html",
        FIXTURES / "gaceta_20260828.html",
    )
    monkeypatch.setattr(cli, "client_from_config", lambda cfg: client)
    return client


PERIODO = ["--since", "2026-07-03", "--until", "2026-08-28"]


def test_run_escribe_digest_y_base(project, cliente_con_fixtures, capsys):
    codigo = cli.main(["--root", str(project), "run", *PERIODO])
    assert codigo == 0
    salida = capsys.readouterr().out
    assert "con menciones" in salida

    md = (project / "digests" / "2026-07.md").read_text(encoding="utf-8")
    assert "Asistencia social a personas adultas mayores" in md
    assert (project / "digests" / "latest.md").exists()
    assert (project / "data" / "state.sqlite3").exists()

    datos = json.loads((project / "digests" / "2026-07.json").read_text(encoding="utf-8"))
    assert datos["resumen"]["total"] == len(datos["documentos"])


def test_run_dry_run_no_escribe_nada(project, cliente_con_fixtures):
    cli.main(["--root", str(project), "run", *PERIODO, "--dry-run"])
    assert not (project / "digests").exists()
    assert not (project / "data" / "state.sqlite3").exists()


def test_run_marca_nuevos_solo_la_primera_vez(project, cliente_con_fixtures):
    args = ["--root", str(project), "run", *PERIODO]
    cli.main(args)
    primera = (project / "digests" / "2026-07.md").read_text(encoding="utf-8")
    cli.main(args)
    segunda = (project / "digests" / "2026-07.md").read_text(encoding="utf-8")
    assert "🆕" in primera and "🆕" not in segunda


def test_digest_regenera_desde_la_base(project, cliente_con_fixtures):
    cli.main(["--root", str(project), "run", *PERIODO])
    (project / "digests" / "2026-07.md").unlink()
    cli.main(["--root", str(project), "digest", "--month", "2026-07", "--formats", "md"])
    assert "personas adultas mayores" in (project / "digests" / "2026-07.md").read_text("utf-8")


def test_history_lista_corridas(project, cliente_con_fixtures, capsys):
    cli.main(["--root", str(project), "run", *PERIODO])
    cli.main(["--root", str(project), "history"])
    assert "hallazgos=" in capsys.readouterr().out


def test_check_terms(project, tmp_path, capsys):
    archivo = tmp_path / "texto.txt"
    archivo.write_text("Programa de atención a la vejez y al envejecimiento.", encoding="utf-8")
    codigo = cli.main(["--root", str(project), "check-terms", str(archivo)])
    assert codigo == 0
    salida = capsys.readouterr().out
    assert "Vejez" in salida and "Envejecimiento" in salida


def test_check_terms_sin_coincidencias(project, tmp_path):
    archivo = tmp_path / "texto.txt"
    archivo.write_text("Tipo de cambio del día.", encoding="utf-8")
    assert cli.main(["--root", str(project), "check-terms", str(archivo)]) == 1


def test_run_no_sobrescribe_digest_si_todo_falla(project, monkeypatch):
    """Si ninguna fuente responde, el digest previo se conserva y el comando falla."""
    from dofwatch.http import FetchError

    class ClienteCaido(FakeClient):
        def get(self, url, **kw):
            self.stats["requests"] += 1
            raise FetchError(f"sin red: {url}")

    monkeypatch.setattr(cli, "client_from_config", lambda cfg: ClienteCaido())
    (project / "digests").mkdir()
    previo = project / "digests" / "2026-07.md"
    previo.write_text("digest anterior", encoding="utf-8")

    codigo = cli.main(["--root", str(project), "run", *PERIODO])
    assert codigo == 2
    assert previo.read_text(encoding="utf-8") == "digest anterior"


def test_run_con_allow_empty_escribe_digest_vacio(project, monkeypatch):
    from dofwatch.http import FetchError

    class ClienteCaido(FakeClient):
        def get(self, url, **kw):
            self.stats["requests"] += 1
            raise FetchError(f"sin red: {url}")

    monkeypatch.setattr(cli, "client_from_config", lambda cfg: ClienteCaido())
    codigo = cli.main(["--root", str(project), "run", *PERIODO, "--allow-empty"])
    assert codigo == 0
    assert "Sin menciones en el periodo." in (project / "digests" / "2026-07.md").read_text("utf-8")
