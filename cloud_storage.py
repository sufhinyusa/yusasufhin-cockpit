# -*- coding: utf-8 -*-
"""
cloud_storage.py — Kalıcı Medya Depolama & İsteğe Bağlı Cloudflare R2 (S3 SigV4)
================================================================================
`boto3` gerektirmeden saf stdlib + `requests` ile Cloudflare R2 (10 GB ücretsiz,
sıfır egress) veya herhangi bir S3 uyumlu nesne deposuna yedekleme / geri yükleme.

Ortam değişkenleri (isteğe bağlı):
  R2_ENDPOINT_URL     (ör. https://<account_id>.r2.cloudflarestorage.com)
  R2_BUCKET           (ör. yusasufhin-media)
  R2_ACCESS_KEY_ID
  R2_SECRET_ACCESS_KEY
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger("Fabrika.CloudStorage")


def _r2_config() -> Optional[Dict[str, str]]:
    ep = (os.environ.get("R2_ENDPOINT_URL") or "").strip().rstrip("/")
    bucket = (os.environ.get("R2_BUCKET") or "").strip().strip("/")
    ak = (os.environ.get("R2_ACCESS_KEY_ID") or "").strip()
    sk = (os.environ.get("R2_SECRET_ACCESS_KEY") or "").strip()
    if ep and bucket and ak and sk:
        return {"endpoint": ep, "bucket": bucket, "access_key": ak, "secret_key": sk}
    return None


def is_configured() -> bool:
    return _r2_config() is not None


def storage_status(local_dir: Path) -> Dict[str, Any]:
    cfg = _r2_config()
    if cfg:
        return {
            "backend": "cloudflare_r2",
            "persistent": True,
            "bucket": cfg["bucket"],
            "local_cache_dir": str(local_dir),
            "message": f"Cloudflare R2 kalıcı medya deposu etkin (bucket: {cfg['bucket']}).",
        }
    is_render = bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"))
    return {
        "backend": "local_disk",
        "persistent": not is_render,
        "bucket": None,
        "local_cache_dir": str(local_dir),
        "message": (
            "Render geçici diski kullanılıyor — R2_ENDPOINT_URL/R2_BUCKET eklenirse veya Oracle ARM/VPS'e geçilirse dosyalar kalıcı olur."
            if is_render
            else "Yerel kalıcı disk depolaması etkin."
        ),
    }


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sigv4_headers(
    method: str,
    url: str,
    payload_hash: str,
    access_key: str,
    secret_key: str,
    content_type: Optional[str] = None,
) -> Dict[str, str]:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc
    canonical_uri = urllib.parse.quote(parsed.path or "/", safe="/-_.~")
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    region = "auto"
    service = "s3"

    headers: Dict[str, str] = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if content_type:
        headers["content-type"] = content_type

    signed_keys = sorted(headers.keys())
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in signed_keys)
    signed_headers = ";".join(signed_keys)

    canonical_req = "\n".join([
        method.upper(),
        canonical_uri,
        parsed.query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])
    cred_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        cred_scope,
        hashlib.sha256(canonical_req.encode("utf-8")).hexdigest(),
    ])
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    out = {
        "X-Amz-Date": amz_date,
        "X-Amz-Content-Sha256": payload_hash,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{cred_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }
    if content_type:
        out["Content-Type"] = content_type
    return out


def _object_url(cfg: Dict[str, str], key: str) -> str:
    clean_key = key.lstrip("/")
    return f"{cfg['endpoint']}/{cfg['bucket']}/{clean_key}"


def _sha256_file(path: Path) -> Tuple[str, bytes]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), data


def put_file(local_path: Path, key: Optional[str] = None, content_type: str = "application/octet-stream") -> bool:
    """Dosyayı R2'ye yedekler. R2 yapılandırılmamışsa sessizce False döner."""
    cfg = _r2_config()
    if not cfg or not local_path.is_file():
        return False
    obj_key = key or f"media/{local_path.name}"
    url = _object_url(cfg, obj_key)
    try:
        payload_hash, data = _sha256_file(local_path)
        hdrs = _sigv4_headers("PUT", url, payload_hash, cfg["access_key"], cfg["secret_key"], content_type=content_type)
        resp = requests.put(url, headers=hdrs, data=data, timeout=60)
        if not resp.ok:
            logger.warning("[R2] Yükleme başarısız (%s): HTTP %s", obj_key, resp.status_code)
            return False
        return True
    except Exception as exc:
        logger.warning("[R2] Yükleme hatası (%s): %s", obj_key, exc)
        return False


def ensure_local(local_path: Path, key: Optional[str] = None) -> bool:
    """Yerelde dosya yoksa R2'den indirip atomik olarak yerel önbelleğe yazar."""
    if local_path.is_file():
        return True
    cfg = _r2_config()
    if not cfg:
        return False
    obj_key = key or f"media/{local_path.name}"
    url = _object_url(cfg, obj_key)
    empty_hash = hashlib.sha256(b"").hexdigest()
    try:
        hdrs = _sigv4_headers("GET", url, empty_hash, cfg["access_key"], cfg["secret_key"])
        resp = requests.get(url, headers=hdrs, timeout=45, stream=True)
        if not resp.ok:
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = local_path.with_name(f".{local_path.name}.r2tmp")
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    fh.write(chunk)
        os.replace(tmp, local_path)
        return local_path.is_file()
    except Exception as exc:
        logger.warning("[R2] Geri yükleme hatası (%s): %s", obj_key, exc)
        return False
