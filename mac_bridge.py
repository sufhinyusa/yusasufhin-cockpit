# -*- coding: utf-8 -*-
"""
mac_bridge.py — Mac Fabrika Port-443 HTTPS Çift Yönlü Köprü Merkezi
====================================================================
Mac'teki `Core/gateway/vpn_port443_bridge.py` ile birebir uyumlu protokol:
  * POST /api/bridge/poll    (Header: X-Fabrika-Bridge-Secret)
  * GET  /api/bridge/status  (Bearer oturum tokeni)
  * POST /api/bridge/command (Bearer oturum tokeni)

Dürüstlük (Kural 1): Mac son 25 sn içinde kalp atışı göndermediyse
`online=False`, `cpu=None`, `ram=None` döner — asla sahte çevrimiçi göstermez.
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Sequence


DEFAULT_ONLINE_TTL_SEC = 25.0
MAX_PENDING_COMMANDS = 40
MAX_STORED_REPLIES = 100


class MacBridgeHub:
    """Bulut kokpiti ile yerel Mac Fabrika arasındaki iş parçacığı-güvenli köprü."""

    def __init__(self, online_ttl_sec: float = DEFAULT_ONLINE_TTL_SEC) -> None:
        self._lock = threading.Lock()
        self.online_ttl_sec = float(online_ttl_sec)
        self._last_seen: float = 0.0
        self._mac_stats: Dict[str, Any] = {}
        self._desktop_state: Dict[str, Any] = {}
        self._last_broadcast_sig: Any = None
        self._desktop_dirty: bool = False
        self._pending_commands: List[Dict[str, Any]] = []
        self._completed_replies: Dict[str, Dict[str, Any]] = {}
        self._waiters: Dict[str, threading.Event] = {}

    def reset(self) -> None:
        """Test izolasyonu için köprü durumunu sıfırlar."""
        with self._lock:
            self._last_seen = 0.0
            self._mac_stats.clear()
            self._desktop_state.clear()
            self._last_broadcast_sig = None
            self._desktop_dirty = False
            self._pending_commands.clear()
            self._completed_replies.clear()
            for ev in self._waiters.values():
                ev.set()
            self._waiters.clear()

    @staticmethod
    def verify_secret(provided: Optional[str], valid_secrets: Sequence[str]) -> bool:
        """Sabit zamanlı sır doğrulaması; geçerli sır tanımlı değilse her zaman False."""
        temiz = (provided or "").strip()
        if not temiz:
            return False
        adaylar = [str(s).strip() for s in valid_secrets if s and str(s).strip()]
        if not adaylar:
            return False
        saglanan_b = temiz.encode("utf-8")
        return any(hmac.compare_digest(saglanan_b, s.encode("utf-8")) for s in adaylar)

    def is_online(self, now: Optional[float] = None) -> bool:
        t = time.time() if now is None else float(now)
        with self._lock:
            return self._last_seen > 0.0 and (t - self._last_seen) <= self.online_ttl_sec

    def handle_poll(
        self,
        stats: Optional[Dict[str, Any]] = None,
        replies: Optional[List[Dict[str, Any]]] = None,
        desktop_state: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Mac köprüsünün kalp atışını, masaüstü durumunu ve yanıtlarını alır, bekleyen görevleri teslim eder."""
        now = time.time()
        with self._lock:
            self._last_seen = now
            if isinstance(stats, dict) and stats:
                self._mac_stats = {
                    "cpu": stats.get("cpu"),
                    "ram": stats.get("ram"),
                    "status": stats.get("status") or "online",
                    "desktop_app_open": bool(stats.get("desktop_app_open", False)),
                    "smtp_ready": bool(stats.get("smtp_ready", False)),
                    "telegram_ready": bool(stats.get("telegram_ready", False)),
                    "link_pool_count": stats.get("link_pool_count"),
                    "rea_score": stats.get("rea_score"),
                    "named_tunnel_active": bool(stats.get("named_tunnel_active", False)),
                    "custom_domain": stats.get("custom_domain") or "https://yusasufhin.com",
                    "updated_at": now,
                }

            if isinstance(desktop_state, dict) and desktop_state:
                self._desktop_state = dict(desktop_state)
                self._desktop_state["synced_at"] = now
                sig = (
                    bool(desktop_state.get("desktop_app_open")),
                    desktop_state.get("rev"),
                    desktop_state.get("chat_seq"),
                    desktop_state.get("log_seq"),
                    desktop_state.get("is_processing"),
                    desktop_state.get("is_speaking"),
                    desktop_state.get("center_state"),
                )
                if sig != self._last_broadcast_sig:
                    self._last_broadcast_sig = sig
                    self._desktop_dirty = True

            if isinstance(replies, list):
                for rep in replies:
                    if not isinstance(rep, dict):
                        continue
                    cid = str(rep.get("id") or "").strip()
                    if not cid:
                        continue
                    kayit = {
                        "id": cid,
                        "sender": str(rep.get("sender") or "Mac Fabrika"),
                        "text": str(rep.get("text") or ""),
                        "action": rep.get("action"),
                        "media": rep.get("media"),
                        "accepted_desktop": bool(rep.get("accepted_desktop", False)),
                        "email_sent": bool(rep.get("email_sent", False)),
                        "telegram_sent": bool(rep.get("telegram_sent", False)),
                        "provider": rep.get("provider"),
                        "error": rep.get("error"),
                        "timestamp": now,
                    }
                    self._completed_replies[cid] = kayit
                    ev = self._waiters.get(cid)
                    if ev is not None:
                        ev.set()

                if len(self._completed_replies) > MAX_STORED_REPLIES:
                    eski_anahtarlar = sorted(
                        self._completed_replies,
                        key=lambda k: float(self._completed_replies[k].get("timestamp", 0.0)),
                    )[: len(self._completed_replies) - MAX_STORED_REPLIES]
                    for k in eski_anahtarlar:
                        self._completed_replies.pop(k, None)

            tasks = self._pending_commands[:10]
            del self._pending_commands[:10]
            return tasks

    def get_desktop_state(self) -> Optional[Dict[str, Any]]:
        """Son canlı masaüstü anlık görüntüsünü döner (çevrimdışıysa None)."""
        if not self.is_online():
            return None
        with self._lock:
            return dict(self._desktop_state) if self._desktop_state else None

    def pop_dirty_desktop_state(self) -> Optional[Dict[str, Any]]:
        """Değişmiş masaüstü durumunu bir kez tüketir (WebSocket yayını için)."""
        with self._lock:
            if not self._desktop_dirty or not self._desktop_state:
                return None
            self._desktop_dirty = False
            return dict(self._desktop_state)

    def get_status(self) -> Dict[str, Any]:
        """Köprü ve Mac telemetrisini dürüstçe döner (çevrimdışıysa cpu/ram None)."""
        now = time.time()
        with self._lock:
            online = self._last_seen > 0.0 and (now - self._last_seen) <= self.online_ttl_sec
            last_seen_ago = round(now - self._last_seen, 1) if self._last_seen > 0.0 else None
            stats = dict(self._mac_stats) if online else None
            desktop_state = dict(self._desktop_state) if (online and self._desktop_state) else None
            desktop_open = bool(desktop_state.get("desktop_app_open")) if desktop_state else False
            pending = len(self._pending_commands)

        return {
            "online": online,
            "desktop_app_open": desktop_open,
            "status": "online" if online else "offline",
            "last_seen_sec_ago": last_seen_ago,
            "pending_commands": pending,
            "cpu": stats.get("cpu") if stats else None,
            "ram": stats.get("ram") if stats else None,
            "stats": stats,
            "desktop_state": desktop_state,
            "message": (
                "Mac Masaüstü Fabrika canlı ve birebir senkron (Port 443)."
                if (online and desktop_open)
                else (
                    "Mac Fabrika köprüsü canlı (masaüstü pencere bekleniyor)."
                    if online
                    else "Mac Fabrika şu an çevrimdışı. Bilgisayarınızda Fabrika açıldığında otomatik bağlanır."
                )
            ),
        }

    def relay_contact_email(
        self,
        payload: Dict[str, Any],
        *,
        allow_offline_queue: bool = False,
        timeout_sec: float = 12.0,
    ) -> Dict[str, Any]:
        """İletişim e-postasını canlı Mac köprüsüne iletir; Mac çevrimdışı ve SMTP ayarlıysa kuyruğa alır."""
        cmd_id = f"mail_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        task = {
            "id": cmd_id,
            "kind": "contact_email",
            "payload": dict(payload),
            "createdAt": int(time.time() * 1000),
        }
        if not self.is_online():
            if allow_offline_queue and payload.get("smtp_pass"):
                with self._lock:
                    if len(self._pending_commands) >= MAX_PENDING_COMMANDS:
                        self._pending_commands.pop(0)
                    self._pending_commands.append(task)
                return {
                    "ok": True,
                    "email_sent": False,
                    "queued_for_mac": True,
                    "provider": "mac_queue",
                    "error": None,
                }
            return {"ok": False, "email_sent": False, "queued_for_mac": False, "error": "mac_offline"}

        ev = threading.Event()
        with self._lock:
            if len(self._pending_commands) >= MAX_PENDING_COMMANDS:
                self._pending_commands.pop(0)
            self._pending_commands.append(task)
            self._waiters[cmd_id] = ev

        geldi = ev.wait(timeout=max(2.0, float(timeout_sec)))
        with self._lock:
            self._waiters.pop(cmd_id, None)
            yanit = self._completed_replies.pop(cmd_id, None)

        if geldi and yanit:
            return {
                "ok": bool(yanit.get("email_sent") or yanit.get("telegram_sent")),
                "email_sent": bool(yanit.get("email_sent")),
                "telegram_sent": bool(yanit.get("telegram_sent")),
                "queued_for_mac": False,
                "provider": yanit.get("provider") or "mac_gmail_relay",
                "error": yanit.get("error"),
            }
        return {
            "ok": False,
            "email_sent": False,
            "queued_for_mac": bool(payload.get("smtp_pass")),
            "error": "Mac köprüsü zaman aşımı; mesaj kuyrukta bekliyor.",
        }

    def push_mail_config_to_mac(self, smtp_user: str, smtp_pass: str, smtp_host: str = "smtp.gmail.com", smtp_port: int = 587) -> bool:
        """Yöneticinin girdiği SMTP ayarını canlı Mac köprüsündeki Persona/.env içine güvenli aktarır."""
        if not self.is_online() or not smtp_pass:
            return False
        cmd_id = f"mcfg_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        with self._lock:
            if len(self._pending_commands) >= MAX_PENDING_COMMANDS:
                self._pending_commands.pop(0)
            self._pending_commands.append({
                "id": cmd_id,
                "kind": "save_mail_config",
                "payload": {
                    "smtp_host": smtp_host,
                    "smtp_port": int(smtp_port),
                    "smtp_user": smtp_user,
                    "smtp_pass": smtp_pass,
                },
                "createdAt": int(time.time() * 1000),
            })
        return True

    def enqueue_ui_action(self, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Uzaktan UI eylemini (sağ panel, log/XAI, söz kes, soru kartı vb.) Mac kuyruğuna ekler."""
        temiz = str(action or "").strip()
        if not temiz:
            return {"ok": False, "mac_online": self.is_online(), "status": "empty"}
        if not self.is_online():
            return {"ok": False, "mac_online": False, "status": "mac_offline"}
        cmd_id = f"act_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        with self._lock:
            if len(self._pending_commands) >= MAX_PENDING_COMMANDS:
                self._pending_commands.pop(0)
            self._pending_commands.append({
                "id": cmd_id,
                "kind": "ui_action",
                "action": temiz,
                "payload": payload if isinstance(payload, dict) else {},
                "createdAt": int(time.time() * 1000),
            })
        return {"ok": True, "mac_online": True, "status": "queued", "id": cmd_id, "action": temiz}

    def enqueue_and_wait(self, text: str, timeout_sec: float = 14.0) -> Dict[str, Any]:
        """Mac çevrimiçiyse komutu iletir ve gerçek yanıtı bekler; kapalıysa bekletmeden bildirir."""
        temiz = str(text or "").strip()
        if not temiz:
            return {
                "ok": False,
                "mac_online": self.is_online(),
                "sender": "Sistem",
                "text": "Komut metni boş olamaz.",
                "status": "empty",
            }

        if not self.is_online():
            return {
                "ok": False,
                "mac_online": False,
                "sender": "Mac Köprüsü",
                "text": "Mac Fabrika şu an çevrimdışı. Bilgisayarınızda Fabrika açık olduğunda komutlarınız doğrudan Mac üzerinde çalışır.",
                "status": "mac_offline",
            }

        cmd_id = f"cmd_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        ev = threading.Event()
        with self._lock:
            if len(self._pending_commands) >= MAX_PENDING_COMMANDS:
                self._pending_commands.pop(0)
            self._pending_commands.append({
                "id": cmd_id,
                "text": temiz,
                "createdAt": int(time.time() * 1000),
            })
            self._waiters[cmd_id] = ev

        geldi = ev.wait(timeout=max(1.0, float(timeout_sec)))
        with self._lock:
            self._waiters.pop(cmd_id, None)
            yanit = self._completed_replies.pop(cmd_id, None)

        if geldi and yanit:
            return {
                "ok": True,
                "mac_online": True,
                "status": "accepted_desktop" if yanit.get("accepted_desktop") else "replied",
                "accepted_desktop": bool(yanit.get("accepted_desktop", False)),
                "id": cmd_id,
                "sender": yanit.get("sender") or "Mac Fabrika",
                "text": yanit.get("text") or "",
                "action": yanit.get("action"),
                "media": yanit.get("media"),
            }

        return {
            "ok": False,
            "mac_online": self.is_online(),
            "status": "timeout",
            "id": cmd_id,
            "sender": "Mac Köprüsü",
            "text": "Komut Mac Fabrika kuyruğuna iletildi ancak zaman aşımı içinde yanıt dönmedi.",
        }


bridge_hub = MacBridgeHub()
