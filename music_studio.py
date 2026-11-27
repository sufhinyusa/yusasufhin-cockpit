# -*- coding: utf-8 -*-
"""
music_studio.py — Çift Katmanlı Şelaleli Çoklu Model Müzik Üretim Motoru
========================================================================
Kural 1 (Dürüstlük): Hiçbir sağlayıcı sahte ses üretmez. İlgili API anahtarı eksikse veya
yerel GPU/Mac köprüsü çevrimdışıysa eksiklik dürüstçe raporlanır.

Çift Katmanlı Şelale:
  1. Hesap Anahtarı Şelalesi (`api_waterfall`): Her sağlayıcı için `GEMINI_API_KEY`,
     `GEMINI_API_KEY_1`..`_25`, `GEMINI_API_KEYS` ve panelden eklenen tüm hesap
     anahtarlarını sırayla dener; 403 sızdırılmış/geçersiz anahtarları anında atlar,
     429 kota dolu anahtarları soğumaya alıp sonraki hesaba geçer.
  2. Çapraz Model Şelalesi (`auto_waterfall`): Seçildiğinde `lyria-3.5` →
     `lyria-3-clip-preview` → `elevenlabs-music` → `stable-audio-2` →
     `replicate-musicgen` → `local-musicgen-mac` sırasıyla ilk çalışan modeli kullanır.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from api_waterfall import (
    WaterfallProviderError,
    collect_provider_keys,
    execute_key_waterfall,
    reset_all_health,
    split_multi_keys,
    summarize_waterfall,
)

logger = logging.getLogger("Fabrika.MusicStudio")

MUSIC_SECRETS_FILENAME = ".music_secrets.json"
MUSIC_HISTORY_FILENAME = "music_history.json"
MUSIC_JOBS_STATE_FILENAME = "music_jobs_state.json"
R2_MUSIC_SECRETS_KEY = "state/music_secrets.json"
R2_MUSIC_HISTORY_KEY = "state/music_history.json"
R2_MUSIC_JOBS_KEY = "state/music_jobs_state.json"
ALLOWED_SECRET_KEYS = ("GEMINI_API_KEY", "ELEVENLABS_API_KEY", "STABILITY_API_KEY", "REPLICATE_API_TOKEN")
AUTO_WATERFALL_ORDER = (
    "lyria-3.5",
    "lyria-3-clip-preview",
    "elevenlabs-music",
    "gpu-acestep-1.5",
    "stable-audio-2",
    "replicate-musicgen",
    "gpu-musicgen",
    "local-musicgen-mac",
)
VALID_MUSIC_TASKS = ("text2music", "cover", "repaint", "extend")
SUPPORTED_VOCAL_LANGUAGES = ("tr", "en", "de", "fr", "es", "it", "ja", "ko", "zh", "ar", "ru", "unknown")
MAX_JOBS = 120

_SECRETS_LOCK = threading.Lock()
_JOBS_LOCK = threading.Lock()
_MUSIC_JOBS: Dict[str, Dict[str, Any]] = {}

MUSIC_MODELS: List[Dict[str, Any]] = [
    {
        "id": "auto_waterfall",
        "name": "⚡ Otomatik Şelale (Vokal Korumalı · Bulut → Kaggle ACE-Step 1.5)",
        "provider": "auto_waterfall",
        "env_key": None,
        "supports_vocals": True,
        "supports_lyrics": True,
        "supports_tasks": ["text2music", "cover", "repaint", "extend"],
        "max_duration_sec": 240,
        "default_duration_sec": 60,
        "format": "wav",
        "description": "Vokal/söz içeren istekleri yalnızca vokal destekli modellere yönlendirir; ücretli API yoksa ücretsiz Kaggle GPU ACE-Step 1.5 kuyruğuna düşer.",
    },
    {
        "id": "gpu-acestep-1.5",
        "name": "🚀 Kaggle/Colab Ücretsiz GPU ACE-Step 1.5 (Suno Seviyesi · Vokal + Türkçe Söz + 4 dk)",
        "provider": "gpu_queue",
        "env_key": None,
        "repo": "ACE-Step/acestep-v15-xl-turbo-diffusers",
        "license": "MIT",
        "supports_vocals": True,
        "supports_lyrics": True,
        "supports_tasks": ["text2music", "cover", "repaint", "extend"],
        "max_duration_sec": 240,
        "default_duration_sec": 60,
        "format": "wav",
        "description": "MIT lisanslı 5B flow-matching DiT (48 kHz gerçek stereo): Türkçe/çok dilli vokal, [Verse]/[Chorus] şarkı yapısı, BPM, gam, Cover/Repaint ve 4 dk'ya kadar tam şarkı (Kaggle T4 ücretsiz).",
    },
    {
        "id": "lyria-3.5",
        "name": "Google Lyria 3.5 (Tam Şarkı)",
        "provider": "google_lyria",
        "env_key": "GEMINI_API_KEY",
        "supports_vocals": True,
        "supports_lyrics": True,
        "max_duration_sec": 180,
        "default_duration_sec": 60,
        "format": "mp3",
        "description": "44.1 kHz stereo tam şarkı, nakarat/köprü yapısı, vokal ve zamanlı şarkı sözü üretimi (tüm Gemini hesapları şelalede).",
    },
    {
        "id": "lyria-3-clip-preview",
        "name": "Google Lyria 3 Clip (30 sn Klip)",
        "provider": "google_lyria",
        "env_key": "GEMINI_API_KEY",
        "supports_vocals": True,
        "supports_lyrics": True,
        "max_duration_sec": 30,
        "default_duration_sec": 30,
        "format": "mp3",
        "description": "Hızlı 30 saniyelik 44.1 kHz stereo müzik klibi (tüm Gemini hesapları şelalede).",
    },
    {
        "id": "elevenlabs-music",
        "name": "ElevenLabs Music",
        "provider": "elevenlabs",
        "env_key": "ELEVENLABS_API_KEY",
        "supports_vocals": True,
        "supports_lyrics": True,
        "max_duration_sec": 180,
        "default_duration_sec": 30,
        "format": "mp3",
        "description": "Stüdyo kalitesinde çok dilli vokal veya enstrümantal beste üretimi.",
    },
    {
        "id": "stable-audio-2",
        "name": "Stability Stable Audio 2",
        "provider": "stability",
        "env_key": "STABILITY_API_KEY",
        "supports_vocals": False,
        "supports_lyrics": False,
        "max_duration_sec": 180,
        "default_duration_sec": 30,
        "format": "mp3",
        "description": "Sinematik enstrümantal besteler, ambient ve ses tasarımı için difüzyon modeli.",
    },
    {
        "id": "replicate-musicgen",
        "name": "Meta MusicGen Stereo Large (Replicate)",
        "provider": "replicate",
        "env_key": "REPLICATE_API_TOKEN",
        "supports_vocals": False,
        "supports_lyrics": False,
        "max_duration_sec": 30,
        "default_duration_sec": 15,
        "format": "wav",
        "description": "Açık kaynak Meta MusicGen Stereo Large modeli (Replicate bulut GPU üzerinde).",
    },
    {
        "id": "gpu-musicgen",
        "name": "🎹 Kaggle/Colab Ücretsiz GPU MusicGen Stereo (Hızlı Enstrümantal · 30 sn)",
        "provider": "gpu_queue",
        "env_key": None,
        "repo": "facebook/musicgen-stereo-medium",
        "supports_vocals": False,
        "supports_lyrics": False,
        "supports_tasks": ["text2music"],
        "max_duration_sec": 30,
        "default_duration_sec": 15,
        "format": "wav",
        "description": "Meta MusicGen Stereo Medium (32 kHz gerçek stereo) Kaggle/Colab T4 GPU işçisinde yerel çalışır; yalnızca enstrümantal (vokal için ACE-Step 1.5 kullanın).",
    },
    {
        "id": "local-musicgen-mac",
        "name": "Mac Fabrika Yerel Müzik / GPU Hattı",
        "provider": "mac_bridge",
        "env_key": None,
        "supports_vocals": False,
        "supports_lyrics": False,
        "max_duration_sec": 60,
        "default_duration_sec": 20,
        "format": "wav",
        "description": "Bilgisayarınızdaki Fabrika açıkken Port-443 köprüsü üzerinden yerel müzik isteği yollar.",
    },
]

MUSIC_MODELS_BY_ID: Dict[str, Dict[str, Any]] = {m["id"]: m for m in MUSIC_MODELS}


def _sync_from_r2(local_path: Path, r2_key: str, mode: Optional[int] = None) -> None:
    if local_path.is_file():
        return
    try:
        import cloud_storage

        if cloud_storage.is_configured() and cloud_storage.ensure_local(local_path, key=r2_key):
            if mode is not None:
                try:
                    os.chmod(local_path, mode)
                except OSError:
                    pass
    except Exception:
        pass


def load_music_secrets(data_dir: Path) -> Dict[str, Any]:
    yol = Path(data_dir) / MUSIC_SECRETS_FILENAME
    _sync_from_r2(yol, R2_MUSIC_SECRETS_KEY, mode=0o600)
    if not yol.is_file():
        return {}
    try:
        raw = json.loads(yol.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {k: v for k, v in raw.items() if k in ALLOWED_SECRET_KEYS and v}
    except (OSError, ValueError):
        return {}
    return {}


def save_music_secrets(data_dir: Path, updates: Dict[str, Any], *, append: bool = False) -> Dict[str, int]:
    """Çoklu hesap müzik API anahtarlarını atomik 0600 izinle kaydeder; değerleri asla geri döndürmez."""
    with _SECRETS_LOCK:
        cur = load_music_secrets(data_dir)
        for k, v in updates.items():
            if k not in ALLOWED_SECRET_KEYS or v is None:
                continue
            if str(v).strip() == "__CLEAR__":
                cur.pop(k, None)
                continue
            new_keys = split_multi_keys(v)
            if not new_keys:
                continue
            if append:
                merged = split_multi_keys(cur.get(k))
                for nk in new_keys:
                    if nk not in merged:
                        merged.append(nk)
                cur[k] = merged if len(merged) > 1 else merged[0]
            else:
                cur[k] = new_keys if len(new_keys) > 1 else new_keys[0]

        Path(data_dir).mkdir(parents=True, exist_ok=True)
        hedef = Path(data_dir) / MUSIC_SECRETS_FILENAME
        tmp = Path(data_dir) / f".music_secrets.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, hedef)
        os.chmod(hedef, 0o600)
        try:
            import cloud_storage

            if cloud_storage.is_configured():
                cloud_storage.put_file(hedef, key=R2_MUSIC_SECRETS_KEY, content_type="application/json")
        except Exception:
            pass
        reset_all_health()
        return {k: len(split_multi_keys(cur.get(k))) for k in ALLOWED_SECRET_KEYS}


def make_music_env_getter(
    data_dir: Path,
    base_get_env: Callable[[str], Optional[str]],
) -> Callable[[str], Optional[str]]:
    saved = load_music_secrets(data_dir)

    def _get(key: str) -> Optional[str]:
        if key in saved and saved[key]:
            vals = split_multi_keys(saved[key])
            if vals:
                return vals[0]
        return base_get_env(key)

    return _get


def get_waterfall_report(
    data_dir: Path,
    base_get_env: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    """Tüm müzik sağlayıcılarının çoklu hesap şelale durumunu güvenli biçimde raporlar."""
    providers = {
        k: summarize_waterfall(k, data_dir=data_dir, base_get_env=base_get_env)
        for k in ALLOWED_SECRET_KEYS
    }
    total_all = sum(p["total_keys"] for p in providers.values())
    healthy_all = sum(p["healthy_keys"] for p in providers.values())
    return {
        "total_keys": total_all,
        "healthy_keys": healthy_all,
        "providers": providers,
    }


def list_music_models(
    get_env: Callable[[str], Optional[str]],
    *,
    mac_online: bool = False,
    gpu_online: bool = False,
    data_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Tüm müzik modellerini çoklu hesap anahtar sayısı ve şelale durumuyla listeler."""
    out: List[Dict[str, Any]] = []
    any_real_ready = False
    total_ready_keys = 0

    per_spec_rows: List[Dict[str, Any]] = []
    for spec in MUSIC_MODELS:
        if spec["id"] == "auto_waterfall":
            continue
        env_key = spec.get("env_key")
        if env_key:
            summ = summarize_waterfall(env_key, data_dir=data_dir, base_get_env=get_env)
            n_tot = summ["total_keys"]
            n_ok = summ["healthy_keys"]
            ready = n_tot > 0
            if ready:
                any_real_ready = True
                total_ready_keys = max(total_ready_keys, n_tot)
            if n_ok > 0:
                reason = f"Hazır ({n_ok}/{n_tot} hesap aktif)" if n_tot > 1 else "Hazır"
            elif n_tot > 0:
                reason = f"Şelale ({n_tot} hesap engelli/soğumada)"
            else:
                reason = f"API anahtarı eksik: {env_key}"
        elif spec.get("provider") == "gpu_queue":
            n_tot = 1 if gpu_online else 0
            n_ok = n_tot
            ready = bool(gpu_online)
            if ready:
                any_real_ready = True
                total_ready_keys = max(total_ready_keys, 1)
            reason = (
                "Kaggle/Colab GPU bağlı (Ücretsiz)"
                if ready
                else "GPU işçisi çevrimdışı — kuyruğa alınabilir"
            )
        else:
            n_tot = 1 if mac_online else 0
            n_ok = n_tot
            ready = bool(mac_online)
            if ready:
                any_real_ready = True
            reason = "Mac Fabrika bağlı" if ready else "Mac Fabrika çevrimdışı"
        per_spec_rows.append({
            **spec,
            "ready": ready,
            "key_count": n_tot,
            "healthy_key_count": n_ok,
            "status_text": reason,
        })

    auto_spec = MUSIC_MODELS_BY_ID["auto_waterfall"]
    out.append({
        **auto_spec,
        "ready": any_real_ready,
        "key_count": total_ready_keys,
        "healthy_key_count": total_ready_keys,
        "status_text": (
            f"Şelale Hazır ({sum(1 for r in per_spec_rows if r['ready'])} model)"
            if any_real_ready
            else "En az bir API anahtarı ekleyin"
        ),
    })
    out.extend(per_spec_rows)
    return out


