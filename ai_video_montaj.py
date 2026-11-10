# -*- coding: utf-8 -*-
"""ai_video_montaj.py — GERÇEK YZ görsellerinden sinematik video montajı.

NEDEN BU MODÜL VAR (2026-11-10 ikinci tur):
Kurucu haklı olarak şikâyet etti: *"prompt girdiğimde sadece o promptu okuyor,
neden video üretimi yok"*. Ölçüm bunu doğruladı: `video_render.py` prompt metnini
kareye basan TEK bir statik kart üretiyordu (2.0s / 3.5s / 4.8s kareleri birebir
aynı, sahne değişimi 0). Yani "video" değil, zoom'lu bir afişti.

Bu modül GERÇEK difüzyon üretimi yapar:
  1. **FLUX.1-schnell** (HF Space, `gradio_client`) ile prompt'tan N adet
     sinematik sahne görseli üretilir — gerçek YZ difüzyon çıktısı.
  2. Her sahne ffmpeg `zoompan` ile Ken Burns hareketine sokulur.
  3. Sahneler `xfade` ile yumuşak geçişlerle birleştirilir.

Dürüstlük (Kural 1): bu bir **görsel montajdır** — kareler arası fizik
sürekliliği yoktur (Wan/LTX gibi video difüzyonu değil). Çıktı etiketlenir:
`kaynak = "flux_montaj"`. Gerçek video difüzyonu için HF ZeroGPU kotası gerekir;
kota yoksa bu hat devreye girer ve bunu raporda açıkça söyler.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("YusasufhinCockpit.AIVideoMontaj")

KOK = Path(__file__).resolve().parent
FLUX_SPACE = "black-forest-labs/FLUX.1-schnell"
SAHNE_SAYISI = 3
SAHNE_SURE_SN = 3.0
GECIS_SN = 0.6
FLUX_ZAMAN_ASIMI_SN = 120


def _hf_token() -> Optional[str]:
    """HF token: env → Persona/.env → KovaLab/.env sırasıyla aranır."""
    aday = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if aday:
        return aday.strip()
    for dosya in (
        KOK.parent / "Video_Otomasyon" / "KovaLab" / ".env",
        Path("/Users/yusufsahin/Desktop/Fabrika_Products/Video_Otomasyon/KovaLab/.env"),
        Path("/Users/yusufsahin/Desktop/PYTHON PROJECTS/Fabrika/Persona/.env"),
    ):
        try:
            for satir in dosya.read_text(encoding="utf-8").splitlines():
                if satir.strip().startswith(("HF_TOKEN=", "HUGGINGFACE_TOKEN=")):
                    return satir.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    return None


def tesis_durumu() -> Dict[str, Any]:
    """YZ video hattının canlı ortamda çalışabilirliğini teşhis eder.

    NEDEN: Render'da `HF_TOKEN` tanımlı değilse hat sessizce yedeğe düşüyordu
    ve kullanıcı nedenini göremiyordu ("YZ sahne üretilemedi" belirsizdi).
    Bu fonksiyon eksik olan tam adımı söyler.
    """
    durum: Dict[str, Any] = {
        "hf_token": False,
        "gradio_client": False,
        "pillow": False,
        "ffmpeg": False,
        "hazir": False,
        "eksikler": [],
    }

    durum["hf_token"] = bool(_hf_token())
    if not durum["hf_token"]:
        durum["eksikler"].append(
            "HF_TOKEN ortam değişkeni yok (Render → Environment → Add Environment Variable)"
        )

    try:
        import gradio_client  # noqa: F401

        durum["gradio_client"] = True
    except Exception:
        durum["eksikler"].append("gradio_client paketi kurulu değil (requirements.txt)")

    try:
        import PIL  # noqa: F401

        durum["pillow"] = True
    except Exception:
        durum["eksikler"].append("Pillow paketi kurulu değil (requirements.txt)")

    ff = _ffmpeg()
    try:
        r = subprocess.run([ff, "-version"], capture_output=True, timeout=15)
        durum["ffmpeg"] = r.returncode == 0
        durum["ffmpeg_yolu"] = ff
    except Exception:
        durum["ffmpeg"] = False
    if not durum["ffmpeg"]:
        durum["eksikler"].append("ffmpeg çalıştırılamıyor (imageio-ffmpeg kurulu mu?)")

    durum["hazir"] = not durum["eksikler"]
    return durum

    """Tek prompt'u sinematik sahne dizisine böler (geniş → detay → geniş)."""
    temel = prompt.strip().rstrip(".")
    kalip = [
        "cinematic wide establishing shot of {p}, dramatic lighting, ultra detailed, 8k, film still",
        "close up detail shot of {p}, shallow depth of field, macro texture, cinematic color grading",
        "epic aerial view of {p}, atmospheric haze, golden hour, cinematic composition",
        "medium shot of {p}, dynamic angle, professional cinematography, vivid colors",
        "atmospheric detail of {p}, soft light rays, moody cinematic tone, high detail",
    ]
    return [kalip[i % len(kalip)].format(p=temel) for i in range(adet)]


