#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar Pink Doll — monitor mensual de menciones y métricas.

Qué hace en cada corrida:
  1. Barre la web (DuckDuckGo web + noticias) con queries calificadas.
  2. Busca en Reddit (vía buscador, con site:reddit.com).
  3. Busca videos en YouTube (vía yt-dlp, si está instalado) y suma vistas.
  4. Lee métricas de Goodreads (número de calificaciones y promedio).
  5. Deduplica contra la base local (SQLite): solo lo NUEVO aparece en el reporte.
  6. Escribe reports/AAAA-MM.md con novedades + deltas vs. la corrida anterior.

Uso:
  python3 monitor.py                 # corrida normal
  python3 monitor.py --limit 10      # menos resultados por query (más rápido)
  python3 monitor.py --no-notify     # sin notificación de macOS

Dependencias:  pip3 install requests ddgs        (yt-dlp es opcional)
"""

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import requests

try:
    from ddgs import DDGS
except ImportError:  # nombre viejo del paquete
    from duckduckgo_search import DDGS

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "state.db"
REPORTS = BASE / "reports"

# ---------------------------------------------------------------- CONFIG ---
CONFIG = {
    # Queries para búsqueda web general (calificadas para evitar ruido:
    # "pink doll" a secas trae Barbie, muñecas y una streamer llamada Pinkydoll)
    "web_queries": [
        '"Pink Doll" Dehesa',
        '"Pink Doll" novela Juana Inés Dehesa',
        '"Rebel Doll" Dehesa',
        '"Juana Inés Dehesa" entrevista',
        '"Pink Doll" Dehesa site:tiktok.com',
        '"Pink Doll" Dehesa site:instagram.com',
        '"Pink Doll" Dehesa site:wattpad.com',
        '"Pink Doll" Dehesa site:mercadolibre.com.mx',
        '"Pink Doll" Dehesa site:facebook.com',
    ],
    # Queries para la vertical de noticias
    "news_queries": [
        '"Juana Inés Dehesa"',
        '"Pink Doll" novela',
    ],
    # Queries para Reddit
    "reddit_queries": [
        '"pink doll" dehesa',
        '"juana ines dehesa"',
    ],
    # Queries para YouTube (requiere yt-dlp)
    "youtube_queries": [
        'Pink Doll Juana Inés Dehesa',
        'Juana Inés Dehesa entrevista',
    ],
    # Ediciones de Goodreads a monitorear (hay dos fichas del mismo libro)
    "goodreads_urls": [
        "https://www.goodreads.com/book/show/12017792-pink-doll",
        "https://www.goodreads.com/book/show/22106683-pink-doll",
        "https://www.goodreads.com/book/show/16268874",  # Rebel Doll
    ],
    # Un resultado se descarta si trae un término de ruido y NO menciona "dehesa"
    "noise_terms": [
        "pinkydoll", "npc stream", "barbie", "lol surprise", "monster high",
        "bratz", "aliexpress", "shein", "juguete", "muñeca de", "blackpink",
        "tube top", "backpack", "ever after high", "punk rave", "blind box",
        "maymei", "sor juana", "de la cruz",
    ],
    # Anclas de relevancia: al menos una debe aparecer en título+snippet+url
    "anchor_terms": ["dehesa", "novela", "libro", "book", "juana"],
}
PAUSA_ENTRE_QUERIES = 2.0  # segundos, para no encabronar a los servidores


# ---------------------------------------------------------------- utilería ---
def canon_url(url: str) -> str:
    """Normaliza URLs para deduplicar (quita utm_*, fragmentos, slash final)."""
    try:
        p = urlsplit(url.strip())
        q = [(k, v) for k, v in parse_qsl(p.query)
             if not k.lower().startswith(("utm_", "fbclid", "gclid", "igsh"))]
        path = p.path.rstrip("/") or "/"
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), path,
                           urlencode(q), ""))
    except Exception:
        return url.strip()


def es_relevante(texto: str) -> bool:
    t = texto.lower()
    patron = r"\b(" + "|".join(CONFIG["anchor_terms"]) + r")\b"
    if not re.search(patron, t):
        return False
    if "dehesa" not in t and any(n in t for n in CONFIG["noise_terms"]):
        return False
    return True


def db_connect():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS mentions(
        url TEXT PRIMARY KEY, source TEXT, title TEXT, snippet TEXT,
        query TEXT, first_seen TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS metrics(
        run TEXT, key TEXT, value REAL, PRIMARY KEY(run, key))""")
    con.execute("""CREATE TABLE IF NOT EXISTS runs(
        run TEXT PRIMARY KEY, started TEXT, new_mentions INTEGER)""")
    return con


