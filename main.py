#!/usr/bin/env python3
"""
yusasufhin.com — 7/24 Kesintisiz Bulut Web Kokpiti & Yapay Zeka Ağ Geçidi
Render üzerinde bilgisayar kapalıyken 7/24 kesintisiz çalışır.
"""
import os
import sys
import re
import hmac
import hashlib
import json
import time
import base64
import binascii
import inspect
import secrets
import threading
import urllib.parse
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Callable

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header, Query, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("YusasufhinCockpit")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

app = FastAPI(
    title="yusasufhin.com AI Studio & Kokpit",
    description="7/24 Kesintisiz Bulut Web Kokpiti",
    version="2026.11"
)

DEFAULT_PORT = 27491

# GPU işçisine (Kaggle/Colab) devredilecek render hedefleri (2026-11-11).
# Bu hedeflerle üretilen işler `gpu_kuyruk=True` alır; Kaggle/Colab işçisi
# `/api/worker/claim` ile alıp GERÇEK FLUX.2/Wan2.1 difüzyonuyla yeniden üretir.
GPU_HEDEFLERI = {"kaggle_32gb", "google_colab", "hybrid_cluster", "gpu"}

# CORS Ayarları (Özel Origin Kısıtlaması & CSRF Koruması)
ALLOWED_ORIGINS = [
    "https://yusasufhin.com",
    "https://yusasufhin-cockpit.onrender.com",
    f"http://localhost:{DEFAULT_PORT}",
    f"http://127.0.0.1:{DEFAULT_PORT}",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "HEAD", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Worker-Key", "X-Fabrika-Bridge-Secret"],
)

_REQ_COUNT = 0

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    global _REQ_COUNT
    _REQ_COUNT += 1
    if _REQ_COUNT % 50 == 0:
        import gc
        gc.collect()
    # Yetkisiz medya erişimini engelle (/static/media/* veya /media/* doğrudan servis edilemez)
    req_path = request.url.path.lower()
    if req_path.startswith("/static/media") or req_path.startswith("/media/"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Medya dosyalarına doğrudan erişim engellendi; yetkili /api/media/file ucunu kullanın."},
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), payment=()"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "media-src 'self' blob:; "
        "connect-src 'self' wss: https:;"
    )
    return response

# Statik Dosyaları Doğrudan Bağla (static/media middleware ile engellenir)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# -----------------------------------------------------------------------------
# 1. TEMEL SAYFALAR VE STATİK VARLIKLAR (EXPLICIT ROUTES)
# -----------------------------------------------------------------------------
@app.api_route("/ping", methods=["GET", "HEAD"])
@app.api_route("/healthz", methods=["GET", "HEAD"])
async def ping_health():
    """UptimeRobot ve harici 7/24 uyanık tutma servisleri için ultra-hafif ping."""
    return JSONResponse(content={"status": "ok", "service": "yusasufhin-cockpit", "live": True})

@app.api_route("/robots.txt", methods=["GET", "HEAD"])
async def get_robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /lab\n"
        "Disallow: /lab.html\n"
        "Disallow: /studio\n"
        "Disallow: /fabrika\n"
        "Disallow: /fabrika.html\n"
        "Disallow: /api/\n"
        "Sitemap: https://yusasufhin.com/sitemap.xml\n"
    )
    return Response(content=body, media_type="text/plain; charset=utf-8")

@app.api_route("/sitemap.xml", methods=["GET", "HEAD"])
async def get_sitemap_xml():
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url><loc>https://yusasufhin.com/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n'
        '</urlset>\n'
    )
    return Response(content=body, media_type="application/xml; charset=utf-8")

@app.api_route("/", methods=["GET", "HEAD"])
async def root_index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache, must-revalidate"})

@app.api_route("/index.html", methods=["GET", "HEAD"])
async def index_html():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache, must-revalidate"})

_NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}

@app.api_route("/studio", methods=["GET", "HEAD"])
@app.api_route("/lab", methods=["GET", "HEAD"])
@app.api_route("/lab.html", methods=["GET", "HEAD"])
async def lab_page():
    return FileResponse(STATIC_DIR / "lab.html", headers=_NO_CACHE)

@app.api_route("/fabrika", methods=["GET", "HEAD"])
@app.api_route("/fabrika.html", methods=["GET", "HEAD"])
async def fabrika_page():
    return FileResponse(STATIC_DIR / "fabrika.html", headers=_NO_CACHE)

@app.api_route("/manifest.json", methods=["GET", "HEAD"])
async def get_manifest():
    return FileResponse(STATIC_DIR / "manifest.json", media_type="application/manifest+json")

@app.api_route("/sw.js", methods=["GET", "HEAD"])
async def get_sw():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript", headers=_NO_CACHE)

@app.api_route("/site.css", methods=["GET", "HEAD"])
async def get_site_css():
    return FileResponse(STATIC_DIR / "site.css", media_type="text/css", headers=_NO_CACHE)

@app.api_route("/styles.css", methods=["GET", "HEAD"])
async def get_styles_css():
    return FileResponse(STATIC_DIR / "styles.css", media_type="text/css", headers=_NO_CACHE)

@app.api_route("/fabrika_desktop.css", methods=["GET", "HEAD"])
async def get_fabrika_desktop_css():
    return FileResponse(STATIC_DIR / "fabrika_desktop.css", media_type="text/css", headers=_NO_CACHE)

@app.api_route("/site.js", methods=["GET", "HEAD"])
async def get_site_js():
    return FileResponse(STATIC_DIR / "site.js", media_type="application/javascript", headers=_NO_CACHE)

@app.api_route("/app.js", methods=["GET", "HEAD"])
async def get_app_js():
    return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript", headers=_NO_CACHE)

@app.api_route("/fabrika_desktop.js", methods=["GET", "HEAD"])
async def get_fabrika_desktop_js():
    return FileResponse(STATIC_DIR / "fabrika_desktop.js", media_type="application/javascript", headers=_NO_CACHE)

@app.api_route("/lab.js", methods=["GET", "HEAD"])
async def get_lab_js():
    return FileResponse(STATIC_DIR / "lab.js", media_type="application/javascript", headers=_NO_CACHE)

@app.api_route("/fabrika_icon.svg", methods=["GET", "HEAD"])
async def get_icon():
    return FileResponse(STATIC_DIR / "fabrika_icon.svg", media_type="image/svg+xml")

@app.api_route("/worker.py", methods=["GET", "HEAD"])
@app.api_route("/gpu_worker.py", methods=["GET", "HEAD"])
async def get_gpu_worker_script():
    """Kaggle/Colab'ın `curl` ile indirdiği GERÇEK GPU işçisi.

    ÖNCEKİ DURUM: `/worker.py` SPA fallback'ine düşüyor ve HTML dönüyordu;
    Kaggle hücresi HTML'i Python sanıp çalıştırıyordu. Bu uç doğrudan
    `gpu_worker.py` dosyasını servis eder. Baştaki yorum satırı yalnızca
    indirilen dosyanın ne olduğunu belirtir; çalıştırılabilirliği değiştirmez.
    """
    kaynak = BASE_DIR / "gpu_worker.py"
    if not kaynak.is_file():
        return JSONResponse(status_code=404, content={"detail": "gpu_worker.py bulunamadı."})
    try:
        icerik = kaynak.read_text(encoding="utf-8")
    except OSError as e:
        logger.error("gpu_worker.py okunamadı: %s", e)
        return JSONResponse(status_code=500, content={"detail": "İşçi betiği okunamadı."})
    baslik = "# FABRİKA BULUT GPU İŞÇİSİ — gpu_worker.py (canlı sunucu kopyası)\n"
    return Response(content=baslik + icerik, media_type="text/x-python; charset=utf-8")


# -----------------------------------------------------------------------------
# 2. SİSTEM & KİMLİK DOĞRULAMA (AUTH) ENDPOINT'LERİ (SIFIR BACKDOOR, TTL, RATE LIMIT)
# -----------------------------------------------------------------------------
# Bellekte tutulan oturumlar: {token: {"user": str, "created_at": float, "expires_at": float}}
ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
REVOKED_TOKENS: set[str] = set()
_TOKEN_MIN_CREATED_AT: float = 0.0
SESSION_TTL_SEC: float = 86400.0  # 24 saat geçerlilik süresi

# IP bazlı brute-force koruması ve deneme sınırlayıcı
FAILED_ATTEMPTS: Dict[str, List[float]] = {}
MAX_FAILED_ATTEMPTS: int = 5
LOCKOUT_WINDOW_SEC: float = 60.0

# Bilinen, tahmin edilebilir veya ifşa olmuş güvensiz PIN kara listesi
DISALLOWED_PINS = {"192300", "123456", "000000", "111111", "091091", "654321", "123123", "999999"}

_INTERNAL_PROXY_NETS = None

def _is_trusted_proxy_ip(ip_str: str) -> bool:
    import ipaddress
    global _INTERNAL_PROXY_NETS
    if _INTERNAL_PROXY_NETS is None:
        _INTERNAL_PROXY_NETS = tuple(ipaddress.ip_network(n) for n in (
            "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
            "100.64.0.0/10", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10",
        ))
    try:
        ip_obj = ipaddress.ip_address(ip_str)
        return any(ip_obj in net for net in _INTERNAL_PROXY_NETS)
    except ValueError:
        return False

def get_client_ip(req: Request) -> str:
    """İstemci IP adresini sahte başlık (spoofing) ve paylaşımlı LB kilitlemesine karşı güvenli çözer."""
    import ipaddress

    direct_host = (req.client.host if req.client and req.client.host else "127.0.0.1").strip()
    if not _is_trusted_proxy_ip(direct_host):
        return direct_host

    # Yalnızca yusasufhin.com (Cloudflare arkası) trafiğinde CF-Connecting-IP geçerli IP ise kabul et
    host_hdr = (req.headers.get("host") or "").lower().split(":", 1)[0]
    cf_ip = (req.headers.get("cf-connecting-ip") or "").strip()
    if cf_ip and host_hdr.endswith("yusasufhin.com"):
        try:
            ipaddress.ip_address(cf_ip)
            return cf_ip
        except ValueError:
            pass

    # Render / ters vekil: X-Forwarded-For içindeki en sağdaki dahili-olmayan IP vekil tarafından eklenir
    xff = req.headers.get("x-forwarded-for") or ""
    if xff:
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        for candidate in reversed(hops):
            try:
                ipaddress.ip_address(candidate)
                if not _is_trusted_proxy_ip(candidate):
                    return candidate
            except ValueError:
                continue

    return direct_host

MAX_TRACKED_IPS = 2048
MAX_ACTIVE_SESSIONS = 512

def _prune_ip_dict(store: Dict[str, List[float]], window_sec: float) -> None:
    if len(store) <= MAX_TRACKED_IPS:
        return
    now = time.time()
    dead = [k for k, ts_list in store.items() if not ts_list or (now - ts_list[-1]) >= window_sec]
    for k in dead:
        store.pop(k, None)
    if len(store) > MAX_TRACKED_IPS:
        for k in list(store.keys())[: len(store) - MAX_TRACKED_IPS]:
            store.pop(k, None)

def is_rate_limited(ip: str) -> Tuple[bool, int]:
    """IP adresi için rate limit kontrolü yapar."""
    now = time.time()
    attempts = [t for t in FAILED_ATTEMPTS.get(ip, []) if now - t < LOCKOUT_WINDOW_SEC]
    if attempts:
        FAILED_ATTEMPTS[ip] = attempts
    else:
        FAILED_ATTEMPTS.pop(ip, None)
    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        wait_sec = int(LOCKOUT_WINDOW_SEC - (now - attempts[0]))
        return True, max(1, wait_sec)
    return False, 0

def record_failed_attempt(ip: str):
    """Başarısız oturum denemesini kaydeder."""
    _prune_ip_dict(FAILED_ATTEMPTS, LOCKOUT_WINDOW_SEC)
    now = time.time()
    attempts = [t for t in FAILED_ATTEMPTS.get(ip, []) if now - t < LOCKOUT_WINDOW_SEC]
    attempts.append(now)
    FAILED_ATTEMPTS[ip] = attempts

def reset_failed_attempts(ip: str):
    """Başarılı girişte deneme geçmişini temizler."""
    if ip in FAILED_ATTEMPTS:
        del FAILED_ATTEMPTS[ip]

def _read_or_create_secret(dosya: Path, env_adlari: Tuple[str, ...], uzunluk: int = 32) -> str:
    """Gizli anahtarı env'den, yoksa kalıcı dosyadan okur; yoksa üretip kaydeder.

    Depoya gömülü sabit anahtar YOKTUR (Kural: sırlar repoda tutulmaz). Dosya
    yalnız süreç sahibi tarafından okunabilir (0600) ve atomik yazılır.
    """
    for ad in env_adlari:
        deger = os.environ.get(ad)
        if deger and deger.strip():
            return deger.strip()
    try:
        if dosya.is_file():
            mevcut = dosya.read_text(encoding="utf-8").strip()
            if mevcut:
                return mevcut
    except OSError as e:
        logger.warning("Gizli anahtar okunamadı (%s): %s", dosya.name, e)

    yeni = secrets.token_hex(uzunluk)
    try:
        dosya.parent.mkdir(parents=True, exist_ok=True)
        gecici = dosya.with_name(f".{dosya.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        gecici.write_text(yeni + "\n", encoding="utf-8")
        os.chmod(gecici, 0o600)
        os.replace(gecici, dosya)
        os.chmod(dosya, 0o600)
    except OSError as e:
        logger.warning("Gizli anahtar kalıcı yazılamadı (%s): %s — bu süreç için üretildi", dosya.name, e)
    return yeni


SESSION_SIGNING_SECRET = _read_or_create_secret(
    DATA_DIR / ".session_secret",
    ("SESSION_SIGNING_SECRET", "FABRIKA_SESSION_SECRET"),
)

_WORKER_KEY_LOCK = threading.Lock()

def get_worker_key() -> str:
    """GPU işçisi anahtarı: env FABRIKA_WORKER_KEY → DATA_DIR/.worker_key (otomatik)."""
    with _WORKER_KEY_LOCK:
        return _read_or_create_secret(DATA_DIR / ".worker_key", ("FABRIKA_WORKER_KEY",))

def create_session(user: str = "Yusuf Şahin", prefix: str = "tok") -> str:
    """24 saat TTL süreli yeni kriptografik ve sunucu yeniden başlamalarına dayanıklı oturum tokenı üretir."""
    now = int(time.time())
    exp = int(now + int(SESSION_TTL_SEC))
    sig_raw = f"{user}:{now}:{exp}"
    sig = hmac.new(SESSION_SIGNING_SECRET.encode(), sig_raw.encode(), hashlib.sha256).hexdigest()[:24]
    token = f"{prefix}_{now}_{exp}_{sig}"
    if len(ACTIVE_SESSIONS) >= MAX_ACTIVE_SESSIONS:
        oldest = sorted(ACTIVE_SESSIONS.keys(), key=lambda k: ACTIVE_SESSIONS[k].get("created_at", 0))[:64]
        for k in oldest:
            ACTIVE_SESSIONS.pop(k, None)
    ACTIVE_SESSIONS[token] = {
        "user": user,
        "created_at": now,
        "expires_at": exp
    }
    return token

def is_session_valid(token: Optional[str]) -> bool:
    """Token'ın aktifliğini ve süresini kontrol eder; HMAC imzasını doğrular."""
    if not token or token in REVOKED_TOKENS:
        return False
    # 1. Aktif bellek oturumu kontrolü
    if token in ACTIVE_SESSIONS:
        session = ACTIVE_SESSIONS[token]
        if time.time() > session.get("expires_at", 0):
            del ACTIVE_SESSIONS[token]
            return False
        return True

    # 2. Sunucu yeniden başlasa bile geçerli HMAC imza doğrulaması (24 saat)
    try:
        parts = token.split("_")
        if len(parts) >= 4 and parts[0] == "tok":
            created_at = int(float(parts[-3]))
            exp = int(float(parts[-2]))
            sig = parts[-1]
            if time.time() > exp or created_at < _TOKEN_MIN_CREATED_AT:
                return False
            sig_raw = f"Yusuf Şahin:{created_at}:{exp}"
            expected_sig = hmac.new(SESSION_SIGNING_SECRET.encode(), sig_raw.encode(), hashlib.sha256).hexdigest()[:24]
            if hmac.compare_digest(sig, expected_sig):
                ACTIVE_SESSIONS[token] = {
                    "user": "Yusuf Şahin",
                    "created_at": created_at,
                    "expires_at": exp
                }
                return True
    except Exception:
        pass
    return False

def get_secret_from_env(key_name: str) -> Optional[str]:
    """Ortam değişkenlerinden veya yerel yapılandırmadan anahtar okur."""
    val = os.environ.get(key_name)
    if val:
        return val.strip().strip('"').strip("'")
    candidates = [
        BASE_DIR / ".env",
        Path.home() / "Desktop" / "PYTHON PROJECTS" / "Fabrika" / "Persona" / ".env",
    ]
    for c in candidates:
        if c.exists():
            try:
                for line in c.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip().lower() == key_name.lower():
                        clean_v = v.strip().strip('"').strip("'")
                        if clean_v:
                            return clean_v
            except Exception:
                pass
    return None

def get_valid_passwords() -> List[str]:
    """Parolalar YALNIZ ortam/.env dosyasından okunur; repoda gömülü yedek yoktur."""
    keys = ["FABRIKA_GATEWAY_PASSWORD", "GATEWAY_PASSWORD", "alanadisifre", "alansifre"]
    found: List[str] = []
    for k in keys:
        s = get_secret_from_env(k)
        if s and s not in found:
            found.append(s)
    return found

def get_valid_pins() -> List[str]:
    """PIN YALNIZ ortam/.env dosyasından okunur; gömülü/yedek PIN yoktur."""
    keys = ["GATEWAY_PIN", "FABRIKA_GATEWAY_PIN", "alanadisifre", "alansifre"]
    found: List[str] = []
    for k in keys:
        s = get_secret_from_env(k)
        if s and s not in found and s not in DISALLOWED_PINS:
            found.append(s)
    return found

async def verify_auth(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None)
) -> str:
    """Durum değiştiren ve korumalı tüm uç noktalar için zorunlu token doğrulayıcı."""
    auth_tok = (authorization or "").replace("Bearer ", "").strip() or (token or "").strip()
    if not auth_tok or not is_session_valid(auth_tok):
        raise HTTPException(
            status_code=401,
            detail="Yetkilendirme gerekli (Token eksik, geçersiz veya oturum süresi dolmuş)."
        )
    return auth_tok

# -----------------------------------------------------------------------------
# 2b. GPU İŞÇİ KİMLİĞİ & İŞ DEPOSU (kilitli + atomik)
# -----------------------------------------------------------------------------
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_WORKER_UPLOAD_BYTES = 250 * 1024 * 1024
MAX_INPUT_IMAGE_BYTES = 15 * 1024 * 1024
CLAIM_TTL_SEC = 45 * 60
JOBS_LOCK = threading.Lock()

def _bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    parcalar = authorization.split(None, 1)
    if len(parcalar) == 2 and parcalar[0].lower() == "bearer":
        return parcalar[1].strip()
    return authorization.strip()

async def verify_worker_key(
    x_worker_key: Optional[str] = Header(None, alias="X-Worker-Key"),
    authorization: Optional[str] = Header(None),
) -> str:
    """GPU işçisi uçları için zorunlu anahtar doğrulaması (X-Worker-Key veya Bearer)."""
    saglanan = (x_worker_key or "").strip() or _bearer_token(authorization)
    beklenen = get_worker_key()
    if not saglanan or not beklenen or not hmac.compare_digest(
        saglanan.encode("utf-8"), beklenen.encode("utf-8")
    ):
        raise HTTPException(
            status_code=403,
            detail="Geçersiz veya eksik GPU işçi anahtarı (X-Worker-Key / Bearer).",
        )
    return "worker"

def _validate_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        raise HTTPException(
            status_code=400,
            detail="Geçersiz job_id (yalnız A-Z a-z 0-9 . _ -; en fazla 80 karakter).",
        )
    return job_id

def _jobs_path() -> Path:
    return DATA_DIR / "video_jobs.json"

def _load_jobs_unlocked() -> Dict[str, Any]:
    yol = _jobs_path()
    if not yol.is_file():
        return {"jobs": []}
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error("[Jobs] %s okunamadı, boş kuyruk kullanılıyor: %s", yol.name, e)
        return {"jobs": []}
    if isinstance(veri, list):
        veri = {"jobs": veri}
    if not isinstance(veri, dict):
        return {"jobs": []}
    if not isinstance(veri.get("jobs"), list):
        veri["jobs"] = []
    return veri

