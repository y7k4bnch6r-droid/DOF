# dofwatch — monitor mensual del DOF y la Gaceta Parlamentaria

Scraping mensual del **Diario Oficial de la Federación** y de la **Gaceta Parlamentaria
de la Cámara de Diputados** para detectar todo lo publicado sobre **personas mayores,
vejez y envejecimiento**, con **digest automático** (Markdown, JSON y HTML), correo o
webhook opcional, e issue mensual en GitHub.

- Corre solo el día 1 de cada mes (GitHub Actions) sobre el mes anterior.
- Deduplica entre corridas: cada digest marca con 🆕 lo que no se había reportado.
- Los términos son configurables; los tres solicitados vienen activos por defecto.

Ejemplo de salida: [`docs/ejemplo-digest.md`](docs/ejemplo-digest.md) (generado con los
fixtures de prueba, con datos ficticios).

---

## Cómo funciona

| Fuente | Qué se recorre | Ruta |
| --- | --- | --- |
| DOF | Todas las notas de cada día hábil (matutina, vespertina y extraordinarias) y su texto completo | Servicio JSON del DOF (`sidofqa.segob.gob.mx/dof/sidof/documentos/completo/DD-MM-AAAA` y `/notas/{codNota}`), con respaldo automático al HTML público `dof.gob.mx/index.php?year=…&month=…&day=…` |
| Gaceta Parlamentaria | La página índice de cada día y sus anexos (`-I`, `-II`, …): iniciativas, dictámenes, proposiciones, comunicaciones | `gaceta.diputados.gob.mx/Gaceta/{legislatura}/{año}/{mes}/{AAAAMMDD}.html` |

Para cada documento se normaliza el texto (minúsculas, sin acentos, espacios colapsados,
guiones invisibles eliminados) y se buscan los patrones con frontera de palabra, de modo
que *«Vejez»*, *«VEJEZ»* y *«vejez»* coinciden, pero *«vejezuela»* no. Se distingue si la
mención está en el **título** o en el **cuerpo**, se cuentan las ocurrencias y se guarda
un fragmento de contexto.

Los documentos con al menos una coincidencia se guardan en SQLite
(`data/state.sqlite3`) y de ahí sale el digest. **El texto completo no se almacena**:
sólo título, URL, metadatos, términos y fragmentos.

## Instalación

```bash
git clone https://github.com/y7k4bnch6r-droid/DOF.git
cd DOF
pip install -r requirements-dev.txt     # o requirements.txt sin las pruebas
```

Requiere Python 3.10 o superior.

## Uso

```bash
# El mes anterior completo (lo mismo que corre el cron)
python -m dofwatch.cli -v run

# Un mes específico
python -m dofwatch.cli -v run --month 2026-07

# Un rango arbitrario, sólo una fuente
python -m dofwatch.cli run --since 2026-07-01 --until 2026-07-15 --source gaceta

# Rápido: sólo títulos, sin descargar el texto completo de cada nota
python -m dofwatch.cli run --month 2026-07 --titles-only

# Ver qué encontraría, sin escribir digests ni base de datos
python -m dofwatch.cli run --month 2026-07 --dry-run

# Regenerar el digest de un mes ya procesado (sin volver a descargar)
python -m dofwatch.cli digest --month 2026-07

# Historial de corridas
python -m dofwatch.cli history

# Probar los patrones contra un texto cualquiera
python -m dofwatch.cli check-terms archivo.txt
```

Opciones útiles de `run`: `--pdf` (además extrae el texto de los PDF de la Gaceta,
requiere `pypdf` y es lento), `--no-cache`, `--no-store`, `--formats md,json`,
`--notify`, `--allow-empty`.

Si **ninguna** fuente responde, `run` termina con código 2 y **no** escribe el digest,
para no pisar uno bueno con uno vacío (y para que el job de Actions falle a la vista).
`--allow-empty` fuerza la escritura.

Salidas en `digests/`:

```
digests/2026-07.md      digest legible
digests/2026-07.json    mismos datos, estructurados
digests/2026-07.html    versión con estilo, lista para enviar por correo
digests/latest.md       copia del último digest generado
```

### Cuánto tarda

Con `full_text: true` el DOF implica ~1 petición por nota (del orden de 2 000 al mes).
Con la pausa de cortesía de 0.6 s son ~25–35 minutos por mes. Con `--titles-only`,
menos de dos minutos. La caché en disco (`.cache/`) hace que repetir un mes sea casi
instantáneo.

## Configuración

### Términos — `config/keywords.yml`

```yaml
terms:
  - id: personas_mayores
    label: "Personas mayores"
    weight: 2
    patterns:
      - "personas mayores"
      - "adulto mayor"
  - id: envejecimiento
    label: "Envejecimiento"
    patterns:
      - "envejec*"        # envejecimiento, envejecer, envejecida…
```

- Los patrones se escriben en minúsculas y sin acentos (el texto se normaliza antes).
- `*` cubre el resto de la palabra; `re:...` permite una expresión regular cruda.
- `enabled: false` deja el término definido pero apagado. El archivo trae listos —
  apagados— cinco grupos complementarios: INAPAM, geriatría/gerontología, pensión de
  bienestar, cuidados de largo plazo y edadismo. Enciéndelos cambiando `enabled` a `true`.

