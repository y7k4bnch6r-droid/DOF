'use strict';

/**
 * Bot de WhatsApp del consultorio (Google Cloud Functions, HTTP).
 *
 *   GET  → verificación del webhook de Meta
 *   POST → eventos de la WhatsApp Cloud API (firmados con X-Hub-Signature-256)
 *
 * El handler real se arma con crearHandler(deps) para poder probarlo sin
 * Firestore ni Meta. exports.botGeriatria es el que se despliega.
 */

const { cargarConfig, normalizarNumero } = require('./lib/config');
const { verificarFirma } = require('./lib/firma');
const { ahoraEn } = require('./lib/tiempo');
const { decidir, detectarUrgencia } = require('./lib/decidir');
const comandos = require('./lib/comandos');
const { CODIGO_FUERA_DE_VENTANA } = require('./lib/whatsapp');

const WA_ID = /^\d{8,16}$/;
const TIPOS_IGNORADOS = new Set(['reaction', 'system', 'unsupported', 'unknown']);
const DIAS_RETENCION_PROCESADOS = 7;
// Meta sólo acepta texto libre dentro de las 24 h siguientes al mensaje del paciente.
const EDAD_MAXIMA_MS = 23 * 60 * 60 * 1000;

function registrar(severity, message, extra = {}) {
  // Cloud Logging entiende JSON con "severity" en stdout/stderr.
  const linea = JSON.stringify({ severity, message, ...extra });
  if (severity === 'ERROR' || severity === 'WARNING') console.error(linea);
  else console.log(linea);
}

/** Saca el texto legible de cualquier tipo de mensaje; "" si no hay. */
function extraerTexto(msg) {
  switch (msg.type) {
    case 'text':
      return (msg.text && msg.text.body) || '';
    case 'interactive': {
      const i = msg.interactive || {};
      return (i.button_reply && i.button_reply.title) || (i.list_reply && i.list_reply.title) || '';
    }
    case 'button':
      return (msg.button && msg.button.text) || '';
    default:
      return (msg[msg.type] && msg[msg.type].caption) || '';
  }
}

function fechaMas(dias, desde) {
  return new Date(desde.getTime() + dias * 24 * 60 * 60 * 1000);
}