def _compose_music_prompt(
    prompt: str,
    *,
    genre: str = "",
    mood: str = "",
    duration_sec: int = 30,
    instrumental: bool = True,
    lyrics: str = "",
    bpm: Optional[int] = None,
    key_scale: str = "",
    vocal_language: str = "tr",
) -> str:
    parts = [prompt.strip()]
    if genre:
        parts.append(f"Genre/Style: {genre.strip()}.")
    if mood:
        parts.append(f"Mood/Atmosphere: {mood.strip()}.")
    if bpm:
        parts.append(f"Tempo: {int(bpm)} BPM.")
    if key_scale.strip():
        parts.append(f"Key/Scale: {key_scale.strip()}.")
    if instrumental:
        parts.append("Purely instrumental, no vocals.")
    else:
        if vocal_language and vocal_language != "unknown":
            parts.append(f"Vocal language: {vocal_language}.")
        if lyrics.strip():
            parts.append(f"Include vocals with these lyrics:\n{lyrics.strip()[:2400]}")
    if duration_sec:
        parts.append(f"Target duration: approximately {int(duration_sec)} seconds.")
    return " ".join(parts)


def _generate_google_lyria(
    model_id: str,
    api_key: str,
    composed_prompt: str,
) -> Tuple[bytes, str, str]:
    """Google Gemini Interactions API üzerinden gerçek Lyria 3.5 / Lyria 3 Clip müzik üretir."""
    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        headers={
            "x-goog-api-key": api_key,
            "Api-Revision": "2026-05-20",
            "Content-Type": "application/json",
        },
        json={
            "model": model_id,
            "input": composed_prompt,
        },
        timeout=180,
    )
    if not resp.ok:
        txt = resp.text[:260]
        if resp.status_code == 429 and ("limit: 0" in txt.lower() or "free tier" in txt.lower()):
            raise WaterfallProviderError(
                429,
                "Google Lyria Free Tier kotası 0 (ücretli Google Billing gerektirir) — "
                "ücretsiz vokal+sözlü tam şarkı için Kaggle GPU 'gpu-acestep-1.5' kullanın.",
            )
        raise WaterfallProviderError(resp.status_code, f"Google Lyria HTTP {resp.status_code}: {txt}")
    data = resp.json()
    audio_bytes: Optional[bytes] = None
    ext = "mp3"
    lyrics_parts: List[str] = []

    steps = data.get("steps") if isinstance(data.get("steps"), list) else []
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        for block in step.get("content") or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "audio" and block.get("data"):
                audio_bytes = base64.b64decode(block["data"])
                mime = str(block.get("mime_type") or "audio/mp3").lower()
                ext = "wav" if "wav" in mime else "mp3"
            elif btype == "text" and block.get("text"):
                lyrics_parts.append(str(block["text"]))

    if audio_bytes is None and isinstance(data.get("outputs"), list):
        for block in data["outputs"]:
            if isinstance(block, dict) and block.get("type") == "audio" and block.get("data"):
                audio_bytes = base64.b64decode(block["data"])
                mime = str(block.get("mime_type") or "audio/mp3").lower()
                ext = "wav" if "wav" in mime else "mp3"

    if not audio_bytes:
        raise WaterfallProviderError(402, "Lyria yanıtında ses bloğu bulunamadı (ücretli Gemini API anahtarı gerekebilir).")
    return audio_bytes, ext, "\n".join(lyrics_parts).strip()