def _save_jobs_unlocked(veri: Dict[str, Any]) -> None:
    yol = _jobs_path()
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_name(f".{yol.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(gecici, yol)

def _update_jobs(degistirici: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    """video_jobs.json'u kilitle oku-değiştir-atomik yaz."""
    with JOBS_LOCK:
        veri = _load_jobs_unlocked()
        degistirici(veri)
        _save_jobs_unlocked(veri)
        return veri

def _append_job_record(job: Dict[str, Any]) -> None:
    def _ekle(veri: Dict[str, Any]) -> None:
        veri.setdefault("jobs", []).append(job)
    try:
        _update_jobs(_ekle)
    except OSError as e:
        logger.error("[Jobs] İş kaydı yazılamadı (%s): %s", job.get("job_id"), e)

def _is_job(j: Dict[str, Any], job_id: str) -> bool:
    return j.get("job_id") == job_id or j.get("id") == job_id

def _release_expired_claims_data(veri: Dict[str, Any]) -> bool:
    """45 dakikadan uzun süre 'isleniyor' kalan işleri 'bekliyor'a geri bırakır."""
    simdi = time.time()
    degisti = False
    for j in veri.get("jobs", []):
        if j.get("gpu_durum") != "isleniyor":
            continue
        try:
            claim_ts = float(j.get("claimed_at") or 0)
        except (TypeError, ValueError):
            claim_ts = 0
        if simdi - claim_ts <= CLAIM_TTL_SEC:
            continue
        j["gpu_durum"] = "bekliyor"
        j["status"] = "kuyrukta (GPU işçisi bekliyor)"
        j["current_stage"] = "claim süresi doldu — kuyruğa geri alındı"
        j.pop("claimed_by", None)
        j.pop("claimed_at", None)
        degisti = True
    return degisti

def _release_expired_claims() -> None:
    with JOBS_LOCK:
        veri = _load_jobs_unlocked()
        if _release_expired_claims_data(veri):
            _save_jobs_unlocked(veri)

def _new_job_id(prefix: str = "JOB") -> str:
    return f"{prefix}-{int(time.time() * 1000)}-{secrets.token_hex(3)}"

@app.api_route("/api/auth/public_info", methods=["GET", "HEAD"])
async def public_info():
    """Genel sistem durumu — yalnızca güvenli ve doğrulanmış temel bilgi döner (Kural 1)."""
    from mac_bridge import bridge_hub
    from cloud_storage import storage_status

    mac_on = bridge_hub.is_online()
    st = storage_status(MEDIA_DIR)
    return {
        "status": "online",
        "domain": "https://yusasufhin.com/",
        "version": "2026.11",
        "timestamp": time.time(),
        "auth_methods": ["password", "pin"],
        "cluster_vram_gb": 0.0,
        "mac_bridge_online": mac_on,
        "storage_backend": st["backend"],
        "storage_persistent": st["persistent"],
        "active_services": {
            "web_cockpit": "online",
            "mac_bridge": "online" if mac_on else "offline",
            "video_studio": "ready",
            "tts_audio": "ready",
            "youtube_upload": "ready",
            "kaggle_gpu_worker": "active" if _has_live_gpu_worker() else "standby",
        },
    }

@app.post("/api/auth/login")
async def login(req: Request):
    ip = get_client_ip(req)
    limited, wait_sec = is_rate_limited(ip)
    if limited:
        return JSONResponse(status_code=429, content={"success": False, "message": f"Çok fazla hatalı deneme! Lütfen {wait_sec} saniye bekleyin."})

    try:
        body = await req.json()
    except Exception:
        body = {}
    password = str(body.get("password", "")).strip()
    if not password:
        record_failed_attempt(ip)
        return JSONResponse(status_code=400, content={"success": False, "message": "Parola boş olamaz."})

    valid_passwords = get_valid_passwords()
    if not valid_passwords:
        return JSONResponse(status_code=500, content={"success": False, "message": "Sunucuda yetkili parola yapılandırılmamış."})

    pwd_bytes = password.encode("utf-8")
    matched = any(hmac.compare_digest(pwd_bytes, str(vp).strip().encode("utf-8")) for vp in valid_passwords)
    if matched:
        reset_failed_attempts(ip)
        token = create_session(user="Yusuf Şahin", prefix="tok")
        return {"success": True, "token": token, "username": "Yusuf Şahin", "message": "Giriş başarılı."}

    record_failed_attempt(ip)
    return JSONResponse(status_code=401, content={"success": False, "message": "Geçersiz şifre."})

@app.post("/api/auth/verify_pin")
async def verify_pin(req: Request):
    ip = get_client_ip(req)
    limited, wait_sec = is_rate_limited(ip)
    if limited:
        return JSONResponse(status_code=429, content={"success": False, "message": f"Çok fazla hatalı deneme! Lütfen {wait_sec} saniye bekleyin."})

    try:
        body = await req.json()
    except Exception:
        body = {}
    pin = str(body.get("pin", "")).strip()
    if not pin or pin in DISALLOWED_PINS:
        record_failed_attempt(ip)
        return JSONResponse(status_code=401, content={"success": False, "message": "Geçersiz veya engellenmiş PIN kodu."})

    valid_pins = [p for p in get_valid_pins() if p not in DISALLOWED_PINS]
    if not valid_pins:
        return JSONResponse(status_code=500, content={"success": False, "message": "Sunucuda geçerli PIN kodu yapılandırılmamış."})

    pin_bytes = pin.encode("utf-8")
    matched = any(hmac.compare_digest(pin_bytes, str(vp).strip().encode("utf-8")) for vp in valid_pins)
    if matched:
        reset_failed_attempts(ip)
        token = create_session(user="Yusuf Şahin", prefix="tok_pin")
        return {"success": True, "token": token, "username": "Yusuf Şahin", "message": "PIN doğrulandı."}

    record_failed_attempt(ip)
    return JSONResponse(status_code=401, content={"success": False, "message": "Geçersiz PIN kodu."})

@app.api_route("/api/auth/check", methods=["GET", "POST"])
async def auth_check(authorization: Optional[str] = Header(None)):
    token = (authorization or "").replace("Bearer ", "").strip()
    if token and is_session_valid(token):
        return {"authenticated": True, "user": "Yusuf Şahin"}
    return JSONResponse(status_code=401, content={"authenticated": False, "user": None})

@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    token = (authorization or "").replace("Bearer ", "").strip()
    if token and is_session_valid(token):
        if len(REVOKED_TOKENS) >= 4096:
            REVOKED_TOKENS.clear()
        REVOKED_TOKENS.add(token)
        ACTIVE_SESSIONS.pop(token, None)
    return {"success": True}

@app.post("/api/auth/change_pin")
async def change_pin(req: Request, token: str = Depends(verify_auth)):
    try:
        body = await req.json()
    except Exception:
        body = {}
    old_pin = str(body.get("old_pin", "")).strip()
    new_pin = str(body.get("new_pin", "")).strip()

    valid_pins = [p for p in get_valid_pins() if p not in DISALLOWED_PINS]
    if not valid_pins:
        raise HTTPException(status_code=500, detail="Mevcut PIN konfigürasyonu bulunamadı.")

    matched = any(hmac.compare_digest(old_pin.encode("utf-8"), str(vp).strip().encode("utf-8")) for vp in valid_pins)
    if not matched:
        raise HTTPException(status_code=401, detail="Mevcut PIN kodu hatalı!")

    if len(new_pin) != 6 or not new_pin.isdigit():
        raise HTTPException(status_code=400, detail="Yeni PIN tam olarak 6 haneli rakamlardan oluşmalıdır.")

    if new_pin in DISALLOWED_PINS:
        raise HTTPException(status_code=400, detail="Bu PIN kodu güvenlik gerekçesiyle kullanılamaz.")

    if any(hmac.compare_digest(new_pin.encode("utf-8"), str(vp).strip().encode("utf-8")) for vp in valid_pins):
        raise HTTPException(status_code=400, detail="Yeni PIN mevcut PIN ile aynı olamaz.")

    # Persona/.env ve .env dosyalarını güncelle
    candidates = [
        BASE_DIR / ".env",
        Path.home() / "Desktop" / "PYTHON PROJECTS" / "Fabrika" / "Persona" / ".env",
    ]
    for c in candidates:
        if c.exists():
            try:
                lines = c.read_text(encoding="utf-8").splitlines()
                new_lines = []
                found = False
                for line in lines:
                    if line.strip().startswith("GATEWAY_PIN="):
                        new_lines.append(f"GATEWAY_PIN={new_pin}")
                        found = True
                    else:
                        new_lines.append(line)
                if not found:
                    new_lines.append(f"GATEWAY_PIN={new_pin}")
                c.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            except Exception as e:
                logger.error("PIN kaydedilemedi: %s", e)

    os.environ["GATEWAY_PIN"] = new_pin

    # Tüm eski oturumları feshet ve yeni oturum tokenı üret
    global _TOKEN_MIN_CREATED_AT
    REVOKED_TOKENS.update(ACTIVE_SESSIONS.keys())
    _TOKEN_MIN_CREATED_AT = time.time()
    ACTIVE_SESSIONS.clear()
    new_tok = create_session(user="Yusuf Şahin", prefix="tok_pin_change")
    return {"success": True, "token": new_tok, "message": "PIN başarıyla güncellendi ve eski oturumlar kapatıldı."}

@app.post("/api/auth/biometric/register")
@app.post("/api/auth/biometric/login")
async def biometric_auth(req: Request):
    """Biyometrik WebAuthn sunucu doğrulaması henüz aktif değildir."""
    raise HTTPException(
        status_code=501,
        detail="Biyometrik WebAuthn sunucu doğrulaması henüz aktif değildir. Lütfen PIN veya parola kullanın."
    )

# -----------------------------------------------------------------------------
# 3. SİSTEM İSTATİSTİKLERİ, İLETİŞİM FORMU & LİNK HAVUZU
# -----------------------------------------------------------------------------
CONTACT_RATE: Dict[str, List[float]] = {}

@app.post("/api/contact")
async def public_contact(req: Request):
    """Genel vitrin iletişim formu: Resend / SMTP / Mac Port-443 Gmail Rölesi + Telegram + gelen kutusu."""
    from contact_notifier import dispatch_contact_notification, make_layered_env_getter
    from mac_bridge import bridge_hub

    ip = get_client_ip(req)
    _prune_ip_dict(CONTACT_RATE, 300.0)
    now = time.time()
    recent = [t for t in CONTACT_RATE.get(ip, []) if now - t < 300.0]
    if len(recent) >= 5:
        return JSONResponse(status_code=429, content={"success": False, "detail": "Çok sık mesaj gönderildi; lütfen birkaç dakika sonra tekrar deneyin."})
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = re.sub(r"[\r\n]+", " ", str(body.get("name") or "")).strip()[:100]
    email = re.sub(r"[\r\n\s]+", "", str(body.get("email") or "")).strip()[:160]
    message = str(body.get("message") or "").strip()[:2000]
    if len(name) < 2 or "@" not in email or "." not in email.split("@")[-1] or len(message) < 10:
        return JSONResponse(status_code=400, content={"success": False, "detail": "Lütfen geçerli bir ad, e-posta adresi ve en az 10 karakterlik mesaj girin."})

    recent.append(now)
    CONTACT_RATE[ip] = recent
    env_getter = make_layered_env_getter(DATA_DIR, get_secret_from_env)

    delivery = await run_in_threadpool(
        lambda: dispatch_contact_notification(
            name=name,
            sender_email=email,
            message=message,
            get_env=env_getter,
            mac_relay_fn=lambda p: bridge_hub.relay_contact_email(p, allow_offline_queue=True),
        )
    )

    record = {
        "timestamp": now,
        "name": name,
        "email": email,
        "message": message,
        "ip": ip,
        "email_sent": delivery["email_sent"],
        "email_queued_mac": delivery.get("email_queued_mac", False),
        "telegram_sent": delivery["telegram_sent"],
        "delivery_channel": delivery["delivery_channel"],
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with (DATA_DIR / "contact_inquiries.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("İletişim kaydı yazılamadı: %s", exc)

    if delivery["email_sent"]:
        user_msg = f"Mesajınız doğrudan {delivery['to_email']} adresine iletildi. En kısa sürede dönüş yapılacaktır."
    elif delivery.get("email_queued_mac") or delivery["telegram_sent"]:
        user_msg = "Mesajınız iletildi ve bildirim kuyruğuna alındı. En kısa sürede e-posta üzerinden dönüş yapılacaktır."
    else:
        user_msg = (
            "Mesajınız site gelen kutusuna kaydedildi (sunucuda otomatik e-posta/SMTP aktarımı henüz bağlı değil). "
            "Hızlı yanıt için doğrudan e-posta uygulamasıyla da gönderebilirsiniz."
        )

    return {
        "success": True,
        "email_sent": delivery["email_sent"],
        "email_queued_mac": delivery.get("email_queued_mac", False),
        "telegram_sent": delivery["telegram_sent"],
        "notified": bool(delivery["email_sent"] or delivery.get("email_queued_mac") or delivery["telegram_sent"]),
        "delivery_channel": delivery["delivery_channel"],
        "mailto_fallback_url": delivery["mailto_fallback_url"],
        "message": user_msg,
    }


@app.get("/api/contact/messages", dependencies=[Depends(verify_auth)])
async def list_contact_messages(limit: int = Query(30)):
    """Yetkili yönetici için gelen iletişim mesajlarını ve bildirim kanalı durumunu döner."""
    from contact_notifier import make_layered_env_getter, notifier_status, read_contact_messages
    from mac_bridge import bridge_hub

    st = bridge_hub.get_status()
    mac_stats = st.get("stats") or {}
    env_getter = make_layered_env_getter(DATA_DIR, get_secret_from_env)
    items = read_contact_messages(DATA_DIR, limit=limit)
    return {
        "success": True,
        "count": len(items),
        "items": items,
        "notifier": notifier_status(
            env_getter,
            mac_online=bool(st.get("online")),
            mac_smtp_ready=bool(mac_stats.get("smtp_ready")),
        ),
    }


@app.post("/api/contact/config", dependencies=[Depends(verify_auth)])
async def update_contact_mail_config(req: Request):
    """Yöneticinin ys@yusasufhin.com uygulama şifresini veya Resend anahtarını 0600 izinle kaydeder ve Mac'e senkronlar."""
    from contact_notifier import DEFAULT_TO_EMAIL, make_layered_env_getter, notifier_status, save_mail_config
    from mac_bridge import bridge_hub

    try:
        body = await req.json()
    except Exception:
        body = {}
    smtp_pass = str(body.get("smtp_pass") or "").strip()
    resend_key = str(body.get("resend_api_key") or "").strip()
    to_email = re.sub(r"[\r\n\s]+", "", str(body.get("to_email") or DEFAULT_TO_EMAIL)).strip() or DEFAULT_TO_EMAIL
    smtp_user = re.sub(r"[\r\n\s]+", "", str(body.get("smtp_user") or to_email)).strip() or to_email
    smtp_host = re.sub(r"[\r\n\s]+", "", str(body.get("smtp_host") or "smtp.gmail.com")).strip() or "smtp.gmail.com"
    smtp_port = int(body.get("smtp_port") or 587)

    updates: Dict[str, Optional[str]] = {"CONTACT_TO_EMAIL": to_email}
    if smtp_pass:
        updates["SMTP_HOST"] = smtp_host
        updates["SMTP_PORT"] = str(smtp_port)
        updates["SMTP_USER"] = smtp_user
        updates["SMTP_PASS"] = smtp_pass
    if resend_key:
        updates["RESEND_API_KEY"] = resend_key

    save_mail_config(DATA_DIR, updates)
    pushed_mac = bridge_hub.push_mail_config_to_mac(smtp_user, smtp_pass, smtp_host, smtp_port) if smtp_pass else False
    st = bridge_hub.get_status()
    env_getter = make_layered_env_getter(DATA_DIR, get_secret_from_env)
    return {
        "success": True,
        "pushed_to_mac": pushed_mac,
        "notifier": notifier_status(env_getter, mac_online=bool(st.get("online")), mac_smtp_ready=pushed_mac),
    }


@app.post("/api/contact/test", dependencies=[Depends(verify_auth)])
async def send_test_contact_email():
    """Yönetici için ys@yusasufhin.com adresine gerçek uçtan uca test e-postası gönderir."""
    from contact_notifier import dispatch_contact_notification, make_layered_env_getter
    from mac_bridge import bridge_hub

    env_getter = make_layered_env_getter(DATA_DIR, get_secret_from_env)
    res = await run_in_threadpool(
        lambda: dispatch_contact_notification(
            name="Fabrika Doğrulama Testi",
            sender_email="ys@yusasufhin.com",
            message="Bu mesaj yusasufhin.com iletişim formu e-posta teslim hattını doğrulamak için gönderilmiştir.",
            get_env=env_getter,
            mac_relay_fn=lambda p: bridge_hub.relay_contact_email(p, allow_offline_queue=False, timeout_sec=14.0),
        )
    )
    return {"success": bool(res.get("email_sent")), **res}

@app.get("/api/system/stats", dependencies=[Depends(verify_auth)])
async def get_system_stats():
    from mac_bridge import bridge_hub
    from cloud_storage import storage_status

    link_count = 0
    ls_path = DATA_DIR / "link_store.json"
    if ls_path.exists():
        try:
            raw = json.loads(ls_path.read_text(encoding="utf-8"))
            links = raw if isinstance(raw, list) else raw.get("links", raw.get("items", []))
            link_count = len(links)
        except Exception:
            pass

    rea_score = None
    rea_scans = 0
    scans_file = DATA_DIR / "rea_scans.json"
    if scans_file.exists():
        try:
            records = json.loads(scans_file.read_text(encoding="utf-8"))
            if isinstance(records, list) and records:
                rea_scans = len(records)
                rea_score = round(sum(r.get("score", 100) for r in records) / rea_scans, 1)
        except Exception:
            pass

    mac_st = bridge_hub.get_status()
    mac_stats = mac_st.get("stats") or {}
    mac_online = bool(mac_st.get("online"))

    return {
        "cpu": mac_stats.get("cpu") if mac_online else None,
        "ram": mac_stats.get("ram") if mac_online else None,
        "status": "online",
        "mac_bridge_online": mac_online,
        "mac_bridge": mac_st,
        "storage": storage_status(MEDIA_DIR),
        "link_pool_count": mac_stats.get("link_pool_count") if (mac_online and mac_stats.get("link_pool_count")) else link_count,
        "rea_score": rea_score if rea_score is not None else (mac_stats.get("rea_score") if mac_online else None),
        "rea_scans": rea_scans,
        "telemetry": (
            "Canlı Mac Fabrika telemetrisi (Port 443 köprüsü)"
            if mac_online
            else "Mac Fabrika çevrimdışı (bulut kuyruğu etkin)"
        ),
        "tunnel": {
            "active": bool(mac_online and mac_stats.get("named_tunnel_active")),
            "named_tunnel_active": "true" if (mac_online and mac_stats.get("named_tunnel_active")) else "false",
            "url": mac_stats.get("custom_domain") if mac_online else "https://yusasufhin.com",
            "provider": "Mac Port-443 HTTPS Köprüsü" if mac_online else "Bulut Kokpiti (Mac çevrimdışı)",
        }
    }

@app.get("/api/links/pool", dependencies=[Depends(verify_auth)])
async def get_links_pool(q: Optional[str] = None, category: Optional[str] = None):
    ls_path = DATA_DIR / "link_store.json"
    links = []
    if ls_path.exists():
        try:
            raw = json.loads(ls_path.read_text(encoding="utf-8"))
            links = raw if isinstance(raw, list) else raw.get("links", raw.get("items", []))
        except Exception:
            links = []

    q_clean = (q or "").strip().lower()
    cat_clean = (category or "").strip().lower()

    results = []
    for idx, item in enumerate(links):
        if not isinstance(item, dict):
            continue
        lid = item.get("id", idx + 1)
        title = str(item.get("title") or item.get("name") or f"Proje #{lid}")
        url = str(item.get("url") or "")
        summary = str(item.get("summary") or item.get("description") or item.get("text") or "")
        combined = f"{title} {summary} {url}".lower()

        if any(w in combined for w in ["ui", "design", "tasarım", "css", "jiro", "oil", "bento", "shader", "motion"]):
            item_cat = "tasarim_ui"
        elif any(w in combined for w in ["rea", "security", "güvenlik", "cve", "pentest", "waf"]):
            item_cat = "guvenlik"
        elif any(w in combined for w in ["tts", "audio", "ses", "video", "kokoro", "flux", "image"]):
            item_cat = "medya_ses"
        elif any(w in combined for w in ["agent", "ajan", "mcp", "claude", "pilotdeck", "skill"]):
            item_cat = "ajan_mimari"
        else:
            item_cat = "yapay_zeka"

        if cat_clean and cat_clean != "all" and item_cat != cat_clean:
            continue
        if q_clean and q_clean not in combined:
            continue

        results.append({
            "id": lid,
            "title": title[:95],
            "url": url,
            "summary": summary[:260],
            "category": item_cat,
        })

    results.reverse()
    return {
        "total": len(links),
        "filtered_count": len(results),
        "items": results[:60],
    }

# -----------------------------------------------------------------------------
# 4. KOVA LAB MODEL KATALOĞU & İNTERAKTİF STÜDYO
# -----------------------------------------------------------------------------
@app.get("/api/video/tesis", dependencies=[Depends(verify_auth)])
async def get_video_tesis():
    """YZ video hattının canlı ortamda çalışabilirliğini raporlar.

    2026-11-11: Render'da `HF_TOKEN` tanımlı olmadığı için hat sessizce
    yedek başlık kartına düşüyordu. Bu uç, eksik olan tam adımı döner.
    """
    try:
        from ai_video_montaj import tesis_durumu

        return {"success": True, **tesis_durumu()}
    except Exception as e:
        return {"success": False, "hata": str(e)}


@app.get("/api/lab/models", dependencies=[Depends(verify_auth)])
async def get_lab_models():
    models_file = DATA_DIR / "kova_lab_models.json"
    if models_file.exists():
        try:
            veri = json.loads(models_file.read_text(encoding="utf-8"))
            if isinstance(veri, dict):
                modeller = veri.get("modeller")
                if isinstance(modeller, list):
                    # Sayı JSON içeriğinden türetilir; sabit "66" yok (Kural 1).
                    veri["toplam"] = len(modeller)
                elif isinstance(veri.get("gruplar"), list):
                    veri["toplam"] = sum(
                        int(g.get("adet") or len(g.get("modeller") or []))
                        for g in veri["gruplar"]
                        if isinstance(g, dict)
                    )
            return veri
        except Exception as e:
            logger.warning("KovaLab modelleri okunamadı: %s", e)
    return {
        "toplam": 0,
        "ucretsiz": 0,
        "otomatik": 0,
        "havuz_eklenen": 0,
        "konum": "Veri Yok",
        "kovalab_var": False,
        "gruplar": [],
        "modeller": [],
        "mesaj": "Kova Lab model kataloğu (data/kova_lab_models.json) bulunamadı."
    }

def _mp4_oynatilabilir(yol: Path) -> bool:
    """MP4 gerçekten oynatılabilir mi? (ftyp + moov + mdat + asgari boyut)

    2026-11-10: Eski render hattı ffmpeg'i 15. sn'de öldürdüğü için galeride
    yalnız `ftyp` başlığı olan 2 KB'lık dosyalar kalıyordu; tarayıcı
    "moov atom not found" ile hiç oynamıyordu. Böyle dosyalar listelenmez ve
    `/api/media/file` üzerinden de sunulmaz.
    """
    try:
        from video_render import mp4_gecerli_mi

        return mp4_gecerli_mi(yol)[0]
    except Exception:
        try:
            return yol.is_file() and yol.stat().st_size >= 20 * 1024
        except OSError:
            return False


@app.get("/api/lab/history", dependencies=[Depends(verify_auth)])
async def get_lab_history(limit: int = Query(12)):
    """
    Üretilen videoların GERÇEK geçmişi (2026-11-10).

    ÖNCEKİ DURUM: sabit `{"items": [], "count": 0}` dönüyordu — kullanıcı
    ürettiği videoyu sitede BULAMIYORDU ("üretilenleri sitede bulamıyorum").
    ARTIK: `data/video_jobs.json` + `video_factory/studio_jobs.json` okunur,
    yalnız `output_url`'i olan (gerçekten üretilmiş) işler listelenir.
    """
    items: List[Dict[str, Any]] = []
    gorulen: set = set()

    # 1) video_jobs.json (uçtan kaydedilenler)
    for kaynak in (DATA_DIR / "video_jobs.json", BASE_DIR / "video_factory" / "studio_jobs.json"):
        try:
            if not kaynak.is_file():
                continue
            veri = json.loads(kaynak.read_text(encoding="utf-8"))
            kayitlar = veri.get("jobs", []) if isinstance(veri, dict) else (veri or [])
            for j in kayitlar:
                if not isinstance(j, dict):
                    continue
                jid = str(j.get("job_id") or "")
                if not jid or jid in gorulen:
                    continue
                url = j.get("output_url")
                if not url:
                    continue  # yalnız GERÇEKTEN üretilmiş videolar
                gorulen.add(jid)
                art = j.get("artifacts") or {}
                # DOĞRULAMA + ONARIM (2026-11-10): kayıtta URL olabilir ama dosya
                # static/media'da olmayabilir → indirme 404 verir. video_factory'de
                # varsa buraya kopyala; hiç yoksa kaydı LİSTELEME (404 link gösterme).
                servis_adi = f"{jid}.mp4"
                if not (MEDIA_DIR / servis_adi).is_file():
                    kaynak_mp4 = BASE_DIR / "video_factory" / jid / "rendered_output.mp4"
                    if kaynak_mp4.is_file():
                        try:
                            import shutil as _sh2
                            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                            _sh2.copy2(kaynak_mp4, MEDIA_DIR / servis_adi)
                        except Exception as e_kp:
                            logger.warning("Medya kopyalanamadı (%s): %s", jid, e_kp)
                            continue
                    else:
                        continue
                # 2026-11-10: 2 KB'lık "moov atom not found" kalıntıları galeride
                # görünüp oynatılamıyordu. Bozuk MP4 LİSTELENMEZ (Kural 1).
                if not _mp4_oynatilabilir(MEDIA_DIR / servis_adi):
                    continue
                url = f"/api/media/file?path={servis_adi}"

                sz_bytes = int(art.get("file_size_bytes") or j.get("file_size_bytes") or 0)
                dl_url = f"{url}{'&' if '?' in url else '?'}download=1"
                items.append({
                    "id": jid,
                    "job_id": jid,
                    "channel": j.get("channel") or "Stüdyo",
                    "model_ad": j.get("model_ad") or j.get("channel") or j.get("method") or "Fabrika Video",
                    "model_id": j.get("i2v_model") or j.get("model_id") or j.get("method") or "remotion_cinema",
                    "image_model": j.get("image_model"),
                    "i2v_model": j.get("i2v_model"),
                    "style_preset": j.get("style_preset"),
                    "preview_image_url": j.get("preview_image_url") or j.get("input_image_url"),
                    "youtube_bundle": j.get("youtube_bundle"),
                    "kaynak": j.get("status") or "onizleme_hazir (simülasyon)",
                    "prompt": str(j.get("prompt") or "")[:120],
                    "method": j.get("method") or "remotion_cinema",
                    "status": j.get("status") or "onizleme_hazir (simülasyon)",
                    "output_url": url,
                    "video_url": url,
                    "download_url": dl_url,
                    "file_size_bytes": str(sz_bytes) if sz_bytes else art.get("file_size_bytes"),
                    "size_kb": max(1, round(sz_bytes / 1024)) if sz_bytes else 0,
                    "resolution": art.get("resolution") or j.get("resolution") or "1920x1080",
                    "duration": art.get("duration_sec") or j.get("duration") or None,
                    "created_at": j.get("created_at") or "",
                })
        except Exception as e_hist:
            logger.warning("Geçmiş okunamadı (%s): %s", kaynak.name, e_hist)

    # 2) video_factory dizininde dosyası olup kaydı olmayanlar (kurtarma)
    try:
        for mp4 in sorted((BASE_DIR / "video_factory").glob("*/rendered_output.mp4"), reverse=True):
            jid = mp4.parent.name
            if jid in gorulen:
                continue
            hedef = MEDIA_DIR / f"{jid}.mp4"
            if not hedef.is_file():
                try:
                    import shutil as _sh
                    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                    _sh.copy2(mp4, hedef)
                except Exception:
                    continue
            gorulen.add(jid)
            if not _mp4_oynatilabilir(hedef):
                continue
            sz_b = mp4.stat().st_size

            u_path = f"/api/media/file?path={jid}.mp4"
            items.append({
                "id": jid,
                "job_id": jid,
                "channel": "Stüdyo",
                "model_ad": "Fabrika Stüdyo",
                "model_id": "remotion_cinema",
                "kaynak": "onizleme_hazir (simülasyon)",
                "prompt": "Kılavuz Video Üretimi",
                "method": "remotion_cinema",
                "status": "onizleme_hazir (simülasyon)",
                "output_url": u_path,
                "video_url": u_path,
                "download_url": f"{u_path}&download=1",
                "file_size_bytes": str(sz_b),
                "size_kb": max(1, round(sz_b / 1024)),
                "resolution": "1920x1080",
                "duration": None,
                "created_at": "",
            })
    except Exception as e_kurtar:
        logger.debug("video_factory taraması: %s", e_kurtar)

    items.sort(key=lambda x: x.get("job_id", ""), reverse=True)
    items = items[:max(1, min(limit, 60))]
    return {"items": items, "count": len(items)}


@app.get("/api/lab/job/{job_id}", dependencies=[Depends(verify_auth)])
async def get_lab_job_status(job_id: str):
    """Tek bir GPU/stüdyo işinin güncel durumunu ve varsa önizleme/çıktı URL'sini döner."""
    jid = _validate_job_id(job_id)
    with JOBS_LOCK:
        data = _load_jobs_unlocked()
        kayit = next((j for j in data.get("jobs", []) if _is_job(j, jid)), None)
    if kayit is None:
        raise HTTPException(status_code=404, detail="İş kaydı bulunamadı.")
    temiz = {k: v for k, v in kayit.items() if k not in ("input_image_path",)}
    return {"success": True, "job_id": jid, "job": temiz}


def _gorsel_turu(ham: bytes) -> Optional[str]:
    """Sihirli baytlardan görsel türünü döner (PNG/JPEG) — uzantıya güvenilmez."""
    if ham.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if ham.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


def _decode_image_base64(raw: str) -> bytes:
    """PNG/JPEG data URI veya ham base64'ü güvenle çözer (en fazla 15 MB)."""
    veri = (raw or "").strip()
    if not veri:
        raise ValueError("Görsel verisi boş.")
    if veri.startswith("data:"):
        baslik, ayrac, b64 = veri.partition(",")
        if not ayrac or not b64:
            raise ValueError("Geçersiz data URI (virgül/veri eksik).")
        alt_tur = baslik[5:].split(";")[0].strip().lower()
        if alt_tur not in ("image/png", "image/jpeg", "image/jpg"):
            raise ValueError("Yalnızca PNG veya JPEG data URI desteklenir.")
    else:
        b64 = veri
    try:
        ham = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"Geçersiz base64 görsel verisi: {e}")
    if len(ham) < 8:
        raise ValueError("Görsel verisi çok kısa.")
    if len(ham) > MAX_INPUT_IMAGE_BYTES:
        raise ValueError(
            f"Görsel {MAX_INPUT_IMAGE_BYTES // (1024 * 1024)} MB sınırını aşıyor."
        )
    if _gorsel_turu(ham) is None:
        raise ValueError("Görsel PNG/JPEG sihirli baytlarını taşımıyor.")
    return ham


def _input_gorsel_kaydet(job_id: str, ham: bytes) -> Path:
    """Doğrulanmış görseli `MEDIA_DIR/<job_id>_input.png` olarak atomik yazar."""
    if _gorsel_turu(ham) is None:
        raise ValueError("Görsel PNG/JPEG değil.")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    hedef = MEDIA_DIR / f"{job_id}_input.png"
    gecici = MEDIA_DIR / f".{job_id}_input.part"
    gecici.write_bytes(ham)
    os.replace(gecici, hedef)
    return hedef


def _url_den_gorsel_ham(url: str) -> Optional[bytes]:
    """Onaylanmış önizleme/input URL'sinden görsel baytlarını çözer.

    Desteklenen biçimler: `/api/media/file?path=<ad>`, `/api/worker/input/<job_id>`
    ve doğrudan MEDIA_DIR dosya adı. Dizin atlama girişimleri reddedilir.
    """
    aday = ""
    eslesme = re.search(r"[?&]path=([^&]+)", url or "")
    if eslesme:
        aday = urllib.parse.unquote(eslesme.group(1))
    else:
        eslesme = re.search(r"/api/worker/input/([A-Za-z0-9._-]{1,80})", url or "")
        if eslesme:
            aday = f"{eslesme.group(1)}_input.png"
    if not aday:
        return None
    ad = Path(aday).name
    if not ad or ad.startswith(".") or not JOB_ID_RE.match(ad):
        return None
    aday_yollar = [MEDIA_DIR / ad]
    if ad.endswith("_input.png"):
        aday_yollar.append(MEDIA_DIR / (ad[:-4] + ".jpg"))
    for yol in aday_yollar:
        try:
            if yol.is_file() and _gorsel_turu(yol.read_bytes()[:8]) is not None:
                return yol.read_bytes()
        except OSError:
            continue
    return None


def _has_live_gpu_worker() -> bool:
    """Son 60 saniyede kalp atışı göndermiş gerçek GPU işçisi var mı kontrol eder."""
    _prune_stale_workers()
    return bool(ACTIVE_GPU_WORKERS)


def _run_instant_cloud_render_sync(
    *,
    job_id: str,
    method: str,
    prompt: str,
    image_prompts: List[str],
    motion_prompt: str,
    aspect_ratio: str,
    style_preset: str,
    camera_motion: str,
    duration_sec: float,
    source_url: Optional[str] = None,
    execution_mode: str = "instant_cloud",
) -> Dict[str, Any]:
    """GPU işçisi yokken gerçek YZ görseli, LTX I2V canlandırma veya HyperFrames kurgu üretir.

    Kural 1 uyumu: Başarısız görseli metin kartına çevirip sahte resim diye sunmaz;
    `execution_mode=='real_i2v'` iken FFmpeg zoom/pan ile karakter canlandırma taklidi yapmaz.
    """
    import ai_video_montaj as _avm
    from hyperframes_motor import (
        _cozunurluk,
        build_hyperframes_html,
        cloud_real_i2v_animate,
        hyperframes_studio_render,
        instant_i2v_motion,
        verify_onscreen_metrics,
    )

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    w, h = _cozunurluk(aspect_ratio)
    clean_prompts = [p for p in (image_prompts or []) if p and str(p).strip()] or [prompt]

    if method in ("flux2_resim", "image_first_preview"):
        hedef_png = MEDIA_DIR / f"{job_id}_preview.png"
        prev = _avm.preview_single_image(
            clean_prompts[0],
            hedef_png,
            genislik=w,
            yukseklik=h,
            style_preset=style_preset,
            camera_motion=camera_motion,
        )
        if not prev.get("ok") or not hedef_png.is_file():
            return {
                "ok": False,
                "error": prev.get("error") or "Gerçek YZ görseli üretilemedi (Pollinations devre dışı; metin kartı üretilmez).",
            }
        saglayici = str(prev.get("provider") or "cloud")
        preview_url = f"/api/media/file?path={hedef_png.name}"
        return {
            "ok": True,
            "status": "onizleme_hazir",
            "progress_pct": 100,
            "output_url": preview_url,
            "download_url": f"{preview_url}&download=1",
            "preview_image_url": preview_url,
            "hyperframes_url": None,
            "simulasyon": False,
            "video_difuzyonu": False,
            "gpu_upgrade_available": True,
            "kaynak": saglayici,
            "file_size_bytes": hedef_png.stat().st_size,
            "resolution": f"{w}x{h}",
            "duration_sec": 0.0,
            "kalite_raporu": None,
            "open_edit_metrics": None,
        }

    if method == "wan_i2v" or (MEDIA_DIR / f"{job_id}_input.png").is_file():
        src_img = MEDIA_DIR / f"{job_id}_input.png"
        if not src_img.is_file():
            src_img = MEDIA_DIR / f"{job_id}_preview.png"
            prev = _avm.preview_single_image(
                clean_prompts[0],
                src_img,
                genislik=w,
                yukseklik=h,
                style_preset=style_preset,
                camera_motion=camera_motion,
            )
            if not prev.get("ok") or not src_img.is_file():
                return {
                    "ok": False,
                    "error": prev.get("error") or "Gerçek YZ görseli üretilemedi (metin kartı devre dışı).",
                }

        hedef_mp4 = MEDIA_DIR / f"{job_id}.mp4"
        hedef_html = MEDIA_DIR / f"{job_id}_hyperframes.html"
        audio_path = MEDIA_DIR / f"{job_id}.wav"
        ass_path = MEDIA_DIR / f"{job_id}.ass"
        exec_mod = (execution_mode or "instant_cloud").strip().lower()

        res: Optional[Dict[str, Any]] = None
        if exec_mod != "camera_motion_only":
            ltx_res = cloud_real_i2v_animate(
                src_img,
                hedef_mp4,
                prompt=motion_prompt or prompt,
                aspect_ratio=aspect_ratio,
                duration_sec=duration_sec,
                audio_path=audio_path if audio_path.is_file() else None,
                ass_path=ass_path if ass_path.is_file() else None,
            )
            if ltx_res.get("ok"):
                res = ltx_res
            elif exec_mod == "real_i2v":
                return {
                    "ok": False,
                    "needs_gpu_worker": True,
                    "error": ltx_res.get("error") or (
                        "Gerçek karakter canlandırma (LTX ZeroGPU / Kaggle Wan2.1) şu an yanıt vermedi; "
                        "kamera zoom/kaydırma uygulanmadı."
                    ),
                }

        if res is None:
            res = instant_i2v_motion(
                src_img,
                hedef_mp4,
                prompt=motion_prompt or prompt,
                camera_motion=camera_motion,
                aspect_ratio=aspect_ratio,
                duration_sec=duration_sec,
                audio_path=audio_path if audio_path.is_file() else None,
                ass_path=ass_path if ass_path.is_file() else None,
            )
        if not res.get("ok"):
            return res
        build_hyperframes_html(
            hedef_html,
            prompt[:70],
            motion_prompt[:140] or source_url or style_preset,
            [{"caption": prompt[:60], "motion": camera_motion}],
            float(res.get("duration_sec") or duration_sec),
            aspect_ratio,
            style_preset,
        )
        video_url = f"/api/media/file?path={hedef_mp4.name}"
        is_real_diff = bool(res.get("video_difuzyonu"))
        return {
            "ok": True,
            "status": "tamamlandi",
            "progress_pct": 100,
            "output_url": video_url,
            "download_url": f"{video_url}&download=1",
            "preview_image_url": f"/api/media/file?path={src_img.name}" if src_img.is_file() else None,
            "hyperframes_url": f"/api/studio/hyperframes/{job_id}",
            "simulasyon": bool(res.get("simulasyon", not is_real_diff)),
            "video_difuzyonu": is_real_diff,
            "gpu_upgrade_available": not is_real_diff,
            "kaynak": str(res.get("kaynak") or "bulut_hareket_i2v"),
            "file_size_bytes": res.get("file_size_bytes", 0),
            "resolution": res.get("resolution", f"{w}x{h}"),
            "duration_sec": res.get("duration_sec", duration_sec),
            "kalite_raporu": res.get("kalite"),
            "open_edit_metrics": verify_onscreen_metrics(prompt, source_url or prompt),
        }

    hedef_mp4 = MEDIA_DIR / f"{job_id}.mp4"
    hedef_html = MEDIA_DIR / f"{job_id}_hyperframes.html"
    audio_path = MEDIA_DIR / f"{job_id}.wav"
    res = hyperframes_studio_render(
        hedef_mp4,
        hedef_html,
        prompt=prompt,
        image_prompts=clean_prompts,
        aspect_ratio=aspect_ratio,
        style_preset=style_preset,
        camera_motion=camera_motion,
        duration_sec=max(6.0, float(duration_sec)),
        audio_path=audio_path if audio_path.is_file() else None,
        source_url=source_url,
    )
    if not res.get("ok"):
        return res
    prev_png = res.get("preview_png")
    preview_url = f"/api/media/file?path={Path(prev_png).name}" if prev_png and Path(prev_png).is_file() else None
    video_url = f"/api/media/file?path={hedef_mp4.name}"
    return {
        "ok": True,
        "status": "tamamlandi",
        "progress_pct": 100,
        "output_url": video_url,
        "download_url": f"{video_url}&download=1",
        "preview_image_url": preview_url,
        "hyperframes_url": f"/api/studio/hyperframes/{job_id}",
        "simulasyon": True,
        "video_difuzyonu": False,
        "gpu_upgrade_available": True,
        "kaynak": f"hyperframes_{res.get('saglayici', 'cloud')}",
        "file_size_bytes": res.get("file_size_bytes", 0),
        "resolution": res.get("resolution", f"{w}x{h}"),
        "duration_sec": max(6.0, float(duration_sec)),
        "gecisler": res.get("gecisler"),
        "kalite_raporu": res.get("kalite"),
        "open_edit_metrics": res.get("open_edit_metrics"),
    }


def _finalize_instant_cloud_job(job: Dict[str, Any], res: Dict[str, Any]) -> Dict[str, Any]:
    """Anında bulut görsel/MP4 çıktısını Kural 1 etiketleriyle iş kaydına işler."""
    from channels_manager import ChannelStore

    job["status"] = res.get("status") or "tamamlandi"
    job["progress_pct"] = int(res.get("progress_pct") or 100)
    job["gpu_kuyruk"] = False
    job["simulasyon"] = bool(res.get("simulasyon", True))
    job["video_difuzyonu"] = bool(res.get("video_difuzyonu", False))
    job["gpu_durum"] = "tamamlandi" if job["video_difuzyonu"] else "tamamlandi_onizleme"
    job["output_url"] = res.get("output_url")
    job["download_url"] = res.get("download_url")
    job["preview_image_url"] = res.get("preview_image_url")
    if res.get("hyperframes_url"):
        job["hyperframes_url"] = res["hyperframes_url"]
    job["gpu_upgrade_available"] = bool(res.get("gpu_upgrade_available", True))
    job["kalite_raporu"] = res.get("kalite_raporu")
    job["open_edit_metrics"] = res.get("open_edit_metrics")
    job["file_size_bytes"] = res.get("file_size_bytes", 0)
    job["resolution"] = res.get("resolution")
    job["kaynak"] = res.get("kaynak")
    art = dict(job.get("artifacts") or {})
    art.update({
        "kaynak": res.get("kaynak"),
        "video_difuzyonu": job["video_difuzyonu"],
        "file_size_bytes": res.get("file_size_bytes", 0),
        "resolution": res.get("resolution"),
        "gecisler": res.get("gecisler"),
    })
    job["artifacts"] = art
    if str(job.get("output_url") or "").lower().find(".mp4") >= 0:
        try:
            from cloud_storage import put_file
            jid_f = str(job.get("job_id") or "")
            if jid_f:
                put_file(MEDIA_DIR / f"{jid_f}.mp4", content_type="video/mp4")
                if (MEDIA_DIR / f"{jid_f}_preview.png").is_file():
                    put_file(MEDIA_DIR / f"{jid_f}_preview.png", content_type="image/png")
        except Exception:
            pass
        try:
            job["youtube_bundle"] = ChannelStore(DATA_DIR).build_publish_bundle(job, MEDIA_DIR)
        except Exception:
            pass
        if job["video_difuzyonu"]:
            job["message"] = (
                f"Gerçek YZ video difüzyonu ({res.get('kaynak', 'I2V')}) — karakter & sahne canlandırma MP4 hazır."
            )
        else:
            job["message"] = (
                "Anında bulut kamera kurgusu MP4 hazır (gerçek karakter canlandırması değildir; "
                "karakter animasyonu için LTX ZeroGPU / Kaggle Wan2.1 GPU işçisi gerekir)."
            )
    else:
        job["message"] = (
            f"Anahtar görsel hazır ({res.get('kaynak', 'bulut')}) — 2. Aşamaya geçip videoya çevirebilirsiniz."
        )
    return job


@app.post("/api/lab/generate", dependencies=[Depends(verify_auth)])
async def generate_lab_video(req: Request):
    """Kova Lab video/I2V/FLUX önizleme isteğini GERÇEK kuyruğa bağlar.

    GPU hedeflerinde yerel sahte render YOKTUR: iş `video_jobs.json`'a
    `gpu_kuyruk=True, gpu_durum='bekliyor'` olarak yazılır; Kaggle/Colab işçisi
    `/api/worker/claim` ile alıp gerçek difüzyonla üretir.
    """
    basla = time.time()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    model_id = str(body.get("model_id") or "wan2.1-i2v-14b")
    model_ad = str(body.get("model_ad") or model_id)
    channel = str(body.get("channel") or f"KovaLab_{model_id}")
    prompt = str(body.get("prompt") or "Günün sinematik videosu")
    aspect_ratio = str(body.get("aspect_ratio") or "16:9")
    voice = str(body.get("voice") or "").strip()
    render_target = str(body.get("render_target") or "kaggle_32gb")
    mode = str(body.get("mode") or "").strip().lower()
    method = str(body.get("method") or "").strip().lower()
    workflow = str(body.get("workflow") or "").strip().lower()
    image_model = str(body.get("image_model") or "flux2-klein").strip()
    i2v_model = str(body.get("i2v_model") or body.get("video_model") or model_id or "wan2.1-i2v-14b").strip()
    style_preset = str(body.get("style_preset") or body.get("style") or "cinematic_realism").strip()
    camera_motion = str(body.get("camera_motion") or "otomatik").strip()
    neg_prompt_raw = str(body.get("negative_prompt") or "").strip()
    execution_mode = str(body.get("execution_mode") or "").strip().lower()
    source_url = str(body.get("source_url") or "").strip()
    try:
        sure_sn = max(3.0, min(60.0, float(body.get("duration") or body.get("sure_sn") or 5.0)))
    except (TypeError, ValueError):
        sure_sn = 5.0
    job_id = _new_job_id()

    effective_prompt = prompt
    if source_url:
        from prompt_director import fetch_url_launch_brief
        url_res = await run_in_threadpool(lambda: fetch_url_launch_brief(source_url))
        if not url_res.get("ok"):
            return JSONResponse(status_code=400, content={"success": False, "status": "basarisiz", "message": url_res.get("error") or "Geçersiz source_url"})
        effective_prompt = f"{prompt} — {url_res['brief']}"

    scene_n = 3 if (workflow in ("hyperframes_motion", "product_launch", "image_then_i2v", "t2v_direct") or execution_mode == "instant_cloud") else 1
    try:
        from channels_manager import compose_story_plan
        story_plan = await run_in_threadpool(
            lambda: compose_story_plan(
                effective_prompt, style_preset, camera_motion, neg_prompt_raw, scene_count=scene_n, duration_sec=sure_sn
            )
        )
        img_prompt = story_plan["image_prompt"]
        mot_prompt = story_plan["motion_prompt"]
        neg_prompt = story_plan["negative_prompt"]
        narration_txt = story_plan["narration_text"]
        planner_source = story_plan.get("planner_source", "yerel")
        scene_prompts = [s.get("image_prompt", "") for s in (story_plan.get("scenes") or []) if isinstance(s, dict) and s.get("image_prompt")] or [img_prompt]
    except Exception:
        img_prompt, mot_prompt, neg_prompt = effective_prompt, effective_prompt, neg_prompt_raw
        narration_txt, planner_source = prompt, "ham"
        scene_prompts = [img_prompt]

    gorsel_ham: Optional[bytes] = None
    try:
        if body.get("image_base64"):
            gorsel_ham = _decode_image_base64(str(body["image_base64"]))
        elif body.get("input_image_url"):
            gorsel_ham = _url_den_gorsel_ham(str(body["input_image_url"]))
            if gorsel_ham is None:
                raise ValueError(
                    "input_image_url MEDIA_DIR içinde geçerli bir PNG/JPEG görsele çözümlenemedi."
                )
        if gorsel_ham is not None:
            _input_gorsel_kaydet(job_id, gorsel_ham)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"success": False, "status": "basarisiz", "message": str(e)},
        )
    except OSError as e:
        logger.error("Giriş görseli kaydedilemedi (%s): %s", job_id, e)
        return JSONResponse(
            status_code=500,
            content={"success": False, "status": "basarisiz", "message": "Giriş görseli kaydedilemedi."},
        )

    input_url = f"/api/worker/input/{job_id}" if gorsel_ham is not None else None

    if workflow in ("hyperframes_motion", "product_launch"):
        method = workflow
    elif workflow in ("image_first_preview", "flux2_resim"):
        method = "flux2_resim"
    elif workflow == "image_then_i2v":
        method = "wan_i2v" if gorsel_ham is not None else "image_then_i2v"
    elif mode == "flux2_resim" or method == "flux2_resim":
        method = "flux2_resim"
    elif mode == "image_then_i2v":
        method = "wan_i2v" if gorsel_ham is not None else "image_then_i2v"
    elif not method:
        if gorsel_ham is not None:
            method = "wan_i2v"
        elif mode == "i2v":
            method = "wan_i2v"
        elif mode in ("t2v", "t2v_direct"):
            method = "t2v_direct"
        else:
            method = "image_first_preview"

    if method == "wan_i2v" and gorsel_ham is None:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "status": "basarisiz",
                "message": "wan_i2v için onaylanmış bir görsel gerekli (image_base64 veya input_image_url).",
            },
        )

    gpu_hedef = render_target in GPU_HEDEFLERI or method in (
        "wan_i2v", "flux2_resim", "image_first_preview", "image_then_i2v", "t2v_direct",
        "hyperframes_motion", "product_launch",
    )
    if gpu_hedef:
        tts_enabled = bool(body.get("tts_enabled")) or (voice and voice.lower() not in ("none", "yok", ""))
        audio_url = None
        subtitle_url = None
        if method not in ("flux2_resim", "image_first_preview"):
            if tts_enabled and voice.lower() not in ("none", "yok", ""):
                tts = await run_in_threadpool(
                    lambda: _burc_tts_yaz(narration_txt, voice or "Aoede", MEDIA_DIR / f"{job_id}.wav")
                )
                if tts.get("ok"):
                    audio_url = f"/api/worker/audio/{job_id}"
            if body.get("subtitles_enabled", True):
                bmod = _burc_modulu()
                if bmod is not None:
                    try:
                        alt = await run_in_threadpool(
                            lambda: _burc_altyazi_yaz(
                                bmod, narration_txt, sure_sn, MEDIA_DIR / f"{job_id}.srt", MEDIA_DIR / f"{job_id}.ass"
                            )
                        )
                        if alt.get("ok"):
                            subtitle_url = f"/api/worker/subtitle/{job_id}"
                    except Exception:
                        pass

        job = {
            "id": job_id,
            "job_id": job_id,
            "channel": channel,
            "model_id": i2v_model if method != "flux2_resim" else image_model,
            "model_ad": model_ad,
            "image_model": image_model,
            "i2v_model": i2v_model,
            "video_model": i2v_model,
            "style_preset": style_preset,
            "camera_motion": camera_motion,
            "workflow": workflow or method,
            "prompt": prompt,
            "narration_text": narration_txt,
            "planner_source": planner_source,
            "image_prompt": img_prompt,
            "motion_prompt": mot_prompt,
            "negative_prompt": neg_prompt,
            "method": method,
            "mode": mode or method,
            "render_target": render_target,
            "aspect_ratio": aspect_ratio,
            "sure_sn": round(sure_sn, 1),
            "voice": voice or "Aoede",
            "status": "kuyrukta (GPU işçisi bekleniyor)",
            "progress_pct": 0,
            "gpu_kuyruk": True,
            "gpu_durum": "bekliyor",
            "simulasyon": False,
            "input_image_url": input_url,
            "audio_url": audio_url,
            "subtitle_url": subtitle_url,
            "preview_image_url": None,
            "output_url": None,
            "download_url": None,
            "created_at": time.time(),
            "artifacts": {
                "kaynak": "gpu_kuyruk",
                "image_model": image_model,
                "i2v_model": i2v_model,
                "not": "Yerel sahte render yapılmadı; gerçek üretim Kaggle/Colab GPU işçisinde.",
            },
        }
        aninda = (
            method in ("hyperframes_motion", "product_launch")
            or execution_mode == "instant_cloud"
            or (execution_mode == "auto" and not _has_live_gpu_worker())
        )
        if aninda:
            res = await run_in_threadpool(
                lambda: _run_instant_cloud_render_sync(
                    job_id=job_id,
                    method=method,
                    prompt=prompt,
                    image_prompts=scene_prompts,
                    motion_prompt=mot_prompt,
                    aspect_ratio=aspect_ratio,
                    style_preset=style_preset,
                    camera_motion=camera_motion,
                    duration_sec=sure_sn,
                    source_url=source_url or None,
                )
            )
            if not res.get("ok"):
                return JSONResponse(status_code=502, content={"success": False, "status": "basarisiz", "message": res.get("error") or "Bulut render başarısız."})
            _finalize_instant_cloud_job(job, res)
            _append_job_record(job)
            return {
                "success": True,
                "status": job["status"],
                "job_id": job_id,
                "model_id": model_id,
                "prompt": prompt,
                "gpu_kuyruk": False,
                "gpu_durum": job["gpu_durum"],
                "simulasyon": job["simulasyon"],
                "video_difuzyonu": job.get("video_difuzyonu", False),
                "output_url": job.get("output_url"),
                "download_url": job.get("download_url"),
                "preview_image_url": job.get("preview_image_url"),
                "hyperframes_url": job.get("hyperframes_url"),
                "input_image_url": input_url,
                "job": job,
                "message": job["message"],
            }

        _append_job_record(job)
        mesaj = (
            f"1. Adım Anahtar Görsel ({image_model}) GPU kuyruğuna alındı — beğendiğinizde I2V'ye geçebilirsiniz."
            if method in ("flux2_resim", "image_first_preview")
            else (
                f"2 Aşamalı Tutarlı Üretim ({image_model} → {i2v_model}) GPU kuyruğuna alındı."
                if method == "image_then_i2v"
                else f"GPU kuyruğuna alındı ({i2v_model}); işçi bağlandığında gerçek difüzyonla üretilecek."
            )
        )
        return {
            "success": True,
            "status": job["status"],
            "job_id": job_id,
            "model_id": model_id,
            "prompt": prompt,
            "gpu_kuyruk": True,
            "gpu_durum": "bekliyor",
            "input_image_url": input_url,
            "job": job,
            "message": mesaj,
        }

    try:
        from studio_controller import VideoStudioController

        spec = await run_in_threadpool(
            lambda: VideoStudioController().create_video_job(
                channel=f"KovaLab_{model_id}",
                prompt=prompt,
                method=method,
                render_target=render_target,
                aspect_ratio=aspect_ratio,
                voice=voice,
            )
        )
        sz_b = int(spec.artifacts.get("file_size_bytes") or 0)
        dl_url = f"{spec.output_url}&download=1" if spec.output_url else None
        job_obj = {
            "id": spec.job_id,
            "job_id": spec.job_id,
            "model_id": model_id,
            "model_ad": model_ad,
            "kaynak": spec.status,
            "prompt": prompt,
            "method": method,
            "status": spec.status,
            "video_url": spec.output_url,
            "output_url": spec.output_url,
            "download_url": dl_url,
            "resolution": spec.artifacts.get("resolution"),
            "duration_sec": spec.artifacts.get("duration_sec"),
            "elapsed_sec": round(time.time() - basla, 2),
            "size_kb": max(1, round(sz_b / 1024)) if sz_b else 0,
            "file_size_bytes": str(sz_b),
            "simulasyon": bool(spec.simulasyon),
            "input_image_url": input_url,
            "gpu_kuyruk": render_target in GPU_HEDEFLERI,
            "gpu_durum": "bekliyor" if render_target in GPU_HEDEFLERI else None,
        }
        _append_job_record({
            "job_id": spec.job_id,
            "id": spec.job_id,
            "channel": model_ad,
            "prompt": prompt,
            "method": method,
            "model_id": model_id,
            "render_target": render_target,
            "status": spec.status,
            "progress_pct": spec.progress_pct,
            "stages": spec.stages,
            "output_url": spec.output_url,
            "download_url": dl_url,
            "input_image_url": input_url,
            "gpu_kuyruk": render_target in GPU_HEDEFLERI,
            "gpu_durum": "bekliyor" if render_target in GPU_HEDEFLERI else None,
            "simulasyon": bool(spec.simulasyon),
            "artifacts": spec.artifacts,
            "created_at": time.time(),
        })
        return {
            "success": bool(spec.output_url),
            "status": spec.status,
            "job_id": spec.job_id,
            "model_id": model_id,
            "prompt": prompt,
            "job": job_obj,
            "message": (
                f"Yerel önizleme üretildi ({job_obj['size_kb']} KB) — {spec.status}."
                if spec.output_url
                else "Yerel render çıktı veremedi; GPU hedefi seçiliyse iş kuyrukta bekliyor."
            ),
        }
    except Exception as e_lab:
        logger.error("Kova Lab video üretimi başarısız: %s", e_lab)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "status": "basarisiz",
                "message": f"Video üretilemedi: {type(e_lab).__name__}: {str(e_lab)[:200]}",
            },
        )