function crearHandler({ config, store, whatsapp, reloj = () => new Date() }) {
  const enfriamientoMs = config.enfriamientoMin * 60 * 1000;

  async function avisarDoctor(waId, nombre, texto) {
    if (!config.alertarDoctor || !config.doctor) return false;
    const resumen = texto.length > 300 ? `${texto.slice(0, 300)}…` : texto;
    const aviso = `⚠️ Mensaje posiblemente urgente de ${nombre || 'paciente'} (${waId}):\n"${resumen}"`;
    try {
      await whatsapp.enviarTexto(config.doctor, aviso);
      return true;
    } catch (err) {
      if (err.codigoMeta === CODIGO_FUERA_DE_VENTANA && config.plantillaAlerta) {
        try {
          await whatsapp.enviarPlantilla(config.doctor, config.plantillaAlerta, [nombre || 'paciente', waId, resumen]);
          return true;
        } catch (err2) {
          registrar('ERROR', 'No se pudo avisar al doctor con plantilla', { error: err2.message, waId });
          return false;
        }
      }
      registrar('ERROR', 'No se pudo avisar al doctor', { error: err.message, waId });
      return false;
    }
  }

  async function atenderDoctor(msg, texto) {
    const comando = comandos.interpretar(texto);
    const respuesta = comando
      ? await comandos.ejecutar(comando, store)
      : `No entendí ese comando.\n\n${comandos.AYUDA}`;
    await whatsapp.enviarTexto(msg.from, respuesta);
    registrar('INFO', 'Comando del doctor', { comando: comando ? comando.accion : 'desconocido', msgId: msg.id });
  }

  async function atenderPaciente(msg, waId, texto, nombre) {
    const ahora = ahoraEn(config.zonaHoraria, reloj());
    const [contacto, vacacion] = await Promise.all([store.leerContacto(waId), store.leerVacacion()]);

    const urgente = detectarUrgencia(texto);
    const alertado = urgente ? await avisarDoctor(waId, nombre || (contacto && contacto.nombre), texto) : false;

    const decision = decidir({ texto, tipo: msg.type, ahora, contacto, vacacion, config, urgente, alertado });

    // Enfriamiento: no repetir la misma respuesta automática cada vez que el
    // paciente escribe (excepto urgencias y la confirmación de preferencia).
    const ultima = contacto && contacto.ultimaRespuesta;
    const repetida = ultima && ultima.clase === decision.clase
      && ultima.en && (ahora.instante.getTime() - new Date(ultima.en).getTime()) < enfriamientoMs;
    const siempre = decision.clase === 'urgente' || decision.clase === 'preferencia' || decision.clase === 'baja';
    // Si el paciente pidió baja, sólo se le contesta en urgencias.
    const silenciado = Boolean(contacto && contacto.silencio) && decision.clase !== 'urgente';
    // Mensaje viejo (Meta lo reintentó horas después): ya no se puede contestar con texto libre.
    const edadMs = msg.timestamp ? ahora.instante.getTime() - Number(msg.timestamp) * 1000 : 0;
    const viejo = Number.isFinite(edadMs) && edadMs > EDAD_MAXIMA_MS;
    const enviar = !silenciado && !viejo && (!repetida || siempre);
    if (viejo) registrar('WARNING', 'Mensaje con más de 23 h; no se contesta', { msgId: msg.id, edadHoras: Math.round(edadMs / 3600000) });

    let enviado = false;
    if (enviar) {
      try {
        // Se contesta al wa_id exacto que mandó Meta; waId (normalizado) es sólo la llave en Firestore.
        await whatsapp.enviarTexto(msg.from, decision.texto);
        enviado = true;
      } catch (err) {
        registrar('ERROR', 'No se pudo enviar la respuesta', { error: err.message, waId, clase: decision.clase });
      }
    }

    const cambios = {};
    if (nombre && nombre !== (contacto && contacto.nombre)) cambios.nombre = nombre;
    if (decision.preferencia) cambios.preferencia = decision.preferencia;
    if (decision.silencio) cambios.silencio = true;
    if (enviado) cambios.ultimaRespuesta = { clase: decision.clase, en: ahora.instante.toISOString() };
    if (!contacto) cambios.etiquetas = [];
    if (Object.keys(cambios).length) await store.guardarContacto(waId, cambios);

    await store.registrarLog({
      waId,
      msgId: msg.id,
      tipo: msg.type,
      clase: decision.clase,
      enviado,
      urgente,
      alertado,
      ...(config.guardarTexto ? { texto } : { largoTexto: texto.length }),
      expiraEn: fechaMas(config.retencionDias, ahora.instante),
    });
  }

  async function procesarMensaje(valor, msg) {
    const waId = msg && normalizarNumero(msg.from);
    if (!msg || typeof msg.id !== 'string' || !WA_ID.test(waId)) {
      registrar('WARNING', 'Mensaje sin id o remitente válido', { msg });
      return;
    }
    if (TIPOS_IGNORADOS.has(msg.type)) return;

    const nuevo = await store.marcarProcesado(msg.id, fechaMas(DIAS_RETENCION_PROCESADOS, reloj()));
    if (!nuevo) {
      registrar('INFO', 'Mensaje repetido, se ignora', { msgId: msg.id });
      return;
    }

    const texto = extraerTexto(msg);
    const contactoMeta = (valor.contacts || []).find((c) => c && c.wa_id === msg.from);
    const nombre = contactoMeta && contactoMeta.profile && contactoMeta.profile.name;

    if (waId === config.doctorId) return atenderDoctor(msg, texto);
    return atenderPaciente(msg, waId, texto, nombre);
  }

  /** Estados de entrega de lo que mandó el bot: sólo interesan los fallidos. */
  function revisarEstados(valor) {
    for (const estado of valor.statuses || []) {
      if (estado && estado.status === 'failed') {
        registrar('WARNING', 'Meta no pudo entregar un mensaje', {
          msgId: estado.id,
          para: estado.recipient_id,
          errores: (estado.errors || []).map((e) => ({ code: e.code, title: e.title })),
        });
      }
    }
  }

  return async function handler(req, res) {
    if (req.method === 'GET') {
      const q = req.query || {};
      if (q['hub.mode'] === 'subscribe' && q['hub.verify_token'] === config.verifyToken && q['hub.challenge']) {
        return res.status(200).type('text/plain').send(String(q['hub.challenge']));
      }
      return res.sendStatus(403);
    }
    if (req.method !== 'POST') return res.sendStatus(405);

    if (!req.rawBody) {
      registrar('ERROR', 'req.rawBody no disponible; no se puede verificar la firma');
      return res.sendStatus(500);
    }
    if (!verificarFirma(req.rawBody, req.get('x-hub-signature-256'), config.appSecret)) {
      registrar('WARNING', 'Firma inválida', { ip: req.ip });
      return res.sendStatus(401);
    }

    const body = req.body || {};
    if (body.object !== 'whatsapp_business_account') return res.sendStatus(404);

    // Se procesan todos los mensajes del payload (puede traer varios) y se
    // responde 200 aunque algo falle: si Meta no recibe 200, reintenta y el
    // paciente recibiría la misma respuesta dos veces.
    for (const entry of body.entry || []) {
      for (const cambio of entry.changes || []) {
        if (cambio.field !== 'messages') continue;
        const valor = cambio.value || {};
        revisarEstados(valor);
        for (const msg of valor.messages || []) {
          try {
            await procesarMensaje(valor, msg);
          } catch (err) {
            registrar('ERROR', 'Error procesando mensaje', { error: err.message, stack: err.stack, msgId: msg && msg.id });
          }
        }
      }
    }
    return res.sendStatus(200);
  };
}

let handlerProduccion = null;

function armarProduccion() {
  const { Firestore, FieldValue } = require('@google-cloud/firestore');
  const { crearStore } = require('./lib/store');
  const { crearCliente } = require('./lib/whatsapp');
  const config = cargarConfig();
  const store = crearStore(new Firestore(), { FieldValue });
  const whatsapp = crearCliente(config);
  return crearHandler({ config, store, whatsapp });
}

exports.botGeriatria = (req, res) => {
  if (!handlerProduccion) handlerProduccion = armarProduccion();
  return handlerProduccion(req, res);
};
exports.crearHandler = crearHandler;
exports.extraerTexto = extraerTexto;
