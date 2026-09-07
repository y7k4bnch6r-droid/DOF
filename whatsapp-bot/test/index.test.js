'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { crearHandler, extraerTexto } = require('../index');
const { cargarConfig } = require('../lib/config');
const { firmar } = require('../lib/firma');

const APP_SECRET = 'secreto';
const DOCTOR = '525500000000';
const PACIENTE = '525511111111';

const config = cargarConfig({
  WHATSAPP_TOKEN: 't', WHATSAPP_APP_SECRET: APP_SECRET, WHATSAPP_PHONE_NUMBER_ID: '1', WHATSAPP_VERIFY_TOKEN: 'verificame',
  DOCTOR_PHONE: DOCTOR, REPLY_COOLDOWN_MINUTES: '240', LOG_RETENTION_DAYS: '30',
});

function storeFalso() {
  const procesados = new Set();
  const contactos = {};
  const logs = [];
  let vacacion = null;
  return {
    procesados, contactos, logs,
    get vacacion() { return vacacion; },
    async marcarProcesado(id) { if (procesados.has(id)) return false; procesados.add(id); return true; },
    async leerContacto(id) { return contactos[id] ? { ...contactos[id] } : null; },
    async guardarContacto(id, cambios) { contactos[id] = { ...(contactos[id] || {}), ...cambios }; },
    async leerVacacion() { return vacacion; },
    async guardarVacacion(v) { vacacion = v; },
    async registrarLog(e) { logs.push(e); },
  };
}

function whatsappFalso({ fallar } = {}) {
  const enviados = [];
  return {
    enviados,
    async enviarTexto(para, cuerpo) {
      if (fallar && fallar(para)) { const e = new Error('Meta respondió 400'); e.codigoMeta = fallar(para); throw e; }
      enviados.push({ para, cuerpo });
      return { messages: [{ id: `wamid.out.${enviados.length}` }] };
    },
    async enviarPlantilla(para, nombre, parametros) {
      enviados.push({ para, plantilla: nombre, parametros });
      return {};
    },
  };
}

function resFalso() {
  const r = { codigo: null, cuerpo: null, tipo: null };
  r.status = (c) => { r.codigo = c; return r; };
  r.type = (t) => { r.tipo = t; return r; };
  r.send = (b) => { r.cuerpo = b; return r; };
  r.sendStatus = (c) => { r.codigo = c; return r; };
  return r;
}

function reqPost(body, { firma, ip } = {}) {
  const raw = Buffer.from(JSON.stringify(body));
  const headers = { 'x-hub-signature-256': firma === undefined ? firmar(raw, APP_SECRET) : firma };
  return { method: 'POST', body, rawBody: raw, ip: ip || '1.2.3.4', get: (h) => headers[h.toLowerCase()] };
}

let contador = 0;
// timestamp: un minuto antes del reloj por defecto de armar() (2026-09-07T16:00:00Z)
const TS_RECIENTE = String(Math.floor(new Date('2026-09-07T15:59:00Z').getTime() / 1000));
function mensaje(from, texto, extra = {}) {
  contador += 1;
  return { from, id: `wamid.${contador}`, timestamp: TS_RECIENTE, type: 'text', text: { body: texto }, ...extra };
}

function payload(mensajes, { nombre, statuses } = {}) {
  const value = { messaging_product: 'whatsapp', metadata: { display_phone_number: '5255', phone_number_id: '1' } };
  if (mensajes && mensajes.length) {
    value.contacts = mensajes.map((m) => ({ wa_id: m.from, profile: { name: nombre || 'Paciente Prueba' } }));
    value.messages = mensajes;
  }
  if (statuses) value.statuses = statuses;
  return { object: 'whatsapp_business_account', entry: [{ id: 'waba', changes: [{ field: 'messages', value }] }] };
}

function armar({ ahora = '2026-09-07T16:00:00Z', fallar } = {}) {
  const store = storeFalso();
  const whatsapp = whatsappFalso({ fallar });
  let instante = new Date(ahora);
  const handler = crearHandler({ config, store, whatsapp, reloj: () => instante });
  return { store, whatsapp, handler, avanzar: (ms) => { instante = new Date(instante.getTime() + ms); } };
}