def _ffmpeg() -> str:
    aday = shutil.which("ffmpeg")
    if aday:
        return aday
    for sabit in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.path.isfile(sabit):
            return sabit
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def sahneleri_uret(prompt: str, adet: int, genislik: int, yukseklik: int,
                   log=None) -> List[Path]:
    """FLUX.1-schnell ile gerçek YZ sahne görselleri üretir.

    Döner: üretilen PNG yolları (başarısız sahne atlanır).
    """
    def _log(m: str) -> None:
        logger.info(m)
        if log:
            try:
                log(m)
            except Exception:
                pass

    token = _hf_token()
    if not token:
        _log("⚠️ HF_TOKEN yok — gerçek YZ sahne üretimi yapılamaz")
        return []

    try:
        from gradio_client import Client
    except Exception as e:
        _log(f"⚠️ gradio_client yok: {e}")
        return []

    try:
        from PIL import Image
    except Exception as e:
        _log(f"⚠️ Pillow yok: {e}")
        return []

    os.environ["HF_TOKEN"] = token
    gecici = Path(tempfile.mkdtemp(prefix="ai_sahne_"))
    yollar: List[Path] = []

    try:
        istemci = Client(FLUX_SPACE, verbose=False, token=token)
    except Exception as e:
        _log(f"⚠️ FLUX Space'e bağlanılamadı: {str(e)[:160]}")
        return []

    # FLUX 1024x576 gibi 16:9 oranları destekler; hedefe en yakın olanı seç
    flux_w, flux_h = (1024, 576) if genislik >= yukseklik else (576, 1024)

    for i, sahne_prompt in enumerate(_sahne_promptlari(prompt, adet), 1):
        try:
            _log(f"🎨 Sahne {i}/{adet} — FLUX.1-schnell difüzyon…")
            sonuc = istemci.predict(
                prompt=sahne_prompt,
                seed=42 + i,
                randomize_seed=True,
                width=flux_w,
                height=flux_h,
                num_inference_steps=4,
                api_name="/infer",
            )
            kaynak = sonuc[0] if isinstance(sonuc, (list, tuple)) else sonuc
            hedef = gecici / f"sahne_{i}.png"
            Image.open(kaynak).convert("RGB").resize(
                (genislik, yukseklik), Image.LANCZOS
            ).save(hedef, "PNG")
            yollar.append(hedef)
            _log(f"   ✅ Sahne {i} hazır ({hedef.stat().st_size // 1024} KB)")
        except Exception as e:
            _log(f"   ⚠️ Sahne {i} üretilemedi: {str(e)[:140]}")

    return yollar