# -----------------------------------------------------------------------------
# 5. VİDEO OTOMASYON PRODÜKSİYONU (REMOTION / BLENDER / CANVAS)
# -----------------------------------------------------------------------------
@app.get("/api/studio/video/channels", dependencies=[Depends(verify_auth)])
async def studio_channels():
    try:
        from studio_controller import VideoStudioController
        return {
            "success": True,
            "channels": VideoStudioController.CHANNELS,
            "methods": VideoStudioController.METHODS,
            "render_targets": VideoStudioController.RENDER_TARGETS,
        }
    except Exception as e:
        logger.warning("Studio controller channels error: %s", e)
        return {
            "success": True,
            "channels": {
                "Astroloji_Kova": {"name": "Kova Astroloji", "style": "mystic_dark", "ratio": "16:9"},
                "Tech_AI_Fabrika": {"name": "Fabrika AI & Tech", "style": "cyber_tech", "ratio": "16:9"},
                "Belgesel_Sinematik": {"name": "İstanbul & Tarih Belgeseli", "style": "cinematic_4k", "ratio": "16:9"},
                "Viral_Shorts": {"name": "Hızlı Viral Kanca", "style": "vertical_fast", "ratio": "9:16"}
            },
            "methods": {
                "remotion_cinema": {"name": "Remotion Cinema Montage (#246)", "desc": "Kod tabanlı 4K kurgu + gerçek stok video"},
                "blender_wan": {"name": "Blender 3D + Wan 2.2 (#245)", "desc": "3D derinlik ve karakter sürekliliği"},
                "opus_canvas": {"name": "Opus Canvas Code Motion (#179)", "desc": "Saf Canvas/Three.js kod animasyonu"},
                "viral_shorts": {"name": "Viral Shorts Motoru (#85)", "desc": "Otomatik altyazı ve hızlı kurgu"}
            },
            "render_targets": {
                "kaggle_32gb": {"name": "Kaggle 32 GB Dual GPU (#226)", "vram": "32GB Dual T4", "speed": "30 Saat/Hafta Ücretsiz"},
                "google_colab": {"name": "Google Colab GPU", "vram": "16GB Tesla T4", "speed": "Bulut Sırası"},
                "local_mac": {"name": "Yerel Mac (Apple Silicon Metal)", "vram": "32GB Unified", "speed": "Hızlı (Yerel)"},
                "hybrid_cluster": {"name": "Hibrit Süper Küme (Colab+Kaggle 48GB)", "vram": "48GB vRAM", "speed": "Eşzamanlı Paralel"}
            }
        }