def _generate_elevenlabs_music(
    api_key: str,
    composed_prompt: str,
    duration_sec: int,
) -> Tuple[bytes, str, str]:
    resp = requests.post(
        "https://api.elevenlabs.io/v1/music",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "prompt": composed_prompt,
            "music_length_ms": max(10_000, min(180_000, int(duration_sec) * 1000)),
        },
        timeout=180,
    )
    if not resp.ok:
        raise WaterfallProviderError(resp.status_code, f"ElevenLabs Music HTTP {resp.status_code}: {resp.text[:220]}")
    if len(resp.content) < 1024:
        raise WaterfallProviderError(502, "ElevenLabs geçerli ses akışı döndürmedi.")
    return resp.content, "mp3", ""


def _generate_stability_audio(
    api_key: str,
    composed_prompt: str,
    duration_sec: int,
) -> Tuple[bytes, str, str]:
    resp = requests.post(
        "https://api.stability.ai/v2beta/audio/stable-audio-2/text-to-audio",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "audio/*",
        },
        files={"none": (None, "")},
        data={
            "prompt": composed_prompt,
            "duration": str(max(5, min(180, int(duration_sec)))),
            "output_format": "mp3",
        },
        timeout=180,
    )
    if not resp.ok:
        raise WaterfallProviderError(resp.status_code, f"Stable Audio 2 HTTP {resp.status_code}: {resp.text[:220]}")
    if len(resp.content) < 1024:
        raise WaterfallProviderError(502, "Stable Audio 2 geçerli ses dosyası döndürmedi.")
    return resp.content, "mp3", ""


