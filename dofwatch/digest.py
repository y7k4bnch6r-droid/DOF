"""Generacion del digest mensual en Markdown, JSON y HTML."""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from .config import Config
from .models import SOURCE_LABELS, Document
from .pipeline import RunResult
from .sources.base import MESES

MAX_ISSUE_CHARS = 60000


def month_label(d: date) -> str:
    return f"{MESES[d.month]} de {d.year}"


def _fecha_larga(d: date) -> str:
    return f"{d.day} de {MESES[d.month]} de {d.year}"


def summarize(result: RunResult) -> dict:
    """Conteos por fuente y por termino, mas los documentos mas relevantes."""
    por_fuente: dict[str, dict] = {}
    for fuente in SOURCE_LABELS:
        docs = [d for d in result.documents if d.source == fuente]
        if not docs and fuente not in result.per_source_scanned:
            continue
        por_fuente[fuente] = {
            "label": SOURCE_LABELS[fuente],
            "hallazgos": len(docs),
            "nuevos": sum(1 for d in docs if d.uid in result.new_uids),
            "revisados": result.per_source_scanned.get(fuente, 0),
        }

    por_termino: dict[str, Counter] = defaultdict(Counter)
    etiquetas: dict[str, str] = {}
    for d in result.documents:
        for m in d.matches:
            etiquetas[m.term_id] = m.term_label
            por_termino[m.term_id][d.source] += 1
            por_termino[m.term_id]["total"] += 1

    destacados = sorted(result.documents, key=lambda d: (-d.score, d.published))[:5]

    return {
        "por_fuente": por_fuente,
        "por_termino": {tid: dict(c) for tid, c in por_termino.items()},
        "etiquetas_termino": etiquetas,
        "destacados": [d.uid for d in destacados],
        "total": len(result.documents),
        "nuevos": len(result.new_uids),
        "revisados": result.scanned,
    }


def _terms_line(doc: Document) -> str:
    partes = []
    for m in doc.matches:
        detalle = f"{m.count}×" if m.count > 1 else ""
        partes.append(f"{m.term_label} ({detalle}{m.fields})".replace(" ()", ""))
    return ", ".join(partes)


def render_markdown(cfg: Config, result: RunResult, generated: datetime | None = None) -> str:
    generated = generated or datetime.now(timezone.utc)
    resumen = summarize(result)
    titulo = cfg["digest"]["title"]
    incluir_snippets = bool(cfg["digest"].get("include_snippets", True))
    destacados = set(resumen["destacados"])

    L: list[str] = []
    L.append(f"# {titulo} — {month_label(result.start)}")
    L.append("")
    L.append(
        f"**Periodo:** {_fecha_larga(result.start)} a {_fecha_larga(result.end)}  "
    )
    L.append(f"**Generado:** {generated.strftime('%Y-%m-%d %H:%M UTC')}  ")
    L.append(
        "**Términos vigilados:** "
        + ", ".join(f"*{t.label}*" for t in cfg.enabled_terms)
    )
    L.append("")
    L.append(
        f"Se revisaron **{resumen['revisados']}** publicaciones y **{resumen['total']}** "
        f"mencionan los términos vigilados ({resumen['nuevos']} no aparecían en digests previos)."
    )
    L.append("")

    L.append("## Resumen")
    L.append("")
    L.append("| Fuente | Revisados | Con menciones | Nuevos |")
    L.append("| --- | ---: | ---: | ---: |")
    for datos in resumen["por_fuente"].values():
        L.append(
            f"| {datos['label']} | {datos['revisados']} | {datos['hallazgos']} | {datos['nuevos']} |"
        )
    L.append("")

    if resumen["por_termino"]:
        L.append("| Término | DOF | Gaceta | Total |")
        L.append("| --- | ---: | ---: | ---: |")
        for tid, conteos in sorted(
            resumen["por_termino"].items(), key=lambda kv: -kv[1].get("total", 0)
        ):
            L.append(
                f"| {resumen['etiquetas_termino'][tid]} | {conteos.get('dof', 0)} "
                f"| {conteos.get('gaceta', 0)} | {conteos.get('total', 0)} |"
            )
        L.append("")

    if not result.documents:
        L.append("> Sin menciones en el periodo.")
        L.append("")

    for fuente, label in SOURCE_LABELS.items():
        docs = [d for d in result.documents if d.source == fuente]
        if not docs:
            continue
        L.append(f"## {label} ({len(docs)})")
        L.append("")
        for day, del_dia in _group_by_day(docs):
            L.append(f"### {_fecha_larga(day)}")
            L.append("")
            for doc in del_dia:
                marca = " 🆕" if doc.uid in result.new_uids else ""
                estrella = " ⭐" if doc.uid in destacados else ""
                L.append(f"- **[{_md_escape(doc.title)}]({doc.url})**{marca}{estrella}")
                meta = [p for p in (doc.organism, doc.section) if p]
                if meta:
                    L.append(f"  - {' · '.join(_md_escape(m) for m in meta)}")
                L.append(f"  - Términos: {_terms_line(doc)}")
                if incluir_snippets:
                    for s in doc.matches[0].snippets[:2] if doc.matches else []:
                        L.append(f"  - > {_md_escape(s)}")
            L.append("")

    L.append("---")
    L.append("")
    L.append(
        f"Peticiones HTTP: {result.http_stats.get('requests', 0)} "
        f"(cache: {result.http_stats.get('cache_hits', 0)})."
    )
    if result.errors:
        L.append("")
        L.append(f"<details><summary>Incidencias ({len(result.errors)})</summary>")
        L.append("")
        for e in result.errors[:50]:
            L.append(f"- {_md_escape(e)}")
        if len(result.errors) > 50:
            L.append(f"- … y {len(result.errors) - 50} más")
        L.append("")
        L.append("</details>")
    L.append("")
    L.append(
        "_Generado automáticamente por [dofwatch](../README.md); "
        "las coincidencias son literales y conviene verificar el documento fuente._"
    )
    return "\n".join(L) + "\n"


