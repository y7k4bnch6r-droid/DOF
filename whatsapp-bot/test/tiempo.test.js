'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { ahoraEn, esNoche, saludo, fechaLarga, sumarDias, normalizarFecha } = require('../lib/tiempo');

const ZONA = 'America/Mexico_City'; // UTC-6 fijo desde 2022

test('ahoraEn convierte a hora de la Ciudad de México', () => {
  // Sábado 2026-09-05 23:30 CDMX = domingo 05:30 UTC
  const sab = ahoraEn(ZONA, new Date('2026-09-06T05:30:00Z'));
  assert.equal(sab.dia, 6);
  assert.equal(sab.hora, 23);
  assert.equal(sab.minuto, 30);
  assert.equal(sab.fechaISO, '2026-09-05');

  // Domingo 2026-09-06 22:00 CDMX = lunes 04:00 UTC
  const dom = ahoraEn(ZONA, new Date('2026-09-07T04:00:00Z'));
  assert.equal(dom.dia, 0);
  assert.equal(dom.hora, 22);

  // Medianoche exacta no debe salir como 24
  const media = ahoraEn(ZONA, new Date('2026-09-07T06:00:00Z'));
  assert.equal(media.hora, 0);
  assert.equal(media.dia, 1);
  assert.equal(media.fechaISO, '2026-09-07');
});

test('esNoche maneja el rango que cruza medianoche', () => {
  assert.equal(esNoche(22, 22, 6), true);
  assert.equal(esNoche(3, 22, 6), true);
  assert.equal(esNoche(6, 22, 6), false);
  assert.equal(esNoche(12, 22, 6), false);
  assert.equal(esNoche(13, 12, 14), true);
  assert.equal(esNoche(5, 6, 6), false);
});

test('saludo según la hora', () => {
  assert.equal(saludo(8), 'Buenos días');
  assert.equal(saludo(12), 'Buenas tardes');
  assert.equal(saludo(19), 'Buenas noches');
  assert.equal(saludo(0), 'Buenos días');
});

test('fechaLarga y sumarDias', () => {
  assert.equal(fechaLarga('2026-08-10'), '10 de agosto');
  assert.equal(fechaLarga('2026-12-31'), '31 de diciembre');
  assert.equal(sumarDias('2026-08-31', 1), '2026-09-01');
  assert.equal(sumarDias('2024-02-28', 1), '2024-02-29');
});

test('normalizarFecha acepta ISO y DD/MM/AAAA y rechaza basura', () => {
  assert.equal(normalizarFecha('2026-08-10'), '2026-08-10');
  assert.equal(normalizarFecha('10/08/2026'), '2026-08-10');
  assert.equal(normalizarFecha('2026-8-5'), '2026-08-05');
  assert.equal(normalizarFecha('2026-02-30'), null);
  assert.equal(normalizarFecha('mañana'), null);
  assert.equal(normalizarFecha(undefined), null);
});
