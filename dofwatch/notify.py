"""Envio del digest por correo o webhook. Los secretos salen del entorno."""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

import requests

log = logging.getLogger(__name__)


class NotifyError(RuntimeError):
    pass


def _recipients(cfg) -> list[str]:
    del_entorno = os.environ.get("DOFWATCH_EMAIL_TO", "")
    if del_entorno.strip():
        return [d.strip() for d in del_entorno.split(",") if d.strip()]
    return list(cfg["notify"].get("email_to") or [])


def send_email(cfg, subject: str, markdown: str, html_body: str | None = None) -> bool:
    """Envia el digest por SMTP. Devuelve False si falta configuracion."""
    host = os.environ.get("SMTP_HOST")
    destinatarios = _recipients(cfg)
    if not host or not destinatarios:
        log.info("Correo omitido: falta SMTP_HOST o destinatarios")
        return False

    puerto = int(os.environ.get("SMTP_PORT", "587"))
    usuario = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    remitente = (
        os.environ.get("SMTP_FROM")
        or cfg["notify"].get("email_from")
        or usuario
        or f"dofwatch@{host}"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = remitente
    msg["To"] = ", ".join(destinatarios)
    msg.set_content(markdown)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    contexto = ssl.create_default_context()
    try:
        if puerto == 465:
            with smtplib.SMTP_SSL(host, puerto, context=contexto, timeout=60) as s:
                if usuario:
                    s.login(usuario, password or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, puerto, timeout=60) as s:
                s.ehlo()
                if os.environ.get("SMTP_STARTTLS", "1") != "0":
                    s.starttls(context=contexto)
                    s.ehlo()
                if usuario:
                    s.login(usuario, password or "")
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise NotifyError(f"No se pudo enviar el correo: {exc}") from exc

    log.info("Digest enviado a %s", ", ".join(destinatarios))
    return True


def post_webhook(cfg, text: str) -> bool:
    """Publica un resumen corto en un webhook (Slack, Teams o generico)."""
    url = os.environ.get("DOFWATCH_WEBHOOK_URL")
    if not url:
        log.info("Webhook omitido: falta DOFWATCH_WEBHOOK_URL")
        return False
    try:
        r = requests.post(
            url,
            data=json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        raise NotifyError(f"Webhook falló: {exc}") from exc
    return True
