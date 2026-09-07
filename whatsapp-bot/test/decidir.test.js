'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { decidir, detectarUrgencia, detectarPreferencia, detectarBaja, vacacionActiva } = require('../lib/decidir');
const { cargarConfig } = require('../lib/config');

const config = cargarConfig({
  WHATSAPP_TOKEN: 't', WHATSAPP_APP_SECRET: 's', WHATSAPP_PHONE_NUMBER_ID: '1', WHATSAPP_VERIFY_TOKEN: 'v',
  DOCTOR_PHONE: '525500000000',
});

const lunes10 = { dia: 1, hora: 10, minuto: 0, fechaISO: '2026-09-07', instante: new Date('2026-09-07T16:00:00Z') };
const lunes23 = { ...lunes10, hora: 23 };
const domingo11 = { ...lunes10, dia: 0, hora: 11, fechaISO: '2026-09-06' };
const registrado = { etiquetas: ['Registrado'] };
const registradoDomingo = { etiquetas: ['Registrado', 'Domingo-SI'] };

function d(extra) {
  return decidir({ texto: 'hola', ahora: lunes10, contacto: null, vacacion: null, config, ...extra });
}

test('número nuevo recibe bienvenida con precios, dirección y aviso de bot', () => {
  const r = d({});
  assert.equal(r.clase, 'bienvenida');
  assert.match(r.texto, /^Buenos días\. Soy el asistente automático del Dr\. Ulises Pérez, geriatra\./);
  assert.match(r.texto, /911/);
  assert.match(r.texto, /\$1,700/);
  assert.match(r.texto, /\$1,200/);
  assert.match(r.texto, /Río Mixcoac/);
  assert.match(r.texto, /domicilio, consultorio o le es indistinto/);
});

test('contacto con documento pero sin etiquetas no truena', () => {
  assert.equal(d({ contacto: {} }).clase, 'bienvenida');
  assert.equal(d({ contacto: { etiquetas: 'Registrado' } }).clase, 'bienvenida');
});

test('el saludo cambia con la hora', () => {
  assert.match(d({ ahora: { ...lunes10, hora: 15 } }).texto, /^Buenas tardes/);
  assert.match(d({ ahora: { ...lunes10, hora: 20 } }).texto, /^Buenas noches/);
});

test('captura la preferencia cuando el nuevo contesta la pregunta', () => {
  const r = d({ texto: 'Consultorio por favor', contacto: { etiquetas: [], ultimaRespuesta: { clase: 'bienvenida', en: '2026-09-07T15:00:00Z' } } });
  assert.equal(r.clase, 'preferencia');
  assert.equal(r.preferencia, 'consultorio');
  assert.match(r.texto, /Anotado: consulta en consultorio/);
  assert.equal(d({ texto: 'en mi casa' }).preferencia, 'domicilio');
  assert.equal(d({ texto: 'Me da igual' }).preferencia, 'indistinto');
});

test('nuevo que ya dijo su preferencia recibe acuse, no otra vez los precios', () => {
  const r = d({ texto: 'gracias', contacto: { etiquetas: [], preferencia: 'consultorio', ultimaRespuesta: { clase: 'preferencia', en: '2026-09-07T15:00:00Z' } } });
  assert.equal(r.clase, 'espera');
  assert.doesNotMatch(r.texto, /\$1,700/);
  assert.match(r.texto, /El doctor le escribirá/);
});

test('nuevo que llega diciendo "consultorio" de entrada: bienvenida con la preferencia anotada', () => {
  const r = d({ texto: 'buenas, quiero cita en consultorio' });
  assert.equal(r.clase, 'bienvenida');
  assert.equal(r.preferencia, 'consultorio');
  assert.match(r.texto, /\$1,200/);
  assert.match(r.texto, /Anoté su preferencia: consulta en consultorio/);
  assert.doesNotMatch(r.texto, /¿Prefiere/);
});

test('un registrado que menciona "consultorio" en horario normal no dispara la captura', () => {
  const r = d({ texto: 'nos vemos en el consultorio', contacto: { ...registrado, ultimaRespuesta: { clase: 'horario', en: '2026-09-07T15:00:00Z' } } });
  assert.equal(r.clase, 'horario');
});

