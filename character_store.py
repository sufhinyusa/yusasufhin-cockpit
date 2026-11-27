# -*- coding: utf-8 -*-
"""
character_store.py — Higgsfield Soul-ID Tarzı Kalıcı Karakter Tutarlılık Kasası
================================================================================
Aynı karakteri (yüz, saç, kıyafet, seed ve portre referans görseli) birden fazla
video sahnesinde, farklı mekanlarda ve farklı I2V/VACE/FLUX.2 işlerinde tutarlı
biçimde yeniden kullanmak için kalıcı yerel (+ opsiyonel R2) depo.

Güvenlik:
  * Tüm kimlikler sıkı slug/regex doğrulamasından geçer (path traversal yok).
  * Portre görselleri yalnızca doğrulanmış PNG/JPEG baytlarıyla MEDIA_DIR altına yazılır.
  * JSON yazımları atomiktir (`os.replace`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Fabrika.CharacterStore")

_CHAR_LOCK = threading.Lock()
CHARACTERS_FILENAME = "characters.json"
R2_CHARACTERS_KEY = "state/characters.json"
CHAR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,47}$")
MAX_CHARACTERS = 100


def _slugify_char_id(name: str) -> str:
    temiz = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "").strip()).strip("_")
    if len(temiz) < 2:
        temiz = f"char_{secrets.token_hex(4)}"
    return temiz[:48]


def validate_char_id(char_id: str) -> str:
    cid = str(char_id or "").strip()
    if not CHAR_ID_RE.match(cid):
        raise ValueError("Geçersiz karakter kimliği (yalnız harf, rakam, '_' ve '-' kullanılabilir).")
    return cid


def _detect_image_ext(raw: bytes) -> Optional[str]:
    if len(raw) >= 8 and raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(raw) >= 3 and raw[:3] == b"\xff\xd8\xff":
        return "jpg"
    return None


class CharacterStore:
    """Kalıcı karakter profili (character_bible + locked seed + referans portre) yöneticisi."""

    def __init__(self, data_dir: Path, media_dir: Path):
        self.data_dir = Path(data_dir)
        self.media_dir = Path(media_dir)
        self.store_file = self.data_dir / CHARACTERS_FILENAME

    def _sync_from_r2(self) -> None:
        if self.store_file.is_file():
            return
        try:
            import cloud_storage

            if cloud_storage.is_configured():
                cloud_storage.ensure_local(self.store_file, key=R2_CHARACTERS_KEY)
        except Exception:
            pass

    def _load_unlocked(self) -> List[Dict[str, Any]]:
        self._sync_from_r2()
        if not self.store_file.is_file():
            return []
        try:
            raw = json.loads(self.store_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("characters"), list):
                return [c for c in raw["characters"] if isinstance(c, dict)]
            if isinstance(raw, list):
                return [c for c in raw if isinstance(c, dict)]
        except (OSError, ValueError) as exc:
            logger.warning("[CharacterStore] characters.json okunamadı: %s", exc)
        return []

    def _push_r2_async(self, local_path: Path, r2_key: str, content_type: str) -> None:
        """R2 ağ yazımını kilidin dışında arka planda yapar; API'yi bloklamaz."""
        def _worker() -> None:
            try:
                import cloud_storage

                if cloud_storage.is_configured() and local_path.is_file():
                    cloud_storage.put_file(local_path, key=r2_key, content_type=content_type)
            except Exception as exc:
                logger.debug("[CharacterStore] R2 arka plan yüklemesi atlandı (%s): %s", r2_key, exc)

        threading.Thread(target=_worker, daemon=True, name="CharR2Sync").start()

    def _save_unlocked(self, chars: List[Dict[str, Any]]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.store_file.with_name(
            f".{self.store_file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        tmp.write_text(
            json.dumps({"characters": chars[:MAX_CHARACTERS], "updated_at": time.time()}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.store_file)
        self._push_r2_async(self.store_file, R2_CHARACTERS_KEY, "application/json")

    def _enrich(self, item: Dict[str, Any]) -> Dict[str, Any]:
        rec = dict(item)
        fname = str(rec.get("reference_image_file") or "").strip()
        if fname and "/" not in fname and "\\" not in fname:
            local_img = self.media_dir / fname
            if not local_img.is_file():
                try:
                    import cloud_storage

                    if cloud_storage.is_configured():
                        cloud_storage.ensure_local(local_img, key=f"media/{fname}")
                except Exception:
                    pass
            rec["has_reference_image"] = local_img.is_file()
            rec["reference_image_url"] = (
                f"/api/media/file?path={urllib.parse.quote(fname, safe='')}"
                if local_img.is_file()
                else None
            )
        else:
            rec["has_reference_image"] = False
            rec["reference_image_url"] = None
        return rec

    def list_characters(self) -> List[Dict[str, Any]]:
        with _CHAR_LOCK:
            return [self._enrich(c) for c in self._load_unlocked()]

    def get_character(self, char_id: str) -> Optional[Dict[str, Any]]:
        cid = str(char_id or "").strip()
        if not cid:
            return None
        with _CHAR_LOCK:
            for c in self._load_unlocked():
                if str(c.get("id") or "") == cid:
                    return self._enrich(c)
        return None

    def get_reference_image_bytes(self, char_id: str) -> Optional[bytes]:
        char = self.get_character(char_id)
        if not char:
            return None
        fname = str(char.get("reference_image_file") or "").strip()
        if not fname or "/" in fname or "\\" in fname:
            return None
        path = self.media_dir / fname
        if not path.is_file():
            return None
        try:
            return path.read_bytes()
        except OSError:
            return None

    def upsert_character(
        self,
        *,
        name: str,
        character_bible: str,
        char_id: Optional[str] = None,
        style_preset: str = "cinematic_realism",
        seed: Optional[int] = None,
        tags: Optional[List[str]] = None,
        image_bytes: Optional[bytes] = None,
        created_by: str = "owner",
    ) -> Dict[str, Any]:
        clean_name = str(name or "").strip()[:80]
        clean_bible = str(character_bible or "").strip()[:600]
        if len(clean_name) < 2:
            raise ValueError("Karakter adı en az 2 karakter olmalıdır.")
        if len(clean_bible) < 6:
            raise ValueError("Karakter tanımı (yüz, saç, kıyafet vb.) en az 6 karakter olmalıdır.")

        cid = validate_char_id(char_id) if char_id else _slugify_char_id(clean_name)
        try:
            if seed is not None and str(seed).strip() != "":
                locked_seed = int(seed)
            else:
                digest = hashlib.sha256(f"{cid}:{clean_bible}".encode("utf-8")).digest()
                locked_seed = 100000 + (int.from_bytes(digest[:4], "big") % 899999)
        except (TypeError, ValueError):
            locked_seed = 424242

        clean_tags = [str(t).strip()[:30] for t in (tags or []) if str(t).strip()][:12]

        saved_fname: Optional[str] = None
        if image_bytes is not None:
            ext = _detect_image_ext(image_bytes)
            if ext is None:
                raise ValueError("Karakter referans görseli geçerli PNG veya JPEG olmalıdır.")
            self.media_dir.mkdir(parents=True, exist_ok=True)
            saved_fname = f"char_{cid}.{ext}"
            img_path = self.media_dir / saved_fname
            tmp_img = self.media_dir / f".{saved_fname}.{os.getpid()}.part"
            tmp_img.write_bytes(image_bytes)
            os.replace(tmp_img, img_path)
            # Eski farklı uzantılı dosyayı temizle
            other_ext = "jpg" if ext == "png" else "png"
            (self.media_dir / f"char_{cid}.{other_ext}").unlink(missing_ok=True)
            self._push_r2_async(
                img_path, f"media/{saved_fname}",
                "image/png" if ext == "png" else "image/jpeg",
            )

        now = time.time()
        with _CHAR_LOCK:
            chars = self._load_unlocked()
            existing = next((c for c in chars if c.get("id") == cid), None)
            ref_file = saved_fname or (existing.get("reference_image_file") if existing else None)
            record: Dict[str, Any] = {
                "id": cid,
                "name": clean_name,
                "character_bible": clean_bible,
                "style_preset": str(style_preset or "cinematic_realism")[:48],
                "seed": locked_seed,
                "tags": clean_tags,
                "reference_image_file": ref_file,
                "created_by": str(created_by or "owner")[:64],
                "created_at": float(existing.get("created_at", now)) if existing else now,
                "updated_at": now,
            }
            if existing is not None:
                chars = [record if c.get("id") == cid else c for c in chars]
            else:
                chars.insert(0, record)
            self._save_unlocked(chars)
            return self._enrich(record)

    def delete_character(self, char_id: str) -> bool:
        cid = validate_char_id(char_id)
        with _CHAR_LOCK:
            chars = self._load_unlocked()
            target = next((c for c in chars if c.get("id") == cid), None)
            if target is None:
                return False
            new_chars = [c for c in chars if c.get("id") != cid]
            self._save_unlocked(new_chars)
            fname = str(target.get("reference_image_file") or "").strip()
            if fname and "/" not in fname and "\\" not in fname:
                (self.media_dir / fname).unlink(missing_ok=True)
            return True
