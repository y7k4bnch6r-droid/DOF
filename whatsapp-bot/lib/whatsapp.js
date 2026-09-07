'use strict';

const axios = require('axios');

/**
 * Cliente mínimo de la WhatsApp Cloud API (Graph API).
 * Lanza error con detalle de Meta si la llamada falla; quien lo usa decide
 * si eso debe tumbar la petición (no: ver index.js).
 */
function crearCliente({ token, phoneNumberId, versionGraph, timeoutMs = 10000 }) {
  const http = axios.create({
    baseURL: `https://graph.facebook.com/${versionGraph}/${phoneNumberId}`,
    timeout: timeoutMs,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  });

  async function enviar(payload) {
    try {
      const { data } = await http.post('/messages', { messaging_product: 'whatsapp', recipient_type: 'individual', ...payload });
      return data;
    } catch (err) {
      const detalle = err.response && err.response.data && err.response.data.error;
      const e = new Error(`Meta respondió ${err.response ? err.response.status : 'sin respuesta'}: ${detalle ? `${detalle.code} ${detalle.message}` : err.message}`);
      e.codigoMeta = detalle && detalle.code;
      e.status = err.response && err.response.status;
      throw e;
    }
  }

  return {
    /** Texto libre; sólo funciona dentro de la ventana de 24 h del contacto. */
    enviarTexto(para, cuerpo) {
      return enviar({ to: para, type: 'text', text: { body: cuerpo, preview_url: false } });
    },
    /** Plantilla aprobada (sirve fuera de la ventana de 24 h). parametros: strings del cuerpo. */
    enviarPlantilla(para, nombre, parametros = [], idioma = 'es_MX') {
      const components = parametros.length
        ? [{ type: 'body', parameters: parametros.map((p) => ({ type: 'text', text: p })) }]
        : [];
      return enviar({ to: para, type: 'template', template: { name: nombre, language: { code: idioma }, components } });
    },
  };
}

// 131047: fuera de la ventana de 24 h (hay que usar plantilla).
const CODIGO_FUERA_DE_VENTANA = 131047;

module.exports = { crearCliente, CODIGO_FUERA_DE_VENTANA };
