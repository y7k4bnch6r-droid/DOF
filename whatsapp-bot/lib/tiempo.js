'use strict';

/**
 * Hora local de la Ciudad de México sin el truco de
 * new Date(new Date().toLocaleString(...)), que depende del formato de un
 * string y se rompe según la versión de ICU. Aquí se usan las partes que
 * entrega Intl directamente.
 */

const DIAS = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

function ahoraEn(zonaHoraria, fecha = new Date()) {
  const partes = new Intl.DateTimeFormat('en-US', {
    timeZone: zonaHoraria,
    hourCycle: 'h23',
    weekday: 'short',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).formatToParts(fecha);
  const p = {};
  for (const parte of partes) if (parte.type !== 'literal') p[parte.type] = parte.value;
  return {
    dia: DIAS[p.weekday], // 0 = domingo
    hora: Number(p.hour) % 24, // algunas versiones de ICU regresan "24" a medianoche
    minuto: Number(p.minute),
    fechaISO: `${p.year}-${p.month}-${p.day}`,
    instante: fecha,
  };
}

function esNoche(hora, inicio, fin) {
  if (inicio === fin) return false;
  if (inicio > fin) return hora >= inicio || hora < fin; // p. ej. 22 -> 6
  return hora >= inicio && hora < fin;
}

function saludo(hora) {
  if (hora < 12) return 'Buenos días';
  if (hora < 19) return 'Buenas tardes';
  return 'Buenas noches';
}

/** "2026-08-10" -> "10 de agosto" */
function fechaLarga(fechaISO) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(fechaISO || '')) return fechaISO || '';
  return new Intl.DateTimeFormat('es-MX', { day: 'numeric', month: 'long', timeZone: 'UTC' })
    .format(new Date(`${fechaISO}T00:00:00Z`));
}

/** Suma días a una fecha ISO (calendario, sin zona horaria). */
function sumarDias(fechaISO, dias) {
  const d = new Date(`${fechaISO}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

/** Acepta "2026-08-10" o "10/08/2026"; regresa ISO o null si no es fecha válida. */
function normalizarFecha(texto) {
  const t = (texto || '').trim();
  let y; let m; let d;
  let match = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (match) [, y, m, d] = match;
  else {
    match = t.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (!match) return null;
    [, d, m, y] = match;
  }
  const iso = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
  const fecha = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(fecha.getTime()) || fecha.toISOString().slice(0, 10) !== iso) return null;
  return iso;
}

module.exports = { ahoraEn, esNoche, saludo, fechaLarga, sumarDias, normalizarFecha };