@app.get("/api/studio/catalog", dependencies=[Depends(verify_auth)])
async def studio_full_catalog():
    """Tüm doğrulanmış görsel/I2V modellerini, tarzları, sesleri ve kayıtlı YouTube kanallarını döner."""
    from channels_manager import ChannelStore, get_full_catalog

    store = ChannelStore(DATA_DIR)
    return {
        "success": True,
        **get_full_catalog(),
        "channels": store.list_channels(),
        "youtube_auth": store.get_youtube_status(),
    }


@app.get("/api/channels", dependencies=[Depends(verify_auth)])
async def list_youtube_channels():
    from channels_manager import ChannelStore

    store = ChannelStore(DATA_DIR)
    return {
        "success": True,
        "channels": store.list_channels(),
        "youtube_auth": store.get_youtube_status(),
    }


@app.post("/api/channels", dependencies=[Depends(verify_auth)])
async def upsert_youtube_channel(req: Request):
    from channels_manager import ChannelStore

    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        ch = ChannelStore(DATA_DIR).upsert_channel(body)
        return {"success": True, "channel": ch}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "detail": str(e)})


@app.delete("/api/channels/{channel_id}", dependencies=[Depends(verify_auth)])
async def delete_youtube_channel(channel_id: str):
    from channels_manager import ChannelStore

    ok = ChannelStore(DATA_DIR).delete_channel(channel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Kanal bulunamadı.")
    return {"success": True, "deleted": channel_id}


@app.get("/api/youtube/status", dependencies=[Depends(verify_auth)])
async def youtube_auth_status(channel_id: Optional[str] = Query(None)):
    from channels_manager import ChannelStore

    store = ChannelStore(DATA_DIR)
    return {"success": True, **store.get_youtube_status(channel_id), "channels": store.list_channels()}


@app.post("/api/youtube/oauth-secret", dependencies=[Depends(verify_auth)])
async def youtube_upload_oauth_secret(req: Request):
    from channels_manager import ChannelStore

    try:
        body = await req.json()
    except Exception:
        body = {}
    raw_secret = body.get("client_secret_json")
    if isinstance(raw_secret, dict):
        raw_secret = json.dumps(raw_secret)
    if not raw_secret or not isinstance(raw_secret, str):
        return JSONResponse(status_code=400, content={"success": False, "detail": "client_secret_json gerekli."})
    try:
        st = ChannelStore(DATA_DIR).save_client_secret(raw_secret)
        return {"success": True, **st}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "detail": str(e)})


@app.post("/api/youtube/publish/{job_id}", dependencies=[Depends(verify_auth)])
async def youtube_publish_job(job_id: str):
    """Video için YouTube SEO paketi üretir; geçerli OAuth varsa canlı yükler, yoksa (simülasyon) döner."""
    from channels_manager import ChannelStore

    jid = _validate_job_id(job_id)
    with JOBS_LOCK:
        jobs = _load_jobs_unlocked().get("jobs", [])
    hedef_job = next((j for j in reversed(jobs) if _is_job(j, jid)), None)
    if hedef_job is None:
        raise HTTPException(status_code=404, detail="İş kaydı bulunamadı.")

    res = await run_in_threadpool(lambda: ChannelStore(DATA_DIR).attempt_youtube_upload(hedef_job, MEDIA_DIR))
    return res


@app.get("/api/youtube/oauth/start", dependencies=[Depends(verify_auth)])
async def youtube_oauth_start(req: Request, channel_id: Optional[str] = Query(None)):
    """Google OAuth yetkilendirme bağlantısı üretir (client_secret.json varsa)."""
    from channels_manager import ChannelStore

    base = str(req.base_url).rstrip("/")
    redirect_uri = f"{base}/api/youtube/oauth/callback"
    try:
        url = ChannelStore(DATA_DIR).build_oauth_authorize_url(channel_id or "", redirect_uri)
        return {"success": True, "auth_url": url, "redirect_uri": redirect_uri}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "detail": str(e), "redirect_uri": redirect_uri})


@app.get("/api/youtube/oauth/callback")
async def youtube_oauth_callback(req: Request, code: Optional[str] = Query(None), state: Optional[str] = Query(None), error: Optional[str] = Query(None)):
    """Google OAuth dönüş kodunu erişim token'ına çevirir ve kanala kaydeder."""
    from channels_manager import ChannelStore

    if error:
        return JSONResponse(status_code=400, content={"success": False, "detail": f"Google OAuth iptal/hata: {error}"})
    if not code:
        return JSONResponse(status_code=400, content={"success": False, "detail": "Yetkilendirme kodu (code) eksik."})
    base = str(req.base_url).rstrip("/")
    redirect_uri = f"{base}/api/youtube/oauth/callback"
    try:
        import html as _html
        res = await run_in_threadpool(
            lambda: ChannelStore(DATA_DIR).exchange_oauth_code(state or "", code, redirect_uri)
        )
        saved_tok = _html.escape(str(res.get("saved_token_file") or ""))
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;background:#07090e;color:#e2e8f0;padding:40px;text-align:center;'>"
            "<h2>✅ YouTube Kanal Yetkilendirmesi Kaydedildi</h2>"
            f"<p>Dosya: <code>{saved_tok}</code></p>"
            "<p><a href='/lab.html#channelsStudio' style='color:#38bdf8;'>Kokpite Geri Dön →</a></p></body></html>"
        )
    except Exception as e:
        logger.error("[YouTubeOAuth] Callback hatası: %s", e)
        return JSONResponse(status_code=400, content={"success": False, "detail": f"OAuth token alınamadı: {str(e)[:200]}"})


@app.post("/api/studio/preview-image", dependencies=[Depends(verify_auth)])
async def studio_preview_image(req: Request):
    """GPU worker beklemeden bulut FLUX.1-schnell (veya Pollinations) ile somut İngilizce sahne önizlemesi üretir."""
    from ai_video_montaj import preview_single_image
    from channels_manager import ChannelStore

    try:
        body = await req.json()
    except Exception:
        body = {}
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse(status_code=400, content={"success": False, "detail": "Önizleme için prompt gerekli."})

    channel = str(body.get("channel") or "Astroloji_Kova")
    ch_cfg = ChannelStore(DATA_DIR).get_channel(channel) or {}
    style_preset = str(body.get("style_preset") or ch_cfg.get("style_preset") or "cinematic_realism")
    camera_motion = str(body.get("camera_motion") or ch_cfg.get("camera_motion") or "otomatik")
    aspect_ratio = str(body.get("aspect_ratio") or ch_cfg.get("aspect_ratio") or "16:9")
    w, h = (576, 1024) if aspect_ratio.replace(" ", "") == "9:16" else (1280, 720)
    job_id = _new_job_id("IMG")
    hedef = MEDIA_DIR / f"{job_id}_preview.png"

    res = await run_in_threadpool(
        lambda: preview_single_image(prompt, hedef, genislik=w, yukseklik=h, style_preset=style_preset, camera_motion=camera_motion)
    )
    if not res.get("ok"):
        return JSONResponse(status_code=502, content={
            "success": False,
            "detail": res.get("error") or "Bulut görsel önizlemesi üretilemedi.",
            "image_prompt": res.get("image_prompt"),
            "planner_source": res.get("planner_source"),
        })

    onizleme_url = f"/api/media/file?path={hedef.name}"
    job = {
        "id": job_id,
        "job_id": job_id,
        "channel": channel,
        "prompt": prompt,
        "narration_text": res.get("narration_text") or prompt,
        "image_prompt": res.get("image_prompt") or prompt,
        "motion_prompt": res.get("motion_prompt") or prompt,
        "planner_source": res.get("planner_source"),
        "style_preset": style_preset,
        "method": "cloud_preview_image",
        "mode": "flux2_resim",
        "aspect_ratio": aspect_ratio,
        "status": "onizleme_hazir",
        "progress_pct": 100,
        "preview_image_url": onizleme_url,
        "simulasyon": False,
        "kaynak": res.get("provider"),
        "created_at": time.time(),
    }
    _append_job_record(job)
    return {
        "success": True,
        "job_id": job_id,
        "preview_image_url": onizleme_url,
        "provider": res.get("provider"),
        "planner_source": res.get("planner_source"),
        "image_prompt": job["image_prompt"],
        "motion_prompt": job["motion_prompt"],
        "narration_text": job["narration_text"],
        "job": job,
    }


@app.post("/api/studio/storyboard", dependencies=[Depends(verify_auth)])
async def studio_storyboard(req: Request):
    """Konudan çok sahneli (3–5 sahneli) anlatım + İngilizce görsel/hareket senaryosu planlar."""
    from channels_manager import compose_story_plan

    try:
        body = await req.json()
    except Exception:
        body = {}
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        return JSONResponse(status_code=400, content={"success": False, "detail": "Storyboard için konu/prompt gerekli."})
    style_preset = str(body.get("style_preset") or "cinematic_realism")
    camera_motion = str(body.get("camera_motion") or "otomatik")
    scene_count = max(2, min(6, int(body.get("scene_count") or 3)))
    duration_sec = max(5.0, min(90.0, float(body.get("duration") or 15.0)))
    plan = await run_in_threadpool(
        lambda: compose_story_plan(prompt, style_preset, camera_motion, scene_count=scene_count, duration_sec=duration_sec)
    )
    return {"success": True, **plan}


