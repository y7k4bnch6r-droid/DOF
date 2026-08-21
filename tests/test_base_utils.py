from datetime import date

from dofwatch.sources.base import clean, daterange, html_to_text


def test_html_to_text_quita_scripts_y_estilos():
    html = "<p>Hola</p><script>var x=1;</script><style>p{}</style><p>mundo</p>"
    assert html_to_text(html) == "Hola\nmundo"


def test_html_to_text_pega_la_puntuacion_suelta():
    html = "<p>atención a <b>personas mayores</b>. Fin</p>"
    assert "personas mayores. Fin" in html_to_text(html)


def test_html_to_text_conserva_acentos_y_entidades():
    assert html_to_text("<p>Atenci&oacute;n a la vejez</p>") == "Atención a la vejez"


def test_clean_colapsa_saltos_de_linea():
    assert clean(" Ley  de\n las\tPersonas Mayores ") == "Ley de las Personas Mayores"


def test_daterange_inclusivo():
    dias = list(daterange(date(2026, 7, 1), date(2026, 7, 3)))
    assert dias == [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]


def test_daterange_salta_fines_de_semana():
    dias = list(daterange(date(2026, 7, 3), date(2026, 7, 6), skip_weekends=True))
    assert dias == [date(2026, 7, 3), date(2026, 7, 6)]
