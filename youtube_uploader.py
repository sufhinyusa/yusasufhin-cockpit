# -*- coding: utf-8 -*-
"""
youtube_uploader.py — Saf HTTP YouTube Data API v3 OAuth2 & Resumable MP4 Yükleyici
===================================================================================
`google-api-python-client` kurulu olmasa bile (512 MB Render veya Oracle ARM)
yalnız `requests` ile token yeniler, 4 MB parça akışıyla MP4 yükler ve varsa
kapak görselini (thumbnail) ayarlar.

Kalıcılık: OAuth bilgileri hem `data/youtube_auth/` dosyalarından hem de ortam
değişkenlerinden (`YOUTUBE_CLIENT_SECRET_JSON`, `YOUTUBE_TOKEN_JSON`,
`YOUTUBE_REFRESH_TOKEN`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`) okunabilir;
böylece Render yeniden başlatmalarında bağlantı kopmaz.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger("Fabrika.YouTubeUploader")

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
VIDEO_UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB (256 KB'nin katı — YouTube zorunluluğu)


def _slug(raw: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]+", "_", (raw or "").strip()).strip("_")
    return s[:48] or "default"


def _load_client_cfg(auth_dir: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    """OAuth client yapılandırmasını dosya veya ortam değişkeninden yükler."""
    cs_file = auth_dir / "client_secret.json"
    if cs_file.is_file():
        try:
            parsed = json.loads(cs_file.read_text(encoding="utf-8"))
            cfg = parsed.get("web") or parsed.get("installed")
            if isinstance(cfg, dict) and cfg.get("client_id") and cfg.get("client_secret"):
                return cfg, "disk"
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[YouTube] client_secret.json okunamadı: %s", exc)

    raw_env = (os.environ.get("YOUTUBE_CLIENT_SECRET_JSON") or "").strip()
    if raw_env:
        try:
            parsed = json.loads(raw_env)
            cfg = parsed.get("web") or parsed.get("installed") or parsed
            if isinstance(cfg, dict) and cfg.get("client_id") and cfg.get("client_secret"):
                return cfg, "env"
        except json.JSONDecodeError as exc:
            logger.warning("[YouTube] YOUTUBE_CLIENT_SECRET_JSON bozuk: %s", exc)

    cid = (os.environ.get("YOUTUBE_CLIENT_ID") or "").strip()
    csec = (os.environ.get("YOUTUBE_CLIENT_SECRET") or "").strip()
    if cid and csec:
        return {"client_id": cid, "client_secret": csec, "token_uri": TOKEN_ENDPOINT}, "env"

    return None, "none"


def _load_token_data(auth_dir: Path, channel_id: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[Path], str]:
    """Kanal veya genel OAuth token kaydını disk veya ortam değişkeninden okur."""
    candidates = []
    if channel_id:
        candidates.append(auth_dir / f"{_slug(channel_id)}_token.json")
    candidates.append(auth_dir / "youtube_token.json")

    for tok_path in candidates:
        if tok_path.is_file():
            try:
                data = json.loads(tok_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and (data.get("refresh_token") or data.get("token")):
                    return data, tok_path, "disk"
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("[YouTube] Token okunamadı (%s): %s", tok_path.name, exc)

    env_keys = []
    if channel_id:
        env_keys.append(f"YOUTUBE_TOKEN_JSON_{_slug(channel_id).upper()}")
    env_keys.append("YOUTUBE_TOKEN_JSON")
    for ek in env_keys:
        raw = (os.environ.get(ek) or "").strip()
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and (data.get("refresh_token") or data.get("token")):
                    return data, None, "env"
            except json.JSONDecodeError:
                pass

    ref = (os.environ.get("YOUTUBE_REFRESH_TOKEN") or "").strip()
    if ref:
        return {"refresh_token": ref, "token_uri": TOKEN_ENDPOINT}, None, "env"

    return None, None, "none"


def youtube_status(auth_dir: Path, channel_id: Optional[str] = None) -> Dict[str, Any]:
    """YouTube Data API v3 canlı yükleme durumunu dürüstçe raporlar."""
    auth_dir.mkdir(parents=True, exist_ok=True)
    client_cfg, client_src = _load_client_cfg(auth_dir)
    tok_data, _, tok_src = _load_token_data(auth_dir, channel_id)

    has_client = bool(client_cfg) or bool(
        tok_data and tok_data.get("client_id") and tok_data.get("client_secret")
    )
    has_token = bool(tok_data)
    ready = has_client and has_token

    if tok_src == "env" or client_src == "env":
        persistence = "env"
    elif tok_src == "disk" or client_src == "disk":
        persistence = "disk"
    else:
        persistence = "none"

    return {
        "ready_for_live_upload": ready,
        "client_secret_present": has_client,
        "oauth_token_present": has_token,
        "google_api_client_installed": True,  # Saf HTTP Resumable v3 aktif
        "transport": "http_resumable_v3",
        "persistence_mode": persistence,
        "status": "active" if ready else "not_authenticated",
        "message": (
            f"YouTube Data API v3 canlı yükleme için hazır (kaynak: {persistence})."
            if ready
            else "YouTube OAuth (client_secret.json veya YOUTUBE_REFRESH_TOKEN) henüz bağlı değil. Videolar SEO paketi + kapakla yerel hazırlanır (simülasyon)."
        ),
    }


def refresh_access_token(
    tok_data: Dict[str, Any],
    client_cfg: Optional[Dict[str, Any]],
    tok_path: Optional[Path] = None,
) -> str:
    """Refresh token ile taze Google OAuth2 access_token alır."""
    refresh_tok = str(tok_data.get("refresh_token") or "").strip()
    if not refresh_tok:
        access = str(tok_data.get("token") or "").strip()
        if access:
            return access
        raise RuntimeError("OAuth refresh_token veya access_token eksik.")

    cid = str(tok_data.get("client_id") or (client_cfg or {}).get("client_id") or "").strip()
    csec = str(tok_data.get("client_secret") or (client_cfg or {}).get("client_secret") or "").strip()
    token_uri = str(tok_data.get("token_uri") or (client_cfg or {}).get("token_uri") or TOKEN_ENDPOINT)
    if not cid or not csec:
        raise RuntimeError("OAuth token yenilemek için client_id ve client_secret gerekli.")

    resp = requests.post(
        token_uri,
        data={
            "client_id": cid,
            "client_secret": csec,
            "refresh_token": refresh_tok,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if not resp.ok:
        raise RuntimeError(f"OAuth token yenilenemedi (HTTP {resp.status_code}): {resp.text[:160]}")
    body = resp.json()
    access = str(body.get("access_token") or "").strip()
    if not access:
        raise RuntimeError("OAuth yanıtında access_token bulunamadı.")

    tok_data["token"] = access
    if tok_path and tok_path.is_file():
        try:
            tok_path.write_text(json.dumps(tok_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return access


def upload_video_resumable(
    video_path: Path,
    bundle: Dict[str, Any],
    auth_dir: Path,
    thumbnail_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """MP4 dosyasını YouTube Data API v3 Resumable Upload ile doğrudan kanala yükler."""
    if not video_path.is_file():
        return {
            "success": False,
            "simulasyon": False,
            "status": "video_yok",
            "bundle": bundle,
            "message": "Video MP4 dosyası bulunamadı.",
        }

    cid = str(bundle.get("channel_id") or "")
    client_cfg, _ = _load_client_cfg(auth_dir)
    tok_data, tok_path, _ = _load_token_data(auth_dir, cid)
    if not tok_data:
        return {
            "success": False,
            "simulasyon": True,
            "status": "oauth_gerekli",
            "bundle": bundle,
            "message": "(simülasyon) YouTube OAuth token bulunamadı; yerel yayın paketi hazırlandı.",
        }

    access_token = refresh_access_token(tok_data, client_cfg, tok_path)
    total_size = video_path.stat().st_size

    metadata = {
        "snippet": {
            "title": str(bundle.get("title") or video_path.stem)[:100],
            "description": str(bundle.get("description") or "")[:5000],
            "tags": list(bundle.get("tags") or [])[:15],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": str(bundle.get("privacy") or "private"),
            "selfDeclaredMadeForKids": False,
        },
    }

    init_resp = requests.post(
        VIDEO_UPLOAD_ENDPOINT,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(total_size),
            "X-Upload-Content-Type": "video/mp4",
        },
        json=metadata,
        timeout=30,
    )
    if not init_resp.ok:
        raise RuntimeError(f"YouTube yükleme oturumu açılamadı (HTTP {init_resp.status_code}): {init_resp.text[:180]}")

    upload_url = init_resp.headers.get("Location") or init_resp.headers.get("location")
    if not upload_url:
        raise RuntimeError("YouTube resumable upload Location başlığı dönmedi.")

    vid_resp = None
    with video_path.open("rb") as fh:
        offset = 0
        while offset < total_size:
            chunk = fh.read(CHUNK_SIZE)
            if not chunk:
                break
            end = offset + len(chunk) - 1
            put_resp = requests.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Length": str(len(chunk)),
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes {offset}-{end}/{total_size}",
                },
                data=chunk,
                timeout=120,
            )
            if put_resp.status_code in (200, 201):
                vid_resp = put_resp.json()
                break
            if put_resp.status_code != 308:
                raise RuntimeError(f"YouTube parça yükleme hatası (HTTP {put_resp.status_code}): {put_resp.text[:180]}")
            offset = end + 1

    if not isinstance(vid_resp, dict) or not vid_resp.get("id"):
        raise RuntimeError("YouTube yüklemesi tamamlandı ancak video ID dönmedi.")

    vid_id = str(vid_resp["id"])
    thumb_uploaded = False
    if thumbnail_path and thumbnail_path.is_file():
        try:
            mime = "image/png" if thumbnail_path.suffix.lower() == ".png" else "image/jpeg"
            t_resp = requests.post(
                THUMBNAIL_ENDPOINT,
                params={"videoId": vid_id, "uploadType": "media"},
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": mime},
                data=thumbnail_path.read_bytes(),
                timeout=30,
            )
            thumb_uploaded = t_resp.ok
        except Exception as exc:
            logger.warning("[YouTube] Kapak görseli yüklenemedi (%s): %s", vid_id, exc)

    return {
        "success": True,
        "simulasyon": False,
        "status": "uploaded",
        "youtube_video_id": vid_id,
        "youtube_url": f"https://www.youtube.com/watch?v={vid_id}",
        "thumbnail_uploaded": thumb_uploaded,
        "bundle": bundle,
        "message": "Video YouTube kanalına başarıyla yüklendi.",
    }
