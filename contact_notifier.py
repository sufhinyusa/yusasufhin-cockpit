# -*- coding: utf-8 -*-
"""
contact_notifier.py — Gerçek E-posta (Resend / SMTP) + Telegram İletişim Bildirimi
==================================================================================
Kural 1 (Dürüstlük): Hiçbir kanal yapılandırılmamışsa e-posta gitmiş gibi
davranmaz; `email_sent` ve `telegram_sent` alanlarını gerçek sonuçla döner.

Desteklenen ortam değişkenleri (öncelik sırasıyla):
  1. E-posta (HTTP 443 — Render dostu):
       RESEND_API_KEY        (ör. re_...)
       CONTACT_FROM_EMAIL    (opsiyonel, varsayılan: onboarding@resend.dev)
       CONTACT_TO_EMAIL      (opsiyonel, varsayılan: ys@yusasufhin.com)
  2. E-posta (SMTP — Gmail/Outlook/Brevo vb.):
       SMTP_HOST             (ör. smtp.gmail.com veya smtp-mail.outlook.com)
       SMTP_PORT             (varsayılan: 587)
       SMTP_USER
       SMTP_PASS
       CONTACT_TO_EMAIL
  3. Anlık Telegram Bildirimi (HTTP 443 — ücretsiz):
       TELEGRAM_BOT_TOKEN
       TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import json
import logging
import smtplib
import ssl
import urllib.parse
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger("Fabrika.ContactNotifier")

DEFAULT_TO_EMAIL = "ys@yusasufhin.com"
DEFAULT_FROM_EMAIL = "yusasufhin.com <onboarding@resend.dev>"


def notifier_status(get_env: Callable[[str], Optional[str]]) -> Dict[str, Any]:
    """Aktif e-posta ve Telegram bildirim kanallarını dürüstçe raporlar."""
    to_email = (get_env("CONTACT_TO_EMAIL") or DEFAULT_TO_EMAIL).strip()
    has_resend = bool(get_env("RESEND_API_KEY"))
    has_smtp = bool(get_env("SMTP_HOST") and get_env("SMTP_USER") and get_env("SMTP_PASS"))
    has_tg = bool(get_env("TELEGRAM_BOT_TOKEN") and get_env("TELEGRAM_CHAT_ID"))
    email_method = "resend" if has_resend else ("smtp" if has_smtp else "none")
    return {
        "to_email": to_email,
        "email_configured": has_resend or has_smtp,
        "email_method": email_method,
        "telegram_configured": has_tg,
        "any_live_channel": has_resend or has_smtp or has_tg,
        "hint": (
            f"Canlı bildirim etkin (hedef: {to_email})."
            if (has_resend or has_smtp or has_tg)
            else (
                f"{to_email} adresine canlı mail için Render Environment'a RESEND_API_KEY "
                "(HTTPS 443 — Render ücretsiz planda SMTP 25/465/587 kapalıdır) ve/veya "
                "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID ekleyin. "
                "(Oracle/VPS üzerinde SMTP_HOST+SMTP_USER+SMTP_PASS da çalışır.)"
            )
        ),
    }


def _send_via_resend(
    api_key: str,
    from_email: str,
    to_email: str,
    name: str,
    sender_email: str,
    message: str,
) -> Dict[str, Any]:
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_email,
            "to": [to_email],
            "reply_to": sender_email,
            "subject": f"[yusasufhin.com] Yeni İletişim Mesajı — {name}",
            "text": (
                f"Web sitenizden yeni bir mesaj geldi:\n\n"
                f"Gönderen : {name}\n"
                f"E-posta  : {sender_email}\n\n"
                f"Mesaj:\n{message}\n"
            ),
        },
        timeout=15,
    )
    if resp.ok:
        return {"ok": True, "provider": "resend", "error": None}
    return {"ok": False, "provider": "resend", "error": f"HTTP {resp.status_code}: {resp.text[:160]}"}


def _send_via_smtp(
    host: str,
    port: int,
    user: str,
    password: str,
    to_email: str,
    name: str,
    sender_email: str,
    message: str,
) -> Dict[str, Any]:
    msg = EmailMessage()
    msg["Subject"] = f"[yusasufhin.com] Yeni İletişim Mesajı — {name}"
    msg["From"] = user
    msg["To"] = to_email
    msg["Reply-To"] = sender_email
    msg.set_content(
        f"Web sitenizden yeni bir mesaj geldi:\n\n"
        f"Gönderen : {name}\n"
        f"E-posta  : {sender_email}\n\n"
        f"Mesaj:\n{message}\n"
    )
    if "gmail" in host.lower():
        password = password.replace(" ", "")
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=15, context=ctx) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(user, password)
            server.send_message(msg)
    return {"ok": True, "provider": "smtp", "error": None}


def _send_via_telegram(
    bot_token: str,
    chat_id: str,
    name: str,
    sender_email: str,
    message: str,
) -> Dict[str, Any]:
    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": (
                f"📩 yusasufhin.com Yeni Mesaj\n"
                f"Ad: {name}\n"
                f"E-posta: {sender_email}\n\n"
                f"{message[:1400]}"
            ),
        },
        timeout=10,
    )
    if resp.ok:
        return {"ok": True, "error": None}
    return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:140]}"}


def build_mailto_fallback(to_email: str, name: str, sender_email: str, message: str) -> str:
    subj = f"yusasufhin.com Proje Talebi — {name}"
    body = f"Ad: {name}\nE-posta: {sender_email}\n\n{message}"
    return (
        f"mailto:{to_email}?subject={urllib.parse.quote(subj)}"
        f"&body={urllib.parse.quote(body)}"
    )


def dispatch_contact_notification(
    *,
    name: str,
    sender_email: str,
    message: str,
    get_env: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    """Yapılandırılmış gerçek kanallardan (Resend/SMTP ve Telegram) bildirim gönderir."""
    to_email = (get_env("CONTACT_TO_EMAIL") or DEFAULT_TO_EMAIL).strip()
    from_email = (get_env("CONTACT_FROM_EMAIL") or DEFAULT_FROM_EMAIL).strip()

    email_sent = False
    email_provider = None
    email_error = None

    resend_key = get_env("RESEND_API_KEY")
    smtp_host = get_env("SMTP_HOST")
    smtp_user = get_env("SMTP_USER")
    smtp_pass = get_env("SMTP_PASS")

    if resend_key:
        try:
            r = _send_via_resend(resend_key, from_email, to_email, name, sender_email, message)
            email_sent = bool(r["ok"])
            email_provider = r["provider"]
            email_error = r["error"]
        except Exception as exc:
            email_provider = "resend"
            email_error = f"{type(exc).__name__}: {str(exc)[:140]}"
            logger.warning("[Contact] Resend gönderim hatası: %s", email_error)
    elif smtp_host and smtp_user and smtp_pass:
        try:
            port = int(get_env("SMTP_PORT") or 587)
            r = _send_via_smtp(smtp_host, port, smtp_user, smtp_pass, to_email, name, sender_email, message)
            email_sent = bool(r["ok"])
            email_provider = r["provider"]
            email_error = r["error"]
        except Exception as exc:
            email_provider = "smtp"
            email_error = f"{type(exc).__name__}: {str(exc)[:140]}"
            logger.warning("[Contact] SMTP gönderim hatası: %s", email_error)

    telegram_sent = False
    telegram_error = None
    tg_tok = get_env("TELEGRAM_BOT_TOKEN")
    tg_chat = get_env("TELEGRAM_CHAT_ID")
    if tg_tok and tg_chat:
        try:
            tr = _send_via_telegram(tg_tok, tg_chat, name, sender_email, message)
            telegram_sent = bool(tr["ok"])
            telegram_error = tr["error"]
        except Exception as exc:
            telegram_error = f"{type(exc).__name__}: {str(exc)[:140]}"
            logger.warning("[Contact] Telegram bildirim hatası: %s", telegram_error)

    if email_sent and telegram_sent:
        channel = "email+telegram"
    elif email_sent:
        channel = "email"
    elif telegram_sent:
        channel = "telegram"
    else:
        channel = "inbox_only"

    return {
        "email_sent": email_sent,
        "email_provider": email_provider,
        "email_error": email_error,
        "telegram_sent": telegram_sent,
        "telegram_error": telegram_error,
        "delivery_channel": channel,
        "to_email": to_email,
        "mailto_fallback_url": build_mailto_fallback(to_email, name, sender_email, message),
    }


def read_contact_messages(data_dir: Path, limit: int = 30) -> List[Dict[str, Any]]:
    """Kaydedilmiş iletişim mesajlarını yeniden eskiye okur."""
    path = data_dir / "contact_inquiries.jsonl"
    if not path.is_file():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    out.append(rec)
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    out.reverse()
    return out[: max(1, min(limit, 100))]