test('GET: verificación del webhook', async () => {
  const { handler } = armar();
  const ok = resFalso();
  await handler({ method: 'GET', query: { 'hub.mode': 'subscribe', 'hub.verify_token': 'verificame', 'hub.challenge': '12345' } }, ok);
  assert.equal(ok.codigo, 200);
  assert.equal(ok.cuerpo, '12345');
  const mal = resFalso();
  await handler({ method: 'GET', query: { 'hub.mode': 'subscribe', 'hub.verify_token': 'otro', 'hub.challenge': '1' } }, mal);
  assert.equal(mal.codigo, 403);
  const sinModo = resFalso();
  await handler({ method: 'GET', query: { 'hub.verify_token': 'verificame', 'hub.challenge': '1' } }, sinModo);
  assert.equal(sinModo.codigo, 403);
});

test('POST: firma inválida o ausente → 401 y no se manda nada', async () => {
  const { handler, whatsapp, store } = armar();
  for (const firma of ['sha256=deadbeef', null, '']) {
    const res = resFalso();
    await handler(reqPost(payload([mensaje(PACIENTE, 'hola')]), { firma }), res);
    assert.equal(res.codigo, 401);
  }
  assert.equal(whatsapp.enviados.length, 0);
  assert.equal(store.logs.length, 0);
});

test('POST: sin rawBody → 500; método raro → 405; objeto desconocido → 404', async () => {
  const { handler } = armar();
  const r1 = resFalso();
  await handler({ method: 'POST', body: {}, get: () => undefined }, r1);
  assert.equal(r1.codigo, 500);
  const r2 = resFalso();
  await handler({ method: 'PUT' }, r2);
  assert.equal(r2.codigo, 405);
  const r3 = resFalso();
  await handler(reqPost({ object: 'page', entry: [] }), r3);
  assert.equal(r3.codigo, 404);
});

test('POST: sólo statuses → 200 sin respuesta', async () => {
  const { handler, whatsapp } = armar();
  const res = resFalso();
  await handler(reqPost(payload([], { statuses: [{ id: 'wamid.x', status: 'delivered', recipient_id: PACIENTE }] })), res);
  assert.equal(res.codigo, 200);
  assert.equal(whatsapp.enviados.length, 0);
});

test('número nuevo: bienvenida, se crea el contacto con nombre y queda log sin texto', async () => {
  const { handler, whatsapp, store } = armar();
  const res = resFalso();
  await handler(reqPost(payload([mensaje(PACIENTE, 'Hola, quisiera una cita para mi mamá')], { nombre: 'Lupita' })), res);
  assert.equal(res.codigo, 200);
  assert.equal(whatsapp.enviados.length, 1);
  assert.equal(whatsapp.enviados[0].para, PACIENTE);
  assert.match(whatsapp.enviados[0].cuerpo, /asistente automático/);
  assert.equal(store.contactos[PACIENTE].nombre, 'Lupita');
  assert.deepEqual(store.contactos[PACIENTE].etiquetas, []);
  assert.equal(store.contactos[PACIENTE].ultimaRespuesta.clase, 'bienvenida');
  assert.equal(store.logs.length, 1);
  assert.equal(store.logs[0].texto, undefined);
  assert.equal(store.logs[0].largoTexto, 'Hola, quisiera una cita para mi mamá'.length);
  assert.ok(store.logs[0].expiraEn instanceof Date);
});

test('mismo mensaje reenviado por Meta → no se contesta dos veces', async () => {
  const { handler, whatsapp } = armar();
  const m = mensaje(PACIENTE, 'hola');
  await handler(reqPost(payload([m])), resFalso());
  await handler(reqPost(payload([m])), resFalso());
  assert.equal(whatsapp.enviados.length, 1);
});

test('enfriamiento: la misma respuesta no se repite dentro de la ventana, sí después', async () => {
  const { handler, whatsapp, avanzar } = armar();
  await handler(reqPost(payload([mensaje(PACIENTE, 'hola')])), resFalso());
  await handler(reqPost(payload([mensaje(PACIENTE, 'sigue ahí?')])), resFalso());
  assert.equal(whatsapp.enviados.length, 1);
  avanzar(5 * 60 * 60 * 1000);
  await handler(reqPost(payload([mensaje(PACIENTE, 'hola de nuevo')])), resFalso());
  assert.equal(whatsapp.enviados.length, 2);
});

