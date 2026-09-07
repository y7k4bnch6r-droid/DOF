'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { interpretar, ejecutar, AYUDA } = require('../lib/comandos');

function storeFalso() {
  const contactos = {};
  let vacacion = null;
  return {
    contactos,
    get vacacion() { return vacacion; },
    async leerVacacion() { return vacacion; },
    async guardarVacacion(v) { vacacion = v; },
    async leerContacto(id) { return contactos[id] || null; },
    async guardarContacto(id, cambios) { contactos[id] = { ...(contactos[id] || {}), ...cambios }; },
  };
}

test('interpretar reconoce los comandos y rechaza lo demás', () => {
  assert.deepEqual(interpretar('Vacaciones ON 2026-08-10 2026-08-17'), { accion: 'vacaciones_on', inicio: '2026-08-10', fin: '2026-08-17', regreso: '2026-08-18' });
  assert.deepEqual(interpretar('vacaciones on 10/08/2026 17/08/2026 19/08/2026'), { accion: 'vacaciones_on', inicio: '2026-08-10', fin: '2026-08-17', regreso: '2026-08-19' });
  assert.equal(interpretar('vacaciones on').accion, 'error');
  assert.equal(interpretar('vacaciones on 2026-08-17 2026-08-10').accion, 'error');
  assert.deepEqual(interpretar('vacaciones off'), { accion: 'vacaciones_off' });
  assert.deepEqual(interpretar('alta +52 1 55 1234 5678'), { accion: 'alta', numero: '525512345678' });
  assert.deepEqual(interpretar('alta 525512345678'), { accion: 'alta', numero: '525512345678' });
  assert.deepEqual(interpretar('domingo 525512345678 si'), { accion: 'domingo', numero: '525512345678', permitir: true });
  assert.equal(interpretar('domingo 525512345678 tal vez').accion, 'error');
  assert.deepEqual(interpretar('ayuda'), { accion: 'ayuda' });
  assert.equal(interpretar('hola doctor'), null);
  assert.equal(interpretar(''), null);
});

test('ejecutar modifica el store y responde', async () => {
  const store = storeFalso();
  assert.match(await ejecutar(interpretar('estado'), store), /desactivadas/);
  assert.match(await ejecutar(interpretar('vacaciones on 2026-08-10 2026-08-17'), store), /del 10 de agosto al 17 de agosto; regreso 18 de agosto/);
  assert.deepEqual(store.vacacion, { on: true, inicio: '2026-08-10', fin: '2026-08-17', regreso: '2026-08-18' });
  assert.match(await ejecutar(interpretar('estado'), store), /activas/);
  await ejecutar(interpretar('vacaciones off'), store);
  assert.equal(store.vacacion.on, false);

  assert.match(await ejecutar(interpretar('alta 525512345678'), store), /registrado/);
  assert.deepEqual(store.contactos['525512345678'].etiquetas, ['Registrado']);
  await ejecutar(interpretar('domingo 525512345678 si'), store);
  assert.deepEqual(store.contactos['525512345678'].etiquetas, ['Registrado', 'Domingo-SI']);
  assert.match(await ejecutar(interpretar('ver 525512345678'), store), /Registrado, Domingo-SI/);
  await ejecutar(interpretar('baja 525512345678'), store);
  assert.deepEqual(store.contactos['525512345678'].etiquetas, ['Domingo-SI']);
  assert.match(await ejecutar(interpretar('ver 5215599999999'), store), /sin registro/);
  assert.equal(await ejecutar(interpretar('ayuda'), store), AYUDA);
  assert.match(await ejecutar(interpretar('vacaciones on x y'), store), /Formato/);
});
