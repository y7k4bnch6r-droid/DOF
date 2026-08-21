"""Interfaz de linea de comandos de dofwatch."""

from __future__ import annotations

import argparse
import calendar
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .digest import issue_body, month_label, render_html, render_markdown, summarize, write_digest
from .http import client_from_config
from .matching import find_matches
from .notify import NotifyError, post_webhook, send_email
from .pipeline import RunResult, run as run_pipeline
from .store import Store

log = logging.getLogger("dofwatch")


# -- utilidades de fechas --------------------------------------------------
def month_bounds(anio: int, mes: int) -> tuple[date, date]:
    ultimo = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, 1), date(anio, mes, ultimo)


def parse_month(texto: str) -> tuple[date, date]:
    try:
        anio, mes = texto.split("-")
        return month_bounds(int(anio), int(mes))
    except (ValueError, calendar.IllegalMonthError) as exc:
        raise argparse.ArgumentTypeError(f"Mes inválido '{texto}', usa AAAA-MM") from exc


def previous_month(today: date | None = None) -> tuple[date, date]:
    hoy = today or datetime.now(timezone.utc).date()
    primero = hoy.replace(day=1)
    fin = primero - timedelta(days=1)
    return month_bounds(fin.year, fin.month)


def resolve_period(args) -> tuple[date, date]:
    if args.since or args.until:
        if not (args.since and args.until):
            raise SystemExit("--since y --until deben usarse juntos")
        return date.fromisoformat(args.since), date.fromisoformat(args.until)
    if args.month:
        return parse_month(args.month)
    return previous_month()


def month_key(start: date) -> str:
    return f"{start.year:04d}-{start.month:02d}"


# -- comandos --------------------------------------------------------------
def cmd_run(args, cfg: Config) -> int:
    inicio, fin = resolve_period(args)
    clave = month_key(inicio)
    log.info("Periodo: %s a %s", inicio, fin)

    if args.titles_only:
        cfg.data["dof"]["full_text"] = False
        cfg.data["gaceta"]["full_text"] = False
    if args.no_cache:
        cfg.data["http"]["cache_enabled"] = False
    if args.pdf:
        cfg.data["gaceta"]["pdf_full_text"] = True

    cliente = client_from_config(cfg)
    store = None if (args.no_store or args.dry_run) else Store(cfg.path("database"))
    try:
        resultado = run_pipeline(
            cfg,
            inicio,
            fin,
            cliente,
            store=store,
            only_sources=args.source or None,
            digest_month=clave,
        )
    finally:
        if store:
            store.close()

    print(_console_summary(cfg, resultado))

    if args.dry_run:
        log.info("dry-run: no se escribieron digests")
        return 0

    if resultado.scanned == 0 and resultado.errors and not args.allow_empty:
        # Ninguna fuente respondió: no sobrescribimos un digest bueno con uno vacío.
        log.error(
            "No se pudo leer ninguna publicación (%d incidencias). "
            "No se escribió el digest; usa --allow-empty para forzarlo.",
            len(resultado.errors),
        )
        for e in resultado.errors[:5]:
            log.error("  %s", e)
        return 2

    formatos = args.formats.split(",") if args.formats else None
    rutas = write_digest(cfg, resultado, clave, formats=formatos)
    for fmt, ruta in rutas.items():
        print(f"  {fmt:6s} -> {ruta.relative_to(cfg.root) if ruta.is_relative_to(cfg.root) else ruta}")

    if args.notify:
        _notify(cfg, resultado, rutas)
    return 0


def cmd_digest(args, cfg: Config) -> int:
    """Regenera el digest de un mes a partir de lo ya guardado en la base."""
    inicio, fin = resolve_period(args)
    with Store(cfg.path("database")) as store:
        docs = store.documents_between(inicio, fin)
    resultado = RunResult(start=inicio, end=fin, documents=docs)
    resultado.scanned = len(docs)
    rutas = write_digest(
        cfg, resultado, month_key(inicio), formats=args.formats.split(",") if args.formats else None
    )
    print(f"{len(docs)} documentos en {month_label(inicio)}")
    for fmt, ruta in rutas.items():
        print(f"  {fmt:6s} -> {ruta}")
    return 0


def cmd_history(args, cfg: Config) -> int:
    with Store(cfg.path("database")) as store:
        for r in store.last_runs(args.limit):
            print(
                f"#{r['id']:>3} {r['start_date']}..{r['end_date']} "
                f"revisados={r['scanned']:<6} hallazgos={r['found']:<5} nuevos={r['new_docs']:<5} "
                f"inicio={r['started']}"
            )
    return 0