test('vacaciones activas para todos, con fechas en español y se apagan solas', () => {
  const vacacion = { on: true, inicio: '2026-08-10', fin: '2026-08-17', regreso: '2026-08-18' };
  const agosto = { ...lunes10, fechaISO: '2026-08-12' };
  const r = d({ ahora: agosto, vacacion, contacto: registrado });
  assert.equal(r.clase, 'vacaciones');
  assert.match(r.texto, /del 10 de agosto al 17 de agosto y regresa el 18 de agosto/);
  assert.equal(d({ ahora: agosto, vacacion }).clase, 'vacaciones');
  assert.equal(d({ ahora: { ...lunes10, fechaISO: '2026-08-18' }, vacacion, contacto: registrado }).clase, 'horario');
  assert.equal(vacacionActiva({ on: true }, '2030-01-01'), true);
  assert.equal(vacacionActiva({ on: false, fin: '2099-01-01' }, '2030-01-01'), false);
  assert.equal(vacacionActiva(null, '2030-01-01'), false);
});

test('registrado: domingo, noche y horario normal', () => {
  assert.equal(d({ contacto: registrado, ahora: domingo11 }).clase, 'domingo');
  assert.match(d({ contacto: registrado, ahora: domingo11 }).texto, /lunes a primera hora/);
  assert.equal(d({ contacto: registradoDomingo, ahora: domingo11 }).clase, 'horario');
  assert.equal(d({ contacto: registradoDomingo, ahora: { ...domingo11, hora: 23 } }).clase, 'fuera_horario');
  assert.equal(d({ contacto: registrado, ahora: lunes23 }).clase, 'fuera_horario');
  assert.equal(d({ contacto: registrado, ahora: { ...lunes10, hora: 5 } }).clase, 'fuera_horario');
  assert.equal(d({ contacto: registrado, ahora: { ...lunes10, hora: 6 } }).clase, 'horario');
  const r = d({ contacto: registrado });
  assert.equal(r.clase, 'horario');
  assert.match(r.texto, /asistente automático/);
  assert.doesNotMatch(r.texto, /acompañar/);
});

test('urgencia gana sobre todo lo demás', () => {
  const r = d({ texto: 'mi mamá se cayó y no responde', contacto: registrado, ahora: lunes23, urgente: true, alertado: true });
  assert.equal(r.clase, 'urgente');
  assert.match(r.texto, /^Si se trata de una emergencia, llame al 911/);
  assert.match(r.texto, /Ya envié un aviso al doctor/);
  assert.match(d({ urgente: true, alertado: false }).texto, /queda guardado/);
});

test('detectarUrgencia y detectarPreferencia', () => {
  assert.equal(detectarUrgencia('Doctor, mi papá SE CAYÓ y sangra de la cabeza'), true);
  assert.equal(detectarUrgencia('tiene dolor en el pecho'), true);
  assert.equal(detectarUrgencia('es urgente'), true);
  assert.equal(detectarUrgencia('no respira bien'), true);
  assert.equal(detectarUrgencia('buenas tardes, quisiera una cita'), false);
  assert.equal(detectarUrgencia(''), false);
  assert.equal(detectarUrgencia('la caídita de precio'), false);
  assert.equal(detectarPreferencia('quiero que vaya a domicilio'), 'domicilio');
  assert.equal(detectarPreferencia('hola'), null);
});

test('baja de mensajes automáticos', () => {
  assert.equal(detectarBaja('Ya no me mande mensajes por favor'), true);
  assert.equal(detectarBaja('STOP'), true);
  assert.equal(detectarBaja('no quiero recibir mensajes'), true);
  assert.equal(detectarBaja('me mandó el mensaje del doctor'), false);
  assert.equal(detectarBaja('baja de presión'), false);
  const r = d({ texto: 'ya no me manden mensajes', contacto: registrado });
  assert.equal(r.clase, 'baja');
  assert.equal(r.silencio, true);
  assert.match(r.texto, /No le enviaré más mensajes automáticos/);
});

test('acuse según el tipo de mensaje y aviso de privacidad opcional', () => {
  assert.match(d({ texto: '', tipo: 'audio', contacto: registrado }).texto, /Recibí su nota de voz/);
  assert.match(d({ texto: '', tipo: 'image', contacto: registrado }).texto, /Recibí su imagen/);
  assert.match(d({ texto: 'hola', tipo: 'text', contacto: registrado }).texto, /Su mensaje fue recibido/);
  assert.doesNotMatch(d({}).texto, /Aviso de privacidad/);
  const conAviso = { ...config, avisoPrivacidad: 'https://consultorio.mx/privacidad' };
  assert.match(d({ config: conAviso }).texto, /Aviso de privacidad: https:\/\/consultorio\.mx\/privacidad/);
});
