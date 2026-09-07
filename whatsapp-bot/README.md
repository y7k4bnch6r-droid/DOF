# Bot de WhatsApp del consultorio

Respuestas automáticas para el WhatsApp del consultorio (Meta **WhatsApp Cloud API**)
corriendo como **Google Cloud Function** (HTTP, Node 20+) con **Firestore** para etiquetas,
vacaciones, idempotencia y logs.

Qué hace:

- Contesta a números nuevos con presentación, precios, dirección y pregunta
  domicilio/consultorio/indistinto; guarda la preferencia cuando el paciente contesta.
- A pacientes registrados les contesta según hora local de la CDMX (día, noche, domingo)
  y si hay vacaciones activas (con fechas y se apagan solas al terminar).
- Detecta mensajes que suenan a urgencia (caída, no respira, dolor de pecho, sangrado, etc.),
  le manda un aviso al doctor y le contesta al paciente con la instrucción de llamar al 911.
- No repite la misma respuesta automática al mismo contacto antes de 4 h (configurable).
- Verifica la firma de Meta (`X-Hub-Signature-256`), ignora eventos de estado
  (entregado/leído), no contesta dos veces el mismo mensaje aunque Meta lo reintente,
  y siempre regresa 200 para que Meta no reintente.
- Respeta la baja: si el paciente pide que no le manden mensajes automáticos, deja de contestar.
- Acusa recibo según el tipo de mensaje (nota de voz, imagen, documento) y no contesta mensajes
  con más de 23 h (Meta ya no permite texto libre fuera de la ventana de 24 h).
- El doctor administra todo desde su WhatsApp con comandos (ver abajo).

## Estructura

```
index.js          entrada HTTP (verificación, firma, despacho); crearHandler(deps) para pruebas
lib/config.js     variables de entorno → configuración (falla al arrancar si falta algo)
lib/tiempo.js     hora local CDMX con Intl, saludo, noche, fechas en español
lib/decidir.js    lógica pura: contexto → {clase, texto}; detección de urgencia y preferencia
lib/comandos.js   comandos del doctor
lib/firma.js      HMAC-SHA256 del webhook
lib/whatsapp.js   cliente de la Graph API (texto y plantillas)
lib/store.js      Firestore: contactos, config/vacacion, procesados, logs
test/             pruebas con node:test (sin red ni Firestore)
```

Firestore:

| Colección | Documento | Campos |
| --- | --- | --- |
| `contactos` | `{wa_id}` | `nombre`, `etiquetas` (`Registrado`, `Domingo-SI`), `preferencia`, `silencio`, `ultimaRespuesta {clase, en}` |
| `config` | `vacacion` | `on`, `inicio`, `fin`, `regreso` (ISO `AAAA-MM-DD`) |
| `procesados` | `{id del mensaje}` | `en`, `expiraEn` (7 días) |
| `logs` | auto | `waId`, `msgId`, `tipo`, `clase`, `enviado`, `urgente`, `alertado`, `largoTexto`, `expiraEn` |

Por defecto **no se guarda el texto** de los mensajes (datos de salud); sólo su longitud.
`LOG_MESSAGE_TEXT=true` lo activa si de verdad hace falta.

## Comandos del doctor (desde `DOCTOR_PHONE` al número del consultorio)

```
vacaciones on 2026-08-10 2026-08-17 [2026-08-18]   (también 10/08/2026)
vacaciones off
alta 5215512345678          marca como paciente registrado
baja 5215512345678
domingo 5215512345678 si|no permite mensajes en domingo
ver 5215512345678
estado
ayuda
```

## Correr local

```bash
cd whatsapp-bot
npm install
npm test
cp .env.example .env   # llena valores
set -a; source .env; set +a
npm start              # http://localhost:8080
```

Para recibir webhooks reales en local hace falta un túnel (`ngrok http 8080`) y registrar
esa URL en Meta; con `curl` puedes probar la verificación:

```bash
curl "http://localhost:8080/?hub.mode=subscribe&hub.verify_token=$WHATSAPP_VERIFY_TOKEN&hub.challenge=123"
```

## Desplegar en Google Cloud

1. Proyecto con Firestore (modo nativo) y APIs habilitadas:
   `cloudfunctions`, `cloudbuild`, `run`, `secretmanager`, `firestore`.
