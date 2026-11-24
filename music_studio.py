# -*- coding: utf-8 -*-
"""
music_studio.py — Çoklu Model Müzik Üretim Motoru (Lyria 3.5, ElevenLabs, Stable Audio, MusicGen)
==================================================================================================
Kural 1 (Dürüstlük): Hiçbir sağlayıcı sahte ses üretmez. İlgili API anahtarı eksikse veya
yerel GPU/Mac köprüsü çevrimdışıysa eksiklik dürüstçe raporlanır.

Gerçek desteklenen modeller:
  1. Google Lyria 3.5 (`lyria-3.5`)                 — GEMINI_API_KEY (Interactions REST API)
  2. Google Lyria 3 Clip (`lyria-3-clip-preview`)   — GEMINI_API_KEY (30 sn stereo MP3)
  3. ElevenLabs Music (`elevenlabs-music`)          — ELEVENLABS_API_KEY
  4. Stability Stable Audio 2 (`stable-audio-2`)    — STABILITY_API_KEY
  5. Meta MusicGen Stereo (`replicate-musicgen`)    — REPLICATE_API_TOKEN
  6. Yerel Mac / GPU MusicGen (`local-musicgen-mac`)— Canlı Mac Port-443 köprüsü
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

logger = logging.getLogger("Fabrika.MusicStudio")

MUSIC_SECRETS_FILENAME = ".music_secrets.json"
MUSIC_HISTORY_FILENAME = "music_history.json"
R2_MUSIC_SECRETS_KEY = "state/music_secrets.json"
R2_MUSIC_HISTORY_KEY = "state/music_history.json"
ALLOWED_SECRET_KEYS = ("GEMINI_API_KEY", "ELEVENLABS_API_KEY", "STABILITY_API_KEY", "REPLICATE_API_TOKEN")
MAX_JOBS = 120

_SECRETS_LOCK = threading.Lock()
_JOBS_LOCK = threading.Lock()
_MUSIC_JOBS: Dict[str, Dict[str, Any]] = {}

MUSIC_MODELS: List[Dict[str, Any]] = [
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
        "description": "44.1 kHz stereo tam şarkı, nakarat/köprü yapısı, vokal ve zamanlı şarkı sözü üretimi.",
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
        "description": "Hızlı 30 saniyelik 44.1 kHz stereo müzik klibi, döngü veya video fon müziği.",
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


def load_music_secrets(data_dir: Path) -> Dict[str, str]:
    yol = Path(data_dir) / MUSIC_SECRETS_FILENAME
    _sync_from_r2(yol, R2_MUSIC_SECRETS_KEY, mode=0o600)
    if not yol.is_file():
        return {}
    try:
        raw = json.loads(yol.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {k: str(v).strip() for k, v in raw.items() if k in ALLOWED_SECRET_KEYS and str(v or "").strip()}
    except (OSError, ValueError):
        return {}
    return {}


def save_music_secrets(data_dir: Path, updates: Dict[str, Optional[str]]) -> Dict[str, bool]:
    """Müzik API anahtarlarını atomik 0600 izinle kaydeder; değerleri asla geri döndürmez."""
    with _SECRETS_LOCK:
        cur = load_music_secrets(data_dir)
        for k, v in updates.items():
            if k not in ALLOWED_SECRET_KEYS or v is None:
                continue
            clean = str(v).strip()
            if clean == "__CLEAR__":
                cur.pop(k, None)
            elif clean:
                cur[k] = clean
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
        return {k: bool(cur.get(k)) for k in ALLOWED_SECRET_KEYS}


def make_music_env_getter(
    data_dir: Path,
    base_get_env: Callable[[str], Optional[str]],
) -> Callable[[str], Optional[str]]:
    saved = load_music_secrets(data_dir)

    def _get(key: str) -> Optional[str]:
        if key in saved and saved[key]:
            return saved[key]
        return base_get_env(key)

    return _get


def list_music_models(
    get_env: Callable[[str], Optional[str]],
    *,
    mac_online: bool = False,
) -> List[Dict[str, Any]]:
    """Tüm müzik modellerini gerçek erişilebilirlik/anahtar durumuyla birlikte listeler."""
    out: List[Dict[str, Any]] = []
    for spec in MUSIC_MODELS:
        env_key = spec.get("env_key")
        if env_key:
            ready = bool(get_env(env_key))
            reason = "Hazır" if ready else f"API anahtarı eksik: {env_key}"
        else:
            ready = bool(mac_online)
            reason = "Mac Fabrika bağlı" if ready else "Mac Fabrika çevrimdışı"
        out.append({
            **spec,
            "ready": ready,
            "status_text": reason,
        })
    return out


def _compose_music_prompt(
    prompt: str,
    *,
    genre: str = "",
    mood: str = "",
    duration_sec: int = 30,
    instrumental: bool = True,
    lyrics: str = "",
) -> str:
    parts = [prompt.strip()]
    if genre:
        parts.append(f"Genre/Style: {genre.strip()}.")
    if mood:
        parts.append(f"Mood/Atmosphere: {mood.strip()}.")
    if instrumental:
        parts.append("Purely instrumental, no vocals.")
    elif lyrics.strip():
        parts.append(f"Include vocals with these lyrics:\n{lyrics.strip()[:1200]}")
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
        raise RuntimeError(f"Google Lyria HTTP {resp.status_code}: {resp.text[:220]}")
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

    # Bazı SDK/proxy yanıtlarında üst düzey `outputs` alanı bulunabilir
    if audio_bytes is None and isinstance(data.get("outputs"), list):
        for block in data["outputs"]:
            if isinstance(block, dict) and block.get("type") == "audio" and block.get("data"):
                audio_bytes = base64.b64decode(block["data"])
                mime = str(block.get("mime_type") or "audio/mp3").lower()
                ext = "wav" if "wav" in mime else "mp3"

    if not audio_bytes:
        raise RuntimeError("Lyria yanıtında ses bloğu bulunamadı (ücretli Gemini API anahtarı gerekebilir).")
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
        raise RuntimeError(f"ElevenLabs Music HTTP {resp.status_code}: {resp.text[:220]}")
    if len(resp.content) < 1024:
        raise RuntimeError("ElevenLabs geçerli ses akışı döndürmedi.")
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
        raise RuntimeError(f"Stable Audio 2 HTTP {resp.status_code}: {resp.text[:220]}")
    if len(resp.content) < 1024:
        raise RuntimeError("Stable Audio 2 geçerli ses dosyası döndürmedi.")
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
        raise RuntimeError(f"Replicate MusicGen HTTP {resp.status_code}: {resp.text[:220]}")
    pred = resp.json()
    poll_url = (pred.get("urls") or {}).get("get")
    deadline = time.time() + 180.0
    while pred.get("status") not in ("succeeded", "failed", "canceled") and poll_url and time.time() < deadline:
        time.sleep(3.0)
        pr = requests.get(poll_url, headers={"Authorization": f"Bearer {api_token}"}, timeout=20)
        if pr.ok:
            pred = pr.json()
    if pred.get("status") != "succeeded":
        raise RuntimeError(f"Replicate MusicGen tamamlanamadı: {pred.get('error') or pred.get('status')}")
    out_url = pred.get("output")
    if isinstance(out_url, list) and out_url:
        out_url = out_url[0]
    if not isinstance(out_url, str) or not out_url.startswith("https://"):
        raise RuntimeError("Replicate yanıtında indirme URL'si bulunamadı.")
    dl = requests.get(out_url, timeout=60)
    if not dl.ok or len(dl.content) < 1024:
        raise RuntimeError("Replicate ses çıktısı indirilemedi.")
    ext = "wav" if out_url.lower().endswith(".wav") else "mp3"
    return dl.content, ext, ""


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


def get_music_history(data_dir: Path, limit: int = 30) -> List[Dict[str, Any]]:
    with _JOBS_LOCK:
        return _load_history(data_dir)[: max(1, min(int(limit), 60))]


def get_music_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _MUSIC_JOBS.get(job_id)
        return dict(job) if job else None


def start_music_job(
    *,
    model_id: str,
    prompt: str,
    genre: str = "",
    mood: str = "",
    duration_sec: int = 30,
    instrumental: bool = True,
    lyrics: str = "",
    created_by: str = "owner",
    data_dir: Path,
    media_dir: Path,
    get_env: Callable[[str], Optional[str]],
    mac_dispatch_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Gerçek bir müzik üretim işini doğrular ve arka plan iş parçacığında başlatır."""
    spec = MUSIC_MODELS_BY_ID.get(model_id)
    if not spec:
        raise ValueError(f"Bilinmeyen müzik modeli: {model_id}")
    clean_prompt = str(prompt or "").strip()
    if len(clean_prompt) < 4:
        raise ValueError("Müzik promptu en az 4 karakter olmalıdır.")
    dur = max(5, min(int(spec["max_duration_sec"]), int(duration_sec or spec["default_duration_sec"])))

    env_key = spec.get("env_key")
    api_key = get_env(env_key) if env_key else None
    if env_key and not api_key:
        raise PermissionError(
            f"'{spec['name']}' için {env_key} anahtarı yapılandırılmamış. "
            "Müzik Stüdyosu → Model Anahtarları panelinden ekleyin."
        )

    job_id = f"mus_{int(time.time())}_{secrets.token_hex(4)}"
    composed = _compose_music_prompt(
        clean_prompt, genre=genre, mood=mood, duration_sec=dur, instrumental=instrumental, lyrics=lyrics
    )
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
        "instrumental": bool(instrumental),
        "created_by": created_by,
        "created_at": time.time(),
        "audio_url": None,
        "filename": None,
        "lyrics": "",
        "error": None,
    }
    with _JOBS_LOCK:
        if len(_MUSIC_JOBS) >= MAX_JOBS:
            oldest = sorted(_MUSIC_JOBS.keys(), key=lambda k: _MUSIC_JOBS[k].get("created_at", 0))[:20]
            for k in oldest:
                _MUSIC_JOBS.pop(k, None)
        _MUSIC_JOBS[job_id] = job

    def _run() -> None:
        try:
            prov = spec["provider"]
            if prov == "google_lyria":
                audio_bytes, ext, out_lyrics = _generate_google_lyria(model_id, str(api_key), composed)
            elif prov == "elevenlabs":
                audio_bytes, ext, out_lyrics = _generate_elevenlabs_music(str(api_key), composed, dur)
            elif prov == "stability":
                audio_bytes, ext, out_lyrics = _generate_stability_audio(str(api_key), composed, dur)
            elif prov == "replicate":
                audio_bytes, ext, out_lyrics = _generate_replicate_musicgen(str(api_key), composed, dur)
            elif prov == "mac_bridge":
                if mac_dispatch_fn is None:
                    raise RuntimeError("Mac Fabrika köprüsü etkin değil.")
                res = mac_dispatch_fn(f"müzik üret ({dur} sn): {composed}")
                if not res.get("ok"):
                    raise RuntimeError(res.get("text") or "Mac Fabrika çevrimdışı.")
                with _JOBS_LOCK:
                    _MUSIC_JOBS[job_id]["status"] = "delegated_mac"
                    _MUSIC_JOBS[job_id]["lyrics"] = str(res.get("text") or "Mac Fabrika'ya iletildi.")
                return
            else:
                raise RuntimeError(f"Desteklenmeyen sağlayıcı: {prov}")

            Path(media_dir).mkdir(parents=True, exist_ok=True)
            fname = f"{job_id}.{ext}"
            out_path = Path(media_dir) / fname
            tmp_path = Path(media_dir) / f".{fname}.part"
            tmp_path.write_bytes(audio_bytes)
            os.replace(tmp_path, out_path)

            mime = "audio/wav" if ext == "wav" else "audio/mpeg"
            try:
                import cloud_storage

                if cloud_storage.is_configured():
                    cloud_storage.put_file(out_path, content_type=mime)
            except Exception:
                pass

            audio_url = f"/api/media/file?path={fname}"
            with _JOBS_LOCK:
                _MUSIC_JOBS[job_id]["status"] = "completed"
                _MUSIC_JOBS[job_id]["audio_url"] = audio_url
                _MUSIC_JOBS[job_id]["filename"] = fname
                _MUSIC_JOBS[job_id]["lyrics"] = out_lyrics
                _MUSIC_JOBS[job_id]["completed_at"] = time.time()
                _append_history(data_dir, dict(_MUSIC_JOBS[job_id]))
        except Exception as exc:
            logger.warning("[MusicStudio] İş başarısız (%s): %s", job_id, exc)
            with _JOBS_LOCK:
                _MUSIC_JOBS[job_id]["status"] = "failed"
                _MUSIC_JOBS[job_id]["error"] = str(exc)[:300]

    t = threading.Thread(target=_run, daemon=True, name=f"MusicJob-{job_id}")
    t.start()
    return dict(job)