### General — `config/config.yml`

Ahí se ajustan las pausas y reintentos HTTP, la caché, el tamaño de los fragmentos, el
puntaje mínimo (`matching.min_score`), las fuentes activas, las legislaturas de la
Gaceta y los formatos del digest. Todo lo relevante se puede sobrescribir por CLI.

Las legislaturas están mapeadas hasta la LXVII (2027-2030); para años posteriores basta
añadir una entrada en `gaceta.legislaturas`.

## Automatización mensual

`.github/workflows/digest-mensual.yml` corre el **día 1 de cada mes a las 09:00 de la
Ciudad de México** (15:00 UTC) y, además, se puede lanzar a mano desde la pestaña
Actions indicando el mes:

1. procesa el mes anterior completo;
2. escribe `digests/AAAA-MM.{md,json,html}`;
3. hace commit del digest y de `data/state.sqlite3` (para no repetir hallazgos);
4. sube el digest como artefacto y lo publica en el resumen del job;
5. abre un **issue** con el digest, etiquetado `digest`;
6. si hay secretos SMTP configurados, lo manda por correo.

### Secretos opcionales (Settings → Secrets → Actions)

| Secreto | Para qué |
| --- | --- |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Envío por correo (puerto 465 = SSL; cualquier otro usa STARTTLS) |
| `DOFWATCH_EMAIL_TO` | Destinatarios separados por coma |
| `DOFWATCH_WEBHOOK_URL` | Webhook de Slack/Teams para el aviso corto |

Para que el correo salga hay que además poner `notify.email_enabled: true` (y/o
`notify.webhook_enabled: true`) en `config/config.yml`. Sin secretos, el digest igual
queda en el repo y en el issue.

### Correrlo fuera de GitHub

Cualquier cron sirve:

```cron
0 9 1 * *  cd /ruta/DOF && /usr/bin/python3 -m dofwatch.cli run --notify >> /var/log/dofwatch.log 2>&1
```

## Estructura

```
dofwatch/
  cli.py          comandos run / digest / history / check-terms
  config.py       carga de YAML y de términos
  http.py         sesión HTTP con reintentos, backoff, pausa y caché
  matching.py     compilación de patrones y búsqueda con contexto
  normalize.py    normalización con mapa de índices al texto original
  models.py       Document y sus metadatos
  pipeline.py     recorrido de fuentes → filtrado → almacenamiento
  store.py        SQLite (documentos y corridas)
  digest.py       render Markdown / JSON / HTML
  notify.py       correo SMTP y webhook
  sources/
    dof.py        DOF (JSON del SIDOF + respaldo HTML)
    gaceta.py     Gaceta Parlamentaria
config/           keywords.yml y config.yml
digests/          salidas mensuales
data/             state.sqlite3 (historial y deduplicación)
tests/            pruebas con fixtures locales (no tocan la red)
radar/            radar mensual de Pink Doll (herramienta aparte, ver radar/README.md)
```

## Radar Pink Doll

En `radar/` vive una herramienta aparte, sin relación con el DOF: un monitor mensual
de menciones y métricas de la novela **Pink Doll**, de Juana Inés Dehesa (web,
noticias, Reddit, YouTube y Goodreads, con deduplicación en SQLite y reporte en
`radar/reports/AAAA-MM.md`). Es un script suelto, con sus propias dependencias:

```bash
pip3 install -r radar/requirements.txt
python3 radar/monitor.py        # o: make radar
```

Los detalles están en [`radar/README.md`](radar/README.md).

## Pruebas

```bash
python -m pytest        # 89 pruebas, sin red
```

Las pruebas usan un cliente HTTP falso que sirve fixtures guardadas en
`tests/fixtures/`, así que corren sin conexión y sin golpear los sitios públicos.

## Consideraciones

- **Cortesía con los sitios**: una petición a la vez, pausa configurable entre ellas,
  reintentos con backoff exponencial y caché en disco para no volver a pedir lo mismo.
  Sube `http.delay_seconds` si vas a procesar rangos largos.
- **Las coincidencias son literales.** El monitor detecta menciones, no relevancia
  jurídica: conviene abrir el documento fuente antes de citar cualquier hallazgo.
- La Gaceta publica gran parte de su contenido en PDF. Por defecto se busca en el
  índice del día —que trae los títulos completos de iniciativas y proposiciones—; con
  `gaceta.pdf_full_text: true` (o `--pdf`) también se lee el texto de los PDF.
- El índice de la Gaceta se reporta como un documento aparte, con peso reducido, para
  no opacar los asuntos concretos.
- La estructura de ambos sitios cambia de vez en cuando. El DOF tiene respaldo
  automático JSON → HTML; si alguna ruta deja de responder, las incidencias quedan
  listadas al final del digest y en la tabla `runs` de la base de datos.
- **Los endpoints no pudieron probarse contra la red real desde el entorno donde se
  desarrolló esto** (la política de egreso bloquea `dof.gob.mx`,
  `sidofqa.segob.gob.mx` y `gaceta.diputados.gob.mx`). La primera corrida real conviene
  hacerla acotada, por ejemplo:
  `python -m dofwatch.cli -v run --since 2026-07-01 --until 2026-07-02`.
