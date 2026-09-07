'use strict';

/**
 * Configuración del bot. Todo sale de variables de entorno (o de Secret Manager
 * montado como variable de entorno). Nada de tokens en el código.
 */

const ZONA_HORARIA = 'America/Mexico_City';

function requerida(env, nombre) {
  const valor = (env[nombre] || '').trim();
  if (!valor) throw new Error(`Falta la variable de entorno ${nombre}`);
  return valor;
}

function entero(env, nombre, porDefecto) {
  const crudo = env[nombre];
  if (crudo === undefined || crudo === '') return porDefecto;
  const n = Number(crudo);
  if (!Number.isInteger(n)) throw new Error(`${nombre} debe ser un entero, llegó "${crudo}"`);
  return n;
}

function booleano(env, nombre, porDefecto) {
  const crudo = (env[nombre] || '').trim().toLowerCase();
  if (!crudo) return porDefecto;
  return ['1', 'true', 'si', 'sí', 'yes', 'on'].includes(crudo);
}

/**
 * WhatsApp ha usado dos formatos para México: "521" + 10 dígitos (histórico) y
 * "52" + 10 dígitos. Se normaliza al de 12 dígitos para que el doctor y las
 * etiquetas coincidan sin importar cuál mande Meta.
 */
function normalizarNumero(valor) {
  const limpio = String(valor || '').replace(/[^\d]/g, '');
  if (/^521\d{10}$/.test(limpio)) return `52${limpio.slice(3)}`;
  return limpio;
}

function soloDigitos(valor, nombre) {
  const limpio = String(valor || '').replace(/[^\d]/g, '');
  if (!/^\d{8,16}$/.test(limpio)) {
    throw new Error(`${nombre} debe ser un número en formato internacional sin "+", p. ej. 5215512345678`);
  }
  return limpio;
}

function cargarConfig(env = process.env) {
  return {
    // Meta / WhatsApp Cloud API
    token: requerida(env, 'WHATSAPP_TOKEN'),
    appSecret: requerida(env, 'WHATSAPP_APP_SECRET'),
    phoneNumberId: requerida(env, 'WHATSAPP_PHONE_NUMBER_ID'),
    verifyToken: requerida(env, 'WHATSAPP_VERIFY_TOKEN'),
    versionGraph: (env.GRAPH_API_VERSION || 'v23.0').trim(),

    // Consultorio. "doctor" tal cual se escribió (para mandarle mensajes);
    // "doctorId" normalizado (para reconocerlo cuando escribe).
    doctor: soloDigitos(requerida(env, 'DOCTOR_PHONE'), 'DOCTOR_PHONE'),
    doctorId: normalizarNumero(requerida(env, 'DOCTOR_PHONE')),
    nombreDoctor: (env.NOMBRE_DOCTOR || 'Dr. Ulises Pérez').trim(),
    direccion: (env.CLINIC_ADDRESS
      || 'Av. Río Mixcoac 25, 8.º piso, consultorio 9, Col. Crédito Constructor (entre Barranca del Muerto e Insurgentes Sur)').trim(),
    costoDomicilio: entero(env, 'PRICE_HOME', 1700),
    costoConsultorio: entero(env, 'PRICE_OFFICE', 1200),

    // Horarios (hora local de la Ciudad de México, 0-23)
    zonaHoraria: ZONA_HORARIA,
    nocheInicio: entero(env, 'NIGHT_START_HOUR', 22),
    nocheFin: entero(env, 'NIGHT_END_HOUR', 6),

    // Comportamiento
    enfriamientoMin: entero(env, 'REPLY_COOLDOWN_MINUTES', 240),
    retencionDias: entero(env, 'LOG_RETENTION_DAYS', 90),
    guardarTexto: booleano(env, 'LOG_MESSAGE_TEXT', false),
    plantillaAlerta: (env.ALERT_TEMPLATE_NAME || '').trim(),
    alertarDoctor: booleano(env, 'ALERT_DOCTOR', true),
    avisoPrivacidad: (env.PRIVACY_NOTICE_URL || '').trim(),
  };
}

module.exports = { cargarConfig, normalizarNumero, ZONA_HORARIA };
