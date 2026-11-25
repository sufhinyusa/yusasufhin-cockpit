# -*- coding: utf-8 -*-
"""
api_waterfall.py — Çoklu Hesap API Anahtar Şelalesi (Waterfall & Circuit Breaker)
=================================================================================
Birden fazla hesaptaki API anahtarlarını (`GEMINI_API_KEY`, `GEMINI_API_KEY_1`..`_20`,
`GEMINI_API_KEYS`, yönetici panelinden kaydedilen çoklu anahtarlar vb.) sırayla dener:
  - `HTTP 403` (leaked / permission_denied / API_KEY_INVALID) veya `HTTP 401`:
      Anahtar parmak iziyle (SHA-256) 24 saat devre dışı bırakılır, sıradaki hesaba geçilir.
  - `HTTP 429` (kota / rate limit / RESOURCE_EXHAUSTED):
      Anahtar 15 dakika soğumaya alınır, anında sıradaki hesaba geçilir.
  - `5xx` / ağ zaman aşımı:
      Kısa soğumaya alınır ve sıradaki hesap denenir.

Güvenlik: Ham API anahtarları ASLA loglara, hata mesajlarına veya API yanıtlarına yazılmaz;
yalnızca güvenli etiketler (`GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `panel#1`) raporlanır.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

logger = logging.getLogger("Fabrika.ApiWaterfall")

T = TypeVar("T")

MAX_INDEXED_KEYS = 25
LEAKED_TTL_SEC = 24 * 3600.0
QUOTA_TTL_SEC = 15 * 60.0
TRANSIENT_TTL_SEC = 120.0

_HEALTH_LOCK = threading.Lock()
# fingerprint -> {"state": "leaked"|"invalid"|"quota"|"transient", "until": float, "reason": str, "updated_at": float}
_KEY_HEALTH: Dict[str, Dict[str, Any]] = {}


class WaterfallProviderError(RuntimeError):
    """Şelaledeki tek bir anahtar çağrısında oluşan HTTP/API hatası."""

    def __init__(self, status_code: Optional[int], message: str):
        super().__init__(message)
        self.status_code = status_code
        self.raw_message = message


def key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(str(api_key or "").encode("utf-8")).hexdigest()[:16]


def split_multi_keys(raw: Any) -> List[str]:
    """Tek anahtar, virgüllü/satır sonlu liste veya JSON dizisinden temiz anahtarları çıkarır."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        items = [str(x).strip().strip('"').strip("'") for x in raw]
    else:
        s = str(raw).strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    items = [str(x).strip().strip('"').strip("'") for x in parsed]
                else:
                    items = [s]
            except ValueError:
                items = re.split(r"[\r\n,;]+", s)
        else:
            items = re.split(r"[\r\n,;]+", s)
    out: List[str] = []
    for item in items:
        clean = item.strip().strip('"').strip("'")
        if clean and clean not in out:
            out.append(clean)
    return out


def classify_api_error(status_code: Optional[int], message: str) -> Tuple[str, float, str]:
    """Hata kodunu ve mesajını şelale aksiyonuna dönüştürür."""
    low = str(message or "").lower()
    if "leaked" in low or "reported as leaked" in low:
        return "leaked", LEAKED_TTL_SEC, "403 sızdırılmış anahtar (atlandı)"
    if status_code in (401, 403) or "api_key_invalid" in low or "permission_denied" in low or "unauthorized" in low or "invalid api key" in low:
        return "invalid", LEAKED_TTL_SEC, f"HTTP {status_code or 403} yetkisiz/geçersiz (atlandı)"
    if status_code == 429 or "resource_exhausted" in low or "quota" in low or "rate limit" in low or "too many requests" in low:
        return "quota", QUOTA_TTL_SEC, "429 kota/hız sınırı (soğumada)"
    if status_code == 400 and ("api key" in low or "key not valid" in low):
        return "invalid", LEAKED_TTL_SEC, "400 geçersiz anahtar (atlandı)"
    return "transient", TRANSIENT_TTL_SEC, f"HTTP {status_code or 'hata'} geçici hata"


