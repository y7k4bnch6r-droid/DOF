"""Cliente HTTP cortes: reintentos, pausa entre peticiones y cache en disco."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)


class FetchError(RuntimeError):
    """Fallo definitivo al descargar un recurso (tras agotar reintentos)."""


@dataclass
class Response:
    url: str
    status: int
    content: bytes
    encoding: str | None = None
    from_cache: bool = False

    @property
    def text(self) -> str:
        # UTF-8 se valida a sí mismo: si decodifica, es UTF-8. Esto evita el
        # ISO-8859-1 que requests asume por defecto en text/html sin charset,
        # que convertiría "atención" en "atenciÃ³n".
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            pass
        if self.encoding:
            try:
                return self.content.decode(self.encoding, errors="replace")
            except LookupError:
                pass
        # El DOF y la Gaceta mezclan codificaciones sin declararlas bien.
        for enc in ("cp1252", "latin-1"):
            try:
                return self.content.decode(enc)
            except UnicodeDecodeError:
                continue
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


class HttpClient:
    """Sesion HTTP con cache opcional en disco y reintentos exponenciales."""

    def __init__(
        self,
        user_agent: str,
        timeout: int = 45,
        max_retries: int = 4,
        backoff_seconds: float = 2.0,
        delay_seconds: float = 0.6,
        cache_dir: Path | None = None,
        cache_ttl_days: int = 45,
        sleep=time.sleep,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "es-MX,es;q=0.9",
            }
        )
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.delay_seconds = delay_seconds
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl = cache_ttl_days * 86400
        self._sleep = sleep
        self._last_request = 0.0
        self.stats = {"requests": 0, "cache_hits": 0, "errors": 0}

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -- cache -------------------------------------------------------------
    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        assert self.cache_dir is not None
        return self.cache_dir / f"{key}.bin", self.cache_dir / f"{key}.json"

    def _cache_read(self, url: str) -> Response | None:
        if not self.cache_dir:
            return None
        body, meta = self._cache_paths(url)
        if not body.exists() or not meta.exists():
            return None
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - info.get("ts", 0) > self.cache_ttl:
            return None
        self.stats["cache_hits"] += 1
        return Response(
            url=url,
            status=info.get("status", 200),
            content=body.read_bytes(),
            encoding=info.get("encoding"),
            from_cache=True,
        )

    def _cache_write(self, url: str, resp: Response) -> None:
        if not self.cache_dir:
            return
        body, meta = self._cache_paths(url)
        try:
            body.write_bytes(resp.content)
            meta.write_text(
                json.dumps(
                    {"url": url, "status": resp.status, "encoding": resp.encoding, "ts": time.time()}
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # cache llena o sin permisos: no es fatal
            log.debug("No se pudo escribir cache de %s: %s", url, exc)

    # -- peticiones --------------------------------------------------------
    def _throttle(self) -> None:
        if self.delay_seconds <= 0:
            return
        espera = self.delay_seconds - (time.monotonic() - self._last_request)
        if espera > 0:
            self._sleep(espera)
        self._last_request = time.monotonic()

    def get(self, url: str, *, allow_404: bool = True, use_cache: bool = True) -> Response:
        """Descarga una URL. Devuelve la respuesta aunque sea 404 si se permite."""
        if use_cache:
            cached = self._cache_read(url)
            if cached is not None:
                log.debug("cache hit %s", url)
                return cached

        ultimo_error: Exception | None = None
        for intento in range(self.max_retries + 1):
            self._throttle()
            try:
                self.stats["requests"] += 1
                r = self.session.get(url, timeout=self.timeout)
                if r.status_code == 404 and allow_404:
                    resp = Response(url, 404, b"", r.encoding)
                    self._cache_write(url, resp)
                    return resp
                if r.status_code == 429 or r.status_code >= 500:
                    raise FetchError(f"HTTP {r.status_code} en {url}")
                r.raise_for_status()
                resp = Response(url, r.status_code, r.content, r.encoding)
                self._cache_write(url, resp)
                return resp
            except Exception as exc:  # noqa: BLE001 - reintentamos cualquier fallo de red
                ultimo_error = exc
                self.stats["errors"] += 1
                if intento >= self.max_retries:
                    break
                espera = self.backoff_seconds * (2**intento)
                log.warning(
                    "Fallo %s (intento %d/%d): %s — reintento en %.0fs",
                    url,
                    intento + 1,
                    self.max_retries,
                    exc,
                    espera,
                )
                self._sleep(espera)

        raise FetchError(f"No se pudo descargar {url}: {ultimo_error}")

    def get_json(self, url: str, **kw):
        resp = self.get(url, **kw)
        if resp.status == 404:
            return None
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise FetchError(f"Respuesta no-JSON en {url}: {exc}") from exc

    def get_text(self, url: str, **kw) -> str | None:
        resp = self.get(url, **kw)
        if resp.status == 404:
            return None
        return resp.text


def client_from_config(cfg) -> HttpClient:
    h = cfg["http"]
    cache_dir = cfg.path("cache_dir") if h.get("cache_enabled", True) else None
    return HttpClient(
        user_agent=h["user_agent"],
        timeout=h["timeout"],
        max_retries=h["max_retries"],
        backoff_seconds=h["backoff_seconds"],
        delay_seconds=h["delay_seconds"],
        cache_dir=cache_dir,
        cache_ttl_days=h["cache_ttl_days"],
    )
