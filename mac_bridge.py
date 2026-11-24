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
        self._pending_commands: List[Dict[str, Any]] = []
        self._completed_replies: Dict[str, Dict[str, Any]] = {}
        self._waiters: Dict[str, threading.Event] = {}

    def reset(self) -> None:
        """Test izolasyonu için köprü durumunu sıfırlar."""
        with self._lock:
            self._last_seen = 0.0
            self._mac_stats.clear()
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
    ) -> List[Dict[str, Any]]:
        """Mac köprüsünün kalp atışını ve yanıtlarını alır, bekleyen komutları teslim eder."""
        now = time.time()
        with self._lock:
            self._last_seen = now
            if isinstance(stats, dict) and stats:
                self._mac_stats = {
                    "cpu": stats.get("cpu"),
                    "ram": stats.get("ram"),
                    "status": stats.get("status") or "online",
                    "link_pool_count": stats.get("link_pool_count"),
                    "rea_score": stats.get("rea_score"),
                    "named_tunnel_active": bool(stats.get("named_tunnel_active", False)),
                    "custom_domain": stats.get("custom_domain") or "https://yusasufhin.com",
                    "updated_at": now,
                }

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

    def get_status(self) -> Dict[str, Any]:
        """Köprü ve Mac telemetrisini dürüstçe döner (çevrimdışıysa cpu/ram None)."""
        now = time.time()
        with self._lock:
            online = self._last_seen > 0.0 and (now - self._last_seen) <= self.online_ttl_sec
            last_seen_ago = round(now - self._last_seen, 1) if self._last_seen > 0.0 else None
            stats = dict(self._mac_stats) if online else None
            pending = len(self._pending_commands)

        return {
            "online": online,
            "status": "online" if online else "offline",
            "last_seen_sec_ago": last_seen_ago,
            "pending_commands": pending,
            "cpu": stats.get("cpu") if stats else None,
            "ram": stats.get("ram") if stats else None,
            "stats": stats,
            "message": (
                "Mac Fabrika köprüsü canlı (Port 443 HTTPS)."
                if online
                else "Mac Fabrika şu an çevrimdışı. Bilgisayarınızda Fabrika açıldığında otomatik bağlanır."
            ),
        }

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
                "status": "replied",
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