def _generate_replicate_musicgen(
    api_token: str,
    composed_prompt: str,
    duration_sec: int,
) -> Tuple[bytes, str, str]:
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json", "Prefer": "wait=60"}
    resp = requests.post(
        "https://api.replicate.com/v1/models/meta/musicgen/predictions",
        headers=headers,
        json={
            "input": {
                "prompt": composed_prompt,
                "model_version": "stereo-large",
                "output_format": "mp3",
                "duration": max(5, min(30, int(duration_sec))),
            }
        },
        timeout=90,
    )
    if not resp.ok:
        raise WaterfallProviderError(resp.status_code, f"Replicate MusicGen HTTP {resp.status_code}: {resp.text[:220]}")
    pred = resp.json()
    poll_url = (pred.get("urls") or {}).get("get")
    deadline = time.time() + 180.0
    while pred.get("status") not in ("succeeded", "failed", "canceled") and poll_url and time.time() < deadline:
        time.sleep(3.0)
        pr = requests.get(poll_url, headers={"Authorization": f"Bearer {api_token}"}, timeout=20)
        if pr.ok:
            pred = pr.json()
    if pred.get("status") != "succeeded":
        raise WaterfallProviderError(502, f"Replicate MusicGen tamamlanamadı: {pred.get('error') or pred.get('status')}")
    out_url = pred.get("output")
    if isinstance(out_url, list) and out_url:
        out_url = out_url[0]
    if not isinstance(out_url, str) or not out_url.startswith("https://"):
        raise WaterfallProviderError(502, "Replicate yanıtında indirme URL'si bulunamadı.")
    dl = requests.get(out_url, timeout=60)
    if not dl.ok or len(dl.content) < 1024:
        raise WaterfallProviderError(502, "Replicate ses çıktısı indirilemedi.")
    ext = "wav" if out_url.lower().endswith(".wav") else "mp3"
    return dl.content, ext, ""


def _run_single_model_with_key_waterfall(
    model_id: str,
    composed: str,
    dur: int,
    *,
    data_dir: Path,
    base_get_env: Callable[[str], Optional[str]],
) -> Tuple[bytes, str, str, str, List[str]]:
    """Tek bir model için tüm hesap anahtarlarını şelalede dener."""
    spec = MUSIC_MODELS_BY_ID[model_id]
    prov = spec["provider"]
    env_key = str(spec["env_key"])
    capped_dur = max(5, min(int(spec["max_duration_sec"]), dur))

    if prov == "google_lyria":
        call = lambda k: _generate_google_lyria(model_id, k, composed)
    elif prov == "elevenlabs":
        call = lambda k: _generate_elevenlabs_music(k, composed, capped_dur)
    elif prov == "stability":
        call = lambda k: _generate_stability_audio(k, composed, capped_dur)
    elif prov == "replicate":
        call = lambda k: _generate_replicate_musicgen(k, composed, capped_dur)
    else:
        raise RuntimeError(f"Desteklenmeyen sağlayıcı: {prov}")

    (audio_bytes, ext, out_lyrics), used_label, trace = execute_key_waterfall(
        env_key,
        call,
        data_dir=data_dir,
        base_get_env=base_get_env,
    )
    return audio_bytes, ext, out_lyrics, used_label, trace


def _load_history(data_dir: Path) -> List[Dict[str, Any]]:
    yol = Path(data_dir) / MUSIC_HISTORY_FILENAME
    _sync_from_r2(yol, R2_MUSIC_HISTORY_KEY)
    if not yol.is_file():
        return []
    try:
        raw = json.loads(yol.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except (OSError, ValueError):
        return []


def _append_history(data_dir: Path, entry: Dict[str, Any]) -> None:
    items = _load_history(data_dir)
    items.insert(0, entry)
    items = items[:60]
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    yol = Path(data_dir) / MUSIC_HISTORY_FILENAME
    tmp = Path(data_dir) / f".music_hist.{os.getpid()}.{threading.get_ident()}.tmp"
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, yol)
    try:
        import cloud_storage

        if cloud_storage.is_configured():
            cloud_storage.put_file(yol, key=R2_MUSIC_HISTORY_KEY, content_type="application/json")
    except Exception:
        pass