@app.post("/api/studio/stitch-clips", dependencies=[Depends(verify_auth)])
async def studio_stitch_clips(req: Request):
    """Birden fazla tamamlanmış I2V klip MP4'ünü birleştirip tam ses+altyazılı uzun video ve YouTube paketi üretir."""
    import shutil
    import subprocess
    import tempfile
    from channels_manager import ChannelStore

    try:
        body = await req.json()
    except Exception:
        body = {}
    raw_ids = body.get("job_ids") or []
    if not isinstance(raw_ids, list) or len(raw_ids) < 2:
        return JSONResponse(status_code=400, content={"success": False, "detail": "Birleştirme için en az 2 job_id gerekli."})

    klipler: List[Path] = []
    for raw_id in raw_ids[:10]:
        jid = _validate_job_id(str(raw_id))
        mp4 = MEDIA_DIR / f"{jid}.mp4"
        if not mp4.is_file() or not _mp4_oynatilabilir(mp4):
            return JSONResponse(status_code=400, content={"success": False, "detail": f"Geçerli MP4 bulunamadı: {jid}"})
        klipler.append(mp4)

    out_id = _new_job_id("STITCH")
    out_mp4 = MEDIA_DIR / f"{out_id}.mp4"
    ff = shutil.which("ffmpeg") or "ffmpeg"
    tmp_dir = Path(tempfile.mkdtemp(prefix="stitch_"))

    def _birlesik_yap() -> Dict[str, Any]:
        norm_paths: List[Path] = []
        for idx, src in enumerate(klipler):
            norm = tmp_dir / f"c{idx}.mp4"
            r = subprocess.run(
                [ff, "-y", "-loglevel", "error", "-i", str(src), "-vf", "scale=720:-2:flags=lanczos,fps=24",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", "-pix_fmt", "yuv420p", str(norm)],
                capture_output=True, text=True, timeout=180,
            )
            if r.returncode != 0:
                raise RuntimeError(f"Klip normalize hatası: {(r.stderr or '')[-160:]}")
            norm_paths.append(norm)

        concat_txt = tmp_dir / "list.txt"
        concat_txt.write_text("\n".join(f"file '{p.as_posix()}'" for p in norm_paths), encoding="utf-8")
        raw_merged = tmp_dir / "merged.mp4"
        r2 = subprocess.run(
            [ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
             "-c", "copy", str(raw_merged)],
            capture_output=True, text=True, timeout=180,
        )
        if r2.returncode != 0:
            raise RuntimeError(f"Concat hatası: {(r2.stderr or '')[-160:]}")

        prompt_txt = str(body.get("narration_text") or body.get("prompt") or "Çok sahneli YouTube prodüksiyonu").strip()
        voice = str(body.get("voice") or "Aoede")
        wav_path = MEDIA_DIR / f"{out_id}.wav"
        tts = _burc_tts_yaz(prompt_txt, voice, wav_path) if voice.lower() != "none" else {"ok": False}

        bmod = _burc_modulu()
        if bmod is not None:
            try:
                _burc_altyazi_yaz(bmod, prompt_txt, 15.0, MEDIA_DIR / f"{out_id}.srt", MEDIA_DIR / f"{out_id}.ass")
            except Exception:
                pass

        if tts.get("ok") and wav_path.is_file():
            r3 = subprocess.run(
                [ff, "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(raw_merged), "-i", str(wav_path),
                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_mp4)],
                capture_output=True, text=True, timeout=300,
            )
            if r3.returncode != 0:
                shutil.copy2(raw_merged, out_mp4)
        else:
            subprocess.run(
                [ff, "-y", "-loglevel", "error", "-i", str(raw_merged), "-c", "copy", "-movflags", "+faststart", str(out_mp4)],
                check=True,
            )
        return {"size_bytes": out_mp4.stat().st_size, "tts": tts}

    try:
        res = await run_in_threadpool(_birlesik_yap)
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "detail": f"Birleştirme başarısız: {str(e)[:200]}"})
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    url = f"/api/media/file?path={out_mp4.name}"
    try:
        from video_render import video_kalite_denetle
        kalite_raporu = video_kalite_denetle(out_mp4)
    except Exception:
        kalite_raporu = {}
    job = {
        "id": out_id,
        "job_id": out_id,
        "channel": str(body.get("channel") or "Genel"),
        "prompt": str(body.get("prompt") or "Çok sahneli birleştirme"),
        "narration_text": str(body.get("narration_text") or body.get("prompt") or ""),
        "method": "multi_clip_stitch",
        "status": "tamamlandi (Çok Sahneli Birleştirme)",
        "progress_pct": 100,
        "output_url": url,
        "download_url": f"{url}&download=1",
        "file_size_bytes": res["size_bytes"],
        "size_kb": max(1, round(res["size_bytes"] / 1024)),
        "kalite_raporu": kalite_raporu,
        "simulasyon": False,
        "created_at": time.time(),
    }
    job["youtube_bundle"] = ChannelStore(DATA_DIR).build_publish_bundle(job, MEDIA_DIR)
    _append_job_record(job)
    return {"success": True, "job": job}


@app.post("/api/studio/video/generate", dependencies=[Depends(verify_auth)])
async def studio_video_generate(req: Request):
    """
    Stüdyo video üretimi.

    * Öncelikli tutarlı hat: `image_first_preview` / `flux2_resim` (önce seçili görsel
      modeliyle anahtar kare → onay sonrası seçili I2V modeliyle MP4) veya
      `image_then_i2v` (otomatik 2 aşama: Görsel → I2V).
    * Eski/yerel yöntemler (`remotion_cinema`, `opus_canvas`, `viral_shorts`) geriye
      dönük uyumluluk için `VideoStudioController` üzerinden çalışır.
    """
    from channels_manager import ChannelStore, compose_story_plan

    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    channel = str(body.get("channel") or "Astroloji_Kova")
    ch_cfg = ChannelStore(DATA_DIR).get_channel(channel) or {}

    prompt = str(body.get("prompt") or ch_cfg.get("default_prompt") or "Günün sinematik videosu")
    workflow = str(body.get("workflow") or "").strip().lower()
    method = str(body.get("method") or "").strip().lower()
    mode = str(body.get("mode") or "").strip().lower()
    execution_mode = str(body.get("execution_mode") or "").strip().lower()
    source_url = str(body.get("source_url") or "").strip()
    render_target = str(body.get("render_target") or "kaggle_32gb")
    aspect_ratio = str(body.get("aspect_ratio") or ch_cfg.get("aspect_ratio") or "16:9")
    voice = str(body.get("voice") or ch_cfg.get("voice") or "Aoede")
    image_model = str(body.get("image_model") or ch_cfg.get("image_model") or "flux2-klein")
    i2v_model = str(body.get("i2v_model") or body.get("video_model") or ch_cfg.get("i2v_model") or "wan2.1-i2v-14b")
    style_preset = str(body.get("style_preset") or ch_cfg.get("style_preset") or "cinematic_realism")
    camera_motion = str(body.get("camera_motion") or ch_cfg.get("camera_motion") or "otomatik")
    neg_raw = str(body.get("negative_prompt") or "")
    try:
        sure_sn = max(3.0, min(60.0, float(body.get("duration") or body.get("sure_sn") or ch_cfg.get("duration") or 5.0)))
    except (TypeError, ValueError):
        sure_sn = 5.0
    job_id = _new_job_id()

    effective_prompt = prompt
    if source_url:
        from prompt_director import fetch_url_launch_brief
        url_res = await run_in_threadpool(lambda: fetch_url_launch_brief(source_url))
        if not url_res.get("ok"):
            return JSONResponse(status_code=400, content={"success": False, "detail": url_res.get("error") or "Geçersiz source_url"})
        effective_prompt = f"{prompt} — {url_res['brief']}"

    gorsel_ham: Optional[bytes] = None
    try:
        if body.get("image_base64"):
            gorsel_ham = _decode_image_base64(str(body["image_base64"]))
        elif body.get("input_image_url"):
            gorsel_ham = _url_den_gorsel_ham(str(body["input_image_url"]))
            if gorsel_ham is None:
                raise ValueError("input_image_url geçerli bir PNG/JPEG görsele çözümlenemedi.")
        if gorsel_ham is not None:
            _input_gorsel_kaydet(job_id, gorsel_ham)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "detail": str(e)})
    except OSError as e:
        logger.error("[Studio] Giriş görseli kaydedilemedi: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "detail": "Giriş görseli kaydedilemedi."})

    # Yöntem çözümlemesi (yeni Image-First/I2V/HyperFrames iş akışları + eski Remotion/Canvas uyumu)
    if workflow in ("hyperframes_motion", "product_launch"):
        method = workflow
    elif workflow in ("image_first_preview", "flux2_resim"):
        method = "flux2_resim"
    elif workflow == "image_then_i2v":
        method = "wan_i2v" if gorsel_ham is not None else "image_then_i2v"
    elif workflow == "wan_i2v":
        method = "wan_i2v"
    elif workflow == "t2v_direct":
        method = "t2v_direct"
    elif mode == "flux2_resim":
        method = "flux2_resim"
    elif workflow in ("remotion_cinema", "opus_canvas", "viral_shorts"):
        method = workflow
    elif not method:
        method = "remotion_cinema"

    if method == "wan_i2v" and gorsel_ham is None:
        return JSONResponse(
            status_code=400,
            content={"success": False, "detail": "wan_i2v için image_base64 veya input_image_url gerekli."},
        )

    gpu_diffusion_methods = (
        "wan_i2v", "flux2_resim", "image_first_preview", "image_then_i2v", "t2v_direct",
        "hyperframes_motion", "product_launch",
    )
    if method in gpu_diffusion_methods:
        scene_n = 3 if (
            method in ("hyperframes_motion", "product_launch", "image_then_i2v", "t2v_direct")
            or execution_mode == "instant_cloud"
            or (execution_mode == "auto" and not _has_live_gpu_worker())
        ) else 1
        story = await run_in_threadpool(
            lambda: compose_story_plan(
                effective_prompt, style_preset, camera_motion, neg_raw, scene_count=scene_n, duration_sec=sure_sn
            )
        )
        img_prompt = story["image_prompt"]
        mot_prompt = story["motion_prompt"]
        neg_prompt = story["negative_prompt"]
        narration_txt = story["narration_text"]
        planner_source = story.get("planner_source", "yerel")
        scene_prompts = [s.get("image_prompt", "") for s in (story.get("scenes") or []) if isinstance(s, dict) and s.get("image_prompt")] or [img_prompt]
        audio_url = None
        subtitle_url = None
        if method not in ("flux2_resim", "image_first_preview"):
            if voice and voice.lower() not in ("none", "yok", ""):
                tts = await run_in_threadpool(
                    lambda: _burc_tts_yaz(narration_txt, voice, MEDIA_DIR / f"{job_id}.wav")
                )
                if tts.get("ok"):
                    audio_url = f"/api/worker/audio/{job_id}"
            bmod = _burc_modulu()
            if bmod is not None:
                try:
                    alt = await run_in_threadpool(
                        lambda: _burc_altyazi_yaz(
                            bmod, narration_txt, sure_sn, MEDIA_DIR / f"{job_id}.srt", MEDIA_DIR / f"{job_id}.ass"
                        )
                    )
                    if alt.get("ok"):
                        subtitle_url = f"/api/worker/subtitle/{job_id}"
                except Exception:
                    pass

        task_data = {
            "job_id": job_id,
            "channel": channel,
            "prompt": prompt,
            "source_url": source_url or None,
            "narration_text": narration_txt,
            "planner_source": planner_source,
            "image_prompt": img_prompt,
            "motion_prompt": mot_prompt,
            "negative_prompt": neg_prompt,
            "image_model": image_model,
            "i2v_model": i2v_model,
            "video_model": i2v_model,
            "style_preset": style_preset,
            "camera_motion": camera_motion,
            "workflow": workflow or method,
            "method": method,
            "mode": "flux2_resim" if method in ("flux2_resim", "image_first_preview") else method,
            "render_target": render_target,
            "aspect_ratio": aspect_ratio,
            "sure_sn": round(sure_sn, 1),
            "voice": voice,
            "status": "kuyrukta (GPU işçisi bekleniyor)",
            "progress_pct": 0,
            "stages": [
                {"ad": "1. Stil & Prompt Kurgusu", "durum": "tamamlandi"},
                {"ad": f"2. Görsel ({image_model}) / I2V ({i2v_model})", "durum": "kuyrukta (GPU işçisi bekleniyor)"},
                {"ad": "3. Mux & YouTube Paketi", "durum": "beklemede"},
            ],
            "artifacts": {"kaynak": "gpu_kuyruk", "image_model": image_model, "i2v_model": i2v_model},
            "output_url": None,
            "download_url": None,
            "simulasyon": False,
            "input_image_url": f"/api/worker/input/{job_id}" if gorsel_ham is not None else None,
            "audio_url": audio_url,
            "subtitle_url": subtitle_url,
            "preview_image_url": None,
            "gpu_kuyruk": True,
            "gpu_durum": "bekliyor",
            "created_at": time.time(),
            "message": (
                f"Önce {image_model} ile anahtar kare üretilecek; beğendiğinizde {i2v_model} ile videoya çevirebilirsiniz."
                if method in ("flux2_resim", "image_first_preview")
                else f"Tutarlı 2 aşamalı GPU üretimi ({image_model} → {i2v_model}) kuyruğa alındı."
            ),
        }
        aninda = (
            method in ("hyperframes_motion", "product_launch")
            or execution_mode in ("instant_cloud", "camera_motion_only")
            or (execution_mode in ("auto", "real_i2v") and not _has_live_gpu_worker())
        )
        if aninda:
            res = await run_in_threadpool(
                lambda: _run_instant_cloud_render_sync(
                    job_id=job_id,
                    method=method,
                    prompt=prompt,
                    image_prompts=scene_prompts,
                    motion_prompt=mot_prompt,
                    aspect_ratio=aspect_ratio,
                    style_preset=style_preset,
                    camera_motion=camera_motion,
                    duration_sec=sure_sn,
                    source_url=source_url or None,
                    execution_mode=execution_mode or "instant_cloud",
                )
            )
            if res.get("needs_gpu_worker"):
                task_data["status"] = "kuyrukta (Gerçek I2V GPU bekleniyor)"
                task_data["preview_image_url"] = task_data.get("input_image_url")
                task_data["message"] = str(res.get("error") or "Gerçek karakter canlandırma için GPU işçisi bekleniyor; iş kuyruğa alındı.")
                task_data["needs_gpu_worker"] = True
            elif not res.get("ok"):
                return JSONResponse(status_code=502, content={"success": False, "detail": res.get("error") or "Anında bulut render başarısız."})
            else:
                _finalize_instant_cloud_job(task_data, res)
                task_data["stages"] = [
                    {"ad": "1. Stil & Prompt Kurgusu", "durum": "tamamlandi"},
                    {"ad": f"2. {'Gerçek I2V Canlandırma' if task_data.get('video_difuzyonu') else 'Anında Bulut Kurgu'} ({task_data.get('kaynak', 'cloud')})", "durum": "tamamlandi"},
                    {"ad": "3. FFmpeg Kalite & YouTube Paketi", "durum": "tamamlandi"},
                ]
        _append_job_record(task_data)
        return {"success": True, "task": task_data}

    try:
        from studio_controller import VideoStudioController

        spec = await run_in_threadpool(
            lambda: VideoStudioController().create_video_job(
                channel=channel,
                prompt=prompt,
                method=method,
                render_target=render_target,
                aspect_ratio=aspect_ratio,
                voice=voice,
            )
        )
        input_url = None
        if gorsel_ham is not None:
            # Görseli gerçek iş kimliğine taşı; worker input ucu bu adı arar.
            eski = MEDIA_DIR / f"{job_id}_input.png"
            yeni = MEDIA_DIR / f"{spec.job_id}_input.png"
            try:
                if eski.is_file():
                    os.replace(eski, yeni)
                input_url = f"/api/worker/input/{spec.job_id}"
            except OSError as e:
                logger.warning("[Studio] Giriş görseli iş kimliğine taşınamadı: %s", e)
        dl_url = f"{spec.output_url}&download=1" if spec.output_url else None
        task_data = {
            "job_id": spec.job_id,
            "channel": spec.channel,
            "prompt": spec.prompt,
            "method": spec.method,
            "render_target": spec.render_target,
            "aspect_ratio": spec.aspect_ratio,
            "status": spec.status,
            "progress_pct": spec.progress_pct,
            "stages": spec.stages,
            "artifacts": spec.artifacts,
            "output_url": spec.output_url,
            "download_url": dl_url,
            "simulasyon": bool(spec.simulasyon),
            "input_image_url": input_url,
            "gpu_kuyruk": render_target in GPU_HEDEFLERI,
            "gpu_durum": "bekliyor" if render_target in GPU_HEDEFLERI else None,
            "created_at": time.time(),
            "message": (
                f"Yerel çıktı üretildi ({spec.artifacts.get('file_size_bytes', '?')} bayt, "
                f"{spec.artifacts.get('resolution', '?')}) — {spec.status}."
                if spec.output_url
                else "Yerel render çıktı veremedi; iş GPU kuyruğunda bekliyor."
            ),
        }
    except Exception as e_ctl:
        logger.error("[Studio] Video üretimi başarısız: %s", e_ctl)
        # DÜRÜST hata — sahte başarı YOK (Kural 1)
        task_data = {
            "job_id": job_id,
            "channel": channel,
            "prompt": prompt,
            "method": method,
            "render_target": render_target,
            "aspect_ratio": aspect_ratio,
            "status": "basarisiz",
            "progress_pct": 0,
            "stages": [{"ad": "1. Render motoru", "durum": f"basarisiz: {type(e_ctl).__name__}"}],
            "artifacts": {"error": str(e_ctl)[:300]},
            "output_url": None,
            "download_url": None,
            "simulasyon": False,
            "input_image_url": f"/api/worker/input/{job_id}" if gorsel_ham is not None else None,
            "gpu_kuyruk": render_target in GPU_HEDEFLERI,
            "gpu_durum": "bekliyor" if render_target in GPU_HEDEFLERI else None,
            "created_at": time.time(),
            "message": f"Video üretilemedi: {type(e_ctl).__name__}: {str(e_ctl)[:200]}",
        }
        return {"success": False, "task": task_data}

    _append_job_record(task_data)
    return {"success": bool(task_data.get("output_url")), "task": task_data}



# -----------------------------------------------------------------------------
# 6. SES, MÜZİK & PODCAST İŞLEME (GERÇEK İNDİRİLEBİLİR WAV ÜRETİMİ + GEÇMİŞ)
# -----------------------------------------------------------------------------
def _synthesize_audio_wav(action: str, params: Dict[str, Any], out_path: Path) -> Dict[str, Any]:
    """
    Her işletim sisteminde (macOS ve Render Cloud Linux) çalışabilen gerçek WAV ses üreticisi.
    macOS üzerinde TTS için `/usr/bin/say` + `ffmpeg` varsa gerçek Türkçe seslendirme üretir;
    bulutta veya müzik modunda ise saf Python `wave` + `math` ile çok-harmonikli ritmik WAV sentezler.
    """
    import math
    import struct
    import wave

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_text = str(
        params.get("prompt") or params.get("text") or params.get("topic") or "Fabrika ses üretimi"
    ).strip()

    # 1) Google Gemini 2.5 Nöral TTS (Hem Linux/Render bulutta hem macOS'ta %100 saf API, Microsoft Edge KESİNLİKLE YASAKTIR)
    if action in ("voice_clone_tts", "generate_podcast"):
        try:
            from gemini_audio import synthesize_gemini_speech
            tts_text = prompt_text[:350]
            if action == "generate_podcast":
                tts_text = f"Fabrika Podcast yayınına hoş geldiniz. Bugünkü konumuz: {tts_text}."
            voice_choice = str(params.get("voice") or "Aoede")
            g_path, g_dur = synthesize_gemini_speech(
                text=tts_text,
                voice_name=voice_choice,
                output_path=out_path,
                output_format="wav"
            )
            if g_path and out_path.is_file() and out_path.stat().st_size > 1000:
                sz = out_path.stat().st_size
                return {
                    "duration_sec": g_dur,
                    "file_size_bytes": sz,
                    "simulasyon": False,
                    "status": "tamamlandi",
                    "engine": f"Google Gemini 2.5 Neural TTS ({voice_choice})",
                }
        except Exception as e_gemini:
            logger.debug("Gemini TTS atlandı: %s", e_gemini)

    # 2) macOS üzerinde yerel seslendirme dene (voice_clone_tts / generate_podcast)
    if action in ("voice_clone_tts", "generate_podcast") and os.path.isfile("/usr/bin/say"):
        try:
            import shutil as _sh
            import subprocess
            import tempfile

            ffmpeg_bin = _sh.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if os.path.isfile("/opt/homebrew/bin/ffmpeg") else None)
            if not ffmpeg_bin:
                try:
                    import imageio_ffmpeg
                    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
                except Exception:
                    ffmpeg_bin = None

            if ffmpeg_bin:
                tts_text = prompt_text[:280]
                if action == "generate_podcast":
                    tts_text = f"Fabrika Podcast yayınına hoş geldiniz. Bugünkü konumuz: {tts_text}."
                with tempfile.TemporaryDirectory() as td:
                    aiff_file = Path(td) / "speech.aiff"
                    subprocess.run(["/usr/bin/say", "-v", "Yelda", "-o", str(aiff_file), tts_text], check=True, timeout=15)
                    subprocess.run(
                        [ffmpeg_bin, "-y", "-i", str(aiff_file), "-ar", "44100", "-ac", "1", str(out_path)],
                        capture_output=True,
                        check=True,
                        timeout=15,
                    )
                if out_path.is_file() and out_path.stat().st_size > 2000:
                    sz = out_path.stat().st_size
                    dur = round(max(1.0, (sz - 44) / (44100 * 2)), 1)
                    return {
                        "duration_sec": dur,
                        "file_size_bytes": sz,
                        "simulasyon": False,
                        "status": "tamamlandi",
                        "engine": "Apple macOS Neural TTS (Yelda TR 44.1kHz)",
                    }
        except Exception as e_tts:
            logger.debug("macOS TTS fallback: %s", e_tts)

    # 2) Saf Python çok-harmonikli ritmik / melodik WAV sentezi (Linux/Render dahil %100 garantili)
    sample_rate = 44100
    duration_sec = 6.0
    total_samples = int(sample_rate * duration_sec)
    bpm = max(60, min(200, int(params.get("bpm") or 128)))
    genre = str(params.get("genre") or "roman_havasi")

    if action == "generate_music":
        if genre == "roman_havasi":
            # Hicaz / Roman dizisi frekansları (A4=440 bazlı: D4, Eb4, F#4, G4, A4, Bb4, C5, D5)
            scale = [293.66, 311.13, 369.99, 392.00, 440.00, 466.16, 523.25, 587.33]
            step_pattern = [0, 2, 3, 4, 3, 2, 1, 2, 4]  # 9/8 Aksak Roman ritmi
        elif genre == "lofi_chill":
            scale = [261.63, 311.13, 349.23, 392.00, 466.16, 523.25]
            step_pattern = [0, 2, 4, 3, 1, 3, 5, 4]
        elif genre == "cyberpunk_synthwave":
            scale = [110.00, 130.81, 146.83, 164.81, 196.00, 220.00]
            step_pattern = [0, 0, 3, 2, 0, 4, 3, 1]
        else:
            scale = [220.00, 261.63, 293.66, 329.63, 392.00, 440.00]
            step_pattern = [0, 2, 4, 5, 4, 2, 3, 1]
    else:
        # Ses/Podcast kılavuz melodi dizisi
        scale = [261.63, 329.63, 392.00, 523.25, 392.00, 329.63]
        step_pattern = [0, 1, 2, 3, 2, 1]

    beat_sec = 60.0 / (bpm * 2.0)
    frames = bytearray()

    for i in range(total_samples):
        t = i / sample_rate
        step_idx = int(t / beat_sec) % len(step_pattern)
        local_t = (t % beat_sec) / beat_sec
        freq = scale[step_pattern[step_idx] % len(scale)]

        # Zarf (ADSR benzeri vuruş sönümlenmesi)
        env = math.exp(-3.2 * local_t) * min(1.0, local_t * 35.0)
        # Temel frekans + 2. ve 3. harmonik + bas eşliği
        sig = (
            0.55 * math.sin(2.0 * math.pi * freq * t)
            + 0.25 * math.sin(2.0 * math.pi * (freq * 2.0) * t)
            + 0.12 * math.sin(2.0 * math.pi * (freq * 3.0) * t)
            + 0.20 * math.sin(2.0 * math.pi * (freq * 0.5) * t)
        ) * env

        # Darbuka / Kick perküsyon vuruşu (her adımda kısa frekans süpürmesi)
        if local_t < 0.12:
            kick_env = math.exp(-28.0 * local_t)
            kick_freq = 140.0 * math.exp(-18.0 * local_t) + 48.0
            sig += 0.45 * math.sin(2.0 * math.pi * kick_freq * t) * kick_env

        # Fade-in / Fade-out
        if t < 0.08:
            sig *= t / 0.08
        elif t > duration_sec - 0.25:
            sig *= max(0.0, (duration_sec - t) / 0.25)

        val = max(-32767, min(32767, int(sig * 24000)))
        frames += struct.pack("<h", val)

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))

    sz = out_path.stat().st_size
    return {
        "duration_sec": duration_sec,
        "file_size_bytes": sz,
        "simulasyon": True,
        "status": "onizleme_hazir (simülasyon)",
        "engine": f"Fabrika Procedural Audio Synthesizer ({genre}, {bpm} BPM) (simülasyon)",
    }


