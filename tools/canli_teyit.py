#!/usr/bin/env python3
"""canli_teyit.py — Canlı sitenin YENİ kodu çalıştırdığını ölçer ve teyit eder.

NEDEN: 2026-11-10'da video render hattı onarıldı (boş/oynatılamaz video kök
nedeni: 15 sn ffmpeg timeout + düz renk video). Kod yerelde uçtan uca
doğrulandı, ancak Render deploy'u yapılmadan canlı eski kodu çalıştırmaya
devam ediyor. Bu araç deploy'un gerçekleşip gerçekleşmediğini KANITLA ölçer.

Kullanım:
    python3 tools/canli_teyit.py                 # tek seferlik durum raporu
    python3 tools/canli_teyit.py --izle 1800     # deploy'u bekle (sn)

Deploy dedektörü: `/static/fonts/DejaVuSans.ttf` yalnız yeni commit'te vardır.
Eski sürümde 404, yeni sürümde 200 döner.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TABAN = "https://yusasufhin.com"
# Deploy dedektörü: `/static/surum.json` yalnız yeni commit'lerde güncellenir.
# (Eski dedektör `fonts/DejaVuSans.ttf` idi; o dosya bir kez deploy edildikten
#  sonra hep 200 döndüğü için yeni sürümleri ayırt edemiyordu.)
SURUM_YOLU = "/static/surum.json"
BEKLENEN_SURUM = "2026.11.17-hyperframes-v18"
RAPOR = Path(__file__).resolve().parent.parent / "data" / "canli_teyit_rapor.txt"



def _istek(yol: str, veri: dict | None = None, token: str | None = None,
           zaman_asimi: int = 60) -> tuple[int, bytes]:
    url = TABAN + yol
    govde = None
    basliklar = {"Accept": "*/*"}
    if veri is not None:
        govde = json.dumps(veri).encode("utf-8")
        basliklar["Content-Type"] = "application/json"
    if token:
        basliklar["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=govde, headers=basliklar,
                                 method="POST" if govde else "GET")
    try:
        with urllib.request.urlopen(req, timeout=zaman_asimi) as y:
            return y.status, y.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return 0, str(e).encode("utf-8")


def deploy_var_mi() -> bool:
    """Yeni commit canlıda mı? (`static/surum.json` beklenen sürümü mü yayınlıyor)"""
    kod, govde = _istek(SURUM_YOLU, zaman_asimi=25)
    if kod != 200:
        return False
    try:
        return json.loads(govde).get("surum") == BEKLENEN_SURUM
    except Exception:
        return False



def _env_oku(anahtar: str) -> str | None:
    """Ortam değişkeni veya `Persona/.env` içinden anahtar okur."""
    val = os.environ.get(anahtar)
    if val and val.strip():
        return val.strip().strip('"').strip("'")
    adaylar = [
        Path("/Users/yusufsahin/Desktop/PYTHON PROJECTS/Fabrika/Persona/.env"),
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in adaylar:
        try:
            for satir in p.read_text(encoding="utf-8").splitlines():
                k, _, v = satir.partition("=")
                if k.strip().lower() == anahtar.lower() and not satir.strip().startswith("#"):
                    temiz = v.strip().strip('"').strip("'")
                    if temiz:
                        return temiz
        except Exception:
            continue
    return None


def pin_bul() -> str | None:
    """Persona/.env içinden `alansifre` veya `GATEWAY_PIN` okur (yalnız yerel kullanım)."""
    return _env_oku("GATEWAY_PIN")


def _mp4_dogrula(veri: bytes) -> str:
    """İndirilen baytların gerçek MP4 olup olmadığını atomlardan doğrular."""
    if len(veri) < 20 * 1024:
        return f"BAŞARISIZ: çok küçük ({len(veri)} bayt)"
    turler = set()
    ofs = 0
    while ofs + 8 <= len(veri):
        boyut = int.from_bytes(veri[ofs:ofs + 4], "big")
        tur = veri[ofs + 4:ofs + 8]
        baslik = 8
        if boyut == 1:
            boyut = int.from_bytes(veri[ofs + 8:ofs + 16], "big")
            baslik = 16
        elif boyut == 0:
            boyut = len(veri) - ofs
        if boyut < baslik:
            break
        turler.add(tur)
        ofs += boyut
    eksik = [t.decode(errors="replace") for t in (b"ftyp", b"moov", b"mdat") if t not in turler]
    if eksik:
        return f"BAŞARISIZ: eksik atom {eksik} (oynatılamaz)"
    return f"BAŞARILI: ftyp+moov+mdat tam, {len(veri)} bayt"


def rapor_yaz(satirlar: list[str]) -> None:
    metin = "\n".join(satirlar)
    print(metin)
    try:
        RAPOR.write_text(metin + "\n", encoding="utf-8")
    except Exception:
        pass



def tam_teyit() -> int:
    """Deploy sonrası: canlı galeri + gerçek üretim + indirme doğrulaması."""
    satirlar = [f"=== CANLI TEYİT {time.strftime('%Y-%m-%d %H:%M:%S')} ==="]

    kod, govde = _istek("/api/lab/history")
    satirlar.append(f"galeri HTTP {kod}")
    if kod == 200:
        try:
            d = json.loads(govde)
            satirlar.append(f"galeri kayıt: {d.get('count')}")
            for i in (d.get("items") or [])[:5]:
                satirlar.append(f"  {i.get('id')} {i.get('size_kb')} KB {i.get('status')}")
        except Exception as e:
            satirlar.append(f"galeri okunamadı: {e}")

    token = None
    for pw_key in ("alansifre", "alanadisifre", "FABRIKA_GATEWAY_PASSWORD"):
        pw = _env_oku(pw_key)
        if not pw:
            continue
        kod, govde = _istek("/api/auth/login", {"password": pw})
        if kod == 200:
            token = json.loads(govde).get("token") or json.loads(govde).get("access_token")
            if token:
                break
    if not token:
        pin = pin_bul()
        if pin:
            kod, govde = _istek("/api/auth/verify_pin", {"pin": pin})
            if kod == 200:
                token = json.loads(govde).get("token")
    if not token:
        satirlar.append("login BAŞARISIZ (alansifre / GATEWAY_PIN)")
        rapor_yaz(satirlar)
        return 1
    satirlar.append("login OK")

    kod, govde = _istek("/api/studio/video/generate", {
        "channel": "Astroloji_Kova",
        "prompt": "Kova burcu haftalik analizi: gezegen kavusumlari ve sezgisel uyanis donemi",
        "workflow": "hyperframes_motion",
        "execution_mode": "auto",
    }, token=token, zaman_asimi=180)
    satirlar.append(f"üretim HTTP {kod}")
    if kod != 200:
        satirlar.append(f"  hata: {govde[:200]!r}")
        rapor_yaz(satirlar)
        return 1

    task = json.loads(govde).get("task") or {}
    art = task.get("artifacts") or {}
    satirlar.append(f"  status  : {task.get('status')}")
    satirlar.append(f"  kaynak  : {art.get('kaynak')}  (flux_montaj = gerçek YZ sahne)")
    satirlar.append(f"  sahne   : {art.get('sahne_sayisi')}")
    satirlar.append(f"  boyut   : {art.get('file_size_bytes')} b")
    satirlar.append(f"  çözünür : {art.get('resolution')} @ {art.get('duration_sec')} sn")
    satirlar.append(f"  log     : {art.get('render_log')}")
    if art.get("ai_hata"):
        satirlar.append(f"  AI HATA : {art.get('ai_hata')}")


    url = task.get("output_url")
    if not url:
        satirlar.append("  output_url YOK")
        rapor_yaz(satirlar)
        return 1

    kod, veri = _istek(url, token=token, zaman_asimi=120)
    satirlar.append(f"indirme HTTP {kod} ({len(veri)} bayt)")
    satirlar.append("MP4 doğrulama: " + _mp4_dogrula(veri))

    import tempfile
    with tempfile.TemporaryDirectory(prefix="canli_teyit_") as td:
        hedef = Path(td) / "canli_teyit_video.mp4"
        hedef.write_bytes(veri)
        try:
            cikti = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration,size,bit_rate",
                 "-show_entries", "stream=codec_name,width,height,nb_frames",
                 "-of", "default=nw=1", str(hedef)],
                capture_output=True, text=True, timeout=60,
            )
            satirlar.append("ffprobe:\n" + (cikti.stdout or cikti.stderr).strip())
        except Exception as e:
            satirlar.append(f"ffprobe çalıştırılamadı: {e}")

    rapor_yaz(satirlar)
    return 0 if "BAŞARILI" in "\n".join(satirlar) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Canlı video hattı teyidi")
    ap.add_argument("--izle", type=int, default=0,
                    help="Deploy'u bekle: en fazla bu kadar saniye poll et")
    ap.add_argument("--aralik", type=int, default=20, help="Poll aralığı (sn)")
    args = ap.parse_args()

    if args.izle <= 0:
        var = deploy_var_mi()
        print(f"deploy: {'VAR (yeni kod canlı)' if var else 'YOK (eski kod canlı)'}")
        return tam_teyit() if var else 2

    bitis = time.time() + args.izle
    while time.time() < bitis:
        if deploy_var_mi():
            print(f"[{time.strftime('%H:%M:%S')}] DEPLOY ALGILANDI — teyit başlıyor")
            return tam_teyit()
        print(f"[{time.strftime('%H:%M:%S')}] deploy yok, bekleniyor…")
        time.sleep(args.aralik)
    print("Süre doldu — deploy hâlâ yok.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