def mark_key_failure(api_key: str, status_code: Optional[int], message: str) -> Tuple[str, str]:
    state, ttl, short_reason = classify_api_error(status_code, message)
    fp = key_fingerprint(api_key)
    now = time.time()
    with _HEALTH_LOCK:
        _KEY_HEALTH[fp] = {
            "state": state,
            "until": now + ttl,
            "reason": short_reason,
            "updated_at": now,
        }
    return state, short_reason


def mark_key_success(api_key: str) -> None:
    fp = key_fingerprint(api_key)
    with _HEALTH_LOCK:
        _KEY_HEALTH.pop(fp, None)


def get_key_health(api_key: str) -> Tuple[bool, str, str]:
    """(kullanilabilir_mi, durum_kodu, kisa_aciklama) döner."""
    fp = key_fingerprint(api_key)
    now = time.time()
    with _HEALTH_LOCK:
        rec = _KEY_HEALTH.get(fp)
        if not rec:
            return True, "healthy", "Hazır"
        if now >= float(rec.get("until", 0.0)):
            _KEY_HEALTH.pop(fp, None)
            return True, "healthy", "Hazır"
        return False, str(rec.get("state") or "cooldown"), str(rec.get("reason") or "Soğumada")


def reset_all_health() -> int:
    with _HEALTH_LOCK:
        n = len(_KEY_HEALTH)
        _KEY_HEALTH.clear()
        return n