@app.post("/api/audio/process", dependencies=[Depends(verify_auth)])
async def audio_process(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    action = body.get("action", "voice_clone_tts")
    params = body.get("params", {})

    if action == "identify_music":
        audio_file = params.get("audio_file") or params.get("query") or params.get("lyrics")
        if not audio_file:
            return {
                "success": False,
                "detail": "Parmak izi analizi için ses verisi veya dosya yolu sağlanmadı."
            }
        return {
            "success": True,
            "data": {
                "status": "taranıyor",
                "matched": False,
                "message": "Ses parmak izi veritabanında henüz eşleşen kayıt bulunamadı.",
                "confidence": 0.0,
                "simulasyon": False
            }
        }

    job_id = f"AUD-{int(time.time()*1000)}-{os.urandom(3).hex()}"
    wav_name = f"{job_id}.wav"
    wav_path = MEDIA_DIR / wav_name
    prompt_text = str(
        params.get("prompt") or params.get("text") or params.get("topic") or action
    ).strip()

    try:
        synth_info = _synthesize_audio_wav(action, params, wav_path)
        out_url = f"/api/media/file?path={wav_name}"
        dl_url = f"/api/media/file?path={wav_name}&download=1"
        sz_b = int(synth_info.get("file_size_bytes") or 0)
        dur_s = synth_info.get("duration_sec", 6.0)
        st_label = synth_info.get("status", "onizleme_hazir (simülasyon)")
        is_sim = bool(synth_info.get("simulasyon", True))
        eng_name = synth_info.get("engine", "Fabrika Audio Synthesizer")

        record = {
            "job_id": job_id,
            "action": action,
            "prompt": prompt_text[:140],
            "genre": params.get("genre", ""),
            "bpm": params.get("bpm", 128),
            "engine": eng_name,
            "output_format": "audio/wav (44.1kHz 16-bit PCM)",
            "status": st_label,
            "simulasyon": is_sim,
            "output_url": out_url,
            "download_url": dl_url,
            "file_size_bytes": sz_b,
            "size_kb": max(1, round(sz_b / 1024)),
            "duration_sec": dur_s,
            "created_at": time.time(),
            "message": (
                f"✅ Ses dosyası üretildi ({max(1, round(sz_b / 1024))} KB, {dur_s} sn) — "
                f"Dinlemeye ve indirmeye hazır ({st_label}). Tam GPU render kuyruğuna da kaydedildi."
            ),
        }

        audio_jobs_file = DATA_DIR / "audio_jobs.json"
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            hist = json.loads(audio_jobs_file.read_text(encoding="utf-8")) if audio_jobs_file.exists() else {"jobs": []}
            hist.setdefault("jobs", []).append(record)
            audio_jobs_file.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e_save:
            logger.warning("Ses iş kaydı yazılamadı: %s", e_save)

        return {"success": True, "data": record}
    except Exception as e_aud:
        logger.error("Ses üretimi başarısız: %s", e_aud)
        return {
            "success": False,
            "detail": f"Ses üretilemedi: {type(e_aud).__name__}: {e_aud}",
            "data": {"status": "basarisiz", "output_url": None, "simulasyon": False},
        }


@app.get("/api/audio/history", dependencies=[Depends(verify_auth)])
async def get_audio_history(limit: int = Query(12)):
    """Üretilen ses ve müzik dosyalarının gerçek geçmişi ve indirme bağlantıları."""
    items: List[Dict[str, Any]] = []
    gorulen: set = set()

    audio_jobs_file = DATA_DIR / "audio_jobs.json"
    if audio_jobs_file.is_file():
        try:
            veri = json.loads(audio_jobs_file.read_text(encoding="utf-8"))
            for j in (veri.get("jobs", []) if isinstance(veri, dict) else []):
                if not isinstance(j, dict):
                    continue
                jid = str(j.get("job_id") or "")
                url = j.get("output_url")
                if not jid or not url or jid in gorulen:
                    continue
                gorulen.add(jid)
                items.append(j)
        except Exception as e_ah:
            logger.warning("Ses geçmişi okunamadı: %s", e_ah)

    try:
        for wav in sorted(MEDIA_DIR.glob("AUD-*.wav"), reverse=True):
            jid = wav.stem
            if jid in gorulen:
                continue
            gorulen.add(jid)
            sz_b = wav.stat().st_size
            u_path = f"/api/media/file?path={wav.name}"
            items.append({
                "job_id": jid,
                "action": "generate_music",
                "prompt": "Kılavuz Ses Üretimi",
                "engine": "Fabrika Audio Synthesizer",
                "output_format": "audio/wav (44.1kHz)",
                "status": "onizleme_hazir (simülasyon)",
                "simulasyon": True,
                "output_url": u_path,
                "download_url": f"{u_path}&download=1",
                "file_size_bytes": sz_b,
                "size_kb": max(1, round(sz_b / 1024)),
                "duration_sec": round(max(1.0, (sz_b - 44) / (44100 * 2)), 1),
            })
    except Exception:
        pass

    items.sort(key=lambda x: str(x.get("job_id", "")), reverse=True)
    items = items[:max(1, min(limit, 60))]
    return {"items": items, "count": len(items)}


# -----------------------------------------------------------------------------
# 6b. BURÇ SİNEMATİK HATTI (SENARYO + GEMINI TTS + SRT/ASS + GPU KUYRUĞU)
# -----------------------------------------------------------------------------
def _burc_modulu():
    """burc_pipeline'ı savunmalı içe aktarır; eksikse None döner (503)."""
    try:
        import burc_pipeline as mod
    except Exception as e:  # modül henüz dağıtılmadıysa uç dürüstçe 503 verir
        logger.error("[Burç] burc_pipeline içe aktarılamadı: %s", e)
        return None
    for ad in ("BURC_KATALOGU", "burc_listesi", "burc_senaryo_olustur",
               "altyazi_dosyalari_olustur"):
        if not hasattr(mod, ad):
            logger.error("[Burç] burc_pipeline eksik arayüz: %s", ad)
            return None
    return mod


def _burc_altyazi_yaz(mod: Any, metin: str, sure_sn: float,
                     srt_yolu: Path, ass_yolu: Path) -> Dict[str, Any]:
    """`altyazi_dosyalari_olustur` imzası değişse de doğru adlarla çağırır."""
    fn = mod.altyazi_dosyalari_olustur
    adaylar = {
        "metin": metin, "text": metin, "narration_text": metin,
        "sure_sn": sure_sn, "duration_sec": sure_sn, "sure": sure_sn,
        "hedef_srt": srt_yolu, "srt_path": srt_yolu, "srt_yolu": srt_yolu,
        "hedef_ass": ass_yolu, "ass_path": ass_yolu, "ass_yolu": ass_yolu,
    }
    kwargs: Dict[str, Any] = {}
    for ad, parametre in inspect.signature(fn).parameters.items():
        if parametre.kind in (parametre.VAR_POSITIONAL, parametre.VAR_KEYWORD):
            continue
        if ad in adaylar:
            kwargs[ad] = adaylar[ad]
        elif parametre.default is inspect.Parameter.empty:
            raise TypeError(f"altyazi_dosyalari_olustur bilinmeyen zorunlu parametre: {ad}")
    return fn(**kwargs)


def _burc_tts_yaz(metin: str, ses: str, hedef: Path) -> Dict[str, Any]:
    """Gemini anahtarı varsa gerçek TTS WAV üretir; yoksa sahte ses üretmez."""
    try:
        from gemini_audio import synthesize_gemini_speech
    except Exception as e:
        return {"ok": False, "engine": "yok", "neden": f"gemini_audio içe aktarılamadı: {e}"}
    try:
        yol, sure = synthesize_gemini_speech(
            text=metin, voice_name=ses, output_path=hedef, output_format="wav")
    except Exception as e:
        logger.warning("[Burç] Gemini TTS başarısız: %s", e)
        return {"ok": False, "engine": "yok", "neden": f"{type(e).__name__}: {str(e)[:160]}"}
    if yol is None or not hedef.is_file() or hedef.stat().st_size <= 1000:
        return {"ok": False, "engine": "yok", "neden": "GEMINI_API_KEY yok veya TTS yanıt vermedi"}
    return {"ok": True, "engine": f"Google Gemini TTS ({ses})",
            "duration_sec": round(float(sure or 0.0), 3)}


@app.get("/api/burc/list")
async def burc_listele():
    """12 burcun senaryo kataloğunu döner (statik, kimlik doğrulaması gerekmez)."""
    mod = _burc_modulu()
    if mod is None:
        return JSONResponse(
            status_code=503,
            content={"success": False, "detail": "burc_pipeline modülü hazır değil."})
    try:
        liste = mod.burc_listesi()
    except Exception as e:
        logger.error("[Burç] Katalog okunamadı: %s", e)
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": "Burç kataloğu okunamadı."})
    return {"success": True, "items": liste, "count": len(liste)}


@app.post("/api/burc/video/generate", dependencies=[Depends(verify_auth)])
async def burc_video_generate(req: Request):
    """Burç videosunu gerçek GPU kuyruğuna bağlar.

    * `burc_senaryo_olustur` ile anlatım/FLUX/Wan istemleri üretilir.
    * Onaylanmış girdi görseli varsa `wan_i2v`, yoksa `flux2_resim` önizlemesi
      kuyruğa yazılır; yerel sahte render YAPILMAZ.
    * Gemini anahtarı varsa TTS WAV, her durumda SRT/ASS `job_id` ile kaydedilir
      ve `/api/worker/audio|subtitle/<job_id>` uçlarından sunulur.
    """
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    burc_kodu = str(body.get("burc_kodu") or "").strip()
    if not burc_kodu:
        return JSONResponse(
            status_code=400,
            content={"success": False, "detail": "burc_kodu zorunlu."})

    mod = _burc_modulu()
    if mod is None:
        return JSONResponse(
            status_code=503,
            content={"success": False, "detail": "burc_pipeline modülü hazır değil."})

    konu = str(body.get("konu") or "").strip()[:300]
    dil = str(body.get("dil") or "tr").strip().lower()[:8]
    aspect_ratio = str(body.get("aspect_ratio") or "9:16").strip()
    raw_prompt = bool(body.get("raw_prompt"))
    try:
        sure_sn = max(3.0, min(120.0, float(body.get("sure_sn") or 15)))
    except (TypeError, ValueError):
        sure_sn = 15.0

    try:
        senaryo = await run_in_threadpool(
            lambda: mod.burc_senaryo_olustur(
                burc_kodu=burc_kodu, konu=konu, sure_sn=int(round(sure_sn)), dil=dil,
                aspect_ratio=aspect_ratio, raw_prompt=raw_prompt))
    except TypeError:
        # Farklı imza (eski 4 parametre veya konumsal) ihtimaline karşı savunma.
        try:
            senaryo = await run_in_threadpool(
                lambda: mod.burc_senaryo_olustur(
                    burc_kodu=burc_kodu, konu=konu, sure_sn=int(round(sure_sn)), dil=dil))
        except TypeError:
            try:
                senaryo = await run_in_threadpool(
                    lambda: mod.burc_senaryo_olustur(burc_kodu, konu, int(round(sure_sn)), dil))
            except Exception as e:
                logger.error("[Burç] Senaryo üretimi başarısız: %s", e)
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "detail": f"Senaryo üretilemedi: {type(e).__name__}"})
        except Exception as e:
            logger.error("[Burç] Senaryo üretimi başarısız: %s", e)
            return JSONResponse(
                status_code=500,
                content={"success": False, "detail": f"Senaryo üretilemedi: {type(e).__name__}"})
    except Exception as e:
        logger.error("[Burç] Senaryo üretimi başarısız: %s", e)
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": f"Senaryo üretilemedi: {type(e).__name__}"})

    if not isinstance(senaryo, dict) or not senaryo.get("ok"):
        mesaj = str((senaryo or {}).get("hata") if isinstance(senaryo, dict) else "") or "Geçersiz burç kodu."
        return JSONResponse(
            status_code=400,
            content={"success": False, "detail": mesaj[:300]})

    metin = str(senaryo.get("narration_text") or senaryo.get("subtitle_text") or "").strip()
    if not metin:
        return JSONResponse(
            status_code=502,
            content={"success": False, "detail": "Senaryo boş anlatım metni döndürdü."})

    job_id = _new_job_id("BURC")
    gorsel_ham: Optional[bytes] = None
    try:
        if body.get("image_base64"):
            gorsel_ham = _decode_image_base64(str(body["image_base64"]))
        elif body.get("input_image_url"):
            gorsel_ham = _url_den_gorsel_ham(str(body["input_image_url"]))
            if gorsel_ham is None:
                raise ValueError("input_image_url geçerli bir PNG/JPEG görsele çözümlenemedi.")
        if gorsel_ham is not None:
            _input_gorsel_kaydet(job_id, gorsel_ham)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "detail": str(e)})
    except OSError as e:
        logger.error("[Burç] Girdi görseli kaydedilemedi (%s): %s", job_id, e)
        return JSONResponse(
            status_code=500,
            content={"success": False, "detail": "Girdi görseli kaydedilemedi."})

    yontem = str(body.get("method") or body.get("workflow") or "").strip().lower()
    execution_mode = str(body.get("execution_mode") or "").strip().lower()
    if yontem == "image_first_preview":
        yontem = "flux2_resim"
    elif yontem == "image_then_i2v":
        yontem = "wan_i2v" if gorsel_ham is not None else "image_then_i2v"
    if yontem not in ("wan_i2v", "flux2_resim", "burc_video", "image_then_i2v", "hyperframes_motion"):
        yontem = "wan_i2v" if gorsel_ham is not None else "flux2_resim"
    if yontem == "wan_i2v" and gorsel_ham is None:
        return JSONResponse(
            status_code=400,
            content={"success": False,
                     "detail": "wan_i2v için onaylanmış görsel gerekli (image_base64 veya input_image_url)."})

    image_model = str(body.get("image_model") or "flux2-klein").strip()
    i2v_model = str(body.get("i2v_model") or body.get("video_model") or "wan2.1-i2v-14b").strip()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    burc = mod.BURC_KATALOGU.get(str(senaryo.get("burc_kodu") or "").lower(), {})
    ses = str(body.get("voice") or burc.get("varsayilan_ses") or "").strip()
    if not ses:
        try:
            from gemini_audio import get_channel_gemini_voice
            ses = get_channel_gemini_voice("Astroloji")
        except Exception:
            ses = "Aoede"
    tts = await run_in_threadpool(
        lambda: _burc_tts_yaz(metin, ses, MEDIA_DIR / f"{job_id}.wav"))

    altyazi: Dict[str, Any]
    try:
        altyazi = await run_in_threadpool(
            lambda: _burc_altyazi_yaz(
                mod, metin, sure_sn,
                MEDIA_DIR / f"{job_id}.srt", MEDIA_DIR / f"{job_id}.ass"))
    except Exception as e:
        logger.warning("[Burç] Altyazı yazılamadı (%s): %s", job_id, e)
        altyazi = {"ok": False, "hata": f"{type(e).__name__}: {str(e)[:160]}"}

    input_url = f"/api/worker/input/{job_id}" if gorsel_ham is not None else None
    audio_url = f"/api/worker/audio/{job_id}" if tts.get("ok") else None
    subtitle_url = f"/api/worker/subtitle/{job_id}" if altyazi.get("ok") else None
    render_target = str(body.get("render_target") or "kaggle_32gb").strip()
    if render_target not in GPU_HEDEFLERI:
        render_target = "kaggle_32gb"

    scene_prompts = [
        str(s.get("image_prompt") or "").strip()
        for s in (senaryo.get("scenes") or [])
        if isinstance(s, dict) and str(s.get("image_prompt") or "").strip()
    ] or [str(senaryo.get("image_prompt") or metin)[:1200]]

    burc_stili = "cinematic_realism" if (raw_prompt and konu) else "astrology_mystic"

    job = {
        "id": job_id,
        "job_id": job_id,
        "channel": "Astroloji_Kova",
        "model_id": i2v_model if yontem != "flux2_resim" else image_model,
        "model_ad": f"{i2v_model} (Burç I2V)" if yontem != "flux2_resim" else f"{image_model} (Burç önizleme)",
        "image_model": image_model,
        "i2v_model": i2v_model,
        "video_model": i2v_model,
        "style_preset": burc_stili,
        "prompt": str(senaryo.get("image_prompt") or metin)[:1200],
        "image_prompt": str(senaryo.get("image_prompt") or metin)[:1200],
        "motion_prompt": str(senaryo.get("motion_prompt") or "")[:400],
        "planner_source": str(senaryo.get("kaynak") or ""),
        "narration_text": metin,
        "raw_prompt": bool(senaryo.get("raw_prompt") or (raw_prompt and konu)),
        "burc_kodu": senaryo.get("burc_kodu") or burc_kodu,
        "burc_adi": senaryo.get("burc_adi") or burc.get("ad", ""),
        "burc_simge": str(burc.get("simge") or senaryo.get("simge") or ""),
        "method": yontem,
        "mode": ("burc_video" if yontem in ("burc_video", "image_then_i2v")
                 else "flux2_resim" if yontem == "flux2_resim" else "video"),
        "render_target": render_target,
        "aspect_ratio": aspect_ratio,
        "sure_sn": round(sure_sn, 1),
        "voice": ses,
        "status": "kuyrukta (GPU işçisi bekleniyor)",
        "progress_pct": 0,
        "gpu_kuyruk": True,
        "gpu_durum": "bekliyor",
        "simulasyon": False,
        "metin_simulasyon": bool(senaryo.get("simulasyon")),
        "senaryo_kaynak": str(senaryo.get("kaynak") or ""),
        "input_image_url": input_url,
        "audio_url": audio_url,
        "subtitle_url": subtitle_url,
        "preview_image_url": None,
        "output_url": None,
        "download_url": None,
        "artifacts": {
            "kaynak": "gpu_kuyruk",
            "tts": tts,
            "altyazi": altyazi,
            "uyari": senaryo.get("uyari"),
            "not": "Yerel sahte render yapılmadı; gerçek üretim Kaggle/Colab GPU işçisinde.",
        },
        "created_at": time.time(),
    }
    aninda = (
        yontem == "hyperframes_motion"
        or execution_mode in ("instant_cloud", "camera_motion_only")
        or (execution_mode in ("auto", "real_i2v") and not _has_live_gpu_worker())
    )
    if aninda:
        res = await run_in_threadpool(
            lambda: _run_instant_cloud_render_sync(
                job_id=job_id,
                method=yontem if yontem != "burc_video" else "hyperframes_motion",
                prompt=metin,
                image_prompts=scene_prompts,
                motion_prompt=job["motion_prompt"],
                aspect_ratio=job["aspect_ratio"],
                style_preset=burc_stili,
                camera_motion=str(body.get("camera_motion") or "orbital"),
                duration_sec=sure_sn,
                execution_mode=execution_mode or "instant_cloud",
            )
        )
        if res.get("needs_gpu_worker"):
            job["status"] = "kuyrukta (Gerçek I2V GPU bekleniyor)"
            job["preview_image_url"] = input_url
            _append_job_record(job)
            return {
                "success": True,
                "job_id": job_id,
                "task": job,
                "burc": {"kod": job["burc_kodu"], "ad": job["burc_adi"], "simge": job["burc_simge"]},
                "senaryo": {
                    "narration_text": metin,
                    "image_prompt": job["prompt"],
                    "motion_prompt": job["motion_prompt"],
                    "simulasyon": bool(senaryo.get("simulasyon")),
                    "kaynak": job["senaryo_kaynak"],
                },
                "input_image_url": input_url,
                "audio_url": audio_url,
                "subtitle_url": subtitle_url,
                "gpu_kuyruk": True,
                "gpu_durum": "bekliyor",
                "needs_gpu_worker": True,
                "message": str(res.get("error") or "Gerçek karakter canlandırma için GPU işçisi bekleniyor; kamera zoom/pan uygulanmadı."),
            }
        if not res.get("ok"):
            return JSONResponse(status_code=502, content={"success": False, "detail": res.get("error") or "Burç anında bulut render başarısız."})
        _finalize_instant_cloud_job(job, res)
        _append_job_record(job)
        return {
            "success": True,
            "job_id": job_id,
            "task": job,
            "burc": {"kod": job["burc_kodu"], "ad": job["burc_adi"], "simge": job["burc_simge"]},
            "senaryo": {
                "narration_text": metin,
                "image_prompt": job["prompt"],
                "motion_prompt": job["motion_prompt"],
                "simulasyon": bool(senaryo.get("simulasyon")),
                "kaynak": job["senaryo_kaynak"],
            },
            "input_image_url": input_url,
            "audio_url": audio_url,
            "subtitle_url": subtitle_url,
            "output_url": job.get("output_url"),
            "download_url": job.get("download_url"),
            "preview_image_url": job.get("preview_image_url"),
            "hyperframes_url": job.get("hyperframes_url"),
            "gpu_kuyruk": False,
            "gpu_durum": job["gpu_durum"],
            "simulasyon": job["simulasyon"],
            "video_difuzyonu": job.get("video_difuzyonu", False),
            "message": job["message"],
        }

    _append_job_record(job)
    mesaj = (
        "Wan2.1 I2V işi GPU kuyruğuna alındı."
        if yontem == "wan_i2v"
        else "FLUX.2 önizleme görseli GPU kuyruğuna alındı; onay sonrası wan_i2v ile devam edin."
    )
    return {
        "success": True,
        "job_id": job_id,
        "task": job,
        "burc": {"kod": job["burc_kodu"], "ad": job["burc_adi"], "simge": job["burc_simge"]},
        "senaryo": {
            "narration_text": metin,
            "image_prompt": job["prompt"],
            "motion_prompt": job["motion_prompt"],
            "simulasyon": bool(senaryo.get("simulasyon")),
            "kaynak": job["senaryo_kaynak"],
        },
        "input_image_url": input_url,
        "audio_url": audio_url,
        "subtitle_url": subtitle_url,
        "gpu_kuyruk": True,
        "gpu_durum": "bekliyor",
        "message": mesaj,
    }