def _group_by_day(docs: list[Document]):
    agrupado: dict[date, list[Document]] = defaultdict(list)
    for d in docs:
        agrupado[d.published].append(d)
    for day in sorted(agrupado):
        yield day, sorted(agrupado[day], key=lambda d: (-d.score, d.title))


def _md_escape(texto: str) -> str:
    return texto.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


def render_json(cfg: Config, result: RunResult, generated: datetime | None = None) -> str:
    generated = generated or datetime.now(timezone.utc)
    payload = {
        "generado": generated.isoformat(timespec="seconds"),
        "periodo": {"inicio": result.start.isoformat(), "fin": result.end.isoformat()},
        "terminos": [
            {"id": t.id, "label": t.label, "patterns": list(t.patterns)}
            for t in cfg.enabled_terms
        ],
        "resumen": summarize(result),
        "documentos": [
            {**d.to_dict(), "nuevo": d.uid in result.new_uids} for d in result.documents
        ],
        "errores": result.errors,
        "http": result.http_stats,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


HTML_CSS = """
:root { color-scheme: light dark; --fg:#1a1a1a; --bg:#ffffff; --muted:#5b6472;
        --line:#e3e6ea; --accent:#7b1e3a; --chip:#f3f0f4; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e9eaec; --bg:#14161a; --muted:#a2acba; --line:#2b2f36;
          --accent:#f0a6bd; --chip:#22262d; } }
body { margin:0 auto; padding:2rem 1.25rem 4rem; max-width:56rem; background:var(--bg);
       color:var(--fg); font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
h1 { font-size:1.7rem; margin:0 0 .25rem; } h2 { margin-top:2.5rem; border-bottom:1px solid var(--line);
     padding-bottom:.3rem; } h3 { margin-top:1.6rem; font-size:1.05rem; color:var(--muted); }
a { color:var(--accent); } .meta { color:var(--muted); font-size:.9rem; }
table { border-collapse:collapse; width:100%; margin:1rem 0; font-size:.95rem; }
th,td { border:1px solid var(--line); padding:.4rem .6rem; text-align:left; }
th { background:var(--chip); } td.num, th.num { text-align:right; }
ul.docs { list-style:none; padding:0; } ul.docs > li { border-left:3px solid var(--line);
    padding:.5rem .9rem; margin:.8rem 0; } ul.docs > li.nuevo { border-left-color:var(--accent); }
.chip { display:inline-block; background:var(--chip); border-radius:999px; padding:.05rem .55rem;
        font-size:.8rem; margin-right:.3rem; } blockquote { margin:.5rem 0 0; padding-left:.8rem;
        border-left:2px solid var(--line); color:var(--muted); font-size:.92rem; }
.wrap { overflow-x:auto; }
"""


def render_html(cfg: Config, result: RunResult, generated: datetime | None = None) -> str:
    generated = generated or datetime.now(timezone.utc)
    resumen = summarize(result)
    e = html.escape
    P: list[str] = []
    P.append("<!doctype html><html lang='es'><head><meta charset='utf-8'>")
    P.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    P.append(f"<title>{e(cfg['digest']['title'])} — {e(month_label(result.start))}</title>")
    P.append(f"<style>{HTML_CSS}</style></head><body>")
    P.append(f"<h1>{e(cfg['digest']['title'])} — {e(month_label(result.start))}</h1>")
    P.append(
        f"<p class='meta'>{e(_fecha_larga(result.start))} a {e(_fecha_larga(result.end))} · "
        f"generado {generated.strftime('%Y-%m-%d %H:%M UTC')}</p>"
    )
    P.append(
        "<p>"
        + " ".join(f"<span class='chip'>{e(t.label)}</span>" for t in cfg.enabled_terms)
        + "</p>"
    )
    P.append(
        f"<p>Se revisaron <strong>{resumen['revisados']}</strong> publicaciones; "
        f"<strong>{resumen['total']}</strong> mencionan los términos "
        f"({resumen['nuevos']} nuevas).</p>"
    )

    P.append("<div class='wrap'><table><tr><th>Fuente</th><th class='num'>Revisados</th>"
             "<th class='num'>Con menciones</th><th class='num'>Nuevos</th></tr>")
    for datos in resumen["por_fuente"].values():
        P.append(
            f"<tr><td>{e(datos['label'])}</td><td class='num'>{datos['revisados']}</td>"
            f"<td class='num'>{datos['hallazgos']}</td><td class='num'>{datos['nuevos']}</td></tr>"
        )
    P.append("</table></div>")

    for fuente, label in SOURCE_LABELS.items():
        docs = [d for d in result.documents if d.source == fuente]
        if not docs:
            continue
        P.append(f"<h2>{e(label)} ({len(docs)})</h2>")
        for day, del_dia in _group_by_day(docs):
            P.append(f"<h3>{e(_fecha_larga(day))}</h3><ul class='docs'>")
            for doc in del_dia:
                clase = " class='nuevo'" if doc.uid in result.new_uids else ""
                P.append(f"<li{clase}><a href='{e(doc.url)}'>{e(doc.title)}</a>")
                meta = " · ".join(e(m) for m in (doc.organism, doc.section) if m)
                if meta:
                    P.append(f"<div class='meta'>{meta}</div>")
                P.append(f"<div class='meta'>Términos: {e(_terms_line(doc))}</div>")
                if cfg["digest"].get("include_snippets", True) and doc.matches:
                    for s in doc.matches[0].snippets[:2]:
                        P.append(f"<blockquote>{e(s)}</blockquote>")
                P.append("</li>")
            P.append("</ul>")

    if not result.documents:
        P.append("<p><em>Sin menciones en el periodo.</em></p>")
    P.append("</body></html>")
    return "\n".join(P)


def write_digest(
    cfg: Config,
    result: RunResult,
    month_key: str,
    formats: list[str] | None = None,
    generated: datetime | None = None,
) -> dict[str, Path]:
    """Escribe el digest en los formatos pedidos y devuelve las rutas."""
    formats = formats or list(cfg["digest"]["formats"])
    destino = cfg.path("digests_dir")
    destino.mkdir(parents=True, exist_ok=True)
    rutas: dict[str, Path] = {}

    renderers = {
        "md": (render_markdown, ".md"),
        "json": (render_json, ".json"),
        "html": (render_html, ".html"),
    }
    for fmt in formats:
        if fmt not in renderers:
            raise ValueError(f"Formato de digest desconocido: {fmt}")
        render, ext = renderers[fmt]
        ruta = destino / f"{month_key}{ext}"
        ruta.write_text(render(cfg, result, generated), encoding="utf-8")
        rutas[fmt] = ruta

    if "md" in rutas:
        ultimo = destino / "latest.md"
        ultimo.write_text(rutas["md"].read_text(encoding="utf-8"), encoding="utf-8")
        rutas["latest"] = ultimo

    return rutas


def issue_body(markdown: str, url_hint: str | None = None) -> str:
    """Recorta el digest para que quepa en el cuerpo de un issue de GitHub."""
    cuerpo = markdown
    if len(cuerpo) > MAX_ISSUE_CHARS:
        cuerpo = cuerpo[:MAX_ISSUE_CHARS] + "\n\n_…digest truncado; ver el archivo completo._\n"
    if url_hint:
        cuerpo += f"\n\nArchivo completo: {url_hint}\n"
    return cuerpo
