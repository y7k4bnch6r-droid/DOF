'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { verificarFirma, firmar } = require('../lib/firma');

const SECRETO = 'app-secret-de-prueba';
const cuerpo = Buffer.from('{"object":"whatsapp_business_account","entry":[]}');

test('acepta la firma correcta', () => {
  assert.equal(verificarFirma(cuerpo, firmar(cuerpo, SECRETO), SECRETO), true);
});

test('rechaza firma alterada, secreto distinto, encabezado ausente o mal formado', () => {
  const buena = firmar(cuerpo, SECRETO);
  assert.equal(verificarFirma(cuerpo, buena.replace(/.$/, (c) => (c === '0' ? '1' : '0')), SECRETO), false);
  assert.equal(verificarFirma(cuerpo, buena, 'otro-secreto'), false);
  assert.equal(verificarFirma(cuerpo, undefined, SECRETO), false);
  assert.equal(verificarFirma(cuerpo, 'sha1=abc', SECRETO), false);
  assert.equal(verificarFirma(cuerpo, 'sha256=', SECRETO), false);
  assert.equal(verificarFirma(cuerpo, 'sha256=zz', SECRETO), false);
  assert.equal(verificarFirma(Buffer.from('{}'), buena, SECRETO), false);
  assert.equal(verificarFirma(cuerpo, buena, ''), false);
});