# ------------------------------------------------------------- colectores ---
def collect_web(limit):
    hallazgos = []
    for tipo, queries in (("web", CONFIG["web_queries"]),
                          ("noticias", CONFIG["news_queries"])):
        for q in queries:
            try:
                with DDGS() as d:
                    fn = d.text if tipo == "web" else d.news
                    res = fn(q, region="mx-es", safesearch="off",
                             max_results=limit) or []
            except Exception as e:
                if "no results" not in str(e).lower():
                    print(f"  [!] DDG falló con '{q}': {e}", file=sys.stderr)
                res = []
            for it in res:
                url = it.get("href") or it.get("url") or ""
                title = it.get("title") or ""
                body = it.get("body") or ""
                if url and es_relevante(f"{title} {body} {url}"):
                    hallazgos.append(dict(source=tipo, title=title.strip(),
                                          url=url, snippet=body.strip()[:280],
                                          query=q))
            time.sleep(PAUSA_ENTRE_QUERIES)
    return hallazgos


def collect_reddit(limit):
    """Reddit ya bloquea su endpoint JSON público a scripts (pide OAuth),
    así que entramos por la puerta de al lado: buscador con site:reddit.com."""
    hallazgos = []
    for q in CONFIG["reddit_queries"]:
        try:
            with DDGS() as d:
                res = d.text(f"{q} site:reddit.com", region="mx-es",
                             safesearch="off", max_results=limit) or []
        except Exception as e:
            if "no results" not in str(e).lower():
                print(f"  [!] Reddit/DDG falló con '{q}': {e}",
                      file=sys.stderr)
            res = []
        for it in res:
            url = it.get("href") or it.get("url") or ""
            title = it.get("title") or ""
            body = it.get("body") or ""
            if url and es_relevante(f"{title} {body} {url}"):
                hallazgos.append(dict(source="reddit", title=title.strip(),
                                      url=url, snippet=body.strip()[:280],
                                      query=q))
        time.sleep(PAUSA_ENTRE_QUERIES)
    return hallazgos


def collect_youtube(limit):
    if not shutil.which("yt-dlp"):
        print("  [i] yt-dlp no instalado; me salto YouTube "
              "(pip3 install yt-dlp para activarlo)", file=sys.stderr)
        return [], None
    hallazgos, vistas = [], 0
    for q in CONFIG["youtube_queries"]:
        try:
            out = subprocess.run(
                ["yt-dlp", f"ytsearch{limit}:{q}", "--skip-download",
                 "--dump-json", "--no-warnings", "--ignore-errors"],
                capture_output=True, text=True, timeout=420)
            entries = [json.loads(ln) for ln in out.stdout.splitlines()
                       if ln.strip().startswith("{")]
        except Exception as e:
            print(f"  [!] yt-dlp falló con '{q}': {e}", file=sys.stderr)
            entries = []
        for e in entries:
            if not e:
                continue
            vid = e.get("id", "")
            url = e.get("url") or f"https://www.youtube.com/watch?v={vid}"
            title = e.get("title") or ""
            canal = e.get("channel") or e.get("uploader") or ""
            if not es_relevante(f"{title} {canal}"):
                continue
            vc = e.get("view_count") or 0
            vistas += int(vc)
            hallazgos.append(dict(source="youtube", title=title.strip(),
                                  url=url,
                                  snippet=f"{canal} · {vc:,} vistas", query=q))
    return hallazgos, float(vistas)


def collect_goodreads():
    """Regresa {clave_métrica: valor} raspando el JSON-LD de cada ficha."""
    met = {}
    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")
    for url in CONFIG["goodreads_urls"]:
        gid = re.search(r"/show/(\d+)", url)
        gid = gid.group(1) if gid else url[-8:]
        try:
            html = requests.get(url, headers={"User-Agent": ua},
                                timeout=25).text
            rc = re.search(r'"ratingCount"\s*:\s*(\d+)', html)
            rv = re.search(r'"ratingValue"\s*:\s*([\d.]+)', html)
            rw = re.search(r'"reviewCount"\s*:\s*(\d+)', html)
            if rc:
                met[f"gr_{gid}_ratings"] = float(rc.group(1))
            if rv:
                met[f"gr_{gid}_promedio"] = float(rv.group(1))
            if rw:
                met[f"gr_{gid}_reviews"] = float(rw.group(1))
        except Exception as e:
            print(f"  [!] Goodreads falló con {url}: {e}", file=sys.stderr)
        time.sleep(1.5)
    return met


# ----------------------------------------------------------------- reporte ---
def delta_str(actual, previo):
    if previo is None:
        return "(primera medición)"
    d = actual - previo
    signo = "+" if d > 0 else ""
    return f"({signo}{d:g} vs. mes anterior)" if d else "(sin cambio)"