test('el nuevo contesta "consultorio": se guarda la preferencia aunque haya enfriamiento', async () => {
  const { handler, whatsapp, store } = armar();
  await handler(reqPost(payload([mensaje(PACIENTE, 'hola')])), resFalso());
  await handler(reqPost(payload([mensaje(PACIENTE, 'Consultorio')])), resFalso());
  assert.equal(whatsapp.enviados.length, 2);
  assert.match(whatsapp.enviados[1].cuerpo, /Anotado: consulta en consultorio/);
  assert.equal(store.contactos[PACIENTE].preferencia, 'consultorio');
});

test('después de anotar la preferencia no se vuelve a mandar la bienvenida', async () => {
  const { handler, whatsapp, store } = armar();
  await handler(reqPost(payload([mensaje(PACIENTE, 'hola')])), resFalso());
  await handler(reqPost(payload([mensaje(PACIENTE, 'domicilio')])), resFalso());
  await handler(reqPost(payload([mensaje(PACIENTE, 'gracias doctor')])), resFalso());
  await handler(reqPost(payload([mensaje(PACIENTE, 'ahí le encargo')])), resFalso());
  assert.equal(whatsapp.enviados.length, 3);
  assert.match(whatsapp.enviados[2].cuerpo, /Su mensaje fue recibido/);
  assert.doesNotMatch(whatsapp.enviados[2].cuerpo, /\$1,700/);
  assert.equal(store.contactos[PACIENTE].preferencia, 'domicilio');
});

test('audio de un registrado en horario: se contesta igual; reacción: se ignora', async () => {
  const { handler, whatsapp, store } = armar();
  store.contactos[PACIENTE] = { etiquetas: ['Registrado'] };
  await handler(reqPost(payload([mensaje(PACIENTE, undefined, { type: 'audio', text: undefined, audio: { id: 'a1' } })])), resFalso());
  assert.equal(whatsapp.enviados.length, 1);
  assert.match(whatsapp.enviados[0].cuerpo, /Recibí su nota de voz/);
  await handler(reqPost(payload([mensaje(PACIENTE, undefined, { type: 'reaction', text: undefined, reaction: { emoji: '👍' } })])), resFalso());
  assert.equal(whatsapp.enviados.length, 1);
});

test('registrado en la noche y en domingo', async () => {
  const noche = armar({ ahora: '2026-09-08T05:00:00Z' }); // lunes 23:00 CDMX
  noche.store.contactos[PACIENTE] = { etiquetas: ['Registrado'] };
  await noche.handler(reqPost(payload([mensaje(PACIENTE, 'hola')])), resFalso());
  assert.match(noche.whatsapp.enviados[0].cuerpo, /En este horario el doctor no está disponible/);

  const domingo = armar({ ahora: '2026-09-06T17:00:00Z' }); // domingo 11:00 CDMX
  domingo.store.contactos[PACIENTE] = { etiquetas: ['Registrado'] };
  await domingo.handler(reqPost(payload([mensaje(PACIENTE, 'hola')])), resFalso());
  assert.match(domingo.whatsapp.enviados[0].cuerpo, /Hoy domingo/);
});

test('urgencia: avisa al doctor, contesta aunque haya enfriamiento y lo registra', async () => {
  const { handler, whatsapp, store } = armar();
  store.contactos[PACIENTE] = { etiquetas: ['Registrado'], nombre: 'Lupita', ultimaRespuesta: { clase: 'horario', en: '2026-09-07T15:59:00Z' } };
  await handler(reqPost(payload([mensaje(PACIENTE, 'Doctor, mi mamá se cayó y no responde')], { nombre: 'Lupita' })), resFalso());
  assert.equal(whatsapp.enviados.length, 2);
  assert.equal(whatsapp.enviados[0].para, DOCTOR);
  assert.match(whatsapp.enviados[0].cuerpo, /urgente de Lupita \(525511111111\)/);
  assert.match(whatsapp.enviados[0].cuerpo, /se cayó y no responde/);
  assert.equal(whatsapp.enviados[1].para, PACIENTE);
  assert.match(whatsapp.enviados[1].cuerpo, /^Si se trata de una emergencia, llame al 911/);
  assert.match(whatsapp.enviados[1].cuerpo, /Ya envié un aviso al doctor/);
  assert.equal(store.logs[0].urgente, true);
  assert.equal(store.logs[0].alertado, true);
});

