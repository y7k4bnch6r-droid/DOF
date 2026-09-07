'use strict';

/**
 * Lógica pura: dado el contexto (texto, hora local, etiquetas del contacto,
 * vacaciones, configuración) decide qué contestar. No toca red ni base de
 * datos, por eso se puede probar sin Firestore ni Meta.
 */

const { saludo, esNoche, fechaLarga } = require('./tiempo');

const ETIQUETA_REGISTRADO = 'Registrado';
const ETIQUETA_DOMINGO = 'Domingo-SI';

function normalizar(texto) {
  return String(texto || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

// Palabras que, viniendo de una persona mayor o de su familia, ameritan
// avisarle al doctor de inmediato. Se aceptan falsos positivos: lo peor que
// pasa es una alerta de más.
const PATRONES_URGENCIA = [
  /\burgente\b/, /\burgencia\b/, /\bemergencia\b/, /\b911\b/,
  /\bno respira\b/, /\bno responde\b/, /\bno reacciona\b/, /\binconsciente\b/,
  /\bdesmay/, /\bconvulsion/, /\bse (me )?ahoga\b/, /\basfixi/,
  /\bdolor (en el|de) pecho\b/, /\binfarto\b/, /\bderrame\b/, /\bembolia\b/,
  /\bse (me )?cayo\b/, /\bcaida\b/, /\bfractura\b/,
  /\bsangra/, /\bsangrado\b/, /\bvomit\w* sangre\b/,
  /\bno puede hablar\b/, /\bno puede caminar\b/, /\bno despierta\b/,
];

function detectarUrgencia(texto) {
  const t = normalizar(texto);
  if (!t) return false;
  return PATRONES_URGENCIA.some((re) => re.test(t));
}

// "ya no me mande mensajes", "baja", "stop": el paciente no quiere respuestas automáticas.
function detectarBaja(texto) {
  const t = normalizar(texto);
  if (!t) return false;
  return /^(stop|baja|alto|cancelar)$/.test(t)
    || /\b(no|ya no|dejen? de|deje de|dejar de) (me )?(mand|envi|escrib)\w* (mas )?mensajes?\b/.test(t)
    || /\bno (quiero|deseo) (recibir |mas )?mensajes\b/.test(t);
}

const ACUSE = {
  audio: 'Recibí su nota de voz.',
  image: 'Recibí su imagen.',
  video: 'Recibí su video.',
  document: 'Recibí su documento.',
  sticker: 'Recibí su mensaje.',
  location: 'Recibí su ubicación.',
  contacts: 'Recibí el contacto.',
};

function acuse(tipo) {
  return ACUSE[tipo] || 'Su mensaje fue recibido.';
}

function detectarPreferencia(texto) {
  const t = normalizar(texto);
  if (!t) return null;
  if (/\b(domicilio|casa|hogar)\b/.test(t)) return 'domicilio';
  if (/\b(consultorio|oficina)\b/.test(t)) return 'consultorio';
  if (/\b(indistinto|indistinta|cualquiera|da igual|me da lo mismo)\b/.test(t)) return 'indistinto';
  return null;
}

const COMO_PREFERENCIA = {
  domicilio: 'a domicilio',
  consultorio: 'en consultorio',
  indistinto: 'en domicilio o consultorio, indistinto',
};

function pesos(cantidad) {
  return `$${Number(cantidad).toLocaleString('es-MX')}`;
}

function vacacionActiva(vacacion, fechaISO) {
  if (!vacacion || !vacacion.on) return false;
  // Se apaga sola al pasar la fecha de fin (comparación ISO funciona como texto).
  if (vacacion.fin && fechaISO > vacacion.fin) return false;
  return true;
}

function textos(config) {
  const doctor = config.nombreDoctor;
  const quienSoy = `Soy el asistente automático del ${doctor}.`;
  const presentacion = `Soy el asistente automático del ${doctor}, geriatra.`;
  const emergencia = 'Si se trata de una emergencia, llame al 911 o acuda al servicio de urgencias más cercano; no espere respuesta por este medio.';
  const precios = [
    `• Consulta a domicilio: ${pesos(config.costoDomicilio)}`,
    `• Consulta en consultorio: ${pesos(config.costoConsultorio)}`,
    `  ${config.direccion}`,
  ].join('\n');
  const pregunta = '¿Prefiere domicilio, consultorio o le es indistinto? Responda con una palabra y el doctor le escribirá para confirmar fecha y hora.';
  const privacidad = config.avisoPrivacidad ? `Aviso de privacidad: ${config.avisoPrivacidad}` : '';
  return { doctor, quienSoy, presentacion, emergencia, precios, pregunta, privacidad };
}

/**
 * @param {object} ctx
 * @param {string} ctx.texto           texto del mensaje ("" si fue audio, imagen, etc.)
 * @param {string} [ctx.tipo]          tipo de mensaje de Meta (text, audio, image, ...)
 * @param {object} ctx.ahora           resultado de tiempo.ahoraEn
 * @param {object} ctx.contacto        {etiquetas: string[], preferencia?: string, ultimaRespuesta?: {clase, en}}
 * @param {object} ctx.vacacion        {on, inicio, fin, regreso} o null
 * @param {object} ctx.config          cargarConfig()
 * @param {boolean} [ctx.urgente]      ya se detectó urgencia
 * @param {boolean} [ctx.alertado]     se logró avisar al doctor
 * @returns {{clase: string, texto: string, preferencia?: string}}
 */
function decidir(ctx) {
  const { texto, ahora, config } = ctx;
  const contacto = ctx.contacto || {};
  const etiquetas = Array.isArray(contacto.etiquetas) ? contacto.etiquetas : [];
  const registrado = etiquetas.includes(ETIQUETA_REGISTRADO);
  const domingoSI = etiquetas.includes(ETIQUETA_DOMINGO);
  const t = textos(config);
  const hola = saludo(ahora.hora);
  const enVacaciones = vacacionActiva(ctx.vacacion, ahora.fechaISO);

  // 1. Urgencia: siempre se contesta, sin importar horario ni enfriamiento.
  if (ctx.urgente) {
    const aviso = ctx.alertado
      ? 'Ya envié un aviso al doctor con su mensaje.'
      : 'Su mensaje queda guardado para el doctor.';
    return {
      clase: 'urgente',
      texto: `${t.emergencia}\n\n${t.quienSoy} ${aviso}`,
    };
  }

  // 2. Baja de mensajes automáticos: se confirma una vez y no se vuelve a contestar.
  if (detectarBaja(texto)) {
    return {
      clase: 'baja',
      silencio: true,
      texto: `Entendido. No le enviaré más mensajes automáticos. El doctor sigue viendo sus mensajes. ${t.emergencia}`,
    };
  }

  // 3. El paciente contesta la pregunta domicilio/consultorio/indistinto
  //    (sólo si se le acaba de preguntar; un registrado que menciona
  //    "consultorio" en otro contexto no cuenta).
  const ultimaClase = contacto.ultimaRespuesta && contacto.ultimaRespuesta.clase;
  const preferencia = detectarPreferencia(texto);
  if (preferencia && (ultimaClase === 'bienvenida' || ultimaClase === 'vacaciones')) {
    return {
      clase: 'preferencia',
      preferencia,
      texto: `Anotado: consulta ${COMO_PREFERENCIA[preferencia]}. El doctor le escribirá para confirmar fecha y hora. Gracias.`,
    };
  }

  // 3. Vacaciones (para todos, registrados o no).
  if (enVacaciones) {
    const v = ctx.vacacion;
    const rango = v.inicio && v.fin ? ` del ${fechaLarga(v.inicio)} al ${fechaLarga(v.fin)}` : '';
    const regreso = v.regreso ? ` y regresa el ${fechaLarga(v.regreso)}` : '';
    return {
      clase: 'vacaciones',
      texto: [
        `${hola}. ${t.quienSoy}`,
        t.emergencia,
        '',
        `El doctor está fuera${rango}${regreso}. Su mensaje queda guardado y se le responde a su regreso.`,
        `Si desea agendar para esa fecha, indíqueme si prefiere domicilio (${pesos(config.costoDomicilio)}), consultorio (${pesos(config.costoConsultorio)}) o le es indistinto.`,
      ].join('\n'),
    };
  }

  // 4. Número nuevo.
  if (!registrado) {
    // Ya dijo qué prefiere (o ya se le dio la bienvenida y contestó): sólo acusar recibo,
    // no repetirle los precios cada vez que escribe.
    if (contacto.preferencia && !preferencia) {
      return {
        clase: 'espera',
        texto: `${hola}. ${t.quienSoy} ${acuse(ctx.tipo)} El doctor le escribirá para confirmar fecha y hora.`,
      };
    }
    // Primer mensaje: presentación, precios y pregunta. Si ya viene con la
    // preferencia ("quiero cita en consultorio"), se anota de una vez.
    const anotada = preferencia ? `Anoté su preferencia: consulta ${COMO_PREFERENCIA[preferencia]}.` : t.pregunta;
    return {
      clase: 'bienvenida',
      ...(preferencia ? { preferencia } : {}),
      texto: [
        `${hola}. ${t.presentacion}`,
        t.emergencia,
        '',
        'Con gusto le ayudo a agendar una consulta.',
        t.precios,
        '',
        anotada,
        ...(preferencia ? ['El doctor le escribirá para confirmar fecha y hora.'] : []),
        ...(t.privacidad ? ['', t.privacidad] : []),
      ].join('\n'),
    };
  }

  // 5. Domingo sin permiso de domingo.
  const esDomingo = ahora.dia === 0;
  if (esDomingo && !domingoSI) {
    return {
      clase: 'domingo',
      texto: [
        `${hola}. ${t.quienSoy}`,
        t.emergencia,
        '',
        'Hoy domingo el doctor no atiende mensajes. Su mensaje queda guardado y se le responde el lunes a primera hora.',
      ].join('\n'),
    };
  }

  // 6. Noche (cualquier día).
  if (esNoche(ahora.hora, config.nocheInicio, config.nocheFin)) {
    return {
      clase: 'fuera_horario',
      texto: [
        `${hola}. ${t.quienSoy}`,
        t.emergencia,
        '',
        'En este horario el doctor no está disponible. Su mensaje queda guardado y se le responde a primera hora.',
      ].join('\n'),
    };
  }

  // 7. Horario normal (incluye domingo de día para quien tiene Domingo-SI).
  return {
    clase: 'horario',
    texto: `${hola}. ${t.quienSoy} ${acuse(ctx.tipo)} El doctor lo revisa y le responde en cuanto pueda.`,
  };
}

module.exports = {
  decidir,
  detectarUrgencia,
  detectarPreferencia,
  detectarBaja,
  acuse,
  normalizar,
  vacacionActiva,
  ETIQUETA_REGISTRADO,
  ETIQUETA_DOMINGO,
};
