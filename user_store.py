# -*- coding: utf-8 -*-
"""
user_store.py — Çoklu Yönetici & Kullanıcı Yetkilendirme Deposu (PBKDF2-SHA256)
================================================================================
- Kurucu (owner) PIN/parola girişi her zaman süper yönetici (`role="admin"`,
  `is_owner=True`, tüm bölümler: `fabrika`, `video`, `muzik`) olarak çalışır.
- Ek yönetici (`admin`) ve standart kullanıcı (`user`) hesapları PBKDF2-HMAC-SHA256
  (310.000 tur + kullanıcı başına 16 bayt rastgele tuz) ile saklanır.
- Dosya izinleri atomik `0600` ile korunur; Cloudflare R2 yapılandırılmışsa
  (`cloud_storage`) yeniden başlatmalara karşı `state/users.json` olarak yedeklenir.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

USERS_FILENAME = ".users.json"
R2_USERS_KEY = "state/users.json"
PBKDF2_ITERATIONS = 310_000
VALID_ROLES = ("admin", "user")
VALID_SECTIONS = ("fabrika", "video", "muzik")
RESERVED_USERNAMES = {"owner", "root", "system", "superadmin", "kurucu"}
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MAX_USERS = 100

_STORE_LOCK = threading.Lock()


def normalize_username(raw: Any) -> str:
    return str(raw or "").strip().lower()


def normalize_sections(sections: Optional[Iterable[Any]], role: str) -> List[str]:
    if role == "admin":
        return list(VALID_SECTIONS)
    if not sections:
        return []
    out: List[str] = []
    for item in sections:
        s = str(item or "").strip().lower()
        if s in VALID_SECTIONS and s not in out:
            out.append(s)
    return out


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """PBKDF2-HMAC-SHA256 (310k iterasyon) ile güvenli parola özeti üretir."""
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Parola en az 8 karakter olmalıdır.")
    s = salt if salt is not None else os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), s, PBKDF2_ITERATIONS)
    s_b64 = base64.b64encode(s).decode("ascii")
    dk_b64 = base64.b64encode(dk).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${s_b64}${dk_b64}"


def verify_password(password: str, encoded: str) -> bool:
    """Sabit zamanlı (constant-time) parola doğrulaması yapar."""
    try:
        alg, iters_s, s_b64, dk_b64 = str(encoded or "").split("$", 3)
        if alg != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        if iters < 100_000:
            return False
        salt = base64.b64decode(s_b64.encode("ascii"))
        expected = base64.b64decode(dk_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iters)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _public_user_view(rec: Dict[str, Any]) -> Dict[str, Any]:
    role = rec.get("role") if rec.get("role") in VALID_ROLES else "user"
    return {
        "username": rec.get("username", ""),
        "display_name": rec.get("display_name") or rec.get("username", ""),
        "role": role,
        "sections": normalize_sections(rec.get("sections"), role),
        "active": bool(rec.get("active", True)),
        "token_version": int(rec.get("token_version", 1)),
        "created_at": rec.get("created_at"),
        "created_by": rec.get("created_by") or "owner",
        "is_owner": False,
    }


def owner_identity() -> Dict[str, Any]:
    return {
        "username": "owner",
        "display_name": "Yusuf Şahin",
        "role": "admin",
        "sections": list(VALID_SECTIONS),
        "active": True,
        "token_version": 1,
        "is_owner": True,
    }


class UserStore:
    """Atomik 0600 JSON + isteğe bağlı Cloudflare R2 + env bootstrap kullanıcı deposu."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / USERS_FILENAME

    def _sync_from_r2_if_missing(self) -> None:
        if self.path.is_file():
            return
        try:
            import cloud_storage

            if cloud_storage.is_configured():
                if cloud_storage.ensure_local(self.path, key=R2_USERS_KEY):
                    try:
                        os.chmod(self.path, 0o600)
                    except OSError:
                        pass
        except Exception:
            pass

    def _bootstrap_from_env_if_empty(self, users: Dict[str, Dict[str, Any]]) -> bool:
        """FABRIKA_USERS_BOOTSTRAP ortam değişkeninden başlangıç kullanıcılarını yükler (opsiyonel)."""
        if users:
            return False
        raw = (os.environ.get("FABRIKA_USERS_BOOTSTRAP") or "").strip()
        if not raw:
            return False
        try:
            items = json.loads(raw)
        except ValueError:
            return False
        if not isinstance(items, list):
            return False
        changed = False
        now = time.time()
        for item in items[:MAX_USERS]:
            if not isinstance(item, dict):
                continue
            uname = normalize_username(item.get("username"))
            pwd = str(item.get("password") or "")
            role = str(item.get("role") or "user").strip().lower()
            if not USERNAME_RE.match(uname) or uname in RESERVED_USERNAMES or role not in VALID_ROLES or len(pwd) < 8:
                continue
            secs = normalize_sections(item.get("sections"), role)
            if not secs:
                secs = ["video"]
            users[uname] = {
                "username": uname,
                "display_name": str(item.get("display_name") or uname).strip()[:60] or uname,
                "role": role,
                "sections": secs,
                "password_hash": hash_password(pwd),
                "active": True,
                "token_version": 1,
                "created_at": now,
                "created_by": "env_bootstrap",
            }
            changed = True
        return changed

    def _load_unlocked(self) -> Dict[str, Dict[str, Any]]:
        self._sync_from_r2_if_missing()
        users: Dict[str, Dict[str, Any]] = {}
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("users"), dict):
                    users = {
                        normalize_username(k): v
                        for k, v in raw["users"].items()
                        if isinstance(v, dict)
                    }
            except (OSError, ValueError):
                users = {}
        if self._bootstrap_from_env_if_empty(users):
            self._save_unlocked(users)
        return users

    def _save_unlocked(self, users: Dict[str, Dict[str, Any]]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.data_dir / f".users.{os.getpid()}.{threading.get_ident()}.tmp"
        payload = json.dumps({"version": 1, "users": users}, ensure_ascii=False, indent=2) + "\n"
        tmp.write_text(payload, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        os.chmod(self.path, 0o600)
        try:
            import cloud_storage

            if cloud_storage.is_configured():
                cloud_storage.put_file(self.path, key=R2_USERS_KEY, content_type="application/json")
        except Exception:
            pass

    def list_users(self, section_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        sec = str(section_filter or "").strip().lower()
        with _STORE_LOCK:
            users = self._load_unlocked()
            out = [_public_user_view(u) for u in users.values()]
        out.sort(key=lambda r: (0 if r["role"] == "admin" else 1, r["username"]))
        if sec in VALID_SECTIONS:
            out = [u for u in out if u["role"] == "admin" or sec in u["sections"]]
        return out

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        uname = normalize_username(username)
        if uname == "owner":
            return owner_identity()
        with _STORE_LOCK:
            users = self._load_unlocked()
            rec = users.get(uname)
            return _public_user_view(rec) if rec else None

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Kullanıcı adı + parola doğrulaması. Zamanlama sızıntısına karşı sabit işlem yapar."""
        uname = normalize_username(username)
        pwd = str(password or "")
        with _STORE_LOCK:
            users = self._load_unlocked()
            rec = users.get(uname)
        if not rec or not rec.get("active", True):
            # Var olmayan kullanıcıyı zamanlama ile belli etmemek için sahte PBKDF2
            hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), b"fabrika-dummy-salt", 120_000)
            return None
        if not verify_password(pwd, str(rec.get("password_hash") or "")):
            return None
        return _public_user_view(rec)

    def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str = "",
        role: str = "user",
        sections: Optional[Iterable[str]] = None,
        created_by: str = "owner",
    ) -> Dict[str, Any]:
        uname = normalize_username(username)
        if not USERNAME_RE.match(uname):
            raise ValueError("Kullanıcı adı 3–32 karakter (a-z, 0-9, ., _, -) olmalıdır.")
        if uname in RESERVED_USERNAMES:
            raise ValueError("Bu kullanıcı adı sistem tarafından ayrılmıştır.")
        clean_role = str(role or "user").strip().lower()
        if clean_role not in VALID_ROLES:
            raise ValueError("Rol yalnızca 'admin' veya 'user' olabilir.")
        clean_sections = normalize_sections(sections, clean_role)
        if clean_role == "user" and not clean_sections:
            raise ValueError("Kullanıcı için en az bir bölüm yetkisi (Fabrika, Video veya Müzik) seçilmelidir.")
        pwd_hash = hash_password(password)
        dname = re.sub(r"[\r\n]+", " ", str(display_name or uname)).strip()[:60] or uname

        with _STORE_LOCK:
            users = self._load_unlocked()
            if uname in users:
                raise ValueError(f"'{uname}' kullanıcı adı zaten kayıtlı.")
            if len(users) >= MAX_USERS:
                raise ValueError(f"Maksimum kullanıcı sınırına ({MAX_USERS}) ulaşıldı.")
            users[uname] = {
                "username": uname,
                "display_name": dname,
                "role": clean_role,
                "sections": clean_sections,
                "password_hash": pwd_hash,
                "active": True,
                "token_version": 1,
                "created_at": time.time(),
                "created_by": str(created_by or "owner")[:40],
            }
            self._save_unlocked(users)
            return _public_user_view(users[uname])

    def update_user(
        self,
        username: str,
        *,
        actor_username: str,
        display_name: Optional[str] = None,
        role: Optional[str] = None,
        sections: Optional[Iterable[str]] = None,
        active: Optional[bool] = None,
        password: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """Kullanıcıyı günceller; oturumları feshedilmesi gerekiyorsa ikinci değer True döner."""
        uname = normalize_username(username)
        if uname == "owner":
            raise ValueError("Kurucu (owner) hesabı değiştirilemez.")
        actor = normalize_username(actor_username)

        with _STORE_LOCK:
            users = self._load_unlocked()
            rec = users.get(uname)
            if not rec:
                raise KeyError(f"'{uname}' kullanıcısı bulunamadı.")

            revoke = False
            if active is not None:
                if not active and uname == actor:
                    raise ValueError("Kendi yönetici hesabınızı devre dışı bırakamazsınız.")
                if bool(active) != bool(rec.get("active", True)):
                    rec["active"] = bool(active)
                    if not active:
                        revoke = True

            if role is not None:
                new_role = str(role).strip().lower()
                if new_role not in VALID_ROLES:
                    raise ValueError("Geçersiz rol.")
                if uname == actor and new_role != "admin":
                    raise ValueError("Kendi yönetici yetkinizi düşüremezsiniz.")
                if new_role != rec.get("role"):
                    rec["role"] = new_role
                    revoke = True

            cur_role = str(rec.get("role") or "user")
            if sections is not None or role is not None:
                new_secs = normalize_sections(sections if sections is not None else rec.get("sections"), cur_role)
                if cur_role == "user" and not new_secs:
                    raise ValueError("Kullanıcı için en az bir bölüm yetkisi kalmalıdır.")
                if new_secs != rec.get("sections"):
                    rec["sections"] = new_secs
                    revoke = True

            if display_name is not None:
                dname = re.sub(r"[\r\n]+", " ", str(display_name)).strip()[:60]
                if dname:
                    rec["display_name"] = dname

            if password:
                rec["password_hash"] = hash_password(password)
                revoke = True

            if revoke:
                rec["token_version"] = int(rec.get("token_version", 1)) + 1

            users[uname] = rec
            self._save_unlocked(users)
            return _public_user_view(rec), revoke

    def delete_user(self, username: str, *, actor_username: str) -> bool:
        uname = normalize_username(username)
        if uname == "owner":
            raise ValueError("Kurucu (owner) hesabı silinemez.")
        if uname == normalize_username(actor_username):
            raise ValueError("Kendi aktif hesabınızı silemezsiniz.")
        with _STORE_LOCK:
            users = self._load_unlocked()
            if uname not in users:
                raise KeyError(f"'{uname}' kullanıcısı bulunamadı.")
            del users[uname]
            self._save_unlocked(users)
            return True