def escribir_reporte(con, run_id, nuevos, metricas, prev_metricas):
    REPORTS.mkdir(exist_ok=True)
    ruta = REPORTS / f"{run_id}.md"
    total = con.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]

    lineas = [
        f"# Radar Pink Doll — {run_id}",
        f"_Corrida: {datetime.now():%Y-%m-%d %H:%M}_",
        "",
        "## Resumen",
        f"- Menciones nuevas este mes: **{len(nuevos)}**",
        f"- Menciones acumuladas en la base: **{total}**",
        "",
        "## Métricas",
    ]
    if metricas:
        for k in sorted(metricas):
            lineas.append(f"- `{k}`: **{metricas[k]:g}** "
                          f"{delta_str(metricas[k], prev_metricas.get(k))}")
    else:
        lineas.append("- (sin métricas esta corrida)")

    lineas += ["", "## Menciones nuevas"]
    if nuevos:
        por_fuente = {}
        for n in nuevos:
            por_fuente.setdefault(n["source"], []).append(n)
        for fuente in sorted(por_fuente):
            lineas.append(f"\n### {fuente} ({len(por_fuente[fuente])})")
            for n in por_fuente[fuente]:
                snip = n["snippet"].replace("\n", " ")
                lineas.append(f"- [{n['title'] or n['url']}]({n['url']})  \n"
                              f"  {snip}")
    else:
        lineas.append("- Nada nuevo bajo el sol (o bajo el radar).")

    lineas += [
        "",
        "## Chequeo manual sugerido (jardines amurallados)",
        "- TikTok: https://www.tiktok.com/search?q=pink%20doll%20dehesa",
        "- Instagram: https://www.instagram.com/explore/search/keyword/?q=pink%20doll%20dehesa",
        "- X/Twitter: https://x.com/search?q=%22pink%20doll%22%20dehesa&f=live",
        "- Threads: https://www.threads.net/search?q=pink+doll+dehesa",
        "",
    ]
    ruta.write_text("\n".join(lineas), encoding="utf-8")
    return ruta


def notificar(msg):
    if sys.platform == "darwin":
        try:
            subprocess.run(["osascript", "-e",
                            f'display notification "{msg}" '
                            f'with title "Radar Pink Doll"'],
                           timeout=10)
        except Exception:
            pass


# -------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser(description="Radar mensual de Pink Doll")
    ap.add_argument("--limit", type=int, default=15,
                    help="resultados máximos por query (default 15)")
    ap.add_argument("--no-notify", action="store_true",
                    help="no mandar notificación de macOS")
    args = ap.parse_args()

    run_id = f"{date.today():%Y-%m}"
    con = db_connect()
    print(f"[*] Radar Pink Doll — corrida {run_id}")

    hallazgos = []
    print("[*] Barrido web y noticias…")
    hallazgos += collect_web(args.limit)
    print("[*] Reddit…")
    hallazgos += collect_reddit(args.limit)
    print("[*] YouTube…")
    yt, vistas = collect_youtube(args.limit)
    hallazgos += yt

    metricas = {}
    if vistas is not None:
        metricas["youtube_vistas_rastreadas"] = vistas
    print("[*] Goodreads…")
    metricas.update(collect_goodreads())

    # Deduplicar e insertar lo nuevo
    nuevos, vistos = [], set()
    for h in hallazgos:
        cu = canon_url(h["url"])
        if cu in vistos:
            continue
        vistos.add(cu)
        cur = con.execute(
            "INSERT OR IGNORE INTO mentions(url, source, title, snippet, "
            "query, first_seen) VALUES(?,?,?,?,?,?)",
            (cu, h["source"], h["title"], h["snippet"], h["query"],
             datetime.now().isoformat(timespec="seconds")))
        if cur.rowcount:
            nuevos.append(h)
    metricas["menciones_totales"] = float(
        con.execute("SELECT COUNT(*) FROM mentions").fetchone()[0])

    # Métricas de la corrida anterior (para deltas)
    prev = con.execute(
        "SELECT run FROM runs WHERE run != ? ORDER BY run DESC LIMIT 1",
        (run_id,)).fetchone()
    prev_metricas = {}
    if prev:
        prev_metricas = dict(con.execute(
            "SELECT key, value FROM metrics WHERE run = ?", (prev[0],)))

    # Guardar corrida y métricas
    con.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?)",
                (run_id, datetime.now().isoformat(timespec="seconds"),
                 len(nuevos)))
    for k, v in metricas.items():
        con.execute("INSERT OR REPLACE INTO metrics VALUES(?,?,?)",
                    (run_id, k, v))
    con.commit()

    ruta = escribir_reporte(con, run_id, nuevos, metricas, prev_metricas)
    con.close()
    print(f"[✓] {len(nuevos)} menciones nuevas. Reporte: {ruta}")
    if not args.no_notify:
        notificar(f"{len(nuevos)} menciones nuevas de Pink Doll este mes")


if __name__ == "__main__":
    main()
