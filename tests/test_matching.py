from dofwatch.matching import Term, compile_patterns, find_matches, score
from dofwatch.normalize import normalize, normalize_with_map


def test_normalize_quita_acentos_y_espacios():
    assert normalize("  ATENCIÓN  a  las\nPersonas   Mayores ") == "atencion a las personas mayores"


def test_normalize_ignora_caracteres_invisibles():
    assert normalize("enve­jecimiento") == "envejecimiento"


def test_mapa_de_indices_apunta_al_original():
    texto = "La Vejez digna"
    norm, mapa = normalize_with_map(texto)
    i = norm.index("vejez")
    assert texto[mapa[i]] == "V"


def test_frontera_de_palabra(cfg):
    terms = cfg.enabled_terms
    assert find_matches(terms, "vejezuela municipio", "") == []
    assert find_matches(terms, "Ley de la Vejez", "")[0].term_id == "vejez"


def test_comodin_cubre_familia_de_palabras(cfg):
    terms = cfg.enabled_terms
    ms = find_matches(terms, "", "la población envejece y el envejecimiento avanza")
    ids = {m.term_id for m in ms}
    assert "envejecimiento" in ids
    assert next(m for m in ms if m.term_id == "envejecimiento").count == 2


def test_coincidencia_a_traves_de_salto_de_linea(cfg):
    ms = find_matches(cfg.enabled_terms, "", "apoyo a personas\n   mayores del país")
    assert [m.term_id for m in ms] == ["personas_mayores"]


def test_distingue_titulo_de_cuerpo(cfg):
    ms = find_matches(cfg.enabled_terms, "Reglas para personas mayores", "sobre la vejez")
    por_id = {m.term_id: m for m in ms}
    assert por_id["personas_mayores"].in_title and not por_id["personas_mayores"].in_body
    assert por_id["vejez"].in_body and not por_id["vejez"].in_title


def test_snippet_conserva_acentos(cfg):
    ms = find_matches(cfg.enabled_terms, "", "El Estado garantiza una vejez digna y sanà.", snippet_chars=20)
    assert "vejez digna" in ms[0].snippets[0]


def test_score_pondera_titulo(cfg):
    tbi = cfg.terms_by_id
    en_titulo = find_matches(cfg.enabled_terms, "Personas mayores", "")
    en_cuerpo = find_matches(cfg.enabled_terms, "", "personas mayores")
    assert score(en_titulo, tbi) > score(en_cuerpo, tbi)


def test_patron_regex_crudo():
    rx = compile_patterns(["re:ley\\s+\\d+"])
    assert rx.search("la ley 123 dice")


def test_termino_desactivado_no_busca():
    t = Term("x", "X", ("vejez",), enabled=False)
    assert find_matches([t], "vejez", "") == []