def _load_panel_pool(data_dir: Optional[Path], prefix: str) -> List[Tuple[str, str]]:
    if data_dir is None:
        return []
    yol = Path(data_dir) / ".music_secrets.json"
    if not yol.is_file():
        return []
    try:
        raw = json.loads(yol.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return []
    except (OSError, ValueError):
        return []
    vals = split_multi_keys(raw.get(prefix))
    return [(f"panel#{i + 1}", val) for i, val in enumerate(vals)]


def collect_provider_keys(
    prefix: str,
    *,
    data_dir: Optional[Path] = None,
    base_get_env: Optional[Callable[[str], Optional[str]]] = None,
) -> List[Tuple[str, str]]:
    """Sağlayıcı için tüm hesap anahtarlarını deterministik sırada tekilleştirerek toplar.

    Öncelik sırası:
      1. Yönetici panelinden kaydedilmiş çoklu anahtarlar (`.music_secrets.json`)
      2. `<PREFIX>`, `<PREFIX>_1` .. `<PREFIX>_25`, `<PREFIX>S` (base_get_env üzerinden)
      3. `os.environ` içindeki diğer `<PREFIX>_*` anahtarları
    """
    seen_vals: set = set()
    out: List[Tuple[str, str]] = []

    def _add(label: str, raw_val: Any) -> None:
        vals = split_multi_keys(raw_val)
        for idx, val in enumerate(vals):
            if val in seen_vals:
                continue
            seen_vals.add(val)
            lbl = label if len(vals) == 1 else f"{label}#{idx + 1}"
            out.append((lbl, val))

    # 1. Panelden kaydedilen anahtarlar
    for lbl, val in _load_panel_pool(data_dir, prefix):
        _add(lbl, val)

    # 2. Standart env / .env sırası (GEMINI_API_KEY, GEMINI_API_KEY_1.._25, GEMINI_API_KEYS)
    getter = base_get_env if base_get_env is not None else os.environ.get
    ordered_names = [prefix] + [f"{prefix}_{i}" for i in range(1, MAX_INDEXED_KEYS + 1)] + [f"{prefix}S"]
    for name in ordered_names:
        val = getter(name)
        if val:
            _add(name, val)

    # 3. os.environ içinde farklı son ekle tanımlanmış ek anahtarlar (ör. GEMINI_API_KEY_YEDEK)
    if base_get_env is None:
        up_pref = prefix.upper()
        extra_names = sorted(
            k for k in os.environ.keys()
            if k.upper().startswith(up_pref + "_") and k not in ordered_names
        )
        for name in extra_names:
            val = os.environ.get(name)
            if val:
                _add(name, val)

    return out


def summarize_waterfall(
    prefix: str,
    *,
    data_dir: Optional[Path] = None,
    base_get_env: Optional[Callable[[str], Optional[str]]] = None,
) -> Dict[str, Any]:
    """Ham anahtarları ifşa etmeden şelale sağlığını özetler."""
    entries = collect_provider_keys(prefix, data_dir=data_dir, base_get_env=base_get_env)
    slots: List[Dict[str, Any]] = []
    healthy = 0
    leaked = 0
    cooldown = 0
    for label, key in entries:
        ok, state, reason = get_key_health(key)
        if ok:
            healthy += 1
        elif state in ("leaked", "invalid"):
            leaked += 1
        else:
            cooldown += 1
        slots.append({"label": label, "status": state, "reason": reason})
    return {
        "prefix": prefix,
        "total_keys": len(entries),
        "healthy_keys": healthy,
        "leaked_or_invalid_keys": leaked,
        "cooldown_keys": cooldown,
        "slots": slots,
    }


def execute_key_waterfall(
    prefix: str,
    call_fn: Callable[[str], T],
    *,
    data_dir: Optional[Path] = None,
    base_get_env: Optional[Callable[[str], Optional[str]]] = None,
    retry_cooldown_if_all_blocked: bool = False,
) -> Tuple[T, str, List[str]]:
    """Tüm hesap anahtarlarını şelale düzeninde dener; ilk çalışan anahtarın sonucunu döner.

    Dönen değer: `(sonuc, kullanilan_etiket, deneme_izi)`
    """
    entries = collect_provider_keys(prefix, data_dir=data_dir, base_get_env=base_get_env)
    if not entries:
        raise PermissionError(f"{prefix} bulunamadı. Ortam değişkeni veya panelden en az bir anahtar ekleyin.")

    trace: List[str] = []
    healthy_batch: List[Tuple[str, str]] = []
    cooldown_batch: List[Tuple[str, str]] = []

    for label, key in entries:
        ok, state, reason = get_key_health(key)
        if ok:
            healthy_batch.append((label, key))
        elif state in ("leaked", "invalid"):
            trace.append(f"{label}: {reason}")
        else:
            trace.append(f"{label}: {reason}")
            if retry_cooldown_if_all_blocked:
                cooldown_batch.append((label, key))

    candidates = healthy_batch + (cooldown_batch if not healthy_batch else [])
    if not candidates:
        raise RuntimeError(
            f"{prefix} şelalesindeki {len(entries)} anahtarın tamamı engelli/sızdırılmış veya soğumada: "
            + " · ".join(trace[:6])
        )

    last_err = ""
    for label, key in candidates:
        try:
            res = call_fn(key)
            mark_key_success(key)
            trace.append(f"{label}: ✅ başarılı")
            return res, label, trace
        except WaterfallProviderError as exc:
            _, short_reason = mark_key_failure(key, exc.status_code, exc.raw_message)
            last_err = exc.raw_message
            trace.append(f"{label}: {short_reason}")
            logger.warning("[ApiWaterfall] %s başarısız (%s) → sıradaki hesaba geçiliyor.", label, short_reason)
        except Exception as exc:
            msg = str(exc)
            _, short_reason = mark_key_failure(key, None, msg)
            last_err = msg
            trace.append(f"{label}: {short_reason}")
            logger.warning("[ApiWaterfall] %s hata (%s) → sıradaki hesaba geçiliyor.", label, short_reason)

    ozet = " · ".join(trace[-6:])
    raise RuntimeError(f"{prefix} şelalesi ({len(entries)} hesap) başarısız: {ozet} | Son yanıt: {last_err[:180]}")
