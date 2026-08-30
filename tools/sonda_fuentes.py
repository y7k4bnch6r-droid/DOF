#!/usr/bin/env python3
"""Sonda las fuentes reales y describe su estructura.

Se corre desde una máquina con salida a internet (por ejemplo el workflow
"Diagnóstico de fuentes"). Sirve para saber qué ruta se rompió y cómo está
marcado el HTML cuando el DOF o la Gaceta cambian de formato.

    python tools/sonda_fuentes.py --fecha 2026-08-28
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date

import requests
from bs4 import BeautifulSoup

MESES = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
         7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}

UA = {"User-Agent": "dofwatch-sonda/1.0 (+https://github.com/y7k4bnch6r-droid/DOF)"}


def titulo(texto: str) -> None:
    print(f"\n{'=' * 78}\n== {texto}\n{'=' * 78}")


def traer(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=UA, timeout=40)
    except requests.RequestException as exc:
        print(f"  ERROR {url}\n    {type(exc).__name__}: {exc}")
        return None
    print(f"  {r.status_code} {len(r.content)}B {r.headers.get('content-type')} <- {r.url}")
    return r


def sopa(r: requests.Response) -> BeautifulSoup:
    # El DOF sirve utf-8; la Gaceta, iso-8859-1 declarado sólo en el <meta>.
    try:
        html = r.content.decode("utf-8")
    except UnicodeDecodeError:
        html = r.content.decode("cp1252", errors="replace")
    return BeautifulSoup(html, "lxml")


def rodaja(html: str, patron: str, antes: int = 500, despues: int = 900) -> None:
    m = re.search(patron, html)
    if not m:
        print(f"    (no se encontró /{patron}/)")
        return
    ini = max(0, m.start() - antes)
    print("    " + html[ini : m.end() + despues].replace("\n", "\n    ")[:2200])


def sondear_dof(dia: date, detalle: bool = True) -> None:
    titulo(f"DOF — índice del {dia}")
    url = f"https://dof.gob.mx/index.php?year={dia.year}&month={dia.month:02d}&day={dia.day:02d}"
    r = traer(url)
    if not r or r.status_code != 200:
        return
    html = r.text
    s = sopa(r)

    enlaces = s.select('a[href*="nota_detalle.php"]')
    print(f"  enlaces a nota_detalle: {len(enlaces)}")
    for a in enlaces[:8]:
        print(f"    - {a.get('href')}  ::  {' '.join(a.get_text(' ').split())[:110]}")

    print("  ids/clases de contenedores:")
    ids = [t.get("id") for t in s.find_all(attrs={"id": True})][:25]
    clases = sorted({c for t in s.find_all(attrs={"class": True}) for c in t.get("class")})[:30]
    print(f"    ids: {ids}")
    print(f"    clases: {clases}")

    variantes = sorted({a["href"] for a in s.select('a[href*="index.php"]')})[:12]
    print(f"  variantes de index.php enlazadas: {variantes}")

    if not detalle:
        return

    print("  marcado alrededor del primer enlace:")
    rodaja(html, r'nota_detalle\.php')

    if enlaces:
        href = enlaces[0]["href"]
        detalle = href if href.startswith("http") else f"https://dof.gob.mx/{href.lstrip('/')}"
        titulo("DOF — una nota completa")
        rn = traer(detalle)
        if rn and rn.status_code == 200:
            sn = sopa(rn)
            for sel in ("#DivDetalleNota", "#DetalleNota", ".Titulo", "#contenido"):
                print(f"    {sel}: {'sí' if sn.select_one(sel) else 'no'}")
            ids = [t.get("id") for t in sn.find_all(attrs={"id": True})][:25]
            print(f"    ids: {ids}")
            texto = " ".join(sn.get_text(" ").split())
            print(f"    texto ({len(texto)} car.): {texto[:400]}")


def sondear_gaceta(dia: date, legislatura: int) -> None:
    titulo(f"Gaceta — {dia} (legislatura {legislatura})")
    url = (f"https://gaceta.diputados.gob.mx/Gaceta/{legislatura}/{dia.year}/"
           f"{MESES[dia.month]}/{dia:%Y%m%d}.html")
    r = traer(url)
    if not r or r.status_code != 200:
        return
    s = sopa(r)
    html = r.text

    print(f"  title: {s.title.get_text(' ').strip() if s.title else '(sin title)'}")
    secciones = s.select("a.Seccion")
    items = s.select("a.Indice")
    print(f"  a.Seccion: {len(secciones)} -> {[x.get_text(' ').strip() for x in secciones][:12]}")
    print(f"  a.Indice: {len(items)}")
    for a in items[:5]:
        print(f"    - {a.get('href')} :: {' '.join(a.get_text(' ').split())[:130]}")

    anexos = s.select('#Anexos a[href]')
    print(f"  anexos: {[(a.get('href'), a.get_text(' ').strip()) for a in anexos]}")

    print("  contenedores:")
    ids = [t.get("id") for t in s.find_all(attrs={"id": True})][:30]
    clases = sorted({c for t in s.find_all(attrs={"class": True}) for c in t.get("class")})[:30]
    print(f"    ids: {ids}")
    print(f"    clases: {clases}")

    print("  marcado del cuerpo del primer asunto:")
    destino = items[0].get("href", "").lstrip("#") if items else "Iniciativa1"
    rodaja(html, rf'(name|id)="{re.escape(destino)}"')


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fecha", default="2026-08-28",
                   help="día hábil a sondear; admite varios separados por coma")
    p.add_argument("--legislatura", type=int, default=66)
    args = p.parse_args()

    dias = [date.fromisoformat(f.strip()) for f in args.fecha.split(",") if f.strip()]
    for i, dia in enumerate(dias):
        sondear_dof(dia, detalle=(i == 0))
    sondear_gaceta(dias[0], args.legislatura)
    return 0


if __name__ == "__main__":
    sys.exit(main())