test('urgencia fuera de la ventana de 24 h del doctor: cae a plantilla si está configurada', async () => {
  const conPlantilla = cargarConfig({
    WHATSAPP_TOKEN: 't', WHATSAPP_APP_SECRET: APP_SECRET, WHATSAPP_PHONE_NUMBER_ID: '1', WHATSAPP_VERIFY_TOKEN: 'verificame',
    DOCTOR_PHONE: DOCTOR, ALERT_TEMPLATE_NAME: 'alerta_paciente',
  });
  const store = storeFalso();
  const whatsapp = whatsappFalso({ fallar: (para) => (para === DOCTOR ? 131047 : null) });
  const handler = crearHandler({ config: conPlantilla, store, whatsapp, reloj: () => new Date('2026-09-07T16:00:00Z') });
  await handler(reqPost(payload([mensaje(PACIENTE, 'es urgente, no respira bien')])), resFalso());
  assert.equal(whatsapp.enviados[0].plantilla, 'alerta_paciente');
  assert.equal(whatsapp.enviados[0].para, DOCTOR);
  assert.match(whatsapp.enviados[1].cuerpo, /Ya envié un aviso/);
});

test('si Meta rechaza el envío, se responde 200 igual, no se marca ultimaRespuesta y queda log', async () => {
  const { handler, store } = armar({ fallar: () => 131000 });
  const res = resFalso();
  await handler(reqPost(payload([mensaje(PACIENTE, 'hola')])), res);
  assert.equal(res.codigo, 200);
  assert.equal(store.contactos[PACIENTE].ultimaRespuesta, undefined);
  assert.equal(store.logs[0].enviado, false);
});

test('el doctor manda comandos y el bot no lo trata como paciente', async () => {
  const { handler, whatsapp, store } = armar();
  await handler(reqPost(payload([mensaje(DOCTOR, 'vacaciones on 2026-08-10 2026-08-17')])), resFalso());
  assert.equal(store.vacacion.on, true);
  assert.match(whatsapp.enviados[0].cuerpo, /Vacaciones activadas/);
  await handler(reqPost(payload([mensaje(DOCTOR, 'alta 5215511111111')])), resFalso());
  assert.deepEqual(store.contactos[PACIENTE].etiquetas, ['Registrado']);
  await handler(reqPost(payload([mensaje(DOCTOR, 'qué onda')])), resFalso());
  assert.match(whatsapp.enviados[2].cuerpo, /No entendí ese comando/);
  assert.equal(whatsapp.enviados.every((e) => e.para === DOCTOR), true);
  assert.equal(store.contactos[DOCTOR], undefined);
});

test('otro número no puede usar los comandos', async () => {
  const { handler, store } = armar();
  await handler(reqPost(payload([mensaje(PACIENTE, 'vacaciones on 2026-08-10 2026-08-17')])), resFalso());
  assert.equal(store.vacacion, null);
});

test('varios mensajes en un payload y un error en uno no tumba los demás', async () => {
  const { handler, whatsapp, store } = armar();
  const otro = '5215522222222';
  const original = store.leerContacto;
  store.leerContacto = async (id) => { if (id === PACIENTE) throw new Error('Firestore caído'); return original(id); };
  const res = resFalso();
  await handler(reqPost(payload([mensaje(PACIENTE, 'hola'), mensaje(otro, 'hola')])), res);
  assert.equal(res.codigo, 200);
  assert.equal(whatsapp.enviados.length, 1);
  assert.equal(whatsapp.enviados[0].para, otro);
});

test('mensaje con remitente inválido no rompe ni crea documentos raros', async () => {
  const { handler, whatsapp, store } = armar();
  const res = resFalso();
  await handler(reqPost(payload([mensaje('../config', 'hola')])), res);
  assert.equal(res.codigo, 200);
  assert.equal(whatsapp.enviados.length, 0);
  assert.equal(Object.keys(store.contactos).length, 0);
});