2. Secretos (una vez):

   ```bash
   printf '%s' "$TOKEN"      | gcloud secrets create whatsapp-token --data-file=-
   printf '%s' "$APP_SECRET" | gcloud secrets create whatsapp-app-secret --data-file=-
   printf '%s' "$VERIFY"     | gcloud secrets create whatsapp-verify-token --data-file=-
   ```

3. Despliegue (2.ª generación, región cercana):

   ```bash
   gcloud functions deploy botGeriatria \
     --gen2 --runtime=nodejs22 --region=us-central1 \
     --source=. --entry-point=botGeriatria --trigger-http --allow-unauthenticated \
     --min-instances=0 --max-instances=3 --timeout=60s --memory=256Mi \
     --set-env-vars=WHATSAPP_PHONE_NUMBER_ID=...,DOCTOR_PHONE=5215512345678,GRAPH_API_VERSION=v23.0 \
     --set-secrets=WHATSAPP_TOKEN=whatsapp-token:latest,WHATSAPP_APP_SECRET=whatsapp-app-secret:latest,WHATSAPP_VERIFY_TOKEN=whatsapp-verify-token:latest
   ```

   `--allow-unauthenticated` es necesario porque Meta llama la URL directamente; la
   autenticación real es la firma HMAC.

4. TTL en Firestore para que los logs y los ids procesados se borren solos:

   ```bash
   gcloud firestore fields ttls update expiraEn --collection-group=logs --enable-ttl
   gcloud firestore fields ttls update expiraEn --collection-group=procesados --enable-ttl
   ```

5. En Meta (App Dashboard → WhatsApp → Configuration): URL del webhook = URL de la función,
   *Verify token* = el mismo `WHATSAPP_VERIFY_TOKEN`, y suscribirse al campo `messages`.
6. Manda "ayuda" desde el teléfono del doctor al número del consultorio para comprobar.

### Cómo ve el doctor los mensajes

El bot **sólo contesta**; no reenvía cada mensaje. El doctor tiene que leer el WhatsApp del
consultorio en algún lado:

- **Coexistencia** (recomendado para un consultorio): el mismo número sigue en la app de
  WhatsApp Business del teléfono y a la vez está conectado a la Cloud API. Los mensajes
  llegan al teléfono como siempre y el bot contesta desde la nube. Se activa desde el
  App Dashboard de Meta (WhatsApp → onboarding con "usar el número de mi app").
- Si el número está **sólo** en la Cloud API, los mensajes no aparecen en ningún teléfono:
  hace falta una bandeja (un CRM o una app que lea el webhook). En ese caso el aviso de
  urgencia al `DOCTOR_PHONE` es lo único que le llega directo.

### Formato de los números mexicanos

Meta ha usado `521` + 10 dígitos y `52` + 10 dígitos para México. El bot normaliza los dos al
de 12 dígitos (`52…`) en `DOCTOR_PHONE`, en los ids de `contactos` y en los comandos, así que
da igual cuál llegue.

### Baja de mensajes automáticos

Si un paciente escribe "ya no me mande mensajes", "stop" o similar, el bot confirma una vez,
marca `silencio: true` y deja de contestarle (salvo urgencias). El doctor sigue viendo sus
mensajes. `alta <número>` lo reactiva.

### Aviso al doctor y la ventana de 24 h

Meta sólo permite texto libre a un número que escribió al negocio en las últimas 24 h.
Si el doctor no le ha escrito al número del consultorio ese día, el aviso de urgencia falla
con el código 131047. Para cubrir ese caso, crea una **plantilla** aprobada (p. ej.
`alerta_paciente`, idioma `es_MX`, cuerpo con tres variables: nombre, número, texto) y ponla
en `ALERT_TEMPLATE_NAME`; el bot la usa como respaldo.

### Versión de la Graph API

`GRAPH_API_VERSION` (por defecto `v23.0`). Cada versión vive unos dos años; revisa el
changelog de Meta y súbela cuando toque, no hay que tocar código.

## Privacidad

- Los mensajes de pacientes son datos personales sensibles (salud). Se guardan sólo metadatos,
  con borrado automático por TTL; el contenido queda únicamente en WhatsApp.
- La función se identifica siempre como asistente automático y pone la instrucción de
  emergencia (911 / urgencias) al principio de cada respuesta.
- Conviene tener el aviso de privacidad del consultorio y mencionarlo en la primera respuesta
  si así lo pide su asesor legal (`lib/decidir.js`, texto de bienvenida).
