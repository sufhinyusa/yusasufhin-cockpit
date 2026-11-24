# -*- coding: utf-8 -*-
"""
contact_notifier.py — ys@yusasufhin.com Doğrudan E-posta + Mac Köprü Rölesi + Telegram
======================================================================================
Kural 1 (Dürüstlük): Hiçbir kanal gerçekten iletmediyse `email_sent=True` dönmez.

Desteklenen e-posta teslim kanalları (öncelik sırasıyla):
  1. Bulut HTTPS 443 (Resend API — Render ücretsiz planda 7/24 çalışır):
       RESEND_API_KEY, CONTACT_FROM_EMAIL, CONTACT_TO_EMAIL (varsayılan: ys@yusasufhin.com)
  2. Doğrudan SMTP (VPS / Oracle ARM veya yerel ortam):
       SMTP_HOST (varsayılan: smtp.gmail.com), SMTP_PORT (587), SMTP_USER (ys@yusasufhin.com), SMTP_PASS
  3. Mac Port-443 Köprüsü Üzerinden TLS 587 Gmail Rölesi + Çevrimdışı Kuyruk:
       Render ücretsiz planda port 587 engelli olduğu için mesajı HTTPS 443 köprüsüyle
       Mac'e iletir; Mac doğrudan `smtp.gmail.com:587` üzerinden `ys@yusasufhin.com`
       kutusuna gerçek e-postayı düşürür (Mac kapalıysa kuyruğa alır, açılınca otomatik yollar).
  4. Anlık Telegram Bildirimi (HTTPS 443):
       TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import threading
import time
import urllib.parse
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger("Fabrika.ContactNotifier")

DEFAULT_TO_EMAIL = "ys@yusasufhin.com"
DEFAULT_FROM_EMAIL = "yusasufhin.com <onboarding@resend.dev>"
MAIL_SECRETS_FILENAME = ".mail_secrets.json"
_MAIL_LOCK = threading.Lock()


def load_saved_mail_config(data_dir: Path) -> Dict[str, str]:
    """Yönetici panelinden kaydedilmiş (0600 izinli) e-posta ayarlarını okur."""
    yol = data_dir / MAIL_SECRETS_FILENAME
    if not yol.is_file():
        return {}
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
        if isinstance(veri, dict):
            return {str(k): str(v).strip() for k, v in veri.items() if v is not None and str(v).strip()}
    except (OSError, ValueError):
        return {}
    return {}


def save_mail_config(data_dir: Path, updates: Dict[str, Optional[str]]) -> Dict[str, str]:
    """E-posta kimlik bilgilerini 0600 dosya izniyle atomik olarak kaydeder."""
    izinli = {
        "CONTACT_TO_EMAIL",
        "CONTACT_FROM_EMAIL",
        "RESEND_API_KEY",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASS",
    }
    with _MAIL_LOCK:
        mevcut = load_saved_mail_config(data_dir)
        for k, v in updates.items():
            if k not in izinli:
                continue
            if v is None:
                continue
            temiz = str(v).strip()
            if temiz == "__CLEAR__":
                mevcut.pop(k, None)
            elif temiz:
                mevcut[k] = temiz

        data_dir.mkdir(parents=True, exist_ok=True)
        hedef = data_dir / MAIL_SECRETS_FILENAME
        gecici = data_dir / f".mail_secrets.{os.getpid()}.{threading.get_ident()}.tmp"
        gecici.write_text(json.dumps(mevcut, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(gecici, 0o600)
        os.replace(gecici, hedef)
        os.chmod(hedef, 0o600)
        return dict(mevcut)


def make_layered_env_getter(
    data_dir: Path,
    base_get_env: Callable[[str], Optional[str]],
) -> Callable[[str], Optional[str]]:
    """Önce kayıtlı yönetici e-posta ayarlarını, yoksa ortam/.env değerlerini okur."""
    saved = load_saved_mail_config(data_dir)

    def _get(key: str) -> Optional[str]:
        if key in saved and saved[key]:
            return saved[key]
        return base_get_env(key)

    return _get


def notifier_status(
    get_env: Callable[[str], Optional[str]],
    *,
    mac_online: bool = False,
    mac_smtp_ready: bool = False,
) -> Dict[str, Any]:
    """Aktif e-posta, Mac rölesi ve Telegram bildirim kanallarını dürüstçe raporlar."""
    to_email = (get_env("CONTACT_TO_EMAIL") or DEFAULT_TO_EMAIL).strip()
    has_resend = bool(get_env("RESEND_API_KEY"))
    smtp_pass = get_env("SMTP_PASS")
    smtp_host = get_env("SMTP_HOST") or ("smtp.gmail.com" if smtp_pass else None)
    smtp_user = get_env("SMTP_USER") or (to_email if smtp_pass else None)
    has_smtp = bool(smtp_host and smtp_user and smtp_pass)
    has_tg = bool(get_env("TELEGRAM_BOT_TOKEN") and get_env("TELEGRAM_CHAT_ID"))
    has_mac_relay = bool(mac_smtp_ready or (mac_online and has_smtp))

    if has_resend:
        email_method = "resend"
    elif has_mac_relay:
        email_method = "mac_gmail_relay"
    elif has_smtp:
        email_method = "smtp_or_mac_queue"
    else:
        email_method = "none"

    email_ready = has_resend or has_smtp or has_mac_relay
    if email_ready:
        hint = f"✅ Canlı e-posta aktif (hedef: {to_email} • kanal: {email_method})."
    else:
        hint = (
            f"⚠️ {to_email} adresine doğrudan mail düşmesi için aşağıdaki kutuya "
            "16 haneli Google Uygulama Şifrenizi (Mac köprüsü üzerinden doğrudan Gmail TLS 587 ile gönderir) "
            "veya RESEND_API_KEY anahtarınızı girip Kaydet'e basın."
        )

    return {
        "to_email": to_email,
        "smtp_user": smtp_user or to_email,
        "smtp_host": smtp_host or "smtp.gmail.com",
        "email_configured": email_ready,
        "resend_configured": has_resend,
        "smtp_configured": has_smtp,
        "mac_relay_ready": has_mac_relay,
        "mac_online": mac_online,
        "email_method": email_method,
        "telegram_configured": has_tg,
        "any_live_channel": email_ready or has_tg,
        "hint": hint,
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


def send_via_smtp_direct(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    to_email: str,
    name: str,
    sender_email: str,
    message: str,
) -> Dict[str, Any]:
    """Doğrudan TLS/SSL SMTP üzerinden gerçek e-posta gönderir (Mac köprüsü ve VPS uyumlu)."""
    clean_pass = password.replace(" ", "") if "gmail" in host.lower() else password
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
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=12, context=ctx) as server:
            server.login(user, clean_pass)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=12) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(user, clean_pass)
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
    mac_relay_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Resend -> Doğrudan SMTP -> Mac Port-443 Gmail Rölesi (+ Çevrimdışı Kuyruk) + Telegram ile gönderir."""
    to_email = (get_env("CONTACT_TO_EMAIL") or DEFAULT_TO_EMAIL).strip()
    from_email = (get_env("CONTACT_FROM_EMAIL") or DEFAULT_FROM_EMAIL).strip()

    email_sent = False
    email_queued_mac = False
    email_provider: Optional[str] = None
    email_error: Optional[str] = None

    resend_key = get_env("RESEND_API_KEY")
    smtp_pass = get_env("SMTP_PASS")
    smtp_host = get_env("SMTP_HOST") or ("smtp.gmail.com" if smtp_pass else None)
    smtp_user = get_env("SMTP_USER") or (to_email if smtp_pass else None)
    smtp_port = int(get_env("SMTP_PORT") or 587)

    # 1. Bulut HTTPS 443 (Resend)
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

    # 2. Doğrudan SMTP (VPS/yerel ortamda çalışır; Render ücretsiz planda zaman aşımına düşerse 3. adıma geçer)
    if not email_sent and smtp_host and smtp_user and smtp_pass and not os.environ.get("RENDER"):
        try:
            r = send_via_smtp_direct(
                host=smtp_host,
                port=smtp_port,
                user=smtp_user,
                password=smtp_pass,
                to_email=to_email,
                name=name,
                sender_email=sender_email,
                message=message,
            )
            email_sent = bool(r["ok"])
            email_provider = "smtp"
            email_error = None
        except Exception as exc:
            email_provider = "smtp"
            email_error = f"{type(exc).__name__}: {str(exc)[:140]}"
            logger.warning("[Contact] Doğrudan SMTP hatası, Mac rölesi denenecek: %s", email_error)

    # 3. Mac Port-443 Köprüsü Üzerinden TLS 587 Rölesi (Render port 587 engelini yasal HTTPS 443 ile aşar)
    telegram_sent = False
    telegram_error: Optional[str] = None
    if not email_sent and mac_relay_fn is not None:
        relay_payload: Dict[str, Any] = {
            "to_email": to_email,
            "name": name,
            "sender_email": sender_email,
            "message": message,
            "smtp_host": smtp_host or "smtp.gmail.com",
            "smtp_port": smtp_port,
            "smtp_user": smtp_user or to_email,
            "smtp_pass": smtp_pass or "",
        }
        try:
            mr = mac_relay_fn(relay_payload)
            if mr.get("email_sent"):
                email_sent = True
                email_provider = str(mr.get("provider") or "mac_gmail_relay")
                email_error = None
            elif mr.get("queued_for_mac"):
                email_queued_mac = True
                email_provider = "mac_queue"
                email_error = mr.get("error")
            elif mr.get("error"):
                email_error = str(mr.get("error"))
            if mr.get("telegram_sent"):
                telegram_sent = True
        except Exception as exc:
            logger.warning("[Contact] Mac röle çağrısı hatası: %s", exc)

    # 4. Bulut Telegram Bildirimi (henüz Mac üzerinden gitmediyse)
    tg_tok = get_env("TELEGRAM_BOT_TOKEN")
    tg_chat = get_env("TELEGRAM_CHAT_ID")
    if not telegram_sent and tg_tok and tg_chat:
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
    elif email_queued_mac and telegram_sent:
        channel = "mac_email_queue+telegram"
    elif email_queued_mac:
        channel = "mac_email_queue"
    elif telegram_sent:
        channel = "telegram"
    else:
        channel = "inbox_only"

    return {
        "email_sent": email_sent,
        "email_queued_mac": email_queued_mac,
        "email_provider": email_provider,
        "email_error": email_error,
        "telegram_sent": telegram_sent,
        "telegram_error": telegram_error,
        "delivery_channel": channel,
        "to_email": to_email,
        "mailto_fallback_url": build_mailto_fallback(to_email, name, sender_email, message),
        "timestamp": time.time(),
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