def _load_jobs_state(data_dir: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    if data_dir is None:
        return {}
    yol = Path(data_dir) / MUSIC_JOBS_STATE_FILENAME
    _sync_from_r2(yol, R2_MUSIC_JOBS_KEY)
    if not yol.is_file():
        return {}
    try:
        raw = json.loads(yol.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    except (OSError, ValueError):
        return {}
    return {}


def _push_r2_json_async(yol: Path, r2_key: str) -> None:
    """R2 JSON senkronizasyonunu kilit dışında arka planda yapar."""
    def _worker() -> None:
        try:
            import cloud_storage

            if cloud_storage.is_configured() and yol.is_file():
                cloud_storage.put_file(yol, key=r2_key, content_type="application/json")
        except Exception as exc:
            logger.debug("[MusicStudio] R2 arka plan yazımı atlandı (%s): %s", r2_key, exc)

    threading.Thread(target=_worker, daemon=True, name="MusicR2Sync").start()


def _save_jobs_state(data_dir: Optional[Path]) -> None:
    """_JOBS_LOCK altında çağrılır: önce yerel atomik yazar, R2 yüklemesini kilit dışı thread'e devreder."""
    if data_dir is None:
        return
    try:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        yol = Path(data_dir) / MUSIC_JOBS_STATE_FILENAME
        # Liste kopyası üzerinden güvenli sıralama (mutasyon yarışı yok)
        items_copy = list(_MUSIC_JOBS.items())
        ordered = sorted(
            items_copy,
            key=lambda kv: float(kv[1].get("created_at") or 0),
            reverse=True,
        )[:MAX_JOBS]
        snapshot = {k: dict(v) for k, v in ordered}
        tmp = Path(data_dir) / f".music_jobs.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, yol)
        _push_r2_json_async(yol, R2_MUSIC_JOBS_KEY)
    except OSError as exc:
        logger.warning("[MusicStudio] music_jobs_state.json yazılamadı: %s", exc)


def get_music_history(data_dir: Path, limit: int = 30) -> List[Dict[str, Any]]:
    with _JOBS_LOCK:
        return _load_history(data_dir)[: max(1, min(int(limit), 60))]


def get_music_job(job_id: str, data_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _MUSIC_JOBS.get(job_id)
        if job is not None:
            return dict(job)
        if data_dir is not None:
            persisted = _load_jobs_state(data_dir)
            if job_id in persisted:
                _MUSIC_JOBS[job_id] = dict(persisted[job_id])
                return dict(_MUSIC_JOBS[job_id])
            for item in _load_history(data_dir):
                if isinstance(item, dict) and item.get("job_id") == job_id:
                    return dict(item)
        return None


def _gpu_kuyruga_al(
    *,
    job_id: str,
    composed: str,
    clean_prompt: str,
    dur: int,
    genre: str,
    mood: str,
    instrumental: bool,
    created_by: str,
    enqueue_gpu_fn: Callable[[Dict[str, Any]], Any],
    data_dir: Optional[Path] = None,
    trace: Optional[List[str]] = None,
    chosen_model: str = "gpu-acestep-1.5",
    lyrics: str = "",
    vocal_language: str = "tr",
    bpm: Optional[int] = None,
    key_scale: str = "",
    time_signature: str = "",
    music_task: str = "text2music",
    ref_audio_url: Optional[str] = None,
    audio_cover_strength: float = 0.85,
    repaint_start: Optional[float] = None,
    repaint_end: Optional[float] = None,
    seed: Optional[int] = None,
) -> bool:
    """İşi Kaggle/Colab GPU kuyruğuna yazar (ACE-Step 1.5 veya MusicGen Stereo)."""
    is_acestep = chosen_model == "gpu-acestep-1.5"
    audio_model = "acestep-v15-xl-turbo" if is_acestep else "musicgen-stereo-medium"
    max_cap = 240 if is_acestep else 30
    effective_dur = max(5, min(max_cap, int(dur)))
    payload: Dict[str, Any] = {
        "job_id": job_id,
        "method": "acestep" if is_acestep else "musicgen",
        "model_id": chosen_model,
        "prompt": composed if not is_acestep else clean_prompt,
        "composed_prompt": composed,
        "raw_prompt": clean_prompt,
        "duration_sec": effective_dur,
        "genre": genre.strip()[:60],
        "mood": mood.strip()[:60],
        "instrumental": bool(instrumental),
        "lyrics": "" if instrumental else str(lyrics or "").strip()[:4096],
        "vocal_language": str(vocal_language or "tr").strip().lower()[:12],
        "bpm": int(bpm) if bpm else None,
        "key_scale": str(key_scale or "").strip()[:32],
        "time_signature": str(time_signature or "").strip()[:12],
        "music_task": str(music_task or "text2music").strip().lower(),
        "ref_audio_url": ref_audio_url,
        "audio_cover_strength": float(audio_cover_strength),
        "repaint_start": float(repaint_start) if repaint_start is not None else None,
        "repaint_end": float(repaint_end) if repaint_end is not None else None,
        "seed": int(seed) if seed is not None else None,
        "audio_model": audio_model,
        "created_by": created_by,
    }
    try:
        enqueue_gpu_fn(payload)
    except Exception as exc:
        logger.warning("[MusicStudio] GPU kuyruğuna alınamadı (%s): %s", job_id, exc)
        with _JOBS_LOCK:
            job = _MUSIC_JOBS.get(job_id)
            if job is not None:
                job["status"] = "failed"
                job["error"] = f"GPU kuyruğuna alınamadı: {str(exc)[:280]}"
                _save_jobs_state(data_dir)
        return False
    with _JOBS_LOCK:
        job = _MUSIC_JOBS.get(job_id)
        if job is None:
            return False
        job["status"] = "queued_gpu"
        job["gpu_job_id"] = job_id
        job["model_id"] = chosen_model
        job["model_name"] = MUSIC_MODELS_BY_ID[chosen_model]["name"]
        job["duration_sec"] = effective_dur
        job["queued_at"] = time.time()
        if trace is not None:
            job["waterfall_trace"] = trace[-12:]
        _save_jobs_state(data_dir)
    return True


def complete_music_job(
    job_id: str,
    audio_url: str,
    filename: str,
    data_dir: Path,
    engine_label: str = "Kaggle GPU ACE-Step 1.5",
    fallback_meta: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """GPU işçisinin yüklediği WAV/MP3/FLAC'ı müzik işine bağlar ve geçmişe yazar.

    Sunucu yeniden başlamış olsa bile `music_jobs_state.json` veya `fallback_meta`
    (video_jobs.json kaydı) üzerinden işi kurtarır; tamamlanan şarkı asla kaybolmaz.
    """
    temiz_url = str(audio_url or "").strip()
    if not job_id or not temiz_url:
        raise ValueError("complete_music_job için job_id ve audio_url zorunludur.")
    with _JOBS_LOCK:
        job = _MUSIC_JOBS.get(job_id)
        if job is None:
            persisted = _load_jobs_state(data_dir)
            if job_id in persisted:
                job = dict(persisted[job_id])
                _MUSIC_JOBS[job_id] = job
            elif isinstance(fallback_meta, dict) and fallback_meta:
                mid = str(fallback_meta.get("model_id") or (
                    "gpu-acestep-1.5"
                    if str(fallback_meta.get("method") or "").lower() in ("acestep", "gpu_acestep")
                    else "gpu-musicgen"
                ))
                spec = MUSIC_MODELS_BY_ID.get(mid, MUSIC_MODELS_BY_ID["gpu-acestep-1.5"])
                job = {
                    "job_id": job_id,
                    "status": "queued_gpu",
                    "model_id": mid,
                    "model_name": spec["name"],
                    "provider": spec["provider"],
                    "prompt": str(fallback_meta.get("raw_prompt") or fallback_meta.get("prompt") or ""),
                    "genre": str(fallback_meta.get("genre") or ""),
                    "mood": str(fallback_meta.get("mood") or ""),
                    "duration_sec": int(fallback_meta.get("sure_sn") or fallback_meta.get("duration") or 30),
                    "instrumental": bool(fallback_meta.get("instrumental", True)),
                    "lyrics": str(fallback_meta.get("lyrics") or ""),
                    "vocal_language": str(fallback_meta.get("vocal_language") or "tr"),
                    "bpm": fallback_meta.get("bpm"),
                    "key_scale": str(fallback_meta.get("key_scale") or ""),
                    "music_task": str(fallback_meta.get("music_task") or "text2music"),
                    "created_by": str(fallback_meta.get("created_by") or "owner"),
                    "created_at": float(fallback_meta.get("created_at") or time.time()),
                    "gpu_job_id": job_id,
                    "waterfall_trace": [],
                }
                _MUSIC_JOBS[job_id] = job
            else:
                logger.warning("[MusicStudio] Tamamlanacak müzik işi bulunamadı: %s", job_id)
                return None
        job["status"] = "completed"
        job["audio_url"] = temiz_url
        job["filename"] = str(filename or "")
        job["used_key_label"] = engine_label
        job["completed_at"] = time.time()
        job["error"] = None
        _save_jobs_state(data_dir)
        _append_history(data_dir, dict(job))
        return dict(job)


def fail_music_job(job_id: str, error_msg: str, data_dir: Optional[Path] = None) -> bool:
    """GPU işçisinin başarısız bildirdiği müzik işini dürüstçe işaretler (restart dayanıklı)."""
    with _JOBS_LOCK:
        job = _MUSIC_JOBS.get(job_id)
        if job is None and data_dir is not None:
            persisted = _load_jobs_state(data_dir)
            if job_id in persisted:
                job = dict(persisted[job_id])
                _MUSIC_JOBS[job_id] = job
        if job is None:
            logger.warning("[MusicStudio] Başarısız işaretlenecek müzik işi bulunamadı: %s", job_id)
            return False
        job["status"] = "failed"
        job["error"] = str(error_msg or "GPU işçisi işi başarısız bildirdi.")[:360]
        job["failed_at"] = time.time()
        _save_jobs_state(data_dir)
        return True


def generate_song_lyrics(
    *,
    topic: str,
    genre: str = "",
    mood: str = "",
    vocal_language: str = "tr",
    duration_sec: int = 90,
    data_dir: Path,
    get_env: Callable[[str], Optional[str]],
) -> Dict[str, Any]:
    """Gemini çoklu hesap şelalesiyle Suno/ACE-Step yapısında ([Verse]/[Chorus]) gerçek şarkı sözü üretir."""
    clean_topic = str(topic or "").strip()
    if len(clean_topic) < 3:
        raise ValueError("Şarkı sözü konusu en az 3 karakter olmalıdır.")
    lang = str(vocal_language or "tr").strip().lower()
    lang_label = {"tr": "Türkçe", "en": "English", "de": "Deutsch", "fr": "Français", "es": "Español"}.get(lang, lang)
    prompt = (
        f"Sen profesyonel bir söz yazarı ve müzik yapımcısısın.\n"
        f"Konu: {clean_topic}\n"
        f"Tür: {genre or 'Modern'}\n"
        f"Atmosfer: {mood or 'Duygusal ve akılda kalıcı'}\n"
        f"Hedef süre: ~{int(duration_sec)} saniye\n"
        f"Dil: {lang_label}\n"
        "Kurallar:\n"
        "- Yalnızca şu yapı etiketlerini kullan: [Intro], [Verse 1], [Pre-Chorus], [Chorus], [Verse 2], [Bridge], [Outro].\n"
        "- Ritimli, söylenebilir, kafiyeli ve doğal şarkı sözleri yaz.\n"
        "- Açıklama veya ekstra yorum ekleme, yalnızca şarkı sözünü döndür."
    )

    def _call_gemini(api_key: str) -> str:
        for model in ("gemini-2.5-flash", "gemini-2.0-flash"):
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.85, "maxOutputTokens": 900},
                },
                timeout=30,
            )
            if resp.ok:
                data = resp.json()
                cands = data.get("candidates") or []
                parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
                text = "".join(str(p.get("text") or "") for p in parts).strip()
                if text:
                    return text
            elif resp.status_code in (401, 403, 429):
                raise WaterfallProviderError(resp.status_code, f"Gemini HTTP {resp.status_code}: {resp.text[:180]}")
        raise WaterfallProviderError(502, "Gemini söz üretiminden geçerli yanıt alınamadı.")

    lyrics_text, used_label, trace = execute_key_waterfall(
        "GEMINI_API_KEY",
        _call_gemini,
        data_dir=data_dir,
        base_get_env=get_env,
    )
    return {
        "lyrics": lyrics_text.strip(),
        "vocal_language": lang,
        "used_key_label": used_label,
        "trace": trace,
    }


def start_music_job(
    *,
    model_id: str,
    prompt: str,
    genre: str = "",
    mood: str = "",
    duration_sec: int = 30,
    instrumental: bool = True,
    lyrics: str = "",
    vocal_language: str = "tr",
    bpm: Optional[int] = None,
    key_scale: str = "",
    time_signature: str = "",
    music_task: str = "text2music",
    ref_audio_url: Optional[str] = None,
    audio_cover_strength: float = 0.85,
    repaint_start: Optional[float] = None,
    repaint_end: Optional[float] = None,
    seed: Optional[int] = None,
    created_by: str = "owner",
    data_dir: Path,
    media_dir: Path,
    get_env: Callable[[str], Optional[str]],
    mac_dispatch_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
    enqueue_gpu_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Çoklu hesap şelalesiyle veya Kaggle GPU ACE-Step 1.5/MusicGen ile gerçek müzik işi başlatır."""
    spec = MUSIC_MODELS_BY_ID.get(model_id)
    if not spec:
        raise ValueError(f"Bilinmeyen müzik modeli: {model_id}")
    clean_prompt = str(prompt or "").strip()
    if len(clean_prompt) < 4:
        raise ValueError("Müzik promptu en az 4 karakter olmalıdır.")
    task_norm = str(music_task or "text2music").strip().lower()
    if task_norm not in VALID_MUSIC_TASKS:
        raise ValueError(f"Geçersiz müzik görevi: {music_task!r}. Geçerliler: {', '.join(VALID_MUSIC_TASKS)}")
    if task_norm in ("cover", "repaint", "extend") and not ref_audio_url:
        raise ValueError(f"'{task_norm}' görevi için referans ses dosyası (ref_audio_base64 veya ref_audio_url) zorunludur.")

    clean_lyrics = str(lyrics or "").strip()[:4096]
    needs_vocals = (not bool(instrumental)) or bool(clean_lyrics)
    if needs_vocals and model_id != "auto_waterfall" and not spec.get("supports_vocals"):
        raise ValueError(
            f"'{spec['name']}' yalnızca enstrümantal destekler (vokal/şarkı sözü üretmez). "
            "Vokal ve sözlü şarkı için 'gpu-acestep-1.5' (ücretsiz Kaggle GPU) veya 'auto_waterfall' seçin."
        )
    supported_tasks = spec.get("supports_tasks") or ["text2music"]
    if task_norm != "text2music" and model_id != "auto_waterfall" and task_norm not in supported_tasks:
        raise ValueError(
            f"'{spec['name']}' modeli '{task_norm}' görevini desteklemiyor. Cover/Repaint/Extend için 'gpu-acestep-1.5' seçin."
        )

    lang_norm = str(vocal_language or "tr").strip().lower()[:12]
    if lang_norm not in SUPPORTED_VOCAL_LANGUAGES:
        lang_norm = "unknown"

    clean_bpm: Optional[int] = None
    if bpm is not None and str(bpm).strip() != "":
        try:
            clean_bpm = max(40, min(240, int(bpm)))
        except (TypeError, ValueError):
            clean_bpm = None

    try:
        cov_strength = max(0.0, min(1.0, float(audio_cover_strength)))
    except (TypeError, ValueError):
        cov_strength = 0.85

    dur = max(5, min(int(spec["max_duration_sec"]), int(duration_sec or spec["default_duration_sec"])))

    # Ön doğrulama: tekil bulut modelde en az 1 anahtar var mı?
    env_key = spec.get("env_key")
    if env_key:
        keys = collect_provider_keys(env_key, data_dir=data_dir, base_get_env=get_env)
        if not keys:
            raise PermissionError(
                f"'{spec['name']}' için {env_key} (veya {env_key}_1.._9) anahtarı yapılandırılmamış. "
                "Müzik Stüdyosu → API Şelalesi panelinden ekleyin veya ücretsiz 'gpu-acestep-1.5' seçin."
            )
    elif model_id == "auto_waterfall":
        any_keys = any(
            collect_provider_keys(k, data_dir=data_dir, base_get_env=get_env)
            for k in ALLOWED_SECRET_KEYS
        )
        if not any_keys and mac_dispatch_fn is None and enqueue_gpu_fn is None:
            raise PermissionError(
                "Otomatik Şelale için en az bir sağlayıcı anahtarı veya Kaggle GPU kuyruğu gereklidir."
            )

    if model_id in ("gpu-musicgen", "gpu-acestep-1.5") and enqueue_gpu_fn is None:
        raise PermissionError(
            "GPU kuyruğu köprüsü etkin değil: Kaggle/Colab işçisine iş gönderilemiyor."
        )

    job_id = f"mus_{int(time.time())}_{secrets.token_hex(4)}"
    composed = _compose_music_prompt(
        clean_prompt,
        genre=genre,
        mood=mood,
        duration_sec=dur,
        instrumental=bool(instrumental) and not bool(clean_lyrics),
        lyrics=clean_lyrics,
        bpm=clean_bpm,
        key_scale=key_scale,
        vocal_language=lang_norm,
    )
    eff_instrumental = bool(instrumental) and not bool(clean_lyrics)
    job: Dict[str, Any] = {
        "job_id": job_id,
        "status": "running",
        "model_id": model_id,
        "model_name": spec["name"],
        "provider": spec["provider"],
        "prompt": clean_prompt,
        "genre": genre.strip()[:60],
        "mood": mood.strip()[:60],
        "duration_sec": dur,
        "instrumental": eff_instrumental,
        "vocal_language": lang_norm,
        "bpm": clean_bpm,
        "key_scale": str(key_scale or "").strip()[:32],
        "time_signature": str(time_signature or "").strip()[:12],
        "music_task": task_norm,
        "ref_audio_url": ref_audio_url,
        "seed": int(seed) if seed is not None else None,
        "created_by": created_by,
        "created_at": time.time(),
        "audio_url": None,
        "filename": None,
        "lyrics": clean_lyrics,
        "used_key_label": None,
        "waterfall_trace": [],
        "error": None,
        "gpu_job_id": None,
    }
    with _JOBS_LOCK:
        if len(_MUSIC_JOBS) >= MAX_JOBS:
            oldest = sorted(_MUSIC_JOBS.keys(), key=lambda k: _MUSIC_JOBS[k].get("created_at", 0))[:20]
            for k in oldest:
                _MUSIC_JOBS.pop(k, None)
        _MUSIC_JOBS[job_id] = job
        _save_jobs_state(data_dir)

    # Doğrudan Kaggle/Colab GPU modelleri (ACE-Step 1.5 veya MusicGen Stereo)
    if model_id in ("gpu-acestep-1.5", "gpu-musicgen"):
        _gpu_kuyruga_al(
            job_id=job_id,
            composed=composed,
            clean_prompt=clean_prompt,
            dur=dur,
            genre=genre,
            mood=mood,
            instrumental=eff_instrumental,
            created_by=created_by,
            enqueue_gpu_fn=enqueue_gpu_fn,  # type: ignore[arg-type]
            data_dir=data_dir,
            chosen_model=model_id,
            lyrics=clean_lyrics,
            vocal_language=lang_norm,
            bpm=clean_bpm,
            key_scale=key_scale,
            time_signature=time_signature,
            music_task=task_norm,
            ref_audio_url=ref_audio_url,
            audio_cover_strength=cov_strength,
            repaint_start=repaint_start,
            repaint_end=repaint_end,
            seed=seed,
        )
        with _JOBS_LOCK:
            return dict(_MUSIC_JOBS[job_id])

    # Cover / Repaint / Extend görevlerinde auto_waterfall doğrudan ACE-Step 1.5 GPU kuyruğuna yönlenir
    if model_id == "auto_waterfall" and task_norm != "text2music":
        if enqueue_gpu_fn is None:
            raise PermissionError(f"'{task_norm}' görevi için Kaggle GPU ACE-Step 1.5 kuyruğu gereklidir.")
        _gpu_kuyruga_al(
            job_id=job_id,
            composed=composed,
            clean_prompt=clean_prompt,
            dur=dur,
            genre=genre,
            mood=mood,
            instrumental=eff_instrumental,
            created_by=created_by,
            enqueue_gpu_fn=enqueue_gpu_fn,
            data_dir=data_dir,
            trace=[f"[auto_waterfall] '{task_norm}' görevi için gpu-acestep-1.5 seçildi"],
            chosen_model="gpu-acestep-1.5",
            lyrics=clean_lyrics,
            vocal_language=lang_norm,
            bpm=clean_bpm,
            key_scale=key_scale,
            time_signature=time_signature,
            music_task=task_norm,
            ref_audio_url=ref_audio_url,
            audio_cover_strength=cov_strength,
            repaint_start=repaint_start,
            repaint_end=repaint_end,
            seed=seed,
        )
        with _JOBS_LOCK:
            return dict(_MUSIC_JOBS[job_id])

    def _run() -> None:
        all_traces: List[str] = []
        try:
            chosen_model = model_id
            audio_bytes: Optional[bytes] = None
            ext = "mp3"
            out_lyrics = clean_lyrics
            used_label = ""

            if model_id == "local-musicgen-mac":
                if mac_dispatch_fn is None:
                    raise RuntimeError("Mac Fabrika köprüsü etkin değil.")
                res = mac_dispatch_fn(f"müzik üret ({dur} sn): {composed}")
                if not res.get("ok"):
                    raise RuntimeError(res.get("text") or "Mac Fabrika çevrimdışı.")
                with _JOBS_LOCK:
                    _MUSIC_JOBS[job_id]["status"] = "delegated_mac"
                    _MUSIC_JOBS[job_id]["lyrics"] = str(res.get("text") or "Mac Fabrika'ya iletildi.")
                    _save_jobs_state(data_dir)
                return

            if model_id == "auto_waterfall":
                last_exc: Optional[Exception] = None
                for cand_id in AUTO_WATERFALL_ORDER:
                    cspec = MUSIC_MODELS_BY_ID[cand_id]
                    # KRİTİK VOKAL KORUMASI: Vokal/şarkı sözü isteyen kullanıcı asla
                    # enstrümantal-only modele sessizce düşürülmez!
                    if needs_vocals and not cspec.get("supports_vocals"):
                        all_traces.append(f"[{cand_id}] atlandı (vokal/söz desteklemiyor)")
                        continue
                    if cand_id in ("gpu-acestep-1.5", "gpu-musicgen"):
                        if enqueue_gpu_fn is not None:
                            all_traces.append(f"[{cand_id}] Kaggle GPU kuyruğuna alındı")
                            _gpu_kuyruga_al(
                                job_id=job_id,
                                composed=composed,
                                clean_prompt=clean_prompt,
                                dur=dur,
                                genre=genre,
                                mood=mood,
                                instrumental=eff_instrumental,
                                created_by=created_by,
                                enqueue_gpu_fn=enqueue_gpu_fn,
                                data_dir=data_dir,
                                trace=all_traces,
                                chosen_model=cand_id,
                                lyrics=clean_lyrics,
                                vocal_language=lang_norm,
                                bpm=clean_bpm,
                                key_scale=key_scale,
                                time_signature=time_signature,
                                music_task=task_norm,
                                ref_audio_url=ref_audio_url,
                                audio_cover_strength=cov_strength,
                                repaint_start=repaint_start,
                                repaint_end=repaint_end,
                                seed=seed,
                            )
                            return
                        all_traces.append(f"[{cand_id}] GPU kuyruğu köprüsü etkin değil")
                        continue
                    if cand_id == "local-musicgen-mac":
                        if mac_dispatch_fn is not None:
                            res = mac_dispatch_fn(f"müzik üret ({dur} sn): {composed}")
                            if res.get("ok"):
                                with _JOBS_LOCK:
                                    _MUSIC_JOBS[job_id]["status"] = "delegated_mac"
                                    _MUSIC_JOBS[job_id]["model_id"] = cand_id
                                    _MUSIC_JOBS[job_id]["model_name"] = cspec["name"]
                                    _MUSIC_JOBS[job_id]["waterfall_trace"] = all_traces + ["Mac Köprüsü: ✅ iletildi"]
                                    _MUSIC_JOBS[job_id]["lyrics"] = str(res.get("text") or "Mac Fabrika'ya iletildi.")
                                    _save_jobs_state(data_dir)
                                return
                            all_traces.append("Mac Köprüsü: çevrimdışı")
                        continue
                    ckey = str(cspec["env_key"])
                    if not collect_provider_keys(ckey, data_dir=data_dir, base_get_env=get_env):
                        continue
                    try:
                        audio_bytes, ext, got_lyrics, used_label, tr = _run_single_model_with_key_waterfall(
                            cand_id, composed, dur, data_dir=data_dir, base_get_env=get_env
                        )
                        all_traces.extend(f"[{cand_id}] {x}" for x in tr)
                        if got_lyrics:
                            out_lyrics = got_lyrics
                        chosen_model = cand_id
                        break
                    except Exception as exc:
                        last_exc = exc
                        all_traces.append(f"[{cand_id}] {str(exc)[:140]}")
                if audio_bytes is None:
                    raise RuntimeError(str(last_exc or "Otomatik şelalede çalışan müzik modeli bulunamadı."))
            else:
                audio_bytes, ext, got_lyrics, used_label, tr = _run_single_model_with_key_waterfall(
                    model_id, composed, dur, data_dir=data_dir, base_get_env=get_env
                )
                if got_lyrics:
                    out_lyrics = got_lyrics
                all_traces.extend(tr)

            Path(media_dir).mkdir(parents=True, exist_ok=True)
            fname = f"{job_id}.{ext}"
            out_path = Path(media_dir) / fname
            tmp_path = Path(media_dir) / f".{fname}.part"
            tmp_path.write_bytes(audio_bytes)
            os.replace(tmp_path, out_path)

            mime = "audio/wav" if ext == "wav" else ("audio/flac" if ext == "flac" else "audio/mpeg")
            try:
                import cloud_storage

                if cloud_storage.is_configured():
                    cloud_storage.put_file(out_path, content_type=mime)
            except Exception:
                pass

            audio_url = f"/api/media/file?path={fname}"
            with _JOBS_LOCK:
                _MUSIC_JOBS[job_id]["status"] = "completed"
                _MUSIC_JOBS[job_id]["model_id"] = chosen_model
                _MUSIC_JOBS[job_id]["model_name"] = MUSIC_MODELS_BY_ID[chosen_model]["name"]
                _MUSIC_JOBS[job_id]["audio_url"] = audio_url
                _MUSIC_JOBS[job_id]["filename"] = fname
                _MUSIC_JOBS[job_id]["lyrics"] = out_lyrics
                _MUSIC_JOBS[job_id]["used_key_label"] = used_label
                _MUSIC_JOBS[job_id]["waterfall_trace"] = all_traces[-12:]
                _MUSIC_JOBS[job_id]["completed_at"] = time.time()
                _save_jobs_state(data_dir)
                _append_history(data_dir, dict(_MUSIC_JOBS[job_id]))
        except Exception as exc:
            logger.warning("[MusicStudio] İş başarısız (%s): %s", job_id, exc)
            with _JOBS_LOCK:
                _MUSIC_JOBS[job_id]["status"] = "failed"
                _MUSIC_JOBS[job_id]["waterfall_trace"] = all_traces[-12:]
                _MUSIC_JOBS[job_id]["error"] = str(exc)[:360]
                _save_jobs_state(data_dir)

    t = threading.Thread(target=_run, daemon=True, name=f"MusicJob-{job_id}")
    t.start()
    return dict(job)