@app.get("/api/studio/queue", dependencies=[Depends(verify_auth)])
async def get_studio_queue(status: str = "all", limit: int = 50):
    """GPU kuyruğunda bekleyen ve tamamlanan stüdyo işlerini döner."""
    _release_expired_claims()
    _prune_stale_workers()
    with JOBS_LOCK:
        jobs = list(_load_jobs_unlocked().get("jobs", []))
    jobs.sort(key=lambda j: float(j.get("created_at") or 0), reverse=True)
    waiting_count = sum(1 for j in jobs if j.get("gpu_kuyruk") and j.get("gpu_durum") in ("bekliyor", "isleniyor"))
    st = (status or "all").strip().lower()
    if st == "bekliyor":
        jobs = [j for j in jobs if j.get("gpu_kuyruk") and j.get("gpu_durum") in ("bekliyor", "isleniyor")]
    elif st == "tamamlandi":
        jobs = [j for j in jobs if j.get("output_url")]
    lim = max(1, min(int(limit or 50), 100))
    return {
        "success": True,
        "active_workers_count": len(ACTIVE_GPU_WORKERS),
        "waiting_count": waiting_count,
        "items": jobs[:lim],
    }


@app.post("/api/studio/queue/{job_id}/instant-render", dependencies=[Depends(verify_auth)])
async def studio_queue_instant_render(job_id: str):
    """Kuyrukta bekleyen bir işi GPU işçisi beklemeden anında bulutta render eder."""
    jid = _validate_job_id(job_id)
    with JOBS_LOCK:
        veri = _load_jobs_unlocked()
        kayit = next((dict(j) for j in veri.get("jobs", []) if _is_job(j, jid)), None)
    if kayit is None:
        raise HTTPException(status_code=404, detail="İş kaydı bulunamadı.")

    hedef_yontem = str(kayit.get("method") or "image_then_i2v")
    if hedef_yontem == "burc_video":
        hedef_yontem = "hyperframes_motion"
    res = await run_in_threadpool(
        lambda: _run_instant_cloud_render_sync(
            job_id=jid,
            method=hedef_yontem,
            prompt=str(kayit.get("prompt") or "yusasufhin Studio"),
            image_prompts=[str(kayit.get("image_prompt") or kayit.get("prompt") or "")],
            motion_prompt=str(kayit.get("motion_prompt") or ""),
            aspect_ratio=str(kayit.get("aspect_ratio") or "16:9"),
            style_preset=str(kayit.get("style_preset") or "cinematic_realism"),
            camera_motion=str(kayit.get("camera_motion") or "orbital"),
            duration_sec=float(kayit.get("sure_sn") or 5.0),
            source_url=kayit.get("source_url"),
        )
    )
    if not res.get("ok"):
        return JSONResponse(status_code=502, content={"success": False, "detail": res.get("error") or "Anında render başarısız."})

    guncel: Dict[str, Any] = {}

    def _uygula(data: Dict[str, Any]) -> None:
        for item in data.get("jobs", []):
            if _is_job(item, jid):
                _finalize_instant_cloud_job(item, res)
                guncel.update(item)
                break

    _update_jobs(_uygula)
    return {"success": True, "job_id": jid, "task": guncel, "job": guncel, "message": guncel.get("message")}


@app.post("/api/studio/queue/{job_id}/requeue-gpu", dependencies=[Depends(verify_auth)])
async def studio_queue_requeue_gpu(job_id: str):
    """Mevcut işi (veya onaylı önizlemesini) gerçek Wan2.1/LTX GPU kuyruğuna yükseltir."""
    jid = _validate_job_id(job_id)
    with JOBS_LOCK:
        veri = _load_jobs_unlocked()
        eski = next((dict(j) for j in veri.get("jobs", []) if _is_job(j, jid)), None)
    if eski is None:
        raise HTTPException(status_code=404, detail="İş kaydı bulunamadı.")

    if eski.get("output_url") or str(eski.get("gpu_durum") or "").startswith("tamamlandi"):
        yeni_id = _new_job_id()
        input_url = None
        for ext_ad in (f"{jid}_input.png", f"{jid}_preview.png"):
            src = MEDIA_DIR / ext_ad
            if src.is_file():
                dst = MEDIA_DIR / f"{yeni_id}_input.png"
                shutil.copy2(src, dst)
                input_url = f"/api/worker/input/{yeni_id}"
                break
        for ek in (".wav", ".srt", ".ass"):
            src_ek = MEDIA_DIR / f"{jid}{ek}"
            if src_ek.is_file():
                shutil.copy2(src_ek, MEDIA_DIR / f"{yeni_id}{ek}")

        yeni_is = {
            **eski,
            "id": yeni_id,
            "job_id": yeni_id,
            "parent_job_id": jid,
            "method": "wan_i2v" if input_url else "image_then_i2v",
            "mode": "wan_i2v" if input_url else "image_then_i2v",
            "input_image_url": input_url,
            "audio_url": f"/api/worker/audio/{yeni_id}" if (MEDIA_DIR / f"{yeni_id}.wav").is_file() else eski.get("audio_url"),
            "subtitle_url": f"/api/worker/subtitle/{yeni_id}" if (MEDIA_DIR / f"{yeni_id}.srt").is_file() else eski.get("subtitle_url"),
            "output_url": None,
            "download_url": None,
            "gpu_kuyruk": True,
            "gpu_durum": "bekliyor",
            "status": "kuyrukta (GPU işçisi bekleniyor)",
            "progress_pct": 0,
            "simulasyon": False,
            "created_at": time.time(),
            "message": f"Gerçek Wan2.1/LTX GPU yükseltmesi ({yeni_id}) kuyruğa alındı.",
        }
        yeni_is.pop("claimed_by", None)
        yeni_is.pop("claimed_at", None)
        _append_job_record(yeni_is)
        return {"success": True, "job_id": yeni_id, "task": yeni_is, "message": yeni_is["message"]}

    guncel: Dict[str, Any] = {}

    def _reset(data: Dict[str, Any]) -> None:
        for item in data.get("jobs", []):
            if _is_job(item, jid):
                item["gpu_kuyruk"] = True
                item["gpu_durum"] = "bekliyor"
                item["status"] = "kuyrukta (GPU işçisi bekleniyor)"
                item["progress_pct"] = 0
                item.pop("claimed_by", None)
                item.pop("claimed_at", None)
                guncel.update(item)
                break

    _update_jobs(_reset)
    return {"success": True, "job_id": jid, "task": guncel, "message": "İş GPU kuyruğuna yeniden alındı."}


@app.post("/api/studio/queue/{job_id}/cancel", dependencies=[Depends(verify_auth)])
async def studio_queue_cancel(job_id: str):
    """Kuyrukta bekleyen işi iptal eder."""
    jid = _validate_job_id(job_id)
    bulundu = {"ok": False}

    def _iptal(data: Dict[str, Any]) -> None:
        for item in data.get("jobs", []):
            if _is_job(item, jid):
                item["gpu_kuyruk"] = False
                item["gpu_durum"] = "iptal"
                item["status"] = "iptal_edildi"
                bulundu["ok"] = True
                break

    _update_jobs(_iptal)
    if not bulundu["ok"]:
        raise HTTPException(status_code=404, detail="İş kaydı bulunamadı.")
    return {"success": True, "job_id": jid, "status": "iptal_edildi"}


@app.post("/api/studio/analyze-video", dependencies=[Depends(verify_auth)])
async def studio_analyze_video(req: Request):
    """Link #296 (`rea-video`): Seçili MP4'ün sahne kesimleri & teknik şemasını çıkarır."""
    from hyperframes_motor import rea_video_reverse_blueprint

    try:
        body = await req.json()
    except Exception:
        body = {}
    jid_raw = str(body.get("job_id") or "").strip()
    path_raw = str(body.get("path") or body.get("video_url") or "").strip()
    target: Optional[Path] = None
    if jid_raw:
        jid = _validate_job_id(jid_raw)
        cand = (MEDIA_DIR / f"{jid}.mp4").resolve()
        if cand.is_file():
            target = cand
    if target is None and path_raw:
        m = re.search(r"[?&]path=([^&]+)", path_raw)
        ad = Path(urllib.parse.unquote(m.group(1)) if m else path_raw).name
        if ad and not ad.startswith(".") and JOB_ID_RE.match(ad):
            for kok in (MEDIA_DIR, DATA_MEDIA_DIR):
                cand = (kok / ad).resolve()
                if cand.is_file() and cand.is_relative_to(kok):
                    target = cand
                    break
    if target is None or not target.is_file():
        return JSONResponse(status_code=404, content={"success": False, "detail": "Analiz edilecek MP4 dosyası bulunamadı."})

    sonuc = await run_in_threadpool(lambda: rea_video_reverse_blueprint(target))
    return {"success": bool(sonuc.get("ok")), **sonuc}


@app.get("/api/studio/hyperframes/{job_id}", dependencies=[Depends(verify_auth)])
async def get_studio_hyperframes(job_id: str):
    """İş için oluşturulan HyperFrames HTML5 zaman çizelgesini güvenle servis eder."""
    jid = _validate_job_id(job_id)
    hedef = (MEDIA_DIR / f"{jid}_hyperframes.html").resolve()
    if not hedef.is_file() or not hedef.is_relative_to(MEDIA_DIR):
        raise HTTPException(status_code=404, detail="HyperFrames zaman çizelgesi bulunamadı.")
    return FileResponse(
        hedef,
        media_type="text/html; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; media-src blob:; connect-src 'none'",
            "Content-Disposition": f'inline; filename="{jid}_hyperframes.html"',
        },
    )


# -----------------------------------------------------------------------------
# 7. GPU KÜMESİ TELEMETRİSİ, BULUT İŞÇİ PROTOKOLÜ (KAGGLE / COLAB)
# -----------------------------------------------------------------------------
CURRENT_GPU_MODE = "kaggle_first"
ACTIVE_GPU_WORKERS: Dict[str, Dict[str, Any]] = {}

def _prune_stale_workers():
    now = time.time()
    stale = [wid for wid, w in ACTIVE_GPU_WORKERS.items() if now - w.get("last_seen", 0) > 60]
    for wid in stale:
        ACTIVE_GPU_WORKERS.pop(wid, None)

@app.get("/api/gpu/cluster/status", dependencies=[Depends(verify_auth)])
async def gpu_status():
    """Gerçek GPU işçi bağlantı durumu (Kural 1 gereği dürüst telemetri)."""
    _prune_stale_workers()
    _release_expired_claims()
    kaggle_connected = any(w.get("worker_type") == "kaggle" for w in ACTIVE_GPU_WORKERS.values())
    colab_connected = any(w.get("worker_type") == "colab" for w in ACTIVE_GPU_WORKERS.values())
    toplam_vram = sum(float(w.get("vram_gb", 0)) for w in ACTIVE_GPU_WORKERS.values())
    gpu_bagli = bool(kaggle_connected or colab_connected)
    aktif_sayi = len(ACTIVE_GPU_WORKERS)

    if gpu_bagli:
        st_label = "active (Kaggle Dual-T4 Bağlı)" if kaggle_connected else "active (Google Colab T4 Bağlı)"
        msg = f"Canlı GPU işçisi bağlı ({toplam_vram:.1f} GB vRAM). İşler bulut GPU'sunda render edilmektedir."
    else:
        st_label = "standby (GPU işçisi bekleniyor)"
        msg = (
            "Canlı GPU işçisi bağlı değil. GPU render hakkında hiçbir çevrimiçi iddia yoktur; "
            "işler kuyrukta bekler, Kaggle/Colab bağlandığında gerçek difüzyonla işlenir."
        )

    return {
        "success": True,
        "status": {
            "cluster_status": st_label,
            "gpu_bagli": gpu_bagli,
            "colab_connected": colab_connected,
            "kaggle_connected": kaggle_connected,
            "allocated_vram_gb": toplam_vram if gpu_bagli else 0.0,
            "mode": CURRENT_GPU_MODE,
            "active_workers_count": aktif_sayi,
            "workers": list(ACTIVE_GPU_WORKERS.values()),
            "message": msg,
            "simulasyon": not gpu_bagli,
        }
    }

@app.get("/api/gpu/worker-setup", dependencies=[Depends(verify_auth)])
async def gpu_worker_setup(request: Request):
    """Oturum açmış kullanıcı için Kaggle/Colab işçi kurulum bilgisi (anahtar korumalı)."""
    temel = str(request.base_url).rstrip("/")
    anahtar = get_worker_key()
    komut = (
        f"FABRIKA_WORKER_KEY={anahtar} python gpu_worker.py "
        f"--server {temel} --token {anahtar} --tek-seferlik"
    )
    return {
        "success": True,
        "server": temel,
        "worker_key": anahtar,
        "worker_key_env": "FABRIKA_WORKER_KEY",
        "worker_key_header": "X-Worker-Key",
        "worker_script_url": f"{temel}/worker.py",
        "command": komut,
        "not": (
            "İşçi uçları X-Worker-Key veya Authorization: Bearer <worker_key> ister. "
            "Anahtarı paylaşmayın; yalnız GPU çalışma ortamına girin."
        ),
    }

@app.post("/api/gpu/cluster/mode", dependencies=[Depends(verify_auth)])
async def gpu_mode(req: Request):
    global CURRENT_GPU_MODE
    body = await req.json()
    CURRENT_GPU_MODE = body.get("mode", "kaggle_first")
    return {"success": True, "mode": CURRENT_GPU_MODE, "status": "switched"}

@app.post("/api/worker/heartbeat", dependencies=[Depends(verify_worker_key)])
async def worker_heartbeat(req: Request):
    """Kaggle veya Google Colab GPU işçisinden gelen canlı sinyal (heartbeat)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    wid = str(body.get("worker_id") or f"worker_{int(time.time())}")[:80]
    try:
        vram = float(body.get("vram_gb", 16.0))
    except (TypeError, ValueError):
        vram = 0.0
    ACTIVE_GPU_WORKERS[wid] = {
        "worker_id": wid,
        "worker_type": body.get("worker_type", "kaggle"),
        "gpu_name": body.get("gpu_name", "Tesla T4"),
        "vram_gb": vram,
        "status": body.get("status", "idle"),
        "last_seen": time.time(),
        "tasks_completed": body.get("tasks_completed", 0)
    }
    return {"success": True, "registered": True, "server_time": time.time()}

def _worker_job_payload(job: Dict[str, Any]) -> Dict[str, Any]:
    """Claim yanıtına gerçek ek dosya URL'lerini ekler (dosya yoksa eklemez)."""
    if job.get("sure_sn") is not None or job.get("duration") is not None:
        job["duration"] = job.get("duration") or job.get("sure_sn") or 15.0
    # motion_prompt varsa işçiye aynen taşınır: Wan2.1 I2V animasyonunu bu sürer.
    if job.get("motion_prompt"):
        job["motion_prompt"] = str(job["motion_prompt"])[:500]
    for anahtar in ("image_model", "i2v_model", "video_model", "negative_prompt", "workflow", "style_preset"):
        if job.get(anahtar):
            job[anahtar] = str(job[anahtar])[:400]
    jid = str(job.get("job_id") or job.get("id") or "")
    if not jid or not JOB_ID_RE.match(jid):
        return job
    gorsel_bulundu = False
    for ad in (f"{jid}_input.png", f"{jid}_input.jpg"):
        if (MEDIA_DIR / ad).is_file():
            job["input_image_url"] = f"/api/worker/input/{jid}"
            gorsel_bulundu = True
            break
    if not gorsel_bulundu:
        job.pop("input_image_url", None)
    if (MEDIA_DIR / f"{jid}.wav").is_file():
        job["audio_url"] = f"/api/worker/audio/{jid}"
    if (MEDIA_DIR / f"{jid}.srt").is_file() or (MEDIA_DIR / f"{jid}.ass").is_file():
        job["subtitle_url"] = f"/api/worker/subtitle/{jid}"
    return job

@app.get("/api/worker/claim", dependencies=[Depends(verify_worker_key)])
async def worker_claim(worker_id: Optional[str] = Query(None)):
    """Kaggle veya Colab GPU işçisinin sıradaki video görevini alması.

    `gpu_kuyruk=True` işaretli kayıtlar önceliklidir. Claim/kuyruk işlemleri
    kilit altında ve atomik yazılır; 45 dakikayı aşan claim'ler geri bırakılır.
    """
    _prune_stale_workers()
    secilen: Optional[Dict[str, Any]] = None
    mod = ""
    with JOBS_LOCK:
        data = _load_jobs_unlocked()
        degisti = _release_expired_claims_data(data)
        jobs = data.get("jobs", [])

        # 1) Açıkça GPU'ya bırakılmış işler (öncelik)
        for j in jobs:
            if j.get("gpu_kuyruk") and j.get("gpu_durum") == "bekliyor":
                j["gpu_durum"] = "isleniyor"
                j["claimed_by"] = worker_id or "gpu_worker"
                j["claimed_at"] = time.time()
                j["status"] = "isleniyor (GPU render)"
                secilen = j
                mod = "gpu_kuyruk"
                break

        # 2) Eski davranış (geriye dönük uyumluluk) — zaten claim edilmişi atla
        if secilen is None:
            for j in jobs:
                if j.get("gpu_kuyruk") or j.get("claimed_by"):
                    continue
                st = str(j.get("status", ""))
                if "kuyrukta" in st or "onizleme_hazir" in st:
                    j["status"] = "isleniyor (GPU render)"
                    j["claimed_by"] = worker_id or "gpu_worker"
                    j["claimed_at"] = time.time()
                    secilen = j
                    mod = "eski"
                    break

        if secilen is not None or degisti:
            _save_jobs_unlocked(data)

    if secilen is not None:
        _worker_job_payload(secilen)
        return {"success": True, "job": secilen, "mod": mod}
    return {"success": True, "job": None, "message": "İş yok"}

