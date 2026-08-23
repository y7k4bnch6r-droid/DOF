# Radar Pink Doll

Monitor mensual de menciones y métricas de la novela **Pink Doll** (y *Rebel Doll*),
de Juana Inés Dehesa. Vive aparte de `dofwatch`: es un script suelto, pensado para
correrse a mano o desde un cron en la máquina de uno.

## Qué hace en cada corrida

1. Barre la web y la vertical de noticias (DuckDuckGo) con queries calificadas.
2. Busca en Reddit (por buscador, con `site:reddit.com`: el endpoint JSON de Reddit
   ya pide OAuth).
3. Busca videos en YouTube con `yt-dlp` —si está instalado— y suma sus vistas.
4. Lee de Goodreads el número de calificaciones, el promedio y las reseñas.
5. Deduplica contra `state.db` (SQLite): al reporte sólo llega lo **nuevo**.
6. Escribe `reports/AAAA-MM.md` con las novedades y los deltas contra la corrida
   anterior.

Las queries van calificadas a propósito («Pink Doll» a secas trae Barbie, muñecas de
AliExpress y una streamer llamada Pinkydoll), y además cada resultado pasa por un
filtro de ruido: necesita al menos un ancla (`dehesa`, `novela`, `libro`, `book`,
`juana`) y se descarta si trae términos de ruido sin mencionar «dehesa».

## Instalación

```bash
pip3 install -r radar/requirements.txt
pip3 install yt-dlp          # opcional, para la parte de YouTube
```

## Uso

```bash
python3 radar/monitor.py                # corrida normal
python3 radar/monitor.py --limit 10     # menos resultados por query (más rápido)
python3 radar/monitor.py --no-notify    # sin notificación de macOS
```

Desde la raíz del repo también sirve `make radar` (o `make radar-rapido`).

Mensual, con cron:

```cron
0 9 1 * *  cd /ruta/DOF && /usr/bin/python3 radar/monitor.py >> /var/log/radar.log 2>&1
```

## Archivos

```
radar/monitor.py        el script completo (configuración incluida, arriba del todo)
radar/state.db          SQLite con menciones, métricas y corridas (no se versiona)
radar/reports/AAAA-MM.md   reporte mensual
```

La configuración —queries, fichas de Goodreads, términos de ruido y anclas— está en el
diccionario `CONFIG`, al principio de `monitor.py`.

## Consideraciones

- Hay una pausa de 2 s entre queries y de 1.5 s entre fichas de Goodreads, para no
  golpear a los servidores. Súbelas si vas a correrlo seguido.
- TikTok, Instagram, X y Threads no se pueden barrer sin API; el reporte cierra con
  las ligas de búsqueda para revisarlos a mano.
- Todos los colectores fallan en silencio (avisan por `stderr` y siguen): si una
  fuente se cae, el reporte igual se escribe con lo demás.
- **Ninguna fuente pudo probarse contra la red real desde el entorno donde se agregó
  esto** (la política de egreso bloquea buscadores y Goodreads). El script corre de
  principio a fin y escribe el reporte, pero la primera corrida de verdad conviene
  hacerla con `--limit 3` para ver que las queries traen lo esperado.