def _sahne_video(sahne_png: Path, cikti: Path, genislik: int, yukseklik: int,
                 sure_sn: float, zoom_in: bool = True) -> bool:
    """Tek sahneyi Ken Burns (zoompan) hareketiyle MP4'e çevirir.

    NOT: `zoompan` filtresinde `d=90` yazmak her giriş karesini 90 kez
    çoğaltır → 274 saniyelik dosya üretir (2026-11-10'da yaşandı). Bu yüzden
    `d=1` kullanılır: her giriş karesi tam bir çıkış karesi olur, süreyi
    `-frames:v` belirler.
    """
    kare = int(sure_sn * 30)
    if zoom_in:
        z_ifade = "min(zoom+0.0015,1.18)"
    else:
        z_ifade = "if(eq(on,1),1.18,max(zoom-0.0015,1.0))"

    cmd = [
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", "30", "-t", f"{sure_sn:.3f}", "-i", str(sahne_png),
        "-vf", (
            f"scale={int(genislik * 1.25)}:{int(yukseklik * 1.25)},"
            f"zoompan=z='{z_ifade}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={genislik}x{yukseklik}:fps=30,setsar=1,format=yuv420p"
        ),
        "-frames:v", str(kare),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        str(cikti),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        return r.returncode == 0 and cikti.is_file() and cikti.stat().st_size > 5000
    except Exception as e:
        logger.warning("[AIVideoMontaj] Sahne render hatası: %s", e)
        return False


def montaj_birlestir(sahne_mp4leri: List[Path], hedef: Path,
                     gecis_sn: float = GECIS_SN, sure_sn: float = SAHNE_SURE_SN) -> bool:
    """Sahneleri `xfade` yumuşak geçişlerle birleştirir."""
    if not sahne_mp4leri:
        return False
    if len(sahne_mp4leri) == 1:
        shutil.copy2(sahne_mp4leri[0], hedef)
        return True

    cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    for v in sahne_mp4leri:
        cmd += ["-i", str(v)]

    filtre = ""
    onceki = "[0:v]"
    offset = sure_sn - gecis_sn
    for i in range(1, len(sahne_mp4leri)):
        etiket = f"[x{i}]"
        filtre += (
            f"{onceki}[{i}:v]xfade=transition=fade:duration={gecis_sn}:"
            f"offset={offset:.3f}{etiket};"
        )
        onceki = etiket
        offset += sure_sn - gecis_sn
    filtre = filtre.rstrip(";")

    cmd += [
        "-filter_complex", filtre,
        "-map", onceki,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(hedef),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            logger.warning("[AIVideoMontaj] Birleştirme hatası: %s", (r.stderr or "")[-300:])
            return False
        return hedef.is_file() and hedef.stat().st_size > 20000
    except Exception as e:
        logger.warning("[AIVideoMontaj] Birleştirme istisnası: %s", e)


def ai_video_uret(
    hedef_mp4: Path,
    prompt: str,
    genislik: int,
    yukseklik: int,
    sahne_sayisi: int = SAHNE_SAYISI,
    sahne_sure_sn: float = SAHNE_SURE_SN,
    ses_yolu: Optional[Path] = None,
    log=None,
) -> Dict[str, Any]:
    """Prompt'tan GERÇEK YZ görselleri üretip sinematik video montajı yapar.

    Döner: {"basarili", "yol", "boyut", "sahne", "kaynak", "hata"}
    """
    def _log(m: str) -> None:
        logger.info(m)
        if log:
            try:
                log(m)
            except Exception:
                pass

    hedef_mp4 = Path(hedef_mp4)
    hedef_mp4.parent.mkdir(parents=True, exist_ok=True)
    baslangic = time.time()

    _log(f"🎬 Gerçek YZ video hattı: {sahne_sayisi} sahne, {genislik}x{yukseklik}")

    sahneler = sahneleri_uret(prompt, sahne_sayisi, genislik, yukseklik, log=_log)
    if not sahneler:
        tesis = tesis_durumu()
        neden = "; ".join(tesis.get("eksikler") or ["FLUX Space erişilemedi (kota/ağ)"])
        return {
            "basarili": False, "yol": None, "boyut": 0, "sahne": 0,
            "kaynak": "flux_montaj",
            "hata": f"YZ sahne üretilemedi → {neden}",
            "tesis": tesis,
        }


    gecici = Path(tempfile.mkdtemp(prefix="ai_montaj_"))
    parcalar: List[Path] = []
    for i, png in enumerate(sahneler):
        parca = gecici / f"p{i}.mp4"
        if _sahne_video(png, parca, genislik, yukseklik, sahne_sure_sn,
                        zoom_in=(i % 2 == 0)):
            parcalar.append(parca)
            _log(f"   ✅ Sahne {i + 1} hareketlendirildi")

    if not parcalar:
        return {
            "basarili": False, "yol": None, "boyut": 0, "sahne": 0,
            "kaynak": "flux_montaj", "hata": "Sahne render edilemedi",
        }

    sessiz = gecici / "sessiz.mp4"
    if not montaj_birlestir(parcalar, sessiz, gecis_sn=GECIS_SN, sure_sn=sahne_sure_sn):
        return {
            "basarili": False, "yol": None, "boyut": 0, "sahne": len(parcalar),
            "kaynak": "flux_montaj", "hata": "Montaj birleştirme başarısız",
        }

    son = hedef_mp4
    if ses_yolu is not None and Path(ses_yolu).is_file() and Path(ses_yolu).stat().st_size > 500:
        cmd = [
            _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(sessiz), "-i", str(ses_yolu),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart", str(son),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                shutil.copy2(sessiz, son)
        except Exception:
            shutil.copy2(sessiz, son)
    else:
        shutil.copy2(sessiz, son)

    try:
        from video_render import mp4_gecerli_mi

        gecerli, neden = mp4_gecerli_mi(son)
    except Exception:
        gecerli, neden = son.is_file(), "doğrulama atlandı"

    if not gecerli:
        return {
            "basarili": False, "yol": None, "boyut": 0, "sahne": len(parcalar),
            "kaynak": "flux_montaj", "hata": f"doğrulama başarısız: {neden}",
        }

    shutil.rmtree(gecici, ignore_errors=True)

    boyut = son.stat().st_size
    _log(f"✅ Gerçek YZ montaj hazır: {len(parcalar)} sahne, {boyut // 1024} KB, "
         f"{round(time.time() - baslangic, 1)} sn")
    return {
        "basarili": True, "yol": son, "boyut": boyut, "sahne": len(parcalar),
        "kaynak": "flux_montaj", "hata": None,
    }