test('extraerTexto cubre texto, botones, listas y captions', () => {
  assert.equal(extraerTexto({ type: 'text', text: { body: 'hola' } }), 'hola');
  assert.equal(extraerTexto({ type: 'interactive', interactive: { type: 'button_reply', button_reply: { id: '1', title: 'Consultorio' } } }), 'Consultorio');
  assert.equal(extraerTexto({ type: 'interactive', interactive: { type: 'list_reply', list_reply: { id: '1', title: 'Domicilio' } } }), 'Domicilio');
  assert.equal(extraerTexto({ type: 'button', button: { text: 'Sí', payload: 'SI' } }), 'Sí');
  assert.equal(extraerTexto({ type: 'image', image: { id: 'x', caption: 'receta' } }), 'receta');
  assert.equal(extraerTexto({ type: 'audio', audio: { id: 'x' } }), '');
});

test('números mexicanos con o sin el "1" se tratan como el mismo contacto', async () => {
  const { handler, whatsapp, store } = armar();
  store.contactos[PACIENTE] = { etiquetas: ['Registrado'] };
  const conUno = `521${PACIENTE.slice(2)}`; // 5215511111111 → 521 + 10 dígitos
  await handler(reqPost(payload([mensaje(conUno, 'hola')])), resFalso());
  assert.equal(whatsapp.enviados[0].para, conUno); // se contesta al wa_id tal cual lo mandó Meta
  assert.match(whatsapp.enviados[0].cuerpo, /Su mensaje fue recibido/);
  assert.deepEqual(Object.keys(store.contactos), [PACIENTE]); // pero se guarda bajo la llave normalizada
  // el doctor también puede venir con el 1
  const doctorConUno = `521${DOCTOR.slice(2)}`;
  await handler(reqPost(payload([mensaje(doctorConUno, 'estado')])), resFalso());
  assert.match(whatsapp.enviados[1].cuerpo, /Vacaciones: desactivadas/);
});

test('el paciente pide baja: se confirma una vez y luego sólo se contesta en urgencias', async () => {
  const { handler, whatsapp, store, avanzar } = armar();
  store.contactos[PACIENTE] = { etiquetas: ['Registrado'] };
  await handler(reqPost(payload([mensaje(PACIENTE, 'ya no me mande mensajes')])), resFalso());
  assert.equal(whatsapp.enviados.length, 1);
  assert.match(whatsapp.enviados[0].cuerpo, /No le enviaré más mensajes automáticos/);
  assert.equal(store.contactos[PACIENTE].silencio, true);
  avanzar(2 * 60 * 60 * 1000);
  await handler(reqPost(payload([mensaje(PACIENTE, 'hola')])), resFalso());
  assert.equal(whatsapp.enviados.length, 1);
  await handler(reqPost(payload([mensaje(PACIENTE, 'se cayó y no responde')])), resFalso());
  assert.equal(whatsapp.enviados.length, 3); // aviso al doctor + respuesta al paciente
  assert.equal(store.logs.at(-2).enviado, false);
  await handler(reqPost(payload([mensaje(DOCTOR, `alta ${PACIENTE}`)])), resFalso());
  assert.equal(store.contactos[PACIENTE].silencio, false);
});

test('mensaje con más de 23 h no se contesta (ya no hay ventana de texto libre)', async () => {
  const { handler, whatsapp, store } = armar({ ahora: '2026-09-09T16:00:00Z' });
  await handler(reqPost(payload([mensaje(PACIENTE, 'hola')])), resFalso()); // el mensaje es del 7, el reloj va en el 9
  assert.equal(whatsapp.enviados.length, 0);
  assert.equal(store.logs[0].enviado, false);
});

test('statuses fallidos se registran sin romper nada', async () => {
  const { handler, whatsapp } = armar();
  const res = resFalso();
  await handler(reqPost(payload([], { statuses: [{ id: 'wamid.x', status: 'failed', recipient_id: PACIENTE, errors: [{ code: 131047, title: 'Re-engagement message' }] }] })), res);
  assert.equal(res.codigo, 200);
  assert.equal(whatsapp.enviados.length, 0);
});