def cmd_check_terms(args, cfg: Config) -> int:
    """Prueba los patrones contra un texto (archivo o stdin)."""
    texto = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    matches = find_matches(
        cfg.enabled_terms,
        args.title or "",
        texto,
        snippet_chars=cfg["matching"]["snippet_chars"],
        max_snippets=cfg["matching"]["max_snippets"],
    )
    if not matches:
        print("Sin coincidencias.")
        return 1
    for m in matches:
        print(f"- {m.term_label}: {m.count} ({m.fields})")
        for s in m.snippets:
            print(f"    … {s}")
    return 0


# -- auxiliares ------------------------------------------------------------
def _console_summary(cfg: Config, resultado: RunResult) -> str:
    resumen = summarize(resultado)
    lineas = [
        "",
        f"Revisados: {resumen['revisados']} · con menciones: {resumen['total']} · nuevos: {resumen['nuevos']}",
    ]
    for datos in resumen["por_fuente"].values():
        lineas.append(
            f"  - {datos['label']}: {datos['hallazgos']} de {datos['revisados']} "
            f"({datos['nuevos']} nuevos)"
        )
    for tid, conteos in sorted(
        resumen["por_termino"].items(), key=lambda kv: -kv[1].get("total", 0)
    ):
        lineas.append(f"  · {resumen['etiquetas_termino'][tid]}: {conteos.get('total', 0)}")
    if resultado.errors:
        lineas.append(f"  ! incidencias: {len(resultado.errors)} (ver digest)")
    lineas.append("")
    return "\n".join(lineas)


def _notify(cfg: Config, resultado: RunResult, rutas: dict) -> None:
    asunto = (
        f"{cfg['digest']['title']} — {month_label(resultado.start)}: "
        f"{len(resultado.documents)} menciones"
    )
    md = rutas["md"].read_text(encoding="utf-8") if "md" in rutas else render_markdown(cfg, resultado)
    html_body = (
        rutas["html"].read_text(encoding="utf-8") if "html" in rutas else render_html(cfg, resultado)
    )
    try:
        if cfg["notify"].get("email_enabled"):
            send_email(cfg, asunto, md, html_body)
        if cfg["notify"].get("webhook_enabled"):
            post_webhook(cfg, f"{asunto}\n{issue_body(md)[:1500]}")
    except NotifyError as exc:
        log.error("%s", exc)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dofwatch",
        description="Monitor mensual del DOF y la Gaceta Parlamentaria por temas de vejez.",
    )
    p.add_argument("--config", default="config/config.yml", help="ruta del YAML de configuración")
    p.add_argument("--root", default=None, help="raíz del proyecto (por defecto, el directorio actual)")
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("--version", action="version", version=f"dofwatch {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def periodo(sp):
        sp.add_argument("--month", help="mes a procesar en formato AAAA-MM (por defecto, el mes pasado)")
        sp.add_argument("--since", help="fecha inicial AAAA-MM-DD (con --until)")
        sp.add_argument("--until", help="fecha final AAAA-MM-DD (con --since)")

    r = sub.add_parser("run", help="descarga, busca términos y escribe el digest")
    periodo(r)
    r.add_argument("--source", action="append", choices=["dof", "gaceta"], help="limita las fuentes")
    r.add_argument("--titles-only", action="store_true", help="no descarga el texto completo")
    r.add_argument("--pdf", action="store_true", help="además extrae texto de los PDFs de la Gaceta")
    r.add_argument("--no-cache", action="store_true", help="ignora la caché en disco")
    r.add_argument("--no-store", action="store_true", help="no escribe en la base de datos")
    r.add_argument("--dry-run", action="store_true", help="sólo reporta en consola")
    r.add_argument(
        "--allow-empty",
        action="store_true",
        help="escribe el digest aunque ninguna fuente haya respondido",
    )
    r.add_argument("--formats", help="formatos separados por coma (md,json,html)")
    r.add_argument("--notify", action="store_true", help="envía correo/webhook si están configurados")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("digest", help="regenera el digest desde la base de datos")
    periodo(d)
    d.add_argument("--formats")
    d.set_defaults(func=cmd_digest)

    h = sub.add_parser("history", help="muestra las últimas corridas")
    h.add_argument("--limit", type=int, default=10)
    h.set_defaults(func=cmd_history)

    c = sub.add_parser("check-terms", help="prueba los patrones contra un texto")
    c.add_argument("file", nargs="?", help="archivo de texto (o stdin)")
    c.add_argument("--title", help="título a evaluar además del cuerpo")
    c.set_defaults(func=cmd_check_terms)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    nivel = logging.WARNING - min(args.verbose, 2) * 10
    logging.basicConfig(
        level=nivel, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", stream=sys.stderr
    )
    cfg = load_config(args.config, root=args.root)
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
