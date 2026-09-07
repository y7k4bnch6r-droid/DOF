'use strict';

/**
 * Comandos que el doctor manda por WhatsApp al número del consultorio.
 * Sólo se aceptan si el mensaje viene de DOCTOR_PHONE y la firma de Meta
 * es válida (ver index.js), así que nadie más puede activarlos.
 */

const { normalizar, ETIQUETA_REGISTRADO, ETIQUETA_DOMINGO } = require('./decidir');
const { normalizarFecha, sumarDias, fechaLarga } = require('./tiempo');
const { normalizarNumero } = require('./config');

const AYUDA = [
  'Comandos disponibles:',
  '• vacaciones on 2026-08-10 2026-08-17 [2026-08-18] → activa vacaciones (inicio, fin y, opcional, día de regreso; también sirve 10/08/2026)',
  '• vacaciones off → desactiva vacaciones',
  '• alta 5215512345678 → marca el número como paciente registrado',
  '• baja 5215512345678 → quita el registro',
  '• domingo 5215512345678 si|no → permite (o no) mensajes en domingo',
  '• ver 5215512345678 → muestra etiquetas y preferencia',
  '• estado → muestra si hay vacaciones activas',
  '• ayuda → esta lista',
].join('\n');

function telefono(token) {
  const limpio = normalizarNumero(token);
  return /^\d{8,16}$/.test(limpio) ? limpio : null;
}

/** Regresa {accion, ...} o null si el texto no es un comando. */
function interpretar(texto) {
  const partes = normalizar(texto).split(' ').filter(Boolean);
  if (!partes.length) return null;
  const [cmd, ...args] = partes;

  if (cmd === 'ayuda' || cmd === 'help' || cmd === '?') return { accion: 'ayuda' };
  if (cmd === 'estado') return { accion: 'estado' };

  if (cmd === 'vacaciones') {
    const modo = args[0];
    if (modo === 'off' || modo === 'no') return { accion: 'vacaciones_off' };
    if (modo === 'on' || modo === 'si') {
      const inicio = normalizarFecha(args[1]);
      const fin = normalizarFecha(args[2]);
      if (!inicio || !fin) return { accion: 'error', mensaje: 'Formato: vacaciones on 2026-08-10 2026-08-17 [2026-08-18]' };
      if (fin < inicio) return { accion: 'error', mensaje: 'La fecha de fin es anterior a la de inicio.' };
      const regreso = args[3] ? normalizarFecha(args[3]) : sumarDias(fin, 1);
      if (!regreso) return { accion: 'error', mensaje: 'La fecha de regreso no es válida.' };
      return { accion: 'vacaciones_on', inicio, fin, regreso };
    }
    return { accion: 'error', mensaje: 'Formato: vacaciones on <inicio> <fin> [regreso] | vacaciones off' };
  }

  if (cmd === 'alta' || cmd === 'baja' || cmd === 'ver' || cmd === 'domingo') {
    // El número puede venir con espacios o "+" ("+52 1 55 1234 5678"): se juntan los tokens.
    const valor = cmd === 'domingo' ? args[args.length - 1] : null;
    const numero = telefono((cmd === 'domingo' ? args.slice(0, -1) : args).join(''));
    if (!numero) return { accion: 'error', mensaje: `Formato: ${cmd} 5215512345678${cmd === 'domingo' ? ' si|no' : ''}` };
    if (cmd === 'domingo') {
      if (valor !== 'si' && valor !== 'no') return { accion: 'error', mensaje: 'Formato: domingo 5215512345678 si|no' };
      return { accion: 'domingo', numero, permitir: valor === 'si' };
    }
    return { accion: cmd, numero };
  }

  return null;
}

/**
 * Ejecuta el comando contra el store y regresa el texto de respuesta para el doctor.
 * store: {leerVacacion, guardarVacacion, leerContacto, guardarContacto}
 */
async function ejecutar(comando, store) {
  switch (comando.accion) {
    case 'ayuda':
      return AYUDA;
    case 'error':
      return `${comando.mensaje}\n\nEscriba *ayuda* para ver los comandos.`;
    case 'estado': {
      const v = await store.leerVacacion();
      if (!v || !v.on) return 'Vacaciones: desactivadas.';
      return `Vacaciones: activas del ${fechaLarga(v.inicio)} al ${fechaLarga(v.fin)}, regreso ${fechaLarga(v.regreso)}.`;
    }
    case 'vacaciones_on':
      await store.guardarVacacion({ on: true, inicio: comando.inicio, fin: comando.fin, regreso: comando.regreso });
      return `Vacaciones activadas del ${fechaLarga(comando.inicio)} al ${fechaLarga(comando.fin)}; regreso ${fechaLarga(comando.regreso)}. Se apagan solas al pasar el ${fechaLarga(comando.fin)}.`;
    case 'vacaciones_off':
      await store.guardarVacacion({ on: false });
      return 'Vacaciones desactivadas.';
    case 'alta':
    case 'baja': {
      const contacto = (await store.leerContacto(comando.numero)) || {};
      const etiquetas = new Set(Array.isArray(contacto.etiquetas) ? contacto.etiquetas : []);
      if (comando.accion === 'alta') etiquetas.add(ETIQUETA_REGISTRADO);
      else etiquetas.delete(ETIQUETA_REGISTRADO);
      // "alta" también reactiva los mensajes automáticos si el paciente había pedido baja.
      const cambios = { etiquetas: [...etiquetas] };
      if (comando.accion === 'alta' && contacto.silencio) cambios.silencio = false;
      await store.guardarContacto(comando.numero, cambios);
      return `${comando.numero}: ${comando.accion === 'alta' ? 'registrado' : 'registro eliminado'}. Etiquetas: ${[...etiquetas].join(', ') || 'ninguna'}.`;
    }
    case 'domingo': {
      const contacto = (await store.leerContacto(comando.numero)) || {};
      const etiquetas = new Set(Array.isArray(contacto.etiquetas) ? contacto.etiquetas : []);
      if (comando.permitir) etiquetas.add(ETIQUETA_DOMINGO);
      else etiquetas.delete(ETIQUETA_DOMINGO);
      await store.guardarContacto(comando.numero, { etiquetas: [...etiquetas] });
      return `${comando.numero}: domingo ${comando.permitir ? 'permitido' : 'no permitido'}. Etiquetas: ${[...etiquetas].join(', ') || 'ninguna'}.`;
    }
    case 'ver': {
      const contacto = await store.leerContacto(comando.numero);
      if (!contacto) return `${comando.numero}: sin registro.`;
      const etiquetas = Array.isArray(contacto.etiquetas) && contacto.etiquetas.length ? contacto.etiquetas.join(', ') : 'ninguna';
      const nombre = contacto.nombre ? ` (${contacto.nombre})` : '';
      const pref = contacto.preferencia ? ` Preferencia: ${contacto.preferencia}.` : '';
      const silencio = contacto.silencio ? ' Pidió no recibir mensajes automáticos.' : '';
      return `${comando.numero}${nombre}: etiquetas ${etiquetas}.${pref}${silencio}`;
    }
    default:
      return AYUDA;
  }
}

module.exports = { interpretar, ejecutar, AYUDA };