@app.post("/api/worker/progress", dependencies=[Depends(verify_worker_key)])
async def worker_progress(req: Request):
    """GPU işçisinin render ilerlemesini (veya başarısızlığını) bildirmesi."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    jid = _validate_job_id(str(body.get("job_id") or ""))
    try:
        pct = int(body.get("progress_pct", 0))
    except (TypeError, ValueError):
        pct = 0
    pct = max(0, min(100, pct))
    stage = str(body.get("stage") or "GPU Render")[:200]
    failed = bool(body.get("failed")) or stage.lower().startswith("basarisiz")

    def _guncelle(data: Dict[str, Any]) -> None:
        for j in data.get("jobs", []):
            if not _is_job(j, jid):
                continue
            j["progress_pct"] = pct
            j["current_stage"] = stage
            j["updated_at"] = time.time()
            if failed:
                j["status"] = "basarisiz (GPU işçisi)"
                j["gpu_durum"] = "basarisiz"
                j["simulasyon"] = False
                j["error"] = str(body.get("error") or stage)[:300]
            break

    try:
        _update_jobs(_guncelle)
    except OSError as e:
        logger.error("[WorkerProgress] Kayıt güncellenemedi (%s): %s", jid, e)
        raise HTTPException(status_code=500, detail="İş kaydı güncellenemedi.")
    return {"success": True, "job_id": jid, "failed": failed}

def _mark_worker_failed(job_id: str, hata: str) -> None:
    def _guncelle(data: Dict[str, Any]) -> None:
        for j in data.get("jobs", []):
            if not _is_job(j, job_id):
                continue
            j["status"] = "basarisiz (GPU işçisi)"
            j["gpu_durum"] = "basarisiz"
            j["progress_pct"] = 0
            j["simulasyon"] = False
            j["error"] = hata[:300]
            break
    _update_jobs(_guncelle)

def _gorsel_media_type(yol: Path) -> str:
    try:
        with yol.open("rb") as fh:
            tur = _gorsel_turu(fh.read(8))
    except OSError:
        return "application/octet-stream"
    if tur == "png":
        return "image/png"
    if tur == "jpeg":
        return "image/jpeg"
    return "application/octet-stream"

@app.post("/api/worker/upload", dependencies=[Depends(verify_worker_key)])
async def worker_upload(
    job_id: str = Form(...),
    file: Optional[UploadFile] = File(None),
    media_type: Optional[str] = Form(None),
    failed: bool = Form(False),
    error_message: Optional[str] = Form(None),
):
    """GPU işçisinin MP4 videosunu veya FLUX.2 önizleme PNG/JPEG'ini yüklemesi.

    * 250 MB üst sınır parça parça okunarak uygulanır (bellek şişmez).
    * MP4 `_mp4_oynatilabilir` doğrulamasından geçmeden kaydedilmez/başarı sayılmaz.
    * `media_type=image` için PNG/JPEG sihirli baytları zorunludur.
    * `failed=true` işi dürüstçe "basarisiz" işaretler; sahte çıktı üretmez.
    """
    jid = _validate_job_id(job_id)

    if failed:
        _mark_worker_failed(jid, error_message or "GPU işçisi işi başarısız bildirdi.")
        return {
            "success": False,
            "job_id": jid,
            "status": "basarisiz",
            "message": "İşçi hatası kaydedildi; sahte çıktı üretilmedi.",
        }

    if file is None:
        raise HTTPException(status_code=400, detail="Yüklenecek dosya (file) eksik.")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    uzanti = Path(file.filename or "").suffix.lower()
    gorsel_mi = (media_type or "").strip().lower() == "image" or uzanti in (".png", ".jpg", ".jpeg")
    gecici = MEDIA_DIR / f".{jid}.upload.part"
    boyut = 0

    gecici.unlink(missing_ok=True)
    try:
        with gecici.open("wb") as fh:
            while True:
                parca = await file.read(1024 * 1024)
                if not parca:
                    break
                boyut += len(parca)
                if boyut > MAX_WORKER_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Yükleme {MAX_WORKER_UPLOAD_BYTES // (1024 * 1024)} MB sınırını aşıyor.",
                    )
                await run_in_threadpool(fh.write, parca)
        if boyut == 0:
            raise HTTPException(status_code=400, detail="Boş dosya yüklenemez.")

        if gorsel_mi:
            with gecici.open("rb") as fh:
                tur = _gorsel_turu(fh.read(8))
            if tur is None:
                raise HTTPException(
                    status_code=422,
                    detail="Görsel PNG veya JPEG değil (sihirli baytlar doğrulanamadı).",
                )
            hedef = MEDIA_DIR / f"{jid}_preview{'.png' if tur == 'png' else '.jpg'}"
            os.replace(gecici, hedef)
            onizleme_url = f"/api/media/file?path={hedef.name}"

            def _gorsel_kaydet(data: Dict[str, Any]) -> None:
                for j in data.get("jobs", []):
                    if not _is_job(j, jid):
                        continue
                    j["preview_image_url"] = onizleme_url
                    j["simulasyon"] = False
                    j["kaynak"] = f"gpu_worker_{j.get('image_model') or 'flux2'}"
                    j["file_size_bytes"] = boyut
                    j["size_kb"] = max(1, round(boyut / 1024))
                    j.pop("error", None)
                    if str(j.get("method") or "").lower() in ("image_then_i2v", "burc_video") and j.get("gpu_durum") == "isleniyor":
                        j["progress_pct"] = 45
                        j["status"] = "isleniyor (Anahtar görsel hazır, I2V üretiliyor)"
                    else:
                        j["progress_pct"] = 100
                        j["status"] = "onizleme_hazir"
                        j["gpu_durum"] = "tamam"
                    break
            try:
                _update_jobs(_gorsel_kaydet)
            except OSError as e:
                logger.error("[WorkerUpload] Görsel iş kaydı güncellenemedi (%s): %s", jid, e)
            return {
                "success": True,
                "job_id": jid,
                "media_type": "image",
                "file_size_bytes": boyut,
                "preview_image_url": onizleme_url,
            }

        if not _mp4_oynatilabilir(gecici):
            raise HTTPException(
                status_code=422,
                detail="MP4 doğrulanamadı (ftyp/moov/mdat eksik veya dosya yarım). Kaydedilmedi.",
            )
        hedef = MEDIA_DIR / f"{jid}.mp4"
        os.replace(gecici, hedef)
        try:
            from cloud_storage import put_file
            await run_in_threadpool(lambda: put_file(hedef, content_type="video/mp4"))
        except Exception:
            pass
        cikti_url = f"/api/media/file?path={hedef.name}"
        indirme_url = f"{cikti_url}&download=1"

        def _video_kaydet(data: Dict[str, Any]) -> None:
            for j in data.get("jobs", []):
                if not _is_job(j, jid):
                    continue
                j["status"] = "tamamlandi (GPU render)"
                j["progress_pct"] = 100
                j["file_size_bytes"] = boyut
                j["size_kb"] = max(1, round(boyut / 1024))
                j["simulasyon"] = False
                j["gpu_durum"] = "tamam"
                j["kaynak"] = str(j.get("kaynak") or "gpu_worker_wan21_flux2")
                j["output_url"] = cikti_url
                j["download_url"] = indirme_url
                try:
                    from channels_manager import ChannelStore

                    j["youtube_bundle"] = ChannelStore(DATA_DIR).build_publish_bundle(j, MEDIA_DIR)
                except Exception:
                    pass
                j.pop("error", None)
                break
        try:
            _update_jobs(_video_kaydet)
        except OSError as e:
            logger.error("[WorkerUpload] Video iş kaydı güncellenemedi (%s): %s", jid, e)

        return {
            "success": True,
            "job_id": jid,
            "media_type": "video",
            "file_size_bytes": boyut,
            "output_url": cikti_url,
            "download_url": indirme_url,
        }
    finally:
        gecici.unlink(missing_ok=True)

@app.get("/api/worker/input/{job_id}", dependencies=[Depends(verify_worker_key)])
async def worker_input(job_id: str):
    """İşçinin I2V/FLUX girdi görselini indirdiği korumalı uç."""
    jid = _validate_job_id(job_id)
    for ad in (f"{jid}_input.png", f"{jid}_input.jpg"):
        yol = MEDIA_DIR / ad
        if yol.is_file():
            return FileResponse(yol, media_type=_gorsel_media_type(yol))
    raise HTTPException(status_code=404, detail="Girdi görseli bulunamadı.")

@app.get("/api/worker/audio/{job_id}", dependencies=[Depends(verify_worker_key)])
async def worker_audio(job_id: str):
    """İşçinin TTS seslendirmesini indirdiği korumalı uç."""
    jid = _validate_job_id(job_id)
    for ad, mt in ((f"{jid}.wav", "audio/wav"), (f"{jid}.mp3", "audio/mpeg")):
        yol = MEDIA_DIR / ad
        if yol.is_file():
            return FileResponse(yol, media_type=mt)
    raise HTTPException(status_code=404, detail="Ses dosyası bulunamadı.")

@app.get("/api/worker/subtitle/{job_id}", dependencies=[Depends(verify_worker_key)])
async def worker_subtitle(job_id: str):
    """İşçinin SRT/ASS altyazısını indirdiği korumalı uç."""
    jid = _validate_job_id(job_id)
    for ad, mt in (
        (f"{jid}.srt", "application/x-subrip; charset=utf-8"),
        (f"{jid}.ass", "text/x-ssa; charset=utf-8"),
    ):
        yol = MEDIA_DIR / ad
        if yol.is_file():
            return FileResponse(yol, media_type=mt)
    raise HTTPException(status_code=404, detail="Altyazı dosyası bulunamadı.")


# -----------------------------------------------------------------------------
# 8. OMNIROUTE MODEL ŞELALESİ & ANTI-SLOP
# -----------------------------------------------------------------------------
@app.get("/api/omniroute/status", dependencies=[Depends(verify_auth)])
async def omniroute_status():
    return {
        "status": "operational",
        "cost_sla": "$0.00 (Doğrulanmadı: Ücretsiz model havuzu)",
        "verified_providers_count": 4,
        "global_openrouter_endpoints": "375 (Doğrulanmadı: Katalog tahmini)",
        "active_waterfall_tiers": [
            {"tier": 1, "model": "deepseek/deepseek-chat:free", "provider": "DeepSeek / OpenRouter"},
            {"tier": 2, "model": "meta-llama/llama-3.3-70b-instruct:free", "provider": "Groq / OpenRouter"},
            {"tier": 3, "model": "google/gemini-2.0-flash-exp:free", "provider": "Google Cloud"},
            {"tier": 4, "model": "qwen/qwen-2.5-72b-instruct:free", "provider": "SiliconFlow / OpenRouter"}
        ]
    }

@app.post("/api/omniroute/generate", dependencies=[Depends(verify_auth)])
async def omniroute_generate(req: Request):
    body = await req.json()
    prompt = str(body.get("prompt", "")).strip()

    # 1. Gerçek Gemini API çağrısı dene
    gemini_key = get_secret_from_env("GEMINI_API_KEY")
    if gemini_key and prompt:
        basla = time.perf_counter()
        try:
            import urllib.request
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
            api_req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(api_req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return {
                    "success": True,
                    "result": {
                        "display_name": "Gemini 2.0 Flash (Live Free Tier)",
                        "tier": 1,
                        "provider": "Google Cloud",
                        "latency_ms": round((time.perf_counter() - basla) * 1000),
                        "fallbacks_attempted": [],
                        "cost": "$0.00",
                        "simulasyon": False,
                        "content": text
                    }
                }
        except Exception as e:
            logger.warning("Canlı Gemini API çağrısı başarısız: %s", e)

    # 2. Canlı API yoksa Kural 1 uyarınca açıkça simülasyon etiketiyle dön
    return {
        "success": True,
        "result": {
            "display_name": "Llama 3.3 70B Instruct (Kılavuz Simülasyon)",
            "tier": 2,
            "provider": "Groq / OpenRouter Cloud Edge",
            "latency_ms": 0,
            "fallbacks_attempted": [],
            "cost": "$0.00",
            "simulasyon": True,
            "content": f"(simülasyon: model çıktısı simüle edildi)\nOmniRoute kılavuz yanıtı: '{prompt}' talebiniz alındı."
        }
    }

@app.post("/api/humanizer/clean", dependencies=[Depends(verify_auth)])
async def humanizer_clean(req: Request):
    body = await req.json()
    raw_text = body.get("text", "")
    slop_words = [
        "Sonuç olarak", "Şüphesiz ki", "dikkate değerdir ki", "altını çizmek gerekir ki",
        "Umarım faydalı olmuştur", "Sorunuz olursa çekinmeyin", "Gelin birlikte inceleyelim",
        "Bu bağlamda", "Oldukça önemlidir", "Göz ardı edilemez", "doğrudan", "her alanda"
    ]
    cleaned = raw_text
    count = 0
    for word in slop_words:
        if word.lower() in cleaned.lower():
            count += 1
            cleaned = re.sub(re.escape(word), "", cleaned, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split())
    if cleaned and not cleaned.endswith("."):
        cleaned += "."

    words = raw_text.split()
    total_words = len(words)
    if total_words > 0:
        human_score = max(0, min(100, round((1.0 - (count / max(1, total_words))) * 100)))
    else:
        human_score = None

    return {
        "success": True,
        "cleaned_text": cleaned,
        "analysis": {
            "human_score": human_score,
            "is_organic": (count == 0),
            "slop_count": count
        }
    }

# -----------------------------------------------------------------------------
# 9. GÜVENLİK, REA (GERÇEK AST), MEDYA (R2 + İZOLASYON) & MAC PORT-443 KÖPRÜSÜ
# -----------------------------------------------------------------------------
MEDIA_DIR = (BASE_DIR / "storage" / "media").resolve()
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
LEGACY_MEDIA_DIR = (BASE_DIR / "static" / "media").resolve()
DATA_MEDIA_DIR = (BASE_DIR / "data").resolve()

ALLOWED_MEDIA_EXT = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp3", ".ogg", ".wav",
    ".mp4", ".webm", ".mov",
    ".srt", ".ass",
    ".pdf"
}

@app.api_route("/api/media/file", methods=["GET", "HEAD"], dependencies=[Depends(verify_auth)])
async def get_media_file(path: str, download: Optional[int] = Query(0)):
    """Path Traversal ve Keyfi Dosya Okuma Açıklarına Karşı %100 Yalıtılmış & Korumalı Medya Sunucu."""
    from cloud_storage import ensure_local

    if not path:
        return JSONResponse(status_code=400, content={"detail": "Dosya yolu parametresi eksik."})

    # Dosya adını sanitize et, dizin atlama (path traversal) girişimlerini nötralize et
    file_name = Path(path).name
    if not file_name or file_name.startswith("."):
        return JSONResponse(status_code=403, content={"detail": "Geçersiz dosya adı veya gizli dosya erişimi engellendi."})

    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_MEDIA_EXT:
        return JSONResponse(status_code=415, content={"detail": "Yalnızca doğrulanmış medya formatları desteklenir."})

    # Dosyayı yalnızca yalıtılmış storage/media, eski static/media veya video_factory içinde ara (data/ hariç!)
    target = (MEDIA_DIR / file_name).resolve()
    if not target.is_file() and LEGACY_MEDIA_DIR.is_dir():
        legacy_cand = (LEGACY_MEDIA_DIR / file_name).resolve()
        if legacy_cand.is_file() and legacy_cand.is_relative_to(LEGACY_MEDIA_DIR):
            target = legacy_cand
    if not target.is_file():
        for _aday in sorted((BASE_DIR / "video_factory").glob(f"*/{file_name}"), reverse=True):
            if _aday.is_file():
                target = _aday.resolve()
                break
    if not target.is_file():
        restored = (MEDIA_DIR / file_name).resolve()
        if restored.is_relative_to(MEDIA_DIR) and await run_in_threadpool(lambda: ensure_local(restored)):
            target = restored

    _izinli_kokler = (MEDIA_DIR, LEGACY_MEDIA_DIR, (BASE_DIR / "video_factory").resolve())
    if target.is_file() and any(target.is_relative_to(k) for k in _izinli_kokler):
        if ext == ".mp4" and not _mp4_oynatilabilir(target):
            return JSONResponse(
                status_code=422,
                content={
                    "detail": (
                        "Bu MP4 dosyası bozuk/yarım kalmış (moov atomu yok) ve oynatılamaz. "
                        "Videoyu stüdyodan yeniden üretin."
                    )
                },
            )
        media_types = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif", ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg", ".wav": "audio/wav", ".mp4": "video/mp4",
            ".webm": "video/webm", ".mov": "video/quicktime", ".pdf": "application/pdf",
            ".srt": "application/x-subrip; charset=utf-8", ".ass": "text/x-ssa; charset=utf-8",
        }
        safe_disp_name = re.sub(r'["\\\r\n]', "_", file_name)
        disp = f'attachment; filename="{safe_disp_name}"' if download else "inline"
        return FileResponse(
            target,
            media_type=media_types.get(ext, "application/octet-stream"),
            headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": disp}
        )
    return JSONResponse(status_code=404, content={"detail": "Medya dosyası bulunamadı."})

@app.post("/api/rea/scan", dependencies=[Depends(verify_auth)])
async def rea_scan(req: Request):
    """Gerçek Python AST + Desen Tabanlı Güvenlik Analizörü (`hedef`, `code`, `snippet`, `url`)."""
    from rea_analyzer import analyze_code

    try:
        body = await req.json()
    except Exception:
        body = {}
    target_code = (
        body.get("hedef")
        or body.get("code")
        or body.get("snippet")
        or body.get("url")
        or ""
    )
    persona = str(body.get("persona") or "kys")
    result = analyze_code(str(target_code), persona=persona)

    if result.get("score") is not None:
        scan_record = {
            "timestamp": time.time(),
            "score": result["score"],
            "vulnerabilities_found": result["vulnerabilities_found"],
            "rules": [f.get("kural", "") for f in result.get("findings", [])],
            "level": result["level"],
        }
        scans_file = DATA_DIR / "rea_scans.json"
        try:
            records = []
            if scans_file.exists():
                records = json.loads(scans_file.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                records = []
            records.append(scan_record)
            scans_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("REA tarama kaydı yazılamadı: %s", e)

    return result

@app.get("/api/rea/history", dependencies=[Depends(verify_auth)])
async def rea_history():
    """Gerçek REA geçmişi (Kural 1 uyarınca sahte mock rakamlar kaldırılmıştır)."""
    scans_file = DATA_DIR / "rea_scans.json"
    if scans_file.exists():
        try:
            records = json.loads(scans_file.read_text(encoding="utf-8"))
            if isinstance(records, list) and records:
                toplam = len(records)
                ort = round(sum(r.get("score", 100) for r in records) / toplam, 1)
                rule_counts: Dict[str, int] = {}
                for rec in records:
                    for rname in (rec.get("rules") or []):
                        rule_counts[rname] = rule_counts.get(rname, 0) + 1
                tekrar = sum(1 for c in rule_counts.values() if c >= 2)
                level = "A+ (Mükemmel)" if ort >= 90 else ("B (Orta)" if ort >= 70 else "Kritik")
                return {
                    "toplam_tarama": toplam,
                    "ort_skor": ort,
                    "tekrarlayan_zafiyet_sayisi": tekrar,
                    "guvenlik_seviyesi": level,
                }
        except Exception:
            pass
    return {
        "toplam_tarama": 0,
        "ort_skor": None,
        "tekrarlayan_zafiyet_sayisi": 0,
        "guvenlik_seviyesi": "Veri Yok (Tarama Yapılmadı)",
    }

@app.get("/api/push/vapid_public_key")
async def push_vapid():
    """VAPID anahtarı yapılandırılmadıysa sahte anahtar dağıtılmaz."""
    return {
        "public_key": None,
        "configured": False,
        "message": "Web Push VAPID anahtarı yapılandırılmadı (VAPID_PUBLIC_KEY env yok).",
    }

@app.post("/api/push/subscribe", dependencies=[Depends(verify_auth)])
async def push_sub():
    raise HTTPException(
        status_code=501,
        detail="Web Push abonelikleri yapılandırılmadı (VAPID anahtarları tanımlı değil).",
    )

@app.post("/api/tunnel/setup_domain", dependencies=[Depends(verify_auth)])
async def tunnel_setup():
    raise HTTPException(
        status_code=501,
        detail="Tünel/alan adı otomasyonu yapılandırılmadı; sahte başarı döndürülmez.",
    )

# -----------------------------------------------------------------------------
# 9b. MAC FABRİKA PORT-443 HTTPS KÖPRÜSÜ (Core/gateway/vpn_port443_bridge.py)
# -----------------------------------------------------------------------------
def _valid_bridge_secrets() -> List[str]:
    found: List[str] = []
    for k in (
        "BRIDGE_SECRET",
        "ALANADISIFRE",
        "alanadisifre",
        "FABRIKA_GATEWAY_PASSWORD",
        "GATEWAY_PASSWORD",
        "alansifre",
        "GATEWAY_PIN",
        "FABRIKA_GATEWAY_PIN",
    ):
        val = get_secret_from_env(k)
        if val and val not in DISALLOWED_PINS and val not in found:
            found.append(val)
    return found

@app.post("/api/bridge/poll")
async def mac_bridge_poll(
    req: Request,
    x_bridge_secret: Optional[str] = Header(None, alias="X-Fabrika-Bridge-Secret"),
):
    """Mac'teki `VPNPort443Bridge` her 2 sn'de bir bu ucu arar; kalp atışı & yanıt bırakır, görev alır."""
    from mac_bridge import bridge_hub

    secrets_list = _valid_bridge_secrets()
    if not secrets_list:
        raise HTTPException(status_code=503, detail="Bridge secret sunucuda yapılandırılmadı.")
    if not bridge_hub.verify_secret(x_bridge_secret, secrets_list):
        raise HTTPException(status_code=401, detail="Geçersiz X-Fabrika-Bridge-Secret.")

    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    tasks = bridge_hub.handle_poll(
        stats=body.get("stats") if isinstance(body.get("stats"), dict) else None,
        replies=body.get("replies") if isinstance(body.get("replies"), list) else None,
        desktop_state=body.get("desktop_state") if isinstance(body.get("desktop_state"), dict) else None,
    )
    fresh_state = bridge_hub.pop_dirty_desktop_state()
    if fresh_state is not None and manager.active_connections:
        await manager.broadcast(json.dumps({"type": "desktop_sync", "state": fresh_state}, ensure_ascii=False))
    return {"ok": True, "tasks": tasks}

@app.post("/api/bridge/action", dependencies=[Depends(verify_auth)])
async def mac_bridge_action(req: Request):
    """Uzaktan UI eylemini (sağ panel, log/XAI, söz kes, soru kartı) Mac Fabrika'ya iletir."""
    from mac_bridge import bridge_hub

    try:
        body = await req.json()
    except Exception:
        body = {}
    action = str(body.get("action") or "").strip()
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    res = bridge_hub.enqueue_ui_action(action, payload)
    return {"success": bool(res.get("ok")), **res}

@app.get("/api/bridge/status", dependencies=[Depends(verify_auth)])
async def mac_bridge_status():
    """Mac Fabrika bağlantısının anlık ve dürüst durumunu döner."""
    from mac_bridge import bridge_hub

    return {"success": True, **bridge_hub.get_status()}

@app.post("/api/bridge/command", dependencies=[Depends(verify_auth)])
async def mac_bridge_command(req: Request):
    """Komutu canlı Mac Fabrika köprüsüne iletir; Mac çevrimdışıysa bekletmeden dürüstçe bildirir."""
    from mac_bridge import bridge_hub

    try:
        body = await req.json()
    except Exception:
        body = {}
    text = str(body.get("text") or body.get("command") or "").strip()
    timeout_sec = max(2.0, min(25.0, float(body.get("timeout_sec") or 14.0)))
    res = await run_in_threadpool(lambda: bridge_hub.enqueue_and_wait(text, timeout_sec=timeout_sec))
    return {"success": bool(res.get("ok")), **res}

# -----------------------------------------------------------------------------
# 10. WEBSOCKET CANLI CHAT (MAC KÖPRÜSÜNE BAĞLI — ÇEVRİMDIŞIYSA DÜRÜST BİLDİRİM)
# -----------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, token: Optional[str] = Query(None)):
    from mac_bridge import bridge_hub

    if not token or not is_session_valid(token):
        await websocket.close(code=4401)
        return

    await manager.connect(websocket)
    try:
        mac_on = bridge_hub.is_online()
        desk_state = bridge_hub.get_desktop_state()
        desk_open = bool(desk_state and desk_state.get("desktop_app_open"))
        welcome = {
            "type": "system_alert",
            "sender": "Mac Fabrika Köprüsü",
            "text": (
                "🟢 Mac Masaüstü Fabrika birebir canlı bağlı! Yazdığınız ve yaptığınız her şey doğrudan Mac'teki Fabrika'da çalışır."
                if (mac_on and desk_open)
                else (
                    "🟢 Mac Fabrika köprüsü canlı! Komutlarınız doğrudan bilgisayarınızdaki Fabrika'da çalıştırılır."
                    if mac_on
                    else "⚪ Mac Fabrika şu an çevrimdışı. Bilgisayarınızda Fabrika açıldığında otomatik bağlanır."
                )
            ),
        }
        await websocket.send_text(json.dumps(welcome, ensure_ascii=False))
        if desk_state is not None:
            await websocket.send_text(json.dumps({"type": "desktop_sync", "state": desk_state}, ensure_ascii=False))

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except Exception:
                msg = {"type": "user_message", "text": str(data)}

            if isinstance(msg, dict) and msg.get("type") == "ui_action":
                act = str(msg.get("action") or "").strip()
                pay = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
                ack = bridge_hub.enqueue_ui_action(act, pay)
                await websocket.send_text(json.dumps({"type": "ui_action_ack", **ack}, ensure_ascii=False))
                continue

            user_text = str(msg.get("text", "") if isinstance(msg, dict) else data).strip()
            if not user_text:
                continue

            res = await run_in_threadpool(lambda: bridge_hub.enqueue_and_wait(user_text, timeout_sec=14.0))
            if res.get("ok") and res.get("accepted_desktop"):
                reply = {
                    "type": "desktop_ack",
                    "sender": res.get("sender") or "Mac Fabrika",
                    "text": user_text,
                }
            elif res.get("ok"):
                reply = {
                    "type": "agent_reply",
                    "sender": res.get("sender") or "Mac Fabrika",
                    "text": res.get("text") or "",
                    "action": res.get("action"),
                    "media": res.get("media"),
                }
            else:
                reply = {
                    "type": "system_alert",
                    "sender": res.get("sender") or "Mac Köprüsü",
                    "text": res.get("text") or "Mac Fabrika şu an çevrimdışı.",
                }
            await websocket.send_text(json.dumps(reply, ensure_ascii=False))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket hatası: %s", e)
        manager.disconnect(websocket)

# -----------------------------------------------------------------------------
# 11. ÇOK KATMANLI AKILLI STATİK VE SPA DÜŞÜŞ (FALLBACK) YÖNLENDİRMESİ
# -----------------------------------------------------------------------------
_PUBLIC_STATIC_EXT = {".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff2", ".ttf", ".ipynb"}

@app.api_route("/{full_path:path}", methods=["GET", "HEAD"])
async def catch_all_router(full_path: str):
    """
    Güvenli statik/SPA yönlendiricisi:
    - `media/`, gizli dosyalar ve hassas uzantılar kesinlikle engellenir.
    - İzinli statik varlıklar ve `.html` sayfaları sunulur; yoksa index.html döner.
    """
    raw = (full_path or "").lstrip("/")
    if not raw:
        return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)

    low = raw.lower()
    if low.startswith("media/") or low.startswith("static/media") or "/media/" in low or low.startswith(".") or "/." in low:
        return JSONResponse(status_code=403, content={"detail": "Bu kaynağa doğrudan erişim yasaktır."})

    try:
        clean_name = Path(raw).name if "/" not in raw else raw
        target = (STATIC_DIR / clean_name).resolve()
        if not target.is_relative_to(STATIC_DIR.resolve()):
            return JSONResponse(status_code=403, content={"detail": "Dizin sınırları dışına erişim engellendi."})
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Geçersiz dosya yolu."})

    if target.is_file():
        if target.name in ("manifest.json", "surum.json") or target.suffix.lower() in _PUBLIC_STATIC_EXT:
            return FileResponse(target, headers=_NO_CACHE)
        return JSONResponse(status_code=403, content={"detail": "Bu dosya türü doğrudan sunulamaz."})

    target_html = (STATIC_DIR / f"{clean_name}.html").resolve()
    if target_html.is_file() and target_html.is_relative_to(STATIC_DIR.resolve()):
        return FileResponse(target_html, headers=_NO_CACHE)

    return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
