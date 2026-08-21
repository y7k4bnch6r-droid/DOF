import pytest

from dofwatch.http import FetchError, HttpClient


class FakeResponse:
    def __init__(self, status=200, content=b"ok", encoding="utf-8"):
        self.status_code = status
        self.content = content
        self.encoding = encoding

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.headers = {}
        self.llamadas = 0

    def get(self, url, timeout=None):
        self.llamadas += 1
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _client(respuestas, tmp_path=None, **kw):
    dormidas = []
    c = HttpClient(
        "test-agent",
        delay_seconds=0,
        backoff_seconds=0.01,
        cache_dir=tmp_path,
        sleep=dormidas.append,
        **kw,
    )
    c.session = FakeSession(respuestas)
    return c, dormidas


def test_reintenta_ante_error_500_y_luego_avanza():
    c, dormidas = _client([FakeResponse(500), FakeResponse(200, b"listo")])
    assert c.get("https://ejemplo.mx/a").text == "listo"
    assert len(dormidas) == 1


def test_backoff_exponencial():
    c, dormidas = _client([FakeResponse(503)] * 3 + [FakeResponse(200)], max_retries=3)
    c.backoff_seconds = 2.0
    c.get("https://ejemplo.mx/a")
    assert dormidas == [2.0, 4.0, 8.0]


def test_falla_definitiva_tras_agotar_reintentos():
    c, _ = _client([FakeResponse(500)] * 3, max_retries=2)
    with pytest.raises(FetchError):
        c.get("https://ejemplo.mx/a")


def test_404_no_es_error_por_defecto(tmp_path):
    c, _ = _client([FakeResponse(404, b"")], tmp_path=tmp_path)
    r = c.get("https://ejemplo.mx/no-existe")
    assert r.status == 404
    assert c.get_text("https://ejemplo.mx/no-existe") is None  # servido desde caché de 404


def test_cache_evita_una_segunda_peticion(tmp_path):
    c, _ = _client([FakeResponse(200, b"contenido")], tmp_path=tmp_path)
    assert c.get("https://ejemplo.mx/a").text == "contenido"
    segunda = c.get("https://ejemplo.mx/a")
    assert segunda.from_cache and segunda.text == "contenido"
    assert c.session.llamadas == 1
    assert c.stats["cache_hits"] == 1


def test_cache_expira(tmp_path):
    c, _ = _client([FakeResponse(200, b"v1"), FakeResponse(200, b"v2")], tmp_path=tmp_path)
    c.get("https://ejemplo.mx/a")
    c.cache_ttl = -1
    assert c.get("https://ejemplo.mx/a").text == "v2"


def test_decodifica_latin1_cuando_no_hay_codificacion():
    c, _ = _client([FakeResponse(200, "atención".encode("latin-1"), encoding=None)])
    assert c.get("https://ejemplo.mx/a").text == "atención"


def test_utf8_gana_a_la_codificacion_declarada_por_requests():
    # requests asume ISO-8859-1 en text/html sin charset; el contenido es UTF-8.
    c, _ = _client([FakeResponse(200, "atención a la vejez".encode("utf-8"), encoding="ISO-8859-1")])
    assert c.get("https://ejemplo.mx/a").text == "atención a la vejez"
