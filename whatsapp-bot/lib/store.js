'use strict';

/**
 * Adaptador de Firestore. Colecciones:
 *   contactos/{wa_id}   {nombre, etiquetas[], preferencia, ultimaRespuesta{clase,en}, actualizado}
 *   config/vacacion     {on, inicio, fin, regreso}
 *   procesados/{msgId}  {en, expiraEn}   ← idempotencia (Meta reintenta webhooks)
 *   logs/{auto}         {waId, msgId, tipo, clase, en, expiraEn, texto?}
 * Activa TTL en "expiraEn" para procesados y logs (ver README).
 */

const ID_SEGURO = /^[A-Za-z0-9_.:=+-]{1,900}$/;

function crearStore(db, { FieldValue }) {
  function ref(coleccion, id) {
    if (!ID_SEGURO.test(id)) throw new Error(`Id no válido para ${coleccion}: ${JSON.stringify(id)}`);
    return db.collection(coleccion).doc(id);
  }

  return {
    /** true si es la primera vez que vemos este mensaje; false si ya se procesó. */
    async marcarProcesado(msgId, expiraEn) {
      try {
        await ref('procesados', msgId).create({ en: FieldValue.serverTimestamp(), expiraEn });
        return true;
      } catch (err) {
        if (err.code === 6 || /already exists/i.test(err.message || '')) return false; // ALREADY_EXISTS
        throw err;
      }
    },

    async leerContacto(waId) {
      const snap = await ref('contactos', waId).get();
      return snap.exists ? snap.data() : null;
    },

    async guardarContacto(waId, cambios) {
      await ref('contactos', waId).set({ ...cambios, actualizado: FieldValue.serverTimestamp() }, { merge: true });
    },

    async leerVacacion() {
      const snap = await db.doc('config/vacacion').get();
      return snap.exists ? snap.data() : null;
    },

    async guardarVacacion(datos) {
      await db.doc('config/vacacion').set({ ...datos, actualizado: FieldValue.serverTimestamp() });
    },

    async registrarLog(entrada) {
      await db.collection('logs').add({ ...entrada, en: FieldValue.serverTimestamp() });
    },
  };
}

module.exports = { crearStore };
