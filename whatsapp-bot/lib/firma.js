'use strict';

const crypto = require('node:crypto');

/**
 * Meta firma cada POST con HMAC-SHA256 del cuerpo crudo usando el App Secret
 * y lo manda en el encabezado X-Hub-Signature-256 como "sha256=<hex>".
 * Sin esto, cualquiera que conozca la URL puede hacer que el bot mande
 * mensajes (y pague por ellos) o activar los comandos del doctor.
 */
function verificarFirma(cuerpoCrudo, encabezado, appSecret) {
  if (!cuerpoCrudo || !encabezado || !appSecret) return false;
  const [algoritmo, hex] = String(encabezado).split('=');
  if (algoritmo !== 'sha256' || !hex) return false;
  const esperado = crypto.createHmac('sha256', appSecret).update(cuerpoCrudo).digest();
  let recibido;
  try {
    recibido = Buffer.from(hex, 'hex');
  } catch {
    return false;
  }
  if (recibido.length !== esperado.length) return false;
  return crypto.timingSafeEqual(recibido, esperado);
}

function firmar(cuerpoCrudo, appSecret) {
  return `sha256=${crypto.createHmac('sha256', appSecret).update(cuerpoCrudo).digest('hex')}`;
}

module.exports = { verificarFirma, firmar };
